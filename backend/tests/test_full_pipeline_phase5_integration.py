"""
Full end-to-end test of the Phase 5 pipeline through the real HTTP API:
Question -> Query Analyzer -> PubMed/ClinicalTrials.gov -> Study Analysis
-> Claim Extraction -> Evidence Verification -> Conflict Detection ->
Evidence Grading, then reads back through every Phase 5 endpoint
(/evidence, /conflicts, /grade, /api/studies/{id}/evidence).

The two studies are deliberately given opposite effect directions on the
same outcome so conflict detection has something real to find.
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
            "web": [],
        },
    }
)


def _study_analysis_response(direction: str, conclusion: str) -> str:
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
            "findings": f"Effect on cardiovascular events: {direction}.",
            "effect_size": "HR 0.82" if direction == "BENEFIT" else None,
            "limitations": "Not reported",
            "conclusion": conclusion,
            "relevance_score": 0.9,
            "study_findings": [
                {
                    "outcome": "cardiovascular events",
                    "effect_direction": direction,
                    "effect_size": "HR 0.82" if direction == "BENEFIT" else None,
                    "confidence": "HIGH",
                }
            ],
        }
    )


class DispatchingFakeLLM:
    async def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        if "biomedical research question analyzer" in system_prompt:
            return QUERY_ANALYZER_RESPONSE
        if "biomedical evidence extraction system" in system_prompt:
            if "Metformin Benefit Trial" in user_prompt:
                return _study_analysis_response("BENEFIT", "Metformin reduced cardiovascular events.")
            if "Metformin No-Effect Trial" in user_prompt:
                return _study_analysis_response("NO_EFFECT", "Metformin showed no cardiovascular benefit.")
            raise AssertionError(f"Unrecognized study in prompt: {user_prompt[:200]}")
        if "extract important, evidence-based factual claims" in system_prompt:
            if "Metformin Benefit Trial" in user_prompt:
                return json.dumps({"claims": ["Metformin reduced cardiovascular events compared to placebo."]})
            return json.dumps({"claims": ["Metformin showed no cardiovascular benefit compared to placebo."]})
        if "evidence verification system" in system_prompt:
            if "reduced cardiovascular events" in user_prompt:
                return json.dumps(
                    {
                        "verification_status": "SUPPORTED",
                        "confidence": 0.9,
                        "supporting_excerpt": "metformin reduced cardiovascular events",
                    }
                )
            return json.dumps(
                {
                    "verification_status": "SUPPORTED",
                    "confidence": 0.85,
                    "supporting_excerpt": "no significant reduction in cardiovascular events",
                }
            )
        if "narrative sections of a medical evidence" in system_prompt:
            return json.dumps(
                {
                    "executive_summary": "The available verified evidence is mixed on cardiovascular benefit.",
                    "key_findings_narrative": "One study found a benefit while another found no effect.",
                    "evidence_gaps_narrative": "The studies disagree on this outcome; the reason is not established from available evidence.",
                    "limitations_narrative": "Evidence is based on abstract/trial-summary-level text rather than full papers.",
                    "conclusion": "The evidence on cardiovascular benefit is currently mixed and warrants further review.",
                }
            )
        raise AssertionError("Unexpected system prompt routed to fake LLM.")

    async def complete_text(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError

    async def embed(self, texts):
        raise NotImplementedError


PUBMED_ESEARCH_RESPONSE = {"esearchresult": {"idlist": ["3003"]}}
PUBMED_EFETCH_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>3003</PMID>
      <Article>
        <ArticleTitle>Metformin Benefit Trial</ArticleTitle>
        <Journal><Title>Diabetes Care</Title><JournalIssue><PubDate><Year>2023</Year></PubDate></JournalIssue></Journal>
        <AbstractText>In this trial, metformin reduced cardiovascular events versus placebo (HR 0.82).</AbstractText>
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
                "identificationModule": {"nctId": "NCT08888888", "briefTitle": "Metformin No-Effect Trial"},
                "designModule": {"enrollmentInfo": {"count": 1200}},
                "descriptionModule": {
                    "briefSummary": "This trial found no significant reduction in cardiovascular events with metformin."
                },
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
async def test_full_phase5_pipeline_query_to_grade():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/research",
            json={"raw_question": "Does metformin reduce cardiovascular risk in patients with type 2 diabetes?"},
        )
        query_id = create_resp.json()["id"]

        start_resp = await client.post(f"/api/research/{query_id}/start")
        assert start_resp.status_code == 202, start_resp.text
        job = await wait_for_terminal_status(client, query_id)

        assert job["status"] == "COMPLETED", job["failure_summary"]
        assert job["evidence_grade"] in ("STRONG", "MODERATE", "LIMITED", "INSUFFICIENT")

        studies = (await client.get(f"/api/research/{query_id}/studies")).json()
        assert len(studies) == 2
        directions = {s["study_findings"][0]["effect_direction"] for s in studies}
        assert directions == {"BENEFIT", "NO_EFFECT"}

        # --- /evidence ---
        evidence = (await client.get(f"/api/research/{query_id}/evidence")).json()
        assert len(evidence) == 2  # one claim per study
        for claim in evidence:
            assert claim["verification_status"] == "SUPPORTED"
            assert len(claim["evidence_links"]) == 1
            assert claim["evidence_links"][0]["excerpt"]  # a real excerpt, not empty

        # --- /conflicts ---
        conflicts = (await client.get(f"/api/research/{query_id}/conflicts")).json()
        assert len(conflicts) == 1
        conflict = conflicts[0]
        assert conflict["conflicting_outcome"] == "cardiovascular events"
        assert {conflict["finding_a"].split(" ")[0], conflict["finding_b"].split(" ")[0]} == {"BENEFIT", "NO_EFFECT"}
        assert conflict["possible_explanation"]  # never blank

        # --- /grade ---
        grade_resp = (await client.get(f"/api/research/{query_id}/grade")).json()
        assert grade_resp["grade"] == job["evidence_grade"]
        assert grade_resp["explanation"]["conflict_count"] == 1
        assert "methodology_note" in grade_resp["explanation"]

        # --- /api/studies/{id}/evidence ---
        benefit_study = next(s for s in studies if s["study_findings"][0]["effect_direction"] == "BENEFIT")
        study_evidence = (await client.get(f"/api/studies/{benefit_study['id']}/evidence")).json()
        assert len(study_evidence) == 1
        assert "reduced cardiovascular events" in study_evidence[0]["claim_text"]

        # A user cannot fetch evidence for a study that doesn't exist / isn't theirs.
        missing_resp = await client.get(f"/api/studies/{uuid.uuid4()}/evidence")
        assert missing_resp.status_code == 404

        # --- Phase 7: /report ---
        report_resp = await client.get(f"/api/research/{query_id}/report")
        assert report_resp.status_code == 200, report_resp.text
        report = report_resp.json()
        assert report["evidence_grade"] == job["evidence_grade"]
        assert report["sections"]["research_question"]
        assert len(report["sections"]["studies_analyzed"]) == 2
        assert len(report["sections"]["conflicting_evidence"]) == 1
        # Only claims verified as SUPPORTED/PARTIALLY_SUPPORTED get a citation.
        assert len(report["citations"]) == 2
        assert {c["number"] for c in report["citations"]} == {1, 2}

        save_report_resp = await client.post(f"/api/reports/{report['id']}/save")
        assert save_report_resp.json()["saved"] is True

        # --- Phase 7: /evidence-map ---
        map_resp = await client.get(f"/api/research/{query_id}/evidence-map")
        assert map_resp.status_code == 200
        evidence_map = map_resp.json()
        assert evidence_map["nodes"][0]["type"] == "question"
        assert len(evidence_map["nodes"]) == 3  # question + 2 studies
        conflict_edges = [e for e in evidence_map["edges"] if e["type"] == "conflict"]
        assert len(conflict_edges) == 1

        # --- Phase 7: study detail + save ---
        study_detail_resp = await client.get(f"/api/studies/{benefit_study['id']}")
        assert study_detail_resp.status_code == 200
        assert study_detail_resp.json()["conclusion"] == "Metformin reduced cardiovascular events."

        save_study_resp = await client.post(f"/api/studies/{benefit_study['id']}/save")
        assert save_study_resp.json()["saved"] is True
        unsave_study_resp = await client.delete(f"/api/studies/{benefit_study['id']}/save")
        assert unsave_study_resp.json()["saved"] is False
