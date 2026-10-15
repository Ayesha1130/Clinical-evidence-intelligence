"""
LLM provider abstraction.

Agents depend on `LLMClient`, not on OpenAI's SDK directly, so switching
providers later (e.g. to Anthropic) means implementing this interface once
rather than touching every agent.
"""
from abc import ABC, abstractmethod

from openai import AsyncOpenAI

from app.core.config import get_settings


class LLMClient(ABC):
    @abstractmethod
    async def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        """Return a raw JSON string the caller will validate against a Pydantic schema."""

    @abstractmethod
    async def complete_text(self, system_prompt: str, user_prompt: str) -> str:
        """Return a plain-text completion (used for report prose, Q&A answers)."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for a batch of texts."""


class OpenAILLMClient(LLMClient):
    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model
        self._embedding_model = settings.openai_embedding_model

    async def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("LLM returned an empty completion.")
        return content

    async def complete_text(self, system_prompt: str, user_prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("LLM returned an empty completion.")
        return content

    async def embed(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(model=self._embedding_model, input=texts)
        return [item.embedding for item in response.data]


def get_llm_client() -> LLMClient:
    settings = get_settings()
    if settings.llm_provider == "openai":
        return OpenAILLMClient()
    raise NotImplementedError(f"LLM provider '{settings.llm_provider}' is not implemented yet.")
