variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "name_suffix" { type = string }
variable "capacity" { type = number }
variable "tags" { type = map(string) }

# Azure Cache for Redis — holds intermediate search results so we don't
# re-query the vector DB for the same question twice within 5 minutes
resource "azurerm_redis_cache" "main" {
  name                = "redis-${var.name_suffix}"
  location            = var.location
  resource_group_name = var.resource_group_name
  capacity            = var.capacity
  family              = "C"
  sku_name            = "Standard"
  enable_non_ssl_port = false
  minimum_tls_version = "1.2"

  redis_configuration {
    maxmemory_policy = "allkeys-lru"
  }

  tags = var.tags
}

output "hostname"                  { value = azurerm_redis_cache.main.hostname }
output "primary_connection_string" { value = azurerm_redis_cache.main.primary_connection_string; sensitive = true }
output "ssl_port"                  { value = azurerm_redis_cache.main.ssl_port }
