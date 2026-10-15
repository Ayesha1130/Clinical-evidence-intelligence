"""
PubMed Research Agent. Wraps PubMedClient (real NCBI E-utilities calls) in
the standard BaseAgent framework so its execution is logged to agent_runs
and gets retry/timeout handling like every other agent.
"""
from app.agents.base import BaseAgent
from app.integrations.pubmed import PubMedClient
from app.schemas.source_agents import PubMedAgentOutput, PubMedArticleSchema, SourceAgentInput


class PubMedAgent(BaseAgent[SourceAgentInput, PubMedAgentOutput]):
    name = "pubmed_research"
    timeout_seconds = 30.0
    max_attempts = 3

    def __init__(self, client: PubMedClient) -> None:
        self._client = client

    async def _execute(self, payload: SourceAgentInput) -> PubMedAgentOutput:
        seen_pmids: set[str] = set()
        articles: list[PubMedArticleSchema] = []

        for query in payload.queries:
            results = await self._client.search_and_fetch(query, max_results=payload.max_results_per_query)
            for article in results:
                if article.pmid in seen_pmids:
                    continue
                seen_pmids.add(article.pmid)
                articles.append(
                    PubMedArticleSchema(
                        pmid=article.pmid,
                        title=article.title,
                        authors=article.authors,
                        journal=article.journal,
                        publication_date=article.publication_date,
                        abstract=article.abstract,
                        doi=article.doi,
                        publication_types=article.publication_types,
                    )
                )

        return PubMedAgentOutput(articles=articles)
