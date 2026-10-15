import uuid
from datetime import date, datetime

from pydantic import BaseModel


class StudyFindingOut(BaseModel):
    id: uuid.UUID
    outcome: str
    effect_direction: str | None
    effect_size: str | None
    confidence: str | None

    model_config = {"from_attributes": True}


class StudyOut(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    origin: str
    external_id: str | None
    source_type: str
    title: str
    url: str | None
    publisher: str | None
    published_date: date | None
    study_type: str | None
    population: str | None
    sample_size: int | None
    intervention: str | None
    comparator: str | None
    outcomes: list | None
    follow_up: str | None
    findings: str | None
    effect_size: str | None
    limitations: str | None
    conclusion: str | None
    relevance_score: float | None
    study_findings: list[StudyFindingOut]
    created_at: datetime

    @classmethod
    def from_orm_with_source(cls, study) -> "StudyOut":
        source = study.source
        return cls(
            id=study.id,
            source_id=source.id,
            origin=source.origin,
            external_id=source.external_id,
            source_type=source.source_type,
            title=source.title,
            url=source.url,
            publisher=source.publisher,
            published_date=source.published_date,
            study_type=study.study_type,
            population=study.population,
            sample_size=study.sample_size,
            intervention=study.intervention,
            comparator=study.comparator,
            outcomes=study.outcomes,
            follow_up=study.follow_up,
            findings=study.findings,
            effect_size=study.effect_size,
            limitations=study.limitations,
            conclusion=study.conclusion,
            relevance_score=float(study.relevance_score) if study.relevance_score is not None else None,
            study_findings=[StudyFindingOut.model_validate(f) for f in study.study_findings],
            created_at=study.created_at,
        )


class StudyDetailOut(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    origin: str
    external_id: str | None
    source_type: str
    title: str
    url: str | None
    publisher: str | None
    published_date: date | None
    authors: list[str] | None
    doi: str | None
    study_type: str | None
    population: str | None
    sample_size: int | None
    intervention: str | None
    comparator: str | None
    outcomes: list | None
    follow_up: str | None
    methodology: str | None
    findings: str | None
    effect_size: str | None
    limitations: str | None
    conclusion: str | None
    relevance_score: float | None
    document_type: str | None
    study_findings: list[StudyFindingOut]
    created_at: datetime

    @classmethod
    def from_orm_with_source(cls, study) -> "StudyDetailOut":
        source = study.source
        raw_meta = source.raw_metadata or {}
        document_type = study.documents[0].document_type if study.documents else None
        return cls(
            id=study.id,
            source_id=source.id,
            origin=source.origin,
            external_id=source.external_id,
            source_type=source.source_type,
            title=source.title,
            url=source.url,
            publisher=source.publisher,
            published_date=source.published_date,
            authors=raw_meta.get("authors"),
            doi=raw_meta.get("doi"),
            study_type=study.study_type,
            population=study.population,
            sample_size=study.sample_size,
            intervention=study.intervention,
            comparator=study.comparator,
            outcomes=study.outcomes,
            follow_up=study.follow_up,
            methodology=study.methodology,
            findings=study.findings,
            effect_size=study.effect_size,
            limitations=study.limitations,
            conclusion=study.conclusion,
            relevance_score=float(study.relevance_score) if study.relevance_score is not None else None,
            document_type=document_type,
            study_findings=[StudyFindingOut.model_validate(f) for f in study.study_findings],
            created_at=study.created_at,
        )


class SaveStudyOut(BaseModel):
    saved: bool
