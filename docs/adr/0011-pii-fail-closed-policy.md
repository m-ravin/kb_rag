# ADR-0011: PII Fail-Closed Policy for Medical PIL System

**Date**: 2026-05-11
**Status**: accepted
**Deciders**: KB RAG system design

## Context

The Presidio PII microservice is a synchronous critical dependency: every user
question passes through `detect_pii` + `mask_pii` before reaching the LLM or
being logged. When Presidio is unreachable (cold-start, network blip, OOM kill),
the previous implementation returned `(False, [])` from `detect_pii` and the
original unmasked text from `mask_pii` — a fail-open policy. For a generic
knowledge base this is acceptable; for a medical PIL system handling patient
questions that may contain names, dates of birth, NHS numbers, and drug dosages,
fail-open means raw PII silently reaches GPT-4o and persists in MongoDB logs
during any outage window.

## Decision

We adopt a **fail-closed** policy for PII handling:
- `detect_pii` returns `(True, ["UNKNOWN"])` on any Presidio connectivity failure,
  signalling "assume PII present"
- `mask_pii` raises HTTP 503 on failure, blocking the Q&A pipeline until Presidio
  recovers rather than passing unmasked text to the LLM

## Alternatives Considered

### Alternative 1: Fail-open (previous implementation)
- **Pros**: Q&A remains available during Presidio outages; users see no errors
- **Cons**: Raw PII reaches GPT-4o and is logged to MongoDB with no masking;
  compliance posture is silently degraded with no operational signal
- **Why not**: Unacceptable for a medical system — an outage becomes an invisible
  data protection incident rather than a visible service degradation

### Alternative 2: Local regex fallback on Presidio failure
- **Pros**: Partial PII coverage maintains availability
- **Cons**: Regex PII detection has high false-positive (redacting dosage numbers)
  and false-negative (missing context-dependent PII) rates; already rejected once
  in the Presidio migration (see ADR-0010)
- **Why not**: Gives false confidence — users believe PII is masked when it may
  not be; the regex failures that motivated moving to Presidio still apply here

### Alternative 3: Circuit breaker with cached last-known-good state
- **Pros**: Graceful degradation; can keep serving with stale analysis
- **Cons**: Significant complexity; stale state may itself be stale or wrong;
  doesn't meaningfully reduce PII risk since the question text changes each call
- **Why not**: Complexity not justified; the right signal for PII service failure
  is a visible 503, not a silent degradation

## Consequences

### Positive
- Presidio outages produce visible HTTP 503 errors and ERROR-level log events —
  no silent data protection regression
- GDPR/PDPA exposure is bounded: PII cannot reach GPT-4o or MongoDB logs if
  the masking service is unavailable
- Operational monitoring can alert on 503 spikes and correlate with Presidio
  health before any PII is at risk

### Negative
- Q&A is unavailable during Presidio outages instead of degrading gracefully
- Cold starts (~60–90 s for spaCy model loading) cause a brief startup window
  where Q&A returns 503 — mitigated by Docker Compose `service_healthy` dependency
  and Kubernetes readiness probe on the Presidio pod

### Risks
- **Availability**: Presidio must be highly available. Mitigation: run ≥2 replicas
  with HPA; configure Kubernetes readiness probe on `GET /health` before marking
  the pod ready
- **False positives on failure**: `detect_pii` returning `(True, ["UNKNOWN"])` causes
  `mask_pii` to be called even when there may be no PII — acceptable cost given the
  context
