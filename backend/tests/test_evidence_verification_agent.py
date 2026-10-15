"""
Agent-level unit tests for Evidence Verification — no DB, no real network.
A FakeLLM stands in for OpenAILLMClient.
"""
import json

import pytest

from app.agents.base import AgentExecutionError
from app.agents.evidence_verification import EvidenceVerificationAgent, excerpt_is_grounded
from app.schemas.evidence_verification import EvidenceVerificationInput, VerificationStatus

DOCUMENT_TEXT = (
    "This randomized trial of 500 adults with type 2 diabetes found that metformin "
    "reduced cardiovascular events compared to placebo (HR 0.82, 95% CI 0.71-0.94). "
    "No significant difference in all-cause mortality was observed between groups."
)


class FakeLLM:
    def __init__(self, response: str):
        self._response = response

    async def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        return self._response

    async def complete_text(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError

    async def embed(self, texts):
        raise NotImplementedError


def _input(claim: str) -> EvidenceVerificationInput:
    return EvidenceVerificationInput(claim_text=claim, study_id="s1", document_text=DOCUMENT_TEXT)


# ---------- 1. Fully supported claim ----------


@pytest.mark.asyncio
async def test_fully_supported_claim_with_verbatim_excerpt():
    response = json.dumps(
        {
            "verification_status": "SUPPORTED",
            "confidence": 0.95,
            "supporting_excerpt": "metformin reduced cardiovascular events compared to placebo",
        }
    )
    agent = EvidenceVerificationAgent(FakeLLM(response))
    result = await agent._execute(_input("Metformin reduced cardiovascular events compared to placebo."))

    assert result.verification_status == VerificationStatus.SUPPORTED
    assert result.supporting_excerpt is not None
    assert result.confidence == 0.95


# ---------- 2. Partially supported claim ----------


@pytest.mark.asyncio
async def test_partially_supported_claim():
    response = json.dumps(
        {
            "verification_status": "PARTIALLY_SUPPORTED",
            "confidence": 0.6,
            "supporting_excerpt": "reduced cardiovascular events compared to placebo",
        }
    )
    agent = EvidenceVerificationAgent(FakeLLM(response))
    result = await agent._execute(_input("Metformin reduced cardiovascular events by 50% compared to placebo."))

    assert result.verification_status == VerificationStatus.PARTIALLY_SUPPORTED
    assert result.supporting_excerpt is not None


# ---------- 3. Unsupported claim ----------


@pytest.mark.asyncio
async def test_unsupported_claim():
    response = json.dumps({"verification_status": "NOT_SUPPORTED", "confidence": 0.1, "supporting_excerpt": None})
    agent = EvidenceVerificationAgent(FakeLLM(response))
    result = await agent._execute(_input("Metformin cured type 1 diabetes in all participants."))

    assert result.verification_status == VerificationStatus.NOT_SUPPORTED
    assert result.supporting_excerpt is None


# ---------- 4. Conflicting evidence ----------


@pytest.mark.asyncio
async def test_conflicting_claim():
    response = json.dumps(
        {
            "verification_status": "CONFLICTING",
            "confidence": 0.8,
            "supporting_excerpt": "No significant difference in all-cause mortality was observed between groups",
        }
    )
    agent = EvidenceVerificationAgent(FakeLLM(response))
    result = await agent._execute(_input("Metformin significantly reduced all-cause mortality."))

    assert result.verification_status == VerificationStatus.CONFLICTING


# ---------- 5. Invalid structured output ----------


@pytest.mark.asyncio
async def test_invalid_json_raises_agent_execution_error():
    agent = EvidenceVerificationAgent(FakeLLM("not json at all"))
    with pytest.raises(AgentExecutionError):
        await agent._execute(_input("Some claim."))


@pytest.mark.asyncio
async def test_invalid_verification_status_value_raises_agent_execution_error():
    response = json.dumps({"verification_status": "MAYBE", "confidence": 0.5, "supporting_excerpt": None})
    agent = EvidenceVerificationAgent(FakeLLM(response))
    with pytest.raises(AgentExecutionError):
        await agent._execute(_input("Some claim."))


# ---------- 6. Evidence excerpt provenance (grounding) ----------


def test_excerpt_is_grounded_true_for_verbatim_substring():
    assert excerpt_is_grounded("metformin reduced cardiovascular events", DOCUMENT_TEXT)


def test_excerpt_is_grounded_false_for_fabricated_text():
    assert not excerpt_is_grounded("metformin cured all patients completely", DOCUMENT_TEXT)


def test_excerpt_is_grounded_handles_whitespace_normalization():
    assert excerpt_is_grounded("metformin   reduced\ncardiovascular events", DOCUMENT_TEXT)


@pytest.mark.asyncio
async def test_fabricated_excerpt_is_downgraded_to_not_supported_despite_llm_claiming_supported():
    """The model claims SUPPORTED with high confidence and a fabricated
    excerpt — the agent must not trust it and must downgrade the result."""
    response = json.dumps(
        {
            "verification_status": "SUPPORTED",
            "confidence": 0.99,
            "supporting_excerpt": "metformin completely eliminated all cardiovascular risk permanently",
        }
    )
    agent = EvidenceVerificationAgent(FakeLLM(response))
    result = await agent._execute(_input("Metformin completely eliminated cardiovascular risk."))

    assert result.verification_status == VerificationStatus.NOT_SUPPORTED
    assert result.supporting_excerpt is None
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_claimed_support_without_any_excerpt_is_downgraded():
    """SUPPORTED/PARTIALLY_SUPPORTED with no excerpt at all can't be trusted."""
    response = json.dumps({"verification_status": "SUPPORTED", "confidence": 0.9, "supporting_excerpt": None})
    agent = EvidenceVerificationAgent(FakeLLM(response))
    result = await agent._execute(_input("Metformin reduced cardiovascular events."))

    assert result.verification_status == VerificationStatus.NOT_SUPPORTED
