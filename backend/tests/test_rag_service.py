"""
Integration tests for Phase 6 RAG against real Postgres + pgvector. LLM and
embedding calls are faked (deterministic, no real network); everything else
— chunking, embedding storage, cosine similarity search, grounding checks —
is real.
"""
import json
import uuid

import pytest
from sqlalchemy import func, select, text

from app.db.session import AsyncSessionLocal
from app.models.evidence import Document, DocumentChunk, Source, Study
from app.models.research import ResearchJob, ResearchQuery
from app.rag.rag_service import ask_study_question, retrieve_relevant_chunks
from app.schemas.rag import NOT_ENOUGH_INFO
from app.services.rag_indexing_service import index_document, index_studies_for_job


class FakeEmbeddingClient:
    def __init__(self, vector_for_text=None, default_dim=1536):
        self._vector_for_text = vector_for_text or {}
        self._default_dim = default_dim

    async def embed(self, texts):
        vectors = []
        for t in texts:
            for key, vec in self._vector_for_text.items():
                if key in t:
                    vectors.append(vec)
                    break
            else:
                vectors.append([0.001] * self._default_dim)
        return vectors


def _unit_vector(index: int, dim: int = 1536) -> list[float]:
    v = [0.0] * dim
    v[index] = 1.0
    return v


class ScriptedLLM:
    def __init__(self, response: str):
        self._response = response

    async def complete_json(self, system_prompt, user_prompt):
        return self._response

    async def complete_text(self, system_prompt, user_prompt):
        raise NotImplementedError

    async def embed(self, texts):
        raise NotImplementedError


class RaisingLLM:
    async def complete_json(self, system_prompt, user_prompt):
        raise RuntimeError("Simulated LLM outage.")

    async def complete_text(self, system_prompt, user_prompt):
        raise NotImplementedError

    async def embed(self, texts):
        raise NotImplementedError


class RaisingEmbeddingClient:
    async def embed(self, texts):
        raise RuntimeError("Simulated embedding API outage.")


@pytest.fixture(autouse=True)
async def _ensure_test_user():
    user_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as session:
        await session.execute(text("INSERT INTO auth.users (id) VALUES (:uid)"), {"uid": user_id})
        await session.commit()
    yield user_id


@pytest.fixture(autouse=True)
async def _dispose_engine_after():
    yield
    from app.db.session import engine

    await engine.dispose()


async def _make_study_with_document(session, user_id, *, content: str, document_type: str = "ABSTRACT"):
    query = ResearchQuery(user_id=user_id, raw_question="Does X help with Y?", status="RUNNING")
    session.add(query)
    await session.flush()
    job = ResearchJob(research_query_id=query.id, status="RUNNING")
    session.add(job)
    await session.flush()
    source = Source(
        research_job_id=job.id, source_type="PRIMARY_STUDY", origin="pubmed",
        external_id=str(uuid.uuid4()), title=f"Study {uuid.uuid4()}",
    )
    session.add(source)
    await session.flush()
    study = Study(source_id=source.id)
    session.add(study)
    await session.flush()
    document = Document(study_id=study.id, content=content, document_type=document_type)
    session.add(document)
    await session.commit()
    return job, study, document


# ---------- 4. Vector persistence ----------


@pytest.mark.asyncio
async def test_indexing_persists_chunks_with_embeddings(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        _, study, document = await _make_study_with_document(
            session, _ensure_test_user, content="Metformin reduced cardiovascular events in this trial. " * 20
        )
        count = await index_document(session, document.id, study.id, document.content, FakeEmbeddingClient())
        assert count > 0

        chunks = (
            (await session.execute(select(DocumentChunk).where(DocumentChunk.document_id == document.id)))
            .scalars()
            .all()
        )
        assert len(chunks) == count
        for c in chunks:
            assert c.embedding is not None
            assert c.study_id == study.id


# ---------- 5. Vector similarity retrieval ----------


@pytest.mark.asyncio
async def test_similarity_search_ranks_closer_vector_higher(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        _, study, document = await _make_study_with_document(session, _ensure_test_user, content="placeholder")
        session.add_all(
            [
                DocumentChunk(document_id=document.id, study_id=study.id, chunk_index=0, content="chunk A", embedding=_unit_vector(0), char_count=7),
                DocumentChunk(document_id=document.id, study_id=study.id, chunk_index=1, content="chunk B", embedding=_unit_vector(1), char_count=7),
            ]
        )
        await session.commit()

        results = await retrieve_relevant_chunks(session, study.id, _unit_vector(0), top_k=5, similarity_threshold=0.0)
        assert results[0].chunk.content == "chunk A"


@pytest.mark.asyncio
async def test_similarity_threshold_filters_out_dissimilar_chunks(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        _, study, document = await _make_study_with_document(session, _ensure_test_user, content="placeholder")
        session.add(
            DocumentChunk(document_id=document.id, study_id=study.id, chunk_index=0, content="unrelated chunk", embedding=_unit_vector(5), char_count=15)
        )
        await session.commit()

        results = await retrieve_relevant_chunks(session, study.id, _unit_vector(6), top_k=5, similarity_threshold=0.5)
        assert results == []


# ---------- 6 & 7. Study-scoped retrieval / no cross-study retrieval ----------


@pytest.mark.asyncio
async def test_retrieval_never_crosses_study_boundaries(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        _, study_a, doc_a = await _make_study_with_document(session, _ensure_test_user, content="Study A content")
        _, study_b, doc_b = await _make_study_with_document(session, _ensure_test_user, content="Study B content")

        same_vector = _unit_vector(0)
        session.add(DocumentChunk(document_id=doc_a.id, study_id=study_a.id, chunk_index=0, content="Study A chunk", embedding=same_vector, char_count=13))
        session.add(DocumentChunk(document_id=doc_b.id, study_id=study_b.id, chunk_index=0, content="Study B chunk", embedding=same_vector, char_count=13))
        await session.commit()

        results = await retrieve_relevant_chunks(session, study_a.id, same_vector, top_k=10, similarity_threshold=0.0)
        assert len(results) == 1
        assert results[0].chunk.content == "Study A chunk"
        assert all(r.chunk.study_id == study_a.id for r in results)


# ---------- 8. Empty retrieval ----------


@pytest.mark.asyncio
async def test_empty_retrieval_returns_grounded_not_enough_info(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        _, study, document = await _make_study_with_document(session, _ensure_test_user, content="Some content.")
        response = await ask_study_question(
            session, study.id, "What was the sample size?",
            llm=RaisingLLM(),  # must never even be called
            embedding_client=FakeEmbeddingClient(),
        )
        assert response.answer == NOT_ENOUGH_INFO
        assert response.grounded is False
        assert response.citations == []


# ---------- 9. Grounded answer (required Study A vs Study B isolation test) ----------


@pytest.mark.asyncio
async def test_study_a_sample_size_question_never_leaks_study_b_data(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        _, study_a, doc_a = await _make_study_with_document(
            session, _ensure_test_user, content="The study enrolled 250 participants with type 2 diabetes."
        )
        _, study_b, doc_b = await _make_study_with_document(
            session, _ensure_test_user, content="The study enrolled 500 participants with type 2 diabetes."
        )

        embedding_client = FakeEmbeddingClient(
            vector_for_text={
                "250 participants": _unit_vector(0),
                "500 participants": _unit_vector(1),
                "What was the sample size": _unit_vector(0),
            }
        )
        await index_document(session, doc_a.id, study_a.id, doc_a.content, embedding_client)
        await index_document(session, doc_b.id, study_b.id, doc_b.content, embedding_client)

        llm_response = json.dumps(
            {
                "answer": "The study enrolled 250 participants.",
                "grounded": True,
                "supporting_excerpt": "The study enrolled 250 participants",
                "supporting_chunk_index": 0,
            }
        )
        response = await ask_study_question(
            session, study_a.id, "What was the sample size?",
            llm=ScriptedLLM(llm_response), embedding_client=embedding_client,
        )

        assert "500" not in response.answer
        assert "250" in response.answer
        assert response.grounded is True
        assert "250" in response.citations[0].excerpt


# ---------- 10. Unsupported question ----------


@pytest.mark.asyncio
async def test_unsupported_question_returns_fixed_not_enough_info_message(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        _, study, document = await _make_study_with_document(
            session, _ensure_test_user, content="This study examined metformin's effect on blood glucose."
        )
        embedding_client = FakeEmbeddingClient(vector_for_text={"metformin": _unit_vector(0), "weather": _unit_vector(0)})
        await index_document(session, document.id, study.id, document.content, embedding_client)

        llm_response = json.dumps(
            {"answer": NOT_ENOUGH_INFO, "grounded": False, "supporting_excerpt": None, "supporting_chunk_index": None}
        )
        response = await ask_study_question(
            session, study.id, "What was the weather like during the study?",
            llm=ScriptedLLM(llm_response), embedding_client=embedding_client,
        )
        assert response.answer == NOT_ENOUGH_INFO
        assert response.grounded is False


# ---------- 11. Fake/fabricated excerpt rejection ----------


@pytest.mark.asyncio
async def test_fabricated_excerpt_forces_not_enough_info_despite_llm_claiming_grounded(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        _, study, document = await _make_study_with_document(
            session, _ensure_test_user, content="The study enrolled 250 participants with type 2 diabetes."
        )
        embedding_client = FakeEmbeddingClient(vector_for_text={"250 participants": _unit_vector(0), "sample size": _unit_vector(0)})
        await index_document(session, document.id, study.id, document.content, embedding_client)

        llm_response = json.dumps(
            {
                "answer": "The study enrolled 10,000 participants.",
                "grounded": True,
                "supporting_excerpt": "the study enrolled 10000 participants across twelve countries",
                "supporting_chunk_index": 0,
            }
        )
        response = await ask_study_question(
            session, study.id, "What was the sample size?",
            llm=ScriptedLLM(llm_response), embedding_client=embedding_client,
        )
        assert response.answer == NOT_ENOUGH_INFO
        assert response.grounded is False
        assert response.citations == []


@pytest.mark.asyncio
async def test_out_of_range_chunk_index_is_rejected(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        _, study, document = await _make_study_with_document(session, _ensure_test_user, content="Some content about metformin.")
        embedding_client = FakeEmbeddingClient(vector_for_text={"metformin": _unit_vector(0), "question": _unit_vector(0)})
        await index_document(session, document.id, study.id, document.content, embedding_client)

        llm_response = json.dumps(
            {"answer": "Some answer.", "grounded": True, "supporting_excerpt": "metformin", "supporting_chunk_index": 99}
        )
        response = await ask_study_question(
            session, study.id, "question", llm=ScriptedLLM(llm_response), embedding_client=embedding_client
        )
        assert response.grounded is False


# ---------- 12. Duplicate indexing prevention ----------


@pytest.mark.asyncio
async def test_reindexing_same_document_does_not_duplicate_chunks(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        _, study, document = await _make_study_with_document(
            session, _ensure_test_user, content="Metformin reduced cardiovascular events. " * 30
        )
        embedding_client = FakeEmbeddingClient()
        first_count = await index_document(session, document.id, study.id, document.content, embedding_client)
        second_count = await index_document(session, document.id, study.id, document.content, embedding_client)

        assert first_count == second_count
        total = (
            await session.execute(
                select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == document.id)
            )
        ).scalar_one()
        assert total == first_count


# ---------- 14. LLM failure ----------


@pytest.mark.asyncio
async def test_llm_failure_during_ask_propagates_rather_than_fabricating(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        _, study, document = await _make_study_with_document(session, _ensure_test_user, content="Some content about metformin.")
        embedding_client = FakeEmbeddingClient(vector_for_text={"metformin": _unit_vector(0), "question": _unit_vector(0)})
        await index_document(session, document.id, study.id, document.content, embedding_client)

        with pytest.raises(RuntimeError, match="Simulated LLM outage"):
            await ask_study_question(session, study.id, "question", llm=RaisingLLM(), embedding_client=embedding_client)


# ---------- 15. Embedding failure ----------


@pytest.mark.asyncio
async def test_embedding_failure_during_indexing_is_isolated_per_document(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        job, study, document = await _make_study_with_document(session, _ensure_test_user, content="Metformin content here.")
        summary = await index_studies_for_job(session, job.id, RaisingEmbeddingClient())
        assert summary.documents_indexed == 0
        assert len(summary.failed) == 1
        assert "Simulated embedding API outage" in summary.failed[0]["error"]


@pytest.mark.asyncio
async def test_embedding_failure_during_ask_propagates(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        _, study, document = await _make_study_with_document(session, _ensure_test_user, content="Some content.")
        with pytest.raises(RuntimeError, match="Simulated embedding API outage"):
            await ask_study_question(
                session, study.id, "question", llm=RaisingLLM(), embedding_client=RaisingEmbeddingClient()
            )


# ---------- Document type metadata ----------


@pytest.mark.asyncio
async def test_document_type_is_returned_in_ask_response(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        _, study, document = await _make_study_with_document(
            session, _ensure_test_user, content="Abstract-only content.", document_type="ABSTRACT"
        )
        response = await ask_study_question(
            session, study.id, "question", llm=RaisingLLM(), embedding_client=FakeEmbeddingClient()
        )
        assert response.document_type.value == "ABSTRACT"
