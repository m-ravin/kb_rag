"""
Archive stage — moves a successfully-indexed blob out of the ingestion path.

Takes an already-constructed container client (dependency injection) instead
of creating one itself, so this is testable with a mock client.

Only called on success. A failed document is deliberately left at its
original path instead of being moved to a "failed/" prefix: the blob trigger
has its own retry-on-exception behavior (up to 5 attempts before the poison
queue), and moving the blob after the first failure would delete the source
a subsequent retry needs to read, breaking a retry that might otherwise have
succeeded. Leaving failed files in place also keeps them easy to find for
manual investigation.
"""


def archive_processed_blob(container_client, document_id: str, filename: str, data: bytes) -> None:
    """
    Moves a blob from its ingestion path to processed/{document_id}/{filename}.
    Copy-then-delete (Azure Blob has no native move), reusing the bytes
    already read into memory during processing instead of re-downloading.
    """
    source_path = f"{document_id}/{filename}"
    dest_path = f"processed/{document_id}/{filename}"

    container_client.upload_blob(name=dest_path, data=data, overwrite=True)
    container_client.delete_blob(source_path)
