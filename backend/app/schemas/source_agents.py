from pydantic import BaseModel, Field


# ---------- Shared agent input ----------


class SourceAgentInput(BaseModel):
    queries: list[str] = Field(min_length=1)
    max_results_per_query: int = 10


# ---------- PubMed ----------


class PubMedArticleSchema(BaseModel):
    pmid: str
    title: str
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    publication_date: str | None = None
    abstract: str | None = None
    doi: str | None = None
    publication_types: list[str] = Field(default_factory=list)


class PubMedAgentOutput(BaseModel):
    articles: list[PubMedArticleSchema] = Field(default_factory=list)


# ---------- ClinicalTrials.gov ----------


class ClinicalTrialSchema(BaseModel):
    nct_id: str
    title: str
    status: str | None = None
    conditions: list[str] = Field(default_factory=list)
    interventions: list[str] = Field(default_factory=list)
    study_type: str | None = None
    phase: list[str] = Field(default_factory=list)
    enrollment: int | None = None
    sponsor: str | None = None
    start_date: str | None = None
    completion_date: str | None = None
    outcomes: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    brief_summary: str | None = None


class ClinicalTrialsAgentOutput(BaseModel):
    trials: list[ClinicalTrialSchema] = Field(default_factory=list)


# ---------- Tavily / web research ----------


class WebResultSchema(BaseModel):
    title: str
    url: str
    domain: str
    snippet: str
    retrieved_at: str
    score: float | None = None


class WebResearchAgentOutput(BaseModel):
    results: list[WebResultSchema] = Field(default_factory=list)
