"""
Document Processor Azure Function

This is the "robot" that wakes up automatically whenever a new document is
uploaded to Azure Data Lake Storage. It reads the file, breaks it into small
pieces, converts those pieces to numbers (vectors), and stores everything so
the Q&A system can later find the right answer.

Think of it like a librarian who reads every new book, writes a summary card
for each chapter, and files it in the card catalogue.

This file only wires the blob trigger to the pipeline stage modules below — to
fix a specific step, edit its module there instead of here. Numbered by
execution order (stage1 runs first, stage6 last):
  stage1_extraction.py    — text extraction from PDF/DOCX/PPTX + magic byte check
  stage2_chunking.py      — splitting text into overlapping chunks
  stage3_embedding.py     — turning chunk text into vectors via Azure OpenAI
  stage4_vector_store.py  — building + uploading Azure AI Search documents
  stage5_graph.py         — Cosmos Gremlin chunk relationship graph
  stage6_status.py        — MongoDB document status updates (also called
                             before stage1 to mark "processing" — it brackets
                             the whole pipeline rather than being a one-shot
                             step, but is numbered last as the pipeline's
                             final write on success)
  stage7_archive.py       — moves a successfully-processed blob out of the
                             ingestion path so it isn't reprocessed

Deliberately flat (not an ingest/ subpackage): the Azure Functions Consumption
plan's remote build pipeline was observed to intermittently corrupt nested
subdirectories in the deployed package (files ending up flattened with a
literal backslash in the name instead of living in a real subdirectory),
causing sporadic "No module named 'ingest'" failures on an otherwise-identical
zip. Flat modules alongside function_app.py sidestep that entirely. Modules
are numeric-prefixed (not a plain "ingest" grouping) purely to keep the
execution order visible in a flat directory listing — `import stage1_x`
works fine since the digit isn't leading an otherwise-bare identifier.

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

# Ensures sibling modules resolve regardless of how the Functions runtime
# sets sys.path for this file — this directory isn't part of the installable
# `backend` package (see pyproject.toml), so it can't rely on that.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import azure.functions as func
import pymongo
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.storage.blob import ContainerClient
from gremlin_python.driver import client as gremlin_client
from gremlin_python.driver import serializer
from openai import AzureOpenAI

from stage1_extraction import extract_content, validate_magic_bytes
from stage2_chunking import chunk_text
from stage3_embedding import embed_texts
from stage4_vector_store import build_search_documents, upload_to_search
from stage5_graph import build_chunk_graph
from stage6_status import update_document_status
from stage7_archive import archive_processed_blob

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


@lru_cache(maxsize=1)
def _get_source_container_client() -> ContainerClient:
    return ContainerClient.from_connection_string(
        os.environ["STORAGE_CONNECTION"],
        container_name=os.environ.get("STORAGE_CONTAINER_NAME", "pil-documents"),
    )


@lru_cache(maxsize=1)
def _get_processed_container_client() -> ContainerClient:
    # Deliberately a separate container from the ingestion one, not a
    # "processed/" subfolder — see stage7_archive.py's module docstring for
    # why (a same-container prefix caused a self-triggering reprocessing
    # loop via the Event Grid subscription).
    return ContainerClient.from_connection_string(
        os.environ["STORAGE_CONNECTION"],
        container_name=os.environ.get("STORAGE_PROCESSED_CONTAINER_NAME", "processed"),
    )


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


# source="EventGrid" fires within seconds of a blob write, backed by an Event
# Grid subscription on the storage account. Without it, the SDK falls back to
# LogsAndContainerScan — a polling scan of storage logs that can take minutes
# (occasionally much longer) to notice a new blob.
@app.blob_trigger(
    arg_name="blob",
    path="pil-documents/{document_id}/{filename}",
    connection="STORAGE_CONNECTION",
    source="EventGrid",
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

        archive_processed_blob(
            _get_source_container_client(), _get_processed_container_client(), document_id, filename, raw_bytes
        )
        logger.info("Archived %s to processed/%s/%s", filename, document_id, filename)

    except Exception as exc:
        logger.exception("Failed to process %s: %s", blob_name, exc)
        update_document_status(db, document_id, "failed", error=str(exc))
        raise
