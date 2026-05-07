"""
Unit tests for llm_service — all GPT-4o prompt functions.

User journeys covered:
  - As a user, I want my question type detected correctly
  - As a user, I want keywords extracted to improve search precision
  - As a user, I want a clear answer generated from relevant document chunks
  - As an editor, I want answers summarised and wording-tuned before returning
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from tests.conftest import make_chunk_result, make_openai_chat_response


def _make_llm_mock(content: str, tokens: int = 100) -> MagicMock:
    """Helper: builds a minimal OpenAI response mock."""
    choice = MagicMock()
    choice.message.content = content
    usage = MagicMock()
    usage.total_tokens = tokens
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


# ── Question type detection ────────────────────────────────────────────────────

class TestDetectQuestionType:

    @pytest.mark.asyncio
    async def test_classifies_faq_question(self):
        """'How often can I take paracetamol?' → faq"""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _make_llm_mock("faq")

        with patch("backend.services.llm_service.get_openai_client", return_value=mock_client):
            from backend.services.llm_service import detect_question_type
            from backend.models.qa import QuestionType

            result = await detect_question_type("How often can I take paracetamol?")

        assert result == QuestionType.FAQ

    @pytest.mark.asyncio
    async def test_classifies_procedural_question(self):
        """Step-by-step questions → procedural"""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _make_llm_mock("procedural")

        with patch("backend.services.llm_service.get_openai_client", return_value=mock_client):
            from backend.services.llm_service import detect_question_type
            from backend.models.qa import QuestionType

            result = await detect_question_type("How do I administer this injection?")

        assert result == QuestionType.PROCEDURAL

    @pytest.mark.asyncio
    async def test_returns_unknown_for_unrecognised_llm_output(self):
        """If LLM returns garbage, fall back to UNKNOWN rather than crash."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _make_llm_mock("definitely-not-a-valid-type")

        with patch("backend.services.llm_service.get_openai_client", return_value=mock_client):
            from backend.services.llm_service import detect_question_type
            from backend.models.qa import QuestionType

            result = await detect_question_type("some question")

        assert result == QuestionType.UNKNOWN

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_llm_response(self):
        """LLM sometimes returns ' faq\n' — must still match."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _make_llm_mock("  factual  \n")

        with patch("backend.services.llm_service.get_openai_client", return_value=mock_client):
            from backend.services.llm_service import detect_question_type
            from backend.models.qa import QuestionType

            result = await detect_question_type("What are the ingredients?")

        assert result == QuestionType.FACTUAL


# ── Keyword extraction ─────────────────────────────────────────────────────────

class TestExtractKeywords:

    @pytest.mark.asyncio
    async def test_returns_list_of_strings(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _make_llm_mock("paracetamol, dosage, adults")

        with patch("backend.services.llm_service.get_openai_client", return_value=mock_client):
            from backend.services.llm_service import extract_keywords

            result = await extract_keywords("What is the adult dose of paracetamol?")

        assert isinstance(result, list)
        assert len(result) == 3
        assert "paracetamol" in result

    @pytest.mark.asyncio
    async def test_strips_empty_keywords(self):
        """Commas at start/end or double commas must not produce empty strings."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _make_llm_mock(",paracetamol,,dosage,")

        with patch("backend.services.llm_service.get_openai_client", return_value=mock_client):
            from backend.services.llm_service import extract_keywords

            result = await extract_keywords("anything")

        assert all(kw.strip() for kw in result)
        assert "" not in result


# ── Answer generation ──────────────────────────────────────────────────────────

class TestGenerateAnswer:

    @pytest.mark.asyncio
    async def test_returns_answer_and_token_count(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _make_llm_mock(
            "Adults should take 500mg every 4–6 hours.", tokens=80
        )

        chunks = [make_chunk_result()]

        with patch("backend.services.llm_service.get_openai_client", return_value=mock_client):
            from backend.services.llm_service import generate_answer

            answer, tokens = await generate_answer("What is the adult dose?", chunks)

        assert "500mg" in answer
        assert tokens == 80

    @pytest.mark.asyncio
    async def test_includes_all_chunk_content_in_prompt(self):
        """Every chunk's text must appear in the system prompt sent to GPT."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _make_llm_mock("answer")

        chunks = [
            make_chunk_result(content="Chunk A content"),
            make_chunk_result(content="Chunk B content"),
        ]

        with patch("backend.services.llm_service.get_openai_client", return_value=mock_client):
            from backend.services.llm_service import generate_answer

            await generate_answer("question", chunks)

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        full_prompt = " ".join(m["content"] for m in messages)
        assert "Chunk A content" in full_prompt
        assert "Chunk B content" in full_prompt

    @pytest.mark.asyncio
    async def test_handles_empty_chunks_list(self):
        """No chunks available → answer still returns without crash."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _make_llm_mock(
            "I don't have enough information."
        )

        with patch("backend.services.llm_service.get_openai_client", return_value=mock_client):
            from backend.services.llm_service import generate_answer

            answer, _ = await generate_answer("question", [])

        assert isinstance(answer, str)
        assert len(answer) > 0


# ── Compliance check ───────────────────────────────────────────────────────────

class TestCheckCompliance:

    @pytest.mark.asyncio
    async def test_returns_compliant_true_for_safe_answer(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _make_llm_mock(
            '{"compliant": true, "reason": ""}'
        )

        with patch("backend.services.llm_service.get_openai_client", return_value=mock_client):
            from backend.services.llm_service import check_compliance

            is_compliant, reason = await check_compliance("Paracetamol helps with pain.")

        assert is_compliant is True
        assert reason == ""

    @pytest.mark.asyncio
    async def test_returns_compliant_false_for_dangerous_claim(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _make_llm_mock(
            '{"compliant": false, "reason": "Makes a definitive diagnostic claim."}'
        )

        with patch("backend.services.llm_service.get_openai_client", return_value=mock_client):
            from backend.services.llm_service import check_compliance

            is_compliant, reason = await check_compliance("You definitely have diabetes.")

        assert is_compliant is False
        assert "diagnostic" in reason.lower()

    @pytest.mark.asyncio
    async def test_returns_true_when_llm_returns_invalid_json(self):
        """Graceful fallback: bad JSON from LLM → assume compliant (safe default)."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _make_llm_mock("not json at all")

        with patch("backend.services.llm_service.get_openai_client", return_value=mock_client):
            from backend.services.llm_service import check_compliance

            is_compliant, reason = await check_compliance("any text")

        assert is_compliant is True


# ── Language detection ─────────────────────────────────────────────────────────

class TestDetectLanguage:

    @pytest.mark.asyncio
    async def test_returns_iso_code(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _make_llm_mock("ms")

        with patch("backend.services.llm_service.get_openai_client", return_value=mock_client):
            from backend.services.llm_service import detect_language

            result = await detect_language("Apakah dos yang disyorkan?")

        assert result == "ms"
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_truncates_long_response_to_two_chars(self):
        """Even if LLM returns 'english', we must only return the first 2 chars."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _make_llm_mock("english")

        with patch("backend.services.llm_service.get_openai_client", return_value=mock_client):
            from backend.services.llm_service import detect_language

            result = await detect_language("some text")

        assert len(result) == 2
