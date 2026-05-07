# ADR-0005: uv for Python Package Management

**Date**: 2026-05-07
**Status**: accepted
**Deciders**: KB RAG system design

## Context

The KB RAG backend has 20+ Python dependencies spanning Azure SDKs, async frameworks, document parsers, and database drivers. These packages must be installed reproducibly across developer machines, CI runners, and Docker containers. Python package management has historically been a pain point: `pip` is slow, `requirements.txt` has no lockfile semantics, and virtual environment setup is error-prone. The project uses Python 3.11+ and needs both production and dev dependency groups.

## Decision

We use **`uv`** (from Astral) for all Python package management. Dependencies are declared in `pyproject.toml` under `[project.dependencies]` and `[project.optional-dependencies]`. The lockfile `uv.lock` is committed to the repository. All install commands in `Dockerfile.backend`, `scripts/setup.sh`, and `README.md` use `uv sync` and `uv run`. The `ghcr.io/astral-sh/uv` Docker image provides `uv` in multi-stage builds without a separate install step.

## Alternatives Considered

### Alternative 1: pip + requirements.txt
- **Pros**: Ships with Python; universally understood; no extra tooling to install; every tutorial and blog post uses it
- **Cons**: `requirements.txt` has no native dependency groups (prod vs dev); no lockfile — `pip install -r requirements.txt` can install different versions on different days depending on PyPI resolver state; `pip install` is slow (10–30 seconds for this project's dependency tree)
- **Why not**: Reproducibility is non-negotiable for a production system. `requirements.txt` without pinning every transitive dependency (which is unmaintainable) cannot guarantee identical installs across environments. `uv.lock` solves this automatically.

### Alternative 2: Poetry
- **Pros**: Well-established; `pyproject.toml`-native; virtual environment management built in; good monorepo support via workspaces; large community
- **Cons**: Poetry's resolver is written in Python and is slow (30–90 seconds for complex dependency trees); Poetry's lockfile format (`poetry.lock`) is Poetry-specific and cannot be used by pip; Poetry's dependency groups are not PEP 735 compliant
- **Why not**: `uv` installs the same 20+ packages in ~2 seconds vs Poetry's ~45 seconds. For a CI pipeline that runs on every PR, this compounds to significant time savings. `uv`'s lockfile format is compatible with standard `pyproject.toml`.

### Alternative 3: conda / mamba
- **Pros**: Handles non-Python dependencies (CUDA, MKL); standard in data science; environment isolation at OS level
- **Cons**: Overkill for a web API project with no GPU dependencies; `conda` environments are large and slow to create; conda channels are separate from PyPI and can have outdated packages; not well-suited for Docker-based deployments
- **Why not**: The KB RAG system uses Azure OpenAI for all LLM/embedding work — no local GPU dependencies exist. Conda's benefits don't apply here, and its overhead is unnecessary.

## Consequences

### Positive
- `uv sync --frozen` in Docker ensures byte-for-byte identical installs in every container (no "works on my machine" dependency drift)
- `uv add <package>` automatically updates both `pyproject.toml` and `uv.lock` atomically — no manual step to forget
- Cold install of all 20+ packages takes ~3 seconds locally, ~8 seconds in CI (vs ~45s with Poetry, ~30s with pip)
- `uv run pytest` runs tests in the correct virtualenv without `source .venv/bin/activate`
- Docker multi-stage build uses `ghcr.io/astral-sh/uv:python3.11-bookworm-slim` — no separate `pip install uv` step

### Negative
- `uv` is a newer tool (first stable release 2024); team members unfamiliar with it need a short orientation
- `uv.lock` format is Astral-specific; switching away from `uv` in future requires converting the lockfile (though `pyproject.toml` remains standard)
- Some legacy Azure SDK installation patterns using `pip install -e .` need adjustment for `uv`

### Risks
- **uv project maturity**: Astral is well-funded and `uv` has rapid adoption (used by FastAPI, Pydantic, and other major Python projects). Risk of abandonment is low. Mitigation: `pyproject.toml` is a standard format — migrating to Poetry or pip is straightforward if needed.
