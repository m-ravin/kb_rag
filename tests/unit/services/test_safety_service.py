"""
Unit tests for safety_service — PII detection and content safety.

User journeys covered:
  - As a user, I want my PII detected before my question is processed
  - As a user, I want unsafe content blocked before it reaches the LLM
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


# ── PII Detection ─────────────────────────────────────────────────────────────

class TestDetectPII:
    """Tests for backend.services.safety_service.detect_pii"""

    @pytest.mark.asyncio
    async def test_detects_email_address(self):
        """Arrange: text with email → Act: detect_pii → Assert: flagged."""
        from backend.services.safety_service import detect_pii

        has_pii, patterns = await detect_pii("Please email me at john.doe@example.com")

        assert has_pii is True
        assert len(patterns) > 0

    @pytest.mark.asyncio
    async def test_detects_phone_number(self):
        """Phone numbers (8+ digits) should be flagged as PII."""
        from backend.services.safety_service import detect_pii

        has_pii, patterns = await detect_pii("Call me at +60 12-345 6789")

        assert has_pii is True

    @pytest.mark.asyncio
    async def test_clean_text_returns_no_pii(self):
        """Arrange: medical question without PII → Assert: not flagged."""
        from backend.services.safety_service import detect_pii

        has_pii, patterns = await detect_pii("What is the recommended dose of paracetamol?")

        assert has_pii is False
        assert patterns == []

    @pytest.mark.asyncio
    async def test_empty_string_returns_no_pii(self):
        """Edge case: empty input should never crash and return no PII."""
        from backend.services.safety_service import detect_pii

        has_pii, patterns = await detect_pii("")

        assert has_pii is False

    @pytest.mark.asyncio
    async def test_returns_tuple_of_bool_and_list(self):
        """Return type contract: always (bool, list)."""
        from backend.services.safety_service import detect_pii

        result = await detect_pii("some text")

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], list)

    @pytest.mark.asyncio
    async def test_pii_detection_falls_back_to_regex_when_azure_unavailable(self):
        """When content_safety_endpoint is blank, regex fallback must still catch PII."""
        with patch("backend.services.safety_service.get_settings") as mock_settings:
            mock_settings.return_value.content_safety_endpoint = ""
            mock_settings.return_value.content_safety_key = ""
            from backend.services.safety_service import detect_pii

            has_pii, _ = await detect_pii("Contact: ravin@example.com")

        assert has_pii is True


# ── Content Safety ────────────────────────────────────────────────────────────

class TestCheckContentSafety:
    """Tests for backend.services.safety_service.check_content_safety"""

    @pytest.mark.asyncio
    async def test_returns_safe_when_endpoint_not_configured(self):
        """
        When CONTENT_SAFETY_ENDPOINT is blank, all text passes through as safe.
        This is the expected fallback behaviour for dev environments.
        """
        with patch("backend.services.safety_service.get_settings") as mock_settings:
            mock_settings.return_value.content_safety_endpoint = ""
            mock_settings.return_value.content_safety_key = ""
            from backend.services.safety_service import check_content_safety

            is_safe, category = await check_content_safety("What are the side effects?")

        assert is_safe is True
        assert category == ""

    @pytest.mark.asyncio
    async def test_returns_tuple_of_bool_and_str(self):
        """Return type contract: always (bool, str)."""
        with patch("backend.services.safety_service.get_settings") as mock_settings:
            mock_settings.return_value.content_safety_endpoint = ""
            mock_settings.return_value.content_safety_key = ""
            from backend.services.safety_service import check_content_safety

            result = await check_content_safety("normal question")

        assert isinstance(result, tuple)
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)

    @pytest.mark.asyncio
    async def test_flags_unsafe_content_when_azure_returns_high_severity(self):
        """When Azure Content Safety returns severity >= 4, content should be blocked."""
        import httpx

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
