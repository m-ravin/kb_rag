"""
Adds azure-functions/document_processor to sys.path so tests in this
directory can import the real pipeline stage modules (chunking, extraction,
embedding, etc.) that live flat in that folder alongside function_app.py.

That folder isn't part of the installable `backend` package (see
pyproject.toml's [tool.hatch.build.targets.wheel]) and its parent directory
name has a hyphen, so it can't be reached via a normal dotted import —
this sys.path insert is the standard workaround.
"""

import sys
from pathlib import Path

_DOCUMENT_PROCESSOR_DIR = (
    Path(__file__).resolve().parents[3] / "azure-functions" / "document_processor"
)
if str(_DOCUMENT_PROCESSOR_DIR) not in sys.path:
    sys.path.insert(0, str(_DOCUMENT_PROCESSOR_DIR))
