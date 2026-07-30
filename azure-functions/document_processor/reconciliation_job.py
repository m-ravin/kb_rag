"""
Reconciliation job — nightly timer that diffs Mongo's "indexed" document_ids
against what Azure Search actually has, and logs any drift.

Not numbered stage1..stage7: those run per-document as part of
process_document(); this runs on a timer independent of any single
document's processing. Companion to purge_job.py.

Exists because this system already hit exactly the drift it detects: a
folder-name collision (see document_identity.py) let one document's Search
chunks silently overwrite another's, and it was only found because a human
happened to notice a missing PDF a day later. This job would have logged
that the same day.

Detection only for now, not auto-healing — logs drift at WARNING/ERROR so
the Azure Monitor alert rule on Function App failures/traces (see
infrastructure/terraform/modules/monitoring) can be pointed at these log
lines. Automatically re-triggering ingestion for a "missing from Search"
document is a larger, riskier change (which blob does it re-read? what if
the source was already purged?) deliberately deferred — see
docs/adr/0016-document-lifecycle-and-data-integrity.md.
"""

import logging

logger = logging.getLogger(__name__)


def reconcile(db, search_client, environment: str) -> dict:
    """
    Returns {"missing_from_search": [...], "orphaned_in_search": [...]} —
    both empty on a clean run.
    """
    mongo_indexed_ids = {
        doc["document_id"]
        for doc in db["documents"].find(
            {"status": "indexed", "environment": environment}, {"document_id": 1}
        )
    }

    # Deliberately no `top=` cap — the SDK's SearchItemPaged iterator pages
    # through the full result set as it's consumed. Passing top would instead
    # cap the TOTAL rows returned across all pages, silently truncating the
    # comparison once the index holds more chunks than that cap.
    search_ids: set[str] = {
        r["document_id"]
        for r in search_client.search(
            search_text="*", filter=f"environment eq '{environment}'", select=["document_id"]
        )
    }

    missing_from_search = sorted(mongo_indexed_ids - search_ids)
    orphaned_in_search = sorted(search_ids - mongo_indexed_ids)

    if missing_from_search:
        logger.error(
            "Reconciliation drift: %d document(s) marked 'indexed' in Mongo but missing from Search: %s",
            len(missing_from_search), missing_from_search,
        )
    if orphaned_in_search:
        logger.warning(
            "Reconciliation drift: %d document_id(s) in Search with no matching 'indexed' Mongo record: %s",
            len(orphaned_in_search), orphaned_in_search,
        )
    if not missing_from_search and not orphaned_in_search:
        logger.info("Reconciliation: Mongo and Search are in sync (%d indexed documents)", len(mongo_indexed_ids))

    return {"missing_from_search": missing_from_search, "orphaned_in_search": orphaned_in_search}
