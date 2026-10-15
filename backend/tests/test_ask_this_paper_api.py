"""
API-level authentication/ownership tests for Phase 6 endpoints. A study
owned by user A must be completely invisible to user B — not even a 403
that would confirm the study exists, a plain 404.
"""
import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.security import CurrentUser, get_current_user
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.evidence import Document, DocumentChunk, Source, Study
from app.models.research import ResearchJob, ResearchQuery

USER_A = str(uuid.uuid4())
USER_B = str(uuid.uuid4())


class FakeLLM:
    async def complete_json(self, system_prompt, user_prompt):
        return json.dumps(
            {
                "answer": "The study enrolled 250 participants.",
                "grounded": True,
                "supporting_excerpt": "enrolled 250 participants",
                "supporting_chunk_index": 0,
            }
        )

    async def complete_text(self, system_prompt, user_prompt):
        raise NotImplementedError

    async def embed(self, texts):
        raise NotImplementedError


class FakeEmbeddingClient:
    async def embed(self, texts):
        return [[0.01] * 1536 for _ in texts]


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    monkeypatch.setattr("app.api.routes.studies.get_llm_client", lambda: FakeLLM())


@pytest.fixture(autouse=True)
def _mock_embeddings(monkeypatch):
    monkeypatch.setattr("app.api.routes.studies.get_embedding_client", lambda: FakeEmbeddingClient())


@pytest.fixture(autouse=True)
async def _setup_users_and_cleanup():
    async with AsyncSessionLocal() as session:
        await session.execute(text("DELETE FROM research_queries"))
        for uid in (USER_A, USER_B):
            await session.execute(text("DELETE FROM auth.users WHERE id = :uid"), {"uid": uid})
            await session.execute(text("INSERT INTO auth.users (id) VALUES (:uid)"), {"uid": uid})
        await session.commit()
    yield
    from app.db.session import engine

    await engine.dispose()


async def _make_study_owned_by(user_id: str) -> uuid.UUID:
    async with AsyncSessionLocal() as session:
        query = ResearchQuery(user_id=user_id, raw_question="Does X help with Y?", status="COMPLETED")
        session.add(query)
        await session.flush()
        job = ResearchJob(research_query_id=query.id, status="COMPLETED")
        session.add(job)
        await session.flush()
        source = Source(
            research_job_id=job.id, source_type="PRIMARY_STUDY", origin="pubmed",
            external_id=str(uuid.uuid4()), title="Owned Study",
        )
        session.add(source)
        await session.flush()
        study = Study(source_id=source.id)
        session.add(study)
        await session.flush()
        document = Document(study_id=study.id, content="The study enrolled 250 participants.", document_type="ABSTRACT")
        session.add(document)
        await session.flush()
        session.add(
            DocumentChunk(
                document_id=document.id, study_id=study.id, chunk_index=0,
                content="The study enrolled 250 participants.", embedding=[0.01] * 1536, char_count=35,
            )
        )
        await session.commit()
        return study.id


def _as_user(user_id: str):
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=user_id, email="u@example.com")


# ---------- 13. Authentication / ownership ----------


@pytest.mark.asyncio
async def test_owner_can_ask_their_own_study():
    study_id = await _make_study_owned_by(USER_A)
    _as_user(USER_A)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/studies/{study_id}/ask", json={"question": "What was the sample size?"})
    app.dependency_overrides.pop(get_current_user, None)
    assert resp.status_code == 200
    assert "250" in resp.json()["answer"]


@pytest.mark.asyncio
async def test_other_user_cannot_ask_someone_elses_study():
    study_id = await _make_study_owned_by(USER_A)
    _as_user(USER_B)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/studies/{study_id}/ask", json={"question": "What was the sample size?"})
    app.dependency_overrides.pop(get_current_user, None)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_other_user_cannot_list_someone_elses_chunks():
    study_id = await _make_study_owned_by(USER_A)
    _as_user(USER_B)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/studies/{study_id}/chunks")
    app.dependency_overrides.pop(get_current_user, None)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_owner_can_list_their_own_chunks():
    study_id = await _make_study_owned_by(USER_A)
    _as_user(USER_A)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/studies/{study_id}/chunks")
    app.dependency_overrides.pop(get_current_user, None)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected():
    study_id = await _make_study_owned_by(USER_A)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/studies/{study_id}/ask", json={"question": "What was the sample size?"})
    assert resp.status_code == 401
