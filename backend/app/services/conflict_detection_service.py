"""
Conflict Detection.

Deliberately NOT an LLM agent: whether two studies' findings on the same
outcome disagree is a factual comparison of structured effect_direction
values (see the rule table in DIRECTION_CONFLICT below), not something
that benefits from — or should risk — an LLM's judgment call. This also
means conflict detection can never hallucinate a disagreement that isn't
actually in the data.

The "possible_explanation" for a real conflict is also rule-based: it only
ever cites a factor that's actually observably different between the two
studies' own metadata (population, study_type, follow_up, intervention,
sample_size). If nothing differs enough to explain it, the explanation is
the literal fallback string, never a fabricated clinical rationale.
"""
import re
from dataclasses import dataclass
from itertools import combinations
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.evidence import Conflict, Source, Study, StudyFinding

NOT_ESTABLISHED = "Reason for disagreement not established from available evidence."

# (direction_a, direction_b) -> confidence, order-independent (checked both ways).
# Anything not listed here (including any pair involving UNCLEAR, and same-
# direction pairs) is NOT a conflict — used conservatively per spec.
_CONFLICT_CONFIDENCE = {
    frozenset({"BENEFIT", "HARM"}): 0.9,
    frozenset({"BENEFIT", "NO_EFFECT"}): 0.6,
    frozenset({"HARM", "NO_EFFECT"}): 0.6,
}


@dataclass
class ConflictCandidate:
    study_a_id: UUID
    study_b_id: UUID
    conflicting_outcome: str
    finding_a: str
    finding_b: str
    possible_explanation: str
    confidence: float


def _normalize_outcome(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", "", text.lower())).strip()


def directions_conflict(direction_a: str, direction_b: str) -> float | None:
    """Returns a confidence score if these two directions represent a
    meaningful conflict, or None if they don't (same direction, or either
    is UNCLEAR — used conservatively, never a 'confirmed' conflict)."""
    if direction_a == direction_b:
        return None
    if direction_a == "UNCLEAR" or direction_b == "UNCLEAR":
        return None
    return _CONFLICT_CONFIDENCE.get(frozenset({direction_a, direction_b}))


def explain_difference(study_a: Study, study_b: Study) -> str:
    if (
        study_a.population
        and study_b.population
        and study_a.population.strip().lower() != study_b.population.strip().lower()
    ):
        return "population differences"
    if (
        study_a.study_type
        and study_b.study_type
        and study_a.study_type.strip().lower() != study_b.study_type.strip().lower()
    ):
        return "study design differences"
    if (
        study_a.follow_up
        and study_b.follow_up
        and study_a.follow_up.strip().lower() != study_b.follow_up.strip().lower()
    ):
        return "follow-up duration differences"
    if (
        study_a.intervention
        and study_b.intervention
        and study_a.intervention.strip().lower() != study_b.intervention.strip().lower()
    ):
        return "intervention differences"
    if study_a.sample_size and study_b.sample_size and study_a.sample_size > 0 and study_b.sample_size > 0:
        ratio = max(study_a.sample_size, study_b.sample_size) / max(1, min(study_a.sample_size, study_b.sample_size))
        if ratio >= 2.0:
            return "sample size differences (statistical uncertainty)"
    return NOT_ESTABLISHED


def detect_conflicts(studies: list[Study]) -> list[ConflictCandidate]:
    """Pure function: groups each study's findings by normalized outcome,
    then compares every pair of *different* studies that reported on the
    same outcome. A study is never compared against itself."""
    by_outcome: dict[str, list[tuple[Study, StudyFinding]]] = {}
    for study in studies:
        for finding in study.study_findings:
            key = _normalize_outcome(finding.outcome)
            by_outcome.setdefault(key, []).append((study, finding))

    candidates: list[ConflictCandidate] = []
    seen_pairs: set[tuple[str, str, str]] = set()

    for entries in by_outcome.values():
        for (study_a, finding_a), (study_b, finding_b) in combinations(entries, 2):
            if study_a.id == study_b.id:
                continue  # a study can't conflict with itself

            confidence = directions_conflict(finding_a.effect_direction, finding_b.effect_direction)
            if confidence is None:
                continue

            pair_key = tuple(sorted([str(study_a.id), str(study_b.id)])) + (_normalize_outcome(finding_a.outcome),)
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            candidates.append(
                ConflictCandidate(
                    study_a_id=study_a.id,
                    study_b_id=study_b.id,
                    conflicting_outcome=finding_a.outcome,
                    finding_a=f"{finding_a.effect_direction}"
                    + (f" ({finding_a.effect_size})" if finding_a.effect_size else ""),
                    finding_b=f"{finding_b.effect_direction}"
                    + (f" ({finding_b.effect_size})" if finding_b.effect_size else ""),
                    possible_explanation=explain_difference(study_a, study_b),
                    confidence=confidence,
                )
            )

    return candidates


async def run_conflict_detection(db: AsyncSession, research_job_id: UUID) -> list[ConflictCandidate]:
    result = await db.execute(
        select(Study)
        .options(selectinload(Study.study_findings), selectinload(Study.source))
        .join(Source, Source.id == Study.source_id)
        .where(Source.research_job_id == research_job_id)
    )
    studies = result.scalars().all()

    candidates = detect_conflicts(studies)

    # Idempotency: replace this job's conflicts rather than accumulating
    # duplicates if the pipeline is ever re-run.
    await db.execute(delete(Conflict).where(Conflict.research_job_id == research_job_id))
    for c in candidates:
        db.add(
            Conflict(
                research_job_id=research_job_id,
                study_a_id=c.study_a_id,
                study_b_id=c.study_b_id,
                conflicting_outcome=c.conflicting_outcome,
                finding_a=c.finding_a,
                finding_b=c.finding_b,
                possible_explanation=c.possible_explanation,
                confidence=c.confidence,
            )
        )
    await db.commit()
    return candidates
