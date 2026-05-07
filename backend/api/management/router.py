"""
Knowledge Management API — document upload, versioning, user management, monitoring.

This powers the CMS frontend. Only authenticated users with the right role
can access these endpoints.
"""

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.security import OAuth2PasswordRequestForm

from backend.core.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    require_role,
    verify_password,
)
from backend.core.clients import get_db
from backend.core.config import get_settings
from backend.models.documents import (
    ActivityLog,
    DocumentListResponse,
    DocumentRecord,
    DocumentStatus,
    DocumentUploadResponse,
)
from backend.services.monitoring_service import get_metrics_summary

router = APIRouter(prefix="/manage", tags=["Knowledge Management"])


# ── Authentication ────────────────────────────────────────────────────────────

@router.post("/auth/token")
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> dict:
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
async def register(
    email: str,
    password: str,
    role: str = "viewer",
    _admin: Annotated[dict, Depends(require_role("admin"))] = None,
) -> dict:
    """Creates a new CMS user. Only admins can register new users."""
    db = get_db()
    existing = await db["users"].find_one({"email": email})
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")

    await db["users"].insert_one(
        {
            "user_id": str(uuid.uuid4()),
            "email": email,
            "password_hash": hash_password(password),
            "role": role,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return {"message": f"User {email} created with role {role}"}


# ── Document Management ────────────────────────────────────────────────────────

@router.post("/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    version: str = Form("1.0"),
    current_user: Annotated[dict, Depends(require_role("admin", "editor"))] = None,
) -> DocumentUploadResponse:
    """
    Uploads a PIL document (PDF/DOCX/PPTX) to Azure Data Lake Storage.
    The Azure Function is triggered automatically to process and index it.
    """
    from azure.storage.blob.aio import BlobServiceClient

    s = get_settings()
    document_id = str(uuid.uuid4())
    blob_path = f"{document_id}/{file.filename}"

    allowed_types = {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                     "application/vnd.openxmlformats-officedocument.presentationml.presentation"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")

    # Upload to ADLS — this triggers the Azure Function automatically
    async with BlobServiceClient.from_connection_string(s.storage_connection) as blob_svc:
        async with blob_svc.get_blob_client(
            container=s.storage_container_name, blob=blob_path
        ) as blob:
            content = await file.read()
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
    page: int = 1,
    limit: int = 20,
    status: str | None = None,
    _user: Annotated[dict, Depends(get_current_user)] = None,
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
    current_user: Annotated[dict, Depends(require_role("admin"))] = None,
) -> dict:
    """Removes a document from the knowledge base and its search index entry."""
    db = get_db()
    result = await db["documents"].delete_one({"document_id": document_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")

    await _log_activity(db, "delete", document_id, current_user["email"], {})
    return {"message": f"Document {document_id} deleted"}


# ── Activity Logs ─────────────────────────────────────────────────────────────

@router.get("/activity-logs", response_model=list[ActivityLog])
async def get_activity_logs(
    limit: int = 50,
    _admin: Annotated[dict, Depends(require_role("admin"))] = None,
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
    _user: Annotated[dict, Depends(get_current_user)] = None,
) -> dict:
    """Returns Q&A performance metrics for the monitoring dashboard."""
    return await get_metrics_summary()


# ── Internal helper ───────────────────────────────────────────────────────────

async def _log_activity(db, action: str, document_id: str, user_email: str, details: dict) -> None:
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
