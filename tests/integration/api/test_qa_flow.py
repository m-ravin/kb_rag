"""
Integration tests for POST /qa/ask — the full RAG pipeline endpoint.

User journeys covered:
  - As a user, I want to ask a question and get a safe, accurate, source-cited answer
  - As a user, I want unsafe content blocked before it reaches the LLM
  - As a user, I want my PII flagged in the response so I know it was detected
"""

import pytest
from unittest.mock import AsyncMock, patch

from tests.conftest import make_chunk_result_obj


class TestQAFlowAsk:

    @pytest.mark.asyncio
    async def test_returns_200_with_answer_for_valid_question(self, client):
        """Happy path: valid question → 200 with answer field."""
        with patch("backend.api.qa_flow.router.safety_service") as mock_safety, \
             patch("backend.api.qa_flow.router.llm_service") as mock_llm, \
             patch("backend.api.qa_flow.router.search_service") as mock_search, \
             patch("backend.api.qa_flow.router.monitoring_service") as mock_monitor:

            mock_safety.screen_pii = AsyncMock(
                return_value=(False, [], "What is the dose of paracetamol?")
            )
            mock_safety.check_content_safety = AsyncMock(return_value=(True, ""))
            mock_llm.detect_question_type = AsyncMock(return_value=__import__(
                "backend.models.qa", fromlist=["QuestionType"]
            ).QuestionType.FAQ)
            mock_llm.extract_keywords = AsyncMock(return_value=["paracetamol", "dose"])
            mock_llm.generate_answer = AsyncMock(return_value=("Take 500mg every 4 hours.", 80))
            mock_llm.tune_wording = AsyncMock(return_value=("Take 500mg every 4 hours.", 20))
            mock_llm.check_compliance = AsyncMock(return_value=(True, ""))
            mock_llm.detect_language = AsyncMock(return_value="en")
            mock_search.hybrid_search = AsyncMock(return_value=[make_chunk_result_obj()])
            mock_search.graph_search = AsyncMock(return_value=[])
            mock_monitor.log_qa_interaction = AsyncMock()

            response = await client.post("/qa/ask", json={"question": "What is the dose of paracetamol?"})

        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert len(data["answer"]) > 0
        assert "sources" in data
        assert "session_id" in data

    @pytest.mark.asyncio
    async def test_blocks_unsafe_content_and_returns_200_with_refusal(self, client):
        """
        Unsafe content must not reach the LLM — the endpoint still returns 200
        but with a refusal message.
        """
        with patch("backend.api.qa_flow.router.safety_service") as mock_safety, \
             patch("backend.api.qa_flow.router.llm_service") as mock_llm, \
             patch("backend.api.qa_flow.router.monitoring_service") as mock_monitor:

            mock_safety.screen_pii = AsyncMock(return_value=(False, [], "harmful content here"))
            mock_safety.check_content_safety = AsyncMock(return_value=(False, "Hate"))
            mock_monitor.log_qa_interaction = AsyncMock()

            response = await client.post("/qa/ask", json={"question": "harmful content here"})

        assert response.status_code == 200
        data = response.json()
        assert data["flagged_unsafe"] is True
        # LLM generate_answer must NOT have been called
        mock_llm.generate_answer.assert_not_called() if hasattr(mock_llm, "generate_answer") else None

    @pytest.mark.asyncio
    async def test_flags_pii_in_response_without_blocking(self, client):
        """
        PII in question is flagged in the response but does NOT block processing.
        The answer is still generated.
        """
        from backend.models.qa import QuestionType

        with patch("backend.api.qa_flow.router.safety_service") as mock_safety, \
             patch("backend.api.qa_flow.router.llm_service") as mock_llm, \
             patch("backend.api.qa_flow.router.search_service") as mock_search, \
             patch("backend.api.qa_flow.router.monitoring_service") as mock_monitor:

            mock_safety.screen_pii = AsyncMock(
                return_value=(True, ["email"], "[REDACTED] - what is the dose?")
            )
            mock_safety.check_content_safety = AsyncMock(return_value=(True, ""))
            mock_llm.detect_question_type = AsyncMock(return_value=QuestionType.FACTUAL)
            mock_llm.extract_keywords = AsyncMock(return_value=["dose"])
            mock_llm.generate_answer = AsyncMock(return_value=("The dose is 500mg.", 60))
            mock_llm.tune_wording = AsyncMock(return_value=("The dose is 500mg.", 10))
            mock_llm.check_compliance = AsyncMock(return_value=(True, ""))
            mock_llm.detect_language = AsyncMock(return_value="en")
            mock_search.hybrid_search = AsyncMock(return_value=[make_chunk_result_obj()])
            mock_search.graph_search = AsyncMock(return_value=[])
            mock_monitor.log_qa_interaction = AsyncMock()

            response = await client.post(
                "/qa/ask",
                json={"question": "john@example.com - what is the dose?"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["flagged_pii"] is True
        assert len(data["answer"]) > 0

    @pytest.mark.asyncio
    async def test_returns_422_for_question_too_short(self, client):
        """Question shorter than 3 characters is rejected by Pydantic validation."""
        response = await client.post("/qa/ask", json={"question": "hi"})

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_returns_422_for_missing_question_field(self, client):
        """Missing 'question' field must return 422, not 500."""
        response = await client.post("/qa/ask", json={})

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_response_contains_token_count_and_latency(self, client):
        """Monitoring fields tokens_used and latency_ms must be present and numeric."""
        from backend.models.qa import QuestionType

        with patch("backend.api.qa_flow.router.safety_service") as mock_safety, \
             patch("backend.api.qa_flow.router.llm_service") as mock_llm, \
             patch("backend.api.qa_flow.router.search_service") as mock_search, \
             patch("backend.api.qa_flow.router.monitoring_service") as mock_monitor:

            mock_safety.screen_pii = AsyncMock(return_value=(False, [], "What is the dose?"))
            mock_safety.check_content_safety = AsyncMock(return_value=(True, ""))
            mock_llm.detect_question_type = AsyncMock(return_value=QuestionType.FAQ)
            mock_llm.extract_keywords = AsyncMock(return_value=["dose"])
            mock_llm.generate_answer = AsyncMock(return_value=("500mg", 50))
            mock_llm.tune_wording = AsyncMock(return_value=("500mg", 10))
            mock_llm.check_compliance = AsyncMock(return_value=(True, ""))
            mock_llm.detect_language = AsyncMock(return_value="en")
            mock_search.hybrid_search = AsyncMock(return_value=[])
            mock_search.graph_search = AsyncMock(return_value=[])
            mock_monitor.log_qa_interaction = AsyncMock()

            response = await client.post("/qa/ask", json={"question": "What is the dose?"})

        data = response.json()
        assert isinstance(data["tokens_used"], int)
        assert isinstance(data["latency_ms"], float)
        assert data["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_uses_provided_session_id(self, client):
        """When caller provides a session_id, it must appear in the response."""
        from backend.models.qa import QuestionType

        with patch("backend.api.qa_flow.router.safety_service") as mock_safety, \
             patch("backend.api.qa_flow.router.llm_service") as mock_llm, \
             patch("backend.api.qa_flow.router.search_service") as mock_search, \
             patch("backend.api.qa_flow.router.monitoring_service") as mock_monitor:

            mock_safety.screen_pii = AsyncMock(return_value=(False, [], "What is the dose?"))
            mock_safety.check_content_safety = AsyncMock(return_value=(True, ""))
            mock_llm.detect_question_type = AsyncMock(return_value=QuestionType.FAQ)
            mock_llm.extract_keywords = AsyncMock(return_value=[])
            mock_llm.generate_answer = AsyncMock(return_value=("answer", 10))
            mock_llm.tune_wording = AsyncMock(return_value=("answer", 5))
            mock_llm.check_compliance = AsyncMock(return_value=(True, ""))
            mock_llm.detect_language = AsyncMock(return_value="en")
            mock_search.hybrid_search = AsyncMock(return_value=[])
            mock_search.graph_search = AsyncMock(return_value=[])
            mock_monitor.log_qa_interaction = AsyncMock()

            response = await client.post(
                "/qa/ask",
                json={"question": "What is the dose?", "session_id": "my-session-abc"},
            )

        assert response.json()["session_id"] == "my-session-abc"
