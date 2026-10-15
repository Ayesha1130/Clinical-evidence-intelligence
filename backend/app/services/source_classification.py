"""
Heuristic source-quality classification.

This is explicitly NOT an official evidence-grading system. It labels each
retrieved item into one of the categories the product surfaces to users
(see README / Evidence Grading section), based on observable signals:
publication type strings from PubMed, or domain/title keywords for web
results. When no signal is strong enough, it falls back to UNKNOWN /
GENERAL_WEB rather than guessing upward.
"""

OFFICIAL_MEDICAL_DOMAINS = {
    "who.int", "cdc.gov", "nih.gov", "nice.org.uk", "fda.gov",
    "ema.europa.eu", "cochranelibrary.com", "uptodate.com",
}

GUIDELINE_KEYWORDS = ("guideline", "recommendation", "consensus statement")
SYSTEMATIC_REVIEW_KEYWORDS = ("systematic review",)
META_ANALYSIS_KEYWORDS = ("meta-analysis", "meta analysis")


def classify_pubmed_source(publication_types: list[str]) -> str:
    types_lower = {t.lower() for t in publication_types}
    if any("meta-analysis" in t for t in types_lower):
        return "META_ANALYSIS"
    if any("systematic review" in t for t in types_lower):
        return "SYSTEMATIC_REVIEW"
    if any("guideline" in t or "practice guideline" in t for t in types_lower):
        return "GUIDELINE"
    if any("randomized controlled trial" in t or "clinical trial" in t for t in types_lower):
        return "PRIMARY_STUDY"
    if types_lower:
        return "PRIMARY_STUDY"
    return "UNKNOWN"


def classify_clinical_trial_source() -> str:
    # Every ClinicalTrials.gov record is, by definition, a registered trial.
    return "CLINICAL_TRIAL"


def classify_web_source(title: str, domain: str) -> str:
    title_lower = title.lower()
    domain_lower = domain.lower().lstrip("www.")

    if any(domain_lower.endswith(d) for d in OFFICIAL_MEDICAL_DOMAINS):
        if any(k in title_lower for k in GUIDELINE_KEYWORDS):
            return "GUIDELINE"
        return "OFFICIAL_MEDICAL_SOURCE"
    if any(k in title_lower for k in META_ANALYSIS_KEYWORDS):
        return "META_ANALYSIS"
    if any(k in title_lower for k in SYSTEMATIC_REVIEW_KEYWORDS):
        return "SYSTEMATIC_REVIEW"
    if any(k in title_lower for k in GUIDELINE_KEYWORDS):
        return "GUIDELINE"
    if domain_lower.endswith((".edu", ".gov")):
        return "SECONDARY_SOURCE"
    return "GENERAL_WEB"
