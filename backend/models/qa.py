"""Pydantic models for Q&A flow requests and responses."""

from datetime import datetime
from enum import Enum
from typing import Any

from typing import Literal

from pydantic import BaseModel, Field


class QuestionType(str, Enum):
    FAQ = "faq"
    PROCEDURAL = "procedural"
    FACTUAL = "factual"
    COMPARISON = "comparison"
    UNKNOWN = "unknown"


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    session_id: str | None = None
    language: Literal["en", "ms", "zh", "ta", "fr", "de", "es", "ar", "pt", "id"] = "en"
    max_chunks: int = Field(default=5, ge=1, le=20)


class ChunkResult(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    content: str
    score: float


class AskResponse(BaseModel):
    session_id: str
    question: str
    answer: str
    question_type: QuestionType
    sources: list[ChunkResult]
    language: str
    tokens_used: int
    latency_ms: float
    flagged_pii: bool
    flagged_unsafe: bool
    created_at: datetime


class TaskRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    session_id: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class TaskResponse(BaseModel):
    result: Any
    tokens_used: int | None = None
    latency_ms: float
