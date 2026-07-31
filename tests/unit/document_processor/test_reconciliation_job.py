"""Tests for the Mongo/Search reconciliation job."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(
    0, str(Path(__file__).resolve().parents[3] / "azure-functions" / "document_processor")
)

from reconciliation_job import reconcile  # noqa: E402


def _mock_db(indexed_document_ids: list[str]):
    db = MagicMock()
    db["documents"].find.return_value = [{"document_id": did} for did in indexed_document_ids]
    return db


def _mock_search_client(search_document_ids: list[str]):
    client = MagicMock()
    client.search.return_value = [{"document_id": did} for did in search_document_ids]
    return client


def test_no_drift_when_mongo_and_search_match():
    db = _mock_db(["doc-a", "doc-b"])
    search_client = _mock_search_client(["doc-a", "doc-b"])

    result = reconcile(db, search_client, "dev")

    assert result == {"missing_from_search": [], "orphaned_in_search": []}


def test_detects_document_missing_from_search():
    # This is the exact failure mode this system already hit: a document
    # marked "indexed" in Mongo whose Search chunks were silently overwritten
    # by a folder-collision (see document_identity.py).
    db = _mock_db(["doc-a", "doc-b"])
    search_client = _mock_search_client(["doc-a"])

    result = reconcile(db, search_client, "dev")

    assert result["missing_from_search"] == ["doc-b"]
    assert result["orphaned_in_search"] == []


def test_detects_orphaned_search_chunks():
    db = _mock_db(["doc-a"])
    search_client = _mock_search_client(["doc-a", "orphan-doc"])

    result = reconcile(db, search_client, "dev")

    assert result["missing_from_search"] == []
    assert result["orphaned_in_search"] == ["orphan-doc"]


def test_filters_search_query_by_environment():
    db = _mock_db([])
    search_client = _mock_search_client([])

    reconcile(db, search_client, "prod")

    _, kwargs = search_client.search.call_args
    assert kwargs["filter"] == "environment eq 'prod'"


def test_filters_mongo_query_by_status_and_environment():
    db = _mock_db([])
    search_client = _mock_search_client([])

    reconcile(db, search_client, "dev")

    args, _ = db["documents"].find.call_args
    assert args[0] == {"status": "indexed", "environment": "dev"}


def test_does_not_cap_search_results_with_top():
    """
    Regression guard: passing top= to search_client.search() caps the TOTAL
    rows returned across all pages, not the page size — which would silently
    truncate the comparison once the index holds more chunks than the cap.
    """
    db = _mock_db([])
    search_client = _mock_search_client([])

    reconcile(db, search_client, "dev")

    _, kwargs = search_client.search.call_args
    assert "top" not in kwargs
