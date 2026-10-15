"""
Assembles the final research report.

Only the narrative prose sections come from the LLM (via
ReportGenerationAgent), and only from claims already verified in Phase 5.
Every other section is built directly from database rows. Citation
numbers are assigned here, in code, in a fixed order — the LLM is handed
those exact numbers to use and cannot introduce a citation that doesn't
correspond to a real evidence_claim/evidence_link pair.
"""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.report_generation import ReportGenerationAgent
from app.integrations.llm import LLMClient
from app.models.evidence import Conflict, EvidenceClaim, ResearchReport, Source, Study
from app.models.research import ResearchQuery
from app.schemas.report import ReportGenerationInput, VerifiedClaimForReport

VERIFIED_STATUSES = ("SUPPORTED", "PARTIALLY_SUPPORTED")


async def _load_report_context(db: AsyncSession, research_job_id: UUID):
    studies_result = await db.execute(
        select(Study)
        .options(selectinload(Study.source), selectinload(Study.study_findings))
        .join(Source, Source.id == Study.source_id)
        .where(Source.research_job_id == research_job_id)
    )
    studies = studies_result.scalars().all()

    claims_result = await db.execute(
        select(EvidenceClaim)
        .options(selectinload(EvidenceClaim.evidence_links))
        .where(EvidenceClaim.research_job_id == research_job_id)
        .order_by(EvidenceClaim.created_at.asc())
    )
    claims = claims_result.scalars().all()

    conflicts_result = await db.execute(
        select(Conflict).where(Conflict.research_job_id == research_job_id).order_by(Conflict.created_at.asc())
    )
    conflicts = conflicts_result.scalars().all()

    return studies, claims, conflicts


def _study_title_for_claim(claim: EvidenceClaim, studies_by_id: dict) -> str:
    for link in claim.evidence_links:
        if link.study_id and link.study_id in studies_by_id:
            return studies_by_id[link.study_id].source.title
    return "Unknown study"


async def generate_report(
    db: AsyncSession, research_job_id: UUID, research_query: ResearchQuery, llm: LLMClient, evidence_grade: str
) -> ResearchReport:
    studies, claims, conflicts = await _load_report_context(db, research_job_id)
    studies_by_id = {s.id: s for s in studies}

    verified_claims = [c for c in claims if c.verification_status in VERIFIED_STATUSES]

    citation_entries = []
    claims_for_llm = []
    for i, claim in enumerate(verified_claims, start=1):
        study_title = _study_title_for_claim(claim, studies_by_id)
        study = next(
            (studies_by_id[link.study_id] for link in claim.evidence_links if link.study_id in studies_by_id), None
        )
        excerpt = next((link.excerpt for link in claim.evidence_links if link.excerpt), None)
        citation_entries.append(
            {
                "number": i,
                "claim_text": claim.claim_text,
                "verification_status": claim.verification_status,
                "confidence": float(claim.confidence) if claim.confidence is not None else None,
                "excerpt": excerpt,
                "study_id": str(study.id) if study else None,
                "study_title": study_title,
                "source_url": study.source.url if study else None,
                "origin": study.source.origin if study else None,
            }
        )
        claims_for_llm.append(
            VerifiedClaimForReport(claim_text=claim.claim_text, study_title=study_title, citation_number=i)
        )

    agent_input = ReportGenerationInput(
        research_question=research_query.raw_question,
        population=research_query.population,
        intervention=research_query.intervention,
        comparator=research_query.comparator,
        outcomes=list(research_query.outcomes) if research_query.outcomes else [],
        verified_claims=claims_for_llm,
        conflict_count=len(conflicts),
        evidence_grade=evidence_grade,
        studies_considered=len(studies),
    )

    agent = ReportGenerationAgent(llm)
    narrative = await agent.run(db, research_job_id, agent_input)

    studies_analyzed = [
        {
            "id": str(s.id),
            "title": s.source.title,
            "origin": s.source.origin,
            "source_type": s.source.source_type,
            "study_type": s.study_type,
            "conclusion": s.conclusion,
            "relevance_score": float(s.relevance_score) if s.relevance_score is not None else None,
        }
        for s in studies
    ]
    high_quality_evidence = [
        s for s in studies_analyzed
        if s["source_type"] in ("SYSTEMATIC_REVIEW", "META_ANALYSIS", "GUIDELINE", "OFFICIAL_MEDICAL_SOURCE")
    ]
    conflicting_evidence = [
        {
            "outcome": c.conflicting_outcome,
            "finding_a": c.finding_a,
            "finding_b": c.finding_b,
            "explanation": c.possible_explanation,
            "confidence": float(c.confidence) if c.confidence is not None else None,
        }
        for c in conflicts
    ]
    sources = [
        {
            "id": str(s.id),
            "title": s.source.title,
            "origin": s.source.origin,
            "url": s.source.url,
            "external_id": s.source.external_id,
            "publisher": s.source.publisher,
        }
        for s in studies
    ]

    sections = {
        "research_question": research_query.raw_question,
        "executive_summary": narrative.executive_summary,
        "search_methodology": (
            f"Searched PubMed, ClinicalTrials.gov, and web sources for evidence on this question. "
            f"{len(studies)} unique study/source record(s) were retrieved and analyzed after deduplication."
        ),
        "evidence_strength": evidence_grade,
        "key_findings": narrative.key_findings_narrative,
        "studies_analyzed": studies_analyzed,
        "high_quality_evidence": high_quality_evidence,
        "conflicting_evidence": conflicting_evidence,
        "evidence_gaps": narrative.evidence_gaps_narrative,
        "limitations": narrative.limitations_narrative,
        "conclusion": narrative.conclusion,
        "sources": sources,
    }

    report = ResearchReport(
        research_job_id=research_job_id,
        sections=sections,
        citations=citation_entries,
        evidence_grade=evidence_grade,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return report
