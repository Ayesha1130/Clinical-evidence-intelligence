"""
Report Generation schemas.

The LLM's role is deliberately narrow: it only writes prose synthesis
(executive summary, key findings narrative, evidence gaps narrative,
limitations narrative, conclusion) from a list of claims that were ALREADY
verified as SUPPORTED or PARTIALLY_SUPPORTED in Phase 5. It never invents
new facts, and it never assigns its own citation numbers — citation
numbering is computed deterministically in
app/services/report_generation_service.py from the actual evidence_links
already in the database, so a citation can never point to something that
doesn't exist.

Everything else in the final report (methodology, studies-analyzed table,
sources list, conflicting-evidence list, evidence strength) is assembled
directly from database rows, with no LLM involvement at all.
"""
from pydantic import BaseModel, Field, field_validator


class VerifiedClaimForReport(BaseModel):
    claim_text: str
    study_title: str
    citation_number: int


class ReportGenerationInput(BaseModel):
    research_question: str
    population: str | None = None
    intervention: str | None = None
    comparator: str | None = None
    outcomes: list[str] = Field(default_factory=list)
    verified_claims: list[VerifiedClaimForReport] = Field(default_factory=list)
    conflict_count: int
    evidence_grade: str
    studies_considered: int


class ReportGenerationOutput(BaseModel):
    executive_summary: str
    key_findings_narrative: str
    evidence_gaps_narrative: str
    limitations_narrative: str
    conclusion: str

    @field_validator(
        "executive_summary", "key_findings_narrative", "evidence_gaps_narrative",
        "limitations_narrative", "conclusion",
    )
    @classmethod
    def not_blank(cls, v: str) -> str:
        return v.strip() or "Not reported."


# ---------- API response schemas ----------

import uuid
from datetime import datetime


class ReportOut(BaseModel):
    id: uuid.UUID
    research_job_id: uuid.UUID
    sections: dict
    citations: list
    evidence_grade: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class EvidenceMapOut(BaseModel):
    nodes: list[dict]
    edges: list[dict]


class SaveReportOut(BaseModel):
    saved: bool
