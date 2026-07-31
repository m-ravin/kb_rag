# ADR-0014: Reuse Pre-Provisioned Resources from the Dev Subscription Where Compatible

**Date**: 2026-07-21
**Status**: accepted
**Deciders**: KB RAG system design

## Context

Deployment moved to a different Azure subscription ("Azure Dev subscription", `af7a7908-9432-4a21-959f-96d97c7cfacb`) than originally planned. That subscription already contains a resource group, `rsg-dev-az1-dp`, with an Azure AI Foundry-style project already provisioned: an Azure AI Search service (Free tier), a Cosmos DB account, two Storage accounts, a Key Vault, a Cognitive Services "AIServices" account, and a managed Foundry workspace resource group. This was confirmed to be intended for this project rather than unrelated infrastructure. Reusing existing resources avoids paying for and managing duplicates, but not every existing resource is actually compatible with what `ai-pil-rag` needs.

## Decision

We reuse three of the existing resources as-is via Terraform `data` sources instead of creating new ones: **Azure AI Search** (`srch-dev-az1-dp`, already Free tier — matches ADR's own free-tier cost goal exactly), the **HNS-enabled Storage account** (`stdevaz1dp001`, already Data Lake Gen2), and **Key Vault** (`kv-dev-az1-dp`). We do **not** reuse the existing Cosmos DB account or the existing AIServices Cognitive Services account — both are provisioned fresh, for reasons below. New resources (Cosmos, Container Apps, ACR, Functions, Redis, Monitoring, OpenAI+Content Safety) are placed in a **separate new resource group** (`rg-pil-dev`) rather than inside `rsg-dev-az1-dp`, so a future `terraform destroy` for this project can never affect the Foundry hub, managed workspace, or anything else already living in that group.

## Alternatives Considered

### Alternative 1: Reuse the existing Cosmos DB account
- **Pros**: One fewer resource to provision; avoids a second Cosmos bill
- **Cons**: The existing account (`cosmos-dev-az1-dp`) has no `EnableMongo` or `EnableGremlin` capabilities — it's a plain Core (SQL) API account. Cosmos DB API capabilities are set at account creation and are immutable afterward; there is no migration path to add Mongo/Gremlin support to an existing SQL API account.
- **Why not**: Structurally incompatible with ADR-0001 (multi-database strategy) and ADR-0002 (hybrid search approach), both of which depend on MongoDB API (document metadata) and Gremlin API (chunk relationship graph) on the same account. Adopting the existing account would require redesigning those two ADRs and rewriting the `pymongo`/`gremlin_python` data-access code to target the Cosmos SQL SDK instead, and reimplementing graph relationships without a native graph API. Rejected as disproportionate to the benefit of not paying for a second (free-tier-eligible) Cosmos account.

### Alternative 2: Reuse the existing AIServices Cognitive Services account for OpenAI + Content Safety
- **Pros**: One fewer Cognitive Services resource; the account already exists with a custom subdomain configured
- **Cons**: It's in `centralindia`, and a live check (`az cognitiveservices account list-models`) confirmed neither `gpt-4o` nor `text-embedding-3-small` are deployable on this account in this region — same regional limitation documented in ADR-0013's predecessor discussion, independent of account `kind` (OpenAI vs. AIServices draws from the same regional model catalog).
- **Why not**: The account cannot serve its core purpose where it is. A new Cognitive Services resource in `southeastasia` is required regardless of reuse intent.

### Alternative 3: Put all new resources inside rsg-dev-az1-dp instead of a separate resource group
- **Pros**: Single resource group for the whole project; simpler mental model
- **Cons**: `rsg-dev-az1-dp` also contains an Azure AI Foundry hub and its auto-managed workspace resource group, which are unrelated to this application. A resource-group-scoped `terraform destroy` (or accidental `terraform state rm` mistakes) would carry meaningfully higher blast radius.
- **Why not**: Isolating new, Terraform-owned resources into their own resource group is a standard safety practice when co-existing with resources Terraform doesn't manage. The three reused resources are still referenced cross-resource-group via `data` sources — Azure resources can reference resources in a different resource group (and even a different region) within the same subscription without issue.

## Consequences

### Positive
- Avoids duplicate Search and Storage costs (both already Free/Standard-LRS, matching the personal-budget goal from ADR-0013)
- `terraform destroy` for this project is scoped to `rg-pil-dev` only — the Foundry hub, managed workspace, and existing AIServices/Cosmos resources in `rsg-dev-az1-dp` are structurally unreachable by it
- Resource identity mismatches (Cosmos API type, OpenAI region) were caught and resolved before any `terraform apply`, not discovered mid-deployment

### Negative
- Two resource groups to reason about instead of one; `docs/RUNBOOK.md` needs updating to reflect where each resource actually lives
- The identity running `terraform apply` needs a manually-granted RBAC role (`Key Vault Secrets Officer` or equivalent) on `kv-dev-az1-dp` before the first `apply` can create secrets — Terraform cannot grant itself that initial permission, since `kv-dev-az1-dp` uses Azure RBAC authorization (not legacy access policies), confirmed via `az keyvault show`
- If `rsg-dev-az1-dp`'s owner ever deletes or renames the reused resources outside this project's awareness, the next `terraform plan` will fail loudly (data source not found) rather than silently recreating them — acceptable fail-safe behavior, but worth knowing when debugging a sudden plan failure

### Risks
- **Cross-RG/cross-region secret sprawl**: secrets for resources in three different scopes (rg-pil-dev/centralindia, rg-pil-dev/southeastasia, rsg-dev-az1-dp/centralindia) all land in one Key Vault. Mitigated by consistent secret naming already established in `main.tf`.
- **Permission drift**: if the RBAC role granted to the Terraform-running identity on `kv-dev-az1-dp` is ever revoked, applies will fail with a clear `Forbidden` error (already observed once during setup) rather than a confusing one — low risk once initially resolved.
