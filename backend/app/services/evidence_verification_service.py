"""
Runs Claim Extraction then Evidence Verification for every study that had
real analyzable content in Phase 4. Each study — and each claim within a
study — is independent: one failing never blocks the others.
"""
import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.base import AgentExecutionError
from app.agents.claim_extraction import ClaimExtractionAgent
from app.agents.evidence_verification import EvidenceVerificationAgent
from app.integrations.llm import LLMClient
from app.models.evidence import Document, EvidenceClaim, EvidenceLink, Source, Study
from app.models.research import ResearchQuery
from app.schemas.evidence_verification import ClaimExtractionInput, EvidenceVerificationInput

logger = logging.getLogger("evidence_verification_service")


@dataclass
class EvidenceVerificationSummary:
    studies_considered: int = 0
    claims_extracted: int = 0
    claims_verified: int = 0
    extraction_failures: list[dict] = field(default_factory=list)
    verification_failures: list[dict] = field(default_factory=list)

    @property
    def any_failed(self) -> bool:
        return bool(self.extraction_failures or self.verification_failures)


async def run_evidence_verification(
    db: AsyncSession, research_job_id: UUID, research_query: ResearchQuery, llm: LLMClient
) -> EvidenceVerificationSummary:
    result = await db.execute(
        select(Study)
        .options(selectinload(Study.source), selectinload(Study.documents), selectinload(Study.study_findings))
        .join(Source, Source.id == Study.source_id)
        .where(Source.research_job_id == research_job_id)
    )
    studies = result.scalars().all()

    summary = EvidenceVerificationSummary()
    extraction_agent = ClaimExtractionAgent(llm)
    verification_agent = EvidenceVerificationAgent(llm)

    for study in studies:
        document: Document | None = study.documents[0] if study.documents else None
        if document is None:
            continue  # nothing to verify claims against for this study

        summary.studies_considered += 1
        source = study.source

        extraction_input = ClaimExtractionInput(
            study_id=str(study.id),
            study_title=source.title,
            research_question=research_query.raw_question,
            conclusion=study.conclusion,
            findings_summary=study.findings,
            study_findings=[
                {"outcome": f.outcome, "effect_direction": f.effect_direction, "effect_size": f.effect_size}
                for f in study.study_findings
            ],
        )

        try:
            extraction_output = await extraction_agent.run(db, research_job_id, extraction_input)
        except AgentExecutionError as exc:
            logger.warning("Claim extraction failed for study %s: %s", study.id, exc)
            summary.extraction_failures.append({"study_id": str(study.id), "title": source.title, "error": str(exc)})
            continue

        for claim_text in extraction_output.claims:
            summary.claims_extracted += 1
            verification_input = EvidenceVerificationInput(
                claim_text=claim_text, study_id=str(study.id), document_text=document.content
            )
            try:
                verification_output = await verification_agent.run(db, research_job_id, verification_input)
            except AgentExecutionError as exc:
                logger.warning("Evidence verification failed for a claim on study %s: %s", study.id, exc)
                summary.verification_failures.append(
                    {"study_id": str(study.id), "title": source.title, "claim": claim_text, "error": str(exc)}
                )
                continue

            claim_row = EvidenceClaim(
                research_job_id=research_job_id,
                claim_text=claim_text,
                verification_status=verification_output.verification_status.value,
                confidence=verification_output.confidence,
            )
            db.add(claim_row)
            await db.flush()

            db.add(
                EvidenceLink(
                    evidence_claim_id=claim_row.id,
                    study_id=study.id,
                    source_id=source.id,
                    excerpt=verification_output.supporting_excerpt,
                )
            )
            summary.claims_verified += 1
            await db.commit()

    return summary
