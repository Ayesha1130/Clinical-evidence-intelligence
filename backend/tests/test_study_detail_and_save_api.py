"""
API tests for Phase 7 study detail + bookmark endpoints, ownership enforced
the same way as every other resource.
"""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.security import CurrentUser, get_current_user
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.evidence import ResearchReport, Source, Study
from app.models.research import ResearchJob, ResearchQuery

USER_A = str(uuid.uuid4())
USER_B = str(uuid.uuid4())


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


async def _make_study(user_id: str):
    async with AsyncSessionLocal() as session:
        query = ResearchQuery(user_id=user_id, raw_question="Does X help?", status="COMPLETED")
        session.add(query)
        await session.flush()
        job = ResearchJob(research_query_id=query.id, status="COMPLETED", evidence_grade="MODERATE")
        session.add(job)
        await session.flush()
        source = Source(
            research_job_id=job.id, source_type="PRIMARY_STUDY", origin="pubmed",
            external_id="123", title="Metformin Study", url="https://pubmed.ncbi.nlm.nih.gov/123/",
            raw_metadata={"authors": ["Jane Smith"], "doi": "10.1/example"},
        )
        session.add(source)
        await session.flush()
        study = Study(source_id=source.id, conclusion="Metformin helps.", relevance_score=0.8)
        session.add(study)
        await session.flush()
        report = ResearchReport(
            research_job_id=job.id,
            sections={"research_question": "Does X help?"},
            citations=[],
            evidence_grade="MODERATE",
        )
        session.add(report)
        await session.commit()
        return study.id, report.id


def _as_user(user_id: str):
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=user_id, email="u@example.com")


# ---------- Study detail ----------


@pytest.mark.asyncio
async def test_study_detail_includes_authors_and_doi_from_raw_metadata():
    study_id, _ = await _make_study(USER_A)
    _as_user(USER_A)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/studies/{study_id}")
    app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["authors"] == ["Jane Smith"]
    assert data["doi"] == "10.1/example"
    assert data["conclusion"] == "Metformin helps."


@pytest.mark.asyncio
async def test_other_user_cannot_view_study_detail():
    study_id, _ = await _make_study(USER_A)
    _as_user(USER_B)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/studies/{study_id}")
    app.dependency_overrides.pop(get_current_user, None)
    assert resp.status_code == 404


# ---------- Save / unsave study ----------


@pytest.mark.asyncio
async def test_save_and_unsave_study_is_idempotent():
    study_id, _ = await _make_study(USER_A)
    _as_user(USER_A)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post(f"/api/studies/{study_id}/save")
        r2 = await client.post(f"/api/studies/{study_id}/save")
        r3 = await client.delete(f"/api/studies/{study_id}/save")
        r4 = await client.delete(f"/api/studies/{study_id}/save")
    app.dependency_overrides.pop(get_current_user, None)

    assert r1.status_code == 200 and r1.json()["saved"] is True
    assert r2.status_code == 200 and r2.json()["saved"] is True
    assert r3.status_code == 200 and r3.json()["saved"] is False
    assert r4.status_code == 200 and r4.json()["saved"] is False


@pytest.mark.asyncio
async def test_other_user_cannot_save_someone_elses_study():
    study_id, _ = await _make_study(USER_A)
    _as_user(USER_B)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/studies/{study_id}/save")
    app.dependency_overrides.pop(get_current_user, None)
    assert resp.status_code == 404


# ---------- Report fetch / save ----------


@pytest.mark.asyncio
async def test_owner_can_fetch_and_save_their_report():
    _, report_id = await _make_study(USER_A)
    _as_user(USER_A)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        get_resp = await client.get(f"/api/reports/{report_id}")
        save_resp = await client.post(f"/api/reports/{report_id}/save")
    app.dependency_overrides.pop(get_current_user, None)

    assert get_resp.status_code == 200
    assert get_resp.json()["sections"]["research_question"] == "Does X help?"
    assert save_resp.json()["saved"] is True


@pytest.mark.asyncio
async def test_other_user_cannot_fetch_someone_elses_report():
    _, report_id = await _make_study(USER_A)
    _as_user(USER_B)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/reports/{report_id}")
    app.dependency_overrides.pop(get_current_user, None)
    assert resp.status_code == 404
