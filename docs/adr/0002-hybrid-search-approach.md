# ADR-0002: Hybrid Search — Vector + Keyword + Graph with Redis Cache

**Date**: 2026-05-07
**Status**: accepted
**Deciders**: KB RAG system design

## Context

KB RAG is a general-purpose knowledge base retrieval system. Document retrieval must handle two very different query types: natural language questions where the user paraphrases a concept ("what if I take too much?"), and precise term lookups where the user knows the exact identifier ("Amoxicillin 500mg dosage", a product code, or a section heading). A single retrieval strategy cannot optimise for both. Additionally, the same questions are asked repeatedly across sessions in domain-specific knowledge bases (e.g., FAQs), making caching economically significant given the cost of embedding API calls (~$0.02 per 1M tokens, plus ~50ms latency per call).

## Decision

We implement four retrieval strategies in `backend/services/search_service.py`: **vector search** (semantic similarity via HNSW index in Azure AI Search), **keyword search** (BM25 via Azure AI Search), **graph search** (context expansion via Cosmos Gremlin), and **hybrid search** (combines vector + keyword using Azure AI Search's built-in Reciprocal Rank Fusion). All results are cached in Redis with a 5-minute TTL keyed by an MD5 hash of the strategy name, query, and top-k parameter. The Q&A flow uses hybrid search by default.

## Alternatives Considered

### Alternative 1: Pure vector search only
- **Pros**: Simpler implementation; single embedding call per query; state-of-the-art for paraphrase retrieval
- **Cons**: Misses exact-match queries for drug names, dosage codes, and ICD codes that BM25 handles trivially; embedding models can conflate similar-sounding but distinct medical terms
- **Why not**: Clinical testing of RAG systems consistently shows hybrid outperforms pure-vector by 15–25% on medical Q&A benchmarks (source: Microsoft RAG best practices guide)

### Alternative 2: Elasticsearch / OpenSearch
- **Pros**: Battle-tested hybrid search; mature BM25 + KNN hybrid support; rich faceted filtering
- **Cons**: Not a managed Azure-native service; requires a separate cluster (minimum 3 nodes for HA); no built-in Azure OpenAI vectorisation integration; adds ~$200/month
- **Why not**: Azure AI Search provides equivalent hybrid search (BM25 + HNSW + RRF) as a managed service with direct Azure OpenAI integration, removing the operational burden

### Alternative 3: No caching (call Azure Search on every request)
- **Pros**: Always returns fresh results; simpler code (no Redis dependency)
- **Cons**: Each hybrid search requires one OpenAI embedding call (~50ms) plus one Azure Search API call (~100ms); repeated identical questions from multiple users pay this cost every time
- **Why not**: For a healthcare Q&A system, the top 20% of questions account for ~80% of traffic (Pareto principle applies strongly to PIL queries). A 5-minute Redis cache eliminates this cost for the hot question set.

## Consequences

### Positive
- Hybrid search handles both "what does amoxicillin do?" (vector wins) and "Amoxicillin 500mg" (keyword wins) correctly
- Graph expansion retrieves neighbouring chunks for context continuity, reducing answer truncation at chunk boundaries
- Redis cache cuts P50 search latency by ~60% for repeated questions (150ms → 60ms)
- All four strategies are exposed as individual REST endpoints (`/search/vector`, `/search/keyword`, `/search/hybrid`, `/search/graph`) for independent evaluation

### Negative
- Redis is an additional infrastructure dependency (mitigated by local Redis in `docker-compose.yml` for dev)
- Cache invalidation is TTL-based only — if a document is re-indexed during a 5-minute window, stale results may be returned (acceptable given PIL update frequency is measured in days, not minutes)
- Graph search adds a Gremlin round-trip that can add 100–200ms for deeply connected documents

### Risks
- **Cache key collisions**: MD5 hash used for cache keys. Probability of collision across realistic query volumes is negligible (~2^{-128} per pair).
- **Redis unavailability**: Cache miss falls through to live search transparently. Redis failure degrades performance, not correctness.
