# ADR-0001: Multi-Database Strategy — Cosmos MongoDB + Gremlin + Azure AI Search

**Date**: 2026-05-07
**Status**: accepted
**Deciders**: KB RAG system design

## Context

The KB RAG system must store three fundamentally different types of data with very different access patterns:
document metadata (structured records looked up by ID or status), chunk relationship graphs (traversal queries across connected nodes), and document chunk embeddings (approximate nearest-neighbour vector search). No single general-purpose database serves all three access patterns well. The system runs on Azure, which offers managed services for each requirement.

## Decision

We use three purpose-built stores in parallel: **Azure Cosmos DB (MongoDB API)** for document metadata and Q&A logs, **Azure Cosmos DB (Gremlin API)** for chunk dependency graphs, and **Azure AI Search** for vector and keyword search over document chunks. All three are accessed through a unified FastAPI backend.

## Alternatives Considered

### Alternative 1: Single PostgreSQL database
- **Pros**: One connection string, simpler ops, ACID transactions across all data, familiar SQL tooling
- **Cons**: `pgvector` extension has limited scalability vs dedicated vector DBs; graph queries require recursive CTEs that become slow at depth; Postgres is not a managed Azure-native service (would use Azure Database for PostgreSQL Flexible Server)
- **Why not**: Vector search performance degrades significantly beyond 1M rows without partitioning strategies; graph traversal at 3+ hops is fundamentally a poor fit for a relational model

### Alternative 2: Cosmos DB only (all APIs on one account)
- **Pros**: Single Azure resource, shared throughput possible, unified billing; Cosmos DB for NoSQL does support native vector search via DiskANN (GA since 2024)
- **Cons**: Cosmos DB vector search lacks built-in BM25 keyword search, semantic ranking, and faceted filtering that Azure AI Search provides out of the box; hybrid search (vector + keyword with RRF) requires custom implementation on top of Cosmos; the Gremlin API and NoSQL API cannot share a vector index on the same account
- **Why not**: Azure AI Search is purpose-built for RAG retrieval workloads — it combines HNSW vector search, BM25 keyword search, semantic ranking, and Reciprocal Rank Fusion in a single API call. Reproducing this on Cosmos DB would require orchestrating multiple separate calls and implementing RRF manually, adding latency and maintenance burden. The decision is not that Cosmos lacks vector search, but that AI Search is the richer retrieval engine for this workload.

### Alternative 3: MongoDB Atlas + Pinecone + Neo4j
- **Pros**: Best-in-class tools for each data type; Pinecone is the leading managed vector DB
- **Cons**: Three separate cloud vendors; no Azure Private Endpoint integration; complex billing; data sovereignty concerns for healthcare data that must stay in a single Azure region
- **Why not**: Violates the requirement to keep all data within Azure for compliance and private networking

## Consequences

### Positive
- Each store is optimised for its query pattern — O(log n) vector search, O(depth) graph traversal, O(1) metadata lookup
- Azure Cosmos DB supports both MongoDB and Gremlin APIs on the same account, reducing resource overhead
- Azure AI Search integrates natively with Azure OpenAI for integrated vectorisation

### Negative
- Three connection strings to manage (mitigated by Key Vault)
- No cross-store ACID transactions — a document upload that partially fails may leave records in inconsistent states across stores (mitigated by idempotent Azure Function retries)
- Higher operational surface area and cost (~$300/month combined vs ~$50 for a single Postgres)

### Risks
- **Cosmos Gremlin API complexity**: Gremlin query language has a steep learning curve and limited library support. Mitigation: graph queries are isolated in `search_service.graph_search()` and can be disabled without affecting core Q&A.
- **Azure AI Search index schema changes require full re-index**: Mitigation: `indexer.py` versions the index name; re-index script provided in `scripts/`.
