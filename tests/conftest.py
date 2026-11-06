"""Shared pytest setup.

Several SubGen modules have import-time side effects (they create directories and
read configuration under SUBGEN_DATA_DIR). Point that at a throwaway directory
*before* any subgen module is imported, so tests never touch a developer's real
configuration, keys, database or uploads.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="subgen-test-data-"))
os.environ["SUBGEN_DATA_DIR"] = str(TEST_DATA_DIR)

for extra in (ROOT, ROOT / "web", ROOT / "cloud"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))


import pytest  # noqa: E402

_PROVIDER_KEY_SUFFIXES = ("_API_KEY", "_API_KEY_WORK")


@pytest.fixture(autouse=True)
def _isolate_environment():
    """Run every test without real provider keys and undo any os.environ edits.

    Tests must never reach a paid API with a developer's real key, and code
    under test (e.g. load_api_keys) writes os.environ directly, which
    monkeypatch cannot undo.
    """
    saved = dict(os.environ)
    for key in list(os.environ):
        if key.upper().endswith(_PROVIDER_KEY_SUFFIXES) or key.upper().startswith("OPENAI_API_KEY"):
            del os.environ[key]
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)
