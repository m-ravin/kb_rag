"""
Unit tests for search_service — vector, keyword, graph, hybrid search.

User journeys covered:
  - As a developer, I want all four search strategies to return ranked ChunkResult objects
  - As a system, I want search results cached in Redis to avoid redundant embedding calls
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import make_chunk_result, make_chunk_result_obj, make_openai_embedding_response


def _make_async_search_results(chunks: list[dict]):
    """Creates an async generator yielding fake Azure Search results."""
    async def _gen():
        for c in chunks:
            yield {**c, "@search.score": c["score"]}
    return _gen()


# ── Vector search ──────────────────────────────────────────────────────────────

class TestVectorSearch:

    @pytest.mark.asyncio
    async def test_returns_list_of_chunk_results(self):
        """Happy path: vector search returns correctly typed results."""
        fake_chunks = [make_chunk_result(score=0.9 - i * 0.1) for i in range(3)]
        mock_openai = AsyncMock()
        mock_openai.embeddings.create.return_value = make_openai_embedding_response()
        mock_search = AsyncMock()
        mock_search.search.return_value = _make_async_search_results(fake_chunks)
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None  # cache miss

        with patch("backend.services.search_service.get_openai_client", return_value=mock_openai), \
             patch("backend.services.search_service.get_search_client", return_value=mock_search), \
             patch("backend.services.search_service.get_redis_client", return_value=mock_redis):
            from backend.services.search_service import vector_search
            from backend.models.qa import ChunkResult

            results = await vector_search("paracetamol dosage")

        assert isinstance(results, list)
        assert all(isinstance(r, ChunkResult) for r in results)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_returns_cached_results_without_calling_openai(self):
        """
        When Redis has a cached result, OpenAI embeddings must NOT be called.
        This is the core Redis cache optimisation — must hold.
        """
        # The cache stores ChunkResult.model_dump() output (key "chunk_id"), not raw
        # Azure Search results (key "id") — make_chunk_result_obj() matches that shape.
        cached = [make_chunk_result_obj().model_dump()]
        mock_openai = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps(cached)

        with patch("backend.services.search_service.get_openai_client", return_value=mock_openai), \
             patch("backend.services.search_service.get_redis_client", return_value=mock_redis):
            from backend.services.search_service import vector_search

            await vector_search("some query")

        mock_openai.embeddings.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_writes_results_to_cache_after_search(self):
        """After a cache miss, results must be stored in Redis."""
        fake_chunks = [make_chunk_result()]
        mock_openai = AsyncMock()
        mock_openai.embeddings.create.return_value = make_openai_embedding_response()
        mock_search = AsyncMock()
        mock_search.search.return_value = _make_async_search_results(fake_chunks)
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch("backend.services.search_service.get_openai_client", return_value=mock_openai), \
             patch("backend.services.search_service.get_search_client", return_value=mock_search), \
             patch("backend.services.search_service.get_redis_client", return_value=mock_redis):
            from backend.services.search_service import vector_search

            await vector_search("some query")

        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args
        # First arg is key, second is TTL (300s), third is JSON payload
        assert args[0][1] == 300

    @pytest.mark.asyncio
    async def test_respects_top_k_parameter(self):
        """top_k must be forwarded to the Azure Search call."""
        mock_openai = AsyncMock()
        mock_openai.embeddings.create.return_value = make_openai_embedding_response()
        mock_search = AsyncMock()
        mock_search.search.return_value = _make_async_search_results([])
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch("backend.services.search_service.get_openai_client", return_value=mock_openai), \
             patch("backend.services.search_service.get_search_client", return_value=mock_search), \
             patch("backend.services.search_service.get_redis_client", return_value=mock_redis):
            from backend.services.search_service import vector_search

            await vector_search("query", top_k=10)

        call_kwargs = mock_search.search.call_args.kwargs
        assert call_kwargs.get("top") == 10


# ── Keyword search ─────────────────────────────────────────────────────────────

class TestKeywordSearch:

    @pytest.mark.asyncio
    async def test_does_not_call_openai_embeddings(self):
        """Keyword search is BM25 — it must never call the embedding endpoint."""
        fake_chunks = [make_chunk_result()]
        mock_openai = AsyncMock()
        mock_search = AsyncMock()
        mock_search.search.return_value = _make_async_search_results(fake_chunks)
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch("backend.services.search_service.get_openai_client", return_value=mock_openai), \
             patch("backend.services.search_service.get_search_client", return_value=mock_search), \
             patch("backend.services.search_service.get_redis_client", return_value=mock_redis):
            from backend.services.search_service import keyword_search

            await keyword_search("paracetamol")

        mock_openai.embeddings.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_passes_query_as_search_text(self):
        """The query string must be forwarded as search_text to Azure Search."""
        mock_search = AsyncMock()
        mock_search.search.return_value = _make_async_search_results([])
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch("backend.services.search_service.get_search_client", return_value=mock_search), \
             patch("backend.services.search_service.get_redis_client", return_value=mock_redis):
            from backend.services.search_service import keyword_search

            await keyword_search("ibuprofen")

        call_kwargs = mock_search.search.call_args.kwargs
        assert call_kwargs.get("search_text") == "ibuprofen"


# ── Hybrid search ──────────────────────────────────────────────────────────────

class TestHybridSearch:

    @pytest.mark.asyncio
    async def test_sends_both_vector_query_and_search_text(self):
        """Hybrid search must provide both vector_queries and search_text."""
        mock_openai = AsyncMock()
        mock_openai.embeddings.create.return_value = make_openai_embedding_response()
        mock_search = AsyncMock()
        mock_search.search.return_value = _make_async_search_results([])
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch("backend.services.search_service.get_openai_client", return_value=mock_openai), \
             patch("backend.services.search_service.get_search_client", return_value=mock_search), \
             patch("backend.services.search_service.get_redis_client", return_value=mock_redis):
            from backend.services.search_service import hybrid_search

            await hybrid_search("what is the dose?")

        call_kwargs = mock_search.search.call_args.kwargs
        assert call_kwargs.get("search_text") is not None
        assert call_kwargs.get("vector_queries") is not None

    @pytest.mark.asyncio
    async def test_returns_chunk_result_objects(self):
        fake_chunks = [make_chunk_result(score=0.88)]
        mock_openai = AsyncMock()
        mock_openai.embeddings.create.return_value = make_openai_embedding_response()
        mock_search = AsyncMock()
        mock_search.search.return_value = _make_async_search_results(fake_chunks)
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch("backend.services.search_service.get_openai_client", return_value=mock_openai), \
             patch("backend.services.search_service.get_search_client", return_value=mock_search), \
             patch("backend.services.search_service.get_redis_client", return_value=mock_redis):
            from backend.services.search_service import hybrid_search
            from backend.models.qa import ChunkResult

            results = await hybrid_search("dose question")

        assert all(isinstance(r, ChunkResult) for r in results)


# ── Monitoring service ────────────────────────────────────────────────────────

class TestMonitoringService:

    @pytest.mark.asyncio
    async def test_log_qa_interaction_inserts_to_mongo(self):
        """Every Q&A interaction must be persisted to the qa_logs collection."""
        mock_collection = AsyncMock()
        mock_collection.insert_one.return_value = MagicMock(inserted_id="log-1")
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        with patch("backend.services.monitoring_service.get_db", return_value=mock_db):
            from backend.services.monitoring_service import log_qa_interaction

            await log_qa_interaction(
                session_id="sess-1",
                question="What is the dose?",
                answer="500mg",
                question_type="faq",
                sources=[],
                tokens_used=100,
                latency_ms=250.0,
                flagged_pii=False,
                flagged_unsafe=False,
                language="en",
            )

        mock_collection.insert_one.assert_called_once()
        doc = mock_collection.insert_one.call_args[0][0]
        assert doc["session_id"] == "sess-1"
        assert doc["tokens_used"] == 100
        assert doc["flagged_pii"] is False

    @pytest.mark.asyncio
    async def test_log_qa_interaction_never_raises_on_mongo_error(self):
        """Logging failure must be swallowed — it must never break the API response."""
        mock_collection = AsyncMock()
        mock_collection.insert_one.side_effect = Exception("Cosmos DB unavailable")
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        with patch("backend.services.monitoring_service.get_db", return_value=mock_db):
            from backend.services.monitoring_service import log_qa_interaction

            # Should not raise
            await log_qa_interaction(
                session_id="s", question="q", answer="a", question_type="faq",
                sources=[], tokens_used=0, latency_ms=0.0,
                flagged_pii=False, flagged_unsafe=False, language="en",
            )
