# ADR-0010: Presidio PII Detection — Standalone Microservice

**Date**: 2026-05-11
**Status**: accepted
**Deciders**: KB RAG system design

## Context

PII detection must run on every inbound user question before it reaches the LLM and
before any question is written to the Q&A log. Microsoft Presidio (with a spaCy NLP
model) was initially introduced as an in-process Python library inside the FastAPI
backend. However, document processing in the Azure Function, future reporting pipelines,
and any additional services added to the platform all have the same PII detection
requirement. Duplicating the Presidio library and a ~500 MB spaCy model across every
service that needs it is wasteful and creates version-drift risk.

## Decision

We deploy Presidio as a **standalone REST microservice** (`presidio-service/`) that any
platform service calls over HTTP. The service wraps `presidio-analyzer` and
`presidio-anonymizer` in a FastAPI application, loads the spaCy model once at startup,
and exposes four endpoints:

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Liveness probe |
| `GET /entities` | List all supported entity types |
| `POST /analyze` | Return entity positions + scores (no masking) |
| `POST /anonymize` | Mask text given pre-computed analyzer results |
| `POST /redact` | Analyze + anonymize in one call (most callers use this) |

A custom `PatternRecognizer` for Malaysian NRIC (dashes and no-dashes forms) is
registered at startup inside the service — callers do not need to know about it.

The FastAPI backend's `safety_service.py` calls `POST /redact` for `mask_pii` and
`POST /analyze` for `detect_pii`. In Docker Compose the service is named
`presidio-service` and the backend resolves it by that name via Docker's internal DNS.
The Kubernetes deployment will run it as a ClusterIP service (not exposed externally).

## Alternatives Considered

### Alternative 1: In-process library (previous implementation)
- **Pros**: No network hop (10–50 ms lower latency); single Docker image; no extra
  container to operate; model failure affects only one pod
- **Cons**: spaCy model (~500 MB) loaded in every FastAPI replica — 3 replicas = 1.5 GB
  wasted memory; Azure Function must bundle its own copy; PII logic cannot be updated
  independently; no centralised audit point for all PII operations across services
- **Why not**: Once more than one service needs PII detection, in-process leads to
  duplicated model weight and version divergence. The microservice eliminates both.

### Alternative 2: Azure AI Language PII endpoint (managed cloud service)
- **Pros**: Fully managed; no infrastructure to operate; automatically updated models;
  multilingual support without extra config
- **Cons**: Every request sends potentially sensitive medical text to an external
  Azure endpoint; async job polling was proven broken in the original implementation
  (the job result was never collected, making PII detection silently a no-op); adds
  per-call cost; latency depends on Azure region cold-start
- **Why not**: A medical PIL system should avoid routing patient questions through an
  external cloud endpoint when an equivalent local service is available. The prior
  implementation also demonstrated how easy it is to misuse the async job API.

### Alternative 3: Official Microsoft Presidio Docker images
- **Pros**: No code to maintain; kept up to date by Microsoft
- **Cons**: Official images do not support registering custom recognizers at runtime
  without custom startup scripts; adding the Malaysian NRIC recognizer requires either
  a custom child image or a post-start API call that may not survive container restarts;
  less transparent than owning the thin wrapper
- **Why not**: The wrapper is ~100 lines of FastAPI code. Owning it gives full control
  over custom recognizers, API shape, and error handling with minimal maintenance cost.

## Consequences

### Positive
- spaCy model loaded once in one container — all backend replicas share it; no
  per-replica memory overhead (~500 MB saved per additional replica)
- Presidio version and spaCy model updated by rebuilding one image, independent of
  backend release cadence
- Azure Function, FastAPI backend, and any future service call the same endpoint —
  single source of PII logic for the whole platform
- `/entities` endpoint makes supported entity types self-documenting at runtime

### Negative
- Additional network round-trip per request (+5–20 ms on the same cluster)
- Extra container to deploy, monitor, and keep healthy
- `docker-compose up` now waits for Presidio to pass a health check before starting
  the backend; cold start is ~60–90 seconds (spaCy model loading)
- Presidio becomes a critical synchronous dependency — a `mask_pii` call that times
  out degrades the Q&A endpoint

### Risks
- **Availability**: `safety_service.py` catches all exceptions from the Presidio
  endpoints and logs warnings. On `/redact` failure, `mask_pii` returns the original
  text unchanged (fail-open) to avoid blocking the Q&A pipeline; callers should alert
  on repeated warnings. For production, run ≥2 Presidio replicas.
- **Not externally accessible**: The service must be on the internal Kubernetes network
  (ClusterIP). Exposing it via Ingress would allow anyone to submit text for PII
  scanning at our cost.
