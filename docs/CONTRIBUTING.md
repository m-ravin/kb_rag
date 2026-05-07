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

# 3. Install backend dependencies
uv sync --dev

# 4. Install frontend dependencies
cd frontend && npm install && cd ..

# 5. Start local stack (Redis runs in Docker; backend + frontend hot-reload)
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
| `npm run build` | Production build |
| `npm run lint` | ESLint |
| `npm run test:e2e` | Playwright E2E headless |
| `npm run test:e2e:ui` | Playwright interactive UI |

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
python tests/unit/pipeline/test_chunker.py  # 14 tests
```

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
- [ ] No hardcoded secrets, PIL-specific language, or `print()` statements
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
