"""
Purge job — hard-deletes blobs that have sat in the "deleted" holding
container past the retention window, and marks their Mongo record purged.

Not numbered stage1..stage7: those run per-document as part of
process_document(); this runs on a timer independent of any single
document's processing. Companion to reconciliation_job.py.

This is the actual authority on *when* a soft-deleted document becomes
permanently gone — the Blob Storage lifecycle management policy on the
deleted/ container (infrastructure/terraform/modules/storage/main.tf) is a
redundant backstop in case this job doesn't run for a while, not the
primary mechanism, so it also updates the Mongo record (the lifecycle
policy only touches blob storage and has no way to do that).
"""

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

RETENTION_DAYS = 7


def purge_expired_deletions(db, deleted_container_client, retention_days: int = RETENTION_DAYS) -> int:
    """
    Finds every Mongo document with status="deleted" whose deleted_at is
    older than the retention window, deletes its blob from the deleted/
    container, and flips its status to "purged". Returns the count purged.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    purged = 0

    for doc in db["documents"].find({"status": "deleted", "deleted_at": {"$lt": cutoff}}):
        document_id = doc["document_id"]
        blob_path = doc.get("blob_path")

        if blob_path:
            try:
                deleted_container_client.delete_blob(blob_path)
            except Exception as exc:
                # Already gone (e.g. the lifecycle-policy backstop got there
                # first) or never existed at this path — either way, still
                # safe to mark purged; nothing left to clean up.
                logger.info("Blob delete for %s at %s: %s (continuing)", document_id, blob_path, exc)

        db["documents"].update_one(
            {"document_id": document_id},
            {"$set": {"status": "purged", "purged_at": datetime.now(timezone.utc).isoformat()}},
        )
        purged += 1
        logger.info("Purged %s (deleted_at=%s, past %d-day retention)", document_id, doc.get("deleted_at"), retention_days)

    return purged
