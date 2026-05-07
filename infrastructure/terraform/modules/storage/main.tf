variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "name_suffix" { type = string }
variable "tags" { type = map(string) }

# Azure Data Lake Storage Gen2 — stores all raw documents (PDF, DOCX, PPTX)
resource "azurerm_storage_account" "main" {
  name                     = "st${replace(var.name_suffix, "-", "")}pil"
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  # Hierarchical namespace = Data Lake Gen2
  is_hns_enabled           = true
  min_tls_version          = "TLS1_2"
  tags                     = var.tags
}

resource "azurerm_storage_container" "pil_documents" {
  name                  = "pil-documents"
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "processed" {
  name                  = "processed"
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "function_artifacts" {
  name                  = "function-artifacts"
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

output "storage_account_name" { value = azurerm_storage_account.main.name }
output "storage_account_key"  { value = azurerm_storage_account.main.primary_access_key; sensitive = true }
output "connection_string"    { value = azurerm_storage_account.main.primary_connection_string; sensitive = true }
