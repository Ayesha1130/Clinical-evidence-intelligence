"""
End-to-end test of the ENTIRE pipeline through the real HTTP API:
Question -> Query Analyzer -> PubMed/ClinicalTrials.gov/Tavily ->
normalization/dedup -> Study Analysis -> study_findings, exactly as a real
request to POST /api/research/{id}/start would trigger. Real Postgres,
real routing/auth, only the outbound LLM and external-source HTTP calls
are faked.
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

QUERY_ANALYZER_RESPONSE = json.dumps(
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
            "web": [],  # no Tavily queries -> exercises the "unavailable, no queries" path
        },
    }
)


def _study_analysis_response(conclusion: str) -> str:
    return json.dumps(
        {
            "evidence_level": "abstract_only",
            "study_type": "randomized controlled trial",
            "population": None,
            "sample_size": None,
            "intervention": None,
            "comparator": None,
            "outcomes": ["cardiovascular events"],
            "follow_up": None,
            "methodology": "Randomized controlled trial per the abstract.",
            "findings": "Metformin reduced cardiovascular events.",
            "effect_size": "HR 0.82",
            "limitations": "Not reported",
            "conclusion": conclusion,
            "relevance_score": 0.9,
            "study_findings": [
                {
                    "outcome": "cardiovascular events",
                    "effect_direction": "BENEFIT",
                    "effect_size": "HR 0.82",
                    "confidence": "HIGH",
                }
            ],
        }
    )


class DispatchingFakeLLM:
    """Routes to the right canned response based on which system prompt the
    caller used — mirrors how the real pipeline calls the same LLMClient
    interface for four different agents (query analyzer, study analysis,
    claim extraction, evidence verification)."""

    async def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        if "biomedical research question analyzer" in system_prompt:
            return QUERY_ANALYZER_RESPONSE
        if "biomedical evidence extraction system" in system_prompt:
            return _study_analysis_response("Metformin shows a cardiovascular benefit in this trial.")
        if "extract important, evidence-based factual claims" in system_prompt:
            return json.dumps({"claims": ["Metformin reduced cardiovascular events compared to placebo."]})
        if "evidence verification system" in system_prompt:
            # Quote a substring that genuinely appears in both PubMed and
            # CT.gov's canned document text below, so the programmatic
            # grounding check in EvidenceVerificationAgent passes for real.
            return json.dumps(
                {
                    "verification_status": "SUPPORTED",
                    "confidence": 0.9,
                    "supporting_excerpt": "metformin reduced cardiovascular events",
                }
            )
        if "narrative sections of a medical evidence" in system_prompt:
            return json.dumps(
                {
                    "executive_summary": "Available verified evidence suggests a cardiovascular benefit.",
                    "key_findings_narrative": "Metformin reduced cardiovascular events across the studies reviewed.",
                    "evidence_gaps_narrative": "Long-term outcomes beyond the studied follow-up were not assessed.",
                    "limitations_narrative": "Evidence is based on abstract/summary-level text rather than full papers.",
                    "conclusion": "Available evidence points toward a cardiovascular benefit, pending further review.",
                }
            )
        raise AssertionError("Unexpected system prompt routed to fake LLM.")

    async def complete_text(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError

    async def embed(self, texts):
        raise NotImplementedError


PUBMED_ESEARCH_RESPONSE = {"esearchresult": {"idlist": ["2002"]}}
PUBMED_EFETCH_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>2002</PMID>
      <Article>
        <ArticleTitle>Metformin Cardiovascular Outcomes Trial</ArticleTitle>
        <Journal><Title>Diabetes Care</Title><JournalIssue><PubDate><Year>2023</Year></PubDate></JournalIssue></Journal>
        <AbstractText>Metformin reduced cardiovascular events in a randomized trial of adults with T2D.</AbstractText>
        <PublicationTypeList><PublicationType>Randomized Controlled Trial</PublicationType></PublicationTypeList>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""
CTGOV_RESPONSE = {
    "studies": [
        {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT07777777", "briefTitle": "Metformin CV Trial"},
                "designModule": {"enrollmentInfo": {"count": 1500}},
                "descriptionModule": {"briefSummary": "Evaluates metformin's cardiovascular effects in T2D patients."},
            }
        }
    ]
}

_ORIGINAL_GET = httpx.AsyncClient.get
_ORIGINAL_POST = httpx.AsyncClient.post


async def fake_get(self, url, params=None, **kwargs):
    url_str = str(url)
    if "esearch.fcgi" in url_str:
        return httpx.Response(200, json=PUBMED_ESEARCH_RESPONSE, request=httpx.Request("GET", url))
    if "efetch.fcgi" in url_str:
        return httpx.Response(200, text=PUBMED_EFETCH_XML, request=httpx.Request("GET", url))
    if "clinicaltrials.gov" in url_str:
        return httpx.Response(200, json=CTGOV_RESPONSE, request=httpx.Request("GET", url))
    return await _ORIGINAL_GET(self, url, params=params, **kwargs)


async def fake_post(self, url, json=None, **kwargs):
    return await _ORIGINAL_POST(self, url, json=json, **kwargs)


@pytest.fixture(autouse=True)
def _mock_http(monkeypatch):
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    monkeypatch.setattr("app.services.pipeline_service.get_llm_client", lambda: DispatchingFakeLLM())


class FakeEmbeddingClient:
    """Deterministic fake — no real network call, but exercises the same
    code path (chunking -> embed -> store) with a fixed-dimension vector."""

    async def embed(self, texts):
        return [[0.01] * 1536 for _ in texts]


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
def _override_auth():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=TEST_USER_ID, email="t@example.com")
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
async def _clean_state():
    async with AsyncSessionLocal() as session:
        await session.execute(text("DELETE FROM research_queries"))
        await session.execute(text("DELETE FROM auth.users WHERE id = :uid"), {"uid": TEST_USER_ID})
        await session.execute(text("INSERT INTO auth.users (id) VALUES (:uid)"), {"uid": TEST_USER_ID})
        await session.commit()
    yield
    from app.db.session import engine

    await engine.dispose()


@pytest.mark.asyncio
async def test_full_pipeline_through_study_analysis_reaches_completed():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/research",
            json={"raw_question": "Does metformin reduce cardiovascular risk in patients with type 2 diabetes?"},
        )
        query_id = create_resp.json()["id"]

        start_resp = await client.post(f"/api/research/{query_id}/start")
        assert start_resp.status_code == 202, start_resp.text
        job = await wait_for_terminal_status(client, query_id)

        # No Tavily queries were generated (web: [] above) and PubMed +
        # ClinicalTrials.gov both succeed with no study-analysis failures,
        # so this should reach COMPLETED, not get stuck at PARTIAL forever.
        assert job["status"] == "COMPLETED", job["failure_summary"]
        assert "analyzed" in job["failure_summary"]

        studies = (await client.get(f"/api/research/{query_id}/studies")).json()
        assert len(studies) == 2
        for study in studies:
            assert study["conclusion"] == "Metformin shows a cardiovascular benefit in this trial."
            assert len(study["study_findings"]) == 1
            assert study["study_findings"][0]["effect_direction"] == "BENEFIT"

        # Both the source agents and the per-study analysis agent runs exist.
        agent_names = {r["agent_name"] for r in (await client.get(f"/api/research/{query_id}/agent-runs")).json()}
        assert {"query_analyzer", "pubmed_research", "clinical_trials_research", "study_analysis"} <= agent_names
