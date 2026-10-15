"""
Persists Study Analysis Agent output onto the existing `studies` row and
into `study_findings`, and determines the evidence_level / provenance for
a given study before analysis runs.

Persistence rule: fields Phase 3 already populated from structured source
metadata (population, sample_size, intervention, outcomes, study_type) are
only filled in if still empty — a CT.gov enrollment count or PubMed
publication-type list is more reliable than an LLM re-deriving the same
fact from the same text, so we never let the LLM overwrite it. Fields that
are exclusively Phase 4's responsibility (methodology, findings, effect_size,
limitations, conclusion, follow_up, relevance_score) are always set from the
agent's output.
"""
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import Document, Source, Study, StudyFinding
from app.schemas.study_analysis import EvidenceLevel, StudyAnalysisInput, StudyAnalysisOutput

EVIDENCE_LEVEL_NOTE = {
    EvidenceLevel.FULL_TEXT: "Full text was available for this analysis.",
    EvidenceLevel.ABSTRACT_ONLY: "Analysis is based on the abstract only; the full paper was not retrieved.",
    EvidenceLevel.TRIAL_REGISTRY_SUMMARY: (
        "Analysis is based on the trial registry's brief summary only, not a full study report."
    ),
    EvidenceLevel.WEB_SNIPPET: "Analysis is based on a short web search snippet only.",
    EvidenceLevel.NO_CONTENT_AVAILABLE: "No source text was available to analyze for this study.",
}


def determine_evidence_level(origin: str, document_text: str | None) -> EvidenceLevel:
    if not document_text or not document_text.strip():
        return EvidenceLevel.NO_CONTENT_AVAILABLE
    if origin == "pubmed":
        return EvidenceLevel.ABSTRACT_ONLY
    if origin == "clinicaltrials":
        return EvidenceLevel.TRIAL_REGISTRY_SUMMARY
    if origin == "tavily":
        return EvidenceLevel.WEB_SNIPPET
    return EvidenceLevel.NO_CONTENT_AVAILABLE


def build_study_analysis_input(
    study: Study,
    source: Source,
    document: Document | None,
    research_question: str,
    population_hint: str | None,
    intervention_hint: str | None,
    comparator_hint: str | None,
    outcomes_hint: list[str] | None,
) -> StudyAnalysisInput:
    document_text = document.content if document else None
    evidence_level = determine_evidence_level(source.origin, document_text)

    return StudyAnalysisInput(
        study_id=str(study.id),
        research_question=research_question,
        population_hint=population_hint,
        intervention_hint=intervention_hint,
        comparator_hint=comparator_hint,
        outcomes_hint=outcomes_hint or [],
        title=source.title,
        origin=source.origin,
        document_text=document_text,
        evidence_level=evidence_level,
        known_population=study.population,
        known_sample_size=study.sample_size,
        known_intervention=study.intervention,
        known_outcomes=list(study.outcomes) if study.outcomes else [],
    )


def _with_provenance(text: str | None, note: str) -> str:
    body = text if text and text.strip() else "Not reported"
    return f"[{note}] {body}"


async def persist_study_analysis(
    db: AsyncSession, study: Study, source: Source, output: StudyAnalysisOutput, document: Document | None
) -> None:
    provenance_note = EVIDENCE_LEVEL_NOTE[output.evidence_level]

    # Structured metadata fields: fill only if Phase 3 left them empty.
    if not study.population and output.population:
        study.population = output.population
    if not study.sample_size and output.sample_size:
        study.sample_size = output.sample_size
    if not study.intervention and output.intervention:
        study.intervention = output.intervention
    if not study.comparator and output.comparator:
        study.comparator = output.comparator
    if not study.outcomes and output.outcomes:
        study.outcomes = output.outcomes
    if not study.study_type and output.study_type:
        study.study_type = output.study_type

    # Phase 4-owned narrative fields: always set, always prefixed with the
    # evidence-level provenance note so nothing downstream can mistake an
    # abstract-only read for a full-text review.
    study.follow_up = output.follow_up
    study.methodology = _with_provenance(output.methodology, provenance_note)
    study.findings = _with_provenance(output.findings, provenance_note)
    study.effect_size = output.effect_size
    study.limitations = output.limitations
    study.conclusion = output.conclusion
    study.relevance_score = output.relevance_score

    # Idempotency: if this study is ever re-analyzed, replace its findings
    # rather than accumulating duplicates.
    await db.execute(delete(StudyFinding).where(StudyFinding.study_id == study.id))
    for item in output.study_findings:
        db.add(
            StudyFinding(
                study_id=study.id,
                outcome=item.outcome,
                effect_direction=item.effect_direction.value,
                effect_size=item.effect_size,
                confidence=item.confidence.value,
            )
        )

    # Provenance on the source record itself: exactly what was analyzed.
    # study_id -> source_id already carries origin/url/title; this adds the
    # evidence_level and, when one exists, which document row was the input.
    source.raw_metadata = {
        **(source.raw_metadata or {}),
        "phase4_analysis": {
            "evidence_level": output.evidence_level.value,
            "document_id": str(document.id) if document else None,
        },
    }
