"""
Evidence Verification Agent.

The LLM is asked to judge whether a claim is supported by ONE study's
document text and to quote the exact supporting excerpt. That excerpt is
then checked programmatically against the real document text — the agent
does not trust the model's word for it. If the quoted excerpt doesn't
actually appear in the source (fabricated or paraphrased instead of
quoted), the result is downgraded to NOT_SUPPORTED with no excerpt,
regardless of what status the model claimed.
"""
import json
import re

from app.agents.base import AgentExecutionError, BaseAgent
from app.integrations.llm import LLMClient
from app.schemas.evidence_verification import (
    EvidenceVerificationInput,
    EvidenceVerificationOutput,
    VerificationStatus,
)

SYSTEM_PROMPT = """You are an evidence verification system. You will be \
given a factual CLAIM and the actual source text for ONE study. Determine \
whether that source text supports the claim.

RULES:
1. Judge ONLY using the provided source text. Do not use outside medical \
knowledge to decide whether the claim is true — decide only whether THIS \
TEXT supports it.
2. If you find supporting text, you MUST quote it VERBATIM as \
"supporting_excerpt" — copy the exact wording from the source text, do not \
paraphrase or summarize it. If you cannot find and quote an exact \
supporting passage, set supporting_excerpt to null and status must be \
NOT_SUPPORTED.
3. Use these statuses:
   - SUPPORTED: the text clearly and directly supports the claim.
   - PARTIALLY_SUPPORTED: the text supports part of the claim, or supports \
it with less certainty/specificity than the claim states.
   - NOT_SUPPORTED: the text does not address the claim, or you cannot \
find a verbatim supporting passage.
   - CONFLICTING: the text contains information that directly contradicts \
the claim.
4. confidence (0.0-1.0) reflects how clearly the text supports (or \
contradicts) the claim — not your general confidence in the claim's truth.

Respond with ONLY a JSON object matching this exact shape:
{
  "verification_status": "SUPPORTED" | "PARTIALLY_SUPPORTED" | "NOT_SUPPORTED" | "CONFLICTING",
  "confidence": number,
  "supporting_excerpt": string | null
}
"""


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def excerpt_is_grounded(excerpt: str | None, document_text: str) -> bool:
    """The only thing standing between 'the model said so' and a citation
    a user might click through to verify. Normalizes whitespace only —
    deliberately does NOT fuzzy-match wording, so a paraphrase can't sneak
    through as a quote."""
    if not excerpt:
        return False
    return _normalize_for_match(excerpt) in _normalize_for_match(document_text)


class EvidenceVerificationAgent(BaseAgent[EvidenceVerificationInput, EvidenceVerificationOutput]):
    name = "evidence_verification"
    timeout_seconds = 30.0
    max_attempts = 3

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def _execute(self, payload: EvidenceVerificationInput) -> EvidenceVerificationOutput:
        user_prompt = (
            f"Claim: {payload.claim_text}\n\n"
            f"--- Source text for this study ---\n{payload.document_text}\n--- End of source text ---"
        )
        raw = await self._llm.complete_json(SYSTEM_PROMPT, user_prompt)
        try:
            data = json.loads(raw)
            output = EvidenceVerificationOutput.model_validate(data)
        except (json.JSONDecodeError, ValueError) as exc:
            raise AgentExecutionError(f"Evidence verification returned invalid structured output: {exc}") from exc

        # Programmatic grounding check — never trust the model's excerpt.
        if output.supporting_excerpt and not excerpt_is_grounded(output.supporting_excerpt, payload.document_text):
            output = EvidenceVerificationOutput(
                verification_status=VerificationStatus.NOT_SUPPORTED,
                confidence=0.0,
                supporting_excerpt=None,
            )
        elif (
            output.verification_status in (VerificationStatus.SUPPORTED, VerificationStatus.PARTIALLY_SUPPORTED)
            and not output.supporting_excerpt
        ):
            # Claimed support but provided no checkable excerpt — can't trust it.
            output = EvidenceVerificationOutput(
                verification_status=VerificationStatus.NOT_SUPPORTED,
                confidence=0.0,
                supporting_excerpt=None,
            )

        return output
