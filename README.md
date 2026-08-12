# KB RAG

An end-to-end **Retrieval-Augmented Generation (RAG)** system for any knowledge base, deployed on Microsoft Azure. Upload documents in any domain (PDF, DOCX, PPTX), then ask natural language questions and receive accurate, source-cited answers drawn directly from your content.

---

## What This System Does

1. An admin **uploads a document** (PDF/DOCX/PPTX) through the CMS web interface.
2. An **Azure Function automatically wakes up**, reads the document, splits it into chunks, converts each chunk to a vector (embedding), and stores everything in three purpose-built databases.
3. When a user **asks a question** via the API or chat UI:
   - The question is checked for PII and unsafe content — PII is **masked** before reaching the LLM
   - The question type is classified (FAQ / procedural / factual)
   - A hybrid search finds the most relevant document chunks
   - Azure OpenAI reads those chunks and writes a clear, compliant answer
   - The answer is tuned, language-detected, logged, and returned

---

## Architecture Diagram

```
User Question
     │
     ▼
[In-app rate limiter (slowapi)]  ← no separate API gateway
     │
     ▼
[Q&A Flow API]  (FastAPI on Azure Container Apps)
  ├─ PII Detection + Masking  →  [Presidio service — separate Container App, internal ingress only]
  │                                 (Docker Compose: presidio-service:8080 · ACA: internal-only, not public)
  ├─ Content Safety check     →  [Azure AI Content Safety]
  ├─ Question Type            →  [Azure OpenAI]
  ├─ Keyword Extraction       →  [Azure OpenAI]
  ├─ Hybrid Search            →  [Azure AI Search] + [Cosmos Gremlin]
  │                                ↑ vectors from [Azure OpenAI Embeddings]
  ├─ Answer Generation        →  [Azure OpenAI]  (best-effort graph enrichment — degrades
  ├─ Wording Tuning           →  [Azure OpenAI]   gracefully if Cosmos Gremlin is unavailable)
  ├─ Compliance Check         →  [Azure OpenAI]
  └─ Logging (PII masked)     →  [Cosmos MongoDB]
     │
     ▼
  Answer + Sources returned to user

Document Upload (CMS)
     │
     ▼
[Azure Data Lake Storage]
     │  (blob trigger)
     ▼
[Azure Function: document_processor]
  ├─ Extract text (PyMuPDF / python-docx / python-pptx)
  ├─ Chunk text (512 words, 64-word overlap)
  ├─ Embed chunks (batched, 16/call)  →  [Azure OpenAI Embeddings]
  ├─ Index chunks  →  [Azure AI Search]
  └─ Build graph   →  [Cosmos Gremlin]
```

---

## Azure Resources — What Each One Does

| # | Azure Resource | Technical role | Explain like I'm 5 |
|---|---|---|---|
| 1 | **Azure Container Apps** | Hosts FastAPI backend + React CMS frontend + Presidio, each as its own app in a shared environment | The apartment building where all your apps live |
| 2 | **Azure AI Search** | Vector + BM25 + hybrid search over document chunks | The super-fast librarian who memorised every sentence |
| 3 | **Azure OpenAI** | Answer generation, summarisation, compliance checking | The clever student who reads the notes and writes the answer |
| 4 | **Azure OpenAI (Embeddings)** | Converts text to 1536-dimension vectors | The translator that turns words into numbers |
| 5 | **Cosmos DB — MongoDB API** | Document metadata, user accounts, Q&A logs | The filing cabinet |
| 6 | **Cosmos DB — Gremlin API** | Chunk-to-chunk relationship graph | A map showing how document pages connect |
| 7 | **Azure Data Lake Storage Gen 2** | Raw document storage (PDF/DOCX/PPTX) | A giant USB drive in the sky |
| 8 | **Azure Cache for Redis** | Search result caching (5-min TTL) | Post-it notes so we don't repeat the same work twice |
| 9 | **Azure Functions** | Blob-triggered document processing pipeline | Little robots that wake up when a new document arrives |
| 10 | **Azure Data Factory** | Orchestrates data pipelines | The assembly line foreman |
| 11 | **Azure Key Vault** | Stores all secrets, accessed via managed identity | A locked safe — no passwords in code |
| 12 | **Azure Container Registry** | Private Docker image storage | A private warehouse for packaged app versions |
| 13 | **Azure Monitor + App Insights** | Logs, traces, metrics, dashboards | Security cameras watching everything |
| 14 | **Azure AI Content Safety** | Input/output content screening | A school internet filter |

> **Note — API Management and in-app rate limiting:**
> An earlier iteration of this system used Azure API Management as a dedicated gateway.
> It was dropped in favour of an in-process rate limiter (`slowapi`) on the FastAPI backend
> itself — one fewer resource to provision and pay for, at the cost of losing a
> developer-portal/versioning layer this project didn't need.
> See [`docs/adr/0013-container-apps-over-aks-apim.md`](docs/adr/0013-container-apps-over-aks-apim.md).

> **Note — Presidio PII service (self-hosted, not an Azure service):**
> Presidio runs as its **own Azure Container App**, with internal-only ingress (not publicly
> accessible outside the Container Apps Environment). It is built from `presidio-service/`
> and deployed alongside the FastAPI backend in the same environment. In local development
> it starts automatically via `docker-compose up`. Because it runs inside the same private
> network, PII text never leaves the environment for an external API.
> See [`docs/adr/0010-presidio-pii-microservice.md`](docs/adr/0010-presidio-pii-microservice.md)
> for the decision rationale and
> [`docs/adr/0013-container-apps-over-aks-apim.md`](docs/adr/0013-container-apps-over-aks-apim.md)
> for the AKS → Container Apps migration.

---

## Repository Structure

```
kb_rag/
├── backend/                          # FastAPI Python backend
│   ├── main.py                       # App entry point — registers all routes
│   ├── core/
│   │   ├── config.py                 # Settings from env vars (pydantic-settings)
│   │   ├── clients.py                # Singleton Azure SDK clients
│   │   └── auth.py                   # JWT auth + role-based access control
│   ├── api/
│   │   ├── qa_flow/router.py         # POST /qa/ask — full RAG pipeline
│   │   ├── task_apis/router.py       # POST /tasks/* — individual AI tasks
│   │   ├── search_apis/router.py     # GET /search/* — all 4 search strategies
│   │   └── management/router.py     # /manage/* — CMS + monitoring
│   ├── services/
│   │   ├── search_service.py         # Vector / keyword / graph / hybrid search
│   │   ├── llm_service.py            # All Azure OpenAI prompts
│   │   ├── safety_service.py         # PII masking + content safety
│   │   └── monitoring_service.py     # Q&A logging + metrics aggregation
│   └── pipeline/
│       └── indexer.py                # Azure AI Search index schema management
│
├── frontend/                         # React + TypeScript CMS
│   ├── src/pages/
│   │   ├── Login.tsx                 # JWT login form
│   │   ├── Dashboard.tsx             # Metrics charts (Recharts)
│   │   ├── Documents.tsx             # Upload + manage documents (drag-drop)
│   │   └── QATest.tsx                # Live Q&A test console
│   ├── e2e/                          # Playwright E2E tests (38 tests)
│   │   ├── specs/                    # auth, qa-console, documents, dashboard
│   │   ├── pages/                    # Page Object Models
│   │   └── fixtures/auth.ts          # JWT injection + full API mocking
│   └── playwright.config.ts
│
├── azure-functions/
│   └── document_processor/
│       ├── function_app.py          # Blob trigger — wires the stages below together
│       ├── stage1_extraction.py     # PDF/DOCX/PPTX text extraction + magic-byte check
│       ├── stage2_chunking.py       # Splits text into overlapping chunks
│       ├── stage3_embedding.py      # Chunk text → vectors (Azure OpenAI)
│       ├── stage4_vector_store.py   # Builds + uploads Azure AI Search documents
│       ├── stage5_graph.py          # Cosmos Gremlin chunk relationship graph
│       ├── stage6_status.py         # MongoDB document status updates
│       └── stage7_archive.py        # Moves processed blobs out of the ingestion path
│       # Flat, not a subpackage, and numbered by execution order — Azure's
│       # remote build pipeline was observed to intermittently corrupt nested
│       # subdirectories in the deployed package. See function_app.py's
│       # module docstring for details.
│
├── infrastructure/
│   └── terraform/                   # Provisions all Azure resources
│       ├── main.tf                  # Root module — wires all child modules
│       ├── variables.tf             # Input parameters (prefix, location, sizes)
│       ├── outputs.tf               # Exports → auto-generates .env after apply
│       └── modules/                 # container_apps, cosmos, search, openai,
│                                     #   storage, redis, functions, monitoring,
│                                     #   diagnostics
│
├── docs/
│   ├── adr/                         # 16 Architecture Decision Records
│   │   └── README.md                # ADR index
│   ├── CONTRIBUTING.md              # Development setup and workflow
│   └── RUNBOOK.md                   # Deployment and operations guide
│
├── tests/                           # Python backend tests (42 tests)
│   ├── conftest.py                  # Shared fixtures, Azure SDK mocks
│   ├── unit/                        # Service + pipeline unit tests
│   └── integration/api/             # FastAPI endpoint integration tests
│
├── scripts/
│   ├── setup.sh                     # One-time local setup
│   └── review_pr.py                 # OpenAI PR review script
│
├── .github/workflows/
│   ├── pr-review.yml                # Tests + lint + security + OpenAI review
│   ├── deploy.yml                   # Docker build → ACR → Container Apps rolling deploy
│   ├── terraform.yml                # Terraform plan/apply + GitHub secret sync
│   └── e2e.yml                      # Playwright E2E tests on every PR
│
├── presidio-service/                 # Standalone PII detection microservice
│   ├── main.py                      # FastAPI: /health /entities /analyze /anonymize /redact
│   └── Dockerfile                   # Multi-stage uv build — bakes in spaCy en_core_web_lg
│
├── docker-compose.yml               # Local dev: backend + frontend + Redis + Presidio
├── Dockerfile.backend               # Multi-stage uv build
├── Dockerfile.frontend              # Vite build → Nginx
├── pyproject.toml                   # Python deps (managed by uv)
├── .env.example                     # Template — copy to .env and fill in
└── README.md
```

---

## Quick Start (Local Development)

### Prerequisites

- Azure subscription (with Azure OpenAI access approved)
- `az` CLI, `terraform`, `uv`, Node.js v20+, Docker

### 1. Clone and set up

```bash
git clone https://github.com/m-ravin/kb_rag.git
cd kb_rag
bash scripts/setup.sh
```

### 2. Fill in Azure credentials

```bash
cp .env.example .env
# Edit .env with your Azure resource endpoints and API keys
```

### 3. Provision Azure infrastructure

```bash
cd infrastructure/terraform
terraform init
terraform apply                                      # ~15-20 min
terraform output -raw env_file_content >> ../../.env # auto-fill .env
```

### 4. Run locally with Docker Compose

```bash
docker-compose up
# Backend:  http://localhost:8000
# Frontend: http://localhost:3000
# API docs: http://localhost:8000/docs
```

### 5. Deploy to Azure Container Apps

Trigger the `deploy.yml` workflow (manual `workflow_dispatch`) — it handles the rest:
1. Builds Docker images (backend, frontend, presidio) → pushes to ACR
2. Sets Container App secrets from Key Vault values
3. Updates each Container App to the newly-built image

---

## Available Commands

<!-- AUTO-GENERATED from pyproject.toml and frontend/package.json -->

### Backend (from repo root)

| Command | Description |
|---------|-------------|
| `uv sync` | Install production dependencies |
| `uv sync --dev` | Install all dependencies including dev tools |
| `uv run uvicorn backend.main:app --reload` | Start backend dev server with hot reload |
| `uv run pytest` | Run full test suite |
| `uv run pytest --cov=backend --cov-report=term-missing` | Run tests with coverage report (80% minimum) |
| `uv run ruff check backend/` | Lint Python source |
| `uv run ruff format backend/` | Format Python source |
| `uv run mypy backend/` | Type check Python source |

### Frontend (from `frontend/`)

| Command | Description |
|---------|-------------|
| `npm run dev` | Start Vite dev server with hot reload (port 3000) |
| `npm run build` | Production build with TypeScript check |
| `npm run preview` | Preview production build locally (port 4173) |
| `npm run lint` | Run ESLint on TypeScript source |
| `npm run test:e2e` | Run Playwright E2E tests headless |
| `npm run test:e2e:ui` | Open Playwright interactive test UI |
| `npm run test:e2e:report` | Open last HTML test report |

### Infrastructure (from `infrastructure/terraform/`)

| Command | Description |
|---------|-------------|
| `terraform init` | Initialise providers and modules |
| `terraform plan` | Preview infrastructure changes |
| `terraform apply` | Provision or update Azure resources |
| `terraform destroy` | Tear down all resources (stops billing) |
| `terraform output -raw env_file_content` | Print generated .env content |

<!-- END AUTO-GENERATED -->

---

## API Reference

<!-- AUTO-GENERATED from backend/api/*/router.py -->

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/qa/ask` | — | Full RAG pipeline — submit a question, receive an answer with sources |
| `GET` | `/search/vector?q=` | — | Pure semantic vector search |
| `GET` | `/search/keyword?q=` | — | BM25 keyword search |
| `GET` | `/search/hybrid?q=` | — | Combined vector + keyword (Reciprocal Rank Fusion) |
| `GET` | `/search/graph?chunk_ids=` | — | Graph-based context expansion |
| `POST` | `/tasks/content-safety` | — | Check text for harmful content |
| `POST` | `/tasks/pii-detection` | — | Detect personally identifiable information |
| `POST` | `/tasks/question-understanding` | — | Classify question type + extract keywords |
| `POST` | `/tasks/question-type-detection` | — | Classify: faq / procedural / factual / comparison |
| `POST` | `/tasks/query-keyword-extraction` | — | Extract search keywords |
| `POST` | `/tasks/translation` | — | Translate to target language |
| `POST` | `/tasks/summarizer` | — | Summarise long text |
| `POST` | `/tasks/wording-tuning` | — | Adjust tone (professional / friendly / simple) |
| `POST` | `/tasks/message-template-parser` | — | Fill `{{variable}}` placeholders |
| `POST` | `/tasks/compliance-check` | — | Validate against content guidelines |
| `POST` | `/tasks/language-check` | — | Detect language (returns ISO 639-1 code) |
| `POST` | `/manage/auth/token` | — | Login — returns JWT access token |
| `POST` | `/manage/auth/register` | Admin | Create new CMS user (JSON body: `email`, `password` ≥12 chars, `role`) |
| `POST` | `/manage/documents/upload` | Admin/Editor | Upload a document (PDF/DOCX/PPTX) |
| `GET` | `/manage/documents` | Any auth | List all documents with pagination |
| `DELETE` | `/manage/documents/{id}` | Admin | Remove document — cascades to blob, search index, and graph |
| `GET` | `/manage/activity-logs` | Admin | CMS activity audit log |
| `GET` | `/manage/metrics` | Any auth | Q&A performance metrics |
| `GET` | `/health` | — | Liveness probe |
| `GET` | `/ready` | — | Readiness probe (checks Redis, when configured) |

Full interactive docs available at `http://localhost:8000/docs` when running.

<!-- END AUTO-GENERATED -->

---

## Environment Variables

<!-- AUTO-GENERATED from .env.example -->

### Required

| Variable | Description |
|----------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI resource endpoint URL |
| `AZURE_OPENAI_KEY` | Azure OpenAI API key |
| `AZURE_OPENAI_GPT_DEPLOYMENT` | GPT model deployment name (default: `gpt-5-mini`) — note: reasoning-family deployments reject a custom `temperature`, which `llm_service.py` accounts for |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Embedding model deployment name (default: `text-embedding-3-small`) |
| `AZURE_SEARCH_ENDPOINT` | Azure AI Search endpoint URL |
| `AZURE_SEARCH_KEY` | Azure AI Search API key |
| `COSMOS_MONGO_CONNECTION` | Cosmos DB MongoDB API connection string |
| `COSMOS_GREMLIN_ENDPOINT` | Cosmos DB Gremlin API WebSocket endpoint |
| `COSMOS_GREMLIN_KEY` | Cosmos DB primary key |
| `STORAGE_CONNECTION` | Azure Data Lake Storage Gen2 connection string |
| `JWT_SECRET` | Strong random string (≥32 chars) for signing JWT tokens — app refuses to start if unset |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `AZURE_OPENAI_API_VERSION` | `2024-08-01-preview` | OpenAI API version |
| `AZURE_SEARCH_INDEX_NAME` | `pil-documents` | Azure AI Search index name |
| `COSMOS_DB_NAME` | `pil-knowledge-base` | Cosmos MongoDB database name |
| `REDIS_CONNECTION` | — | Redis connection string (TLS, port 6380 in Azure) — only used for Q&A result caching; the app starts and runs fine without it |
| `STORAGE_CONTAINER_NAME` | `pil-documents` | ADLS container for uploaded files |
| `CONTENT_SAFETY_ENDPOINT` | — | Azure AI Content Safety endpoint (for harmful content checks) |
| `CONTENT_SAFETY_KEY` | — | Azure AI Content Safety key |
| `APPINSIGHTS_CONNECTION_STRING` | — | Application Insights connection string |
| `PRESIDIO_ENDPOINT` | `http://presidio-service:8080` | Presidio PII service URL — Docker Compose resolves via service name; override for external deployments |
| `ALLOWED_ORIGINS` | `["http://localhost:3000"]` | JSON array of permitted CORS origins — set to your frontend URL in production |
| `DEBUG` | `false` | Enable hot-reload and verbose logging |

<!-- END AUTO-GENERATED -->

---

## CI/CD Workflows

| Workflow | Trigger | Jobs |
|----------|---------|------|
| `pr-review.yml` | Every PR | Tests + Coverage, Linting, Security Scan, OpenAI Code Review |
| `e2e.yml` | Every PR | Playwright E2E (38 tests, Chromium + Firefox + Mobile) |
| `terraform.yml` | PR on `infrastructure/**` or manual dispatch | Terraform plan / apply / destroy |
| `deploy.yml` | Manual `workflow_dispatch` | Docker build → ACR, set Container App secrets from Key Vault, update backend/frontend/presidio Container Apps to the new image |

### Required GitHub Secrets

| Secret | Source |
|--------|--------|
| `AZURE_CREDENTIALS` | `az ad sp create-for-rbac --sdk-auth` |
| `ARM_CLIENT_ID` / `ARM_CLIENT_SECRET` / `ARM_SUBSCRIPTION_ID` / `ARM_TENANT_ID` | Service principal |
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) -> API Keys |
| `ACR_LOGIN_SERVER` / `ACR_USERNAME` / `ACR_PASSWORD` | Auto-set by `terraform.yml` after apply |
| `ACA_RESOURCE_GROUP` / `ACA_IDENTITY_ID` / `KEY_VAULT_URI` | Auto-set by `terraform.yml` after apply |
| `ACA_BACKEND_APP_NAME` / `ACA_FRONTEND_APP_NAME` / `ACA_PRESIDIO_APP_NAME` | Auto-set by `terraform.yml` after apply |
| `GH_PAT` | GitHub PAT with `repo` scope |

Also configurable — a repo **variable**, not a secret: `OPENAI_REVIEW_MODEL` (optional, defaults to `gpt-5-mini`) overrides which OpenAI model `pr-review.yml` uses for code review.

---

## Architecture Decision Records

Sixteen ADRs in [`docs/adr/`](docs/adr/) document all major technical choices with rejected alternatives and rationale, including the AKS → Container Apps migration (0013), reuse of existing dev-subscription resources (0014), and the document lifecycle/integrity design (0016). See [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) for development workflow and [`docs/RUNBOOK.md`](docs/RUNBOOK.md) for deployment procedures.

---

## Security

- PII detected with **Microsoft Presidio** (local NLP — data never leaves the machine) and masked with `[REDACTED]` before reaching the LLM or logs; custom recogniser for Malaysian NRIC
- Content safety screening via Azure AI Content Safety on every input
- Retrieved document chunks are wrapped in boundary tokens to prevent prompt injection
- CORS locked to explicit origin allowlist (`ALLOWED_ORIGINS`)
- `JWT_SECRET` has no default — app refuses to start without it
- No secrets in source code — all from Azure Key Vault via CSI driver
- JWT auth + RBAC (admin / editor / viewer) on all CMS endpoints

---

## Cost Estimate (Azure, dev tier)

| Resource | SKU | Est. monthly |
|---|---|---|
| Azure Container Apps (backend + frontend + presidio) | Consumption, scale-to-zero | ~$0–40 |
| Azure AI Search | Standard (1 replica) | ~$245 |
| Azure OpenAI | Pay-per-token | ~$50–200 |
| Cosmos DB (400 RU/s × 2) | Provisioned | ~$50 |
| Redis Cache | C1 Standard | ~$55 |
| Azure Functions | Consumption | ~$0–5 |
| Storage + Networking | Various | ~$20 |
| **Total (dev)** | | **~$420–615/month** |

This project also reuses several existing dev-subscription resources (Search, Storage, Key
Vault) rather than provisioning new ones — see
[`docs/adr/0014-reuse-existing-dev-subscription-resources.md`](docs/adr/0014-reuse-existing-dev-subscription-resources.md).
Actual cost depends on how much of that reuse applies to your subscription.

Run `terraform destroy` when not in active use to avoid idle charges.
