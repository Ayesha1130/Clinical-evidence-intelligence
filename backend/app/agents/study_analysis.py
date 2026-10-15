"""
Study Analysis Agent.

Extracts structured evidence from a single study's available source text
(abstract, trial registry summary, or web snippet — whatever Phase 3
actually retrieved). Never fabricates a value: the system prompt requires
"Not reported" / null for anything the text doesn't support, and the
`evidence_level` field is threaded through so no downstream consumer can
mistake an abstract-only read for a full-text review.

If there is no document text at all for a study, the LLM is not called —
there is nothing to ground an analysis in, so we return an explicit
"no content available" result instead of giving the model a chance to
invent one.
"""
import json

from app.agents.base import AgentExecutionError, BaseAgent
from app.integrations.llm import LLMClient
from app.schemas.study_analysis import EvidenceLevel, StudyAnalysisInput, StudyAnalysisOutput

SYSTEM_PROMPT = """You are a biomedical evidence extraction system. You will \
be given the title and available source text for ONE study, plus the \
research question it was retrieved for. Extract ONLY what the provided \
text actually supports.

STRICT RULES — violating any of these is a critical failure:
1. NEVER invent a sample size, effect size, outcome, finding, methodology \
detail, limitation, or conclusion that is not stated or clearly implied by \
the provided text.
2. If a field is not supported by the text, set it to null (for numbers) \
or the literal string "Not reported" (for text fields).
3. The "evidence_level" you were told (e.g. "abstract_only") describes how \
much of the source you have access to. Your "methodology", "findings", and \
"conclusion" text MUST reflect that limitation explicitly — e.g. say "Based \
on the available abstract..." rather than writing as if you read the full \
paper. Never claim to have analyzed content you were not given.
4. "known_population" / "known_sample_size" / "known_intervention" / \
"known_outcomes" in the input are already-confirmed structured facts \
(e.g. from a trial registry). Do not contradict them; if you can refine \
them with clearly-stated detail from the text, you may, but do not guess \
against them.
5. relevance_score (0.0-1.0) reflects how directly this specific study's \
population/intervention/outcomes match the stated research question — NOT \
general study quality. If the study is off-target for this question, score \
it low even if it's a well-conducted study.
6. Each item in "study_findings" needs an effect_direction from exactly: \
BENEFIT, HARM, NO_EFFECT, UNCLEAR. Use UNCLEAR whenever the text's language \
is ambiguous, mixed, or you are not confident — do not force a directional \
call the text doesn't support.
7. confidence (HIGH/MODERATE/LOW) reflects how clearly and directly the \
TEXT states the finding, not your general confidence in the study.

Respond with ONLY a JSON object matching this exact shape:
{
  "evidence_level": string,               // echo back the evidence_level you were given
  "study_type": string | null,
  "population": string | null,
  "sample_size": integer | null,
  "intervention": string | null,
  "comparator": string | null,
  "outcomes": string[],
  "follow_up": string | null,
  "methodology": string | null,
  "findings": string | null,              // narrative summary, plain text
  "effect_size": string | null,
  "limitations": string | null,
  "conclusion": string | null,
  "relevance_score": number | null,
  "study_findings": [
    {
      "outcome": string,
      "effect_direction": "BENEFIT" | "HARM" | "NO_EFFECT" | "UNCLEAR",
      "effect_size": string | null,
      "confidence": "HIGH" | "MODERATE" | "LOW"
    }
  ]
}
"""


def _no_content_result(evidence_level: EvidenceLevel) -> StudyAnalysisOutput:
    return StudyAnalysisOutput(
        evidence_level=evidence_level,
        study_type=None,
        population=None,
        sample_size=None,
        intervention=None,
        comparator=None,
        outcomes=[],
        follow_up=None,
        methodology="Not reported",
        findings="Not reported",
        effect_size=None,
        limitations="Not reported",
        conclusion="Not reported",
        relevance_score=None,
        study_findings=[],
    )


class StudyAnalysisAgent(BaseAgent[StudyAnalysisInput, StudyAnalysisOutput]):
    name = "study_analysis"
    timeout_seconds = 45.0
    max_attempts = 3

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def _execute(self, payload: StudyAnalysisInput) -> StudyAnalysisOutput:
        if not payload.document_text or not payload.document_text.strip():
            # Nothing to ground an analysis in — don't give the model a
            # chance to fabricate one.
            return _no_content_result(EvidenceLevel.NO_CONTENT_AVAILABLE)

        user_prompt = self._build_user_prompt(payload)
        raw = await self._llm.complete_json(SYSTEM_PROMPT, user_prompt)
        try:
            data = json.loads(raw)
            return StudyAnalysisOutput.model_validate(data)
        except (json.JSONDecodeError, ValueError) as exc:
            raise AgentExecutionError(f"Study analysis returned invalid structured output: {exc}") from exc

    @staticmethod
    def _build_user_prompt(payload: StudyAnalysisInput) -> str:
        return (
            f"Research question: {payload.research_question}\n"
            f"Population hint: {payload.population_hint or 'none provided'}\n"
            f"Intervention hint: {payload.intervention_hint or 'none provided'}\n"
            f"Comparator hint: {payload.comparator_hint or 'none provided'}\n"
            f"Outcomes hint: {', '.join(payload.outcomes_hint) or 'none provided'}\n\n"
            f"Study title: {payload.title}\n"
            f"Source origin: {payload.origin}\n"
            f"Evidence level (how much text you have): {payload.evidence_level.value}\n"
            f"Known population (from source metadata, do not contradict): {payload.known_population or 'unknown'}\n"
            f"Known sample size (from source metadata, do not contradict): {payload.known_sample_size or 'unknown'}\n"
            f"Known intervention (from source metadata): {payload.known_intervention or 'unknown'}\n"
            f"Known outcomes (from source metadata): {', '.join(payload.known_outcomes) or 'none'}\n\n"
            f"--- Available source text ({payload.evidence_level.value}) ---\n"
            f"{payload.document_text}\n"
            f"--- End of available source text ---"
        )
