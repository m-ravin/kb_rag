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

#### Scenario 4 — Two different files under the same folder (no longer collides)
```bash
az storage blob upload --account-name stdevaz1dp001 --account-key "$STORAGE_KEY" \
  --container-name pil-documents --name "shared-id/a.pdf" --file ./a.pdf
az storage blob upload --account-name stdevaz1dp001 --account-key "$STORAGE_KEY" \
  --container-name pil-documents --name "shared-id/b.pdf" --file ./b.pdf
```
Expect: two distinct `document_id`s (`shared-id-a-<hash>`,
`shared-id-b-<hash>`) and two independently searchable sets of chunks.
This used to silently collide — `document_id` was derived from the
top-level folder only, so both files got the identical id and the second
upload's chunks overwrote the first's Search entries at matching
`chunk_index` positions. That actually happened in production (see
`document_identity.py` and
`docs/adr/0016-document-lifecycle-and-data-integrity.md`) before the id
scheme was changed to include the filename. Re-uploading to the exact same
`{folder}/{filename}` path twice is still an intentional upsert, not a
collision — that's the desired "resubmit a corrected file" behavior.

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

### Inspecting ingested data — chunks, metadata, and vectors directly

The scenarios above confirm *that* a document processed successfully. To
look at what actually landed in each store — the extracted metadata, the
individual chunks, and whether the embeddings are really there — query the
stores directly.

**Get the Search admin key without touching Key Vault.** The Function App's
Key Vault firewall only allows the Function App's own outbound IPs, so a
`az keyvault secret show` for `search-api-key` (or `cosmos-mongo-connection-string`)
from a local machine fails with `ForbiddenByFirewall`. Skip Key Vault
entirely and pull the key straight from the Search resource instead — this
is a direct ARM call, not a Key Vault read, so it isn't subject to that
firewall:
```bash
SEARCH_KEY=$(az search admin-key show --service-name srch-dev-az1-dp \
  --resource-group rsg-dev-az1-dp --query primaryKey -o tsv)
```

**1. Chunk count, metadata, and content preview** for a given document:
```bash
curl -s "https://srch-dev-az1-dp.search.windows.net/indexes/pil-documents/docs/search?api-version=2024-07-01" \
  -H "api-key: $SEARCH_KEY" -H "Content-Type: application/json" \
  -d '{"search": "*", "filter": "document_id eq '\''<document_id>'\''",
       "select": "id,document_id,filename,chunk_index,indexed_at,metadata,content", "top": 50}'
```
`metadata` is a JSON string with `filename`, `file_type`, `page_count`, and
(when extractable) `title`. Sort the results by `chunk_index` client-side —
it's not marked `sortable` in the index, so `$orderby` on it returns a 400.

**2. Confirm the vector is actually populated.** `content_vector` is
`retrievable: false` in the schema (a deliberate write-only setting — it can
be searched but not read back via `$select`), so you can't just fetch the
raw array. Instead run a vector KNN query and confirm you get back distinct,
non-zero cosine scores for the expected chunks — that only happens if real
1536-dim embeddings are indexed:
```bash
python -c "
import json, random
random.seed(0)
vec = [random.gauss(0, 1) for _ in range(1536)]
norm = sum(v * v for v in vec) ** 0.5
vec = [v / norm for v in vec]
print(json.dumps({
    'search': None,
    'filter': \"document_id eq '<document_id>'\",
    'select': 'id,chunk_index',
    'vectorQueries': [{'kind': 'vector', 'vector': vec, 'fields': 'content_vector', 'k': 5}],
}))
" > query.json
curl -s "https://srch-dev-az1-dp.search.windows.net/indexes/pil-documents/docs/search?api-version=2024-07-01" \
  -H "api-key: $SEARCH_KEY" -H "Content-Type: application/json" -d @query.json
```
A random query vector isn't semantically meaningful, but Azure Search still
returns its true nearest neighbors by cosine distance — non-zero, differing
`@search.score` values across results is proof the embeddings are real, not
that the query means anything.

**3. Document status and extracted metadata in MongoDB:**
```bash
uv run python -c "
import pymongo
client = pymongo.MongoClient('<COSMOS_MONGO_CONNECTION from Key Vault>')
print(client['pil-knowledge-base']['documents'].find_one({'document_id': '<document_id>'}))
"
```
Note: as with Search, the Cosmos Mongo firewall only allows the Function
App's outbound IPs — this one *does* need the connection string via Key
Vault, and if your local IP isn't in the Cosmos Mongo firewall allowlist
either, this will fail with a Forbidden/timeout, not just an empty result.
Add your IP with `az cosmosdb mongocluster firewall rule create` if you need
this check regularly; it's not required for the Search-based checks above.

**Gotchas specific to git-bash on Windows, hit while writing these
commands:**
- Shell variables (`STORAGE_KEY`, `SEARCH_KEY`, etc.) do **not** persist
  between separate Bash tool calls — only the working directory does. Any
  script that spans multiple calls must re-source an env file (or re-run
  `az ... show`) inside each call that needs the value.
- When a curl response is piped to a *native Windows* Python (not one
  running inside MSYS) via a file, use a real Windows-style path
  (`C:/Users/...`) for both the `curl -o` output and the `python open(...)`
  call. MSYS-style paths like `/tmp/...` or `/c/Users/...` are virtual
  mappings that only MSYS-aware tools (bash, curl, git) understand — native
  `python.exe` resolves them literally and fails with `FileNotFoundError`.

### Document lifecycle — deletion, purge, and reconciliation

See `docs/adr/0016-document-lifecycle-and-data-integrity.md` for the full
rationale. Operationally:

**Deleting a document** goes through `DELETE /manage/documents/{document_id}`
(admin role required), never a direct blob/Search delete. It's a soft
delete: the Mongo record gets `status="deleted"` (not removed), the Search
chunks are removed immediately, and the blob moves from `processed/` (or
`pil-documents/` if it never finished processing) to the `deleted/`
container.

**Purging** happens automatically: `purge_job.py` runs nightly at 03:00 UTC,
hard-deletes anything in `deleted/` older than 7 days, and flips its Mongo
record to `status="purged"`. A Blob Storage lifecycle-management policy on
the same container (`infrastructure/terraform/modules/storage/main.tf`) is
a redundant backstop, not the primary mechanism — if you need to check
whether something was actually purged, check the Mongo record's `status`,
not just whether the blob is gone.

**Reconciliation** runs nightly at 02:00 UTC (`reconciliation_job.py`),
diffing Mongo's `status="indexed"` document_ids against Search for the same
`environment`. To run it manually against the live index instead of waiting
for the schedule:
```bash
uv run python -c "
import sys
sys.path.insert(0, 'azure-functions/document_processor')
import pymongo
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from reconciliation_job import reconcile

mongo = pymongo.MongoClient('<COSMOS_MONGO_CONNECTION from Key Vault>')
db = mongo['pil-knowledge-base']
search = SearchClient(
    endpoint='https://srch-dev-az1-dp.search.windows.net',
    index_name='pil-documents',
    credential=AzureKeyCredential('<SEARCH_KEY>'),
)
print(reconcile(db, search, 'dev'))
"
```
A clean run returns `{"missing_from_search": [], "orphaned_in_search": []}`.
Anything else means Mongo and Search have drifted — check the Function App's
`AppTraces`/`AppExceptions` for the same time window before assuming which
side is wrong.

**Failure alerts** go to the email configured as `alert_email` in
`modules/monitoring/main.tf` (default: the account owner's email) whenever
`AppTraces`/`AppExceptions` shows `SeverityLevel >= 3` or a message
containing `"Failed to process"` / `"Reconciliation drift"`. This is a
Log Analytics-scoped scheduled query alert, not a classic Function App
metric alert — the latter silently never fires against this App Insights
resource (it's workspace-based; see the ADR).

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

CI automatically runs: tests, lint, security scan (bandit + checkov), and OpenAI code review on every PR.

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
