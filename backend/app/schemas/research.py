import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ResearchQueryCreate(BaseModel):
    raw_question: str = Field(min_length=8, max_length=2000)
    population: str | None = None
    intervention: str | None = None
    comparator: str | None = None
    outcomes: list[str] | None = None
    study_types: list[str] | None = None
    date_range: dict | None = None
    sources: list[str] | None = None


class ResearchQueryOut(BaseModel):
    id: uuid.UUID
    raw_question: str
    population: str | None
    intervention: str | None
    comparator: str | None
    outcomes: list | None
    study_types: list | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ResearchJobOut(BaseModel):
    id: uuid.UUID
    research_query_id: uuid.UUID
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    failure_summary: str | None
    evidence_grade: str | None = None

    model_config = {"from_attributes": True}


class AgentRunOut(BaseModel):
    id: uuid.UUID
    agent_name: str
    status: str
    error: str | None
    retry_count: int
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}
