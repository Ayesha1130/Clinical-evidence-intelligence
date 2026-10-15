"""
Normalizes raw PubMed / ClinicalTrials.gov / Tavily results into the shared
`sources` + `studies` (+ `documents`) schema, and deduplicates across
sources before anything is written to the database.

Dedup strategy (in order of preference):
  1. Exact DOI match (case-insensitive) — the strongest signal available.
  2. Normalized title match (lowercased, punctuation stripped, whitespace
     collapsed) — catches e.g. a Tavily hit for a paper already found via
     PubMed, which won't share a DOI field in Tavily's result at all.

Candidates are deduplicated in source-priority order: PubMed and
ClinicalTrials.gov results are structured, identifier-bearing records and
always win over a Tavily web hit describing the same work. This module is
pure/DB-free except `persist_candidates`, so the dedup logic itself is
fully unit-testable.
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import Document, Source, Study
from app.services.source_classification import (
    classify_clinical_trial_source,
    classify_pubmed_source,
    classify_web_source,
)


@dataclass
class NormalizedCandidate:
    origin: str  # 'pubmed' | 'clinicaltrials' | 'tavily'
    external_id: str | None
    title: str
    source_type: str
    doi: str | None = None
    url: str | None = None
    publisher: str | None = None
    published_date: date | None = None
    study_type: str | None = None
    population: str | None = None
    sample_size: int | None = None
    intervention: str | None = None
    comparator: str | None = None
    outcomes: list[str] = field(default_factory=list)
    document_text: str | None = None
    raw_metadata: dict = field(default_factory=dict)


def _normalize_title(title: str) -> str:
    lowered = title.lower()
    stripped = re.sub(r"[^a-z0-9\s]", "", lowered)
    return re.sub(r"\s+", " ", stripped).strip()


def _document_type_for_origin(origin: str) -> str:
    """PubMed/CT.gov/Tavily only ever give us abstract/summary/snippet-level
    text — never a full paper. This mapping is what lets the RAG layer and
    UI say so explicitly instead of implying a full-text review happened."""
    return {
        "pubmed": "ABSTRACT",
        "clinicaltrials": "TRIAL_SUMMARY",
        "tavily": "WEB_CONTENT",
    }.get(origin, "WEB_CONTENT")


def _parse_pubmed_date(raw: str | None) -> date | None:
    if not raw:
        return None
    for fmt in ("%Y %b %d", "%Y %b", "%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_ctgov_date(raw: str | None) -> date | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def candidates_from_pubmed(articles) -> list[NormalizedCandidate]:
    candidates = []
    for a in articles:
        candidates.append(
            NormalizedCandidate(
                origin="pubmed",
                external_id=a.pmid,
                title=a.title,
                source_type=classify_pubmed_source(a.publication_types),
                doi=a.doi,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{a.pmid}/",
                publisher=a.journal,
                published_date=_parse_pubmed_date(a.publication_date),
                study_type=", ".join(a.publication_types) if a.publication_types else None,
                document_text=a.abstract,
                raw_metadata={"authors": a.authors, "publication_types": a.publication_types},
            )
        )
    return candidates


def candidates_from_clinical_trials(trials) -> list[NormalizedCandidate]:
    candidates = []
    for t in trials:
        candidates.append(
            NormalizedCandidate(
                origin="clinicaltrials",
                external_id=t.nct_id,
                title=t.title,
                source_type=classify_clinical_trial_source(),
                url=f"https://clinicaltrials.gov/study/{t.nct_id}",
                publisher=t.sponsor,
                published_date=_parse_ctgov_date(t.start_date),
                study_type=", ".join(t.phase) if t.phase else t.study_type,
                population=", ".join(t.conditions) if t.conditions else None,
                sample_size=t.enrollment,
                intervention=", ".join(t.interventions) if t.interventions else None,
                outcomes=t.outcomes,
                document_text=t.brief_summary,
                raw_metadata={
                    "status": t.status,
                    "study_type": t.study_type,
                    "locations": t.locations,
                    "completion_date": t.completion_date,
                },
            )
        )
    return candidates


def candidates_from_web(results) -> list[NormalizedCandidate]:
    candidates = []
    for r in results:
        candidates.append(
            NormalizedCandidate(
                origin="tavily",
                external_id=r.url,  # web results have no PMID/NCT; URL is the identifier
                title=r.title,
                source_type=classify_web_source(r.title, r.domain),
                url=r.url,
                publisher=r.domain,
                document_text=r.snippet,
                raw_metadata={"score": r.score, "retrieved_at": r.retrieved_at},
            )
        )
    return candidates


def deduplicate(candidates: list[NormalizedCandidate]) -> list[NormalizedCandidate]:
    """
    Input order encodes source priority (call with pubmed + clinicaltrials
    candidates before tavily candidates). First occurrence wins.
    """
    seen_dois: set[str] = set()
    seen_titles: set[str] = set()
    deduped: list[NormalizedCandidate] = []

    for candidate in candidates:
        doi_key = candidate.doi.lower().strip() if candidate.doi else None
        title_key = _normalize_title(candidate.title)

        if doi_key and doi_key in seen_dois:
            continue
        if title_key and title_key in seen_titles:
            continue

        if doi_key:
            seen_dois.add(doi_key)
        if title_key:
            seen_titles.add(title_key)
        deduped.append(candidate)

    return deduped


async def persist_candidates(
    db: AsyncSession, research_job_id, candidates: list[NormalizedCandidate]
) -> dict[str, int]:
    """Writes Source + Study (+ Document, when text is available) rows.
    Returns counts by origin for observability/reporting."""
    counts = {"pubmed": 0, "clinicaltrials": 0, "tavily": 0}

    for candidate in candidates:
        source = Source(
            research_job_id=research_job_id,
            source_type=candidate.source_type,
            origin=candidate.origin,
            external_id=candidate.external_id,
            title=candidate.title,
            url=candidate.url,
            publisher=candidate.publisher,
            published_date=candidate.published_date,
            raw_metadata={**candidate.raw_metadata, **({"doi": candidate.doi} if candidate.doi else {})},
        )
        db.add(source)
        await db.flush()  # populate source.id without committing yet

        study = Study(
            source_id=source.id,
            study_type=candidate.study_type,
            population=candidate.population,
            sample_size=candidate.sample_size,
            intervention=candidate.intervention,
            comparator=candidate.comparator,
            outcomes=candidate.outcomes or None,
        )
        db.add(study)
        await db.flush()

        if candidate.document_text:
            db.add(
                Document(
                    study_id=study.id,
                    content=candidate.document_text,
                    document_type=_document_type_for_origin(candidate.origin),
                )
            )

        counts[candidate.origin] = counts.get(candidate.origin, 0) + 1

    await db.commit()
    return counts
