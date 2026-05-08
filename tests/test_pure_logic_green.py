"""
GREEN-phase tests — same cases as test_pure_logic_red.py but against
the FIXED implementation. All must pass.

Run: python tests/test_pure_logic_green.py
Expected: OK (all tests pass)
"""

import re
import sys
import unittest

# ── Fixed implementations ──────────────────────────────────────────────────────

def _chunk_text_fixed(text: str, chunk_size: int = 512, overlap: int = 64) -> list[dict]:
    """
    FIX: Drop only genuinely empty chunks (whitespace-only), not short ones.
    Any non-empty content — even a single word — is valid indexable data.
    """
    words = text.split()
    chunks = []
    step = chunk_size - overlap
    for i in range(0, len(words), step):
        chunk_words = words[i: i + chunk_size]
        chunk_text = " ".join(chunk_words)
        if not chunk_text.strip():           # Only skip truly empty chunks
            continue
        chunks.append({"chunk_index": len(chunks), "text": chunk_text,
                       "word_start": i, "word_end": i + len(chunk_words)})
    return chunks


_PII_PATTERNS_FIXED = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                       # US SSN
    re.compile(r"\b[A-Z]{1,2}\d{6,9}[A-Z]?\b"),                 # Passport
    re.compile(r"\b\d{6}-\d{2}-\d{4}\b"),                       # MY NRIC with dashes
    re.compile(r"\b\d{12}\b"),                                   # MY NRIC without dashes
    re.compile(r"\b\+?[\d\s\-]{8,15}\b"),                       # Phone
    re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),  # Email
]


def _detect_pii_fixed(text: str) -> tuple[bool, list[str]]:
    detected = []
    for pattern in _PII_PATTERNS_FIXED:
        if pattern.search(text):
            detected.append(pattern.pattern)
    return bool(detected), detected


# ── GREEN Tests ───────────────────────────────────────────────────────────────

class TestChunkerEdgeCases_GREEN(unittest.TestCase):

    def test_single_word_document_produces_a_chunk(self):
        chunks = _chunk_text_fixed("paracetamol")
        self.assertEqual(len(chunks), 1)

    def test_short_drug_warning_produces_a_chunk(self):
        chunks = _chunk_text_fixed("Warning: keep dry.")
        self.assertEqual(len(chunks), 1)

    def test_exactly_20_char_content_is_kept(self):
        chunks = _chunk_text_fixed("This is a test text.")
        self.assertEqual(len(chunks), 1)

    def test_empty_text_still_returns_empty_list(self):
        chunks = _chunk_text_fixed("")
        self.assertEqual(chunks, [])

    def test_whitespace_only_text_returns_empty_list(self):
        chunks = _chunk_text_fixed("   \n\t  ")
        self.assertEqual(chunks, [])

    def test_long_text_still_chunks_correctly(self):
        text = " ".join([f"word{i}" for i in range(600)])
        chunks = _chunk_text_fixed(text, chunk_size=512, overlap=64)
        self.assertGreater(len(chunks), 1)
        for i, chunk in enumerate(chunks):
            self.assertEqual(chunk["chunk_index"], i)


class TestPIIDetection_GREEN(unittest.TestCase):

    def test_detects_malaysian_nric_with_dashes(self):
        has_pii, _ = _detect_pii_fixed("Patient NRIC: 870315-07-1234")
        self.assertTrue(has_pii)

    def test_detects_malaysian_nric_without_dashes(self):
        has_pii, _ = _detect_pii_fixed("ID: 870315071234")
        self.assertTrue(has_pii)

    def test_still_detects_email(self):
        has_pii, _ = _detect_pii_fixed("contact@test.com")
        self.assertTrue(has_pii)

    def test_still_passes_clean_text(self):
        has_pii, _ = _detect_pii_fixed("What is the recommended dose?")
        self.assertFalse(has_pii)

    def test_twelve_digit_non_nric_number_also_flagged(self):
        """Any 12-digit number should be treated as potential NRIC."""
        has_pii, _ = _detect_pii_fixed("Reference: 123456789012")
        self.assertTrue(has_pii)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print(f"\n[GREEN] All {result.testsRun} tests passed!")
    else:
        print(f"\n[STILL RED] {len(result.failures)} failures remain — fix not complete")
    sys.exit(0 if result.wasSuccessful() else 1)
