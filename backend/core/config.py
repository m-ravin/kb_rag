"""
Central configuration — reads every setting from environment variables.
All secrets come from Azure Key Vault via the Kubernetes CSI driver at runtime.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Azure OpenAI ──────────────────────────────────────────────────────────
    azure_openai_endpoint: str
    azure_openai_key: str
    azure_openai_gpt_deployment: str = "gpt-4o"
    azure_openai_embedding_deployment: str = "text-embedding-3-small"
    azure_openai_api_version: str = "2024-08-01-preview"

    # ── Azure AI Search (vector DB) ───────────────────────────────────────────
    azure_search_endpoint: str
    azure_search_key: str
    azure_search_index_name: str = "pil-documents"

    # ── Cosmos DB — MongoDB API ───────────────────────────────────────────────
    cosmos_mongo_connection: str
    cosmos_db_name: str = "pil-knowledge-base"

    # ── Cosmos DB — Gremlin API ───────────────────────────────────────────────
    cosmos_gremlin_endpoint: str
    cosmos_gremlin_key: str
    cosmos_gremlin_database: str = "pil-graph"
    cosmos_gremlin_graph: str = "chunk-graph"

    # ── Azure Cache for Redis ─────────────────────────────────────────────────
    redis_connection: str

    # ── Azure Data Lake Storage ───────────────────────────────────────────────
    storage_connection: str
    storage_container_name: str = "pil-documents"

    # ── Azure AI Content Safety ───────────────────────────────────────────────
    content_safety_endpoint: str = ""
    content_safety_key: str = ""

    # ── Azure Monitor / App Insights ──────────────────────────────────────────
    appinsights_connection_string: str = ""

    # ── Application ───────────────────────────────────────────────────────────
    app_name: str = "kb-rag RAG Backend"
    debug: bool = False
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
