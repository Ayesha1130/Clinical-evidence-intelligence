"""
Runs PubMed, ClinicalTrials.gov, and Tavily research concurrently for a
research job. Each source is fully independent: if one fails (bad API key,
timeout, rate limit, malformed response), the other two still complete and
their studies are still stored. The caller (the /start route) uses the
returned summary to decide whether the job is COMPLETED, PARTIAL, or FAILED.
"""
import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentExecutionError
from app.agents.clinical_trials import ClinicalTrialsAgent
from app.agents.pubmed import PubMedAgent
from app.agents.web_research import WebResearchAgent
from app.integrations.clinical_trials import ClinicalTrialsClient, ClinicalTrialsIntegrationError
from app.integrations.pubmed import PubMedClient, PubMedIntegrationError
from app.integrations.tavily import TavilyClient, TavilyIntegrationError
from app.schemas.source_agents import SourceAgentInput
from app.services.normalization_service import (
    candidates_from_clinical_trials,
    candidates_from_pubmed,
    candidates_from_web,
    deduplicate,
    persist_candidates,
)

logger = logging.getLogger("research_service")

MAX_RESULTS_PER_QUERY = 10


@dataclass
class SourceOutcome:
    status: str  # 'completed' | 'failed' | 'unavailable'
    count: int = 0
    error: str | None = None


@dataclass
class ResearchSourcesSummary:
    pubmed: SourceOutcome
    clinical_trials: SourceOutcome
    web_research: SourceOutcome
    studies_stored: dict[str, int]

    @property
    def any_succeeded(self) -> bool:
        return any(o.status == "completed" for o in (self.pubmed, self.clinical_trials, self.web_research))

    @property
    def any_failed(self) -> bool:
        return any(o.status == "failed" for o in (self.pubmed, self.clinical_trials, self.web_research))

    @property
    def total_stored(self) -> int:
        return sum(self.studies_stored.values())


async def _run_pubmed(db: AsyncSession, research_job_id: UUID, queries: list[str]):
    if not queries:
        return SourceOutcome(status="unavailable", error="No PubMed search queries were generated."), []
    try:
        client = PubMedClient()
    except PubMedIntegrationError as exc:
        return SourceOutcome(status="unavailable", error=str(exc)), []

    try:
        agent = PubMedAgent(client)
        result = await agent.run(
            db, research_job_id, SourceAgentInput(queries=queries, max_results_per_query=MAX_RESULTS_PER_QUERY)
        )
        return SourceOutcome(status="completed", count=len(result.articles)), result.articles
    except AgentExecutionError as exc:
        logger.warning("PubMed research failed for job %s: %s", research_job_id, exc)
        return SourceOutcome(status="failed", error=str(exc)), []


async def _run_clinical_trials(db: AsyncSession, research_job_id: UUID, queries: list[str]):
    if not queries:
        return SourceOutcome(status="unavailable", error="No ClinicalTrials.gov search queries were generated."), []
    try:
        client = ClinicalTrialsClient()
        agent = ClinicalTrialsAgent(client)
        result = await agent.run(
            db, research_job_id, SourceAgentInput(queries=queries, max_results_per_query=MAX_RESULTS_PER_QUERY)
        )
        return SourceOutcome(status="completed", count=len(result.trials)), result.trials
    except ClinicalTrialsIntegrationError as exc:
        return SourceOutcome(status="unavailable", error=str(exc)), []
    except AgentExecutionError as exc:
        logger.warning("ClinicalTrials.gov research failed for job %s: %s", research_job_id, exc)
        return SourceOutcome(status="failed", error=str(exc)), []


async def _run_web_research(db: AsyncSession, research_job_id: UUID, queries: list[str]):
    if not queries:
        return SourceOutcome(status="unavailable", error="No web research queries were generated."), []
    try:
        client = TavilyClient()
    except TavilyIntegrationError as exc:
        # Missing TAVILY_API_KEY is a configuration gap, not a pipeline
        # failure — the job should still proceed with PubMed/CT.gov alone.
        return SourceOutcome(status="unavailable", error=str(exc)), []

    try:
        agent = WebResearchAgent(client)
        result = await agent.run(
            db, research_job_id, SourceAgentInput(queries=queries, max_results_per_query=MAX_RESULTS_PER_QUERY)
        )
        return SourceOutcome(status="completed", count=len(result.results)), result.results
    except AgentExecutionError as exc:
        logger.warning("Web research failed for job %s: %s", research_job_id, exc)
        return SourceOutcome(status="failed", error=str(exc)), []


async def run_source_research(
    db: AsyncSession, research_job_id: UUID, search_queries: dict
) -> ResearchSourcesSummary:
    pubmed_queries = search_queries.get("pubmed", [])
    ct_queries = search_queries.get("clinical_trials", [])
    web_queries = search_queries.get("web", [])

    # Run sequentially against the shared AsyncSession (SQLAlchemy's
    # AsyncSession is not safe for concurrent use from multiple coroutines),
    # but each source's *external API call* still gets its own timeout/retry
    # and a failure in one never prevents the others from running.
    pubmed_outcome, pubmed_articles = await _run_pubmed(db, research_job_id, pubmed_queries)
    ct_outcome, ct_trials = await _run_clinical_trials(db, research_job_id, ct_queries)
    web_outcome, web_results = await _run_web_research(db, research_job_id, web_queries)

    candidates = candidates_from_pubmed(pubmed_articles) + candidates_from_clinical_trials(ct_trials)
    candidates = deduplicate(candidates)
    web_candidates = deduplicate(candidates_from_web(web_results))
    # Dedupe web candidates against what PubMed/CT.gov already found, so a
    # Tavily hit for a paper already retrieved structurally doesn't create
    # a second study record.
    all_candidates = deduplicate(candidates + web_candidates)

    studies_stored = await persist_candidates(db, research_job_id, all_candidates)

    return ResearchSourcesSummary(
        pubmed=pubmed_outcome,
        clinical_trials=ct_outcome,
        web_research=web_outcome,
        studies_stored=studies_stored,
    )
