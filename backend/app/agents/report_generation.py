"""
Report Generation Agent.

Writes the narrative sections of the research report — executive summary,
key findings, evidence gaps, limitations, conclusion — using ONLY the
claims already verified as SUPPORTED/PARTIALLY_SUPPORTED in Phase 5.
"""
import json

from app.agents.base import AgentExecutionError, BaseAgent
from app.integrations.llm import LLMClient
from app.schemas.report import ReportGenerationInput, ReportGenerationOutput

SYSTEM_PROMPT = """You write the narrative sections of a medical evidence \
research report. You are given a list of claims that have ALREADY been \
verified against source text — these are the ONLY facts you may reference.

STRICT RULES:
1. Do not introduce any specific number, effect size, study detail, or \
finding that is not present in the provided verified claims list.
2. If the verified claims list is empty or very short, say so plainly in \
the executive summary and conclusion (e.g. "Limited verified evidence was \
available for this question") rather than writing generic filler that \
implies more was found.
3. Reference claims by citation number exactly as given (e.g. "metformin \
reduced cardiovascular events in one trial [1]") — do not invent new \
citation numbers or renumber them.
4. evidence_gaps_narrative should note what the research question asked \
about that the verified claims do NOT address, and mention if conflicting \
evidence was found (a conflict count is provided) — never invent a reason \
for a gap that isn't evident from what's given.
5. limitations_narrative should reflect real limitations of what's \
available (e.g. small number of studies, abstract-level evidence, unverified \
claims excluded) — do not invent clinical/methodological limitations you \
weren't told about.
6. Keep each section to 2-4 sentences. Plain prose, no markdown.
7. Never provide personalized medical advice or treatment recommendations \
— this is a research summary, not clinical guidance.

Respond with ONLY a JSON object:
{
  "executive_summary": string,
  "key_findings_narrative": string,
  "evidence_gaps_narrative": string,
  "limitations_narrative": string,
  "conclusion": string
}
"""


class ReportGenerationAgent(BaseAgent[ReportGenerationInput, ReportGenerationOutput]):
    name = "report_generation"
    timeout_seconds = 45.0
    max_attempts = 3

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def _execute(self, payload: ReportGenerationInput) -> ReportGenerationOutput:
        claims_block = "\n".join(
            f"[{c.citation_number}] {c.claim_text} (from: {c.study_title})" for c in payload.verified_claims
        ) or "No claims were verified as supported."

        user_prompt = (
            f"Research question: {payload.research_question}\n"
            f"Population: {payload.population or 'Not specified'}\n"
            f"Intervention: {payload.intervention or 'Not specified'}\n"
            f"Comparator: {payload.comparator or 'Not specified'}\n"
            f"Outcomes: {', '.join(payload.outcomes) or 'Not specified'}\n"
            f"Studies considered: {payload.studies_considered}\n"
            f"Conflicts found among studies: {payload.conflict_count}\n"
            f"Evidence grade (already computed, do not contradict): {payload.evidence_grade}\n\n"
            f"Verified claims (the ONLY facts you may reference):\n{claims_block}"
        )

        raw = await self._llm.complete_json(SYSTEM_PROMPT, user_prompt)
        try:
            data = json.loads(raw)
            return ReportGenerationOutput.model_validate(data)
        except (json.JSONDecodeError, ValueError) as exc:
            raise AgentExecutionError(f"Report generation returned invalid structured output: {exc}") from exc
