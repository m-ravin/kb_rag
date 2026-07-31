"""
Canonical PII regex tests — covers all patterns including NRIC added during
GREEN phase. These are the raw detection patterns; Presidio (ADR-0010) is the
actual PII redaction service used in production.
"""

import re
import unittest


class TestPIIPatterns(unittest.TestCase):
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
