"""
API-level tests for Phase 9 security hardening: response headers, request
body size limits, and rate limiting on the expensive endpoints.
"""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser, get_current_user
from app.db.session import AsyncSessionLocal
from app.main import app

USER_A = str(uuid.uuid4())


class _FakeLLM:
    async def complete_json(self, system_prompt, user_prompt):
        return '{"is_researchable": false, "safety_note": "test", "population": null, "intervention": null, "comparator": null, "outcomes": [], "study_types": [], "evidence_requirements": [], "search_queries": {"pubmed": [], "clinical_trials": [], "web": []}}'

    async def complete_text(self, system_prompt, user_prompt):
        raise NotImplementedError

    async def embed(self, texts):
        raise NotImplementedError


class _FakeEmbeddingClient:
    async def embed(self, texts):
        return [[0.01] * 1536 for _ in texts]


@pytest.fixture(autouse=True)
def _mock_pipeline_clients(monkeypatch):
    # These tests only exercise middleware/rate-limiting around /start —
    # they don't need the pipeline to do real work, just to finish fast
    # and deterministically (query analyzer says "not researchable", so
    # the background task ends almost immediately) instead of spawning
    # real, slow, network-bound background tasks per request.
    monkeypatch.setattr("app.services.pipeline_service.get_llm_client", lambda: _FakeLLM())
    monkeypatch.setattr("app.services.pipeline_service.get_embedding_client", lambda: _FakeEmbeddingClient())


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.fixture(autouse=True)
async def _setup_and_cleanup():
    async with AsyncSessionLocal() as session:
        await session.execute(text("DELETE FROM research_queries"))
        await session.execute(text("DELETE FROM auth.users WHERE id = :uid"), {"uid": USER_A})
        await session.execute(text("INSERT INTO auth.users (id) VALUES (:uid)"), {"uid": USER_A})
        await session.commit()
    yield
    import asyncio

    await asyncio.sleep(0.2)  # let any dispatched background pipelines finish before the loop closes
    from app.db.session import engine

    await engine.dispose()


def _as_user_a():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=USER_A, email="a@example.com")


@pytest.mark.asyncio
async def test_security_headers_present_on_every_response():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in resp.headers


@pytest.mark.asyncio
async def test_oversized_request_body_is_rejected():
    _as_user_a()
    huge_question = "x" * 2_000_000
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/research", json={"raw_question": huge_question})
    app.dependency_overrides.pop(get_current_user, None)
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_normal_sized_request_is_not_affected_by_body_limit():
    _as_user_a()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/research", json={"raw_question": "Does metformin help with CV risk?"})
    app.dependency_overrides.pop(get_current_user, None)
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_start_endpoint_is_rate_limited_per_user():
    _as_user_a()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post("/api/research", json={"raw_question": "Does X help with Y?"})
        query_id = create_resp.json()["id"]

        statuses = []
        for _ in range(11):
            resp = await client.post(f"/api/research/{query_id}/start")
            statuses.append(resp.status_code)

    app.dependency_overrides.pop(get_current_user, None)
    assert 429 in statuses


@pytest.mark.asyncio
async def test_rate_limit_response_has_retry_after_header():
    _as_user_a()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post("/api/research", json={"raw_question": "Does X help with Y?"})
        query_id = create_resp.json()["id"]
        last_resp = None
        for _ in range(11):
            last_resp = await client.post(f"/api/research/{query_id}/start")
    app.dependency_overrides.pop(get_current_user, None)
    assert last_resp.status_code == 429
    assert "Retry-After" in last_resp.headers
