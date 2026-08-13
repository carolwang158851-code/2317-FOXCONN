from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4


MODULE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
SRC_ROOT = MODULE_ROOT / "src"
FIXTURE_PATH = MODULE_ROOT / "tests" / "fixtures" / "phaseb1" / "monthly_revenue_fixture.json"
AUTHORITY_BASELINES_PATH = MODULE_ROOT / "tests" / "fixtures" / "authority_baselines.json"
sys.path.insert(0, str(SRC_ROOT))


@contextmanager
def scratch(prefix: str) -> Iterator[Path]:
    root = PACKAGE_ROOT / "runtime" / "phaseb1_test_scratch"
    root.mkdir(parents=True, exist_ok=True)
    # Do not use tempfile.TemporaryDirectory here. The verified bundled Python
    # can create normal runtime folders on Windows/OneDrive, while inherited
    # TemporaryDirectory ACLs are known to raise PermissionError in this host.
    path = root / f"{prefix}{uuid4().hex}"
    path.mkdir(parents=False, exist_ok=False)
    yield path


def fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def write_fixture(root: Path, payload: dict[str, object]) -> Path:
    path = root / "fixture.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n")
    return path


def authority_sandbox(root: Path) -> Path:
    package = root / "package"
    shutil.copytree(PACKAGE_ROOT / "data", package / "data")
    shutil.copytree(
        PACKAGE_ROOT / "contracts" / "p1008_research_plugin" / "v1.0",
        package / "contracts" / "p1008_research_plugin" / "v1.0",
    )
    (package / "rules").mkdir(parents=True)
    shutil.copy2(
        PACKAGE_ROOT / "rules" / "RULE_STATUS_MANIFEST.json",
        package / "rules" / "RULE_STATUS_MANIFEST.json",
    )
    return package


def frozen_authority_package(root: Path) -> Path:
    """Materialize the Phase B1 golden authority, independent of production data."""

    package = root / "frozen-package"
    shutil.copytree(
        PACKAGE_ROOT / "contracts" / "p1008_research_plugin" / "v1.0",
        package / "contracts" / "p1008_research_plugin" / "v1.0",
    )
    (package / "rules").mkdir(parents=True)
    shutil.copy2(
        PACKAGE_ROOT / "rules" / "RULE_STATUS_MANIFEST.json",
        package / "rules" / "RULE_STATUS_MANIFEST.json",
    )
    baseline = json.loads(AUTHORITY_BASELINES_PATH.read_text(encoding="utf-8"))[
        "phaseB1Frozen"
    ]
    revision = str(baseline["gitRevision"])

    def frozen_blob(relative: str) -> bytes:
        result = subprocess.run(
            ["git", "-C", str(PACKAGE_ROOT), "show", f"{revision}:{relative}"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Frozen Phase B1 authority is unavailable: {revision}:{relative}"
            )
        return result.stdout

    manifest_relative = "data/CSV_AUTHORITY_MANIFEST.json"
    manifest_bytes = frozen_blob(manifest_relative)
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest().upper()
    if manifest_digest != str(baseline["manifestSha256"]).upper():
        raise RuntimeError("Frozen Phase B1 authority hash mismatch: manifest")

    try:
        manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Frozen Phase B1 authority manifest is invalid") from exc

    declared_files = [
        *manifest.get("authoritativeFiles", []),
        *manifest.get("nonAuthoritativeFiles", []),
    ]
    if not declared_files:
        raise RuntimeError("Frozen Phase B1 authority manifest declares no files")

    expected: dict[str, str] = {}
    for entry in declared_files:
        if not isinstance(entry, dict):
            raise RuntimeError("Frozen Phase B1 authority manifest entry is invalid")
        relative = entry.get("path")
        digest = entry.get("sha256")
        if not isinstance(relative, str) or not relative.startswith("data/"):
            raise RuntimeError("Frozen Phase B1 authority path is invalid")
        if relative == manifest_relative or relative in expected:
            raise RuntimeError(f"Frozen Phase B1 authority path is duplicated: {relative}")
        if not isinstance(digest, str) or len(digest) != 64:
            raise RuntimeError(f"Frozen Phase B1 authority digest is invalid: {relative}")
        expected[relative] = digest.upper()

    manifest_target = package / manifest_relative
    manifest_target.parent.mkdir(parents=True, exist_ok=False)
    manifest_target.write_bytes(manifest_bytes)

    for relative, digest in expected.items():
        content = frozen_blob(relative)
        actual = hashlib.sha256(content).hexdigest().upper()
        if actual != digest:
            raise RuntimeError(f"Frozen Phase B1 authority hash mismatch: {relative}")
        target = package / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    return package


def fixture_pipeline(root: Path, fixture_path: Path | None = None):
    from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline

    return PhaseB1Pipeline(
        frozen_authority_package(root),
        fixture_path or FIXTURE_PATH,
    )
