# Routes platform/resource-level logs to Log Analytics for every resource
# this pipeline actually depends on. Found via a live audit (`az monitor
# diagnostic-settings list` against all 10 project resources) that NONE of
# them had a diagnostic setting configured — the only thing reaching
# law-pil-dev before this was the Function App's own Application Insights
# telemetry (AppTraces/AppExceptions), which is a separate mechanism from
# platform logs (Storage read/write/delete, Key Vault access, Search
# queries, Cosmos requests, Function host logs). See
# docs/adr/0016-document-lifecycle-and-data-integrity.md.
#
# Deliberately scoped to resources this pipeline depends on, not every
# resource in either resource group — excludes shared/unrelated
# infrastructure (vnet, NSG, the Foundry hub's own App Insights) living
# alongside the reused resources in rsg-dev-az1-dp.

variable "log_analytics_workspace_id" { type = string }
variable "function_app_id" { type = string }
variable "storage_account_id" { type = string }
variable "key_vault_id" { type = string }
variable "search_service_id" { type = string }
variable "cosmos_mongo_id" { type = string }
variable "cosmos_gremlin_id" { type = string }

resource "azurerm_monitor_diagnostic_setting" "function_app" {
  name                       = "diag-to-law"
  target_resource_id         = var.function_app_id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log { category = "FunctionAppLogs" }

  metric {
    category = "AllMetrics"
    enabled  = true
  }
}

# Diagnostic settings for Storage Accounts attach to the blob sub-resource,
# not the account resource itself — read/write/delete logs live there.
resource "azurerm_monitor_diagnostic_setting" "storage_blob" {
  name                       = "diag-to-law"
  target_resource_id         = "${var.storage_account_id}/blobServices/default"
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log { category = "StorageRead" }
  enabled_log { category = "StorageWrite" }
  enabled_log { category = "StorageDelete" }

  metric {
    category = "Transaction"
    enabled  = true
  }
}

resource "azurerm_monitor_diagnostic_setting" "key_vault" {
  name                       = "diag-to-law"
  target_resource_id         = var.key_vault_id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log { category = "AuditEvent" }

  metric {
    category = "AllMetrics"
    enabled  = true
  }
}

resource "azurerm_monitor_diagnostic_setting" "search" {
  name                       = "diag-to-law"
  target_resource_id         = var.search_service_id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log { category = "OperationLogs" }

  metric {
    category = "AllMetrics"
    enabled  = true
  }
}

resource "azurerm_monitor_diagnostic_setting" "cosmos_mongo" {
  name                       = "diag-to-law"
  target_resource_id         = var.cosmos_mongo_id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log { category = "vCoreMongoRequests" }

  metric {
    category = "Traffic"
    enabled  = true
  }
  metric {
    category = "Latency"
    enabled  = true
  }
}

resource "azurerm_monitor_diagnostic_setting" "cosmos_gremlin" {
  name                       = "diag-to-law"
  target_resource_id         = var.cosmos_gremlin_id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log { category = "GremlinRequests" }
  enabled_log { category = "MongoRequests" }

  metric {
    category = "Requests"
    enabled  = true
  }
}
