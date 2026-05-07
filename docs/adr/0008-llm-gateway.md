# ADR-0008: LLM Gateway — Direct Azure OpenAI with API Management Rate Limiting (v1)

**Date**: 2026-05-07
**Status**: accepted (v1) — gateway enrichment proposed for v2
**Deciders**: KB RAG system design

## Context

KB RAG calls Azure OpenAI for six distinct operations: embeddings, question type detection, keyword extraction, answer generation, wording tuning, and compliance checking. In v1 the FastAPI backend calls Azure OpenAI directly via the SDK. As usage grows, this creates visibility gaps: we cannot see cost per session, cannot swap models without a code deploy, cannot fallback to a cheaper model when GPT-4o is throttled, and cannot replay prompts for debugging. Azure API Management is already deployed for external-facing rate limiting, but it is not wired as an LLM-aware proxy.

## Decision

For **v1** we use direct Azure OpenAI SDK calls from `backend/services/llm_service.py`, with Azure API Management providing basic rate limiting (100 req/min per IP) on the public-facing endpoint. This is the current implementation.

For **v2** (tracked as a follow-up), we will introduce **LiteLLM as an internal LLM gateway** deployed as a sidecar or separate AKS deployment. All OpenAI calls will route through LiteLLM, which provides model routing, fallbacks, cost tracking, and prompt logging without changing the OpenAI SDK interface.

## Alternatives Considered

### Alternative 1: No gateway, direct SDK forever
- **Pros**: Zero added latency; simplest architecture; one fewer service to operate
- **Cons**: No cost attribution per user or session; model swaps require code deploys; no fallback when GPT-4o is throttled; no prompt replay for debugging; no semantic caching at the LLM layer
- **Why not** (for v2): At scale, the lack of cost visibility makes budgeting impossible. A single runaway query loop can exhaust the monthly OpenAI quota with no alerting. The gateway pays for itself in the first week of production traffic.

### Alternative 2: Azure API Management as LLM gateway
- **Pros**: Already deployed in the stack; supports request transformation and retry policies; native Azure integration; no extra service to deploy
- **Cons**: APIM is not LLM-aware — it cannot parse OpenAI's streaming response format, route by model, track token consumption per request, or implement semantic caching; APIM policies are XML-based and difficult to test
- **Why not**: APIM is the right tool for HTTP-level rate limiting and auth. It is the wrong tool for LLM-specific concerns (token budgeting, model routing, prompt versioning). Using APIM for LLM gateway would require complex XML policies to re-implement what LiteLLM does natively.

### Alternative 3: Portkey.ai (managed LLM gateway SaaS)
- **Pros**: Zero infrastructure; semantic caching; observability dashboard; prompt versioning; model fallbacks; supports Azure OpenAI
- **Cons**: Another external SaaS dependency; data (prompts and completions) leaves our Azure tenant to Portkey's servers — a data residency concern for knowledge bases containing sensitive content; monthly SaaS cost on top of OpenAI cost
- **Why not** (for now): The data residency concern is a blocker for any knowledge base containing proprietary or sensitive content. Self-hosted LiteLLM keeps all prompt/completion data within our Azure VNet.

### Alternative 4: Build a custom gateway in FastAPI
- **Pros**: Full control; no extra dependency; can implement exactly what we need
- **Cons**: Maintains a second FastAPI application; reimplements features LiteLLM already has (retry logic, fallback, streaming proxy, cost tracking); engineering cost
- **Why not**: LiteLLM is open-source, self-hostable, and covers 95% of the needed functionality. Building a custom gateway is a classic case of NIH (Not Invented Here) syndrome.

## Consequences

### Positive (v1 current state)
- Zero added latency — no proxy hop between FastAPI and Azure OpenAI
- Simple architecture — one service, one configuration file
- No new failure modes introduced

### Negative (v1 gaps, addressed in v2)
- **No cost tracking per session**: Total OpenAI spend is visible in Azure Cost Management but not attributable to individual sessions, users, or document types
- **No model fallback**: If GPT-4o is throttled, all requests fail until the quota resets. A gateway would automatically fall back to `gpt-4o-mini` for non-critical tasks (keyword extraction, language detection)
- **No prompt versioning**: Changing a system prompt requires a code change and redeploy. A gateway enables prompt A/B testing without deployment
- **No LLM-layer semantic cache**: Redis caches search results but not LLM completions. Two users asking semantically identical questions after cache expiry each pay a full GPT-4o call

### Risks
- **v1 quota exhaustion**: Without per-session token budgets, a malicious or buggy client can exhaust the monthly OpenAI quota. Mitigation: Azure API Management rate limits to 100 requests/minute/IP; Azure OpenAI quotas configured in the Terraform `openai` module (30k TPM for GPT-4o, 120k TPM for embeddings).

## v2 Implementation Notes (LiteLLM)

```
AKS Pod: FastAPI backend
  │
  ▼
AKS Pod: LiteLLM (litellm proxy --config litellm_config.yaml)
  │
  ▼
Azure OpenAI (GPT-4o, text-embedding-3-small)
  └─ fallback: gpt-4o-mini for keyword extraction / language detection
```

LiteLLM config (`litellm_config.yaml`):
```yaml
model_list:
  - model_name: gpt-4o
    litellm_params:
      model: azure/gpt-4o
      api_base: ${AZURE_OPENAI_ENDPOINT}
      api_key: ${AZURE_OPENAI_KEY}
  - model_name: gpt-4o-mini
    litellm_params:
      model: azure/gpt-4o-mini
      api_base: ${AZURE_OPENAI_ENDPOINT}
      api_key: ${AZURE_OPENAI_KEY}

router_settings:
  routing_strategy: usage-based-routing
  fallbacks: [{"gpt-4o": ["gpt-4o-mini"]}]

general_settings:
  master_key: ${LITELLM_MASTER_KEY}
  database_url: ${LITELLM_DB_URL}  # Postgres for usage tracking
```
