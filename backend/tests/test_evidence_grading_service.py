"""
Integration tests for Evidence Grading — needs real DB rows (studies,
sources, study_findings, evidence_claims, conflicts) since the grading
function queries them directly. Same real-Postgres approach as other
Phase 3/4 integration tests.
"""
import uuid

import pytest

from app.db.session import AsyncSessionLocal
from app.models.evidence import Conflict, EvidenceClaim, Source, Study, StudyFinding
from app.models.research import ResearchJob, ResearchQuery
from app.services.evidence_grading_service import compute_evidence_grade


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


async def _make_job(session, user_id) -> ResearchJob:
    query = ResearchQuery(user_id=user_id, raw_question="Does X help with Y?", status="RUNNING")
    session.add(query)
    await session.flush()
    job = ResearchJob(research_query_id=query.id, status="RUNNING")
    session.add(job)
    await session.flush()
    return job


async def _make_study(session, job, *, source_type: str, relevance_score, findings):
    """findings: list of (outcome, direction, effect_size)"""
    source = Source(
        research_job_id=job.id, source_type=source_type, origin="pubmed",
        external_id=str(uuid.uuid4()), title=f"Study {uuid.uuid4()}",
    )
    session.add(source)
    await session.flush()
    study = Study(source_id=source.id, relevance_score=relevance_score)
    session.add(study)
    await session.flush()
    for outcome, direction, effect_size in findings:
        session.add(
            StudyFinding(
                study_id=study.id, outcome=outcome, effect_direction=direction,
                effect_size=effect_size, confidence="HIGH",
            )
        )
    await session.commit()
    return study


async def _make_claim(session, job, *, status: str, confidence: float = 0.9):
    session.add(
        EvidenceClaim(research_job_id=job.id, claim_text="Some claim.", verification_status=status, confidence=confidence)
    )
    await session.commit()


# ---------- 1. Strong consistent evidence ----------


@pytest.mark.asyncio
async def test_strong_grade_for_high_quality_consistent_well_verified_evidence(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        job = await _make_job(session, _ensure_test_user)
        for _ in range(3):
            await _make_study(
                session, job, source_type="SYSTEMATIC_REVIEW", relevance_score=0.95,
                findings=[("cardiovascular events", "BENEFIT", "HR 0.8")],
            )
        for _ in range(5):
            await _make_claim(session, job, status="SUPPORTED")

        breakdown = await compute_evidence_grade(session, job.id)
        assert breakdown.grade == "STRONG"
        assert breakdown.conflict_count == 0


# ---------- 2. Moderate evidence ----------


@pytest.mark.asyncio
async def test_moderate_grade_for_mixed_quality_mostly_verified_evidence(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        job = await _make_job(session, _ensure_test_user)
        await _make_study(
            session, job, source_type="PRIMARY_STUDY", relevance_score=0.7,
            findings=[("cardiovascular events", "BENEFIT", None)],
        )
        await _make_study(
            session, job, source_type="CLINICAL_TRIAL", relevance_score=0.6,
            findings=[("cardiovascular events", "BENEFIT", None)],
        )
        await _make_claim(session, job, status="SUPPORTED")
        await _make_claim(session, job, status="PARTIALLY_SUPPORTED")

        breakdown = await compute_evidence_grade(session, job.id)
        assert breakdown.grade in ("MODERATE", "STRONG")
        assert breakdown.grade != "INSUFFICIENT"


# ---------- 3. Limited evidence ----------


@pytest.mark.asyncio
async def test_limited_grade_for_low_quality_or_weakly_verified_evidence(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        job = await _make_job(session, _ensure_test_user)
        await _make_study(
            session, job, source_type="GENERAL_WEB", relevance_score=0.4,
            findings=[("cardiovascular events", "UNCLEAR", None)],
        )
        await _make_claim(session, job, status="NOT_SUPPORTED")
        await _make_claim(session, job, status="SUPPORTED")

        breakdown = await compute_evidence_grade(session, job.id)
        assert breakdown.grade in ("LIMITED", "INSUFFICIENT")


# ---------- 4. Insufficient evidence ----------


@pytest.mark.asyncio
async def test_insufficient_grade_when_no_claims_were_verified(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        job = await _make_job(session, _ensure_test_user)
        await _make_study(
            session, job, source_type="PRIMARY_STUDY", relevance_score=0.8,
            findings=[("cardiovascular events", "BENEFIT", None)],
        )
        breakdown = await compute_evidence_grade(session, job.id)
        assert breakdown.grade == "INSUFFICIENT"
        assert breakdown.total_claims == 0


@pytest.mark.asyncio
async def test_insufficient_grade_when_no_study_has_real_content(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        job = await _make_job(session, _ensure_test_user)
        source = Source(
            research_job_id=job.id, source_type="GENERAL_WEB", origin="tavily", external_id="x", title="Empty"
        )
        session.add(source)
        await session.flush()
        session.add(Study(source_id=source.id))
        await session.commit()

        breakdown = await compute_evidence_grade(session, job.id)
        assert breakdown.grade == "INSUFFICIENT"
        assert breakdown.studies_with_real_content == 0


# ---------- 5. High conflict scenario ----------


@pytest.mark.asyncio
async def test_high_conflict_scenario_pulls_grade_down(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        job = await _make_job(session, _ensure_test_user)
        study_a = await _make_study(
            session, job, source_type="SYSTEMATIC_REVIEW", relevance_score=0.9,
            findings=[("cardiovascular events", "BENEFIT", None)],
        )
        study_b = await _make_study(
            session, job, source_type="SYSTEMATIC_REVIEW", relevance_score=0.9,
            findings=[("cardiovascular events", "HARM", None)],
        )
        for _ in range(4):
            await _make_claim(session, job, status="SUPPORTED")
        session.add(
            Conflict(
                research_job_id=job.id, study_a_id=study_a.id, study_b_id=study_b.id,
                conflicting_outcome="cardiovascular events", finding_a="BENEFIT", finding_b="HARM",
                possible_explanation="Reason for disagreement not established from available evidence.",
                confidence=0.9,
            )
        )
        await session.commit()

        breakdown_with_conflict = await compute_evidence_grade(session, job.id)

        job2 = await _make_job(session, _ensure_test_user)
        await _make_study(
            session, job2, source_type="SYSTEMATIC_REVIEW", relevance_score=0.9,
            findings=[("cardiovascular events", "BENEFIT", None)],
        )
        await _make_study(
            session, job2, source_type="SYSTEMATIC_REVIEW", relevance_score=0.9,
            findings=[("cardiovascular events", "BENEFIT", None)],
        )
        for _ in range(4):
            await _make_claim(session, job2, status="SUPPORTED")
        breakdown_without_conflict = await compute_evidence_grade(session, job2.id)

        assert breakdown_with_conflict.consistency_score < breakdown_without_conflict.consistency_score
        assert breakdown_with_conflict.composite_score < breakdown_without_conflict.composite_score


# ---------- 6. Missing evidence scenario ----------


@pytest.mark.asyncio
async def test_missing_evidence_scenario_no_studies_at_all(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        job = await _make_job(session, _ensure_test_user)
        breakdown = await compute_evidence_grade(session, job.id)
        assert breakdown.grade == "INSUFFICIENT"
        assert breakdown.studies_considered == 0


def test_explanation_is_always_machine_readable_dict():
    from app.services.evidence_grading_service import GradingBreakdown

    breakdown = GradingBreakdown(grade="MODERATE")
    d = breakdown.to_dict()
    assert d["grade"] == "MODERATE"
    assert "methodology_note" in d
    assert "not an official clinical guideline" in d["methodology_note"].lower()
