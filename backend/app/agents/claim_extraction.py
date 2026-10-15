"""
Claim Extraction Agent.

Turns one study's Phase 4 analysis (conclusion, narrative findings, and
structured study_findings) into a short list of important, evidence-based
claims worth verifying. Deliberately conservative: no claims from a study
with no real content, and the prompt explicitly excludes claims about
metadata (journal name, publication date, sponsor, etc.) that aren't
themselves evidence.
"""
import json

from app.agents.base import AgentExecutionError, BaseAgent
from app.integrations.llm import LLMClient
from app.schemas.evidence_verification import ClaimExtractionInput, ClaimExtractionOutput

SYSTEM_PROMPT = """You extract important, evidence-based factual claims \
from a single study's analysis, for later verification against that \
study's source text.

RULES:
1. Only extract claims that describe evidence: outcomes, findings, effect \
directions, effect sizes, population-specific findings, intervention \
findings, or the study's conclusion.
2. NEVER extract claims from metadata that isn't evidence (journal name, \
sponsor, publication date, authors, study ID).
3. Avoid trivial or vague claims ("the study was about diabetes"). Each \
claim should be specific enough to be checked against source text.
4. If the study's conclusion or findings say "Not reported" or give no \
real information, return an empty claims list — do not invent a claim to \
fill the list.
5. Each claim must be a single, self-contained factual sentence in plain \
text, phrased as a claim (not a question), e.g. "Metformin reduced \
cardiovascular events compared to placebo in this trial."
6. Extract at most 5 claims — the most evidentially important ones.

Respond with ONLY a JSON object: {"claims": string[]}
"""


class ClaimExtractionAgent(BaseAgent[ClaimExtractionInput, ClaimExtractionOutput]):
    name = "claim_extraction"
    timeout_seconds = 30.0
    max_attempts = 3

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def _execute(self, payload: ClaimExtractionInput) -> ClaimExtractionOutput:
        findings_lines = "\n".join(
            f"- {f.get('outcome')}: {f.get('effect_direction')} "
            f"(effect size: {f.get('effect_size') or 'Not reported'})"
            for f in payload.study_findings
        ) or "None"

        user_prompt = (
            f"Research question: {payload.research_question}\n"
            f"Study title: {payload.study_title}\n"
            f"Conclusion: {payload.conclusion or 'Not reported'}\n"
            f"Findings summary: {payload.findings_summary or 'Not reported'}\n"
            f"Structured findings:\n{findings_lines}"
        )

        raw = await self._llm.complete_json(SYSTEM_PROMPT, user_prompt)
        try:
            data = json.loads(raw)
            return ClaimExtractionOutput.model_validate(data)
        except (json.JSONDecodeError, ValueError) as exc:
            raise AgentExecutionError(f"Claim extraction returned invalid structured output: {exc}") from exc
