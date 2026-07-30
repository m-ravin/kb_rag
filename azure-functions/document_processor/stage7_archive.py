"""
Archive stage — moves a successfully-indexed blob out of the ingestion path.

Takes already-constructed source and destination container clients
(dependency injection) instead of creating them itself, so this is testable
with mock clients.

Only called on success. A failed document is deliberately left at its
original path instead of being moved to a "failed" location: the blob
trigger has its own retry-on-exception behavior (up to 5 attempts before the
poison queue), and moving the blob after the first failure would delete the
source a subsequent retry needs to read, breaking a retry that might
otherwise have succeeded. Leaving failed files in place also keeps them easy
to find for manual investigation.

The destination is a SEPARATE container ("processed"), not a subfolder of
the ingestion container. An earlier version archived to a "processed/"
prefix inside the same container — since the Event Grid
subscription driving this trigger is scoped to the whole ingestion
container, that archive write was itself a new BlobCreated event, which
re-triggered this same function on its own output and produced a
self-sustaining reprocessing loop (see incident notes in ADR-0015 /
git history). A container the subscription was never scoped to can't
trigger it, structurally, regardless of any filter configuration.
"""


def archive_processed_blob(
    source_container_client, dest_container_client, document_id: str, filename: str, data: bytes
) -> None:
    """
    Moves a blob from the ingestion container's {document_id}/{filename}
    path to the same path in the processed container. Copy-then-delete
    (Azure Blob has no native cross-container move), reusing the bytes
    already read into memory during processing instead of re-downloading.
    """
    path = f"{document_id}/{filename}"
    dest_container_client.upload_blob(name=path, data=data, overwrite=True)
    source_container_client.delete_blob(path)
