"""
Search Service — implements all four retrieval strategies.

Think of it as a smart librarian who can find books in four ways:
1. Vector: finds pages that MEAN the same thing as your question
2. Keyword: finds pages that contain the EXACT WORDS you typed
3. Graph: finds pages that are NEAR pages you already found
4. Hybrid: combines all three for the best results
"""

import asyncio
import hashlib
import json
import logging
import re

from azure.search.documents.models import VectorizedQuery

from backend.core.clients import get_openai_client, get_redis_client, get_search_client
from backend.core.config import get_settings
from backend.models.qa import ChunkResult

_CHUNK_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,200}$')

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300  # 5-minute cache for search results


async def _get_embedding(text: str) -> list[float]:
    """Converts text into a list of numbers (vector) using Azure OpenAI."""
    client = get_openai_client()
    s = get_settings()
    response = await client.embeddings.create(
        input=text,
        model=s.azure_openai_embedding_deployment,
    )
    return response.data[0].embedding


def _cache_key(strategy: str, query: str, top_k: int) -> str:
    digest = hashlib.sha256(f"{strategy}:{query}:{top_k}".encode()).hexdigest()
    return f"search:{digest}"


async def _try_cache(key: str) -> list[ChunkResult] | None:
    redis = get_redis_client()
    cached = await redis.get(key)
    if cached:
        return [ChunkResult(**c) for c in json.loads(cached)]
    return None


async def _write_cache(key: str, results: list[ChunkResult]) -> None:
    redis = get_redis_client()
    await redis.setex(key, CACHE_TTL_SECONDS, json.dumps([r.model_dump() for r in results]))


async def vector_search(query: str, top_k: int = 5) -> list[ChunkResult]:
    """
    Finds document chunks whose MEANING is closest to the query.
    Uses cosine similarity between embedding vectors.
    """
    cache_key = _cache_key("vector", query, top_k)
    if cached := await _try_cache(cache_key):
        return cached

    vector = await _get_embedding(query)
    search_client = get_search_client()

    vector_query = VectorizedQuery(
        vector=vector,
        k_nearest_neighbors=top_k,
        fields="content_vector",
    )

    results = []
    async for r in await search_client.search(
        search_text=None,
        vector_queries=[vector_query],
        select=["id", "document_id", "filename", "content"],
        top=top_k,
    ):
        results.append(
            ChunkResult(
                chunk_id=r["id"],
                document_id=r["document_id"],
                filename=r["filename"],
                content=r["content"],
                score=r["@search.score"],
            )
        )

    await _write_cache(cache_key, results)
    return results


async def keyword_search(query: str, top_k: int = 5) -> list[ChunkResult]:
    """
    Finds document chunks containing the exact words in the query (BM25).
    Best when the user knows the specific term they're looking for.
    """
    cache_key = _cache_key("keyword", query, top_k)
    if cached := await _try_cache(cache_key):
        return cached

    search_client = get_search_client()
    results = []
    async for r in await search_client.search(
        search_text=query,
        select=["id", "document_id", "filename", "content"],
        top=top_k,
    ):
        results.append(
            ChunkResult(
                chunk_id=r["id"],
                document_id=r["document_id"],
                filename=r["filename"],
                content=r["content"],
                score=r["@search.score"],
            )
        )

    await _write_cache(cache_key, results)
    return results


async def hybrid_search(query: str, top_k: int = 5) -> list[ChunkResult]:
    """
    Combines vector + keyword search in a single Azure AI Search request.
    Azure fuses the two result sets using its built-in hybrid ranking mode
    (similar to RRF). Full semantic RRF requires a semantic configuration —
    add SemanticConfiguration + query_type=SEMANTIC to unlock that tier.
    """
    cache_key = _cache_key("hybrid", query, top_k)
    if cached := await _try_cache(cache_key):
        return cached

    vector = await _get_embedding(query)
    search_client = get_search_client()

    vector_query = VectorizedQuery(
        vector=vector,
        k_nearest_neighbors=top_k,
        fields="content_vector",
    )

    results = []
    async for r in await search_client.search(
        search_text=query,
        vector_queries=[vector_query],
        select=["id", "document_id", "filename", "content"],
        top=top_k,
    ):
        results.append(
            ChunkResult(
                chunk_id=r["id"],
                document_id=r["document_id"],
                filename=r["filename"],
                content=r["content"],
                score=r["@search.score"],
            )
        )

    await _write_cache(cache_key, results)
    return results


async def graph_search(seed_chunk_ids: list[str], top_k: int = 5) -> list[ChunkResult]:
    """
    Expands a set of seed chunks by following the 'nextChunk' graph edges
    in Cosmos Gremlin — returns neighbouring context chunks.

    Gremlin Python is a synchronous blocking client, so the traversal runs
    inside asyncio.to_thread to avoid blocking the event loop.
    """
    s = get_settings()

    # Run the blocking Gremlin traversal in a thread pool
    neighbour_ids: set[str] = await asyncio.to_thread(
        _gremlin_neighbors_sync, seed_chunk_ids[:3], top_k, s
    )

    if not neighbour_ids:
        return []

    # Fetch actual content for neighbour chunk IDs from Azure AI Search.
    # Validate IDs before building the OData filter to prevent injection.
    safe_ids = [cid for cid in list(neighbour_ids)[:top_k] if _CHUNK_ID_RE.match(cid)]
    if not safe_ids:
        return []

    search_client = get_search_client()
    filter_expr = " or ".join(f"id eq '{cid}'" for cid in safe_ids)
    results = []
    async for r in await search_client.search(
        search_text="*",
        filter=filter_expr,
        select=["id", "document_id", "filename", "content"],
    ):
        results.append(
            ChunkResult(
                chunk_id=r["id"],
                document_id=r["document_id"],
                filename=r["filename"],
                content=r["content"],
                score=0.5,  # Graph neighbours get a fixed relevance score
            )
        )

    return results


def _gremlin_neighbors_sync(
    seed_ids: list[str], top_k: int, s
) -> set[str]:
    """
    Synchronous Gremlin traversal — called via asyncio.to_thread.
    Uses Gremlin parameter bindings to prevent query injection.
    """
    from gremlin_python.driver import client as gremlin_client_lib
    from gremlin_python.driver import serializer

    gremlin = gremlin_client_lib.Client(
        s.cosmos_gremlin_endpoint,
        "g",
        username=f"/dbs/{s.cosmos_gremlin_database}/colls/{s.cosmos_gremlin_graph}",
        password=s.cosmos_gremlin_key,
        message_serializer=serializer.GraphSONSerializersV2d0(),
    )
    try:
        neighbour_ids: set[str] = set()
        for chunk_id in seed_ids:
            result = gremlin.submit(
                "g.V(seed_id).both('nextChunk').limit(top_k).values('id')",
                {"seed_id": chunk_id, "top_k": top_k},
            ).all().result()
            neighbour_ids.update(result)
        return neighbour_ids
    finally:
        gremlin.close()
