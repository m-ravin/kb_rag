"""Tests for backend.api.management.router._sanitize_filename."""

import pytest
from fastapi import HTTPException

from backend.api.management.router import _sanitize_filename


def test_plain_filename_passes_through_unchanged():
    assert _sanitize_filename("cookbook.pdf") == "cookbook.pdf"


def test_forward_slash_path_reduced_to_basename():
    assert _sanitize_filename("../../etc/evil.pdf") == "evil.pdf"


def test_backslash_path_reduced_to_basename():
    assert _sanitize_filename("C:\\Users\\me\\report.pdf") == "report.pdf"


@pytest.mark.parametrize("raw", [None, "", "   ", "/", "\\"])
def test_empty_or_path_only_filename_is_rejected(raw):
    with pytest.raises(HTTPException) as exc_info:
        _sanitize_filename(raw)
    assert exc_info.value.status_code == 400
