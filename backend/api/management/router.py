"""
Knowledge Management API — document upload, versioning, user management, monitoring.

This powers the CMS frontend. Only authenticated users with the right role
can access these endpoints.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field

from backend.core.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    require_role,
    verify_password,
)
from backend.core.clients import get_db, get_search_client
from backend.core.config import get_settings
from backend.core.limiter import limiter
from backend.models.documents import (
    ActivityLog,
    DocumentListResponse,
    DocumentRecord,
    DocumentStatus,
    DocumentUploadResponse,
)
from backend.services.monitoring_service import get_metrics_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/manage", tags=["Knowledge Management"])

_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

_MAGIC_BYTES: dict[str, bytes] = {
    "application/pdf": b"%PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": b"PK\x03\x04",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": b"PK\x03\x04",
}


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, description="Minimum 12 characters")
    role: Literal["admin", "editor", "viewer"] = "viewer"


# ── Authentication ────────────────────────────────────────────────────────────

@router.post("/auth/token")
@limiter.limit("10/minute")
async def login(request: Request, form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> dict:
    """
    Exchanges username + password for a JWT access token.
    Used by the CMS frontend login form.
    """
    db = get_db()
    user = await db["users"].find_one({"email": form.username})
    if not user or not verify_password(form.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token({"sub": user["email"], "role": user["role"]})
    return {"access_token": token, "token_type": "bearer"}


@router.post("/auth/register")
@limiter.limit("10/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    _admin: Annotated[dict, Depends(require_role("admin"))],
) -> dict:
    """Creates a new CMS user. Only admins can register new users."""
    db = get_db()
    existing = await db["users"].find_one({"email": body.email})
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")

    await db["users"].insert_one(
        {
            "user_id": str(uuid.uuid4()),
            "email": body.email,
            "password_hash": hash_password(body.password),
            "role": body.role,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return {"message": f"User {body.email} created with role {body.role}"}


# ── Document Management ────────────────────────────────────────────────────────

@router.post("/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(
    current_user: Annotated[dict, Depends(require_role("admin", "editor"))],
    file: UploadFile = File(...),
    title: str = Form(...),
    version: str = Form("1.0"),
) -> DocumentUploadResponse:
    """
    Uploads a PIL document (PDF/DOCX/PPTX) to Azure Data Lake Storage.
    The Azure Function is triggered automatically to process and index it.
    """
    from azure.storage.blob.aio import BlobServiceClient

    s = get_settings()
    document_id = str(uuid.uuid4())
    blob_path = f"{document_id}/{file.filename}"

    if file.content_type not in _MAGIC_BYTES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")

    content = await file.read()

    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB limit")

    expected_magic = _MAGIC_BYTES[file.content_type]
    if not content.startswith(expected_magic):
        raise HTTPException(status_code=400, detail="File content does not match declared type")

    # Upload to ADLS — this triggers the Azure Function automatically
    async with BlobServiceClient.from_connection_string(s.storage_connection) as blob_svc:
        async with blob_svc.get_blob_client(
            container=s.storage_container_name, blob=blob_path
        ) as blob:
            await blob.upload_blob(content, overwrite=True)

    # Create a tracking record in MongoDB
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    await db["documents"].insert_one(
        {
            "document_id": document_id,
            "filename": file.filename,
            "title": title,
            "version": version,
            "status": "pending",
            "uploaded_by": current_user["email"],
            "blob_path": blob_path,
            "created_at": now,
            "updated_at": now,
        }
    )

    await _log_activity(db, "upload", document_id, current_user["email"],
                        {"filename": file.filename, "version": version})

    return DocumentUploadResponse(
        document_id=document_id,
        filename=file.filename,
        status=DocumentStatus.PENDING,
        message="Upload successful. Document is being processed and indexed.",
    )


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    _user: Annotated[dict, Depends(get_current_user)],
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: str | None = None,
) -> DocumentListResponse:
    """Lists all documents in the knowledge base with pagination."""
    db = get_db()
    query = {}
    if status:
        query["status"] = status

    skip = (page - 1) * limit
    total = await db["documents"].count_documents(query)
    cursor = db["documents"].find(query).sort("created_at", -1).skip(skip).limit(limit)
    docs_raw = await cursor.to_list(limit)

    documents = [
        DocumentRecord(
            document_id=d["document_id"],
            filename=d["filename"],
            status=DocumentStatus(d.get("status", "pending")),
            metadata=d.get("metadata", {}),
            chunk_count=d.get("chunk_count", 0),
            created_at=datetime.fromisoformat(d["created_at"]),
            updated_at=datetime.fromisoformat(d["updated_at"]),
            error=d.get("error"),
        )
        for d in docs_raw
    ]
    return DocumentListResponse(documents=documents, total=total, page=page, limit=limit)


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    current_user: Annotated[dict, Depends(require_role("admin"))],
) -> dict:
    """
    Fully removes a document from the knowledge base:
      1. MongoDB tracking record
      2. ADLS blob (source file)
      3. Azure AI Search index chunks
      4. Cosmos Gremlin graph vertices (best-effort)
    """
    from azure.storage.blob.aio import BlobServiceClient

    db = get_db()
    doc = await db["documents"].find_one({"document_id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    s = get_settings()

    # 1. Remove MongoDB record first so the document is immediately invisible
    await db["documents"].delete_one({"document_id": document_id})

    # 2. Delete the source blob from ADLS
    try:
        async with BlobServiceClient.from_connection_string(s.storage_connection) as blob_svc:
            blob_client = blob_svc.get_blob_client(
                container=s.storage_container_name, blob=doc["blob_path"]
            )
            await blob_client.delete_blob()
    except Exception as exc:
        logger.warning("Blob delete failed for %s: %s", document_id, exc)

    # 3. Delete all search index chunks belonging to this document.
    # Track deleted IDs to avoid infinite loops: Azure Search is eventually consistent
    # and can return the same IDs in the next query until the index refreshes.
    try:
        search_client = get_search_client()
        deleted_ids: set[str] = set()
        max_iterations = 20  # safety cap
        for _ in range(max_iterations):
            chunk_ids = []
            async for r in await search_client.search(
                search_text="*",
                filter=f"document_id eq '{document_id}'",
                select=["id"],
                top=1000,
            ):
                if r["id"] not in deleted_ids:
                    chunk_ids.append({"id": r["id"]})
            if not chunk_ids:
                break
            await search_client.delete_documents(documents=chunk_ids)
            deleted_ids.update(c["id"] for c in chunk_ids)
            if len(chunk_ids) < 1000:
                break
        else:
            logger.warning("Search cleanup hit iteration cap for %s — index may have stale chunks", document_id)
    except Exception as exc:
        logger.warning("Search index cleanup failed for %s: %s", document_id, exc)

    # 4. Drop Gremlin vertices (best-effort; graph is supplementary)
    try:
        await asyncio.to_thread(_drop_gremlin_vertices_sync, document_id, s)
    except Exception as exc:
        logger.warning("Gremlin cleanup failed for %s: %s", document_id, exc)

    await _log_activity(db, "delete", document_id, current_user["email"], {})
    return {"message": f"Document {document_id} deleted"}


# ── Activity Logs ─────────────────────────────────────────────────────────────

@router.get("/activity-logs", response_model=list[ActivityLog])
async def get_activity_logs(
    _admin: Annotated[dict, Depends(require_role("admin"))],
    limit: int = Query(50, ge=1, le=200),
) -> list[ActivityLog]:
    """Returns the latest CMS activity log entries."""
    db = get_db()
    cursor = db["activity_logs"].find().sort("created_at", -1).limit(limit)
    logs_raw = await cursor.to_list(limit)
    return [
        ActivityLog(
            log_id=log["log_id"],
            action=log["action"],
            document_id=log.get("document_id"),
            user_email=log["user_email"],
            details=log.get("details", {}),
            created_at=datetime.fromisoformat(log["created_at"]),
        )
        for log in logs_raw
    ]


# ── Monitoring Dashboard Data ─────────────────────────────────────────────────

@router.get("/metrics")
async def get_metrics(
    _user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Returns Q&A performance metrics for the monitoring dashboard."""
    return await get_metrics_summary()


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _log_activity(db, action: str, document_id: str, user_email: str, details: dict) -> None:
    try:
        await db["activity_logs"].insert_one(
            {
                "log_id": str(uuid.uuid4()),
                "action": action,
                "document_id": document_id,
                "user_email": user_email,
                "details": details,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as exc:
        logger.warning("Activity log write failed for %s/%s: %s", action, document_id, exc)


def _drop_gremlin_vertices_sync(document_id: str, s) -> None:
    """
    Drops all graph vertices for a document via Gremlin (sync, runs in thread).
    Uses a binding for document_id to prevent injection.
    """
    from gremlin_python.driver import client as gremlin_client_lib
    from gremlin_python.driver import serializer

    gremlin = gremlin_client_lib.Client(
        s.cosmos_gremlin_endpoint,
        "g",
        username=f"/dbs/{s.cosmos_gremlin_database}/colls/{s.cosmos_gremlin_graph}",
        password=s.cosmos_gremlin_key,
        message_serializer=serializer.GraphSONSerializersV2d0(),
    )
    try:
        gremlin.submit(
            "g.V().has('document_id', did).drop()",
            {"did": document_id},
        ).all().result()
    finally:
        gremlin.close()
