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
