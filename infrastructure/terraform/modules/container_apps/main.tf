variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "name_suffix" { type = string }
variable "log_analytics_workspace_id" { type = string }
variable "tags" { type = map(string) }

# Placeholder image used only at first `terraform apply`, before CI/CD has ever
# pushed a real image to ACR. deploy.yml takes over the running image after that;
# lifecycle.ignore_changes stops subsequent applies from reverting it.
locals {
  placeholder_image = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
}

resource "azurerm_container_registry" "main" {
  name                = "acr${replace(var.name_suffix, "-", "")}pil"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = var.tags
}

# Shared identity so all 3 container apps can pull from ACR without each
# needing its own role assignment
resource "azurerm_user_assigned_identity" "aca" {
  name                = "id-aca-${var.name_suffix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}

resource "azurerm_role_assignment" "aca_acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.aca.principal_id
}

resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${var.name_suffix}"
  resource_group_name        = var.resource_group_name
  location                   = var.location
  log_analytics_workspace_id = var.log_analytics_workspace_id
  tags                       = var.tags
}

# ── Presidio PII service — internal only, nothing outside the environment can reach it ──
resource "azurerm_container_app" "presidio" {
  name                         = "ca-presidio-${var.name_suffix}"
  resource_group_name         = var.resource_group_name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                          = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.aca.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.aca.id
  }

  ingress {
    external_enabled = false
    target_port      = 8080
    transport        = "http"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    # min_replicas = 0 (scale-to-zero) saves cost at personal scale, but combined
    # with the backend's fail-closed PII policy (ADR-0011: mask_pii raises 503 if
    # Presidio is unreachable), the first request after idle pays presidio's ~30-90s
    # spaCy cold-start — worst case, a user-facing 503 if that's slower than the
    # backend's timeout. If that becomes a problem, change ONLY this line to
    # min_replicas = 1 (~$15-20/month always-on) — leave backend/frontend at 0.
    # Full tradeoff writeup: docs/adr/0013-container-apps-over-aks-apim.md (Risks).
    min_replicas = 0
    max_replicas = 1

    container {
      name   = "presidio"
      image  = local.placeholder_image
      cpu    = 1.0
      memory = "2Gi"
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }
}

# ── FastAPI backend — public ingress, talks to presidio over the internal environment DNS ──
resource "azurerm_container_app" "backend" {
  name                         = "ca-backend-${var.name_suffix}"
  resource_group_name         = var.resource_group_name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                          = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.aca.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.aca.id
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "http"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 2

    container {
      name   = "backend"
      image  = local.placeholder_image
      cpu    = 1.0
      memory = "2Gi"

      env {
        name  = "PRESIDIO_ENDPOINT"
        value = "https://${azurerm_container_app.presidio.ingress[0].fqdn}"
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }
}

# ── React CMS frontend — public ingress, static files served by nginx ──
resource "azurerm_container_app" "frontend" {
  name                         = "ca-frontend-${var.name_suffix}"
  resource_group_name         = var.resource_group_name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                          = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.aca.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.aca.id
  }

  ingress {
    external_enabled = true
    target_port      = 80
    transport        = "http"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 1

    container {
      name   = "frontend"
      image  = local.placeholder_image
      cpu    = 0.5
      memory = "1Gi"
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }
}

output "container_registry_login_server" { value = azurerm_container_registry.main.login_server }
output "container_registry_id"           { value = azurerm_container_registry.main.id }
output "identity_id"                     { value = azurerm_user_assigned_identity.aca.id }
output "identity_principal_id"           { value = azurerm_user_assigned_identity.aca.principal_id }
output "environment_id"                  { value = azurerm_container_app_environment.main.id }
output "backend_fqdn"                    { value = azurerm_container_app.backend.ingress[0].fqdn }
output "frontend_fqdn"                   { value = azurerm_container_app.frontend.ingress[0].fqdn }
output "presidio_fqdn"                   { value = azurerm_container_app.presidio.ingress[0].fqdn }
output "backend_name"                    { value = azurerm_container_app.backend.name }
output "frontend_name"                   { value = azurerm_container_app.frontend.name }
output "presidio_name"                   { value = azurerm_container_app.presidio.name }
