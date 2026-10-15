from enum import Enum

from pydantic import BaseModel, Field, field_validator

NOT_ENOUGH_INFO = "This paper does not provide enough information to answer that question."


class DocumentType(str, Enum):
    ABSTRACT = "ABSTRACT"
    TRIAL_SUMMARY = "TRIAL_SUMMARY"
    WEB_CONTENT = "WEB_CONTENT"
    FULL_TEXT = "FULL_TEXT"


class AskQuestionRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class AskAnswerLLMOutput(BaseModel):
    """Raw shape the LLM must return. `supporting_chunk_index` refers to
    the 0-based position within the context chunks it was given — used to
    map the excerpt back to a real chunk_id/similarity for the API
    response, and to verify the excerpt against that SPECIFIC chunk's text
    rather than the whole assembled context."""

    answer: str
    grounded: bool
    supporting_excerpt: str | None = None
    supporting_chunk_index: int | None = None

    @field_validator("answer")
    @classmethod
    def answer_not_blank(cls, v: str) -> str:
        return v.strip() or NOT_ENOUGH_INFO


class CitationOut(BaseModel):
    document_id: str
    chunk_id: str
    excerpt: str
    similarity: float


class AskResponse(BaseModel):
    answer: str
    citations: list[CitationOut] = Field(default_factory=list)
    grounded: bool
    document_type: DocumentType | None = None
