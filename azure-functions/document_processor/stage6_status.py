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
    metadata: dict | None = None,
    error: str | None = None,
) -> None:
    update: dict[str, Any] = {
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if metadata:
        update["metadata"] = metadata
    if error:
        update["error"] = error

    db["documents"].update_one(
        {"document_id": document_id},
        {"$set": update},
        upsert=True,
    )
