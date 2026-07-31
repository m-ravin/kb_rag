"""Pydantic models for document management."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DocumentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    DELETED = "deleted"
    PURGED = "purged"


class DocumentUploadResponse(BaseModel):
    document_id: str
    filename: str
    status: DocumentStatus
    message: str


class DocumentRecord(BaseModel):
    document_id: str
    filename: str
    status: DocumentStatus
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime
    error: str | None = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentRecord]
    total: int
    page: int
    limit: int


class ActivityLog(BaseModel):
    log_id: str
    action: str
    document_id: str | None
    user_email: str
    details: dict[str, Any]
    created_at: datetime
