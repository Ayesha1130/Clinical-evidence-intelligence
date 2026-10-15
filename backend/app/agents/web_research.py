from app.agents.base import BaseAgent
from app.integrations.tavily import TavilyClient
from app.schemas.source_agents import SourceAgentInput, WebResearchAgentOutput, WebResultSchema


class WebResearchAgent(BaseAgent[SourceAgentInput, WebResearchAgentOutput]):
    name = "web_research"
    timeout_seconds = 30.0
    max_attempts = 3

    def __init__(self, client: TavilyClient) -> None:
        self._client = client

    async def _execute(self, payload: SourceAgentInput) -> WebResearchAgentOutput:
        seen_urls: set[str] = set()
        results: list[WebResultSchema] = []

        for query in payload.queries:
            hits = await self._client.search(query, max_results=payload.max_results_per_query)
            for hit in hits:
                if hit.url in seen_urls:
                    continue
                seen_urls.add(hit.url)
                results.append(
                    WebResultSchema(
                        title=hit.title,
                        url=hit.url,
                        domain=hit.domain,
                        snippet=hit.snippet,
                        retrieved_at=hit.retrieved_at,
                        score=hit.score,
                    )
                )

        return WebResearchAgentOutput(results=results)
