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


def _sanitize_filename(raw: str | None) -> str:
    """
    Reduces the uploaded filename to a bare basename before it's used to
    build the blob path and compute_document_id(). The Function pipeline
    derives its filename the same way — via blob_name.split("/")[-1] — so a
    filename containing "/" (or a missing filename) would otherwise make the
    two sides compute different document_ids for the same upload, exactly
    the bug this endpoint was fixed to avoid.
    """
    if not raw or not raw.strip():
        raise HTTPException(status_code=400, detail="Filename is required")
    name = raw.strip().replace("\\", "/").split("/")[-1]
    if not name:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return name


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
    from backend.core.document_identity import compute_document_id

    s = get_settings()
    upload_folder = str(uuid.uuid4())
    filename = _sanitize_filename(file.filename)
    # Same id the Function ingestion pipeline will compute for this exact
    # upload_folder/filename, so the placeholder record created below is the
    # SAME MongoDB document the Function later updates to "indexed" — not a
    # second, disconnected record left permanently stuck at "pending".
    document_id = compute_document_id(upload_folder, filename)
    blob_path = f"{upload_folder}/{filename}"

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
            "filename": filename,
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
                        {"filename": filename, "version": version})

    return DocumentUploadResponse(
        document_id=document_id,
        filename=filename,
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

    def _safe_status(raw_status: str) -> DocumentStatus:
        try:
            return DocumentStatus(raw_status)
        except ValueError:
            # UNKNOWN, not FAILED: defaulting to FAILED would make an
            # unrecognized-but-benign status (e.g. a future status value)
            # look like a processing failure to the CMS user.
            logger.warning("unrecognized document status %r, defaulting to UNKNOWN", raw_status)
            return DocumentStatus.UNKNOWN

    # Documents created by the CMS upload endpoint have top-level filename/created_at;
    # documents created by the Function ingestion pipeline only set filename inside
    # metadata and have no created_at at all — fall back to updated_at for those.
    documents = []
    for d in docs_raw:
        timestamp = d.get("updated_at") or d.get("created_at")
        if not timestamp:
            logger.warning(
                "document %s has neither updated_at nor created_at, excluding from list",
                d.get("document_id", "<unknown>"),
            )
            continue
        documents.append(
            DocumentRecord(
                document_id=d["document_id"],
                filename=d.get("filename") or d.get("metadata", {}).get("filename", "unknown"),
                status=_safe_status(d.get("status", "pending")),
                metadata=d.get("metadata", {}),
                chunk_count=d.get("chunk_count", 0),
                created_at=datetime.fromisoformat(d.get("created_at") or timestamp),
                updated_at=datetime.fromisoformat(timestamp),
                error=d.get("error"),
            )
        )
    return DocumentListResponse(documents=documents, total=total, page=page, limit=limit)


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    current_user: Annotated[dict, Depends(require_role("admin"))],
) -> dict:
    """
    Soft-deletes a document — nothing here is permanent:
      1. MongoDB record marked status="deleted" (kept, not removed — an
         audit trail of who deleted what and when)
      2. Its archived blob is moved to the "deleted" holding container
         (purge_job.py, a nightly timer function, hard-deletes it after a
         7-day retention window — see
         docs/adr/0016-document-lifecycle-and-data-integrity.md)
      3. Azure AI Search index chunks removed immediately (these are a
         derived/regenerable index, not the source of truth, so there's no
         reason to soft-delete them too)
      4. Cosmos Gremlin graph vertices dropped (best-effort; graph is
         supplementary)

    Previously this hard-deleted the Mongo record and the blob in one shot,
    with no recovery window — soft-delete replaced that after this system's
    storage account was found to have soft-delete disabled at the account
    level too (now fixed separately, but app-level recoverability shouldn't
    depend solely on that platform setting).
    """
    from azure.core.exceptions import ResourceNotFoundError
    from azure.storage.blob.aio import BlobServiceClient

    db = get_db()
    doc = await db["documents"].find_one({"document_id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    s = get_settings()

    # 1. Mark deleted rather than removing the record — see docstring.
    now = datetime.now(timezone.utc).isoformat()
    await db["documents"].update_one(
        {"document_id": document_id},
        {"$set": {"status": "deleted", "deleted_at": now, "deleted_by": current_user["email"]}},
    )

    # 2. Move the blob to the deleted/ holding container. Checked in this
    # order because a successfully-processed document's blob has already
    # been moved out of the source container by the Function App's archive
    # step (stage7_archive.py) — only a document that failed processing (or
    # is still mid-processing) would still have its blob in the source
    # container. Download-then-upload-then-delete (not start_copy_from_url):
    # both containers are private, and this mirrors the same approach
    # stage7_archive.py already uses for source→processed moves.
    try:
        async with BlobServiceClient.from_connection_string(s.storage_connection) as blob_svc:
            moved = False
            for container_name in (s.storage_processed_container_name, s.storage_container_name):
                src = blob_svc.get_blob_client(container=container_name, blob=doc["blob_path"])
                try:
                    downloader = await src.download_blob()
                    data = await downloader.readall()
                except ResourceNotFoundError:
                    continue
                dest = blob_svc.get_blob_client(
                    container=s.storage_deleted_container_name, blob=doc["blob_path"]
                )
                await dest.upload_blob(data, overwrite=True)
                await src.delete_blob()
                moved = True
                break
            if not moved:
                logger.warning(
                    "No blob found to soft-delete for %s at path %s (checked %s and %s)",
                    document_id, doc["blob_path"], s.storage_processed_container_name, s.storage_container_name,
                )
    except Exception as exc:
        logger.warning("Blob soft-delete failed for %s: %s", document_id, exc)

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
