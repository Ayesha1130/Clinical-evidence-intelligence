"""
Report Generation tests. Agent-level tests use a fake LLM (no DB); the
assembly/citation-numbering tests need real DB rows since
generate_report() queries studies/claims/conflicts directly.
"""
import json
import uuid

import pytest
from sqlalchemy import select

from app.agents.base import AgentExecutionError
from app.agents.report_generation import ReportGenerationAgent
from app.db.session import AsyncSessionLocal
from app.models.evidence import EvidenceClaim, EvidenceLink, ResearchReport, Source, Study
from app.models.research import ResearchJob, ResearchQuery
from app.schemas.report import ReportGenerationInput, ReportGenerationOutput
from app.services.report_generation_service import generate_report


class FakeLLM:
    def __init__(self, response: str):
        self._response = response

    async def complete_json(self, system_prompt, user_prompt):
        return self._response

    async def complete_text(self, system_prompt, user_prompt):
        raise NotImplementedError

    async def embed(self, texts):
        raise NotImplementedError


VALID_RESPONSE = json.dumps(
    {
        "executive_summary": "Evidence suggests a cardiovascular benefit.",
        "key_findings_narrative": "Metformin reduced cardiovascular events [1].",
        "evidence_gaps_narrative": "Long-term safety data was not available.",
        "limitations_narrative": "Evidence is abstract-level only.",
        "conclusion": "Available evidence points toward benefit.",
    }
)


def _input(**overrides) -> ReportGenerationInput:
    defaults = dict(
        research_question="Does metformin help?",
        verified_claims=[],
        conflict_count=0,
        evidence_grade="MODERATE",
        studies_considered=1,
    )
    defaults.update(overrides)
    return ReportGenerationInput(**defaults)


@pytest.mark.asyncio
async def test_valid_response_parses_into_output_schema():
    agent = ReportGenerationAgent(FakeLLM(VALID_RESPONSE))
    result = await agent._execute(_input())
    assert isinstance(result, ReportGenerationOutput)
    assert "[1]" in result.key_findings_narrative


@pytest.mark.asyncio
async def test_invalid_json_raises_agent_execution_error():
    agent = ReportGenerationAgent(FakeLLM("not json"))
    with pytest.raises(AgentExecutionError):
        await agent._execute(_input())


def test_blank_sections_fall_back_to_not_reported():
    output = ReportGenerationOutput(
        executive_summary="   ", key_findings_narrative="", evidence_gaps_narrative="x",
        limitations_narrative="y", conclusion="z",
    )
    assert output.executive_summary == "Not reported."
    assert output.key_findings_narrative == "Not reported."


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


@pytest.mark.asyncio
async def test_only_verified_claims_receive_citation_numbers(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        query = ResearchQuery(user_id=_ensure_test_user, raw_question="Does metformin help?", status="RUNNING")
        session.add(query)
        await session.flush()
        job = ResearchJob(research_query_id=query.id, status="RUNNING")
        session.add(job)
        await session.flush()
        source = Source(research_job_id=job.id, source_type="PRIMARY_STUDY", origin="pubmed", external_id="1", title="Study One")
        session.add(source)
        await session.flush()
        study = Study(source_id=source.id, conclusion="Metformin reduced events.")
        session.add(study)
        await session.flush()

        supported_claim = EvidenceClaim(research_job_id=job.id, claim_text="Metformin reduced events.", verification_status="SUPPORTED", confidence=0.9)
        unsupported_claim = EvidenceClaim(research_job_id=job.id, claim_text="Metformin cures everything.", verification_status="NOT_SUPPORTED", confidence=0.0)
        session.add_all([supported_claim, unsupported_claim])
        await session.flush()
        session.add(EvidenceLink(evidence_claim_id=supported_claim.id, study_id=study.id, source_id=source.id, excerpt="reduced events"))
        session.add(EvidenceLink(evidence_claim_id=unsupported_claim.id, study_id=study.id, source_id=source.id, excerpt=None))
        await session.commit()

        report = await generate_report(session, job.id, query, FakeLLM(VALID_RESPONSE), evidence_grade="MODERATE")

        assert len(report.citations) == 1
        assert report.citations[0]["number"] == 1
        assert report.citations[0]["claim_text"] == "Metformin reduced events."
        assert report.citations[0]["study_id"] == str(study.id)
        assert report.sections["research_question"] == "Does metformin help?"
        assert report.sections["evidence_strength"] == "MODERATE"
        assert len(report.sections["studies_analyzed"]) == 1


@pytest.mark.asyncio
async def test_report_with_zero_verified_claims_still_generates(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        query = ResearchQuery(user_id=_ensure_test_user, raw_question="Does X help?", status="RUNNING")
        session.add(query)
        await session.flush()
        job = ResearchJob(research_query_id=query.id, status="RUNNING")
        session.add(job)
        await session.flush()

        report = await generate_report(session, job.id, query, FakeLLM(VALID_RESPONSE), evidence_grade="INSUFFICIENT")
        assert report.citations == []
        assert report.sections["studies_analyzed"] == []
        assert report.evidence_grade == "INSUFFICIENT"


@pytest.mark.asyncio
async def test_report_persists_and_is_queryable(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        query = ResearchQuery(user_id=_ensure_test_user, raw_question="Does X help?", status="RUNNING")
        session.add(query)
        await session.flush()
        job = ResearchJob(research_query_id=query.id, status="RUNNING")
        session.add(job)
        await session.flush()
        report = await generate_report(session, job.id, query, FakeLLM(VALID_RESPONSE), evidence_grade="LIMITED")

        fetched = (await session.execute(select(ResearchReport).where(ResearchReport.id == report.id))).scalar_one()
        assert fetched.research_job_id == job.id
        assert fetched.sections["executive_summary"] == "Evidence suggests a cardiovascular benefit."
