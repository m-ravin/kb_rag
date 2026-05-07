"""
Integration tests for POST /tasks/* — individual AI task endpoints.

User journeys covered:
  - As a developer, I want each Task API to return a result with latency metadata
  - As a developer, I want the message-template-parser to fill variables without LLM calls
  - As a developer, I want the translation endpoint to forward the target language
"""

import pytest
from unittest.mock import AsyncMock, patch


class TestTaskAPIs:

    # ── Content Safety ────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_content_safety_returns_safe_result(self, client):
        with patch("backend.api.task_apis.router.safety_service") as mock:
            mock.check_content_safety = AsyncMock(return_value=(True, ""))

            response = await client.post("/tasks/content-safety", json={"text": "What is the dose?"})

        assert response.status_code == 200
        data = response.json()
        assert data["result"]["safe"] is True
        assert "latency_ms" in data

    @pytest.mark.asyncio
    async def test_content_safety_returns_unsafe_result(self, client):
        with patch("backend.api.task_apis.router.safety_service") as mock:
            mock.check_content_safety = AsyncMock(return_value=(False, "Violence"))

            response = await client.post("/tasks/content-safety", json={"text": "harmful text"})

        assert response.status_code == 200
        assert response.json()["result"]["safe"] is False
        assert response.json()["result"]["category"] == "Violence"

    # ── PII Detection ─────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_pii_detection_flags_email(self, client):
        with patch("backend.api.task_apis.router.safety_service") as mock:
            mock.detect_pii = AsyncMock(return_value=(True, ["email_pattern"]))

            response = await client.post(
                "/tasks/pii-detection", json={"text": "email: test@test.com"}
            )

        assert response.status_code == 200
        assert response.json()["result"]["has_pii"] is True

    # ── Question Type Detection ───────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_question_type_detection_returns_type(self, client):
        from backend.models.qa import QuestionType

        with patch("backend.api.task_apis.router.llm_service") as mock:
            mock.detect_question_type = AsyncMock(return_value=QuestionType.FACTUAL)

            response = await client.post(
                "/tasks/question-type-detection", json={"text": "What are the ingredients?"}
            )

        assert response.status_code == 200
        assert response.json()["result"]["question_type"] == "factual"

    # ── Summarizer ────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_summarizer_returns_summary(self, client):
        with patch("backend.api.task_apis.router.llm_service") as mock:
            mock.summarise_text = AsyncMock(return_value=("Short summary.", 30))

            response = await client.post(
                "/tasks/summarizer",
                json={"text": "Long text " * 100, "options": {"max_sentences": 3}},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["result"]["summary"] == "Short summary."
        assert data["tokens_used"] == 30

    # ── Translation ───────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_translation_forwards_target_language(self, client):
        with patch("backend.api.task_apis.router.llm_service") as mock:
            mock.translate_text = AsyncMock(return_value=("Dos yang disyorkan ialah 500mg.", 40))

            response = await client.post(
                "/tasks/translation",
                json={"text": "Recommended dose is 500mg.", "options": {"language": "ms"}},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["result"]["target_language"] == "ms"
        assert "Dos" in data["result"]["translated_text"]
        # Verify language was forwarded to translate_text
        mock.translate_text.assert_called_once_with("Recommended dose is 500mg.", "ms")

    # ── Wording Tuning ────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_wording_tuning_defaults_to_professional(self, client):
        with patch("backend.api.task_apis.router.llm_service") as mock:
            mock.tune_wording = AsyncMock(return_value=("Professional text.", 25))

            response = await client.post(
                "/tasks/wording-tuning", json={"text": "casual text here"}
            )

        assert response.status_code == 200
        assert response.json()["result"]["tone"] == "professional"
        mock.tune_wording.assert_called_once_with("casual text here", "professional")

    @pytest.mark.asyncio
    async def test_wording_tuning_uses_custom_tone(self, client):
        with patch("backend.api.task_apis.router.llm_service") as mock:
            mock.tune_wording = AsyncMock(return_value=("Simple text.", 20))

            response = await client.post(
                "/tasks/wording-tuning",
                json={"text": "complex text", "options": {"tone": "simple"}},
            )

        assert response.json()["result"]["tone"] == "simple"

    # ── Message Template Parser ───────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_template_parser_fills_variables(self, client):
        """Template filling is pure string replacement — no LLM call needed."""
        response = await client.post(
            "/tasks/message-template-parser",
            json={
                "text": "Dear {{name}}, your medication {{drug}} is ready.",
                "options": {"name": "Alice", "drug": "Amoxicillin"},
            },
        )

        assert response.status_code == 200
        rendered = response.json()["result"]["rendered"]
        assert rendered == "Dear Alice, your medication Amoxicillin is ready."

    @pytest.mark.asyncio
    async def test_template_parser_leaves_unfilled_variables_intact(self, client):
        """Variables not in options dict must remain as-is."""
        response = await client.post(
            "/tasks/message-template-parser",
            json={"text": "Dear {{name}}, your {{item}} is ready.", "options": {"name": "Bob"}},
        )

        rendered = response.json()["result"]["rendered"]
        assert "Bob" in rendered
        assert "{{item}}" in rendered

    # ── Compliance Check ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_compliance_check_returns_bool_and_reason(self, client):
        with patch("backend.api.task_apis.router.llm_service") as mock:
            mock.check_compliance = AsyncMock(return_value=(True, ""))

            response = await client.post(
                "/tasks/compliance-check", json={"text": "This medicine relieves pain."}
            )

        assert response.status_code == 200
        assert isinstance(response.json()["result"]["compliant"], bool)

    # ── Language Check ────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_language_check_returns_iso_code(self, client):
        with patch("backend.api.task_apis.router.llm_service") as mock:
            mock.detect_language = AsyncMock(return_value="ms")

            response = await client.post(
                "/tasks/language-check", json={"text": "Apakah dos yang disyorkan?"}
            )

        assert response.status_code == 200
        assert response.json()["result"]["language"] == "ms"

    # ── All endpoints share latency_ms ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_all_task_endpoints_include_latency_ms(self, client):
        """Every Task API response must include latency_ms as a float >= 0."""
        endpoints_and_payloads = [
            ("/tasks/pii-detection", {"text": "hello"}),
            ("/tasks/message-template-parser", {"text": "hello {{x}}", "options": {"x": "y"}}),
        ]

        with patch("backend.api.task_apis.router.safety_service") as mock_safety:
            mock_safety.detect_pii = AsyncMock(return_value=(False, []))

            for endpoint, payload in endpoints_and_payloads:
                response = await client.post(endpoint, json=payload)
                assert response.status_code == 200, f"{endpoint} returned {response.status_code}"
                assert "latency_ms" in response.json(), f"{endpoint} missing latency_ms"
                assert response.json()["latency_ms"] >= 0
