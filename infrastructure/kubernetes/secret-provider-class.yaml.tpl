# SecretProviderClass — maps Azure Key Vault secrets to a Kubernetes Secret.
# Rendered by terraform.yml after each apply (KEY_VAULT_NAME_PLACEHOLDER and
# TENANT_ID_PLACEHOLDER are substituted with real values from Terraform output).
#
# The AKS Key Vault CSI driver (enabled in the aks Terraform module) reads this
# class and syncs all listed secrets into a Kubernetes Secret named kb-rag-secrets.
# Pods reference that Secret via envFrom — no secrets are ever stored in Git.

apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: kb-rag-kv-secrets
  namespace: kb-rag
spec:
  provider: azure
  secretObjects:
    # This block creates the Kubernetes Secret that pods read via envFrom
    - secretName: kb-rag-secrets
      type: Opaque
      data:
        - objectName: openai-api-key
          key: AZURE_OPENAI_KEY
        - objectName: openai-endpoint
          key: AZURE_OPENAI_ENDPOINT
        - objectName: search-api-key
          key: AZURE_SEARCH_KEY
        - objectName: search-endpoint
          key: AZURE_SEARCH_ENDPOINT
        - objectName: cosmos-mongo-connection-string
          key: COSMOS_MONGO_CONNECTION
        - objectName: cosmos-gremlin-endpoint
          key: COSMOS_GREMLIN_ENDPOINT
        - objectName: cosmos-gremlin-key
          key: COSMOS_GREMLIN_KEY
        - objectName: redis-connection-string
          key: REDIS_CONNECTION
        - objectName: storage-connection-string
          key: STORAGE_CONNECTION
        - objectName: appinsights-connection-string
          key: APPINSIGHTS_CONNECTION_STRING
  parameters:
    usePodIdentity: "false"
    useVMManagedIdentity: "true"     # AKS uses its system-assigned managed identity
    keyvaultName: "KEY_VAULT_NAME_PLACEHOLDER"
    tenantId: "TENANT_ID_PLACEHOLDER"
    objects: |
      array:
        - |
          objectName: openai-api-key
          objectType: secret
        - |
          objectName: openai-endpoint
          objectType: secret
        - |
          objectName: search-api-key
          objectType: secret
        - |
          objectName: search-endpoint
          objectType: secret
        - |
          objectName: cosmos-mongo-connection-string
          objectType: secret
        - |
          objectName: cosmos-gremlin-endpoint
          objectType: secret
        - |
          objectName: cosmos-gremlin-key
          objectType: secret
        - |
          objectName: redis-connection-string
          objectType: secret
        - |
          objectName: storage-connection-string
          objectType: secret
        - |
          objectName: appinsights-connection-string
          objectType: secret
