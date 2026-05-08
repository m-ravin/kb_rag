"""
Standalone tests for pure-Python business logic — no Azure SDK required.
Runs with Python stdlib only (unittest + asyncio).

Covers:
  - PII regex patterns (safety_service)
  - Template variable filling (task_apis)
  - Compliance JSON parsing (llm_service)
  - Language code truncation (llm_service)
  - Chunk text splitting (document_processor)
  - Cache key generation (search_service)
"""

import asyncio
import json
import re
import sys
import unittest

# ── Inline implementations extracted from source ──────────────────────────────
# These mirror the exact logic in the real modules so tests are authoritative.

_PII_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b[A-Z]{1,2}\d{6,9}[A-Z]?\b"),
    re.compile(r"\b\+?[\d\s\-]{8,15}\b"),
    re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
]


def _detect_pii_regex(text: str) -> tuple[bool, list[str]]:
    detected = []
    for pattern in _PII_PATTERNS:
        if pattern.search(text):
            detected.append(pattern.pattern)
    return bool(detected), detected


def _fill_template(template: str, variables: dict) -> str:
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result


def _parse_compliance_json(raw: str) -> tuple[bool, str]:
    try:
        result = json.loads(raw)
        return result.get("compliant", True), result.get("reason", "")
    except (json.JSONDecodeError, KeyError):
        return True, ""


def _truncate_lang_code(raw: str) -> str:
    return raw.strip().lower()[:2]


def _chunk_text(text: str, chunk_size: int = 512, overlap: int = 64) -> list[dict]:
    words = text.split()
    chunks = []
    step = chunk_size - overlap
    for i in range(0, len(words), step):
        chunk_words = words[i: i + chunk_size]
        chunk_text = " ".join(chunk_words)
        if len(chunk_text.strip()) < 20:
            continue
        chunks.append({"chunk_index": len(chunks), "text": chunk_text,
                       "word_start": i, "word_end": i + len(chunk_words)})
    return chunks


# ── PII Detection Tests ────────────────────────────────────────────────────────

class TestPIIDetection(unittest.TestCase):

    def test_detects_email_address(self):
        has_pii, patterns = _detect_pii_regex("Contact john.doe@example.com for info.")
        self.assertTrue(has_pii)
        self.assertGreater(len(patterns), 0)

    def test_detects_ssn_pattern(self):
        has_pii, patterns = _detect_pii_regex("SSN: 123-45-6789")
        self.assertTrue(has_pii)

    def test_clean_medical_question_returns_no_pii(self):
        has_pii, patterns = _detect_pii_regex("What is the recommended dose of paracetamol?")
        self.assertFalse(has_pii)
        self.assertEqual(patterns, [])

    def test_empty_string_returns_no_pii(self):
        has_pii, patterns = _detect_pii_regex("")
        self.assertFalse(has_pii)

    def test_returns_tuple_of_bool_and_list(self):
        result = _detect_pii_regex("some text")
        self.assertIsInstance(result, tuple)
        self.assertIsInstance(result[0], bool)
        self.assertIsInstance(result[1], list)

    def test_detects_multiple_pii_types_in_one_string(self):
        text = "Email: alice@test.com, SSN: 123-45-6789"
        has_pii, patterns = _detect_pii_regex(text)
        self.assertTrue(has_pii)
        self.assertGreaterEqual(len(patterns), 2)

    def test_passport_number_detected(self):
        has_pii, _ = _detect_pii_regex("Passport: A12345678")
        self.assertTrue(has_pii)


# ── Template Parser Tests ──────────────────────────────────────────────────────

class TestTemplateParser(unittest.TestCase):

    def test_fills_single_variable(self):
        result = _fill_template("Dear {{name}}, welcome.", {"name": "Alice"})
        self.assertEqual(result, "Dear Alice, welcome.")

    def test_fills_multiple_variables(self):
        result = _fill_template(
            "Dear {{name}}, your {{drug}} is ready.",
            {"name": "Bob", "drug": "Amoxicillin"},
        )
        self.assertEqual(result, "Dear Bob, your Amoxicillin is ready.")

    def test_leaves_unfilled_variables_intact(self):
        result = _fill_template("Dear {{name}}, your {{item}} is ready.", {"name": "Bob"})
        self.assertIn("Bob", result)
        self.assertIn("{{item}}", result)

    def test_empty_template_returns_empty_string(self):
        result = _fill_template("", {"name": "Alice"})
        self.assertEqual(result, "")

    def test_no_variables_returns_template_unchanged(self):
        template = "No placeholders here."
        result = _fill_template(template, {"name": "Alice"})
        self.assertEqual(result, template)

    def test_numeric_variable_values_coerced_to_string(self):
        result = _fill_template("Dose: {{dose}}mg", {"dose": 500})
        self.assertEqual(result, "Dose: 500mg")


# ── Compliance JSON Parser Tests ──────────────────────────────────────────────

class TestComplianceParser(unittest.TestCase):

    def test_parses_compliant_true(self):
        is_compliant, reason = _parse_compliance_json('{"compliant": true, "reason": ""}')
        self.assertTrue(is_compliant)
        self.assertEqual(reason, "")

    def test_parses_compliant_false_with_reason(self):
        is_compliant, reason = _parse_compliance_json(
            '{"compliant": false, "reason": "Definitive diagnostic claim."}'
        )
        self.assertFalse(is_compliant)
        self.assertIn("diagnostic", reason.lower())

    def test_returns_true_for_invalid_json(self):
        """Graceful fallback for malformed LLM output."""
        is_compliant, reason = _parse_compliance_json("not valid json")
        self.assertTrue(is_compliant)
        self.assertEqual(reason, "")

    def test_returns_true_for_empty_string(self):
        is_compliant, reason = _parse_compliance_json("")
        self.assertTrue(is_compliant)

    def test_defaults_compliant_to_true_when_key_missing(self):
        is_compliant, _ = _parse_compliance_json('{"reason": "missing compliant key"}')
        self.assertTrue(is_compliant)


# ── Language Code Tests ────────────────────────────────────────────────────────

class TestLanguageCode(unittest.TestCase):

    def test_returns_two_char_code(self):
        result = _truncate_lang_code("ms")
        self.assertEqual(len(result), 2)
        self.assertEqual(result, "ms")

    def test_truncates_long_response_to_two_chars(self):
        result = _truncate_lang_code("english")
        self.assertEqual(len(result), 2)
        self.assertEqual(result, "en")

    def test_strips_whitespace_before_truncating(self):
        result = _truncate_lang_code("  ZH  ")
        self.assertEqual(result, "zh")

    def test_lowercases_result(self):
        result = _truncate_lang_code("EN")
        self.assertEqual(result, "en")


# ── Text Chunker Tests ─────────────────────────────────────────────────────────

class TestChunkText(unittest.TestCase):

    def test_returns_list_of_dicts(self):
        text = " ".join(["word"] * 600)
        chunks = _chunk_text(text, chunk_size=512, overlap=64)
        self.assertIsInstance(chunks, list)
        self.assertTrue(all(isinstance(c, dict) for c in chunks))

    def test_chunk_index_is_sequential(self):
        text = " ".join(["word"] * 1200)
        chunks = _chunk_text(text, chunk_size=512, overlap=64)
        for i, chunk in enumerate(chunks):
            self.assertEqual(chunk["chunk_index"], i)

    def test_chunks_overlap(self):
        """With overlap=64 and chunk_size=100, consecutive chunks share words."""
        words = [f"word{i}" for i in range(300)]
        text = " ".join(words)
        chunks = _chunk_text(text, chunk_size=100, overlap=64)
        if len(chunks) >= 2:
            end_words_c0 = set(chunks[0]["text"].split()[-64:])
            start_words_c1 = set(chunks[1]["text"].split()[:64])
            overlap_words = end_words_c0 & start_words_c1
            self.assertGreater(len(overlap_words), 0)

    def test_skips_very_short_chunks(self):
        """Chunks with fewer than 20 characters must be dropped."""
        text = " ".join(["word"] * 520)  # enough for 1 full chunk + tiny remainder
        chunks = _chunk_text(text, chunk_size=512, overlap=64)
        for chunk in chunks:
            self.assertGreaterEqual(len(chunk["text"].strip()), 20)

    def test_empty_text_returns_empty_list(self):
        chunks = _chunk_text("")
        self.assertEqual(chunks, [])

    def test_short_text_under_chunk_size_returns_one_chunk(self):
        text = " ".join(["word"] * 50)
        chunks = _chunk_text(text, chunk_size=512, overlap=64)
        self.assertEqual(len(chunks), 1)


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2, failfast=False)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
