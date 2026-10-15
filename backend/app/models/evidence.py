"""
ORM models for retrieved evidence: sources (raw retrieval), studies
(normalized record + Phase 4 LLM-extracted analysis fields), study_findings
(structured per-outcome findings), documents/document_chunks (RAG),
evidence_claims/evidence_links (Phase 5 verification), conflicts (Phase 5),
research_reports (Phase 7 generated report + citations), and
saved_studies/saved_reports (user bookmarks, Phase 7).
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.db.session import Base

# Must match the embedding model configured in app.core.config
# (OpenAI text-embedding-3-small = 1536 dimensions) and the `vector(1536)`
# column type already defined in supabase/migrations/0001_init.sql. This
# constant exists so a future embedding-model change can't silently
# desync the ORM's expectation from the actual column — see
# app/integrations/embeddings.py, which validates every returned
# embedding's length against this same value before it's ever persisted.
EMBEDDING_DIMENSION = 1536


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    research_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("research_jobs.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    origin: Mapped[str] = mapped_column(String, nullable=False)  # 'pubmed' | 'clinicaltrials' | 'tavily'
    external_id: Mapped[str | None] = mapped_column(String)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(Text)
    published_date: Mapped[date | None] = mapped_column(Date)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    raw_metadata: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    studies: Mapped[list["Study"]] = relationship(back_populates="source", cascade="all, delete-orphan")


class Study(Base):
    __tablename__ = "studies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    study_type: Mapped[str | None] = mapped_column(Text)
    population: Mapped[str | None] = mapped_column(Text)
    sample_size: Mapped[int | None] = mapped_column(Integer)
    intervention: Mapped[str | None] = mapped_column(Text)
    comparator: Mapped[str | None] = mapped_column(Text)
    outcomes: Mapped[dict | None] = mapped_column(JSON)
    follow_up: Mapped[str | None] = mapped_column(Text)
    methodology: Mapped[str | None] = mapped_column(Text)
    findings: Mapped[str | None] = mapped_column(Text)
    effect_size: Mapped[str | None] = mapped_column(Text)
    limitations: Mapped[str | None] = mapped_column(Text)
    conclusion: Mapped[str | None] = mapped_column(Text)
    relevance_score: Mapped[float | None] = mapped_column(Numeric)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    source: Mapped["Source"] = relationship(back_populates="studies")
    documents: Mapped[list["Document"]] = relationship(back_populates="study", cascade="all, delete-orphan")
    study_findings: Mapped[list["StudyFinding"]] = relationship(
        back_populates="study", cascade="all, delete-orphan"
    )


class StudyFinding(Base):
    __tablename__ = "study_findings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    effect_direction: Mapped[str | None] = mapped_column(String)
    effect_size: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    study: Mapped["Study"] = relationship(back_populates="study_findings")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    document_type: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    study: Mapped["Study"] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    study_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSION))
    char_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    document: Mapped["Document"] = relationship(back_populates="chunks")


class EvidenceClaim(Base):
    __tablename__ = "evidence_claims"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    research_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("research_jobs.id", ondelete="CASCADE"), nullable=False
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    verification_status: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    evidence_links: Mapped[list["EvidenceLink"]] = relationship(
        back_populates="evidence_claim", cascade="all, delete-orphan"
    )


class EvidenceLink(Base):
    __tablename__ = "evidence_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evidence_claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_claims.id", ondelete="CASCADE"), nullable=False
    )
    study_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("studies.id", ondelete="SET NULL")
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL")
    )
    excerpt: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    evidence_claim: Mapped["EvidenceClaim"] = relationship(back_populates="evidence_links")


class Conflict(Base):
    __tablename__ = "conflicts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    research_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("research_jobs.id", ondelete="CASCADE"), nullable=False
    )
    study_a_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("studies.id", ondelete="CASCADE"))
    study_b_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("studies.id", ondelete="CASCADE"))
    conflicting_outcome: Mapped[str] = mapped_column(Text, nullable=False)
    finding_a: Mapped[str] = mapped_column(Text, nullable=False)
    finding_b: Mapped[str] = mapped_column(Text, nullable=False)
    possible_explanation: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ResearchReport(Base):
    __tablename__ = "research_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    research_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("research_jobs.id", ondelete="CASCADE"), nullable=False
    )
    sections: Mapped[dict] = mapped_column(JSON, nullable=False)
    citations: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_grade: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SavedStudy(Base):
    __tablename__ = "saved_studies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    study_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SavedReport(Base):
    __tablename__ = "saved_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("research_reports.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
