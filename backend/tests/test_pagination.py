"""
Tests pagination on GET /api/research (limit/offset), added in Phase 9 as
a real safeguard against an unbounded list growing without limit for a
user with a long research history.
"""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.security import CurrentUser, get_current_user
from app.db.session import AsyncSessionLocal
from app.main import app

USER_A = str(uuid.uuid4())


@pytest.fixture(autouse=True)
async def _setup_and_cleanup():
    async with AsyncSessionLocal() as session:
        await session.execute(text("DELETE FROM research_queries"))
        await session.execute(text("DELETE FROM auth.users WHERE id = :uid"), {"uid": USER_A})
        await session.execute(text("INSERT INTO auth.users (id) VALUES (:uid)"), {"uid": USER_A})
        await session.commit()
    yield
    from app.db.session import engine

    await engine.dispose()


def _as_user_a():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=USER_A, email="a@example.com")


@pytest.mark.asyncio
async def test_default_limit_caps_results():
    _as_user_a()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for i in range(25):
            await client.post("/api/research", json={"raw_question": f"Does treatment {i} help with condition X?"})
        resp = await client.get("/api/research")
    app.dependency_overrides.pop(get_current_user, None)
    assert resp.status_code == 200
    assert len(resp.json()) == 20


@pytest.mark.asyncio
async def test_limit_and_offset_are_respected():
    _as_user_a()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for i in range(5):
            await client.post("/api/research", json={"raw_question": f"Does treatment {i} help with condition X?"})

        page1 = (await client.get("/api/research?limit=2&offset=0")).json()
        page2 = (await client.get("/api/research?limit=2&offset=2")).json()

    app.dependency_overrides.pop(get_current_user, None)
    assert len(page1) == 2
    assert len(page2) == 2
    assert {p["id"] for p in page1}.isdisjoint({p["id"] for p in page2})


@pytest.mark.asyncio
async def test_limit_above_max_is_rejected():
    _as_user_a()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/research?limit=1000")
    app.dependency_overrides.pop(get_current_user, None)
    assert resp.status_code == 422
