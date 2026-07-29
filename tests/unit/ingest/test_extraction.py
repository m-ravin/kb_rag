"""Unit tests for the extraction stage's magic-byte validation."""

import pytest

from stage1_extraction import validate_magic_bytes


class TestValidateMagicBytes:
    def test_accepts_valid_pdf(self):
        validate_magic_bytes(b"%PDF-1.4 rest of file", "leaflet.pdf")  # no raise

    def test_rejects_mismatched_pdf(self):
        with pytest.raises(ValueError):
            validate_magic_bytes(b"not actually a pdf", "leaflet.pdf")

    def test_accepts_valid_docx(self):
        validate_magic_bytes(b"PK\x03\x04rest of zip", "leaflet.docx")  # no raise

    def test_rejects_mismatched_docx(self):
        with pytest.raises(ValueError):
            validate_magic_bytes(b"not actually a docx", "leaflet.docx")

    def test_accepts_valid_pptx(self):
        validate_magic_bytes(b"PK\x03\x04rest of zip", "leaflet.pptx")  # no raise

    def test_rejects_mismatched_pptx(self):
        with pytest.raises(ValueError):
            validate_magic_bytes(b"not actually a pptx", "leaflet.pptx")

    def test_unknown_extension_is_not_validated(self):
        """No magic-byte rule exists for .txt, so anything passes through."""
        validate_magic_bytes(b"anything at all", "notes.txt")  # no raise
