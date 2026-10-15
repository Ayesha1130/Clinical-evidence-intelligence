"""
Evidence Map tests — real DB, since build_evidence_map queries studies/
conflicts directly.
"""
import uuid

import pytest

from app.db.session import AsyncSessionLocal
from app.models.evidence import Conflict, Source, Study, StudyFinding
from app.models.research import ResearchJob, ResearchQuery
from app.services.evidence_map_service import build_evidence_map


@pytest.fixture(autouse=True)
async def _ensure_test_user():
    user_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as session:
        from sqlalchemy import text

        await session.execute(text("INSERT INTO auth.users (id) VALUES (:uid)"), {"uid": user_id})
        await session.commit()
    yield user_id


@pytest.fixture(autouse=True)
async def _dispose_engine_after():
    yield
    from app.db.session import engine

    await engine.dispose()


async def _make_job(session, user_id):
    query = ResearchQuery(user_id=user_id, raw_question="Does metformin help?", status="RUNNING")
    session.add(query)
    await session.flush()
    job = ResearchJob(research_query_id=query.id, status="RUNNING")
    session.add(job)
    await session.flush()
    return query, job


async def _make_study(session, job, *, title, direction=None):
    source = Source(research_job_id=job.id, source_type="PRIMARY_STUDY", origin="pubmed", external_id=str(uuid.uuid4()), title=title)
    session.add(source)
    await session.flush()
    study = Study(source_id=source.id, relevance_score=0.8)
    session.add(study)
    await session.flush()
    if direction:
        session.add(StudyFinding(study_id=study.id, outcome="cardiovascular events", effect_direction=direction, confidence="HIGH"))
    await session.commit()
    return study


@pytest.mark.asyncio
async def test_map_includes_center_question_node_and_study_nodes(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        query, job = await _make_job(session, _ensure_test_user)
        study = await _make_study(session, job, title="Study A", direction="BENEFIT")

        result = await build_evidence_map(session, job.id, query.raw_question)
        assert result["nodes"][0]["id"] == "research_question"
        assert result["nodes"][0]["type"] == "question"
        study_node = next(n for n in result["nodes"] if n["id"] == str(study.id))
        assert study_node["effect_direction"] == "BENEFIT"
        assert study_node["has_conflict"] is False

        edge = next(e for e in result["edges"] if e["target"] == str(study.id))
        assert edge["source"] == "research_question"
        assert edge["type"] == "informs"


@pytest.mark.asyncio
async def test_conflicting_studies_are_marked_and_get_a_conflict_edge(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        query, job = await _make_job(session, _ensure_test_user)
        study_a = await _make_study(session, job, title="Study A", direction="BENEFIT")
        study_b = await _make_study(session, job, title="Study B", direction="HARM")
        session.add(
            Conflict(
                research_job_id=job.id, study_a_id=study_a.id, study_b_id=study_b.id,
                conflicting_outcome="cardiovascular events", finding_a="BENEFIT", finding_b="HARM",
                possible_explanation="Reason for disagreement not established from available evidence.",
                confidence=0.9,
            )
        )
        await session.commit()

        result = await build_evidence_map(session, job.id, query.raw_question)
        node_a = next(n for n in result["nodes"] if n["id"] == str(study_a.id))
        node_b = next(n for n in result["nodes"] if n["id"] == str(study_b.id))
        assert node_a["has_conflict"] is True
        assert node_b["has_conflict"] is True

        conflict_edges = [e for e in result["edges"] if e["type"] == "conflict"]
        assert len(conflict_edges) == 1
        assert {conflict_edges[0]["source"], conflict_edges[0]["target"]} == {str(study_a.id), str(study_b.id)}


@pytest.mark.asyncio
async def test_study_with_no_findings_has_null_effect_direction(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        query, job = await _make_job(session, _ensure_test_user)
        study = await _make_study(session, job, title="Study With No Findings")

        result = await build_evidence_map(session, job.id, query.raw_question)
        node = next(n for n in result["nodes"] if n["id"] == str(study.id))
        assert node["effect_direction"] is None


@pytest.mark.asyncio
async def test_mixed_findings_within_one_study_report_unclear(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        query, job = await _make_job(session, _ensure_test_user)
        study = await _make_study(session, job, title="Mixed Study")
        session.add(StudyFinding(study_id=study.id, outcome="A", effect_direction="BENEFIT", confidence="HIGH"))
        session.add(StudyFinding(study_id=study.id, outcome="B", effect_direction="HARM", confidence="HIGH"))
        await session.commit()

        result = await build_evidence_map(session, job.id, query.raw_question)
        node = next(n for n in result["nodes"] if n["id"] == str(study.id))
        assert node["effect_direction"] == "UNCLEAR"


@pytest.mark.asyncio
async def test_empty_job_returns_only_the_question_node(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        query, job = await _make_job(session, _ensure_test_user)
        result = await build_evidence_map(session, job.id, query.raw_question)
        assert len(result["nodes"]) == 1
        assert result["edges"] == []
