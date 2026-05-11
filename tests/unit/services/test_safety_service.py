"""
Unit tests for safety_service — PII detection and content safety.

User journeys covered:
  - As a user, I want my PII detected before my question is processed
  - As a user, I want unsafe content blocked before it reaches the LLM
  - As a system operator, I want Q&A to block (503) when Presidio is unreachable
    so raw PII never reaches the LLM (fail-closed policy — see ADR-0011)
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_http_with_response(json_body: dict):
    """Returns an httpx.AsyncClient mock that returns the given JSON body."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = json_body

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=MagicMock(
        post=AsyncMock(return_value=mock_resp)
    ))
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _mock_http_with_error(exc: Exception):
    """Returns an httpx.AsyncClient mock that raises the given exception on post."""
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(side_effect=exc)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# ── screen_pii (single-call detect + mask) ───────────────────────────────────

class TestScreenPII:
    """Tests for safety_service.screen_pii — the atomic detect+mask call used by /qa/ask."""

    @pytest.mark.asyncio
    async def test_returns_has_pii_true_when_presidio_finds_entities(self):
        """Presidio /redact with entities → (True, types, redacted_text)."""
        with patch("backend.services.safety_service.get_settings") as mock_s, \
             patch("httpx.AsyncClient", return_value=_mock_http_with_response({
                 "has_pii": True,
                 "entities_found": ["EMAIL_ADDRESS"],
                 "redacted_text": "Contact [REDACTED] for details",
                 "original_text": "Contact john@example.com for details",
             })):
            mock_s.return_value.presidio_endpoint = "http://presidio-service:8080"
            from backend.services.safety_service import screen_pii
            has_pii, entity_types, masked = await screen_pii("Contact john@example.com for details")

        assert has_pii is True
        assert "EMAIL_ADDRESS" in entity_types
        assert masked == "Contact [REDACTED] for details"

    @pytest.mark.asyncio
    async def test_returns_has_pii_false_for_clean_text(self):
        """Presidio /redact with no entities → (False, [], original_text)."""
        clean = "What is the recommended dose of paracetamol?"
        with patch("backend.services.safety_service.get_settings") as mock_s, \
             patch("httpx.AsyncClient", return_value=_mock_http_with_response({
                 "has_pii": False,
                 "entities_found": [],
                 "redacted_text": clean,
                 "original_text": clean,
             })):
            mock_s.return_value.presidio_endpoint = "http://presidio-service:8080"
            from backend.services.safety_service import screen_pii
            has_pii, entity_types, masked = await screen_pii(clean)

        assert has_pii is False
        assert entity_types == []
        assert masked == clean

    @pytest.mark.asyncio
    async def test_raises_503_when_presidio_unreachable(self):
        """FAIL-CLOSED: connectivity error → HTTP 503 blocks the pipeline."""
        import httpx
        from fastapi import HTTPException

        with patch("backend.services.safety_service.get_settings") as mock_s, \
             patch("httpx.AsyncClient", return_value=_mock_http_with_error(
                 httpx.ConnectError("connection refused")
             )):
            mock_s.return_value.presidio_endpoint = "http://presidio-service:8080"
            from backend.services.safety_service import screen_pii
            with pytest.raises(HTTPException) as exc_info:
                await screen_pii("john@example.com query")

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_raises_503_on_presidio_server_error(self):
        """FAIL-CLOSED: non-2xx response from Presidio → HTTP 503."""
        import httpx
        from fastapi import HTTPException

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=MagicMock(
            post=AsyncMock(return_value=mock_resp)
        ))
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.services.safety_service.get_settings") as mock_s, \
             patch("httpx.AsyncClient", return_value=mock_client):
            mock_s.return_value.presidio_endpoint = "http://presidio-service:8080"
            from backend.services.safety_service import screen_pii
            with pytest.raises(HTTPException) as exc_info:
                await screen_pii("test question")

        assert exc_info.value.status_code == 503


# ── detect_pii (standalone, used by /tasks/pii-detection) ────────────────────

class TestDetectPII:
    """Tests for backend.services.safety_service.detect_pii"""

    @pytest.mark.asyncio
    async def test_returns_true_and_entity_types_when_presidio_finds_pii(self):
        """Presidio /analyze returns results → (True, entity_types)."""
        with patch("backend.services.safety_service.get_settings") as mock_s, \
             patch("httpx.AsyncClient", return_value=_mock_http_with_response([
                 {"entity_type": "EMAIL_ADDRESS", "score": 0.95, "start": 0, "end": 20},
             ])):
            mock_s.return_value.presidio_endpoint = "http://presidio-service:8080"
            from backend.services.safety_service import detect_pii
            has_pii, patterns = await detect_pii("john@example.com query")

        assert has_pii is True
        assert "EMAIL_ADDRESS" in patterns

    @pytest.mark.asyncio
    async def test_returns_false_and_empty_list_for_clean_text(self):
        """Presidio /analyze returns empty list → (False, [])."""
        with patch("backend.services.safety_service.get_settings") as mock_s, \
             patch("httpx.AsyncClient", return_value=_mock_http_with_response([])):
            mock_s.return_value.presidio_endpoint = "http://presidio-service:8080"
            from backend.services.safety_service import detect_pii
            has_pii, patterns = await detect_pii("What is the dose of paracetamol?")

        assert has_pii is False
        assert patterns == []

    @pytest.mark.asyncio
    async def test_fail_closed_returns_true_unknown_when_presidio_unreachable(self):
        """FAIL-CLOSED: Presidio outage → (True, ['UNKNOWN']) not (False, [])."""
        import httpx

        with patch("backend.services.safety_service.get_settings") as mock_s, \
             patch("httpx.AsyncClient", return_value=_mock_http_with_error(
                 httpx.ConnectError("connection refused")
             )):
            mock_s.return_value.presidio_endpoint = "http://presidio-service:8080"
            from backend.services.safety_service import detect_pii
            has_pii, patterns = await detect_pii("test query")

        assert has_pii is True
        assert patterns == ["UNKNOWN"]

    @pytest.mark.asyncio
    async def test_returns_tuple_of_bool_and_list(self):
        """Return type contract: always (bool, list)."""
        with patch("backend.services.safety_service.get_settings") as mock_s, \
             patch("httpx.AsyncClient", return_value=_mock_http_with_response([])):
            mock_s.return_value.presidio_endpoint = "http://presidio-service:8080"
            from backend.services.safety_service import detect_pii
            result = await detect_pii("some text")

        assert isinstance(result, tuple) and len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], list)


# ── mask_pii (standalone) ─────────────────────────────────────────────────────

class TestMaskPII:
    """Tests for backend.services.safety_service.mask_pii"""

    @pytest.mark.asyncio
    async def test_returns_redacted_text_from_presidio(self):
        """Presidio /redact success → returns masked text."""
        with patch("backend.services.safety_service.get_settings") as mock_s, \
             patch("httpx.AsyncClient", return_value=_mock_http_with_response(
                 {"redacted_text": "Contact [REDACTED] for details"}
             )):
            mock_s.return_value.presidio_endpoint = "http://presidio-service:8080"
            from backend.services.safety_service import mask_pii
            result = await mask_pii("Contact john@example.com for details")

        assert result == "Contact [REDACTED] for details"

    @pytest.mark.asyncio
    async def test_raises_503_when_presidio_unreachable(self):
        """FAIL-CLOSED: Presidio outage on /redact → HTTP 503, not silent pass-through."""
        import httpx
        from fastapi import HTTPException

        with patch("backend.services.safety_service.get_settings") as mock_s, \
             patch("httpx.AsyncClient", return_value=_mock_http_with_error(
                 httpx.ConnectError("connection refused")
             )):
            mock_s.return_value.presidio_endpoint = "http://presidio-service:8080"
            from backend.services.safety_service import mask_pii
            with pytest.raises(HTTPException) as exc_info:
                await mask_pii("john@example.com query")

        assert exc_info.value.status_code == 503


# ── Content Safety ────────────────────────────────────────────────────────────

class TestCheckContentSafety:
    """Tests for backend.services.safety_service.check_content_safety"""

    @pytest.mark.asyncio
    async def test_returns_safe_when_endpoint_not_configured(self):
        """When CONTENT_SAFETY_ENDPOINT is blank, all text passes through as safe."""
        with patch("backend.services.safety_service.get_settings") as mock_settings:
            mock_settings.return_value.content_safety_endpoint = ""
            mock_settings.return_value.content_safety_key = ""
            from backend.services.safety_service import check_content_safety
            is_safe, category = await check_content_safety("What are the side effects?")

        assert is_safe is True
        assert category == ""

    @pytest.mark.asyncio
    async def test_flags_unsafe_content_when_azure_returns_high_severity(self):
        """When Azure Content Safety returns severity >= 4, content should be blocked."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "categoriesAnalysis": [{"category": "Hate", "severity": 6}]
        }

        with patch("backend.services.safety_service.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_http:
            mock_settings.return_value.content_safety_endpoint = "https://cs.azure.com"
            mock_settings.return_value.content_safety_key = "key"
            mock_http.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(return_value=mock_response)
            ))
            mock_http.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.services.safety_service import check_content_safety
            is_safe, category = await check_content_safety("harmful content")

        assert is_safe is False
        assert category == "Hate"

    @pytest.mark.asyncio
    async def test_passes_safe_content_when_severity_below_threshold(self):
        """Severity < 4 should be considered safe."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "categoriesAnalysis": [{"category": "Violence", "severity": 2}]
        }

        with patch("backend.services.safety_service.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_http:
            mock_settings.return_value.content_safety_endpoint = "https://cs.azure.com"
            mock_settings.return_value.content_safety_key = "key"
            mock_http.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(return_value=mock_response)
            ))
            mock_http.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.services.safety_service import check_content_safety
            is_safe, category = await check_content_safety("mild content")

        assert is_safe is True
