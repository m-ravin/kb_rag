"""
Cross-consistency test between the two document_identity.py copies.

backend/core/document_identity.py is a deliberate, documented duplicate of
azure-functions/document_processor/document_identity.py (no shared import
boundary between the two independently-deployed units — see either module's
docstring). If the two copies ever drift, the CMS upload endpoint and the
Function pipeline would compute different document_ids for the same upload,
silently reintroducing the dual-record bug both copies exist to prevent.
This test guards against that drift.
"""

import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[3] / "azure-functions" / "document_processor")
)

from document_identity import compute_document_id as functions_compute_document_id  # noqa: E402

from backend.core.document_identity import compute_document_id as backend_compute_document_id


def test_both_copies_produce_identical_ids_for_the_same_input():
    cases = [
        ("cookbook", "cookbook.pdf"),
        ("cooking-made-easy", "Cooking-Made-Easy.pdf"),
        ("My Folder!!", "Report (Final) v2.pdf"),
        ("a", "b.docx"),
    ]
    for upload_folder, filename in cases:
        assert backend_compute_document_id(upload_folder, filename) == functions_compute_document_id(
            upload_folder, filename
        )
