"""
Status stage — writes document processing status updates to MongoDB.

Takes an already-constructed database handle (dependency injection) instead
of creating one itself, so this is testable with a mock db.
"""

from datetime import datetime, timezone
from typing import Any


def update_document_status(
    db,
    document_id: str,
    status: str,
    *,
    upload_folder: str | None = None,
    filename: str | None = None,
    environment: str | None = None,
    metadata: dict | None = None,
    error: str | None = None,
    chunk_count: int | None = None,
) -> None:
    update: dict[str, Any] = {
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if upload_folder is not None:
        update["upload_folder"] = upload_folder
    if filename is not None:
        update["filename"] = filename
    if upload_folder is not None and filename is not None:
        # Same field name/shape the management-API upload path
        # (backend/api/management/router.py) already writes, so purge_job.py
        # and reconciliation_job.py can rely on one consistent field
        # regardless of which of the two ingestion paths created the record.
        update["blob_path"] = f"{upload_folder}/{filename}"
    if environment is not None:
        update["environment"] = environment
    if metadata:
        update["metadata"] = metadata
    if error:
        update["error"] = error
    if chunk_count is not None:
        update["chunk_count"] = chunk_count

    db["documents"].update_one(
        {"document_id": document_id},
        {"$set": update},
        upsert=True,
    )
