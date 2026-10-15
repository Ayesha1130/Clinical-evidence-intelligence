"""
Integration tests for Phase 4 against a REAL local Postgres database (same
approach as the Phase 3 integration tests). External LLM calls are faked;
everything else — ORM writes, dedup, orchestration, status transitions —
is real.
"""
import json
import uuid

import pytest
from sqlalchemy import select

from app.agents.study_analysis import StudyAnalysisAgent
from app.db.session import AsyncSessionLocal
from app.models.evidence import Document, Source, Study, StudyFinding
from app.models.research import ResearchJob, ResearchQuery
from app.schemas.study_analysis import EvidenceLevel
from app.services.study_analysis_persistence import build_study_analysis_input, persist_study_analysis
from app.services.study_analysis_service import run_study_analysis


class ScriptedLLM:
    """Returns a different canned response per call, keyed by a substring
    match against the study title embedded in the user prompt — lets a
    single test simulate multiple studies getting different (or failing)
    analyses without needing real network access."""

    def __init__(self, responses_by_title_substring: dict[str, str]):
        self._responses = responses_by_title_substring

    async def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        for substring, response in self._responses.items():
            if substring in user_prompt:
                if response == "__RAISE__":
                    raise RuntimeError("Simulated LLM outage for this study.")
                return response
        raise AssertionError(f"No scripted response configured for prompt: {user_prompt[:200]}")

    async def complete_text(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError

    async def embed(self, texts):
        raise NotImplementedError


def _valid_json(**overrides) -> str:
    base = {
        "evidence_level": "abstract_only",
        "study_type": "randomized controlled trial",
        "population": None,
        "sample_size": 200,
        "intervention": None,
        "comparator": None,
        "outcomes": ["cardiovascular events"],
        "follow_up": "12 months",
        "methodology": "Randomized controlled trial.",
        "findings": "Reduced cardiovascular events observed.",
        "effect_size": "HR 0.80",
        "limitations": "Short follow-up.",
        "conclusion": "Supports a protective effect.",
        "relevance_score": 0.9,
        "study_findings": [
            {
                "outcome": "cardiovascular events",
                "effect_direction": "BENEFIT",
                "effect_size": "HR 0.80",
                "confidence": "HIGH",
            }
        ],
    }
    base.update(overrides)
    return json.dumps(base)


async def _make_research_job_with_study(
    session, *, title: str, origin: str, document_text: str | None, user_id: str
) -> tuple[ResearchQuery, ResearchJob, Study]:
    query = ResearchQuery(user_id=user_id, raw_question="Does metformin reduce cardiovascular risk?", status="RUNNING")
    session.add(query)
    await session.flush()

    job = ResearchJob(research_query_id=query.id, status="RUNNING")
    session.add(job)
    await session.flush()

    source = Source(
        research_job_id=job.id,
        source_type="PRIMARY_STUDY",
        origin=origin,
        external_id=str(uuid.uuid4()),
        title=title,
    )
    session.add(source)
    await session.flush()

    study = Study(source_id=source.id)
    session.add(study)
    await session.flush()

    if document_text is not None:
        session.add(Document(study_id=study.id, content=document_text))
        await session.flush()

    await session.commit()
    return query, job, study


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


# ---------- 6. Database persistence ----------


@pytest.mark.asyncio
async def test_persist_study_analysis_writes_study_and_findings(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        _, job, study = await _make_research_job_with_study(
            session,
            title="Metformin RCT",
            origin="pubmed",
            document_text="A 200-patient RCT found metformin reduced cardiovascular events (HR 0.80).",
            user_id=_ensure_test_user,
        )
        source = (await session.execute(select(Source).where(Source.id == study.source_id))).scalar_one()
        document = (await session.execute(select(Document).where(Document.study_id == study.id))).scalar_one()

        agent_input = build_study_analysis_input(
            study=study,
            source=source,
            document=document,
            research_question="Does metformin reduce cardiovascular risk?",
            population_hint=None,
            intervention_hint="metformin",
            comparator_hint=None,
            outcomes_hint=["cardiovascular events"],
        )
        assert agent_input.evidence_level == EvidenceLevel.ABSTRACT_ONLY

        agent = StudyAnalysisAgent(ScriptedLLM({"Metformin RCT": _valid_json()}))
        output = await agent.run(session, job.id, agent_input)

        await persist_study_analysis(session, study, source, output, document)
        await session.commit()

        await session.refresh(study)
        assert study.sample_size == 200
        assert study.effect_size == "HR 0.80"
        assert study.conclusion == "Supports a protective effect."
        assert study.methodology.startswith("[Analysis is based on the abstract only")

        findings = (
            (await session.execute(select(StudyFinding).where(StudyFinding.study_id == study.id))).scalars().all()
        )
        assert len(findings) == 1
        assert findings[0].effect_direction == "BENEFIT"
        assert findings[0].confidence == "HIGH"

        await session.refresh(source)
        assert source.raw_metadata["phase4_analysis"]["evidence_level"] == "abstract_only"
        assert source.raw_metadata["phase4_analysis"]["document_id"] == str(document.id)


@pytest.mark.asyncio
async def test_known_structured_fields_are_not_overwritten_by_llm(_ensure_test_user):
    """A CT.gov-derived sample_size (already known precisely) must survive
    even if the LLM's abstract-based extraction would say something else."""
    async with AsyncSessionLocal() as session:
        _, job, study = await _make_research_job_with_study(
            session,
            title="Metformin CT.gov Trial",
            origin="clinicaltrials",
            document_text="This trial evaluates metformin's cardiovascular effects.",
            user_id=_ensure_test_user,
        )
        study.sample_size = 4200  # already known from CT.gov enrollment count
        await session.commit()

        source = (await session.execute(select(Source).where(Source.id == study.source_id))).scalar_one()
        document = (await session.execute(select(Document).where(Document.study_id == study.id))).scalar_one()

        agent_input = build_study_analysis_input(
            study, source, document, "Does metformin help?", None, None, None, []
        )
        agent = StudyAnalysisAgent(
            ScriptedLLM({"Metformin CT.gov Trial": _valid_json(sample_size=999)})
        )
        output = await agent.run(session, job.id, agent_input)
        await persist_study_analysis(session, study, source, output, document)
        await session.commit()
        await session.refresh(study)

        assert study.sample_size == 4200  # NOT overwritten with the LLM's 999


# ---------- 7. Multiple studies ----------


@pytest.mark.asyncio
async def test_run_study_analysis_handles_multiple_studies(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        query = ResearchQuery(
            user_id=_ensure_test_user, raw_question="Does metformin reduce cardiovascular risk?", status="RUNNING"
        )
        session.add(query)
        await session.flush()
        job = ResearchJob(research_query_id=query.id, status="RUNNING")
        session.add(job)
        await session.flush()

        studies = []
        for i, title in enumerate(["Study Alpha", "Study Beta"]):
            source = Source(
                research_job_id=job.id, source_type="PRIMARY_STUDY", origin="pubmed",
                external_id=f"pmid-{i}", title=title,
            )
            session.add(source)
            await session.flush()
            study = Study(source_id=source.id)
            session.add(study)
            await session.flush()
            session.add(Document(study_id=study.id, content=f"Findings text for {title}."))
            studies.append(study)
        await session.commit()

        llm = ScriptedLLM(
            {
                "Study Alpha": _valid_json(conclusion="Alpha conclusion"),
                "Study Beta": _valid_json(conclusion="Beta conclusion"),
            }
        )
        summary = await run_study_analysis(session, job.id, query, llm)

        assert summary.analyzed == 2
        assert summary.failed == []

        for study in studies:
            await session.refresh(study)
        conclusions = {s.conclusion for s in studies}
        assert conclusions == {"Alpha conclusion", "Beta conclusion"}


# ---------- 8. Agent failure without crashing the whole job ----------


@pytest.mark.asyncio
async def test_one_study_failing_analysis_does_not_block_others(_ensure_test_user):
    async with AsyncSessionLocal() as session:
        query = ResearchQuery(
            user_id=_ensure_test_user, raw_question="Does metformin reduce cardiovascular risk?", status="RUNNING"
        )
        session.add(query)
        await session.flush()
        job = ResearchJob(research_query_id=query.id, status="RUNNING")
        session.add(job)
        await session.flush()

        good_source = Source(
            research_job_id=job.id, source_type="PRIMARY_STUDY", origin="pubmed",
            external_id="pmid-good", title="Good Study",
        )
        bad_source = Source(
            research_job_id=job.id, source_type="PRIMARY_STUDY", origin="pubmed",
            external_id="pmid-bad", title="Bad Study",
        )
        session.add_all([good_source, bad_source])
        await session.flush()

        good_study = Study(source_id=good_source.id)
        bad_study = Study(source_id=bad_source.id)
        session.add_all([good_study, bad_study])
        await session.flush()

        session.add(Document(study_id=good_study.id, content="Good study findings text."))
        session.add(Document(study_id=bad_study.id, content="Bad study findings text."))
        await session.commit()

        llm = ScriptedLLM(
            {
                "Good Study": _valid_json(conclusion="Good conclusion"),
                "Bad Study": "__RAISE__",  # simulates an LLM outage for this one study
            }
        )

        summary = await run_study_analysis(session, job.id, query, llm)

        assert summary.analyzed == 1
        assert len(summary.failed) == 1
        assert summary.failed[0]["title"] == "Bad Study"
        assert "Simulated LLM outage" in summary.failed[0]["error"]

        await session.refresh(good_study)
        assert good_study.conclusion == "Good conclusion"

        # The bad study's row must be untouched (still null), not partially
        # written or corrupted by the failed attempt.
        await session.refresh(bad_study)
        assert bad_study.conclusion is None

        # Both attempts were logged to agent_runs regardless of outcome.
        from app.models.research import AgentRun

        runs = (
            (
                await session.execute(
                    select(AgentRun).where(
                        AgentRun.research_job_id == job.id, AgentRun.agent_name == "study_analysis"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(runs) == 2
        statuses = {r.status for r in runs}
        assert statuses == {"completed", "failed"}
