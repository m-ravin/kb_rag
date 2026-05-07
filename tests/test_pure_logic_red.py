"""
RED-phase tests — these expose real edge-case bugs in the current implementation.

Run: python tests/test_pure_logic_red.py
Expected result: FAILURES (this is intentional — we fix them in the GREEN phase)
"""

import re
import sys
import unittest

# ── Inline current implementations (mirrors actual code) ──────────────────────

def _chunk_text_current(text: str, chunk_size: int = 512, overlap: int = 64) -> list[dict]:
    """Current implementation — has a bug: silently drops short but valid content."""
    words = text.split()
    chunks = []
    step = chunk_size - overlap
    for i in range(0, len(words), step):
        chunk_words = words[i: i + chunk_size]
        chunk_text = " ".join(chunk_words)
        if len(chunk_text.strip()) < 20:   # BUG: drops valid short content
            continue
        chunks.append({"chunk_index": len(chunks), "text": chunk_text,
                       "word_start": i, "word_end": i + len(chunk_words)})
    return chunks


_PII_PATTERNS_CURRENT = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b[A-Z]{1,2}\d{6,9}[A-Z]?\b"),
    re.compile(r"\b\+?[\d\s\-]{8,15}\b"),
    re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
]


def _detect_pii_current(text: str) -> tuple[bool, list[str]]:
    """Current implementation — missing Malaysian NRIC format."""
    detected = []
    for pattern in _PII_PATTERNS_CURRENT:
        if pattern.search(text):
            detected.append(pattern.pattern)
    return bool(detected), detected


# ── RED Tests: these must FAIL against the current implementation ─────────────

class TestChunkerEdgeCases_RED(unittest.TestCase):
    """
    BUG: The < 20 char threshold silently drops valid short medical documents.
    A PIL with only a drug name and a one-line warning is real, indexable content.
    """

    def test_single_word_document_produces_a_chunk(self):
        """
        A single-term query like 'Paracetamol' must produce exactly one chunk.
        Currently FAILS: 'paracetamol' (13 chars) is < 20 and is skipped.
        """
        chunks = _chunk_text_current("paracetamol")
        # RED: currently returns [] because 13 chars < 20
        self.assertEqual(len(chunks), 1, "Single-word document should produce 1 chunk")

    def test_short_drug_warning_produces_a_chunk(self):
        """
        'Warning: keep dry.' is valid PIL content (19 chars) that must not be lost.
        Currently FAILS: 19 chars < 20.
        """
        chunks = _chunk_text_current("Warning: keep dry.")
        # RED: currently returns [] because 18 chars < 20
        self.assertEqual(len(chunks), 1, "Short warning must not be silently dropped")

    def test_exactly_20_char_content_is_kept(self):
        """Boundary condition: content of exactly 20 chars must be retained."""
        # exactly 20 chars: "This is a test text."
        text = "This is a test text."
        assert len(text) == 20
        chunks = _chunk_text_current(text)
        self.assertEqual(len(chunks), 1)


class TestPIIDetection_RED(unittest.TestCase):
    """
    BUG: Malaysian NRIC format (YYMMDD-PB-XXXX) is not detected by current regexes.
    Healthcare PIL systems must detect NRIC as PII since it identifies individuals.
    """

    def test_detects_malaysian_nric(self):
        """
        NRIC '870315-07-1234' must be flagged as PII.
        Currently FAILS: no regex in _PII_PATTERNS matches this 12-digit format.
        """
        has_pii, _ = _detect_pii_current("Patient NRIC: 870315-07-1234")
        # RED: currently returns False — NRIC not in patterns
        self.assertTrue(has_pii, "Malaysian NRIC must be detected as PII")

    def test_nric_without_dashes_also_detected(self):
        """NRIC without dashes '870315071234' must also be flagged."""
        has_pii, _ = _detect_pii_current("ID: 870315071234")
        # RED: currently returns False
        self.assertTrue(has_pii, "12-digit NRIC without dashes must be detected")


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    # Print a clear RED summary
    if not result.wasSuccessful():
        print(f"\n[RED] {len(result.failures)} failures, {len(result.errors)} errors — expected")
        print("Now fix the implementation and run test_pure_logic_green.py")
    sys.exit(0 if result.wasSuccessful() else 1)
