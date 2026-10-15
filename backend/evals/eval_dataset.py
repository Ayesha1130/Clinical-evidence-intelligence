"""
A small evaluation dataset for exercising this system's core safety
mechanisms: structured-output validity, excerpt grounding (the defense
against fabricated citations), and conflict-detection accuracy.

These aren't live-LLM evals (this environment has no network access to
OpenAI, and a portfolio project shouldn't require a paid API key just to
prove its safety mechanisms work) — each case supplies a scripted LLM
response and runs it through the REAL production code path
(EvidenceVerificationAgent, ConflictDetectionAgent's rule table, the
StudyAnalysisOutput schema). What's under test is whether the system's own
grounding/validation logic catches a bad model response.
"""
from dataclasses import dataclass, field


@dataclass
class VerificationCase:
    name: str
    claim_text: str
    document_text: str
    llm_response: dict
    expected_status: str
    expect_excerpt_present: bool


@dataclass
class ConflictCase:
    name: str
    direction_a: str
    direction_b: str
    expect_conflict: bool


@dataclass
class StudyAnalysisValidityCase:
    name: str
    llm_response: dict
    expect_valid: bool


VERIFICATION_CASES: list[VerificationCase] = [
    VerificationCase(
        name="genuinely_supported_claim_with_real_excerpt",
        claim_text="Metformin reduced cardiovascular events compared to placebo.",
        document_text="This trial found that metformin reduced cardiovascular events compared to placebo (HR 0.82).",
        llm_response={
            "verification_status": "SUPPORTED",
            "confidence": 0.9,
            "supporting_excerpt": "metformin reduced cardiovascular events compared to placebo",
        },
        expected_status="SUPPORTED",
        expect_excerpt_present=True,
    ),
    VerificationCase(
        name="fabricated_excerpt_must_be_rejected",
        claim_text="Metformin eliminated all cardiovascular risk.",
        document_text="This trial found that metformin reduced cardiovascular events compared to placebo (HR 0.82).",
        llm_response={
            "verification_status": "SUPPORTED",
            "confidence": 0.95,
            "supporting_excerpt": "metformin eliminated all cardiovascular risk permanently",
        },
        expected_status="NOT_SUPPORTED",
        expect_excerpt_present=False,
    ),
    VerificationCase(
        name="claimed_support_with_no_excerpt_must_be_rejected",
        claim_text="Metformin reduced cardiovascular events.",
        document_text="This trial found that metformin reduced cardiovascular events compared to placebo.",
        llm_response={"verification_status": "SUPPORTED", "confidence": 0.9, "supporting_excerpt": None},
        expected_status="NOT_SUPPORTED",
        expect_excerpt_present=False,
    ),
    VerificationCase(
        name="genuinely_unsupported_claim",
        claim_text="Metformin cured type 1 diabetes.",
        document_text="This trial found that metformin reduced cardiovascular events compared to placebo.",
        llm_response={"verification_status": "NOT_SUPPORTED", "confidence": 0.1, "supporting_excerpt": None},
        expected_status="NOT_SUPPORTED",
        expect_excerpt_present=False,
    ),
]

CONFLICT_CASES: list[ConflictCase] = [
    ConflictCase("benefit_vs_harm_is_strong_conflict", "BENEFIT", "HARM", expect_conflict=True),
    ConflictCase("benefit_vs_no_effect_is_conflict", "BENEFIT", "NO_EFFECT", expect_conflict=True),
    ConflictCase("harm_vs_no_effect_is_conflict", "HARM", "NO_EFFECT", expect_conflict=True),
    ConflictCase("no_effect_vs_no_effect_is_not_conflict", "NO_EFFECT", "NO_EFFECT", expect_conflict=False),
    ConflictCase("benefit_vs_benefit_is_not_conflict", "BENEFIT", "BENEFIT", expect_conflict=False),
    ConflictCase("unclear_vs_benefit_is_not_a_confirmed_conflict", "UNCLEAR", "BENEFIT", expect_conflict=False),
    ConflictCase("unclear_vs_unclear_is_not_conflict", "UNCLEAR", "UNCLEAR", expect_conflict=False),
]

STUDY_ANALYSIS_VALIDITY_CASES: list[StudyAnalysisValidityCase] = [
    StudyAnalysisValidityCase(
        name="valid_structured_output",
        llm_response={
            "evidence_level": "abstract_only",
            "study_type": "randomized controlled trial",
            "population": None, "sample_size": 200, "intervention": None, "comparator": None,
            "outcomes": ["cardiovascular events"], "follow_up": None,
            "methodology": "RCT.", "findings": "Reduced events.", "effect_size": "HR 0.8",
            "limitations": "Not reported.", "conclusion": "Supports benefit.", "relevance_score": 0.9,
            "study_findings": [
                {"outcome": "cardiovascular events", "effect_direction": "BENEFIT", "effect_size": "HR 0.8", "confidence": "HIGH"}
            ],
        },
        expect_valid=True,
    ),
    StudyAnalysisValidityCase(
        name="invalid_effect_direction_value_must_be_rejected",
        llm_response={
            "evidence_level": "abstract_only", "study_type": None, "population": None, "sample_size": None,
            "intervention": None, "comparator": None, "outcomes": [], "follow_up": None,
            "methodology": "Not reported.", "findings": "Not reported.", "effect_size": None,
            "limitations": "Not reported.", "conclusion": "Not reported.", "relevance_score": None,
            "study_findings": [
                {"outcome": "cardiovascular events", "effect_direction": "POSITIVE", "effect_size": None, "confidence": "HIGH"}
            ],
        },
        expect_valid=False,
    ),
    StudyAnalysisValidityCase(
        name="negative_sample_size_must_be_rejected",
        llm_response={
            "evidence_level": "abstract_only", "study_type": None, "population": None, "sample_size": -5,
            "intervention": None, "comparator": None, "outcomes": [], "follow_up": None,
            "methodology": "Not reported.", "findings": "Not reported.", "effect_size": None,
            "limitations": "Not reported.", "conclusion": "Not reported.", "relevance_score": None,
            "study_findings": [],
        },
        expect_valid=False,
    ),
]
