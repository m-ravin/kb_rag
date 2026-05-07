# Architecture Decision Records

This directory contains the architectural decisions made for the **KB RAG** system.
Each ADR explains *what* was decided, *why*, and what alternatives were rejected.

> **Adding a new ADR?** Copy `template.md`, increment the number, and add a row below.

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| [0001](0001-multi-database-strategy.md) | Multi-database strategy: Cosmos MongoDB + Gremlin + Azure AI Search | accepted | 2026-05-07 |
| [0002](0002-hybrid-search-approach.md) | Hybrid search: Vector + Keyword + Graph with Redis cache | accepted | 2026-05-07 |
| [0003](0003-azure-functions-document-processing.md) | Azure Functions for blob-triggered document processing | accepted | 2026-05-07 |
| [0004](0004-terraform-modular-iac.md) | Terraform (modular) for Infrastructure as Code | accepted | 2026-05-07 |
| [0005](0005-uv-python-package-management.md) | uv for Python package management | accepted | 2026-05-07 |
| [0006](0006-jwt-rbac-cms-auth.md) | JWT + role-based access control for CMS authentication | accepted | 2026-05-07 |
| [0007](0007-tdd-80-percent-coverage.md) | TDD workflow with 80% coverage threshold enforced by CI | accepted | 2026-05-07 |
