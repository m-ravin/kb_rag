variable "prefix" {
  description = "Short prefix for all resource names (e.g. 'pil')"
  type        = string
  default     = "pil"
}

variable "location" {
  description = "Azure region for most resources (Container Apps, Search, Cosmos, Redis, Storage, ACR, Key Vault, Monitoring)"
  type        = string
  default     = "centralindia"
}

variable "openai_location" {
  description = "Azure region for Azure OpenAI + Content Safety. Must support gpt-4o (GlobalStandard) and text-embedding-3-small — centralindia does not support either, and southeastasia supports the embedding model but not gpt-4o (confirmed via Azure's region-availability docs: GlobalStandard gpt-4o in Asia Pacific is only in australiaeast/japaneast/koreacentral/southindia). southindia is used here since it's the closest to centralindia and supports both models."
  type        = string
  default     = "southindia"
}

variable "environment" {
  description = "Deployment environment: dev, staging, prod"
  type        = string
  default     = "dev"
}

variable "openai_gpt_model" {
  description = "Azure OpenAI GPT model deployment name. The gpt-4o/gpt-4.1 generation is deprecating and blocked for new deployments as of 2026-07 — gpt-5-mini used instead (GA, GlobalStandard, cheapest current mini-tier model). Verify with `az cognitiveservices account list-models` before changing, since Azure rotates model availability quickly."
  type        = string
  default     = "gpt-5-mini"
}

variable "openai_embedding_model" {
  description = "Azure OpenAI embedding model deployment name"
  type        = string
  default     = "text-embedding-3-small"
}

variable "cosmos_throughput" {
  description = "Cosmos DB throughput in RU/s, provisioned once per API (Mongo + Gremlin = 2x this value). Default 400+400=800 RU/s stays under the free tier's 1000 RU/s allowance."
  type        = number
  default     = 400
}

variable "redis_capacity" {
  description = "Redis Basic tier capacity (0=250MB, 1=1GB, 2=2.5GB). 0 is the cheapest paid option — Redis has no free tier."
  type        = number
  default     = 0
}

# ── Existing dev-subscription resources being reused (rsg-dev-az1-dp) ────────
# See docs/adr/0014-reuse-existing-dev-subscription-resources.md.
# New project resources live in a separate resource group (rg-${prefix}-${environment})
# so a `terraform destroy` here can never touch anything else in rsg-dev-az1-dp.
variable "existing_resource_group_name" {
  description = "Resource group containing the pre-provisioned resources to reuse"
  type        = string
  default     = "rsg-dev-az1-dp"
}

variable "existing_search_name" {
  description = "Name of the existing Azure AI Search service to reuse"
  type        = string
  default     = "srch-dev-az1-dp"
}

variable "existing_storage_account_name" {
  description = "Name of the existing (HNS-enabled) storage account to reuse"
  type        = string
  default     = "stdevaz1dp001"
}

variable "existing_key_vault_name" {
  description = "Name of the existing Key Vault to reuse"
  type        = string
  default     = "kv-dev-az1-dp"
}

variable "tags" {
  description = "Tags applied to every Azure resource"
  type        = map(string)
  default = {
    project    = "kb_rag"
    managed_by = "terraform"
  }
}
