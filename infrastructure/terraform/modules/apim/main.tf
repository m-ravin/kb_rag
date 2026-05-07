variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "name_suffix" { type = string }
variable "tags" { type = map(string) }

# API Management — front door for all API traffic; handles rate limiting,
# authentication, request transformation, and developer portal
resource "azurerm_api_management" "main" {
  name                = "apim-${var.name_suffix}"
  location            = var.location
  resource_group_name = var.resource_group_name
  publisher_name      = "kb-rag Team"
  publisher_email     = "admin@kb-rag.example.com"
  sku_name            = "Developer_1"  # Change to "Standard_1" for production

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}

# Rate-limit policy applied to all APIs
resource "azurerm_api_management_policy" "global" {
  api_management_id = azurerm_api_management.main.id

  xml_content = <<XML
<policies>
  <inbound>
    <rate-limit-by-key calls="100" renewal-period="60"
      counter-key="@(context.Request.IpAddress)" />
    <cors>
      <allowed-origins><origin>*</origin></allowed-origins>
      <allowed-methods><method>*</method></allowed-methods>
      <allowed-headers><header>*</header></allowed-headers>
    </cors>
  </inbound>
  <backend><forward-request /></backend>
  <outbound><base /></outbound>
  <on-error><base /></on-error>
</policies>
XML
}

output "gateway_url"      { value = azurerm_api_management.main.gateway_url }
output "management_url"   { value = azurerm_api_management.main.management_api_url }
output "apim_resource_id" { value = azurerm_api_management.main.id }
