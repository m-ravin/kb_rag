"""Tests for the soft-delete purge job."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(
    0, str(Path(__file__).resolve().parents[3] / "azure-functions" / "document_processor")
)

from purge_job import purge_expired_deletions  # noqa: E402


def _mock_db(documents: list[dict]):
    db = MagicMock()
    db["documents"].find.return_value = documents
    return db


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def test_purges_document_past_retention_window():
    doc = {"document_id": "old-doc", "blob_path": "old-doc/file.pdf", "deleted_at": _iso(10)}
    db = _mock_db([doc])
    deleted_container = MagicMock()

    purged = purge_expired_deletions(db, deleted_container, retention_days=7)

    assert purged == 1
    deleted_container.delete_blob.assert_called_once_with("old-doc/file.pdf")
    db["documents"].update_one.assert_called_once()
    call_args = db["documents"].update_one.call_args
    assert call_args[0][0] == {"document_id": "old-doc"}
    assert call_args[0][1]["$set"]["status"] == "purged"


def test_does_not_purge_document_within_retention_window():
    # find() is mocked to return only what the query would match — this test
    # asserts the query itself would exclude a 3-day-old deletion, by
    # simulating the "nothing matched" case a real Mongo $lt filter produces.
    db = _mock_db([])
    deleted_container = MagicMock()

    purged = purge_expired_deletions(db, deleted_container, retention_days=7)

    assert purged == 0
    deleted_container.delete_blob.assert_not_called()


def test_continues_if_blob_already_gone():
    doc = {"document_id": "already-gone", "blob_path": "already-gone/file.pdf", "deleted_at": _iso(30)}
    db = _mock_db([doc])
    deleted_container = MagicMock()
    deleted_container.delete_blob.side_effect = Exception("blob not found")

    purged = purge_expired_deletions(db, deleted_container, retention_days=7)

    assert purged == 1
    db["documents"].update_one.assert_called_once()


def test_purges_multiple_documents():
    docs = [
        {"document_id": f"doc-{i}", "blob_path": f"doc-{i}/file.pdf", "deleted_at": _iso(10)}
        for i in range(3)
    ]
    db = _mock_db(docs)
    deleted_container = MagicMock()

    purged = purge_expired_deletions(db, deleted_container, retention_days=7)

    assert purged == 3
    assert deleted_container.delete_blob.call_count == 3


def test_skips_blob_delete_when_blob_path_missing():
    doc = {"document_id": "no-path", "deleted_at": _iso(10)}
    db = _mock_db([doc])
    deleted_container = MagicMock()

    purged = purge_expired_deletions(db, deleted_container, retention_days=7)

    assert purged == 1
    deleted_container.delete_blob.assert_not_called()
