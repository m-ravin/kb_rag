variable "existing_name" { type = string }
variable "existing_resource_group_name" { type = string }

# Reuses the pre-provisioned HNS-enabled (Data Lake Gen2) storage account in
# rsg-dev-az1-dp rather than creating a new one — see
# docs/adr/0014-reuse-existing-dev-subscription-resources.md
#
# Blob + container soft-delete (7-day retention) is enabled on this account,
# but out-of-band via `az storage account blob-service-properties update`
# rather than through this data source — the AzureRM provider only exposes
# blob_properties as a nested block on the managed azurerm_storage_account
# *resource*, not as a standalone resource attachable to a data source, and
# importing this shared account into Terraform state is out of scope (see
# docs/adr/0016-document-lifecycle-and-data-integrity.md). Blob versioning is
# NOT enabled: unsupported on HNS/Data Lake Gen2 accounts
# (FeatureNotSupportedForAccount).
data "azurerm_storage_account" "main" {
  name                = var.existing_name
  resource_group_name = var.existing_resource_group_name
}

resource "azurerm_storage_container" "pil_documents" {
  name                  = "pil-documents"
  storage_account_name  = data.azurerm_storage_account.main.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "processed" {
  name                  = "processed"
  storage_account_name  = data.azurerm_storage_account.main.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "function_artifacts" {
  name                  = "function-artifacts"
  storage_account_name  = data.azurerm_storage_account.main.name
  container_access_type = "private"
}

# Holding area for soft-deleted documents — DELETE /manage/documents/{id}
# moves the blob here instead of deleting it outright. purge_job.py (a
# nightly timer function) hard-deletes anything older than the retention
# window and is the source of truth for *when* something is actually gone;
# the lifecycle management policy below is a redundant backstop in case that
# job doesn't run for a while, not the primary mechanism. See
# docs/adr/0016-document-lifecycle-and-data-integrity.md.
resource "azurerm_storage_container" "deleted" {
  name                  = "deleted"
  storage_account_name  = data.azurerm_storage_account.main.name
  container_access_type = "private"
}

resource "azurerm_storage_management_policy" "deleted_purge_backstop" {
  storage_account_id = data.azurerm_storage_account.main.id

  rule {
    name    = "purge-deleted-container-backstop"
    enabled = true
    filters {
      prefix_match = ["deleted/"]
      blob_types   = ["blockBlob"]
    }
    actions {
      base_blob {
        delete_after_days_since_modification_greater_than = 7
      }
    }
  }
}

output "storage_account_name" { value = data.azurerm_storage_account.main.name }
output "storage_account_key" {
  value     = data.azurerm_storage_account.main.primary_access_key
  sensitive = true
}
output "connection_string" {
  value     = data.azurerm_storage_account.main.primary_connection_string
  sensitive = true
}
