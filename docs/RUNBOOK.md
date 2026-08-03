# KB RAG — Runbook

Operational guide for deploying, monitoring, and troubleshooting the KB RAG system.

> This runbook describes the **Azure Container Apps** architecture (post [ADR-0013](adr/0013-container-apps-over-aks-apim.md)). There is no AKS, `kubectl`, or Kubernetes manifest involved anywhere in this stack — if you see `kubectl` commands referenced elsewhere, they're stale.

**Current resource names (dev, `rg-pil-dev` unless noted):**

| Resource | Name |
|---|---|
| Resource group (new resources) | `rg-pil-dev` |
| Backend Container App | `ca-backend-pil-dev63u6v3` |
| Frontend Container App | `ca-frontend-pil-dev63u6v3` |
| Presidio Container App | `ca-presidio-pil-dev63u6v3` (internal ingress only) |
| Container Registry | `acrpildev63u6v3pil` |
| Function App | `func-doc-proc-pil-dev63u6v3` |
| Application Insights | `appi-pil-dev` |
| Search (reused, `rsg-dev-az1-dp`) | `srch-dev-az1-dp` |
| Storage (reused, `rsg-dev-az1-dp`) | `stdevaz1dp001` |
| Key Vault (reused, `rsg-dev-az1-dp`) | `kv-dev-az1-dp` |

Reused-resource rationale: [ADR-0014](adr/0014-reuse-existing-dev-subscription-resources.md).

---

## Deployment

### First-Time Provisioning

```bash
az login
az account set --subscription YOUR_SUBSCRIPTION_ID

cd infrastructure/terraform
terraform init
terraform apply

# Auto-generate .env from outputs
terraform output -raw env_file_content > ../../.env
```

Terraform provisions the Container Apps environment, ACR, Function App, and
new-resource-group resources; it cross-references the reused Search/Storage/Key
Vault resources in `rsg-dev-az1-dp` (ADR-0014). After apply, no images exist in
ACR yet — build and push them before the Container Apps can start (see below).

### Building and Pushing Images

Each Container App needs an image in ACR before it can run. Use `az acr build`
(remote build — no local Docker required):

```bash
# Backend and frontend build from the repo root
az acr build --registry acrpildev63u6v3pil --image kb-rag-backend:v1 \
  --file Dockerfile.backend .
az acr build --registry acrpildev63u6v3pil --image kb-rag-frontend:v1 \
  --file Dockerfile.frontend .

# Presidio's build context is its own subdirectory, not repo root
az acr build --registry acrpildev63u6v3pil --image kb-rag-presidio:v1 \
  --file presidio-service/Dockerfile presidio-service/
```

> **Windows / local `az` CLI note:** log streaming for `az acr build` can crash
> with `UnicodeEncodeError: 'charmap' codec can't encode character '✓'`
> (a cp1252-codepage bug in the CLI's log streamer, not a build failure). If you
> hit this, verify the build actually succeeded instead of assuming failure:
> ```bash
> az acr task list-runs --registry acrpildev63u6v3pil -o table
> az acr repository show-tags --name acrpildev63u6v3pil --repository kb-rag-backend
> ```

Then point each Container App at its image:

```bash
az containerapp update --name ca-backend-pil-dev63u6v3 --resource-group rg-pil-dev \
  --image acrpildev63u6v3pil.azurecr.io/kb-rag-backend:v1
az containerapp update --name ca-frontend-pil-dev63u6v3 --resource-group rg-pil-dev \
  --image acrpildev63u6v3pil.azurecr.io/kb-rag-frontend:v1
az containerapp update --name ca-presidio-pil-dev63u6v3 --resource-group rg-pil-dev \
  --image acrpildev63u6v3pil.azurecr.io/kb-rag-presidio:v1
```

### Subsequent Deployments (CI)

Trigger the `deploy.yml` workflow manually (`workflow_dispatch` — deployment
requires explicit human confirmation, it does not run on every push):

```bash
gh workflow run deploy.yml --repo m-ravin/kb_rag
```

It runs three jobs in order:
1. **build** — Docker build + push all 3 images to ACR, tagged with the Git SHA
2. **configure-secrets** — points each Container App's secrets at Key Vault references (values never pass through the workflow or its logs)
3. **deploy** — `az containerapp update --image ...` for presidio, backend, then frontend; prints revision status at the end

### Manual Deploy (emergency)

```bash
az login

# Deploy a specific image tag directly
az containerapp update --name ca-backend-pil-dev63u6v3 --resource-group rg-pil-dev \
  --image acrpildev63u6v3pil.azurecr.io/kb-rag-backend:<tag>

# Watch the new revision come up
az containerapp revision list --name ca-backend-pil-dev63u6v3 --resource-group rg-pil-dev \
  --query "[0].{name:name, runningState:properties.runningState, healthState:properties.healthState}" -o table
```

---

## Health Checks

| Endpoint | Expected | Meaning |
|----------|----------|---------|
| `GET https://<backend_fqdn>/health` | `{"status": "healthy"}` | FastAPI server is up |
| `GET https://<backend_fqdn>/ready` | `{"status": "ready"}` | Redis connection verified (when configured) |
| Presidio `/health` | `{"status": "healthy"}` | Presidio + spaCy model loaded — **internal ingress only**, not reachable from outside the Container Apps environment; check via backend logs or `az containerapp exec` into another app in the same environment |

Get the public FQDNs:
```bash
az containerapp show --name ca-backend-pil-dev63u6v3 --resource-group rg-pil-dev \
  --query properties.configuration.ingress.fqdn -o tsv
az containerapp show --name ca-frontend-pil-dev63u6v3 --resource-group rg-pil-dev \
  --query properties.configuration.ingress.fqdn -o tsv
```

```bash
# Check all 3 apps at a glance
az containerapp list --resource-group rg-pil-dev \
  --query "[].{name:name, runningState:properties.runningStatus, image:properties.template.containers[0].image}" -o table

# Check replica count / revision health for one app
az containerapp revision list --name ca-backend-pil-dev63u6v3 --resource-group rg-pil-dev \
  --query "[].{name:name, active:properties.active, replicas:properties.replicas, health:properties.healthState}" -o table

# Tail logs
az containerapp logs show --name ca-backend-pil-dev63u6v3 --resource-group rg-pil-dev --follow
```

---

## Monitoring

### Azure Monitor / App Insights

All API calls emit traces to Application Insights (`appi-pil-dev`). Key queries in Log Analytics:

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

The CMS Dashboard (`/dashboard`) shows live metrics pulled from Cosmos MongoDB
(`qa_logs` collection, aggregated by `GET /manage/metrics`):
- Total questions answered
- Average latency (ms)
- Tokens used
- PII flag count
- Unsafe content flag count

Raw per-question records (question/answer text, not just aggregates) live in
the `qa_logs` Cosmos collection but aren't exposed through any UI or API
endpoint yet — query Cosmos directly (Data Explorer or `mongosh`) if you need
individual transcripts:
```javascript
db.qa_logs.find().sort({ created_at: -1 }).limit(50)
```

### Alerts configured

Failure alerts (`modules/monitoring/main.tf`) go to the account owner's email
whenever `AppTraces`/`AppExceptions` shows `SeverityLevel >= 3` or a message
containing `"Failed to process"` / `"Reconciliation drift"`. This is a Log
Analytics-scoped scheduled query alert — classic Function App metric alerts
don't fire against this workspace-based App Insights resource.

---

## Common Issues

### Container App stuck at "Activating" / never becomes Healthy

**Symptom:** `az containerapp revision list` shows `runningState: Activating`
indefinitely (or later `Degraded`/`Unhealthy`), and `az containerapp logs show`
returns `"Kubernetes error happened. Closing the connection."` when Azure tries
to attach logs.

**Cause:** almost always the image it's trying to pull no longer exists in ACR
— e.g. the tag or the whole repository was deleted. Container Apps does not
surface a clear "image pull failed" error in this state; the platform-level
symptom above is the tell.

**Fix:** confirm the repository/tag exists, then rebuild and redeploy if not:
```bash
az acr repository list --name acrpildev63u6v3pil -o table
az acr repository show-tags --name acrpildev63u6v3pil --repository kb-rag-backend
```
If missing, rebuild via `az acr build` (see Deployment section above) and
`az containerapp update --image ...` to point the app at the fresh image.

### Presidio service not healthy / Q&A returns 503

**Symptoms:** Q&A requests return HTTP 503 with a detail like `"PII screening
service temporarily unavailable. Please try again shortly."` The pipeline is
blocked (fail-closed) — PII cannot reach the LLM while Presidio is down; see
[ADR-0011](adr/0011-pii-fail-closed-policy.md) for the rationale.

**Cause A — cold start (most common, not an actual failure):** Presidio's
Container App has `minReplicas` unset (scales to zero) and loads a ~380 MB
spaCy `en_core_web_lg` model on startup. A cold start after scale-to-zero
takes roughly 20–30 seconds. Retrying the request after that window succeeds.

**Cause B — image missing from ACR:** same failure mode as the stuck-Activating
issue above, specific to the `kb-rag-presidio` repository. Rebuild via
`az acr build --registry acrpildev63u6v3pil --image kb-rag-presidio:vN --file presidio-service/Dockerfile presidio-service/`
(note the build context is `presidio-service/`, not repo root, unlike the
other two images).

### Frontend shows a generic "Request failed" error for everything

**Cause:** a fixed historical bug — the frontend's catch block used to swallow
all error detail behind one hardcoded string, so a Presidio 503 looked
identical to a genuine network failure. Fixed in `frontend/src/pages/QATest.tsx`
(`getErrorMessage()` narrows `axios.isAxiosError` and surfaces the backend's
actual `detail` field). If this regresses, check that helper hasn't been
reverted or bypassed.

### Search returning no results

**Cause:** Azure AI Search index missing or empty.

**Fix:** re-index by re-uploading documents through the CMS — the Azure
Function rebuilds the index.

```bash
az search index list --service-name srch-dev-az1-dp --resource-group rsg-dev-az1-dp \
  --query "[].name"
```

### Document stuck in "processing" status

See `docs/CONTRIBUTING.md`'s "Live ingestion pipeline" section for the full
diagnostic pattern (App Insights trace query → Mongo status check → blob
archive check). Common causes: Function timeout on very large documents, or
magic-byte validation rejecting a file whose content doesn't match its
extension.

### Redis cache not working

**Cause:** TLS certificate mismatch or connection string format — Azure Cache
for Redis requires `rediss://` (TLS), not `redis://`.

```bash
az containerapp exec --name ca-backend-pil-dev63u6v3 --resource-group rg-pil-dev \
  --command "python -c \"import redis; r = redis.from_url('$REDIS_CONNECTION'); print(r.ping())\""
```

### Terraform state corruption

**Symptom:** `terraform plan` fails with state lock errors.

```bash
terraform force-unlock LOCK_ID
```

---

## Rollback

Container Apps keeps prior revisions around (unless explicitly deactivated),
so rollback is a traffic-routing operation, not a redeploy:

```bash
# List revisions, newest first
az containerapp revision list --name ca-backend-pil-dev63u6v3 --resource-group rg-pil-dev \
  --query "[].{name:name, active:properties.active, created:properties.createdTime}" -o table

# Route 100% of traffic back to a known-good revision
az containerapp ingress traffic set --name ca-backend-pil-dev63u6v3 --resource-group rg-pil-dev \
  --revision-weight <previous-revision-name>=100

# Once confirmed stable, deactivate the bad revision
az containerapp revision deactivate --name ca-backend-pil-dev63u6v3 --resource-group rg-pil-dev \
  --revision <bad-revision-name>
```

### Roll back infrastructure (Terraform)

```bash
cd infrastructure/terraform
terraform state pull > current_state.json
terraform apply -target=module.container_apps  # scope to the affected module
```

---

## Scaling

Scaling is `min`/`max` replica counts on each Container App (Consumption plan,
scale-to-zero-capable) — there is no HPA YAML or node pool to manage.

```bash
az containerapp update --name ca-backend-pil-dev63u6v3 --resource-group rg-pil-dev \
  --min-replicas 1 --max-replicas 3
```

Note: the Azure CLI requires `--max-replicas` to be at least 1 — you cannot
scale an app to a true zero-replica state this way. To fully stop an app
(e.g. before a maintenance window or before deleting its image registry), use
`az containerapp revision deactivate` on its active revision instead (see
Teardown below).

### Scale Cosmos DB throughput

```bash
# Edit infrastructure/terraform/variables.tf: cosmos_throughput = 800
terraform apply -var="cosmos_throughput=800"
```

---

## Container Registry — Cost Notes

`acrpildev63u6v3pil` is Basic SKU (~$5/month flat, 10 GB storage included) —
already the cheapest paid tier, and billed 24/7 regardless of usage. For this
dev-only registry, the only meaningful further saving is **not letting it sit
provisioned while genuinely idle** — see Teardown below. Keep tag hygiene tight
(one current tag per repo, not an accumulating `v1..v40` history) so storage
never approaches the 10 GB threshold as more builds happen over time.

**Do not manually delete individual images/tags from ACR outside of a
deliberate teardown.** Doing so while any Container App is still pointing at
that tag causes the "stuck Activating" failure above the next time that app's
revision restarts or scales from zero — this has happened in this environment
before and looks like a platform bug rather than a missing-image problem until
you check `az acr repository list`.

---

## Teardown

Because Presidio scales to zero and cold-starts routinely, **never delete the
registry (or its images) while any Container App is still live** — the next
scale-from-zero event will fail to pull and the app breaks. Stop the apps
first:

```bash
# 1. Deactivate each app's active revision (stops all replicas deliberately)
for app in ca-frontend-pil-dev63u6v3 ca-presidio-pil-dev63u6v3 ca-backend-pil-dev63u6v3; do
  rev=$(az containerapp revision list --name "$app" --resource-group rg-pil-dev \
    --query "[?properties.active].name | [0]" -o tsv)
  az containerapp revision deactivate --name "$app" --resource-group rg-pil-dev --revision "$rev"
done

# 2a. Delete just the registry (cheapest partial teardown)
az acr delete --name acrpildev63u6v3pil --resource-group rg-pil-dev --yes

# 2b. OR delete everything this project provisioned (stops all billing for it)
cd infrastructure/terraform
terraform destroy
```

Reused resources (`srch-dev-az1-dp`, `stdevaz1dp001`, `kv-dev-az1-dp` in
`rsg-dev-az1-dp`) are **not** touched by `terraform destroy` — they're
referenced via Terraform data sources, not managed resources (ADR-0014).

Key Vault uses soft-delete; purge manually if you need the name back immediately:
```bash
az keyvault purge --name kv-dev-az1-dp --location centralindia
```

### Restoring after teardown

1. `terraform apply` (recreates ACR + Container Apps environment if destroyed)
2. Rebuild all 3 images via `az acr build` (see Deployment section)
3. `az containerapp update --image ...` for each app
4. Reactivate/recreate revisions — a fresh `az containerapp update` creates a
   new active revision automatically, so explicit reactivation usually isn't
   needed unless you deactivated without changing the image.
5. Restore prior scale settings if you changed them:

| App | max-replicas |
|---|---|
| `ca-frontend-pil-dev63u6v3` | 1 |
| `ca-presidio-pil-dev63u6v3` | 1 |
| `ca-backend-pil-dev63u6v3` | 2 |
