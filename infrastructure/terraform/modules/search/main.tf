variable "existing_name" { type = string }
variable "existing_resource_group_name" { type = string }

# Reuses the pre-provisioned Free-tier Search service in rsg-dev-az1-dp rather than
# creating a new one — see docs/adr/0014-reuse-existing-dev-subscription-resources.md
data "azurerm_search_service" "main" {
  name                = var.existing_name
  resource_group_name = var.existing_resource_group_name
}

output "endpoint" { value = "https://${data.azurerm_search_service.main.name}.search.windows.net" }
output "primary_key" {
  value     = data.azurerm_search_service.main.primary_key
  sensitive = true
}
output "name" { value = data.azurerm_search_service.main.name }
output "id" { value = data.azurerm_search_service.main.id }
