# ADR-0015: Key Vault Firewall IP Rules for the Function App Are Provisioned Manually, Not via Terraform

**Date**: 2026-07-29
**Status**: accepted
**Deciders**: KB RAG system design

## Context

`kv-dev-az1-dp` (resource group `rsg-dev-az1-dp`) is a pre-existing, shared Key Vault reused via `data "azurerm_key_vault" "main"` in root `main.tf` — per ADR-0014, this Terraform configuration deliberately does not own it as a managed resource, since other apps outside this project also depend on it.

During live debugging of `func-doc-proc-pil-dev63u6v3` (Linux Consumption plan Function App, `rg-pil-dev`), Key Vault reference app settings (`@Microsoft.KeyVault(...)`) failed to resolve for over an hour with `AccessToKeyVaultDenied`, despite:
- The Function App's system-assigned identity correctly holding the `Key Vault Secrets User` role on the vault (confirmed via `az role assignment list`)
- The vault's firewall already having `bypass: AzureServices` enabled (the generic "trusted Microsoft services" exception)

The actual cause: Linux **Consumption plan** Function Apps do not reliably resolve outbound Key Vault reference calls through the generic `AzureServices` bypass — that bypass covers certain first-party service-to-service paths, but Consumption-plan outbound traffic for this purpose exits through the app's own **outbound IP pool** and needs to be explicitly allow-listed on the vault's firewall `ipRules`. This is a known behavior gap for Consumption plan (not Premium/App Service Environment, which support VNet integration and private endpoints instead). Once all 20 IPs from `possibleOutboundIpAddresses` were added to the vault's firewall via individual `az keyvault network-rule add --ip-address <ip>/32` calls, Key Vault references resolved immediately.

## Decision

We do **not** manage these Key Vault firewall IP rules via Terraform. They are applied as a manual, one-time (per Function App identity) provisioning step using the Azure CLI, and that step — along with how to regenerate it — is documented here instead of in HCL.

This was a close call against Option A (manage the rules as Terraform-owned `azurerm_key_vault_network_rule` resources or an inline `network_acls` block), rejected for reasons below.

## Alternatives Considered

### Alternative 1: Manage the IP rules via a standalone `azurerm_key_vault_network_rule` resource
- **Pros**: Rules would be reproducible via `terraform apply`; diff-visible if someone removes one out-of-band.
- **Cons**: This resource type does not exist in the `hashicorp/azurerm` provider at the version pinned here (`~> 3.90`, see `providers.tf`) — network ACL management was consolidated into the `network_acls` block on the `azurerm_key_vault` resource itself well before 3.x. There is no separate "just add a rule" resource to attach to a vault referenced only via a `data` source.
- **Why not**: Doesn't exist for this provider version — not a real option.

### Alternative 2: Manage the IP rules via an inline `network_acls` block on a fully Terraform-owned `azurerm_key_vault` resource
- **Pros**: Fully declarative; `terraform plan` would show drift if firewall rules changed.
- **Cons**: `network_acls` is a block on `azurerm_key_vault` itself, not a separately attachable resource — using it requires importing the *entire* shared vault (`kv-dev-az1-dp`) into this project's Terraform state as a managed resource. `network_acls` in azurerm is a full-replace attribute: every `terraform apply` from this point on would assert the complete `ip_rules` set as this project's Terraform sees it, silently dropping any IP rules or virtual-network rules that other consumers of this shared vault add later for their own needs (this vault is explicitly documented in ADR-0014 as reused-not-owned, and other apps depend on it too). A missed rule from another team would get silently deleted on our next unrelated `apply`.
- **Why not**: The blast radius of importing and fully owning a shared external resource's network configuration — for the sake of Consumption plan's oddly-narrow bypass gap — is disproportionate. This is exactly the "would require importing/fully owning a shared resource other consumers depend on" case this decision explicitly wants to avoid.

### Alternative 3: Move the Function App to a Premium or Elastic Premium plan to get VNet integration + Private Endpoint instead of IP allow-listing
- **Pros**: Private Endpoint access is the architecturally "correct" long-term answer and sidesteps outbound-IP churn entirely.
- **Cons**: Premium plans bill continuously (no true scale-to-zero), which contradicts the personal-scale, pay-per-execution cost goal that led to choosing Consumption in the first place (see `modules/functions/main.tf`'s `Y1` SKU comment).
- **Why not**: Solves a real but rare failure mode (IP pool regeneration on app recreation, see below) at a cost disproportionate to a personal/dev-scale project. Worth revisiting if this ever moves toward production traffic.

## Consequences

### Positive
- No risk of a future `terraform apply` in this project silently clobbering other consumers' Key Vault network rules — the vault stays a `data` source only, matching ADR-0014's reuse posture.
- No need to import a shared, externally-owned resource into this project's state.

### Negative
- The firewall IP rules are **not reproducible via `terraform apply`**. If `kv-dev-az1-dp`'s firewall is ever reset (e.g., someone flips it back to default-deny and clears `ipRules`), Key Vault references will fail again with `AccessToKeyVaultDenied` and this manual step must be re-run — there is no automated drift detection for it.
- If the Function App is ever deleted and recreated (not just redeployed/restarted), its outbound IP pool **can change** (Azure allocates a fresh pool per Consumption plan app; it is stable across restarts and redeployments of the *same* app, but not guaranteed stable across a delete+recreate). The stale IPs left in the vault's `ipRules` become harmless clutter, and the new pool must be re-applied using the steps below.

### Risks
- **Silent staleness**: because this isn't Terraform-managed, nobody gets a `terraform plan` warning if these rules are missing or wrong. Mitigated by this ADR being the canonical place to look when Key Vault reference resolution fails on this specific app — the root `main.tf` role-assignment comment near `azurerm_role_assignment.functions_kv_secrets_user` also points at "check identity/network before assuming it's RBAC," and this ADR is the network-specific half of that checklist.

## How to Regenerate the IP List

1. Get the current outbound IP pool for the Function App:
   ```bash
   az functionapp show \
     --name func-doc-proc-pil-dev63u6v3 \
     --resource-group rg-pil-dev \
     --query possibleOutboundIpAddresses -o tsv
   ```
   This returns a comma-separated list (20 IPs as of 2026-07-29 for this app). Use `possibleOutboundIpAddresses`, not `outboundIpAddresses` — the former is the full pool the platform may ever use for this app (including addresses reserved for future scale-out), which is what needs to be allow-listed; the latter is only the currently-active subset.

2. Add each IP individually to the vault's firewall (the CLI does not accept a bulk comma-separated list for this command):
   ```bash
   for ip in $(az functionapp show \
     --name func-doc-proc-pil-dev63u6v3 \
     --resource-group rg-pil-dev \
     --query possibleOutboundIpAddresses -o tsv | tr ',' ' '); do
     az keyvault network-rule add \
       --name kv-dev-az1-dp \
       --resource-group rsg-dev-az1-dp \
       --ip-address "${ip}/32"
   done
   ```

3. Confirm the vault's firewall now allows the app's traffic and that a Key Vault reference (e.g. `AZURE_OPENAI_KEY` in the Function App's Configuration blade, or `az functionapp config appsettings list` showing a resolved value rather than a `#REF!`-style error) resolves successfully.

Re-run this whenever: the vault's firewall rules are reset, or the Function App is deleted and recreated (not merely redeployed).
