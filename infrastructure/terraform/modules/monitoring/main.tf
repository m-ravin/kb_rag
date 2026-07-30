variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "name_suffix" { type = string }
variable "tags" { type = map(string) }
variable "alert_email" {
  type        = string
  default     = "raviinfo001@gmail.com"
  description = "Destination for Function App failure alerts."
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "law-${var.name_suffix}"
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = var.tags
}

resource "azurerm_application_insights" "main" {
  name                = "appi-${var.name_suffix}"
  location            = var.location
  resource_group_name = var.resource_group_name
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"
  tags                = var.tags
}

output "connection_string" {
  value     = azurerm_application_insights.main.connection_string
  sensitive = true
}
output "instrumentation_key" {
  value     = azurerm_application_insights.main.instrumentation_key
  sensitive = true
}
output "log_analytics_workspace_id" { value = azurerm_log_analytics_workspace.main.id }

# ── Failure alerting ───────────────────────────────────────────────────────
# App Insights here is workspace-based (IngestionMode: LogAnalytics, see
# azurerm_application_insights.main above) — `az monitor app-insights query`
# and classic metric alerts don't see its data, only queries against the
# linked Log Analytics workspace's AppTraces/AppExceptions tables do (found
# the hard way debugging this system live — see
# docs/adr/0016-document-lifecycle-and-data-integrity.md). So this is a
# Log Analytics-scoped scheduled query alert, not an azurerm_monitor_metric_alert
# on the Function App resource, which would silently never fire.
resource "azurerm_monitor_action_group" "main" {
  name                = "ag-${var.name_suffix}"
  resource_group_name = var.resource_group_name
  short_name           = "pilalerts"

  email_receiver {
    name          = "primary"
    email_address = var.alert_email
  }

  tags = var.tags
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "function_failures" {
  name                = "alert-func-failures-${var.name_suffix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  evaluation_frequency = "PT15M"
  window_duration       = "PT15M"
  scopes                = [azurerm_log_analytics_workspace.main.id]
  severity              = 2
  criteria {
    query                   = <<-QUERY
      union AppTraces, AppExceptions
      | where SeverityLevel >= 3 or Message has "Failed to process" or Message has "Reconciliation drift"
    QUERY
    time_aggregation_method = "Count"
    threshold               = 0
    operator                 = "GreaterThan"
  }
  action {
    action_groups = [azurerm_monitor_action_group.main.id]
  }

  tags = var.tags
}
