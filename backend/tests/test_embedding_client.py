"""
Tests for the embedding client's dimension validation — never silently
persist a mismatched vector.
"""
import pytest

from app.integrations.embeddings import EmbeddingDimensionError, OpenAIEmbeddingClient


class _FakeOpenAIEmbeddingsAPI:
    def __init__(self, dimension: int):
        self._dimension = dimension

    async def create(self, model, input):
        from types import SimpleNamespace

        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1] * self._dimension) for _ in input])


class _FakeOpenAIClient:
    def __init__(self, dimension: int):
        self.embeddings = _FakeOpenAIEmbeddingsAPI(dimension)


@pytest.mark.asyncio
async def test_correct_dimension_passes_through(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = OpenAIEmbeddingClient()
    client._client = _FakeOpenAIClient(dimension=1536)

    vectors = await client.embed(["some text"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 1536


@pytest.mark.asyncio
async def test_mismatched_dimension_raises_clear_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = OpenAIEmbeddingClient()
    client._client = _FakeOpenAIClient(dimension=768)

    with pytest.raises(EmbeddingDimensionError, match="768"):
        await client.embed(["some text"])


@pytest.mark.asyncio
async def test_empty_input_returns_empty_list_without_calling_api(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = OpenAIEmbeddingClient()
    client._client = _FakeOpenAIClient(dimension=1536)

    assert await client.embed([]) == []
