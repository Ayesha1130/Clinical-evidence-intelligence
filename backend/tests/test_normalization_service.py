from app.integrations.clinical_trials import ClinicalTrial
from app.integrations.pubmed import PubMedArticle
from app.integrations.tavily import WebResult
from app.services.normalization_service import (
    candidates_from_clinical_trials,
    candidates_from_pubmed,
    candidates_from_web,
    deduplicate,
)


def test_pubmed_candidate_carries_pmid_and_doi():
    article = PubMedArticle(
        pmid="111",
        title="Metformin and CV Outcomes",
        journal="Diabetes Care",
        publication_date="2022 Jun",
        abstract="Some abstract text.",
        doi="10.1/example",
        publication_types=["Randomized Controlled Trial"],
    )
    candidates = candidates_from_pubmed([article])
    assert len(candidates) == 1
    c = candidates[0]
    assert c.origin == "pubmed"
    assert c.external_id == "111"
    assert c.doi == "10.1/example"
    assert c.source_type == "PRIMARY_STUDY"
    assert c.document_text == "Some abstract text."


def test_clinical_trial_candidate_carries_nct_and_enrollment():
    trial = ClinicalTrial(
        nct_id="NCT001",
        title="Metformin Trial",
        conditions=["Type 2 Diabetes"],
        interventions=["Metformin"],
        enrollment=500,
        phase=["PHASE3"],
    )
    candidates = candidates_from_clinical_trials([trial])
    c = candidates[0]
    assert c.origin == "clinicaltrials"
    assert c.external_id == "NCT001"
    assert c.source_type == "CLINICAL_TRIAL"
    assert c.sample_size == 500
    assert c.population == "Type 2 Diabetes"


def test_web_candidate_has_no_pmid_or_nct_but_has_url_identifier():
    result = WebResult(
        title="Metformin systematic review",
        url="https://www.nih.gov/review",
        domain="www.nih.gov",
        snippet="A review of metformin evidence.",
    )
    candidates = candidates_from_web([result])
    c = candidates[0]
    assert c.origin == "tavily"
    assert c.external_id == "https://www.nih.gov/review"
    assert c.source_type == "OFFICIAL_MEDICAL_SOURCE"


def test_deduplicate_drops_exact_doi_match_across_sources():
    pubmed = candidates_from_pubmed(
        [PubMedArticle(pmid="1", title="Metformin Study", doi="10.1/abc")]
    )
    # Same DOI showing up again from a different simulated origin
    duplicate = candidates_from_pubmed(
        [PubMedArticle(pmid="2", title="A slightly different title", doi="10.1/ABC")]
    )
    deduped = deduplicate(pubmed + duplicate)
    assert len(deduped) == 1
    assert deduped[0].external_id == "1"  # first occurrence wins


def test_deduplicate_drops_title_match_when_no_doi_present():
    web = candidates_from_web(
        [
            WebResult(
                title="Metformin and Cardiovascular Outcomes!!",
                url="https://a.com/1",
                domain="a.com",
                snippet="x",
            ),
            WebResult(
                title="metformin and cardiovascular outcomes",
                url="https://b.com/2",
                domain="b.com",
                snippet="y",
            ),
        ]
    )
    deduped = deduplicate(web)
    assert len(deduped) == 1


def test_deduplicate_keeps_distinct_studies():
    pubmed = candidates_from_pubmed(
        [
            PubMedArticle(pmid="1", title="Study A"),
            PubMedArticle(pmid="2", title="Study B"),
        ]
    )
    deduped = deduplicate(pubmed)
    assert len(deduped) == 2


def test_priority_order_pubmed_wins_over_tavily_duplicate():
    pubmed = candidates_from_pubmed([PubMedArticle(pmid="1", title="Metformin RCT Results")])
    web = candidates_from_web(
        [WebResult(title="Metformin RCT Results", url="https://x.com/1", domain="x.com", snippet="dup")]
    )
    # pubmed listed first => wins per dedup's "first occurrence wins" rule
    deduped = deduplicate(pubmed + web)
    assert len(deduped) == 1
    assert deduped[0].origin == "pubmed"
