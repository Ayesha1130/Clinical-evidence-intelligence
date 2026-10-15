"""
Schemas for Phase 5: Claim Extraction and Evidence Verification.

Grounding is enforced in two layers: the prompt instructs the model not to
invent an excerpt, and — because an LLM cannot be trusted blindly to follow
that instruction — `app/services/evidence_verification_service.py` checks
every returned excerpt is an actual substring of the document it claims to
come from before persisting anything. A claim whose excerpt can't be
verified programmatically is downgraded to NOT_SUPPORTED regardless of
what the model said.
"""
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class VerificationStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    CONFLICTING = "CONFLICTING"


# ---------- Claim Extraction ----------


class ClaimExtractionInput(BaseModel):
    study_id: str
    study_title: str
    research_question: str
    conclusion: str | None = None
    findings_summary: str | None = None
    study_findings: list[dict] = Field(default_factory=list)  # [{outcome, effect_direction, effect_size}]


class ClaimExtractionOutput(BaseModel):
    claims: list[str] = Field(default_factory=list)

    @field_validator("claims")
    @classmethod
    def claims_not_empty_strings(cls, v: list[str]) -> list[str]:
        return [c.strip() for c in v if c and c.strip()]


# ---------- Evidence Verification ----------


class EvidenceVerificationInput(BaseModel):
    claim_text: str
    study_id: str
    document_text: str  # the ONLY text the verifier is allowed to use


class EvidenceVerificationOutput(BaseModel):
    verification_status: VerificationStatus
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_excerpt: str | None = None  # must be a verbatim substring of document_text; checked post-hoc

    @field_validator("supporting_excerpt")
    @classmethod
    def excerpt_not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            return None
        return v
