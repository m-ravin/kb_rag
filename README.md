# kb-rag RAG System

An end-to-end **Retrieval-Augmented Generation (RAG)** system for Patient Information Leaflets (PILs), deployed on Microsoft Azure. Users can ask natural language questions and receive accurate, source-cited answers drawn directly from pharmaceutical documentation.

---

## What This System Does

1. A user **uploads a document** (PDF/DOCX/PPTX) through the CMS web interface.
2. An **Azure Function automatically wakes up**, reads the document, splits it into chunks, converts each chunk to a vector (embedding), and stores everything in three databases.
3. When a user **asks a question** via the API or chat UI:
   - The question is checked for PII and unsafe content
   - The question type is classified (FAQ / procedural / factual)
   - A hybrid search finds the most relevant document chunks
   - GPT-4o reads those chunks and writes a clear, compliant answer
   - The answer is tuned, language-detected, logged, and returned

---

## Architecture Diagram

```
User Question
     │
     ▼
[API Management]  ← rate limiting, auth gateway
     │
     ▼
[Q&A Flow API]  (FastAPI on AKS)
  ├─ Content Safety check  →  [Azure AI Content Safety]
  ├─ PII Detection         →  [Azure AI Language]
  ├─ Question Type         →  [GPT-4o]
  ├─ Keyword Extraction    →  [GPT-4o]
  ├─ Hybrid Search         →  [Azure AI Search] + [Cosmos Gremlin]
  │                             ↑ vectors from [Azure OpenAI Embeddings]
  ├─ Answer Generation     →  [GPT-4o]
  ├─ Wording Tuning        →  [GPT-4o]
  ├─ Compliance Check      →  [GPT-4o]
  └─ Logging               →  [Cosmos MongoDB]
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
  ├─ Embed chunks  →  [Azure OpenAI Embeddings]
  ├─ Index chunks  →  [Azure AI Search]
  └─ Build graph   →  [Cosmos Gremlin]
```

---

## Azure Resources — What Each One Does

> Written so a 10-year-old can understand it too.

| # | Azure Resource | What it does (technical) | Explain like I'm 5 |
|---|---|---|---|
| 1 | **Azure Kubernetes Service (AKS)** | Hosts the FastAPI backend and React frontend as containers, auto-scales under load | The apartment building where all your apps live. More people come → more apartments open automatically. |
| 2 | **Azure AI Search** | Vector DB storing document chunks; supports semantic (vector) + keyword (BM25) + hybrid search | The super-fast librarian who has memorised every sentence in every book and can find the one you need in milliseconds. |
| 3 | **Azure OpenAI (GPT-4o)** | Generates answers, classifies questions, tunes wording, checks compliance | The clever student who reads the relevant book pages and writes a clear answer to your question. |
| 4 | **Azure OpenAI (Embeddings)** | Converts text to 1536-dimension vectors for semantic search | The translator that turns words into numbers so the librarian can compare meanings, not just spellings. |
| 5 | **Azure Cosmos DB — MongoDB API** | Stores document metadata, user accounts, Q&A logs, activity logs | The filing cabinet. Holds the cover page of every document, who uploaded it, and a record of every question ever asked. |
| 6 | **Azure Cosmos DB — Gremlin API** | Graph DB storing chunk-to-chunk relationships (next/previous, same-section edges) | A map connecting all the book pages to show which ones sit next to each other or talk about the same topic. |
| 7 | **Azure Data Lake Storage Gen 2** | Persistent object storage for raw documents (PDF/DOCX/PPTX); hierarchical namespace | A giant USB drive in the sky that holds every original document uploaded, forever. |
| 8 | **Azure Cache for Redis** | In-memory cache for search results and embeddings (5-minute TTL) | Post-it notes stuck to the wall. If someone already asked the same question recently, just read the Post-it instead of doing all the work again. |
| 9 | **Azure Functions** | Serverless compute triggered by blob uploads; runs the document processing pipeline | Little robots that sleep until a new document arrives, then wake up and process it automatically — you don't pay for them when they're sleeping. |
| 10 | **Azure Data Factory** | Orchestrates multi-step data pipelines (document ingestion + reporting pipelines) | The assembly line foreman who tells each robot what to do and in what order. |
| 11 | **Azure Key Vault** | Stores all secrets (API keys, connection strings) securely; accessed via managed identities | A locked safe that only authorised people can open. No passwords are written in the code — they're always fetched from the safe. |
| 12 | **Azure API Management** | Rate limiting, API versioning, developer portal, request transformation | The front-desk receptionist who controls who gets to talk to the system, how many times per minute, and logs every visit. |
| 13 | **Azure Container Registry (ACR)** | Private Docker image registry for backend and frontend images | A private warehouse where we store the packaged versions of our apps before deploying them. |
| 14 | **Azure Monitor + App Insights** | Collects logs, traces, metrics from all services; powers dashboards | Security cameras and health monitors watching every part of the system, alerting when something goes wrong. |
| 15 | **Azure AI Content Safety** | Detects hate speech, violence, self-harm, sexual content in inputs/outputs | A school internet filter that blocks harmful content before it enters or leaves the system. |

---

## Repository Structure

```
kb_rag/
├── backend/                          # FastAPI Python backend
│   ├── main.py                       # App entry point — registers all routes
│   ├── core/
│   │   ├── config.py                 # All settings from env vars
│   │   ├── clients.py                # Singleton Azure SDK clients
│   │   └── auth.py                   # JWT auth + role-based access
│   ├── api/
│   │   ├── qa_flow/router.py         # POST /qa/ask — full RAG pipeline
│   │   ├── task_apis/router.py       # POST /tasks/* — individual AI tasks
│   │   ├── search_apis/router.py     # GET /search/* — all 4 search modes
│   │   └── management/router.py     # /manage/* — CMS + monitoring
│   ├── services/
│   │   ├── search_service.py         # Vector / keyword / graph / hybrid search
│   │   ├── llm_service.py            # All GPT-4o prompts
│   │   ├── safety_service.py         # PII detection + content safety
│   │   └── monitoring_service.py     # Q&A logging + metrics aggregation
│   └── pipeline/
│       └── indexer.py                # Azure AI Search index schema management
│
├── frontend/                         # React + TypeScript CMS
│   └── src/
│       ├── pages/
│       │   ├── Login.tsx             # JWT login form
│       │   ├── Dashboard.tsx         # Metrics charts (Recharts)
│       │   ├── Documents.tsx         # Upload + manage PIL documents
│       │   └── QATest.tsx            # Live Q&A test console
│       ├── components/Layout.tsx     # Sidebar navigation shell
│       └── api/client.ts            # Typed Axios API client
│
├── azure-functions/
│   └── document_processor/
│       └── function.py              # Blob-triggered: extract→chunk→embed→index
│
├── infrastructure/
│   ├── terraform/                   # Provisions all 15 Azure resources
│   │   ├── main.tf                  # Root module — wires all child modules
│   │   ├── variables.tf             # Input parameters
│   │   ├── outputs.tf               # Exports connection strings → .env
│   │   └── modules/                 # One module per Azure resource type
│   └── kubernetes/                  # K8s manifests for AKS deployment
│
├── .github/workflows/
│   ├── deploy.yml                   # Build Docker images → push ACR → deploy AKS
│   └── terraform.yml                # terraform plan/apply on PR
│
├── docker-compose.yml               # Local dev: backend + frontend + Redis
├── Dockerfile.backend               # Multi-stage Python build with uv
├── Dockerfile.frontend              # React build → Nginx serve
├── pyproject.toml                   # Python deps managed by uv
└── .env.example                     # Template — copy to .env and fill in
```

---

## Quick Start (Local Development)

### Prerequisites
- Azure subscription (with Azure OpenAI access approved)
- `az` CLI, `terraform`, `kubectl`, `uv`, `node` v20+, `docker`

### 1. Clone and set up
```bash
git clone https://github.com/YOUR_ORG/kb_rag.git
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
terraform apply          # Takes ~15-20 minutes for full stack
terraform output -raw env_file_content >> ../../.env  # Auto-fill .env
```

### 4. Run locally with Docker Compose
```bash
docker-compose up
# Backend: http://localhost:8000
# Frontend: http://localhost:3000
# API docs: http://localhost:8000/docs
```

### 5. Deploy to AKS
Push to `main` branch — the GitHub Actions workflow handles the rest:
- Builds and pushes Docker images to ACR
- Applies Kubernetes manifests
- Performs rolling deployment with health checks

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| POST | `/qa/ask` | Full RAG pipeline — submit a question, get an answer |
| GET | `/search/vector?q=...` | Pure semantic vector search |
| GET | `/search/keyword?q=...` | BM25 keyword search |
| GET | `/search/hybrid?q=...` | Combined vector + keyword (best for Q&A) |
| GET | `/search/graph?chunk_ids=...` | Graph-based context expansion |
| POST | `/tasks/content-safety` | Check text for harmful content |
| POST | `/tasks/pii-detection` | Detect personal information |
| POST | `/tasks/summarizer` | Summarise long text |
| POST | `/tasks/translation` | Translate to target language |
| POST | `/tasks/wording-tuning` | Adjust tone (professional/friendly/simple) |
| POST | `/manage/documents/upload` | Upload a PIL document |
| GET | `/manage/documents` | List all documents with status |
| GET | `/manage/metrics` | Q&A monitoring metrics |
| POST | `/manage/auth/token` | Login — returns JWT |

Full interactive documentation available at `/docs` (Swagger UI) when running.

---

## GitHub Actions Secrets Required

| Secret | Where to get it |
|---|---|
| `AZURE_CREDENTIALS` | `az ad sp create-for-rbac --sdk-auth` |
| `ARM_CLIENT_ID` | From the service principal above |
| `ARM_CLIENT_SECRET` | From the service principal above |
| `ARM_SUBSCRIPTION_ID` | `az account show --query id` |
| `ARM_TENANT_ID` | `az account show --query tenantId` |
| `ACR_LOGIN_SERVER` | Terraform output: `acr_login_server` |
| `ACR_USERNAME` | ACR admin username |
| `ACR_PASSWORD` | ACR admin password |
| `AKS_CLUSTER_NAME` | Terraform output: `aks_cluster_name` |
| `AKS_RESOURCE_GROUP` | Terraform output: `resource_group_name` |

---

## Cost Estimate (Azure, East US, dev tier)

| Resource | SKU | Est. monthly cost |
|---|---|---|
| AKS (2x D4s_v3 nodes) | Standard | ~$280 |
| Azure AI Search | Standard (1 replica) | ~$245 |
| Azure OpenAI | Pay-per-token | ~$50–200 depending on usage |
| Cosmos DB (400 RU/s × 2) | Provisioned | ~$50 |
| Redis Cache | C1 Standard | ~$55 |
| Azure Functions | Consumption | ~$0–5 |
| Storage + Networking | Various | ~$20 |
| **Total (dev)** | | **~$700–850/month** |

> Run `terraform destroy` when not actively using the system to avoid idle charges.

---

## Security Checklist

- [x] No secrets in source code — all from Azure Key Vault
- [x] PII detection on every user question
- [x] Content safety screening on input and output
- [x] JWT auth on all CMS endpoints
- [x] Role-based access: admin / editor / viewer
- [x] Redis cache uses TLS (SSL port 6380)
- [x] AKS uses managed identity (no stored credentials)
- [x] CORS configured (tighten origins in production)
- [x] Input validation via Pydantic on all endpoints
