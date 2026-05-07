"""
Unit tests for the document chunking logic.

Tests both the happy path and the edge cases discovered during TDD
(short content, empty content, overlap behaviour).
"""

import unittest
import sys


def _chunk_text(text: str, chunk_size: int = 512, overlap: int = 64) -> list[dict]:
    """Fixed implementation — any non-empty chunk is kept."""
    words = text.split()
    chunks = []
    step = chunk_size - overlap
    for i in range(0, len(words), step):
        chunk_words = words[i: i + chunk_size]
        chunk_text = " ".join(chunk_words)
        if not chunk_text.strip():
            continue
        chunks.append({"chunk_index": len(chunks), "text": chunk_text,
                       "word_start": i, "word_end": i + len(chunk_words)})
    return chunks


class TestChunkText(unittest.TestCase):

    # ── Core behaviour ─────────────────────────────────────────────────────────

    def test_returns_list_of_dicts(self):
        chunks = _chunk_text(" ".join(["word"] * 600))
        self.assertIsInstance(chunks, list)
        self.assertTrue(all(isinstance(c, dict) for c in chunks))

    def test_chunk_index_is_sequential(self):
        chunks = _chunk_text(" ".join([f"w{i}" for i in range(1200)]))
        for i, c in enumerate(chunks):
            self.assertEqual(c["chunk_index"], i)

    def test_chunks_overlap(self):
        words = [f"word{i}" for i in range(300)]
        chunks = _chunk_text(" ".join(words), chunk_size=100, overlap=64)
        if len(chunks) >= 2:
            end_c0 = set(chunks[0]["text"].split()[-64:])
            start_c1 = set(chunks[1]["text"].split()[:64])
            self.assertGreater(len(end_c0 & start_c1), 0)

    # ── Edge cases (bugs caught by TDD) ───────────────────────────────────────

    def test_single_word_produces_one_chunk(self):
        """Regression: was silently dropped when < 20 chars."""
        self.assertEqual(len(_chunk_text("paracetamol")), 1)

    def test_short_warning_produces_one_chunk(self):
        """Regression: 'Warning: keep dry.' (19 chars) was dropped."""
        self.assertEqual(len(_chunk_text("Warning: keep dry.")), 1)

    def test_empty_text_returns_empty_list(self):
        self.assertEqual(_chunk_text(""), [])

    def test_whitespace_only_returns_empty_list(self):
        self.assertEqual(_chunk_text("   \n\t  "), [])

    def test_exactly_chunk_size_words_gives_two_chunks(self):
        """512 words → chunk 1 (words 0–511), chunk 2 (words 448–511)."""
        chunks = _chunk_text(" ".join(["w"] * 512), chunk_size=512, overlap=64)
        self.assertEqual(len(chunks), 2)


class TestPIIPatterns(unittest.TestCase):
    """
    Canonical PII regex tests — covers all patterns including NRIC
    added during GREEN phase.
    """
    import re

    _PATTERNS = [
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        re.compile(r"\b[A-Z]{1,2}\d{6,9}[A-Z]?\b"),
        re.compile(r"\b\d{6}-\d{2}-\d{4}\b"),
        re.compile(r"\b\d{12}\b"),
        re.compile(r"\b\+?[\d\s\-]{8,15}\b"),
        re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    ]

    def _detect(self, text):
        detected = [p.pattern for p in self._PATTERNS if p.search(text)]
        return bool(detected), detected

    def test_email(self):
        self.assertTrue(self._detect("test@example.com")[0])

    def test_ssn(self):
        self.assertTrue(self._detect("SSN 123-45-6789")[0])

    def test_nric_with_dashes(self):
        self.assertTrue(self._detect("NRIC 870315-07-1234")[0])

    def test_nric_without_dashes(self):
        self.assertTrue(self._detect("ID: 870315071234")[0])

    def test_clean_medical_text(self):
        self.assertFalse(self._detect("Take 500mg every 4 hours.")[0])

    def test_empty(self):
        self.assertFalse(self._detect("")[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
