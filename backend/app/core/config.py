"""
Centralized, typed application configuration.

All secrets are read from environment variables only. Nothing here is
ever imported by frontend code, and this module never logs secret values.
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"

    # Database
    database_url: str

    # Supabase
    supabase_url: str
    supabase_service_key: str
    supabase_jwt_secret: str

    # LLM
    llm_provider: str = "openai"
    openai_api_key: str
    openai_model: str = "gpt-4.1"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536

    # Research APIs
    tavily_api_key: str | None = None
    ncbi_email: str
    ncbi_api_key: str | None = None

    # CORS
    cors_allowed_origins: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> "Settings":
    """
    Cached settings accessor. Raises a clear pydantic ValidationError at
    startup (not at first use) if a required variable is missing — we never
    silently fall back to a mocked value.
    """
    return Settings()  # type: ignore[call-arg]
