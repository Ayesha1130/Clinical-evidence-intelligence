"""
Embedding client abstraction, separate from LLMClient's completion methods
so RAG's embedding logic isn't hardcoded inside the RAG service itself and
can be swapped independently of the text-generation provider.

Critical safety property: every embedding is validated against
EMBEDDING_DIMENSION (the actual pgvector column width) before being
returned. A silent dimension mismatch would corrupt every future
similarity search, so this fails loudly instead.
"""
from abc import ABC, abstractmethod

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.models.evidence import EMBEDDING_DIMENSION


class EmbeddingDimensionError(Exception):
    pass


class EmbeddingClient(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text, in the same order."""


class OpenAIEmbeddingClient(EmbeddingClient):
    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_embedding_model
        self._expected_dimension = settings.embedding_dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.embeddings.create(model=self._model, input=texts)
        vectors = [item.embedding for item in response.data]
        for vector in vectors:
            if len(vector) != self._expected_dimension:
                raise EmbeddingDimensionError(
                    f"Embedding model '{self._model}' returned a {len(vector)}-dimensional vector, "
                    f"but the configured dimension is {self._expected_dimension} "
                    f"(and the database column is vector({EMBEDDING_DIMENSION})). "
                    "Refusing to persist a mismatched embedding — update EMBEDDING_DIMENSION "
                    "and the pgvector column together if you change embedding models."
                )
        return vectors


def get_embedding_client() -> EmbeddingClient:
    return OpenAIEmbeddingClient()
