# ADR-0003: Azure Functions for Blob-Triggered Document Processing

**Date**: 2026-05-07
**Status**: accepted
**Deciders**: KB RAG system design

## Context

When a PIL document is uploaded to Azure Data Lake Storage, it must be automatically processed through a five-step pipeline: text extraction → chunking → embedding → Azure AI Search indexing → Cosmos Gremlin graph construction. This pipeline is CPU-bound, runs for 30–120 seconds depending on document size, and is triggered by file uploads rather than HTTP requests. The pipeline runs infrequently (tens of documents per day in a typical PIL management scenario) but must be reliable and retryable on failure.

## Decision

We use an **Azure Function with a blob storage trigger** (`azure-functions/document_processor/function.py`) running on a Consumption plan. The function wakes up automatically when a file lands in the `pil-documents` container, runs the full extraction-to-indexing pipeline, and writes status updates to Cosmos MongoDB throughout. Azure Data Factory orchestrates retry logic and pipeline monitoring.

## Alternatives Considered

### Alternative 1: Background worker container in AKS
- **Pros**: Full control over runtime environment; can use GPU for faster embedding; no cold-start latency; easier local debugging
- **Cons**: Container must run 24/7 to avoid missed triggers, even when no documents are being uploaded; adds ~$140/month for a dedicated D2s_v3 node; requires polling or queue-based triggering; more operational complexity
- **Why not**: PIL uploads are infrequent and bursty — paying always-on compute for an idle worker is wasteful. Azure Functions on a Consumption plan costs ~$0 when idle and scales automatically for burst uploads.

### Alternative 2: Azure Data Factory pipeline only (no Functions)
- **Pros**: Visual pipeline designer; built-in retry and monitoring; native Azure integration
- **Cons**: ADF pipelines cannot run arbitrary Python code directly — they orchestrate Activities; embedding and graph construction require custom Python that doesn't fit the ADF Activity model without a Databricks or Function dependency anyway; ADF pipelines are harder to unit test
- **Why not**: ADF is used in this system for orchestration and monitoring reporting pipelines, not for Python-heavy processing. The embedding and graph steps require the full Python scientific stack.

### Alternative 3: FastAPI background task (same AKS pod as the API)
- **Pros**: No extra infrastructure; zero cold start; shares the API's Python environment
- **Cons**: Long-running CPU-bound tasks block FastAPI worker threads, degrading API response times for all concurrent users; no built-in retry on pod restart; document processing state lost if pod is killed mid-pipeline
- **Why not**: Mixing API serving and CPU-intensive batch processing in the same process is an anti-pattern that causes latency spikes under load. The API must remain responsive regardless of upload volume.

## Consequences

### Positive
- Zero cost when no documents are being processed (Consumption plan billing is per-execution)
- Automatic scale-out for burst uploads (up to 200 concurrent function instances)
- Built-in retry on transient failures (configured in `host.json`)
- Clean separation of concerns: API serves queries, Function processes documents
- Status visible in MongoDB (`pending` → `processing` → `indexed` / `failed`) throughout

### Negative
- **Cold start latency**: First invocation after idle can take 3–8 seconds for Python runtime initialisation. Acceptable for a batch process; would not be acceptable for a real-time API.
- **5-minute execution timeout on Consumption plan**: Very large PDFs (>500 pages) may time out. Mitigation: upgrade to Premium plan or split oversized documents at upload time.
- **Local development requires Azurite emulator**: The blob trigger cannot be tested locally without Azure Storage emulation. `docker-compose.yml` can be extended with `mcr.microsoft.com/azure-storage/azurite` if needed.

### Risks
- **Partial pipeline failure**: If the Function completes embedding but crashes before Gremlin graph construction, the document is searchable but lacks graph context. Mitigation: MongoDB status field tracks per-step completion; a re-run endpoint is provided at `POST /manage/documents/{id}/reprocess`.
