locals {
  name_suffix = "${var.prefix}-${var.environment}"
}

resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

resource "azurerm_resource_group" "main" {
  name     = "rg-${local.name_suffix}"
  location = var.location
  tags     = var.tags
}

# ── Networking ────────────────────────────────────────────────────────────────
module "networking" {
  source              = "./modules/networking"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  name_suffix         = local.name_suffix
  tags                = var.tags
}

# ── AKS (hosts backend + CMS frontend) ───────────────────────────────────────
module "aks" {
  source              = "./modules/aks"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  name_suffix         = local.name_suffix
  subnet_id           = module.networking.aks_subnet_id
  node_count          = var.aks_node_count
  node_vm_size        = var.aks_node_vm_size
  tags                = var.tags
}

# ── Azure AI Search (Vector DB for document chunks) ──────────────────────────
module "search" {
  source              = "./modules/search"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  name_suffix         = "${local.name_suffix}${random_string.suffix.result}"
  tags                = var.tags
}

# ── Cosmos DB (MongoDB + Gremlin) ─────────────────────────────────────────────
module "cosmos" {
  source              = "./modules/cosmos"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  name_suffix         = "${local.name_suffix}${random_string.suffix.result}"
  throughput          = var.cosmos_throughput
  tags                = var.tags
}

# ── Azure OpenAI (LLM + Embeddings + Safety) ─────────────────────────────────
module "openai" {
  source                 = "./modules/openai"
  resource_group_name    = azurerm_resource_group.main.name
  location               = var.location
  name_suffix            = "${local.name_suffix}${random_string.suffix.result}"
  gpt_model              = var.openai_gpt_model
  embedding_model        = var.openai_embedding_model
  tags                   = var.tags
}

# ── Azure Data Lake Storage Gen2 (document storage) ──────────────────────────
module "storage" {
  source              = "./modules/storage"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  name_suffix         = "${local.name_suffix}${random_string.suffix.result}"
  tags                = var.tags
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
  source                   = "./modules/functions"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = var.location
  name_suffix              = "${local.name_suffix}${random_string.suffix.result}"
  storage_account_name     = module.storage.storage_account_name
  storage_account_key      = module.storage.storage_account_key
  tags                     = var.tags
}

# ── Azure Monitor + App Insights ──────────────────────────────────────────────
module "monitoring" {
  source              = "./modules/monitoring"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  name_suffix         = local.name_suffix
  tags                = var.tags
}

# ── API Management (rate limiting, gateway) ────────────────────────────────────
module "apim" {
  source              = "./modules/apim"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  name_suffix         = local.name_suffix
  tags                = var.tags
}

# ── Key Vault (all secrets) ───────────────────────────────────────────────────
resource "azurerm_key_vault" "main" {
  name                = "kv-${local.name_suffix}-${random_string.suffix.result}"
  location            = var.location
  resource_group_name = azurerm_resource_group.main.name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id

    secret_permissions = ["Get", "List", "Set", "Delete", "Purge"]
  }

  tags = var.tags
}

data "azurerm_client_config" "current" {}

# ── Store all secrets in Key Vault ────────────────────────────────────────────
resource "azurerm_key_vault_secret" "cosmos_mongo_connection" {
  name         = "cosmos-mongo-connection-string"
  value        = module.cosmos.mongo_connection_string
  key_vault_id = azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "cosmos_gremlin_connection" {
  name         = "cosmos-gremlin-endpoint"
  value        = module.cosmos.gremlin_endpoint
  key_vault_id = azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "search_key" {
  name         = "search-api-key"
  value        = module.search.primary_key
  key_vault_id = azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "openai_key" {
  name         = "openai-api-key"
  value        = module.openai.primary_key
  key_vault_id = azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "redis_connection" {
  name         = "redis-connection-string"
  value        = module.redis.primary_connection_string
  key_vault_id = azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "storage_connection" {
  name         = "storage-connection-string"
  value        = module.storage.connection_string
  key_vault_id = azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "appinsights_key" {
  name         = "appinsights-connection-string"
  value        = module.monitoring.connection_string
  key_vault_id = azurerm_key_vault.main.id
}
