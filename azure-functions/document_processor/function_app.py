"""
Document Processor Azure Function

This is the "robot" that wakes up automatically whenever a new document is
uploaded to Azure Data Lake Storage. It reads the file, breaks it into small
pieces, converts those pieces to numbers (vectors), and stores everything so
the Q&A system can later find the right answer.

Think of it like a librarian who reads every new book, writes a summary card
for each chapter, and files it in the card catalogue.

This file only wires the blob trigger to the pipeline stages in ingest/ — to
fix a specific step, edit its module there instead of here:
  ingest/extraction.py    — text extraction from PDF/DOCX/PPTX + magic byte check
  ingest/chunking.py      — splitting text into overlapping chunks
  ingest/embedding.py     — turning chunk text into vectors via Azure OpenAI
  ingest/vector_store.py  — building + uploading Azure AI Search documents
  ingest/graph.py         — Cosmos Gremlin chunk relationship graph
  ingest/status.py        — MongoDB document status updates

Implementation note: this function is fully synchronous.
Mixing async Azure SDK clients with synchronous gremlin_python and PyMuPDF
causes event-loop deadlocks under concurrent invocations. All I/O here is
synchronous; the Azure Functions runtime manages the worker process pool.
"""

import logging
import os
import sys
from functools import lru_cache
from pathlib import Path

# Ensures `ingest` resolves regardless of how the Functions runtime sets
# sys.path for this file — this directory isn't part of the installable
# `backend` package (see pyproject.toml), so it can't rely on that.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import azure.functions as func
import pymongo
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from gremlin_python.driver import client as gremlin_client
from gremlin_python.driver import serializer
from openai import AzureOpenAI

from ingest.chunking import chunk_text
from ingest.embedding import embed_texts
from ingest.extraction import extract_content, validate_magic_bytes
from ingest.graph import build_chunk_graph
from ingest.status import update_document_status
from ingest.vector_store import build_search_documents, upload_to_search

logger = logging.getLogger(__name__)

# ── Azure SDK clients (created lazily, cached, reused across invocations) ─────
# All clients are synchronous so there is no event-loop contention.
#
# These used to be constructed eagerly at module level. On Linux Consumption,
# module-level code runs during function *indexing* (cold start / worker
# specialization), not just at first invocation — so any slow or
# network-touching client construction here delays indexing itself. Wrapping
# each client in an lru_cache(maxsize=1) defers construction to the first
# real blob-trigger invocation while still only building it once per worker.

_EMBEDDING_MODEL = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")


@lru_cache(maxsize=1)
def _get_openai_client() -> AzureOpenAI:
    return AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_KEY"],
        api_version="2024-08-01-preview",
    )


@lru_cache(maxsize=1)
def _get_search_client() -> SearchClient:
    return SearchClient(
        endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
        index_name=os.environ.get("AZURE_SEARCH_INDEX_NAME", "pil-documents"),
        credential=AzureKeyCredential(os.environ["AZURE_SEARCH_KEY"]),
    )


@lru_cache(maxsize=1)
def _get_mongo_db():
    # pymongo (sync) — motor (async) has no place in a sync function
    mongo_client = pymongo.MongoClient(os.environ["COSMOS_MONGO_CONNECTION"])
    return mongo_client[os.environ.get("COSMOS_DB_NAME", "pil-knowledge-base")]


def _new_gremlin_client() -> gremlin_client.Client:
    """Opens a fresh Gremlin connection — called once per document by graph.py."""
    return gremlin_client.Client(
        os.environ["COSMOS_GREMLIN_ENDPOINT"],
        "g",
        username="/dbs/pil-graph/colls/chunk-graph",
        password=os.environ["COSMOS_GREMLIN_KEY"],
        message_serializer=serializer.GraphSONSerializersV2d0(),
    )


# ── Entry point: triggered by a blob upload to pil-documents container ────────

app = func.FunctionApp()


@app.blob_trigger(
    arg_name="blob",
    path="pil-documents/{document_id}/{filename}",
    connection="STORAGE_CONNECTION",
)
def process_document(blob: func.InputStream) -> None:
    """
    Triggered automatically when a file lands in the pil-documents container.
    Runs the full extraction → chunking → embedding → indexing pipeline.
    """
    blob_name = blob.name
    logger.info("Processing document: %s (%d bytes)", blob_name, blob.length)

    parts = blob_name.split("/")
    document_id = parts[1] if len(parts) > 2 else "unknown"
    filename = parts[-1]

    # Validate magic bytes before doing any parsing (MIME spoofing guard)
    raw_bytes = blob.read()
    validate_magic_bytes(raw_bytes, filename)

    db = _get_mongo_db()
    update_document_status(db, document_id, "processing")

    try:
        text, metadata = extract_content(raw_bytes, filename)
        chunks = chunk_text(text, chunk_size=512, overlap=64)

        vectors = embed_texts(_get_openai_client(), [c["text"] for c in chunks], _EMBEDDING_MODEL)
        documents = build_search_documents(chunks, vectors, document_id, filename, metadata)
        upload_to_search(_get_search_client(), documents)
        logger.info("Indexed %d chunks for document %s", len(documents), document_id)

        build_chunk_graph(_new_gremlin_client, chunks, document_id)

        update_document_status(db, document_id, "indexed", metadata)
        logger.info("Successfully processed %s → %d chunks", filename, len(chunks))

    except Exception as exc:
        logger.exception("Failed to process %s: %s", blob_name, exc)
        update_document_status(db, document_id, "failed", error=str(exc))
        raise
