"""
Tests for the Azure Function's document identity scheme.

azure-functions/document_processor isn't part of the installable `backend`
package (see function_app.py's module docstring), so it's not importable via
normal package resolution — path-inserted here the same way function_app.py
inserts its own directory at runtime.
"""

import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[3] / "azure-functions" / "document_processor")
)

from document_identity import compute_document_id  # noqa: E402


def test_same_folder_and_filename_produce_same_id():
    first = compute_document_id("cookbook", "cookbook.pdf")
    second = compute_document_id("cookbook", "cookbook.pdf")
    assert first == second


def test_different_filenames_in_same_folder_produce_different_ids():
    # This is the exact bug that caused CSHE-Recipe-Book-2022.pdf to silently
    # overwrite Cooking-Made-Easy.pdf's Search chunks: both were uploaded to
    # cooking-made-easy/ and the old scheme used the folder name alone.
    first = compute_document_id("cooking-made-easy", "Cooking-Made-Easy.pdf")
    second = compute_document_id("cooking-made-easy", "CSHE-Recipe-Book-2022.pdf")
    assert first != second


def test_same_filename_in_different_folders_produce_different_ids():
    first = compute_document_id("cookbook", "report.pdf")
    second = compute_document_id("other-folder", "report.pdf")
    assert first != second


def test_id_is_human_readable_and_contains_slugified_parts():
    document_id = compute_document_id("Cooking Made Easy", "Cooking-Made-Easy.pdf")
    assert "cooking-made-easy" in document_id


def test_id_strips_file_extension_from_filename_component():
    document_id = compute_document_id("cookbook", "cookbook.pdf")
    assert ".pdf" not in document_id


def test_special_characters_are_slugified_not_left_raw():
    document_id = compute_document_id("My Folder!!", "Report (Final) v2.pdf")
    assert " " not in document_id
    assert "!" not in document_id
    assert "(" not in document_id


def test_id_is_deterministic_across_multiple_calls():
    ids = {compute_document_id("cookbook", "cookbook.pdf") for _ in range(5)}
    assert len(ids) == 1
