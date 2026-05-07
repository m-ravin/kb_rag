output "resource_group_name" {
  value = azurerm_resource_group.main.name
}

output "aks_cluster_name" {
  value = module.aks.cluster_name
}

output "search_endpoint" {
  value = module.search.endpoint
}

output "openai_endpoint" {
  value     = module.openai.endpoint
  sensitive = true
}

output "cosmos_mongo_connection_string" {
  value     = module.cosmos.mongo_connection_string
  sensitive = true
}

output "cosmos_gremlin_endpoint" {
  value     = module.cosmos.gremlin_endpoint
  sensitive = true
}

output "redis_hostname" {
  value = module.redis.hostname
}

output "storage_account_name" {
  value = module.storage.storage_account_name
}

output "key_vault_uri" {
  value = azurerm_key_vault.main.vault_uri
}

output "app_insights_connection_string" {
  value     = module.monitoring.connection_string
  sensitive = true
}

output "function_app_url" {
  value = module.functions.function_app_url
}

# Helper: generates .env file content for local development
output "env_file_content" {
  sensitive = true
  value     = <<-EOT
    AZURE_OPENAI_ENDPOINT=${module.openai.endpoint}
    AZURE_OPENAI_KEY=${module.openai.primary_key}
    AZURE_OPENAI_GPT_DEPLOYMENT=${var.openai_gpt_model}
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT=${var.openai_embedding_model}
    AZURE_SEARCH_ENDPOINT=${module.search.endpoint}
    AZURE_SEARCH_KEY=${module.search.primary_key}
    AZURE_SEARCH_INDEX_NAME=pil-documents
    COSMOS_MONGO_CONNECTION=${module.cosmos.mongo_connection_string}
    COSMOS_GREMLIN_ENDPOINT=${module.cosmos.gremlin_endpoint}
    COSMOS_GREMLIN_KEY=${module.cosmos.gremlin_key}
    REDIS_CONNECTION=${module.redis.primary_connection_string}
    STORAGE_CONNECTION=${module.storage.connection_string}
    STORAGE_CONTAINER_NAME=pil-documents
    APPINSIGHTS_CONNECTION_STRING=${module.monitoring.connection_string}
    KEY_VAULT_URI=${azurerm_key_vault.main.vault_uri}
  EOT
}
