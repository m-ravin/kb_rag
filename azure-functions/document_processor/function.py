"""
Document Processor Azure Function

This is the "robot" that wakes up automatically whenever a new document is
uploaded to Azure Data Lake Storage. It reads the file, breaks it into small
pieces, converts those pieces to numbers (vectors), and stores everything so
the Q&A system can later find the right answer.

Think of it like a librarian who reads every new book, writes a summary card
for each chapter, and files it in the card catalogue.

Implementation note: this function is fully synchronous.
Mixing async Azure SDK clients with synchronous gremlin_python and PyMuPDF
causes event-loop deadlocks under concurrent invocations. All I/O here is
synchronous; the Azure Functions runtime manages the worker process pool.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

import azure.functions as func
import fitz  # PyMuPDF — reads PDFs
import pymongo
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from docx import Document as DocxDocument
from gremlin_python.driver import client as gremlin_client
from gremlin_python.driver import serializer
from openai import AzureOpenAI
from pptx import Presentation

logger = logging.getLogger(__name__)

# ── Azure SDK clients (created once, reused across invocations) ───────────────
# All clients are synchronous so there is no event-loop contention.

openai_client = AzureOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_KEY"],
    api_version="2024-08-01-preview",
)

search_client = SearchClient(
    endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
    index_name=os.environ.get("AZURE_SEARCH_INDEX_NAME", "pil-documents"),
    credential=AzureKeyCredential(os.environ["AZURE_SEARCH_KEY"]),
)

# pymongo (sync) — motor (async) has no place in a sync function
mongo_client = pymongo.MongoClient(os.environ["COSMOS_MONGO_CONNECTION"])
db = mongo_client["pil-knowledge-base"]

# How many chunks to embed in a single OpenAI API call (max 2048 texts per call,
# but 16 is a safe batch size that balances throughput and payload size)
_EMBED_BATCH_SIZE = 16

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
    _validate_magic_bytes(raw_bytes, filename)

    # Mark document as processing in MongoDB
    _update_document_status(document_id, "processing")

    try:
        text, metadata = _extract_content(raw_bytes, filename)
        chunks = _chunk_text(text, chunk_size=512, overlap=64)
        _embed_and_index(chunks, document_id, filename, metadata)
        _build_chunk_graph(chunks, document_id)
        _update_document_status(document_id, "indexed", metadata)
        logger.info("Successfully processed %s → %d chunks", filename, len(chunks))

    except Exception as exc:
        logger.exception("Failed to process %s: %s", blob_name, exc)
        _update_document_status(document_id, "failed", error=str(exc))
        raise


# ── Step 0: Validate uploaded file magic bytes ────────────────────────────────

_MAGIC_BYTES: dict[str, bytes] = {
    "pdf": b"%PDF",
    "docx": b"PK\x03\x04",  # ZIP-based Office format
    "pptx": b"PK\x03\x04",
}


def _validate_magic_bytes(raw_bytes: bytes, filename: str) -> None:
    """Reject files whose magic bytes don't match the declared extension."""
    ext = filename.rsplit(".", 1)[-1].lower()
    expected = _MAGIC_BYTES.get(ext)
    if expected and not raw_bytes.startswith(expected):
        raise ValueError(
            f"File content does not match extension .{ext} — upload rejected."
        )


# ── Step 1: Extract text from PDF / DOCX / PPTX ──────────────────────────────

def _extract_content(raw_bytes: bytes, filename: str) -> tuple[str, dict]:
    """
    Reads a document file and pulls out all the text.
    Like a person reading a book and typing out every word.
    """
    ext = filename.rsplit(".", 1)[-1].lower()
    metadata: dict[str, Any] = {"filename": filename, "file_type": ext}

    if ext == "pdf":
        return _extract_pdf(raw_bytes, metadata)
    elif ext == "docx":
        return _extract_docx(raw_bytes, metadata)
    elif ext in ("pptx", "ppt"):
        return _extract_pptx(raw_bytes, metadata)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def _extract_pdf(raw_bytes: bytes, metadata: dict) -> tuple[str, dict]:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(raw_bytes)
        tmp_path = tmp.name
    try:
        doc = fitz.open(tmp_path)
        pages = [page.get_text() for page in doc]
        metadata["page_count"] = len(doc)
        metadata["title"] = doc.metadata.get("title", "")
        doc.close()
        return "\n\n".join(pages), metadata
    finally:
        os.remove(tmp_path)


def _extract_docx(raw_bytes: bytes, metadata: dict) -> tuple[str, dict]:
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(raw_bytes)
        tmp_path = tmp.name
    try:
        doc = DocxDocument(tmp_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        metadata["paragraph_count"] = len(paragraphs)
        return "\n\n".join(paragraphs), metadata
    finally:
        os.remove(tmp_path)


def _extract_pptx(raw_bytes: bytes, metadata: dict) -> tuple[str, dict]:
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
        tmp.write(raw_bytes)
        tmp_path = tmp.name
    try:
        prs = Presentation(tmp_path)
        slides_text = [
            " ".join(shape.text for shape in slide.shapes if hasattr(shape, "text"))
            for slide in prs.slides
        ]
        metadata["slide_count"] = len(prs.slides)
        return "\n\n".join(slides_text), metadata
    finally:
        os.remove(tmp_path)


# ── Step 2: Split text into overlapping chunks ─────────────────────────────────

def _chunk_text(text: str, chunk_size: int = 512, overlap: int = 64) -> list[dict]:
    """
    Splits a long document into smaller overlapping pieces.

    Like cutting a long book into short chapters that each overlap a little with
    the next one — so no sentence gets cut off awkwardly at a boundary.
    """
    words = text.split()
    chunks = []
    step = chunk_size - overlap

    for i in range(0, len(words), step):
        chunk_words = words[i : i + chunk_size]
        chunk_text = " ".join(chunk_words)
        if not chunk_text.strip():
            continue
        chunks.append(
            {
                "chunk_index": len(chunks),
                "text": chunk_text,
                "word_start": i,
                "word_end": i + len(chunk_words),
            }
        )

    return chunks


# ── Step 3: Embed and upload to Azure AI Search ───────────────────────────────

def _embed_and_index(
    chunks: list[dict], document_id: str, filename: str, metadata: dict
) -> None:
    """
    Converts each chunk into a vector and stores it in Azure AI Search.

    Chunks are embedded in batches of _EMBED_BATCH_SIZE to reduce the number
    of API round-trips (was previously one call per chunk — now ~16× faster).
    """
    embedding_model = os.environ.get(
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"
    )
    documents = []

    for batch_start in range(0, len(chunks), _EMBED_BATCH_SIZE):
        batch = chunks[batch_start : batch_start + _EMBED_BATCH_SIZE]
        batch_texts = [c["text"] for c in batch]

        response = openai_client.embeddings.create(
            input=batch_texts,
            model=embedding_model,
        )

        for j, chunk in enumerate(batch):
            vector = response.data[j].embedding
            documents.append(
                {
                    "id": f"{document_id}_chunk_{chunk['chunk_index']}",
                    "document_id": document_id,
                    "filename": filename,
                    "chunk_index": chunk["chunk_index"],
                    "content": chunk["text"],
                    "content_vector": vector,
                    "metadata": json.dumps(metadata),
                    "indexed_at": datetime.now(timezone.utc).isoformat(),
                }
            )

    # Upload in batches of 100 (Azure Search limit per request)
    for i in range(0, len(documents), 100):
        search_client.upload_documents(documents=documents[i : i + 100])

    logger.info("Indexed %d chunks for document %s", len(documents), document_id)


# ── Step 4: Build chunk relationship graph in Cosmos Gremlin ──────────────────

def _build_chunk_graph(chunks: list[dict], document_id: str) -> None:
    """
    Creates a map showing how chunks are related to each other.
    Uses Gremlin parameter bindings to prevent query injection.
    Graph building is best-effort — failure does not abort the pipeline.
    """
    try:
        gremlin = gremlin_client.Client(
            os.environ["COSMOS_GREMLIN_ENDPOINT"],
            "g",
            username="/dbs/pil-graph/colls/chunk-graph",
            password=os.environ["COSMOS_GREMLIN_KEY"],
            message_serializer=serializer.GraphSONSerializersV2d0(),
        )

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

            # Link consecutive chunks with "nextChunk" edge
            if chunk["chunk_index"] > 0:
                prev_id = f"{document_id}_chunk_{chunk['chunk_index'] - 1}"
                gremlin.submit(
                    "g.V(prev_id).addE('nextChunk').to(__.V(curr_id))",
                    {"prev_id": prev_id, "curr_id": vertex_id},
                ).all().result()

        gremlin.close()
        logger.info("Built chunk graph for %s (%d nodes)", document_id, len(chunks))

    except Exception as exc:
        logger.warning("Graph build failed for %s: %s", document_id, exc)


# ── Helpers: MongoDB status updates ──────────────────────────────────────────

def _update_document_status(
    document_id: str,
    status: str,
    metadata: dict | None = None,
    error: str | None = None,
) -> None:
    update: dict[str, Any] = {
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if metadata:
        update["metadata"] = metadata
    if error:
        update["error"] = error

    db["documents"].update_one(
        {"document_id": document_id},
        {"$set": update},
        upsert=True,
    )
