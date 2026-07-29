"""
Graph stage — builds the chunk relationship graph in Cosmos Gremlin.

Best-effort: failure here does not abort the ingestion pipeline (the document
is still searchable without graph context — see ADR-0003 risks).
"""

import logging
from typing import Callable

logger = logging.getLogger(__name__)


def build_chunk_graph(
    gremlin_client_factory: Callable[[], object], chunks: list[dict], document_id: str
) -> None:
    """
    Creates a map showing how chunks are related to each other.

    gremlin_client_factory is a zero-arg callable returning a connected
    gremlin_python Client — injected so this is testable with a fake factory
    instead of a real Cosmos Gremlin connection. A fresh client is requested
    per call, matching the original per-invocation connection behaviour.
    Uses Gremlin parameter bindings throughout to prevent query injection.
    """
    gremlin = gremlin_client_factory()
    try:
        for chunk in chunks:
            vertex_id = f"{document_id}_chunk_{chunk['chunk_index']}"

            gremlin.submit(
                "g.addV('chunk')"
                ".property('id', vid)"
                ".property('document_id', did)"
                ".property('chunk_index', cidx)"
                ".property('pk', did)",
                {
                    "vid": vertex_id,
                    "did": document_id,
                    "cidx": chunk["chunk_index"],
                },
            ).all().result()

            # Link consecutive chunks with a "nextChunk" edge
            if chunk["chunk_index"] > 0:
                prev_id = f"{document_id}_chunk_{chunk['chunk_index'] - 1}"
                gremlin.submit(
                    "g.V(prev_id).addE('nextChunk').to(__.V(curr_id))",
                    {"prev_id": prev_id, "curr_id": vertex_id},
                ).all().result()

        logger.info("Built chunk graph for %s (%d nodes)", document_id, len(chunks))

    except Exception as exc:
        logger.warning("Graph build failed for %s: %s", document_id, exc)
    finally:
        gremlin.close()
