variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "name_suffix" { type = string }
variable "subnet_id" { type = string }
variable "node_count" { type = number }
variable "node_vm_size" { type = string }
variable "tags" { type = map(string) }

resource "azurerm_kubernetes_cluster" "main" {
  name                = "aks-${var.name_suffix}"
  location            = var.location
  resource_group_name = var.resource_group_name
  dns_prefix          = "pil-${var.name_suffix}"

  default_node_pool {
    name                = "system"
    node_count          = var.node_count
    vm_size             = var.node_vm_size
    vnet_subnet_id      = var.subnet_id
    enable_auto_scaling = true
    min_count           = 1
    max_count           = 5
    os_disk_size_gb     = 128
  }

  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin    = "azure"
    load_balancer_sku = "standard"
  }

  # Enable Key Vault CSI driver so pods can read secrets directly
  key_vault_secrets_provider {
    secret_rotation_enabled = true
  }

  tags = var.tags
}

# Grant AKS identity permission to pull images from ACR (if ACR is added later)
resource "azurerm_container_registry" "main" {
  name                = "acr${replace(var.name_suffix, "-", "")}pil"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "Standard"
  admin_enabled       = false
  tags                = var.tags
}

resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.main.kubelet_identity[0].object_id
}

output "cluster_name"      { value = azurerm_kubernetes_cluster.main.name }
output "kube_config"       { value = azurerm_kubernetes_cluster.main.kube_config_raw; sensitive = true }
output "acr_login_server"  { value = azurerm_container_registry.main.login_server }
