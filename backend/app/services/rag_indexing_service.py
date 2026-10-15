"""
Indexes a Document into document_chunks with embeddings.

Idempotent by construction: indexing always deletes any existing chunks
for that document_id first, then re-chunks and re-embeds from scratch.
Indexing the same document twice never produces duplicate chunk rows —
enforced both by this delete-first logic and by the DB-level unique
constraint on (document_id, chunk_index) added in migration 0004.
"""
import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.embeddings import EmbeddingClient
from app.models.evidence import Document, DocumentChunk, Source, Study
from app.rag.chunking import chunk_text

logger = logging.getLogger("rag_indexing_service")


@dataclass
class IndexingSummary:
    documents_indexed: int = 0
    chunks_created: int = 0
    documents_skipped_empty: int = 0
    failed: list[dict] = field(default_factory=list)

    @property
    def any_failed(self) -> bool:
        return bool(self.failed)


async def index_document(
    db: AsyncSession, document_id: UUID, study_id: UUID, content: str, embedding_client: EmbeddingClient
) -> int:
    """Chunks + embeds one document, replacing any existing chunks for it.
    Returns the number of chunks created. Raises on embedding failure —
    the caller is expected to run this inside its own savepoint so a
    failure here only rolls back this document's work, not the whole
    session (see index_studies_for_job).

    Takes plain values (not an ORM Document instance) deliberately: if a
    prior document in the same batch fails and its savepoint rolls back,
    re-touching an old ORM object's lazy attributes afterward is exactly
    the kind of thing that trips SQLAlchemy's async/greenlet edge cases.
    Plain values sidestep that entirely.
    """
    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))

    chunks = chunk_text(content)
    if not chunks:
        return 0

    vectors = await embedding_client.embed([c.content for c in chunks])

    for chunk, vector in zip(chunks, vectors):
        db.add(
            DocumentChunk(
                document_id=document_id,
                study_id=study_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                embedding=vector,
                char_count=chunk.char_count,
            )
        )

    await db.flush()
    return len(chunks)


async def index_studies_for_job(
    db: AsyncSession, research_job_id: UUID, embedding_client: EmbeddingClient
) -> IndexingSummary:
    """Indexes every document belonging to every study retrieved for this
    research job. One document failing to embed never blocks the others —
    each document's work runs inside its own SAVEPOINT (not a full session
    rollback), so a failure can't force an unexpected connection checkout
    mid-loop or disturb the other documents' already-flushed work."""
    result = await db.execute(
        select(Document.id, Document.study_id, Document.content)
        .join(Study, Study.id == Document.study_id)
        .join(Source, Source.id == Study.source_id)
        .where(Source.research_job_id == research_job_id)
    )
    # Extracted as plain tuples up front, deliberately — see index_document's
    # docstring for why we never hold onto ORM instances across the loop.
    documents = result.all()

    summary = IndexingSummary()
    for document_id, study_id, content in documents:
        if not content or not content.strip():
            summary.documents_skipped_empty += 1
            continue
        try:
            async with db.begin_nested():
                chunk_count = await index_document(db, document_id, study_id, content, embedding_client)
            summary.documents_indexed += 1
            summary.chunks_created += chunk_count
        except Exception as exc:  # noqa: BLE001 — isolate one document's failure from the rest
            logger.warning("Indexing failed for document %s: %s", document_id, exc)
            summary.failed.append({"document_id": str(document_id), "error": str(exc)})

    await db.commit()
    return summary
