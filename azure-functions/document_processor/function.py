"""
Document Processor Azure Function

This is the "robot" that wakes up automatically whenever a new document is
uploaded to Azure Data Lake Storage. It reads the file, breaks it into small
pieces, converts those pieces to numbers (vectors), and stores everything so
the Q&A system can later find the right answer.

Think of it like a librarian who reads every new book, writes a summary card
for each chapter, and files it in the card catalogue.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

import azure.functions as func
from azure.storage.blob import BlobServiceClient
from openai import AzureOpenAI
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from azure.core.credentials import AzureKeyCredential
from gremlin_python.driver import client as gremlin_client
from gremlin_python.driver import serializer
import motor.motor_asyncio
import fitz  # PyMuPDF — reads PDFs
from docx import Document as DocxDocument
from pptx import Presentation

logger = logging.getLogger(__name__)

# ── Azure SDK clients (created once, reused across invocations) ───────────────

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

mongo_client = motor.motor_asyncio.AsyncIOMotorClient(
    os.environ["COSMOS_MONGO_CONNECTION"]
)
db = mongo_client["pil-knowledge-base"]


# ── Entry point: triggered by a blob upload to pil-documents container ────────

app = func.FunctionApp()


@app.blob_trigger(
    arg_name="blob",
    path="pil-documents/{document_id}/{filename}",
    connection="STORAGE_CONNECTION",
)
async def process_document(blob: func.InputStream) -> None:
    """
    Triggered automatically when a file lands in the pil-documents container.
    Runs the full extraction → chunking → embedding → indexing pipeline.
    """
    blob_name = blob.name
    logger.info("Processing document: %s (%d bytes)", blob_name, blob.length)

    parts = blob_name.split("/")
    document_id = parts[1] if len(parts) > 2 else "unknown"
    filename = parts[-1]

    # Mark document as processing in MongoDB
    await _update_document_status(document_id, "processing")

    try:
        raw_bytes = blob.read()
        text, metadata = _extract_content(raw_bytes, filename)
        chunks = _chunk_text(text, chunk_size=512, overlap=64)
        await _embed_and_index(chunks, document_id, filename, metadata)
        await _build_chunk_graph(chunks, document_id)
        await _update_document_status(document_id, "indexed", metadata)
        logger.info("Successfully processed %s → %d chunks", filename, len(chunks))

    except Exception as exc:
        logger.exception("Failed to process %s: %s", blob_name, exc)
        await _update_document_status(document_id, "failed", error=str(exc))
        raise


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

    doc = fitz.open(tmp_path)
    pages = []
    for page_num, page in enumerate(doc):
        pages.append(page.get_text())

    metadata["page_count"] = len(doc)
    metadata["title"] = doc.metadata.get("title", "")
    doc.close()
    return "\n\n".join(pages), metadata


def _extract_docx(raw_bytes: bytes, metadata: dict) -> tuple[str, dict]:
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(raw_bytes)
        tmp_path = tmp.name

    doc = DocxDocument(tmp_path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    metadata["paragraph_count"] = len(paragraphs)
    return "\n\n".join(paragraphs), metadata


def _extract_pptx(raw_bytes: bytes, metadata: dict) -> tuple[str, dict]:
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
        tmp.write(raw_bytes)
        tmp_path = tmp.name

    prs = Presentation(tmp_path)
    slides_text = []
    for slide in prs.slides:
        slide_text = " ".join(
            shape.text for shape in slide.shapes if hasattr(shape, "text")
        )
        slides_text.append(slide_text)

    metadata["slide_count"] = len(prs.slides)
    return "\n\n".join(slides_text), metadata


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
        if len(chunk_text.strip()) < 20:
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

async def _embed_and_index(
    chunks: list[dict], document_id: str, filename: str, metadata: dict
) -> None:
    """
    Converts each chunk into a vector (list of 1536 numbers) and stores it
    in Azure AI Search so we can do similarity searches later.

    Like translating each chapter into a secret code that lets us find
    chapters with similar meanings very quickly.
    """
    documents = []
    for chunk in chunks:
        embedding_response = openai_client.embeddings.create(
            input=chunk["text"],
            model=os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"),
        )
        vector = embedding_response.data[0].embedding

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
        batch = documents[i : i + 100]
        search_client.upload_documents(documents=batch)

    logger.info("Indexed %d chunks for document %s", len(documents), document_id)


# ── Step 4: Build chunk relationship graph in Cosmos Gremlin ──────────────────

async def _build_chunk_graph(chunks: list[dict], document_id: str) -> None:
    """
    Creates a map showing how chunks are related to each other
    (neighbours in the document, same section, etc.)

    Like drawing a web connecting all the chapters of a book to show
    which ones are near each other or talk about similar things.
    """
    try:
        gremlin = gremlin_client.Client(
            os.environ["COSMOS_GREMLIN_ENDPOINT"],
            "g",
            username=f"/dbs/pil-graph/colls/chunk-graph",
            password=os.environ["COSMOS_GREMLIN_KEY"],
            message_serializer=serializer.GraphSONSerializersV2d0(),
        )

        for chunk in chunks:
            vertex_id = f"{document_id}_chunk_{chunk['chunk_index']}"
            gremlin.submit(
                f"g.addV('chunk')"
                f".property('id', '{vertex_id}')"
                f".property('document_id', '{document_id}')"
                f".property('chunk_index', {chunk['chunk_index']})"
                f".property('pk', '{document_id}')"
            ).all().result()

            # Link consecutive chunks with "nextChunk" edge
            if chunk["chunk_index"] > 0:
                prev_id = f"{document_id}_chunk_{chunk['chunk_index'] - 1}"
                gremlin.submit(
                    f"g.V('{prev_id}').addE('nextChunk').to(g.V('{vertex_id}'))"
                ).all().result()

        gremlin.close()
        logger.info("Built chunk graph for %s (%d nodes)", document_id, len(chunks))

    except Exception as exc:
        # Graph building is best-effort; don't fail the whole pipeline
        logger.warning("Graph build failed for %s: %s", document_id, exc)


# ── Helpers: MongoDB status updates ──────────────────────────────────────────

async def _update_document_status(
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

    await db["documents"].update_one(
        {"document_id": document_id},
        {"$set": update},
        upsert=True,
    )
