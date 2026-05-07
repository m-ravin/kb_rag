"""
Singleton Azure SDK clients.
Created once at startup, shared across all API requests.
"""

from functools import lru_cache

import redis.asyncio as aioredis
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.aio import SearchClient
from motor.motor_asyncio import AsyncIOMotorClient
from openai import AsyncAzureOpenAI

from backend.core.config import get_settings


@lru_cache
def get_openai_client() -> AsyncAzureOpenAI:
    """The brain — talks to GPT-4o for answers and text-embedding for vectors."""
    s = get_settings()
    return AsyncAzureOpenAI(
        azure_endpoint=s.azure_openai_endpoint,
        api_key=s.azure_openai_key,
        api_version=s.azure_openai_api_version,
    )


@lru_cache
def get_search_client() -> SearchClient:
    """The librarian — finds relevant document chunks by similarity."""
    s = get_settings()
    return SearchClient(
        endpoint=s.azure_search_endpoint,
        index_name=s.azure_search_index_name,
        credential=AzureKeyCredential(s.azure_search_key),
    )


@lru_cache
def get_mongo_client() -> AsyncIOMotorClient:
    """The filing cabinet — stores document metadata and Q&A logs."""
    return AsyncIOMotorClient(get_settings().cosmos_mongo_connection)


def get_db():
    """Returns the MongoDB database handle."""
    client = get_mongo_client()
    return client[get_settings().cosmos_db_name]


@lru_cache
def get_redis_client() -> aioredis.Redis:
    """The Post-it note board — caches answers so we don't repeat work."""
    return aioredis.from_url(
        get_settings().redis_connection,
        encoding="utf-8",
        decode_responses=True,
    )
