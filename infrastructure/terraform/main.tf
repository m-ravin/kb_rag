locals {
  name_suffix = "${var.prefix}-${var.environment}"
}

resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

# New resources for this project live here — kept separate from the existing
# rsg-dev-az1-dp resource group so `terraform destroy` can never touch anything
# else living there. See docs/adr/0014-reuse-existing-dev-subscription-resources.md.
resource "azurerm_resource_group" "main" {
  name     = "rg-${local.name_suffix}"
  location = var.location
  tags     = var.tags
}

# ── Azure AI Search (reused, existing free-tier service) ─────────────────────
module "search" {
  source                       = "./modules/search"
  existing_name                = var.existing_search_name
  existing_resource_group_name = var.existing_resource_group_name
}

# ── Cosmos DB (MongoDB + Gremlin) — new, existing account is SQL API only ────
module "cosmos" {
  source              = "./modules/cosmos"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  name_suffix         = "${local.name_suffix}${random_string.suffix.result}"
  throughput          = var.cosmos_throughput
  tags                = var.tags
}

# ── Azure OpenAI (LLM + Embeddings + Safety) — new, existing AIServices ──────
# account can't deploy these models in centralindia (same reason as var.location
# vs var.openai_location generally: region doesn't support gpt-4o/embedding-3-small).
module "openai" {
  source              = "./modules/openai"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.openai_location
  name_suffix         = "${local.name_suffix}${random_string.suffix.result}"
  gpt_model           = var.openai_gpt_model
  embedding_model     = var.openai_embedding_model
  tags                = var.tags
}

# ── Azure Data Lake Storage Gen2 (reused, existing HNS-enabled account) ──────
module "storage" {
  source                       = "./modules/storage"
  existing_name                = var.existing_storage_account_name
  existing_resource_group_name = var.existing_resource_group_name
}

# ── Azure Cache for Redis (intermediate result cache) ─────────────────────────
module "redis" {
  source              = "./modules/redis"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  name_suffix         = local.name_suffix
  capacity            = var.redis_capacity
  tags                = var.tags
}

# ── Azure Functions (document processing tasks) ───────────────────────────────
module "functions" {
  source               = "./modules/functions"
  resource_group_name  = azurerm_resource_group.main.name
  location             = var.location
  name_suffix          = "${local.name_suffix}${random_string.suffix.result}"
  storage_account_name = module.storage.storage_account_name
  storage_account_key  = module.storage.storage_account_key
  key_vault_uri        = data.azurerm_key_vault.main.vault_uri
  tags                 = var.tags
}

# ── Azure Monitor + App Insights ──────────────────────────────────────────────
module "monitoring" {
  source              = "./modules/monitoring"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  name_suffix         = local.name_suffix
  tags                = var.tags
}

# ── Container Apps (hosts backend + CMS frontend + presidio-service) ─────────
# Replaces AKS + API Management: Consumption plan scales to zero, and rate
# limiting is handled in-app via backend/core/limiter.py instead of an APIM policy.
module "container_apps" {
  source                     = "./modules/container_apps"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = var.location
  name_suffix                = "${local.name_suffix}${random_string.suffix.result}"
  log_analytics_workspace_id = module.monitoring.log_analytics_workspace_id
  tags                       = var.tags
}

# ── Diagnostic settings — routes platform logs to Log Analytics ──────────────
# See modules/diagnostics/main.tf for why this exists (an audit found zero
# resources had this configured) and what's deliberately out of scope.
module "diagnostics" {
  source                     = "./modules/diagnostics"
  log_analytics_workspace_id = module.monitoring.log_analytics_workspace_id
  # Built from the resource group + known naming pattern rather than
  # module.functions.function_app_id — referencing that output pulls the
  # whole azurerm_linux_function_app resource into this apply's graph, and
  # it currently has unrelated pre-existing site_config drift (found while
  # wiring this up; flagged separately, not fixed here). This id string
  # resolves to the identical resource without that side effect.
  function_app_id    = "${azurerm_resource_group.main.id}/providers/Microsoft.Web/sites/func-doc-proc-${local.name_suffix}${random_string.suffix.result}"
  storage_account_id = module.storage.storage_account_id
  key_vault_id       = data.azurerm_key_vault.main.id
  search_service_id  = module.search.id
  cosmos_mongo_id    = "${azurerm_resource_group.main.id}/providers/Microsoft.DocumentDB/mongoClusters/cs-dev-az1-mongo"
  cosmos_gremlin_id  = "${azurerm_resource_group.main.id}/providers/Microsoft.DocumentDb/databaseAccounts/cs-dev-az1-gremlin"
}

data "azurerm_client_config" "current" {}

# ── Key Vault (reused, existing RBAC-authorization vault) ─────────────────────
# kv-dev-az1-dp uses Azure RBAC authorization (not legacy access policies), so
# granting access means role assignments, not access_policy blocks.
# NOTE: the identity running `terraform apply` (you) must already hold a role
# with secret write permission (e.g. "Key Vault Secrets Officer") on this vault
# BEFORE the secret resources below can be created — Terraform can't grant
# itself that first grant. Grant it manually once in the Azure Portal.
data "azurerm_key_vault" "main" {
  name                = var.existing_key_vault_name
  resource_group_name = var.existing_resource_group_name
}

# Container Apps' shared identity reads secrets at runtime
resource "azurerm_role_assignment" "container_apps_kv_secrets_user" {
  scope                = data.azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = module.container_apps.identity_principal_id
}

# The ingestion Function App's own system-assigned identity reads secrets at runtime
#
# DRIFT FOOTGUN (observed 2026-07-29): azurerm_role_assignment binds to a
# principal_id captured at apply time. Any operation that regenerates the
# Function App's SystemAssigned identity (e.g. recreating the app, or certain
# identity-toggle sequences) changes the live principalId, but this resource
# can't update principal_id in place — Terraform's cached state can keep
# pointing at a stale, now-unauthorized identity, and `terraform plan` won't
# even show the drift until a `terraform refresh` picks up the live identity
# first. Symptom looks exactly like a Key Vault network/firewall problem
# (AccessToKeyVaultDenied) even though RBAC "looks" correctly assigned. If Key
# Vault references start failing again, compare
# `az functionapp identity show --name <app> --resource-group <rg> --query principalId`
# against this role assignment's actual principal_id in state before assuming
# it's a network/config issue.
resource "azurerm_role_assignment" "functions_kv_secrets_user" {
  scope                = data.azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = module.functions.function_app_principal_id
}

# ── Store all secrets in Key Vault ────────────────────────────────────────────
resource "azurerm_key_vault_secret" "cosmos_mongo_connection" {
  name         = "cosmos-mongo-connection-string"
  value        = module.cosmos.mongo_connection_string
  key_vault_id = data.azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "cosmos_gremlin_connection" {
  name         = "cosmos-gremlin-endpoint"
  value        = module.cosmos.gremlin_endpoint
  key_vault_id = data.azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "search_key" {
  name         = "search-api-key"
  value        = module.search.primary_key
  key_vault_id = data.azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "openai_key" {
  name         = "openai-api-key"
  value        = module.openai.primary_key
  key_vault_id = data.azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "openai_endpoint" {
  name         = "openai-endpoint"
  value        = module.openai.endpoint
  key_vault_id = data.azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "search_endpoint" {
  name         = "search-endpoint"
  value        = module.search.endpoint
  key_vault_id = data.azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "cosmos_gremlin_key" {
  name         = "cosmos-gremlin-key"
  value        = module.cosmos.gremlin_key
  key_vault_id = data.azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "redis_connection" {
  name         = "redis-connection-string"
  value        = module.redis.primary_connection_string
  key_vault_id = data.azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "storage_connection" {
  name         = "storage-connection-string"
  value        = module.storage.connection_string
  key_vault_id = data.azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "appinsights_key" {
  name         = "appinsights-connection-string"
  value        = module.monitoring.connection_string
  key_vault_id = data.azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "content_safety_key" {
  name         = "content-safety-key"
  value        = module.openai.content_safety_key
  key_vault_id = data.azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "content_safety_endpoint" {
  name         = "content-safety-endpoint"
  value        = module.openai.content_safety_endpoint
  key_vault_id = data.azurerm_key_vault.main.id
}
