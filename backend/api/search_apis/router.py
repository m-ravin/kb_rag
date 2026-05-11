"""
Search/Retrieval APIs — exposes all four search strategies directly.

Useful for evaluating search quality or building custom retrieval workflows.
"""

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.core.auth import get_current_user
from backend.models.qa import ChunkResult
from backend.services import search_service

router = APIRouter(prefix="/search", tags=["Search APIs"])

_CHUNK_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,200}$')


@router.get("/vector", response_model=list[ChunkResult])
async def vector_search(
    _user: Annotated[dict, Depends(get_current_user)],
    q: str = Query(..., description="Natural language query"),
    top_k: int = Query(5, ge=1, le=20),
) -> list[ChunkResult]:
    """
    Pure semantic (vector) search.
    Finds chunks whose MEANING is closest to the query.
    Best for: paraphrased questions, concept search.
    """
    return await search_service.vector_search(q, top_k)


@router.get("/keyword", response_model=list[ChunkResult])
async def keyword_search(
    _user: Annotated[dict, Depends(get_current_user)],
    q: str = Query(..., description="Keyword query"),
    top_k: int = Query(5, ge=1, le=20),
) -> list[ChunkResult]:
    """
    Keyword (BM25) search.
    Finds chunks containing the exact words in the query.
    Best for: specific drug names, exact phrases.
    """
    return await search_service.keyword_search(q, top_k)


@router.get("/hybrid", response_model=list[ChunkResult])
async def hybrid_search(
    _user: Annotated[dict, Depends(get_current_user)],
    q: str = Query(..., description="Query (combined semantic + keyword)"),
    top_k: int = Query(5, ge=1, le=20),
) -> list[ChunkResult]:
    """
    Hybrid search combining vector + keyword via Reciprocal Rank Fusion.
    Best for: general Q&A where you want the most relevant results overall.
    """
    return await search_service.hybrid_search(q, top_k)


@router.get("/graph", response_model=list[ChunkResult])
async def graph_search(
    _user: Annotated[dict, Depends(get_current_user)],
    chunk_ids: str = Query(..., description="Comma-separated chunk IDs to expand"),
    top_k: int = Query(5, ge=1, le=10),
) -> list[ChunkResult]:
    """
    Graph-based context expansion.
    Given a set of found chunks, returns their neighbours in the document graph.
    Best for: getting surrounding context after an initial search.
    """
    ids = [cid.strip() for cid in chunk_ids.split(",") if cid.strip()]
    valid_ids = [cid for cid in ids if _CHUNK_ID_RE.match(cid)]
    if not valid_ids:
        raise HTTPException(status_code=400, detail="No valid chunk IDs provided")
    return await search_service.graph_search(valid_ids, top_k)
