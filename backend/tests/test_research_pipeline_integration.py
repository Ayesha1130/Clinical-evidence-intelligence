"""
Full-flow integration test against a REAL local Postgres database (with the
actual migration files applied — see supabase/migrations/). External HTTP
calls to NCBI/ClinicalTrials.gov/Tavily are mocked at the httpx layer (this
sandbox has no network access to those domains), and the OpenAI call inside
the Query Analyzer is swapped for a fake LLM client — everything else
(routing, auth, ORM writes, dedup logic, status transitions) is real.
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
from tests.pipeline_test_utils import wait_for_terminal_status

TEST_USER_ID = str(uuid.uuid4())


class FakeQueryAnalyzerLLM:
    """Deterministic stand-in for OpenAILLMClient — the agent's own JSON
    parsing/validation logic still runs for real against this output."""

    async def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        return json.dumps(
            {
                "is_researchable": True,
                "safety_note": None,
                "population": "adults with type 2 diabetes",
                "intervention": "metformin",
                "comparator": "placebo",
                "outcomes": ["cardiovascular events"],
                "study_types": ["randomized controlled trial"],
                "evidence_requirements": [],
                "search_queries": {
                    "pubmed": ["metformin cardiovascular type 2 diabetes"],
                    "clinical_trials": ["metformin cardiovascular"],
                    "web": ["metformin cardiovascular systematic review"],
                },
            }
        )

    async def complete_text(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError

    async def embed(self, texts):
        raise NotImplementedError


PUBMED_ESEARCH_RESPONSE = {"esearchresult": {"idlist": ["1001"]}}

PUBMED_EFETCH_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>1001</PMID>
      <Article>
        <ArticleTitle>Metformin Reduces Cardiovascular Events in Type 2 Diabetes</ArticleTitle>
        <Journal><Title>Diabetes Care</Title>
          <JournalIssue><PubDate><Year>2021</Year></PubDate></JournalIssue>
        </Journal>
        <AbstractText>Metformin was associated with fewer cardiovascular events.</AbstractText>
        <PublicationTypeList>
          <PublicationType>Randomized Controlled Trial</PublicationType>
        </PublicationTypeList>
      </Article>
      <ArticleIdList><ArticleId IdType="doi">10.1000/metformin-cv</ArticleId></ArticleIdList>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""

CTGOV_RESPONSE = {
    "studies": [
        {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT05555555", "briefTitle": "Metformin CV Outcomes Trial"},
                "statusModule": {"overallStatus": "COMPLETED"},
                "conditionsModule": {"conditions": ["Type 2 Diabetes"]},
                "designModule": {"enrollmentInfo": {"count": 3000}, "phases": ["PHASE4"]},
                "armsInterventionsModule": {"interventions": [{"name": "Metformin"}]},
                "outcomesModule": {"primaryOutcomes": [{"measure": "MACE"}]},
                "descriptionModule": {"briefSummary": "Evaluates metformin's cardiovascular effect."},
            }
        }
    ]
}

TAVILY_RESPONSE = {
    "results": [
        {
            "title": "Metformin and Cardiovascular Risk: A Systematic Review",
            "url": "https://www.nih.gov/metformin-review",
            "content": "A systematic review of metformin's cardiovascular effects.",
            "score": 0.88,
        },
        # Deliberately duplicates the PubMed title above (case/punctuation
        # differences) to prove cross-source dedup actually runs.
        {
            "title": "Metformin Reduces Cardiovascular Events in Type 2 Diabetes",
            "url": "https://some-aggregator.com/dup",
            "content": "Aggregator summary of the same finding.",
            "score": 0.5,
        },
    ]
}


async def fake_get(self, url, params=None, **kwargs):
    url_str = str(url)
    if "esearch.fcgi" in url_str:
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=PUBMED_ESEARCH_RESPONSE, request=request)
    if "efetch.fcgi" in url_str:
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, text=PUBMED_EFETCH_XML, request=request)
    if "clinicaltrials.gov" in url_str:
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=CTGOV_RESPONSE, request=request)
    # Anything else (our own ASGI-transport test client hitting the app
    # itself) falls through to the real implementation.
    return await _ORIGINAL_ASYNC_CLIENT_GET(self, url, params=params, **kwargs)


async def fake_post(self, url, json=None, **kwargs):
    url_str = str(url)
    if "api.tavily.com" in url_str:
        request = httpx.Request("POST", url)
        return httpx.Response(200, json=TAVILY_RESPONSE, request=request)
    return await _ORIGINAL_ASYNC_CLIENT_POST(self, url, json=json, **kwargs)


_ORIGINAL_ASYNC_CLIENT_GET = httpx.AsyncClient.get
_ORIGINAL_ASYNC_CLIENT_POST = httpx.AsyncClient.post


@pytest.fixture(autouse=True)
def _mock_external_http(monkeypatch):
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    monkeypatch.setattr("app.services.pipeline_service.get_llm_client", lambda: FakeQueryAnalyzerLLM())


@pytest.fixture(autouse=True)
def _configure_tavily_key(monkeypatch):
    # Exercise the "configured and succeeding" path here; the missing-key
    # path is covered separately in test_tavily_client.py.
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily-key")
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _override_auth():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=TEST_USER_ID, email="test@example.com")
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
async def _clean_tables():
    async with AsyncSessionLocal() as session:
        await session.execute(text("DELETE FROM research_queries"))
        await session.execute(text("DELETE FROM auth.users WHERE id = :uid"), {"uid": TEST_USER_ID})
        await session.execute(text("INSERT INTO auth.users (id) VALUES (:uid)"), {"uid": TEST_USER_ID})
        await session.commit()
    yield


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    # Each pytest-asyncio test runs its own event loop (function scope);
    # pooled asyncpg connections from a prior test's loop can't be reused
    # safely, so start each test with a clean connection pool.
    yield
    from app.db.session import engine

    await engine.dispose()


@pytest.mark.asyncio
async def test_full_pipeline_question_to_normalized_deduped_studies():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/research",
            json={"raw_question": "Does metformin reduce cardiovascular risk in patients with type 2 diabetes?"},
        )
        assert create_resp.status_code == 201, create_resp.text
        query_id = create_resp.json()["id"]

        start_resp = await client.post(f"/api/research/{query_id}/start")
        assert start_resp.status_code == 202, start_resp.text
        job = await wait_for_terminal_status(client, query_id)

        # Phase 4+ agents aren't implemented yet, so the job is PARTIAL by
        # design — but source retrieval itself must have succeeded.
        assert job["status"] == "PARTIAL"
        assert "PubMed: 1" in job["failure_summary"]

        studies_resp = await client.get(f"/api/research/{query_id}/studies")
        assert studies_resp.status_code == 200, studies_resp.text
        studies = studies_resp.json()

        # 1 PubMed article + 1 CT.gov trial + 2 Tavily results, one of which
        # (the aggregator hit) is a genuine duplicate of the PubMed article's
        # title => 3 unique studies stored, not 4.
        assert len(studies) == 3, studies

        origins = {s["origin"] for s in studies}
        assert origins == {"pubmed", "clinicaltrials", "tavily"}

        pubmed_study = next(s for s in studies if s["origin"] == "pubmed")
        assert pubmed_study["external_id"] == "1001"
        assert pubmed_study["source_type"] == "PRIMARY_STUDY"

        ct_study = next(s for s in studies if s["origin"] == "clinicaltrials")
        assert ct_study["external_id"] == "NCT05555555"
        assert ct_study["source_type"] == "CLINICAL_TRIAL"
        assert ct_study["sample_size"] == 3000

        tavily_study = next(s for s in studies if s["origin"] == "tavily")
        # The surviving Tavily study must be the genuinely distinct NIH
        # review, not the aggregator's duplicate of the PubMed article.
        assert tavily_study["external_id"] == "https://www.nih.gov/metformin-review"
        assert tavily_study["source_type"] == "OFFICIAL_MEDICAL_SOURCE"

        # Agent runs were actually logged for each independent source agent.
        runs_resp = await client.get(f"/api/research/{query_id}/agent-runs")
        agent_names = {r["agent_name"] for r in runs_resp.json()}
        assert {"query_analyzer", "pubmed_research", "clinical_trials_research", "web_research"} <= agent_names


@pytest.mark.asyncio
async def test_pipeline_continues_when_tavily_key_missing(monkeypatch):
    """One source (web research) being unconfigured must not fail the job
    or block PubMed/ClinicalTrials.gov results from being stored."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    from app.core.config import get_settings

    get_settings.cache_clear()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/research", json={"raw_question": "Does metformin reduce cardiovascular risk in type 2 diabetes?"}
        )
        query_id = create_resp.json()["id"]

        start_resp = await client.post(f"/api/research/{query_id}/start")
        assert start_resp.status_code == 202
        job = await wait_for_terminal_status(client, query_id)
        assert job["status"] == "PARTIAL"
        assert "unavailable" in job["failure_summary"].lower()

        studies = (await client.get(f"/api/research/{query_id}/studies")).json()
        # Without Tavily, the PubMed/Tavily duplicate never gets a chance to
        # arrive as a dupe — we should still get exactly the PubMed + CT.gov studies.
        assert len(studies) == 2
        assert {s["origin"] for s in studies} == {"pubmed", "clinicaltrials"}

    get_settings.cache_clear()
