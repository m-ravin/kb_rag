"""
Search Index Manager — creates the Azure AI Search index schema at startup.

Like setting up the card catalogue in a library: defining all the fields
and making sure the vector search column is configured correctly.
"""

import logging

from azure.core.exceptions import ResourceExistsError
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SimpleField,
    SearchableField,
    VectorSearch,
    VectorSearchProfile,
)
from azure.core.credentials import AzureKeyCredential

from backend.core.config import get_settings

logger = logging.getLogger(__name__)


async def ensure_search_index() -> None:
    """
    Creates the Azure AI Search index if it doesn't already exist.
    Called once at application startup.
    """
    s = get_settings()

    index_client = SearchIndexClient(
        endpoint=s.azure_search_endpoint,
        credential=AzureKeyCredential(s.azure_search_key),
    )

    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SimpleField(name="document_id", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="filename", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="chunk_index", type=SearchFieldDataType.Int32),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SimpleField(name="metadata", type=SearchFieldDataType.String),
        SimpleField(name="indexed_at", type=SearchFieldDataType.String),
        # The vector field — 1536 dimensions for text-embedding-3-small
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=1536,
            vector_search_profile_name="pil-vector-profile",
        ),
    ]

    vector_search = VectorSearch(
        profiles=[VectorSearchProfile(name="pil-vector-profile", algorithm_configuration_name="pil-hnsw")],
        algorithms=[HnswAlgorithmConfiguration(name="pil-hnsw")],
    )

    index = SearchIndex(
        name=s.azure_search_index_name,
        fields=fields,
        vector_search=vector_search,
    )

    try:
        index_client.create_index(index)
        logger.info("Created Azure AI Search index: %s", s.azure_search_index_name)
    except ResourceExistsError:
        logger.info("Azure AI Search index already exists: %s", s.azure_search_index_name)
    except Exception as exc:
        logger.warning("Could not create search index (will retry): %s", exc)
