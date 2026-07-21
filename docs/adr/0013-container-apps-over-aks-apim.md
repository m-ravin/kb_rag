# ADR-0013: Azure Container Apps Replaces AKS + API Management

**Date**: 2026-07-21
**Status**: accepted
**Deciders**: KB RAG system design

## Context

The system originally ran the backend and CMS frontend on AKS (2× `Standard_D4s_v3` nodes, autoscale 1–5) fronted by API Management (`Developer_1` SKU) for rate limiting and gateway concerns. That architecture assumed sustained, production-level traffic. In practice this deployment is used as a personal/learning project with low, bursty traffic — a handful of documents and queries per day, not a continuously-loaded production workload. At those volumes, AKS and APIM together account for roughly $350+/month in always-on compute (2 VMs running 24/7 plus a non-stoppable APIM instance), regardless of whether the system is actually being used. Neither AKS worker nodes nor APIM have a free tier.

## Decision

We replace AKS and API Management with **Azure Container Apps** on the Consumption plan (`modules/container_apps`). Three container apps run in one Container Apps Environment: `backend` (FastAPI, external ingress), `frontend` (nginx-served React build, external ingress), and `presidio` (internal ingress only, reachable solely from `backend` over the environment's internal DNS). All three scale to zero when idle. Rate limiting, previously an APIM policy, is handled in-app via the existing `slowapi`-based limiter in `backend/core/limiter.py`.

## Alternatives Considered

### Alternative 1: Keep AKS, shrink to a single small node
- **Pros**: No architecture change, no rewrite of `infrastructure/kubernetes/*` manifests or the `deploy.yml` `kubectl` rollout flow
- **Cons**: Even a single small VM (e.g. `Standard_B2s`) still bills 24/7 whether or not it's serving traffic; AKS control plane and node-pool operational overhead (upgrades, patching cadence) is disproportionate to a personal-scale workload
- **Why not**: The core cost driver — paying for idle compute — isn't solved by downsizing, only reduced. Scale-to-zero is the only way to make idle time free.

### Alternative 2: Azure App Service (single app, both backend and frontend)
- **Pros**: Simpler mental model than Container Apps; mature platform; easy custom domains/TLS
- **Cons**: App Service plans (even Basic B1) bill continuously and don't scale to zero; combining backend + frontend + presidio into one app reintroduces the "everything in one process" problem this system's own `document_processor` ADR (0003) already argued against for a different component
- **Why not**: No scale-to-zero option removes the main cost benefit being sought.

### Alternative 3: Drop Presidio's own container, run it as a Python library import inside the backend process
- **Pros**: One fewer container app to manage; no internal-ingress networking to configure
- **Cons**: Presidio's `en_core_web_lg` spaCy model is a large in-memory dependency (per ADR-0010, this is exactly why Presidio was split out as a microservice in the first place — to keep the FastAPI backend's own container lean and avoid loading the model into every backend worker)
- **Why not**: Contradicts ADR-0010's reasoning, which still applies regardless of the underlying compute platform.

## Consequences

### Positive
- Idle cost drops from ~$350+/month (AKS + APIM) to near-zero when the app isn't being used — Consumption plan bills per vCPU-second/GiB-second actually consumed
- Container images, Dockerfiles, and `docker-compose.yml` (local dev) are unchanged — this is an infrastructure swap, not an application rewrite
- `backend/core/limiter.py` already existed and already provided per-IP rate limiting; no new code was needed to replace APIM's rate-limit policy
- One shared user-assigned managed identity handles ACR pull for all three apps instead of per-node kubelet identity plumbing

### Negative
- **Cold start latency**: scale-to-zero means the first request after idle pays a cold-start cost. This is worst for `presidio` — its `en_core_web_lg` model load takes 30–90 seconds per the existing health-check `start_period` in `docker-compose.yml`. A user's first query after idle time will be noticeably slower.
- Container Apps has a smaller feature surface than full Kubernetes (no custom CRDs, no DaemonSets, no arbitrary Helm charts) — acceptable here since none of those were in use, but worth knowing if requirements grow.
- `infrastructure/kubernetes/*` manifests and `modules/aks` / `modules/apim` are now dead weight; removed in this change rather than left to rot.

### Risks
- **Cold-start UX regression on presidio**: mitigated by keeping `min_replicas = 0` only for `presidio`/`frontend`/`backend` at personal scale where cost matters more than latency; if usage grows, set `min_replicas = 1` on `presidio` specifically (accepting ~$15–20/month of always-on cost) to eliminate its cold start while leaving `backend`/`frontend` scaling to zero.
- **Placeholder image on first apply**: `modules/container_apps` provisions each container app with a public placeholder image (`mcr.microsoft.com/azuredocs/containerapps-helloworld`) so `terraform apply` succeeds before any image has been pushed to ACR. `lifecycle.ignore_changes` on the image field stops later `terraform apply` runs from reverting the real image that CI/CD deploys. If someone runs `terraform apply` before ever running the deploy pipeline, the apps will serve the placeholder, not an error state — worth knowing when debugging "why is my API not responding" during first-time setup.

### Note
This updates the module list referenced in ADR-0004 (Terraform Modular IaC) — `aks` and `apim` modules are removed, `container_apps` is added. ADR-0004's underlying decision (modular Terraform) is unaffected and remains accepted.
