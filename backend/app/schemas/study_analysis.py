"""
Study Analysis Agent schemas.

Every optional field defaults to `None` and the prompt instructs the model
to return `"Not reported"` (for free-text fields) rather than invent a
value. `relevance_score` and `EffectDirection`/`Confidence` enums are
constrained so the LLM can't return an out-of-vocabulary value silently —
Pydantic validation fails loudly instead, and the agent surfaces that as an
AgentExecutionError rather than persisting a malformed result.
"""
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class EffectDirection(str, Enum):
    BENEFIT = "BENEFIT"
    HARM = "HARM"
    NO_EFFECT = "NO_EFFECT"
    UNCLEAR = "UNCLEAR"


class FindingConfidence(str, Enum):
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"


class EvidenceLevel(str, Enum):
    """How much of the source text the analysis actually had access to.
    Carried through so no downstream consumer can mistake an abstract-only
    read for a full-text review."""

    FULL_TEXT = "full_text"
    ABSTRACT_ONLY = "abstract_only"
    TRIAL_REGISTRY_SUMMARY = "trial_registry_summary"
    WEB_SNIPPET = "web_snippet"
    NO_CONTENT_AVAILABLE = "no_content_available"


class StudyFindingItem(BaseModel):
    outcome: str
    effect_direction: EffectDirection
    effect_size: str | None = None  # free text, e.g. "HR 0.86 (95% CI 0.78-0.94)"; "Not reported" if absent
    confidence: FindingConfidence

    @field_validator("outcome")
    @classmethod
    def outcome_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("outcome must not be empty")
        return v.strip()


class StudyAnalysisInput(BaseModel):
    study_id: str
    research_question: str
    population_hint: str | None = None
    intervention_hint: str | None = None
    comparator_hint: str | None = None
    outcomes_hint: list[str] = Field(default_factory=list)

    title: str
    origin: str  # 'pubmed' | 'clinicaltrials' | 'tavily'
    document_text: str | None = None
    evidence_level: EvidenceLevel

    # Already-known structured fields from source normalization (Phase 3),
    # passed through so the model doesn't need to re-derive what's already
    # known precisely (e.g. a CT.gov enrollment count) and isn't tempted to
    # contradict it.
    known_population: str | None = None
    known_sample_size: int | None = None
    known_intervention: str | None = None
    known_outcomes: list[str] = Field(default_factory=list)


class StudyAnalysisOutput(BaseModel):
    evidence_level: EvidenceLevel
    study_type: str | None = None
    population: str | None = None
    sample_size: int | None = None
    intervention: str | None = None
    comparator: str | None = None
    outcomes: list[str] = Field(default_factory=list)
    follow_up: str | None = None
    methodology: str | None = None
    findings: str | None = None  # narrative summary, distinct from the structured list below
    effect_size: str | None = None
    limitations: str | None = None
    conclusion: str | None = None
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    study_findings: list[StudyFindingItem] = Field(default_factory=list)

    @field_validator("sample_size")
    @classmethod
    def sample_size_must_be_positive(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("sample_size, if reported, must be a positive integer")
        return v
