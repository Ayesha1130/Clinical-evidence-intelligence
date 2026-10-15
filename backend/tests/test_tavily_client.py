import httpx
import pytest

from app.integrations.tavily import TavilyClient, TavilyIntegrationError


def test_missing_api_key_raises_clear_configuration_error(monkeypatch):
    monkeypatch.setattr("app.integrations.tavily.get_settings", lambda: _FakeSettings(tavily_api_key=None))
    with pytest.raises(TavilyIntegrationError, match="TAVILY_API_KEY"):
        TavilyClient()


class _FakeSettings:
    def __init__(self, tavily_api_key):
        self.tavily_api_key = tavily_api_key


SAMPLE_RESPONSE = {
    "results": [
        {
            "title": "Metformin and Cardiovascular Outcomes: A Systematic Review",
            "url": "https://www.nih.gov/example-review",
            "content": "This systematic review examines metformin's cardiovascular effects.",
            "score": 0.91,
        },
        {
            "title": "Random blog about diabetes",
            "url": "https://example-blog.com/post",
            "content": "Some general commentary.",
            "score": 0.4,
        },
        {"title": "No URL result", "content": "Should be skipped."},
    ]
}


@pytest.mark.asyncio
async def test_search_parses_results_and_skips_urlless_entries(monkeypatch):
    monkeypatch.setattr("app.integrations.tavily.get_settings", lambda: _FakeSettings(tavily_api_key="test-key"))
    client = TavilyClient()

    async def fake_post(self, url, json=None, **kwargs):
        request = httpx.Request("POST", url)
        return httpx.Response(200, json=SAMPLE_RESPONSE, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    results = await client.search("metformin cardiovascular systematic review")
    assert len(results) == 2  # the URL-less entry is skipped
    assert results[0].domain == "www.nih.gov"
    assert results[0].title.startswith("Metformin")
    assert results[0].score == 0.91


@pytest.mark.asyncio
async def test_non_200_response_raises_integration_error(monkeypatch):
    monkeypatch.setattr("app.integrations.tavily.get_settings", lambda: _FakeSettings(tavily_api_key="test-key"))
    client = TavilyClient()

    async def fake_post(self, url, json=None, **kwargs):
        request = httpx.Request("POST", url)
        return httpx.Response(503, json={}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(TavilyIntegrationError):
        await client.search("query")
