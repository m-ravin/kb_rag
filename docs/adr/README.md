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
| [0008](0008-llm-gateway.md) | LLM gateway — direct Azure OpenAI v1, LiteLLM sidecar planned for v2 | accepted | 2026-05-07 |
| [0009](0009-accuracy-evaluation.md) | LLM accuracy evaluation — RAGAS framework deferred to v2 (gap acknowledged) | proposed | 2026-05-07 |
| [0010](0010-presidio-pii-microservice.md) | Presidio PII detection — standalone microservice instead of in-process library | accepted | 2026-05-11 |
| [0011](0011-pii-fail-closed-policy.md) | PII fail-closed policy — block Q&A on Presidio outage rather than pass raw PII | accepted | 2026-05-11 |
| [0012](0012-security-hardening.md) | Security hardening — rate limiting, auth scope, JWT hardening, upload validation | accepted | 2026-05-11 |
| [0013](0013-container-apps-over-aks-apim.md) | Azure Container Apps replaces AKS + API Management | accepted | 2026-07-21 |
| [0014](0014-reuse-existing-dev-subscription-resources.md) | Reuse pre-provisioned resources from the dev subscription where compatible | accepted | 2026-07-21 |
| [0015](0015-key-vault-firewall-ip-rules-manual.md) | Key Vault firewall IP rules for the Function App are provisioned manually, not via Terraform | accepted | 2026-07-29 |
| [0016](0016-document-lifecycle-and-data-integrity.md) | Document identity, deletion lifecycle, and data integrity — content-addressed ids, soft-delete/purge, reconciliation, alerting | accepted | 2026-07-30 |
