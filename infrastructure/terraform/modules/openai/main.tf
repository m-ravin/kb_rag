variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "name_suffix" { type = string }
variable "gpt_model" { type = string }
variable "embedding_model" { type = string }
variable "tags" { type = map(string) }

resource "azurerm_cognitive_account" "openai" {
  name                = "oai-${var.name_suffix}"
  location            = var.location
  resource_group_name = var.resource_group_name
  kind                = "OpenAI"
  sku_name            = "S0"
  tags                = var.tags
}

# GPT-4o deployment — handles Q&A, summarisation, wording tuning
resource "azurerm_cognitive_deployment" "gpt" {
  name                 = var.gpt_model
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = var.gpt_model
    version = "2024-08-06"
  }

  scale {
    type     = "Standard"
    capacity = 30  # 30k tokens per minute
  }
}

# Embedding model — converts text chunks into vectors
resource "azurerm_cognitive_deployment" "embedding" {
  name                 = var.embedding_model
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = var.embedding_model
    version = "1"
  }

  scale {
    type     = "Standard"
    capacity = 120  # 120k tokens per minute for embeddings
  }
}

# Azure AI Content Safety — screens inputs and outputs
resource "azurerm_cognitive_account" "content_safety" {
  name                = "cs-${var.name_suffix}"
  location            = var.location
  resource_group_name = var.resource_group_name
  kind                = "ContentSafety"
  sku_name            = "S0"
  tags                = var.tags
}

output "endpoint"              { value = azurerm_cognitive_account.openai.endpoint }
output "primary_key"           { value = azurerm_cognitive_account.openai.primary_access_key; sensitive = true }
output "content_safety_endpoint" { value = azurerm_cognitive_account.content_safety.endpoint }
output "content_safety_key"    { value = azurerm_cognitive_account.content_safety.primary_access_key; sensitive = true }
