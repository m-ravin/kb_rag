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

# GPT deployment — handles Q&A, summarisation, wording tuning.
# As of 2026-07, the entire gpt-4o/gpt-4.1 generation is deprecating and
# blocked for new deployments on this account/catalog — confirmed by querying
# `az cognitiveservices account list-models` live rather than assuming.
# gpt-5-mini is the current GA + GlobalStandard mini-tier model (cheap,
# strong enough for RAG Q&A). If this model also rotates out of GA later,
# re-run that command to find the current GA+GlobalStandard chat model list
# before picking a replacement — do not assume any hardcoded version stays valid.
resource "azurerm_cognitive_deployment" "gpt" {
  name                 = var.gpt_model
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = var.gpt_model
    version = "2025-08-07"
  }

  scale {
    # GlobalStandard (not Standard) — southeastasia doesn't support region-pinned
    # "Standard" scale for gpt-4o; GlobalStandard routes across Azure's global
    # capacity pool for this model instead.
    type     = "GlobalStandard"
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
    # GlobalStandard — same regional-availability reason as the gpt deployment above.
    type     = "GlobalStandard"
    capacity = 120  # 120k tokens per minute for embeddings
  }
}

# Azure AI Content Safety — screens inputs and outputs.
# F0 free tier: 5,000 text records/month, plenty for personal-scale usage.
resource "azurerm_cognitive_account" "content_safety" {
  name                = "cs-${var.name_suffix}"
  location            = var.location
  resource_group_name = var.resource_group_name
  kind                = "ContentSafety"
  sku_name            = "F0"
  tags                = var.tags
}

output "endpoint" { value = azurerm_cognitive_account.openai.endpoint }
output "primary_key" {
  value     = azurerm_cognitive_account.openai.primary_access_key
  sensitive = true
}
output "content_safety_endpoint" { value = azurerm_cognitive_account.content_safety.endpoint }
output "content_safety_key" {
  value     = azurerm_cognitive_account.content_safety.primary_access_key
  sensitive = true
}
