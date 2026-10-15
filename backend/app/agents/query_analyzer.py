"""
Query Analyzer Agent.

Turns a free-text research question into structured PICO elements and
source-specific search queries. This agent also enforces the product's
core safety boundary: personalized diagnosis/treatment requests are
flagged rather than turned into a research plan.
"""
import json

from pydantic import BaseModel, Field

from app.agents.base import AgentExecutionError, BaseAgent
from app.integrations.llm import LLMClient

SYSTEM_PROMPT = """You are a biomedical research question analyzer for an \
evidence-research platform (not a clinical decision tool).

Given a user's free-text medical research question, do two things:

1. Determine whether this is a legitimate EVIDENCE RESEARCH question (e.g. \
"what does the evidence say about X") versus a request for PERSONALIZED \
diagnosis or treatment (e.g. "I have symptom X, what should I take/do").
   - If it is a personalized diagnosis/treatment request, set \
"is_researchable" to false and leave the other structured fields null/empty.
   - Otherwise set "is_researchable" to true.

2. If researchable, extract PICO-style elements and produce source-specific \
search queries. Do not invent details the question doesn't support — use \
null for anything not specified rather than guessing.

Respond with ONLY a JSON object matching this exact shape:
{
  "is_researchable": boolean,
  "safety_note": string | null,        // set only when is_researchable is false
  "population": string | null,
  "intervention": string | null,
  "comparator": string | null,
  "outcomes": string[],
  "study_types": string[],             // e.g. ["randomized controlled trial", "meta-analysis"]
  "evidence_requirements": string[],   // e.g. ["prefer studies with >6 month follow-up"]
  "search_queries": {
    "pubmed": string[],                // 2-4 targeted queries using PubMed syntax where useful
    "clinical_trials": string[],       // 2-4 targeted queries for ClinicalTrials.gov
    "web": string[]                    // 2-4 targeted queries for broader web research
  }
}
"""


class QueryAnalyzerInput(BaseModel):
    raw_question: str
    population_hint: str | None = None
    intervention_hint: str | None = None
    comparator_hint: str | None = None


class SearchQueries(BaseModel):
    pubmed: list[str] = Field(default_factory=list)
    clinical_trials: list[str] = Field(default_factory=list)
    web: list[str] = Field(default_factory=list)


class QueryAnalyzerOutput(BaseModel):
    is_researchable: bool
    safety_note: str | None = None
    population: str | None = None
    intervention: str | None = None
    comparator: str | None = None
    outcomes: list[str] = Field(default_factory=list)
    study_types: list[str] = Field(default_factory=list)
    evidence_requirements: list[str] = Field(default_factory=list)
    search_queries: SearchQueries = Field(default_factory=SearchQueries)


class QueryAnalyzerAgent(BaseAgent[QueryAnalyzerInput, QueryAnalyzerOutput]):
    name = "query_analyzer"
    timeout_seconds = 30.0

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def _execute(self, payload: QueryAnalyzerInput) -> QueryAnalyzerOutput:
        user_prompt = (
            f"Research question: {payload.raw_question}\n"
            f"Population hint: {payload.population_hint or 'none provided'}\n"
            f"Intervention hint: {payload.intervention_hint or 'none provided'}\n"
            f"Comparator hint: {payload.comparator_hint or 'none provided'}"
        )
        raw = await self._llm.complete_json(SYSTEM_PROMPT, user_prompt)
        try:
            data = json.loads(raw)
            return QueryAnalyzerOutput.model_validate(data)
        except (json.JSONDecodeError, ValueError) as exc:
            raise AgentExecutionError(f"Query analyzer returned invalid structured output: {exc}") from exc
