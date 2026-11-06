"""Fail when the release version differs between the files that hard-code it.

subgen_version.py is the source of truth. Run from the repository root:

    python scripts/check_versions.py
"""

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def source_of_truth():
    match = re.search(r'__version__\s*=\s*"([^"]+)"', read("subgen_version.py"))
    if not match:
        raise SystemExit("subgen_version.py does not define __version__")
    return match.group(1)


def cargo_lock_package_version(text, name):
    for block in text.split("[[package]]"):
        if re.search(rf'^name = "{re.escape(name)}"$', block, flags=re.MULTILINE):
            match = re.search(r'^version = "([^"]+)"$', block, flags=re.MULTILINE)
            return match.group(1) if match else None
    return None


def found_versions():
    cargo = tomllib.loads(read("desktop/src-tauri/Cargo.toml"))
    package_lock = json.loads(read("desktop/package-lock.json"))
    service_worker = re.search(r"subgen-cloud-v([0-9][^'\"]*)", read("cloud_web/service-worker.js"))
    return {
        "pyproject.toml": tomllib.loads(read("pyproject.toml"))["project"]["version"],
        "desktop/package.json": json.loads(read("desktop/package.json"))["version"],
        "desktop/package-lock.json": package_lock.get("version"),
        "desktop/package-lock.json (root package)": package_lock.get("packages", {}).get("", {}).get("version"),
        "desktop/src-tauri/Cargo.toml": cargo["package"]["version"],
        "desktop/src-tauri/Cargo.lock": cargo_lock_package_version(read("desktop/src-tauri/Cargo.lock"), cargo["package"]["name"]),
        "desktop/src-tauri/tauri.conf.json": json.loads(read("desktop/src-tauri/tauri.conf.json"))["version"],
        "cloud_web/service-worker.js": service_worker.group(1) if service_worker else None,
    }


def main():
    expected = source_of_truth()
    mismatches = {path: version for path, version in found_versions().items() if version != expected}
    if mismatches:
        print(f"subgen_version.py says {expected}, but:")
        for path, version in mismatches.items():
            print(f"  {path}: {version}")
        return 1
    print(f"All version strings match {expected}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
