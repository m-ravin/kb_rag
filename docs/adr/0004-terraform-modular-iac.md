# ADR-0004: Terraform (Modular) for Infrastructure as Code

**Date**: 2026-05-07
**Status**: accepted
**Deciders**: KB RAG system design

## Context

The KB RAG system provisions 15 Azure resources across networking, compute, storage, AI, databases, and monitoring. These resources have interdependencies (AKS needs the VNet subnet; Key Vault needs resource IDs to store secrets; the Function App needs the Storage Account key). The infrastructure must be reproducible across dev, staging, and prod environments with different sizing parameters, and CI/CD must be able to plan and apply changes automatically.

## Decision

We use **Terraform with a modular structure** (`infrastructure/terraform/`). Each Azure resource type lives in its own child module under `modules/` (aks, cosmos, search, openai, storage, redis, functions, monitoring, networking, apim). The root `main.tf` wires modules together and stores all sensitive outputs in Azure Key Vault. Environment differences are expressed through `variables.tf` with defaults for dev. CI/CD uses GitHub Actions (`terraform.yml`) for plan-on-PR and apply-on-dispatch.

## Alternatives Considered

### Alternative 1: Azure Bicep
- **Pros**: Azure-native language; first-class Azure Portal integration; no state file management; Microsoft officially supported; some resources have better Bicep coverage than Terraform providers
- **Cons**: Azure-only — skills and patterns don't transfer to multi-cloud; smaller community and fewer modules in public registries; IDE tooling is maturing but behind Terraform; no equivalent of `terraform plan` dry-run as clean CI output
- **Why not**: Terraform's provider ecosystem, community module library, and multi-cloud portability make it the stronger long-term investment. If the organisation already uses Terraform for other infrastructure, adding Bicep creates a dual-IaC maintenance burden.

### Alternative 2: Pulumi (Python)
- **Pros**: Write infrastructure in Python — same language as the application; full programming language features (loops, conditionals, functions); strong typing; can share utility code between infra and app
- **Cons**: Smaller community than Terraform; Azure provider lags behind the official Terraform AzureRM provider in coverage; state backend requires Pulumi Cloud or self-hosted; debugging stack traces is harder than Terraform's declarative plan output
- **Why not**: The team's existing IaC knowledge is in Terraform. Pulumi's Python approach is compelling but introduces a steeper learning curve for operators who know HCL, and the Azure provider coverage gap creates risk for some resources (e.g., AKS Key Vault CSI integration).

### Alternative 3: ARM Templates / Azure Resource Manager
- **Pros**: Zero abstraction — directly maps to Azure APIs; guaranteed feature parity on day 0 for new Azure services; no extra tooling to install
- **Cons**: JSON/BICEP ARM syntax is verbose and hard to read; no native module system; drift detection requires comparing live state against templates manually; no plan preview before apply
- **Why not**: ARM templates are effectively superseded by Bicep for Azure-native teams, and by Terraform for teams that value portability. The JSON verbosity alone makes maintenance error-prone at 15+ resources.

## Consequences

### Positive
- `terraform plan` in CI PRs gives reviewers a diff of infrastructure changes before merge — no surprise resource modifications
- `terraform output -raw env_file_content` auto-generates `.env` after apply, reducing human error in secret distribution
- Modular structure means a new environment (e.g., `prod`) is a new `terraform.tfvars` file, not a copy-paste of all resources
- State stored in Azure Blob (when enabled) is shared across the team, preventing concurrent apply conflicts

### Negative
- Terraform state file contains sensitive values (connection strings) — must use remote state with encryption at rest, not local `terraform.tfstate`
- Provider version pinning (`~> 3.90`) requires periodic upgrades to stay current with new Azure features
- Terraform's eventual consistency with Azure APIs sometimes requires `terraform apply` to be run twice for resources with circular dependencies (rare but documented in `README.md`)

### Risks
- **State file corruption**: Simultaneous `terraform apply` runs corrupt the state file. Mitigation: enable state locking via the Azure Blob backend (DynamoDB-equivalent locking is built into the AzureRM backend).
- **Resource deletion on rename**: Renaming a Terraform resource block destroys and recreates it. Mitigation: use `terraform state mv` before renaming; `prevent_destroy` lifecycle flag on production databases.
