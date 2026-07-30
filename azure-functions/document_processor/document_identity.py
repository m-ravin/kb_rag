"""
Document identity — derives a stable, collision-resistant document_id.

Not numbered stage0/stage1 like the pipeline modules: this is a pure
identity helper invoked once at the very top of process_document(), before
any pipeline stage runs, so it doesn't fit the stage1..stage7 execution-order
numbering documented in function_app.py's module docstring.

Previously document_id was just the blob's top-level folder name
(blob_name.split("/")[1]). That meant two different files uploaded to the
same folder — e.g. cooking-made-easy/CSHE-Recipe-Book-2022.pdf uploaded
after cooking-made-easy/Cooking-Made-Easy.pdf — got the SAME document_id,
so the second file's chunks silently overwrote the first file's Search
index entries at matching chunk_index positions (Azure Search's
upload_documents is an upsert by id). This is a real incident this system
hit, not a theoretical risk — see docs/adr/0016-document-lifecycle-and-data-integrity.md.

The fix: derive document_id from the FULL upload path (folder + filename),
not just the folder. This keeps IDs human-readable (folder and filename
are still visible in the id) while a short hash of the exact path makes
collisions require an actual matching folder+filename pair, not just a
matching folder. Uploading to the exact same path twice remains an
intentional upsert (e.g. re-uploading a corrected file to the same path) —
that's desired update semantics, not a bug.

Deliberately NOT a hash of the file's bytes: that would make every
re-upload of a corrected version of the same document a brand-new,
unrelated document_id, leaving the old chunks orphaned in Search with no
automatic replacement. Path-derived IDs give retry idempotency (same
upload retried after a transient failure produces the same id) without
that problem.
"""

import hashlib
import re

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    return slug or "file"


def compute_document_id(upload_folder: str, filename: str) -> str:
    """
    Builds a document_id like "cooking-made-easy-cshe-recipe-book-2022-4f2a9c1b3d":
    a human-readable slug of folder + filename, plus a short hash suffix of
    the exact path so two files that only coincidentally slugify the same
    way still get distinct ids.
    """
    filename_stem = filename.rsplit(".", 1)[0]
    path_hash = hashlib.sha256(f"{upload_folder}/{filename}".encode("utf-8")).hexdigest()[:10]
    return f"{_slugify(upload_folder)}-{_slugify(filename_stem)}-{path_hash}"
