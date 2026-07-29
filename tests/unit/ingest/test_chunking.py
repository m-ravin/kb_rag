"""
Unit tests for the chunking stage.

Imports the real chunk_text implementation from
azure-functions/document_processor/stage2_chunking.py — previously this test
duplicated the logic inline instead, so a regression in the real function
would never have been caught.

stage2_chunking.py has zero third-party dependencies, so — like the file this
replaces — this test is runnable stdlib-only, no `uv sync` required:
    python tests/unit/ingest/test_chunking.py
"""

import sys
import unittest
from pathlib import Path

# Self-contained path setup so this file also runs standalone via
# `python tests/unit/ingest/test_chunking.py`, not just under pytest
# (which would pick up conftest.py automatically).
_DOCUMENT_PROCESSOR_DIR = (
    Path(__file__).resolve().parents[3] / "azure-functions" / "document_processor"
)
if str(_DOCUMENT_PROCESSOR_DIR) not in sys.path:
    sys.path.insert(0, str(_DOCUMENT_PROCESSOR_DIR))

from stage2_chunking import chunk_text  # noqa: E402


class TestChunkText(unittest.TestCase):
    # ── Core behaviour ─────────────────────────────────────────────────────

    def test_returns_list_of_dicts(self):
        chunks = chunk_text(" ".join(["word"] * 600))
        self.assertIsInstance(chunks, list)
        self.assertTrue(all(isinstance(c, dict) for c in chunks))

    def test_chunk_index_is_sequential(self):
        chunks = chunk_text(" ".join(f"w{i}" for i in range(1200)))
        for i, c in enumerate(chunks):
            self.assertEqual(c["chunk_index"], i)

    def test_chunks_overlap(self):
        words = [f"word{i}" for i in range(300)]
        chunks = chunk_text(" ".join(words), chunk_size=100, overlap=64)
        if len(chunks) >= 2:
            end_c0 = set(chunks[0]["text"].split()[-64:])
            start_c1 = set(chunks[1]["text"].split()[:64])
            self.assertGreater(len(end_c0 & start_c1), 0)

    # ── Edge cases (bugs caught by TDD) ───────────────────────────────────

    def test_single_word_produces_one_chunk(self):
        """Regression: was silently dropped when < 20 chars."""
        self.assertEqual(len(chunk_text("paracetamol")), 1)

    def test_short_warning_produces_one_chunk(self):
        """Regression: 'Warning: keep dry.' (19 chars) was dropped."""
        self.assertEqual(len(chunk_text("Warning: keep dry.")), 1)

    def test_empty_text_returns_empty_list(self):
        self.assertEqual(chunk_text(""), [])

    def test_whitespace_only_returns_empty_list(self):
        self.assertEqual(chunk_text("   \n\t  "), [])

    def test_exactly_chunk_size_words_gives_two_chunks(self):
        """512 words → chunk 1 (words 0-511), chunk 2 (words 448-511)."""
        chunks = chunk_text(" ".join(["w"] * 512), chunk_size=512, overlap=64)
        self.assertEqual(len(chunks), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
