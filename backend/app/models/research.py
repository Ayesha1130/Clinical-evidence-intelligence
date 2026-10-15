"""
ORM models for the tables this phase's API actually touches.

The full schema already exists in supabase/migrations/0001_init.sql
(sources, studies, evidence_claims, conflicts, documents, document_chunks,
saved_studies, saved_reports, research_reports). ORM classes for those are
added in Phase 3+ alongside the agents that populate them, so this file
doesn't get ahead of working functionality.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Integer, String, Text, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ResearchQuery(Base):
    __tablename__ = "research_queries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    raw_question: Mapped[str] = mapped_column(Text, nullable=False)
    population: Mapped[str | None] = mapped_column(Text)
    intervention: Mapped[str | None] = mapped_column(Text)
    comparator: Mapped[str | None] = mapped_column(Text)
    outcomes: Mapped[dict | None] = mapped_column(JSON)
    study_types: Mapped[dict | None] = mapped_column(JSON)
    date_range: Mapped[dict | None] = mapped_column(JSON)
    sources: Mapped[dict | None] = mapped_column(JSON)
    search_queries: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String, default="DRAFT", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    jobs: Mapped[list["ResearchJob"]] = relationship(back_populates="research_query", cascade="all, delete-orphan")


class ResearchJob(Base):
    __tablename__ = "research_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    research_query_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("research_queries.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, default="QUEUED", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_summary: Mapped[str | None] = mapped_column(Text)
    evidence_grade: Mapped[str | None] = mapped_column(String)
    grading_explanation: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    research_query: Mapped["ResearchQuery"] = relationship(back_populates="jobs")
    agent_runs: Mapped[list["AgentRun"]] = relationship(back_populates="research_job", cascade="all, delete-orphan")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    research_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("research_jobs.id", ondelete="CASCADE"), nullable=False
    )
    agent_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    input: Mapped[dict | None] = mapped_column(JSON)
    output: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    research_job: Mapped["ResearchJob"] = relationship(back_populates="agent_runs")
