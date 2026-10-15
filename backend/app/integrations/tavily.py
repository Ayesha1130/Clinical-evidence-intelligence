"""
Real Tavily web research integration.

Docs: https://docs.tavily.com/
Used for broader evidence discovery (systematic reviews, guidelines,
reputable medical organizations) beyond what PubMed/ClinicalTrials.gov
index directly. Every result carries its own URL/domain/snippet/timestamp
so downstream code can classify source quality rather than trusting it
blindly (see app/services/source_classification.py in Phase 4).
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


@dataclass
class WebResult:
    title: str
    url: str
    domain: str
    snippet: str
    retrieved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    score: float | None = None


class TavilyIntegrationError(Exception):
    pass


class TavilyClient:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.tavily_api_key:
            raise TavilyIntegrationError(
                "TAVILY_API_KEY is not configured. Web research is unavailable until it's set."
            )
        self._api_key = settings.tavily_api_key

    async def search(self, query: str, max_results: int = 8) -> list[WebResult]:
        payload = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_answer": False,
            # Nudge toward higher-quality medical/evidence sources without
            # pretending this makes every result authoritative — quality
            # classification still happens downstream on every result.
            "include_domains": [],
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(TAVILY_SEARCH_URL, json=payload)
        if resp.status_code != 200:
            raise TavilyIntegrationError(f"Tavily search failed with status {resp.status_code}")

        data = resp.json()
        results = []
        for item in data.get("results", []):
            url = item.get("url", "")
            if not url:
                continue
            results.append(
                WebResult(
                    title=item.get("title") or "Untitled",
                    url=url,
                    domain=urlparse(url).netloc,
                    snippet=item.get("content") or "",
                    score=item.get("score"),
                )
            )
        return results
