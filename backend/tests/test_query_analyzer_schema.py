"""
Schema-level tests for the Query Analyzer agent that don't require live
OpenAI calls: they assert that well-formed and malformed LLM outputs are
handled correctly by QueryAnalyzerOutput / the agent's parsing logic.
"""
import json

import pytest

from app.agents.base import AgentExecutionError
from app.agents.query_analyzer import QueryAnalyzerAgent, QueryAnalyzerInput, QueryAnalyzerOutput


class FakeLLM:
    """Stands in for a real LLMClient in unit tests only — never used in
    production code paths. Production always calls OpenAILLMClient."""

    def __init__(self, json_response: str):
        self._json_response = json_response

    async def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        return self._json_response

    async def complete_text(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError

    async def embed(self, texts):
        raise NotImplementedError


VALID_RESPONSE = json.dumps(
    {
        "is_researchable": True,
        "safety_note": None,
        "population": "adults with type 2 diabetes",
        "intervention": "metformin",
        "comparator": "placebo or standard care",
        "outcomes": ["cardiovascular events"],
        "study_types": ["randomized controlled trial", "meta-analysis"],
        "evidence_requirements": [],
        "search_queries": {
            "pubmed": ["metformin cardiovascular type 2 diabetes RCT"],
            "clinical_trials": ["metformin cardiovascular outcomes"],
            "web": ["metformin cardiovascular risk systematic review"],
        },
    }
)

UNRESEARCHABLE_RESPONSE = json.dumps(
    {
        "is_researchable": False,
        "safety_note": "This asks for a personalized treatment recommendation.",
        "population": None,
        "intervention": None,
        "comparator": None,
        "outcomes": [],
        "study_types": [],
        "evidence_requirements": [],
        "search_queries": {"pubmed": [], "clinical_trials": [], "web": []},
    }
)


@pytest.mark.asyncio
async def test_valid_response_parses_into_output_schema():
    agent = QueryAnalyzerAgent(FakeLLM(VALID_RESPONSE))
    result = await agent._execute(QueryAnalyzerInput(raw_question="Does metformin reduce CV risk in T2D?"))
    assert isinstance(result, QueryAnalyzerOutput)
    assert result.is_researchable is True
    assert result.intervention == "metformin"
    assert "metformin cardiovascular type 2 diabetes RCT" in result.search_queries.pubmed


@pytest.mark.asyncio
async def test_unresearchable_question_is_flagged_not_answered():
    agent = QueryAnalyzerAgent(FakeLLM(UNRESEARCHABLE_RESPONSE))
    result = await agent._execute(
        QueryAnalyzerInput(raw_question="I have chest pain, what medication should I take?")
    )
    assert result.is_researchable is False
    assert result.safety_note


@pytest.mark.asyncio
async def test_malformed_json_raises_agent_execution_error():
    agent = QueryAnalyzerAgent(FakeLLM("not valid json"))
    with pytest.raises(AgentExecutionError):
        await agent._execute(QueryAnalyzerInput(raw_question="Does X help with Y?"))
