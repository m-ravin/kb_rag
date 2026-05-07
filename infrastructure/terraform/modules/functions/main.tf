variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "name_suffix" { type = string }
variable "storage_account_name" { type = string }
variable "storage_account_key" { type = string }
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

  app_settings = {
    FUNCTIONS_WORKER_RUNTIME       = "python"
    SCM_DO_BUILD_DURING_DEPLOYMENT = "true"
    WEBSITE_RUN_FROM_PACKAGE       = "1"
  }

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}

output "function_app_url"          { value = "https://${azurerm_linux_function_app.document_processor.default_hostname}" }
output "function_app_principal_id" { value = azurerm_linux_function_app.document_processor.identity[0].principal_id }
