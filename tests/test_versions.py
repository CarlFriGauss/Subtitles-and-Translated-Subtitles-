"""INF-4: the release version must be identical everywhere it is hard-coded."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_versions.py"
spec = importlib.util.spec_from_file_location("check_versions", SCRIPT)
check_versions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_versions)


def test_all_versions_match():
    assert check_versions.main() == 0


def test_mismatch_is_reported(monkeypatch, capsys):
    real = check_versions.found_versions
    monkeypatch.setattr(check_versions, "found_versions", lambda: {**real(), "desktop/package.json": "9.9.9"})
    assert check_versions.main() == 1
    assert "desktop/package.json: 9.9.9" in capsys.readouterr().out
