"""
RAG retrieval + Ask This Paper.

Retrieval is always scoped by study_id at the SQL level (`WHERE
document_chunks.study_id = :study_id`), not just by prompt instruction —
there is no code path in this file that can return another study's chunks.

Ask This Paper follows the same grounding philosophy as Phase 5's evidence
verification: the LLM proposes an answer and (optionally) quotes a
supporting excerpt from one specific retrieved chunk, but that excerpt is
checked programmatically against the real chunk text before being trusted.
If nothing meets the similarity threshold, the LLM is never even called —
there's nothing to ground an answer in, so we return the fixed "not enough
information" response rather than risk a knowledge-fallback hallucination.
"""
import json
import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.embeddings import EmbeddingClient
from app.integrations.llm import LLMClient
from app.models.evidence import Document, DocumentChunk
from app.schemas.rag import NOT_ENOUGH_INFO, AskAnswerLLMOutput, AskResponse, CitationOut, DocumentType

DEFAULT_TOP_K = 5
DEFAULT_SIMILARITY_THRESHOLD = 0.15

SYSTEM_PROMPT = """You are "Ask This Paper" — you answer questions using ONLY \
the provided excerpts from ONE specific paper/document. Answer only from \
the provided paper/document context. Do not use outside medical knowledge, \
and do not answer from anything not present in the given excerpts.

RULES:
1. If the excerpts answer the question, answer concisely and set "grounded" \
to true. You MUST quote the exact supporting sentence/phrase VERBATIM from \
one of the excerpts as "supporting_excerpt", and set \
"supporting_chunk_index" to that excerpt's index (as given below).
2. If the excerpts do NOT contain enough information to answer, respond \
with EXACTLY this answer text: "{not_enough_info}" — set "grounded" to \
false, "supporting_excerpt" to null, and "supporting_chunk_index" to null.
3. Never guess or fill gaps with general knowledge, even if you believe you \
know the answer from training data. Only this paper's excerpts count as \
evidence here.

Respond with ONLY a JSON object:
{{
  "answer": string,
  "grounded": boolean,
  "supporting_excerpt": string | null,
  "supporting_chunk_index": integer | null
}}
""".format(not_enough_info=NOT_ENOUGH_INFO)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def excerpt_is_grounded_in_chunk(excerpt: str | None, chunk_content: str) -> bool:
    if not excerpt:
        return False
    return _normalize(excerpt) in _normalize(chunk_content)


@dataclass
class RetrievedChunk:
    chunk: DocumentChunk
    similarity: float


async def retrieve_relevant_chunks(
    db: AsyncSession,
    study_id: UUID,
    query_vector: list[float],
    top_k: int = DEFAULT_TOP_K,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> list[RetrievedChunk]:
    """Cosine similarity search, hard-scoped to a single study_id. This
    WHERE clause is the actual enforcement of 'never retrieve chunks from
    another study' — not just a prompt instruction."""
    distance_expr = DocumentChunk.embedding.cosine_distance(query_vector)
    stmt = (
        select(DocumentChunk, (1 - distance_expr).label("similarity"))
        .where(DocumentChunk.study_id == study_id)
        .order_by(distance_expr)
        .limit(top_k)
    )
    result = await db.execute(stmt)
    rows = result.all()

    retrieved = [RetrievedChunk(chunk=row[0], similarity=float(row[1])) for row in rows]
    return [r for r in retrieved if r.similarity >= similarity_threshold]


async def ask_study_question(
    db: AsyncSession,
    study_id: UUID,
    question: str,
    llm: LLMClient,
    embedding_client: EmbeddingClient,
    top_k: int = DEFAULT_TOP_K,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> AskResponse:
    document_type = await _get_document_type(db, study_id)

    [query_vector] = await embedding_client.embed([question])
    retrieved = await retrieve_relevant_chunks(db, study_id, query_vector, top_k, similarity_threshold)

    if not retrieved:
        return AskResponse(answer=NOT_ENOUGH_INFO, citations=[], grounded=False, document_type=document_type)

    context_block = "\n\n".join(f"[Excerpt {i}]\n{r.chunk.content}" for i, r in enumerate(retrieved))
    user_prompt = f"Question: {question}\n\n{context_block}"

    raw = await llm.complete_json(SYSTEM_PROMPT, user_prompt)
    try:
        output = AskAnswerLLMOutput.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValueError):
        return AskResponse(answer=NOT_ENOUGH_INFO, citations=[], grounded=False, document_type=document_type)

    if not output.grounded or output.supporting_chunk_index is None or output.supporting_excerpt is None:
        return AskResponse(answer=NOT_ENOUGH_INFO, citations=[], grounded=False, document_type=document_type)

    if not (0 <= output.supporting_chunk_index < len(retrieved)):
        return AskResponse(answer=NOT_ENOUGH_INFO, citations=[], grounded=False, document_type=document_type)

    cited_chunk = retrieved[output.supporting_chunk_index]
    if not excerpt_is_grounded_in_chunk(output.supporting_excerpt, cited_chunk.chunk.content):
        return AskResponse(answer=NOT_ENOUGH_INFO, citations=[], grounded=False, document_type=document_type)

    return AskResponse(
        answer=output.answer,
        citations=[
            CitationOut(
                document_id=str(cited_chunk.chunk.document_id),
                chunk_id=str(cited_chunk.chunk.id),
                excerpt=output.supporting_excerpt,
                similarity=round(cited_chunk.similarity, 4),
            )
        ],
        grounded=True,
        document_type=document_type,
    )


async def _get_document_type(db: AsyncSession, study_id) -> DocumentType | None:
    result = await db.execute(select(Document.document_type).where(Document.study_id == study_id).limit(1))
    value = result.scalar_one_or_none()
    return DocumentType(value) if value else None
