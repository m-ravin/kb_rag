"""
Integration tests for /manage/* — document management and monitoring.

User journeys covered:
  - As an admin, I want to upload a PIL document and have it tracked in the system
  - As an admin, I want to list documents with pagination
  - As an admin, I want to delete a document from the knowledge base
  - As an admin, I want to see Q&A metrics on the dashboard
  - As a viewer, I want to be rejected when attempting admin-only operations
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


class TestDocumentUpload:

    @pytest.mark.asyncio
    async def test_upload_returns_201_with_document_id(self, client, admin_token, mock_db):
        """Happy path: valid PDF upload → pending document record created."""
        mock_collection = AsyncMock()
        mock_collection.insert_one.return_value = MagicMock(inserted_id="fake")
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        mock_user = {"email": "admin@test.com", "role": "admin"}

        with patch("backend.api.management.router.get_db", return_value=mock_db), \
             patch("backend.core.auth.get_db", return_value=mock_db), \
             patch("backend.api.management.router.get_current_user", return_value=mock_user), \
             patch("backend.api.management.router.require_role", return_value=lambda: mock_user), \
             patch("backend.api.management.router.BlobServiceClient") as mock_blob:

            mock_blob_ctx = AsyncMock()
            mock_blob.from_connection_string.return_value.__aenter__ = AsyncMock(return_value=mock_blob_ctx)
            mock_blob.from_connection_string.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_blob_ctx.get_blob_client.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_blob_ctx.get_blob_client.return_value.__aexit__ = AsyncMock(return_value=False)

            response = await client.post(
                "/manage/documents/upload",
                files={"file": ("test.pdf", b"%PDF-1.4 test content", "application/pdf")},
                data={"title": "Test PIL", "version": "1.0"},
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "document_id" in data
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_upload_rejects_unsupported_file_type(self, client, admin_token, mock_db):
        """Excel files (.xlsx) must be rejected with 400."""
        mock_user = {"email": "admin@test.com", "role": "admin"}

        with patch("backend.api.management.router.get_current_user", return_value=mock_user), \
             patch("backend.api.management.router.require_role", return_value=lambda: mock_user):

            response = await client.post(
                "/manage/documents/upload",
                files={"file": ("data.xlsx", b"fake excel", "application/vnd.ms-excel")},
                data={"title": "Bad file"},
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        assert response.status_code == 400


class TestDocumentList:

    @pytest.mark.asyncio
    async def test_list_returns_paginated_results(self, client, viewer_token, mock_db):
        """GET /manage/documents returns documents array with total count."""
        now = datetime.now(timezone.utc).isoformat()
        fake_docs = [
            {
                "document_id": f"doc-{i}",
                "filename": f"pill_{i}.pdf",
                "status": "indexed",
                "metadata": {},
                "chunk_count": 10,
                "created_at": now,
                "updated_at": now,
            }
            for i in range(3)
        ]

        mock_collection = AsyncMock()
        mock_collection.count_documents.return_value = 3
        cursor = AsyncMock()
        cursor.sort.return_value = cursor
        cursor.skip.return_value = cursor
        cursor.limit.return_value = cursor
        cursor.to_list.return_value = fake_docs
        mock_collection.find.return_value = cursor
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        mock_user = {"email": "viewer@test.com", "role": "viewer"}

        with patch("backend.api.management.router.get_db", return_value=mock_db), \
             patch("backend.api.management.router.get_current_user", return_value=mock_user):

            response = await client.get(
                "/manage/documents",
                headers={"Authorization": f"Bearer {viewer_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["documents"]) == 3
        assert data["page"] == 1

    @pytest.mark.asyncio
    async def test_list_requires_auth(self, client):
        """Unauthenticated requests to /manage/documents must return 401."""
        response = await client.get("/manage/documents")

        assert response.status_code == 401


class TestDocumentDelete:

    @pytest.mark.asyncio
    async def test_delete_returns_200_for_existing_document(self, client, admin_token, mock_db):
        """Admin can delete an existing document."""
        mock_collection = AsyncMock()
        mock_collection.delete_one.return_value = MagicMock(deleted_count=1)
        mock_collection.insert_one.return_value = MagicMock(inserted_id="log")
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        mock_user = {"email": "admin@test.com", "role": "admin"}

        with patch("backend.api.management.router.get_db", return_value=mock_db), \
             patch("backend.api.management.router.get_current_user", return_value=mock_user), \
             patch("backend.api.management.router.require_role", return_value=lambda: mock_user):

            response = await client.delete(
                "/manage/documents/doc-123",
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_delete_returns_404_for_missing_document(self, client, admin_token, mock_db):
        """Deleting a non-existent document must return 404."""
        mock_collection = AsyncMock()
        mock_collection.delete_one.return_value = MagicMock(deleted_count=0)
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        mock_user = {"email": "admin@test.com", "role": "admin"}

        with patch("backend.api.management.router.get_db", return_value=mock_db), \
             patch("backend.api.management.router.get_current_user", return_value=mock_user), \
             patch("backend.api.management.router.require_role", return_value=lambda: mock_user):

            response = await client.delete(
                "/manage/documents/non-existent",
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        assert response.status_code == 404


class TestMetrics:

    @pytest.mark.asyncio
    async def test_metrics_returns_summary(self, client, viewer_token, mock_db):
        """GET /manage/metrics returns aggregated Q&A stats."""
        mock_collection = AsyncMock()
        mock_collection.aggregate.return_value.to_list = AsyncMock(return_value=[{
            "total_questions": 100,
            "avg_latency_ms": 350.5,
            "total_tokens": 15000,
            "pii_flagged_count": 5,
            "unsafe_flagged_count": 2,
        }])
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        mock_user = {"email": "viewer@test.com", "role": "viewer"}

        with patch("backend.api.management.router.get_db", return_value=mock_db), \
             patch("backend.services.monitoring_service.get_db", return_value=mock_db), \
             patch("backend.api.management.router.get_current_user", return_value=mock_user):

            response = await client.get(
                "/manage/metrics",
                headers={"Authorization": f"Bearer {viewer_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "total_questions" in data
        assert "avg_latency_ms" in data


class TestAuthentication:

    @pytest.mark.asyncio
    async def test_login_returns_token_for_valid_credentials(self, client, mock_db):
        """POST /manage/auth/token with valid creds → access_token in response."""
        from backend.core.auth import hash_password

        mock_collection = AsyncMock()
        mock_collection.find_one.return_value = {
            "email": "admin@test.com",
            "password_hash": hash_password("correct-password"),
            "role": "admin",
        }
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        with patch("backend.api.management.router.get_db", return_value=mock_db):
            response = await client.post(
                "/manage/auth/token",
                data={"username": "admin@test.com", "password": "correct-password"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        assert response.status_code == 200
        assert "access_token" in response.json()

    @pytest.mark.asyncio
    async def test_login_returns_401_for_wrong_password(self, client, mock_db):
        """Wrong password → 401."""
        from backend.core.auth import hash_password

        mock_collection = AsyncMock()
        mock_collection.find_one.return_value = {
            "email": "admin@test.com",
            "password_hash": hash_password("correct-password"),
            "role": "admin",
        }
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        with patch("backend.api.management.router.get_db", return_value=mock_db):
            response = await client.post(
                "/manage/auth/token",
                data={"username": "admin@test.com", "password": "wrong-password"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_returns_401_for_unknown_user(self, client, mock_db):
        """Unknown email → 401, not 404 (to avoid user enumeration)."""
        mock_collection = AsyncMock()
        mock_collection.find_one.return_value = None
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        with patch("backend.api.management.router.get_db", return_value=mock_db):
            response = await client.post(
                "/manage/auth/token",
                data={"username": "unknown@test.com", "password": "any"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        assert response.status_code == 401
