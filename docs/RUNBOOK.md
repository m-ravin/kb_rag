# KB RAG — Runbook

Operational guide for deploying, monitoring, and troubleshooting the KB RAG system.

---

## Deployment

### First-Time Provisioning

```bash
# 1. Authenticate Azure CLI
az login
az account set --subscription YOUR_SUBSCRIPTION_ID

# 2. Initialise and apply Terraform
cd infrastructure/terraform
terraform init
terraform apply -var="prefix=kb" -var="environment=prod"

# 3. Auto-generate .env from outputs
terraform output -raw env_file_content > ../../.env
```

Terraform provisions all 15 Azure resources (~15-20 minutes). After apply it automatically updates GitHub Secrets (ACR_LOGIN_SERVER, AKS_CLUSTER_NAME, etc.) via `gh secret set`.

### Subsequent Deployments

Push to `main` — GitHub Actions runs the `deploy.yml` workflow:

1. **sync-secrets** — pulls secrets from Key Vault → creates `kb-rag-secrets` Kubernetes Secret
2. **build** — Docker build + push to ACR (parallel with sync-secrets)
3. **deploy** — `kubectl apply` rolling update, waits for rollout

### Manual Deploy (emergency)

```bash
# Get AKS credentials
az aks get-credentials --resource-group rg-kb-prod --name aks-kb-prod

# Apply secrets from Key Vault
KV=kv-kb-prod-abc123
kubectl create secret generic kb-rag-secrets --namespace kb-rag \
  --from-literal=AZURE_OPENAI_KEY=$(az keyvault secret show --vault-name $KV --name openai-api-key --query value -o tsv) \
  --dry-run=client -o yaml | kubectl apply -f -

# Deploy a specific image tag
kubectl set image deployment/kb-rag-backend backend=YOUR_ACR.azurecr.io/kb-rag-backend:SHA --namespace kb-rag
kubectl rollout status deployment/kb-rag-backend --namespace kb-rag
```

---

## Health Checks

| Endpoint | Expected | Meaning |
|----------|----------|---------|
| `GET /health` | `{"status": "healthy"}` | FastAPI server is up |
| `GET /ready` | `{"status": "ready"}` | Redis connection verified |
| `kubectl get pods -n kb-rag` | All pods `Running` | AKS workloads healthy |

```bash
# Check pod status
kubectl get pods -n kb-rag -o wide

# Check backend logs
kubectl logs -n kb-rag -l app=kb-rag-backend --tail=100

# Check recent events
kubectl get events -n kb-rag --sort-by=.lastTimestamp | tail -20
```

---

## Monitoring

### Azure Monitor / App Insights

All API calls emit traces to Application Insights. Key queries in Log Analytics:

```kusto
-- Average Q&A latency over last 24h
customEvents
| where name == "qa_interaction"
| summarize avg(todouble(customDimensions.latency_ms)) by bin(timestamp, 1h)

-- PII detection rate
customEvents
| where name == "qa_interaction"
| summarize pii_rate = countif(tobool(customDimensions.flagged_pii)) * 100.0 / count()
```

### Dashboard Metrics

The CMS Dashboard (`/dashboard`) shows live metrics pulled from Cosmos MongoDB:
- Total questions answered
- Average latency (ms)
- Tokens used
- PII flag count
- Unsafe content flag count

### Alerts to configure in Azure Monitor

| Alert | Condition | Action |
|-------|-----------|--------|
| High latency | Avg Q&A latency > 5000ms for 5 min | Page on-call |
| Error rate spike | 5xx responses > 5% for 2 min | Page on-call |
| Redis unavailable | `/ready` returns non-200 | Page on-call |
| AKS pod crash | Pod restarts > 3 in 10 min | Notify team |

---

## Common Issues

### Backend pods not starting

```bash
kubectl describe pod -n kb-rag -l app=kb-rag-backend
```

**Cause**: Missing secrets. The pod requires `kb-rag-secrets` Kubernetes Secret.

**Fix**: Re-run the `sync-secrets` job manually:
```bash
gh workflow run deploy.yml --repo m-ravin/kb_rag
```

### Search returning no results

**Cause**: Azure AI Search index missing or empty.

**Fix**: Re-index by re-uploading documents through the CMS. The Azure Function rebuilds the index.

**Check index exists**:
```bash
az search index list \
  --service-name srch-kb-prod-abc123 \
  --resource-group rg-kb-prod \
  --query "[].name"
```

### Document stuck in "processing" status

**Cause**: Azure Function timed out (5-min limit on Consumption plan) for very large documents.

**Fix**:
1. Check Function App logs in Azure Portal → Function App → Monitor
2. Split large documents before uploading
3. Or upgrade to Premium plan (no timeout limit)

```bash
# Check function invocations
az functionapp logs show --name func-doc-proc-kb-prod --resource-group rg-kb-prod
```

### Redis cache not working

**Cause**: TLS certificate mismatch or connection string format.

**Check**: The Redis connection string must use `rediss://` (TLS) not `redis://` for Azure Cache for Redis.

**Verify connectivity**:
```bash
kubectl exec -n kb-rag -it $(kubectl get pod -n kb-rag -l app=kb-rag-backend -o name | head -1) \
  -- python -c "import redis; r = redis.from_url('$REDIS_CONNECTION'); print(r.ping())"
```

### Terraform state corruption

**Symptom**: `terraform plan` fails with state lock errors.

**Fix**:
```bash
# Force-unlock (use the lock ID from the error message)
terraform force-unlock LOCK_ID
```

---

## Rollback

### Roll back a bad deployment

```bash
# Check rollout history
kubectl rollout history deployment/kb-rag-backend -n kb-rag

# Roll back to previous version
kubectl rollout undo deployment/kb-rag-backend -n kb-rag

# Verify rollback
kubectl rollout status deployment/kb-rag-backend -n kb-rag
```

### Roll back infrastructure (Terraform)

```bash
cd infrastructure/terraform

# Restore previous state from Azure Blob backend
terraform state pull > current_state.json

# Apply a specific revision
# (use --target to limit scope if needed)
terraform apply -target=module.aks -auto-approve
```

---

## Scaling

### Scale AKS nodes

```bash
# Update node count in Terraform
# Edit infrastructure/terraform/variables.tf: aks_node_count = 4
terraform apply -var="aks_node_count=4"
```

### Scale Cosmos DB throughput

```bash
# Edit infrastructure/terraform/variables.tf: cosmos_throughput = 800
terraform apply -var="cosmos_throughput=800"
```

### Horizontal Pod Autoscaler

HPA is configured in `infrastructure/kubernetes/backend-deployment.yaml`:
- Min replicas: 2
- Max replicas: 10
- Scale up when CPU > 70%

---

## Teardown

```bash
# Delete all Azure resources (stops all billing)
cd infrastructure/terraform
terraform destroy -auto-approve

# Note: Key Vault uses soft-delete. Purge manually if needed:
az keyvault purge --name kv-kb-prod-abc123 --location eastus
```
