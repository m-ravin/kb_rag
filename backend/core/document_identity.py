"""
Document identity — derives the same stable, content-addressed document_id
the Function ingestion pipeline computes.

Deliberately duplicated from azure-functions/document_processor/document_identity.py
rather than shared via import: the backend (Docker image) and the Function
(zip deploy) are independently packaged and deployed, so there's no shared
package boundary between them. Keep both copies in sync if this changes.

Without this, the CMS upload endpoint generated its own random UUID as
document_id, while the Function computed a different, path-derived id for
the same upload — leaving the CMS's original "pending" placeholder record
permanently orphaned in MongoDB (never updated to "indexed") while a second,
disconnected record did the real work. Using the same id here means both
sides update the exact same MongoDB record across its whole lifecycle.
"""

import hashlib
import re

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    return slug or "file"


def compute_document_id(upload_folder: str, filename: str) -> str:
    filename_stem = filename.rsplit(".", 1)[0]
    path_hash = hashlib.sha256(f"{upload_folder}/{filename}".encode("utf-8")).hexdigest()[:10]
    return f"{_slugify(upload_folder)}-{_slugify(filename_stem)}-{path_hash}"
