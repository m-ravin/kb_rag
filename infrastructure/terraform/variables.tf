variable "prefix" {
  description = "Short prefix for all resource names (e.g. 'pil')"
  type        = string
  default     = "pil"
}

variable "location" {
  description = "Azure region to deploy all resources"
  type        = string
  default     = "eastus"
}

variable "environment" {
  description = "Deployment environment: dev, staging, prod"
  type        = string
  default     = "dev"
}

variable "aks_node_count" {
  description = "Initial number of AKS nodes"
  type        = number
  default     = 2
}

variable "aks_node_vm_size" {
  description = "VM size for AKS nodes"
  type        = string
  default     = "Standard_D4s_v3"
}

variable "openai_gpt_model" {
  description = "Azure OpenAI GPT model deployment name"
  type        = string
  default     = "gpt-4o"
}

variable "openai_embedding_model" {
  description = "Azure OpenAI embedding model deployment name"
  type        = string
  default     = "text-embedding-3-small"
}

variable "cosmos_throughput" {
  description = "Cosmos DB throughput in RU/s"
  type        = number
  default     = 400
}

variable "redis_capacity" {
  description = "Redis cache capacity tier (1=1GB, 2=6GB)"
  type        = number
  default     = 1
}

variable "tags" {
  description = "Tags applied to every Azure resource"
  type        = map(string)
  default = {
    project    = "kb_rag"
    managed_by = "terraform"
  }
}
