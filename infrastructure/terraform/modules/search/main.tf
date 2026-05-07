variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "name_suffix" { type = string }
variable "tags" { type = map(string) }

resource "azurerm_search_service" "main" {
  name                = "srch-${var.name_suffix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "standard"
  replica_count       = 1
  partition_count     = 1

  # Allow both API key and AAD auth
  local_authentication_enabled = true
  tags                         = var.tags
}

output "endpoint"    { value = "https://${azurerm_search_service.main.name}.search.windows.net" }
output "primary_key" { value = azurerm_search_service.main.primary_key; sensitive = true }
output "name"        { value = azurerm_search_service.main.name }
