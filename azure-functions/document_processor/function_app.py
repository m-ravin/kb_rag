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

Two more modules run on a timer, independent of any single document's
processing, so they don't fit the stage1..stage7 numbering either:
  document_identity.py    — computes document_id (see its own docstring for
                             the incident that made this necessary)
  reconciliation_job.py    — nightly: flags drift between Mongo and Search
  purge_job.py             — nightly: hard-deletes soft-deleted documents
                              past their retention window

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

from document_identity import compute_document_id
from purge_job import purge_expired_deletions
from reconciliation_job import reconcile
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
# Tags every Mongo/Search record so a future prod index/DB can filter on it
# without a schema redesign — see docs/adr/0016-document-lifecycle-and-data-integrity.md.
_ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")


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


@lru_cache(maxsize=1)
def _get_deleted_container_client() -> ContainerClient:
    # Soft-delete holding area — see purge_job.py.
    return ContainerClient.from_connection_string(
        os.environ["STORAGE_CONNECTION"],
        container_name=os.environ.get("STORAGE_DELETED_CONTAINER_NAME", "deleted"),
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
    upload_folder = parts[1] if len(parts) > 2 else "unknown"
    filename = parts[-1]
    # Content-addressed (folder + filename) id — NOT just upload_folder. Using
    # only the folder previously let two different files uploaded to the same
    # folder collide on the same document_id and silently overwrite each
    # other's Search chunks. See document_identity.py for the full rationale.
    document_id = compute_document_id(upload_folder, filename)

    # Validate magic bytes before doing any parsing (MIME spoofing guard)
    raw_bytes = blob.read()
    validate_magic_bytes(raw_bytes, filename)

    db = _get_mongo_db()
    update_document_status(
        db, document_id, "processing",
        upload_folder=upload_folder, filename=filename, environment=_ENVIRONMENT,
    )

    try:
        text, metadata = extract_content(raw_bytes, filename)
        chunks = chunk_text(text, chunk_size=512, overlap=64)

        vectors = embed_texts(_get_openai_client(), [c["text"] for c in chunks], _EMBEDDING_MODEL)
        documents = build_search_documents(
            chunks, vectors, document_id, upload_folder, filename, metadata, _ENVIRONMENT
        )
        upload_to_search(_get_search_client(), documents)
        logger.info("Indexed %d chunks for document %s", len(documents), document_id)

        build_chunk_graph(_new_gremlin_client, chunks, document_id)

        update_document_status(
            db, document_id, "indexed",
            upload_folder=upload_folder, filename=filename, environment=_ENVIRONMENT, metadata=metadata,
        )
        logger.info("Successfully processed %s → %d chunks", filename, len(chunks))

        archive_processed_blob(
            _get_source_container_client(), _get_processed_container_client(), upload_folder, filename, raw_bytes
        )
        logger.info("Archived %s to processed/%s/%s", filename, upload_folder, filename)

    except Exception as exc:
        logger.exception("Failed to process %s: %s", blob_name, exc)
        update_document_status(
            db, document_id, "failed",
            upload_folder=upload_folder, filename=filename, environment=_ENVIRONMENT, error=str(exc),
        )
        raise


# ── Lifecycle jobs: run on a schedule, independent of any single document ─────

@app.timer_trigger(schedule="0 0 2 * * *", arg_name="reconcileTimer", run_on_startup=False, use_monitor=False)
def reconciliation_job(reconcileTimer: func.TimerRequest) -> None:
    """Nightly at 02:00 UTC — see reconciliation_job.py for what this checks and why."""
    result = reconcile(_get_mongo_db(), _get_search_client(), _ENVIRONMENT)
    logger.info("Reconciliation job complete: %s", result)


@app.timer_trigger(schedule="0 0 3 * * *", arg_name="purgeTimer", run_on_startup=False, use_monitor=False)
def purge_job(purgeTimer: func.TimerRequest) -> None:
    """Nightly at 03:00 UTC (after reconciliation) — see purge_job.py."""
    purged_count = purge_expired_deletions(_get_mongo_db(), _get_deleted_container_client())
    logger.info("Purge job complete: %d document(s) purged", purged_count)
