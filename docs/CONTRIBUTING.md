# Contributing to KB RAG

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.11+ | Backend |
| uv | latest | Python package management |
| Node.js | 20+ | Frontend |
| Docker + Docker Compose | latest | Local stack |
| Terraform | 1.5+ | Infrastructure |
| Azure CLI (`az`) | latest | Azure authentication |

## Development Setup

```bash
# 1. Clone
git clone https://github.com/m-ravin/kb_rag.git
cd kb_rag

# 2. Copy and fill in environment variables
cp .env.example .env
# Edit .env — set JWT_SECRET and all Azure connection strings

# 3. Install backend dependencies
uv sync --dev

# 4. Install frontend dependencies
cd frontend && npm install && cd ..

# 5. Start local stack — builds Presidio image (includes spaCy model download, ~5 min first time)
#    then starts Redis, Presidio service, backend, and frontend together.
docker-compose up
```

Backend runs at `http://localhost:8000` · Frontend at `http://localhost:3000` · Swagger UI at `http://localhost:8000/docs`

## TDD Workflow

All production code changes follow **Red → Green → Refactor**:

1. **Write the failing test first** — tests live in `tests/unit/` or `tests/integration/`
2. **Run it — confirm RED**
   ```bash
   uv run pytest tests/path/to/test_file.py -v
   ```
3. **Write minimal implementation to make it pass**
4. **Run again — confirm GREEN**
5. **Refactor while keeping tests green**
6. **Verify 80%+ coverage**
   ```bash
   uv run pytest --cov=backend --cov-report=term-missing
   ```

See [ADR-0007](adr/0007-tdd-80-percent-coverage.md) for the rationale.

## Available Commands

### Backend

| Command | Description |
|---------|-------------|
| `uv run uvicorn backend.main:app --reload` | Dev server with hot reload |
| `uv run pytest` | Run all tests |
| `uv run pytest tests/unit/ -v` | Unit tests only |
| `uv run pytest tests/integration/ -v` | Integration tests only |
| `uv run pytest --cov=backend` | With coverage report |
| `uv run ruff check backend/` | Lint |
| `uv run ruff format backend/` | Format |
| `uv run mypy backend/` | Type check |

### Frontend

| Command | Description |
|---------|-------------|
| `npm run dev` | Dev server (port 3000) |
| `npm run build` | Production build with TypeScript check |
| `npm run preview` | Preview production build locally (port 4173) |
| `npm run lint` | ESLint |
| `npm run test:e2e` | Playwright E2E headless |
| `npm run test:e2e:ui` | Playwright interactive UI |
| `npm run test:e2e:report` | Open last HTML test report |

## Testing

### Unit tests — no Azure credentials needed

All Azure SDK calls are mocked in `tests/conftest.py`. Tests run in isolation.

```bash
uv run pytest tests/unit/ -v
```

### Integration tests — mocked backend

```bash
uv run pytest tests/integration/ -v
```

### E2E tests — runs against Vite dev server

```bash
cd frontend
npm run dev &          # Start dev server first
npm run test:e2e       # Run Playwright against it
```

### Stdlib-only tests (no packages needed)

```bash
python tests/test_pure_logic.py       # 28 tests
python tests/unit/ingest/test_chunking.py   # 8 tests — imports the real chunking stage
```

### Live ingestion pipeline — manual scenario testing

Unit tests cover pipeline logic in isolation; these scenarios exercise the
*deployed* Function App end-to-end against real Azure resources. Useful
after any change to `azure-functions/document_processor/` or its infra.

Resource names (dev): storage account `stdevaz1dp001`, container
`pil-documents`, Function App `func-doc-proc-pil-dev63u6v3` in resource
group `rg-pil-dev`, Application Insights `appi-pil-dev`.

Get the storage account key once per session and reuse it:
```bash
STORAGE_KEY=$(az storage account keys list --resource-group rsg-dev-az1-dp \
  --account-name stdevaz1dp001 --query '[0].value' -o tsv)
```

**General verification pattern** — after any upload, check status in order
of increasing detail:
```bash
# 1. Did the function even fire, and how? (EventGrid vs LogsAndContainerScan)
az monitor app-insights query --app <app-insights-id> \
  --analytics-query "traces | where timestamp > ago(5m) | where message contains '<document_id>' | order by timestamp desc | project timestamp, message"

# 2. What's the document's final status?
uv run python -c "
import pymongo
client = pymongo.MongoClient('<COSMOS_MONGO_CONNECTION from Key Vault>')
print(client['pil-knowledge-base']['documents'].find_one({'document_id': '<document_id>'}))
"

# 3. Did the blob get archived (only happens on success)? Note: a SEPARATE
#    container, not a "processed/" prefix inside pil-documents — see
#    stage7_archive.py's module docstring for why.
az storage blob list --account-name stdevaz1dp001 --account-key "$STORAGE_KEY" \
  --container-name processed --prefix "<document_id>/" -o table
```

#### Scenario 1 — Happy path (PDF)
```bash
az storage blob upload --account-name stdevaz1dp001 --account-key "$STORAGE_KEY" \
  --container-name pil-documents --name "test-doc-1/sample.pdf" --file ./sample.pdf
```
Expect: trace shows `New blob detected(EventGrid)` within a few seconds →
`Indexed N chunks` → `Successfully processed` → Mongo status `indexed` →
blob present at `processed/test-doc-1/sample.pdf` (in the **processed**
container, not `pil-documents`) and gone from `pil-documents/test-doc-1/sample.pdf`.

#### Scenario 2 — DOCX / PPTX
Same as Scenario 1 with a `.docx` or `.pptx` file, to exercise
`stage1_extraction.py`'s format-specific branches.

#### Scenario 3 — Invalid file (magic-byte mismatch)
Upload a `.txt` file renamed to `.pdf` (content doesn't match extension):
```bash
az storage blob upload --account-name stdevaz1dp001 --account-key "$STORAGE_KEY" \
  --container-name pil-documents --name "test-bad-magic/fake.pdf" --file ./notes.txt
```
Expect: fails fast (before any Azure OpenAI/Search calls) on
`validate_magic_bytes`, Mongo status `failed` with a magic-byte error, blob
stays at its original path (not moved — only successes get archived).

#### Scenario 4 — Duplicate `document_id` (chunk ID collision)
Upload two *different* files under the same folder:
```bash
az storage blob upload --account-name stdevaz1dp001 --account-key "$STORAGE_KEY" \
  --container-name pil-documents --name "shared-id/a.pdf" --file ./a.pdf
az storage blob upload --account-name stdevaz1dp001 --account-key "$STORAGE_KEY" \
  --container-name pil-documents --name "shared-id/b.pdf" --file ./b.pdf
```
Expect: both compute overlapping search-document IDs
(`shared-id_chunk_0`, `shared-id_chunk_1`, ...), so the second upload's
chunks overwrite the first's. This is a known sharp edge, not a bug to
fix here — always give unrelated files distinct top-level folders.

#### Scenario 5 — Graph stage failure (best-effort, non-fatal)
No special setup needed while `gremlinpython`'s aiohttp transport
incompatibility is unresolved — every real upload exercises this path.
Expect: trace shows `Graph build failed for <document_id>: ...` as a
`warning`, but the document still reaches Mongo status `indexed` and gets
archived normally. If this ever instead fails the whole document, that's
a regression in `stage5_graph.py`'s try/except placement.

#### Scenario 6 — Retry then poison queue
Temporarily break something the pipeline needs (e.g. revoke the Function
App's Key Vault role, or rename `COSMOS_DB_NAME`), then upload a file.
Expect: `DequeueCount` increments across up to 5 execution attempts
(visible in the trigger-details trace line), then
`Message has reached MaxDequeueCount of 5. Moving message to queue
'webjobs-blobtrigger-poison'`. Revert the breakage before re-testing —
a poisoned message won't retry itself; re-upload (or copy-to-self) the
blob to generate a fresh event.

#### Scenario 7 — Trigger latency (Event Grid health check)
Upload any file and note the wall-clock time between the upload command
returning and the `New blob detected(EventGrid)` trace appearing. Expect
low single-digit seconds. If it's consistently slow (tens of seconds or
more), check the Event Grid subscription's health:
```bash
az eventgrid event-subscription show --name pil-documents-blob-created \
  --source-resource-id "/subscriptions/<sub>/resourceGroups/rsg-dev-az1-dp/providers/Microsoft.Storage/storageAccounts/stdevaz1dp001" \
  --query "provisioningState"
```
A slow-but-eventually-firing trigger with a healthy subscription usually
means it silently fell back to `LogsAndContainerScan` — check the trace's
`Reason=` text for which mechanism actually fired.

## Code Style

- **Python**: `ruff` for lint + format, `mypy` for type checking
- **TypeScript**: ESLint (`npm run lint`)
- **Line length**: 100 chars (Python), default (TypeScript)
- **No `print()`** in production code — use `logging`
- **No hardcoded secrets** — always use env vars

Pre-commit equivalent (run before pushing):
```bash
uv run ruff check backend/ && uv run ruff format --check backend/ && uv run pytest
```

## PR Checklist

Before opening a PR:

- [ ] Tests written for new code (TDD — tests first)
- [ ] `uv run pytest --cov=backend` passes with 80%+ coverage
- [ ] `uv run ruff check backend/` returns no errors
- [ ] No hardcoded secrets, `print()` statements, or bare `except Exception:` blocks
- [ ] PR description explains *why* (not just *what*)
- [ ] ADR created if an architectural decision was made (`docs/adr/`)

CI automatically runs: tests, lint, security scan (bandit + checkov), and Claude AI review on every PR.

## Adding a New API Endpoint

1. Add route to the appropriate router in `backend/api/`
2. Add Pydantic models to `backend/models/` if needed
3. Write tests in `tests/integration/api/`
4. Add the endpoint to the API Reference table in `README.md`

## Adding a New Document Type

1. Add extraction logic to `azure-functions/document_processor/function.py` in `_extract_content()`
2. Add the MIME type to `frontend/src/pages/Documents.tsx` dropzone `accept` config
3. Add the file extension to the management router upload validation
4. Write a test in `tests/unit/` for the extraction logic

## Architecture Decisions

When making a significant technical choice, create an ADR:

```bash
# Copy the template
cp docs/adr/template.md docs/adr/00XX-your-decision.md

# Add an entry to the index
# Edit docs/adr/README.md
```

See existing ADRs in [`docs/adr/`](adr/) for format examples.
