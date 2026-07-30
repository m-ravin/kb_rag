"""
Vector store stage — builds Azure AI Search documents and uploads them.

Takes an already-constructed SearchClient (dependency injection) instead of
creating one itself, so this is testable with a mock client.
"""

import json
from datetime import datetime, timezone

# Azure AI Search's per-request document upload limit.
_UPLOAD_BATCH_SIZE = 100


def build_search_documents(
    chunks: list[dict],
    vectors: list[list[float]],
    document_id: str,
    upload_folder: str,
    filename: str,
    metadata: dict,
    environment: str,
) -> list[dict]:
    """Pairs each chunk with its vector into an Azure AI Search document record."""
    return [
        {
            "id": f"{document_id}_chunk_{chunk['chunk_index']}",
            "document_id": document_id,
            "upload_folder": upload_folder,
            "filename": filename,
            "chunk_index": chunk["chunk_index"],
            "content": chunk["text"],
            "content_vector": vector,
            "metadata": json.dumps(metadata),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "environment": environment,
        }
        for chunk, vector in zip(chunks, vectors)
    ]


def upload_to_search(search_client, documents: list[dict]) -> None:
    """Uploads documents to Azure AI Search in batches of 100 (the service's per-request limit)."""
    for i in range(0, len(documents), _UPLOAD_BATCH_SIZE):
        search_client.upload_documents(documents=documents[i : i + _UPLOAD_BATCH_SIZE])
