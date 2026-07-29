"""
Embedding stage — converts chunk text into vectors via Azure OpenAI.

Takes an already-constructed OpenAI client (dependency injection) instead of
creating one itself, so this is testable with a mock client.
"""

# Azure OpenAI allows up to 2048 texts per embeddings call; 16 balances
# throughput against payload size and keeps individual requests small.
_DEFAULT_BATCH_SIZE = 16


def embed_texts(
    openai_client, texts: list[str], model: str, batch_size: int = _DEFAULT_BATCH_SIZE
) -> list[list[float]]:
    """Embeds a list of texts in batches, returning vectors in the same order as the input."""
    vectors: list[list[float]] = []
    for batch_start in range(0, len(texts), batch_size):
        batch = texts[batch_start : batch_start + batch_size]
        response = openai_client.embeddings.create(input=batch, model=model)
        vectors.extend(item.embedding for item in response.data)
    return vectors
