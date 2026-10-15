"""
Agent-level unit tests for the Study Analysis Agent — no database, no real
network. A FakeLLM stands in for OpenAILLMClient so the agent's own JSON
parsing / Pydantic validation logic is what's actually under test.
"""
import json

import pytest

from app.agents.base import AgentExecutionError
from app.agents.study_analysis import StudyAnalysisAgent
from app.schemas.study_analysis import EvidenceLevel, StudyAnalysisInput, StudyAnalysisOutput


class FakeLLM:
    def __init__(self, json_response: str | None = None, raise_if_called: bool = False):
        self._json_response = json_response
        self._raise_if_called = raise_if_called
        self.call_count = 0

    async def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        self.call_count += 1
        if self._raise_if_called:
            raise AssertionError("LLM must not be called when there is no source text to ground on.")
        return self._json_response

    async def complete_text(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError

    async def embed(self, texts):
        raise NotImplementedError


def _base_input(**overrides) -> StudyAnalysisInput:
    defaults = dict(
        study_id="11111111-1111-1111-1111-111111111111",
        research_question="Does metformin reduce cardiovascular risk in type 2 diabetes?",
        population_hint="adults with type 2 diabetes",
        intervention_hint="metformin",
        comparator_hint="placebo",
        outcomes_hint=["cardiovascular events"],
        title="Metformin Reduces Cardiovascular Events in Type 2 Diabetes",
        origin="pubmed",
        document_text="This RCT of 500 patients found metformin reduced cardiovascular events vs placebo (HR 0.82).",
        evidence_level=EvidenceLevel.ABSTRACT_ONLY,
        known_population=None,
        known_sample_size=None,
        known_intervention=None,
        known_outcomes=[],
    )
    defaults.update(overrides)
    return StudyAnalysisInput(**defaults)


VALID_RESPONSE = json.dumps(
    {
        "evidence_level": "abstract_only",
        "study_type": "randomized controlled trial",
        "population": "adults with type 2 diabetes",
        "sample_size": 500,
        "intervention": "metformin",
        "comparator": "placebo",
        "outcomes": ["cardiovascular events"],
        "follow_up": "Not reported",
        "methodology": "Randomized controlled trial based on the abstract.",
        "findings": "Metformin reduced cardiovascular events compared to placebo.",
        "effect_size": "HR 0.82",
        "limitations": "Not reported",
        "conclusion": "Metformin may reduce cardiovascular risk in this population.",
        "relevance_score": 0.95,
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

MISSING_FIELDS_RESPONSE = json.dumps(
    {
        "evidence_level": "abstract_only",
        "study_type": None,
        "population": None,
        "sample_size": None,
        "intervention": None,
        "comparator": None,
        "outcomes": [],
        "follow_up": None,
        "methodology": "Not reported",
        "findings": "Not reported",
        "effect_size": None,
        "limitations": "Not reported",
        "conclusion": "Not reported",
        "relevance_score": None,
        "study_findings": [],
    }
)

INVALID_EFFECT_DIRECTION_RESPONSE = json.dumps(
    {
        "evidence_level": "abstract_only",
        "study_type": None,
        "population": None,
        "sample_size": None,
        "intervention": None,
        "comparator": None,
        "outcomes": [],
        "follow_up": None,
        "methodology": "Not reported",
        "findings": "Not reported",
        "effect_size": None,
        "limitations": "Not reported",
        "conclusion": "Not reported",
        "relevance_score": None,
        "study_findings": [
            {
                "outcome": "cardiovascular events",
                "effect_direction": "POSITIVE",  # not a valid EffectDirection value
                "effect_size": None,
                "confidence": "HIGH",
            }
        ],
    }
)


# ---------- 1. Valid structured study analysis ----------


@pytest.mark.asyncio
async def test_valid_response_parses_into_output_schema():
    agent = StudyAnalysisAgent(FakeLLM(VALID_RESPONSE))
    result = await agent._execute(_base_input())

    assert isinstance(result, StudyAnalysisOutput)
    assert result.sample_size == 500
    assert result.study_findings[0].effect_direction.value == "BENEFIT"
    assert result.study_findings[0].confidence.value == "HIGH"
    assert result.relevance_score == 0.95


# ---------- 2. Missing fields ----------


@pytest.mark.asyncio
async def test_missing_fields_are_accepted_as_null_or_not_reported():
    agent = StudyAnalysisAgent(FakeLLM(MISSING_FIELDS_RESPONSE))
    result = await agent._execute(_base_input())

    assert result.sample_size is None
    assert result.population is None
    assert result.methodology == "Not reported"
    assert result.study_findings == []


# ---------- 3. Invalid LLM JSON ----------


@pytest.mark.asyncio
async def test_malformed_json_raises_agent_execution_error():
    agent = StudyAnalysisAgent(FakeLLM("this is not json"))
    with pytest.raises(AgentExecutionError):
        await agent._execute(_base_input())


# ---------- 4. Hallucinated / missing source content handling ----------


@pytest.mark.asyncio
async def test_no_document_text_skips_llm_and_returns_not_reported():
    llm = FakeLLM(raise_if_called=True)
    agent = StudyAnalysisAgent(llm)

    result = await agent._execute(_base_input(document_text=None))

    assert llm.call_count == 0  # never gave the model a chance to invent an answer
    assert result.evidence_level == EvidenceLevel.NO_CONTENT_AVAILABLE
    assert result.methodology == "Not reported"
    assert result.study_findings == []
    assert result.sample_size is None


@pytest.mark.asyncio
async def test_blank_document_text_also_skips_llm():
    llm = FakeLLM(raise_if_called=True)
    agent = StudyAnalysisAgent(llm)

    result = await agent._execute(_base_input(document_text="   "))

    assert llm.call_count == 0
    assert result.evidence_level == EvidenceLevel.NO_CONTENT_AVAILABLE


# ---------- 5. Effect direction validation ----------


@pytest.mark.asyncio
async def test_invalid_effect_direction_value_raises_agent_execution_error():
    agent = StudyAnalysisAgent(FakeLLM(INVALID_EFFECT_DIRECTION_RESPONSE))
    with pytest.raises(AgentExecutionError):
        await agent._execute(_base_input())


def test_effect_direction_enum_only_allows_spec_values():
    from app.schemas.study_analysis import EffectDirection

    assert {d.value for d in EffectDirection} == {"BENEFIT", "HARM", "NO_EFFECT", "UNCLEAR"}


def test_sample_size_must_be_positive_if_reported():
    with pytest.raises(ValueError):
        StudyAnalysisOutput(evidence_level=EvidenceLevel.ABSTRACT_ONLY, sample_size=0)


def test_relevance_score_must_be_within_zero_and_one():
    with pytest.raises(ValueError):
        StudyAnalysisOutput(evidence_level=EvidenceLevel.ABSTRACT_ONLY, relevance_score=1.5)
