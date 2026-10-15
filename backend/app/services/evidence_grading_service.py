"""
Evidence Grading.

Deliberately deterministic and rule-based, not an LLM judgment call — the
spec explicitly requires "Do not assign STRONG simply because the LLM says
the evidence is strong." Every subscore below is computed from data already
in the database (source types, verified claim outcomes, conflicts,
relevance scores), and the final grade + a machine-readable breakdown of
every subscore is returned together so the grade is always explainable.

This is explicitly an AI-assisted evidence assessment, not an official
clinical guideline grading framework (not GRADE, not USPSTF).
"""
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.evidence import Conflict, EvidenceClaim, Source, Study

HIGH_QUALITY_SOURCE_TYPES = {"SYSTEMATIC_REVIEW", "META_ANALYSIS", "GUIDELINE", "OFFICIAL_MEDICAL_SOURCE"}
MEDIUM_QUALITY_SOURCE_TYPES = {"PRIMARY_STUDY", "CLINICAL_TRIAL"}


@dataclass
class GradingBreakdown:
    studies_considered: int = 0
    studies_with_real_content: int = 0
    source_quality_score: float = 0.0
    consistency_score: float = 0.0
    directness_score: float = 0.0
    verified_claims_score: float = 0.0
    conflict_count: int = 0
    total_claims: int = 0
    supported_claims: int = 0
    composite_score: float = 0.0
    grade: str = "INSUFFICIENT"
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "studies_considered": self.studies_considered,
            "studies_with_real_content": self.studies_with_real_content,
            "source_quality_score": round(self.source_quality_score, 3),
            "consistency_score": round(self.consistency_score, 3),
            "directness_score": round(self.directness_score, 3),
            "verified_claims_score": round(self.verified_claims_score, 3),
            "conflict_count": self.conflict_count,
            "total_claims": self.total_claims,
            "supported_claims": self.supported_claims,
            "composite_score": round(self.composite_score, 3),
            "grade": self.grade,
            "rationale": self.rationale,
            "methodology_note": (
                "AI-assisted evidence assessment based on source quality, consistency across "
                "studies, directness to the research question, and the share of extracted claims "
                "verified against source text. This is not an official clinical guideline grading "
                "framework (e.g. not GRADE or USPSTF)."
            ),
        }


def _source_quality_weight(source_type: str) -> float:
    if source_type in HIGH_QUALITY_SOURCE_TYPES:
        return 1.0
    if source_type in MEDIUM_QUALITY_SOURCE_TYPES:
        return 0.6
    return 0.2


async def compute_evidence_grade(db: AsyncSession, research_job_id: UUID) -> GradingBreakdown:
    breakdown = GradingBreakdown()

    studies_result = await db.execute(
        select(Study)
        .options(selectinload(Study.source), selectinload(Study.study_findings))
        .join(Source, Source.id == Study.source_id)
        .where(Source.research_job_id == research_job_id)
    )
    studies = studies_result.scalars().all()
    breakdown.studies_considered = len(studies)

    # A study has real content if Phase 4 actually produced structured
    # findings or a relevance score — both only ever get set when text was
    # available to analyze.
    studies_with_content = [s for s in studies if s.study_findings or s.relevance_score is not None]
    breakdown.studies_with_real_content = len(studies_with_content)

    if breakdown.studies_with_real_content == 0:
        breakdown.grade = "INSUFFICIENT"
        breakdown.rationale.append("No study had analyzable content, so evidence cannot be reliably graded.")
        return breakdown

    quality_weights = [_source_quality_weight(s.source.source_type) for s in studies_with_content]
    breakdown.source_quality_score = sum(quality_weights) / len(quality_weights)

    relevance_values = [
        float(s.relevance_score) if s.relevance_score is not None else 0.5 for s in studies_with_content
    ]
    breakdown.directness_score = sum(relevance_values) / len(relevance_values)

    conflicts_result = await db.execute(select(Conflict).where(Conflict.research_job_id == research_job_id))
    conflicts = conflicts_result.scalars().all()
    breakdown.conflict_count = len(conflicts)
    if breakdown.studies_with_real_content < 2:
        # Consistency across studies isn't a meaningful concept with only
        # one study to look at — treat it as neutral, not as "perfectly
        # consistent" just because there was nothing to disagree with.
        breakdown.consistency_score = 0.5
    else:
        penalty = min(1.0, breakdown.conflict_count / max(1, breakdown.studies_with_real_content))
        breakdown.consistency_score = max(0.0, 1.0 - penalty)

    claims_result = await db.execute(select(EvidenceClaim).where(EvidenceClaim.research_job_id == research_job_id))
    claims = claims_result.scalars().all()
    breakdown.total_claims = len(claims)
    breakdown.supported_claims = sum(
        1 for c in claims if c.verification_status in ("SUPPORTED", "PARTIALLY_SUPPORTED")
    )
    breakdown.verified_claims_score = (
        breakdown.supported_claims / breakdown.total_claims if breakdown.total_claims > 0 else 0.0
    )

    weights = {"source_quality": 0.25, "consistency": 0.25, "directness": 0.20, "verified_claims": 0.30}
    breakdown.composite_score = (
        weights["source_quality"] * breakdown.source_quality_score
        + weights["consistency"] * breakdown.consistency_score
        + weights["directness"] * breakdown.directness_score
        + weights["verified_claims"] * breakdown.verified_claims_score
    )

    if breakdown.total_claims == 0:
        breakdown.grade = "INSUFFICIENT"
        breakdown.rationale.append("No claims were extracted or verified, so confidence cannot be established.")
    elif breakdown.studies_with_real_content < 2 and breakdown.composite_score >= 0.75:
        breakdown.grade = "MODERATE"
        breakdown.rationale.append(
            "Composite score was high, but only one study had analyzable content; capped below STRONG."
        )
    elif breakdown.composite_score >= 0.75:
        breakdown.grade = "STRONG"
    elif breakdown.composite_score >= 0.5:
        breakdown.grade = "MODERATE"
    elif breakdown.composite_score >= 0.25:
        breakdown.grade = "LIMITED"
    else:
        breakdown.grade = "INSUFFICIENT"

    breakdown.rationale.append(
        f"{breakdown.studies_with_real_content} study(ies) with analyzable content; "
        f"source quality {breakdown.source_quality_score:.2f}, consistency {breakdown.consistency_score:.2f} "
        f"({breakdown.conflict_count} conflict(s) found), directness {breakdown.directness_score:.2f}, "
        f"{breakdown.supported_claims}/{breakdown.total_claims} claims verified as supported."
    )

    return breakdown
