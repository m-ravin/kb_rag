variable "existing_name" { type = string }
variable "existing_resource_group_name" { type = string }

# Reuses the pre-provisioned HNS-enabled (Data Lake Gen2) storage account in
# rsg-dev-az1-dp rather than creating a new one — see
# docs/adr/0014-reuse-existing-dev-subscription-resources.md
data "azurerm_storage_account" "main" {
  name                = var.existing_name
  resource_group_name = var.existing_resource_group_name
}

resource "azurerm_storage_container" "pil_documents" {
  name                  = "pil-documents"
  storage_account_name  = data.azurerm_storage_account.main.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "processed" {
  name                  = "processed"
  storage_account_name  = data.azurerm_storage_account.main.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "function_artifacts" {
  name                  = "function-artifacts"
  storage_account_name  = data.azurerm_storage_account.main.name
  container_access_type = "private"
}

output "storage_account_name" { value = data.azurerm_storage_account.main.name }
output "storage_account_key" {
  value     = data.azurerm_storage_account.main.primary_access_key
  sensitive = true
}
output "connection_string" {
  value     = data.azurerm_storage_account.main.primary_connection_string
  sensitive = true
}
