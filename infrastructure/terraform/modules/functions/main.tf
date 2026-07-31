variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "name_suffix" { type = string }
variable "storage_account_name" { type = string }
variable "storage_account_key" { type = string }
variable "key_vault_uri" { type = string }
variable "storage_container_name" {
  type    = string
  default = "pil-documents"
}
variable "storage_processed_container_name" {
  type    = string
  default = "processed"
}
variable "storage_deleted_container_name" {
  type    = string
  default = "deleted"
}
variable "cosmos_db_name" {
  type    = string
  default = "pil-knowledge-base"
}
variable "search_index_name" {
  type    = string
  default = "pil-documents"
}
variable "embedding_model" {
  type    = string
  default = "text-embedding-3-small"
}
# Tags every Mongo/Search record so a future prod deployment of this same
# module (a separate Function App + its own app_settings) can be given
# environment = "prod" without any code change — see
# docs/adr/0016-document-lifecycle-and-data-integrity.md.
variable "environment" {
  type    = string
  default = "dev"
}
variable "tags" { type = map(string) }

# Consumption plan — pay only when the function actually runs
resource "azurerm_service_plan" "functions" {
  name                = "asp-func-${var.name_suffix}"
  location            = var.location
  resource_group_name = var.resource_group_name
  os_type             = "Linux"
  sku_name            = "Y1"
  tags                = var.tags
}

# Azure Function App — runs the document processor robot
resource "azurerm_linux_function_app" "document_processor" {
  name                       = "func-doc-proc-${var.name_suffix}"
  resource_group_name        = var.resource_group_name
  location                   = var.location
  service_plan_id            = azurerm_service_plan.functions.id
  storage_account_name       = var.storage_account_name
  storage_account_access_key = var.storage_account_key

  site_config {
    application_stack {
      python_version = "3.11"
    }
  }

  # Secrets are Key Vault references, resolved at runtime by the Function App's
  # own system-assigned identity — see the Key Vault Secrets User role
  # assignment on that identity in the root module. Non-secret settings are
  # plain values so the app is independently readable without a KV round-trip.
  app_settings = {
    FUNCTIONS_WORKER_RUNTIME       = "python"
    SCM_DO_BUILD_DURING_DEPLOYMENT = "true"

    # Python v2 (decorator-based) programming model requires this feature flag
    # to index functions correctly on this host runtime version. Discovered
    # during live deployment debugging (2026-07-29) — was set imperatively via
    # `az functionapp config appsettings set` before being reflected here.
    AzureWebJobsFeatureFlags = "EnableWorkerIndexing"

    AZURE_OPENAI_ENDPOINT             = "@Microsoft.KeyVault(SecretUri=${var.key_vault_uri}secrets/openai-endpoint/)"
    AZURE_OPENAI_KEY                  = "@Microsoft.KeyVault(SecretUri=${var.key_vault_uri}secrets/openai-api-key/)"
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT = var.embedding_model

    AZURE_SEARCH_ENDPOINT   = "@Microsoft.KeyVault(SecretUri=${var.key_vault_uri}secrets/search-endpoint/)"
    AZURE_SEARCH_KEY        = "@Microsoft.KeyVault(SecretUri=${var.key_vault_uri}secrets/search-api-key/)"
    AZURE_SEARCH_INDEX_NAME = var.search_index_name

    COSMOS_MONGO_CONNECTION = "@Microsoft.KeyVault(SecretUri=${var.key_vault_uri}secrets/cosmos-mongo-connection-string/)"
    COSMOS_DB_NAME          = var.cosmos_db_name
    COSMOS_GREMLIN_ENDPOINT = "@Microsoft.KeyVault(SecretUri=${var.key_vault_uri}secrets/cosmos-gremlin-endpoint/)"
    COSMOS_GREMLIN_KEY      = "@Microsoft.KeyVault(SecretUri=${var.key_vault_uri}secrets/cosmos-gremlin-key/)"

    STORAGE_CONNECTION     = "@Microsoft.KeyVault(SecretUri=${var.key_vault_uri}secrets/storage-connection-string/)"
    STORAGE_CONTAINER_NAME = var.storage_container_name
    # Deliberately a separate container, not a "processed/" prefix inside
    # STORAGE_CONTAINER_NAME — see stage7_archive.py's module docstring for
    # the self-triggering reprocessing loop that caused (2026-07-30).
    STORAGE_PROCESSED_CONTAINER_NAME = var.storage_processed_container_name
    # Soft-delete holding area — see purge_job.py.
    STORAGE_DELETED_CONTAINER_NAME = var.storage_deleted_container_name

    APPLICATIONINSIGHTS_CONNECTION_STRING = "@Microsoft.KeyVault(SecretUri=${var.key_vault_uri}secrets/appinsights-connection-string/)"

    ENVIRONMENT = var.environment
  }

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags

  # WEBSITE_RUN_FROM_PACKAGE drift: the real deploy flow for this app is
  # `az functionapp deployment source config-zip --build-remote true`, which
  # REMOVES WEBSITE_RUN_FROM_PACKAGE from app_settings entirely and instead
  # points the running package via an internal SCM_RUN_FROM_PACKAGE mechanism
  # that lives outside the app_settings map Terraform controls (discovered
  # during live deployment debugging, 2026-07-29). app_settings is otherwise a
  # fully declarative map, so previously hardcoding
  # WEBSITE_RUN_FROM_PACKAGE = "1" here meant any future `terraform apply`
  # touching this resource — even for an unrelated setting — would silently
  # re-add it and fight the deploy tooling's own state. Fix: don't declare the
  # key in app_settings at all (Terraform then has no opinion on it and won't
  # try to reconcile it either direction), and additionally ignore it at the
  # provider-diff level so a `terraform plan` never reports drift for this one
  # key no matter what value the live deploy flow leaves it at.
  lifecycle {
    ignore_changes = [app_settings["WEBSITE_RUN_FROM_PACKAGE"]]
  }
}

output "function_app_url" { value = "https://${azurerm_linux_function_app.document_processor.default_hostname}" }
output "function_app_name" { value = azurerm_linux_function_app.document_processor.name }
output "function_app_id" { value = azurerm_linux_function_app.document_processor.id }
output "function_app_principal_id" { value = azurerm_linux_function_app.document_processor.identity[0].principal_id }
