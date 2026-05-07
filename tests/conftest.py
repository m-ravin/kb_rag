"""
Shared pytest fixtures and mock factories for the KB RAG test suite.

All Azure SDK clients are mocked here so tests run without real Azure credentials.
This follows the Arrange-Act-Assert pattern throughout.
"""

import os
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

# ── Set minimal env vars before importing the app ─────────────────────────────
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com/")
os.environ.setdefault("AZURE_OPENAI_KEY", "test-key-openai")
os.environ.setdefault("AZURE_OPENAI_GPT_DEPLOYMENT", "gpt-4o")
os.environ.setdefault("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
os.environ.setdefault("AZURE_SEARCH_ENDPOINT", "https://test.search.windows.net")
os.environ.setdefault("AZURE_SEARCH_KEY", "test-key-search")
os.environ.setdefault("AZURE_SEARCH_INDEX_NAME", "pil-documents")
os.environ.setdefault("COSMOS_MONGO_CONNECTION", "mongodb://test:test@localhost:27017/test")
os.environ.setdefault("COSMOS_GREMLIN_ENDPOINT", "wss://test.gremlin.cosmos.azure.com:443/")
os.environ.setdefault("COSMOS_GREMLIN_KEY", "test-key-gremlin")
os.environ.setdefault("REDIS_CONNECTION", "redis://localhost:6379")
os.environ.setdefault("STORAGE_CONNECTION", "DefaultEndpointsProtocol=https;AccountName=test;AccountKey=dGVzdA==;EndpointSuffix=core.windows.net")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-testing-only")


# ── Fake data factories ────────────────────────────────────────────────────────

def make_chunk_result(
    chunk_id: str = "doc1_chunk_0",
    document_id: str = "doc1",
    filename: str = "paracetamol.pdf",
    content: str = "Take 500mg every 4 hours. Do not exceed 4g in 24 hours.",
    score: float = 0.95,
) -> dict:
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "filename": filename,
        "content": content,
        "score": score,
    }


def make_openai_chat_response(content: str = "This medication is used to relieve pain.") -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    usage = MagicMock()
    usage.total_tokens = 150
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


def make_openai_embedding_response(dims: int = 1536) -> MagicMock:
    embedding_obj = MagicMock()
    embedding_obj.embedding = [0.1] * dims
    response = MagicMock()
    response.data = [embedding_obj]
    return response


# ── Core mock fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def mock_openai_client():
    """Mock AsyncAzureOpenAI — prevents real API calls in all tests."""
    client = AsyncMock()
    client.chat.completions.create.return_value = make_openai_chat_response()
    client.embeddings.create.return_value = make_openai_embedding_response()
    return client


@pytest.fixture
def mock_search_client():
    """Mock Azure AI Search client with a default result set."""
    client = AsyncMock()

    async def fake_search(*args, **kwargs):
        results = [make_chunk_result(chunk_id=f"doc1_chunk_{i}", score=0.9 - i * 0.05) for i in range(3)]
        for r in results:
            yield r

    client.search.return_value = fake_search()
    return client


@pytest.fixture
def mock_redis():
    """Mock Redis — returns None (cache miss) by default."""
    redis = AsyncMock()
    redis.get.return_value = None
    redis.setex.return_value = True
    redis.ping.return_value = True
    return redis


@pytest.fixture
def mock_mongo_collection():
    """Mock Motor MongoDB collection with sensible defaults."""
    col = AsyncMock()
    col.find_one.return_value = None
    col.insert_one.return_value = MagicMock(inserted_id="fake-id")
    col.update_one.return_value = MagicMock(modified_count=1)
    col.delete_one.return_value = MagicMock(deleted_count=1)
    col.count_documents.return_value = 0

    cursor = AsyncMock()
    cursor.sort.return_value = cursor
    cursor.skip.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list.return_value = []
    col.find.return_value = cursor
    col.aggregate.return_value = AsyncMock()
    col.aggregate.return_value.to_list = AsyncMock(return_value=[])
    return col


@pytest.fixture
def mock_db(mock_mongo_collection):
    """Mock the full MongoDB database handle."""
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=mock_mongo_collection)
    return db


# ── FastAPI test client ────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(mock_openai_client, mock_search_client, mock_redis, mock_db):
    """
    HTTPX async test client wired to the FastAPI app with all Azure dependencies mocked.
    No real network calls are made.
    """
    with (
        patch("backend.core.clients.get_openai_client", return_value=mock_openai_client),
        patch("backend.core.clients.get_search_client", return_value=mock_search_client),
        patch("backend.core.clients.get_redis_client", return_value=mock_redis),
        patch("backend.core.clients.get_db", return_value=mock_db),
        patch("backend.pipeline.indexer.ensure_search_index", new_callable=AsyncMock),
        patch("backend.services.search_service.get_openai_client", return_value=mock_openai_client),
        patch("backend.services.search_service.get_search_client", return_value=mock_search_client),
        patch("backend.services.search_service.get_redis_client", return_value=mock_redis),
        patch("backend.services.llm_service.get_openai_client", return_value=mock_openai_client),
        patch("backend.services.monitoring_service.get_db", return_value=mock_db),
        patch("backend.api.management.router.get_db", return_value=mock_db),
    ):
        from backend.main import create_app
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


# ── Auth helper ────────────────────────────────────────────────────────────────

@pytest.fixture
def admin_token():
    """A valid JWT for an admin user — used in management endpoint tests."""
    from backend.core.auth import create_access_token
    return create_access_token({"sub": "admin@test.com", "role": "admin"})


@pytest.fixture
def editor_token():
    from backend.core.auth import create_access_token
    return create_access_token({"sub": "editor@test.com", "role": "editor"})


@pytest.fixture
def viewer_token():
    from backend.core.auth import create_access_token
    return create_access_token({"sub": "viewer@test.com", "role": "viewer"})
