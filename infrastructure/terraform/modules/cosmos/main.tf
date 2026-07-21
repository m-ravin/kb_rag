variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "name_suffix" { type = string }
variable "throughput" { type = number }
variable "tags" { type = map(string) }

# ── Cosmos DB Account (shared by MongoDB API + Gremlin API) ───────────────────
# free_tier_enabled grants 1000 RU/s + 25GB free per subscription (one account only).
# Only compatible with provisioned throughput, not serverless — hence dedicated
# throughput below stays at the database level, not serverless mode.
resource "azurerm_cosmosdb_account" "main" {
  name                = "cosmos-${var.name_suffix}"
  location            = var.location
  resource_group_name = var.resource_group_name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"
  free_tier_enabled   = true

  # Enable both MongoDB and Gremlin capabilities
  capabilities {
    name = "EnableMongo"
  }
  capabilities {
    name = "EnableGremlin"
  }

  consistency_policy {
    consistency_level       = "Session"
    max_interval_in_seconds = 5
    max_staleness_prefix    = 100
  }

  geo_location {
    location          = var.location
    failover_priority = 0
  }

  tags = var.tags
}

# ── MongoDB API: PIL Knowledge Base (document metadata) ───────────────────────
# Throughput is provisioned once here and shared across all 3 collections below —
# setting it again per-collection would double/quadruple-provision (and bill) RU/s.
resource "azurerm_cosmosdb_mongo_database" "pil_kb" {
  name                = "pil-knowledge-base"
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.main.name
  throughput          = var.throughput
}

resource "azurerm_cosmosdb_mongo_collection" "documents" {
  name                = "documents"
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_mongo_database.pil_kb.name

  index { keys = ["_id"] }
  index { keys = ["document_id"] }
  index { keys = ["status"] }
}

resource "azurerm_cosmosdb_mongo_collection" "qa_logs" {
  name                = "qa_logs"
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_mongo_database.pil_kb.name

  index { keys = ["_id"] }
  index { keys = ["session_id"] }
  index { keys = ["created_at"] }
}

resource "azurerm_cosmosdb_mongo_collection" "users" {
  name                = "users"
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_mongo_database.pil_kb.name

  index { keys = ["_id"] }
  index { keys = ["email"] }
}

# ── Gremlin API: chunk relationship graph ─────────────────────────────────────
# Same shared-throughput approach: throughput lives on the database, not the graph.
resource "azurerm_cosmosdb_gremlin_database" "graph" {
  name                = "pil-graph"
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.main.name
  throughput          = var.throughput
}

resource "azurerm_cosmosdb_gremlin_graph" "chunks" {
  name                = "chunk-graph"
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_gremlin_database.graph.name
  partition_key_path  = "/document_id"

  index_policy {
    automatic      = true
    indexing_mode  = "consistent"
    included_paths = ["/*"]
    excluded_paths = ["/\"_etag\"/?"]
  }
}

output "mongo_connection_string" {
  value     = azurerm_cosmosdb_account.main.connection_strings[0]
  sensitive = true
}
output "gremlin_endpoint" {
  value     = "wss://${azurerm_cosmosdb_account.main.name}.gremlin.cosmos.azure.com:443/"
  sensitive = true
}
output "gremlin_key" {
  value     = azurerm_cosmosdb_account.main.primary_key
  sensitive = true
}
output "account_name" { value = azurerm_cosmosdb_account.main.name }
