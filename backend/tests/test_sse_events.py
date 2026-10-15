"""
Tests the GET /api/research/{id}/events SSE endpoint end-to-end: real
pipeline events streamed in order as the background pipeline actually
runs, ownership enforcement, and behavior when no job exists yet.
"""
import json
import uuid

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.security import CurrentUser, get_current_user
from app.db.session import AsyncSessionLocal
from app.main import app
from tests.test_full_pipeline_phase4_integration import (
    CTGOV_RESPONSE,
    PUBMED_EFETCH_XML,
    PUBMED_ESEARCH_RESPONSE,
    DispatchingFakeLLM,
    FakeEmbeddingClient,
)

USER_A = str(uuid.uuid4())
USER_B = str(uuid.uuid4())

_ORIGINAL_GET = httpx.AsyncClient.get


async def fake_get(self, url, params=None, **kwargs):
    url_str = str(url)
    if "esearch.fcgi" in url_str:
        return httpx.Response(200, json=PUBMED_ESEARCH_RESPONSE, request=httpx.Request("GET", url))
    if "efetch.fcgi" in url_str:
        return httpx.Response(200, text=PUBMED_EFETCH_XML, request=httpx.Request("GET", url))
    if "clinicaltrials.gov" in url_str:
        return httpx.Response(200, json=CTGOV_RESPONSE, request=httpx.Request("GET", url))
    return await _ORIGINAL_GET(self, url, params=params, **kwargs)


@pytest.fixture(autouse=True)
def _mock_http(monkeypatch):
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    monkeypatch.setattr("app.services.pipeline_service.get_llm_client", lambda: DispatchingFakeLLM())


@pytest.fixture(autouse=True)
def _mock_embeddings(monkeypatch):
    monkeypatch.setattr("app.services.pipeline_service.get_embedding_client", lambda: FakeEmbeddingClient())


@pytest.fixture(autouse=True)
def _no_tavily_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
async def _setup_and_cleanup():
    async with AsyncSessionLocal() as session:
        await session.execute(text("DELETE FROM research_queries"))
        for uid in (USER_A, USER_B):
            await session.execute(text("DELETE FROM auth.users WHERE id = :uid"), {"uid": uid})
            await session.execute(text("INSERT INTO auth.users (id) VALUES (:uid)"), {"uid": uid})
        await session.commit()
    yield
    import asyncio

    await asyncio.sleep(0.2)  # let any dispatched background pipelines finish before the loop closes
    from app.db.session import engine

    await engine.dispose()


def _as_user(user_id: str):
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=user_id, email="u@example.com")


async def _read_sse_events(response, max_events: int) -> list[dict]:
    events = []
    buffer = ""
    async for chunk in response.aiter_text():
        buffer += chunk
        while "\n\n" in buffer:
            raw_event, buffer = buffer.split("\n\n", 1)
            data_lines = [line[len("data: "):] for line in raw_event.split("\n") if line.startswith("data: ")]
            for line in data_lines:
                events.append(json.loads(line))
            if len(events) >= max_events:
                return events
    return events


@pytest.mark.asyncio
async def test_sse_stream_delivers_real_events_in_order():
    _as_user(USER_A)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/research", json={"raw_question": "Does metformin reduce cardiovascular risk in T2D?"}
        )
        query_id = create_resp.json()["id"]

        start_resp = await client.post(f"/api/research/{query_id}/start")
        assert start_resp.status_code == 202

        async with client.stream("GET", f"/api/research/{query_id}/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            events = await _read_sse_events(response, max_events=40)

    app.dependency_overrides.pop(get_current_user, None)

    event_names = [e["event"] for e in events]
    assert event_names[0] == "pipeline_started"
    assert event_names[-1] == "pipeline_completed"
    assert event_names.index("agent_started") < event_names.index("pipeline_completed")
    query_analyzer_started = next(
        i for i, e in enumerate(events) if e["event"] == "agent_started" and e["data"].get("agent") == "query_analyzer"
    )
    pubmed_started = next(
        i for i, e in enumerate(events) if e["event"] == "agent_started" and e["data"].get("agent") == "pubmed_research"
    )
    assert query_analyzer_started < pubmed_started

    final_event = events[-1]
    assert final_event["data"]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_other_user_cannot_subscribe_to_someone_elses_events():
    _as_user(USER_A)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post("/api/research", json={"raw_question": "Does X help with Y?"})
        query_id = create_resp.json()["id"]
        await client.post(f"/api/research/{query_id}/start")

    _as_user(USER_B)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/research/{query_id}/events")
    app.dependency_overrides.pop(get_current_user, None)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_events_endpoint_404s_before_any_job_exists():
    _as_user(USER_A)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post("/api/research", json={"raw_question": "Does X help with Y?"})
        query_id = create_resp.json()["id"]
        resp = await client.get(f"/api/research/{query_id}/events")
    app.dependency_overrides.pop(get_current_user, None)
    assert resp.status_code == 404
