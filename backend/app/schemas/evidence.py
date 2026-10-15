import uuid
from datetime import datetime

from pydantic import BaseModel


class EvidenceLinkOut(BaseModel):
    id: uuid.UUID
    study_id: uuid.UUID | None
    source_id: uuid.UUID | None
    excerpt: str | None

    model_config = {"from_attributes": True}


class EvidenceClaimOut(BaseModel):
    id: uuid.UUID
    claim_text: str
    verification_status: str
    confidence: float | None
    evidence_links: list[EvidenceLinkOut]
    created_at: datetime

    @classmethod
    def from_orm_model(cls, claim) -> "EvidenceClaimOut":
        return cls(
            id=claim.id,
            claim_text=claim.claim_text,
            verification_status=claim.verification_status,
            confidence=float(claim.confidence) if claim.confidence is not None else None,
            evidence_links=[EvidenceLinkOut.model_validate(link) for link in claim.evidence_links],
            created_at=claim.created_at,
        )


class ConflictOut(BaseModel):
    id: uuid.UUID
    study_a_id: uuid.UUID
    study_b_id: uuid.UUID
    conflicting_outcome: str
    finding_a: str
    finding_b: str
    possible_explanation: str | None
    confidence: float | None
    created_at: datetime

    @classmethod
    def from_orm_model(cls, conflict) -> "ConflictOut":
        return cls(
            id=conflict.id,
            study_a_id=conflict.study_a_id,
            study_b_id=conflict.study_b_id,
            conflicting_outcome=conflict.conflicting_outcome,
            finding_a=conflict.finding_a,
            finding_b=conflict.finding_b,
            possible_explanation=conflict.possible_explanation,
            confidence=float(conflict.confidence) if conflict.confidence is not None else None,
            created_at=conflict.created_at,
        )


class EvidenceGradeOut(BaseModel):
    grade: str | None
    explanation: dict | None
