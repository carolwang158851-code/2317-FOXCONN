"""Route P1008 conformance by accepted phase metadata, never branch names."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


SCRIPT_ROOT = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_ROOT.parents[2]
ACCEPTANCE_PATH = PACKAGE_ROOT / "contracts" / "p1008_research_plugin" / "acceptance" / "v1.1" / "PHASE_ROUTING_ACCEPTANCE_RECORD.json"
CURRENT_RUNNER_PATH = SCRIPT_ROOT / "v1.1" / "run_contract_tests.py"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _load_current_runner() -> Any:
    spec = importlib.util.spec_from_file_location("p1008_current_conformance", CURRENT_RUNNER_PATH)
    require(spec is not None and spec.loader is not None, "Current conformance runner is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_command(command: list[str], cwd: Path) -> dict[str, Any]:
    result = subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
    parsed: dict[str, Any] | None = None
    if result.stdout.strip():
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            parsed = None
    return {"returnCode": result.returncode, "report": parsed, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}


def legacy_archive_command(archive_path: Path, legacy_commit: str) -> list[str]:
    """Build a runner-independent archive command for the frozen Git tree."""
    return [
        "git",
        "-c",
        "core.autocrlf=false",
        "-c",
        "core.eol=lf",
        "-C",
        str(PACKAGE_ROOT),
        "archive",
        "--format=zip",
        f"--output={archive_path}",
        legacy_commit,
    ]


def resolve_legacy_tree(record: dict[str, Any], destination: Path) -> Path:
    legacy_commit = record["phaseLineage"]["legacyFrozenCommit"]
    archive_path = destination / "legacy.zip"
    legacy_root = destination / "legacy"
    result = subprocess.run(
        legacy_archive_command(archive_path, legacy_commit),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    require(result.returncode == 0, f"Cannot archive frozen legacy tree: {result.stderr.strip()}")
    legacy_root.mkdir()
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(legacy_root)

    # The frozen authority manifest is the byte authority. One historical CSV
    # was committed with normalized LF while its accepted hash described a
    # mixed-line-ending Windows worktree. v1.1 records that exact checkout
    # materialization; every restored file must match both recorded authorities.
    manifest = read_json(legacy_root / "data" / "CSV_AUTHORITY_MANIFEST.json")
    entries = manifest.get("authoritativeFiles", []) + manifest.get("nonAuthoritativeFiles", [])
    recipes = record.get("legacyWorktreeMaterialization", {})
    for entry in entries:
        path = legacy_root / entry["path"]
        expected = entry["sha256"].upper()
        if sha256_file(path) == expected:
            continue
        recipe = recipes.get(entry["path"])
        require(isinstance(recipe, dict), f"Cannot reproduce frozen authority bytes: {entry['path']}")
        require(recipe.get("expectedSha256") == expected, f"Legacy materialization hash conflict: {entry['path']}")
        lines = path.read_bytes().replace(b"\r\n", b"\n").splitlines(keepends=True)
        crlf_lines = set(recipe.get("crlfLineNumbers", []))
        require(crlf_lines and max(crlf_lines) <= len(lines), f"Invalid legacy materialization recipe: {entry['path']}")
        restored = b"".join(
            line[:-1] + b"\r\n" if index in crlf_lines and line.endswith(b"\n") else line
            for index, line in enumerate(lines, start=1)
        )
        require(hashlib.sha256(restored).hexdigest().upper() == expected, f"Cannot reproduce frozen authority bytes: {entry['path']}")
        require(len(restored) == recipe.get("expectedSizeBytes") == entry.get("fileSizeBytes"), f"Frozen authority size mismatch: {entry['path']}")
        path.write_bytes(restored)
    return legacy_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Run legacy and current P1008 conformance")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--no-write-report", action="store_true")
    args = parser.parse_args()
    if not args.all:
        parser.error("--all is required")

    current = _load_current_runner()
    record = read_json(ACCEPTANCE_PATH)
    current.validate_phase_record(record)
    immutable_before = {path: sha256_file(PACKAGE_ROOT / path) for path in record["immutableV1"]["artifacts"]}

    legacy_result: dict[str, Any]
    with tempfile.TemporaryDirectory(prefix="p1008-conformance-") as temp_dir:
        legacy_root = resolve_legacy_tree(record, Path(temp_dir))
        current.validate_module_state(legacy_root, "ABSENT")
        legacy_runner = legacy_root / record["legacySuite"]
        require(legacy_runner.is_file(), "Frozen legacy runner is absent from resolved tree")
        legacy_result = run_command([sys.executable, str(legacy_runner), "--all", "--no-write-report"], legacy_root)

    current_result = run_command([sys.executable, str(PACKAGE_ROOT / record["currentSuite"]), "--all", "--no-write-report"], PACKAGE_ROOT)
    immutable_after = {path: sha256_file(PACKAGE_ROOT / path) for path in record["immutableV1"]["artifacts"]}
    require(immutable_after == immutable_before, "Frozen v1 bytes changed during routing")

    all_pass = legacy_result["returnCode"] == 0 and current_result["returnCode"] == 0
    report = {
        "reportId": "P1008_PHASE_AWARE_CONFORMANCE_ROUTING_V1_1",
        "routingSource": ACCEPTANCE_PATH.relative_to(PACKAGE_ROOT).as_posix(),
        "phase": record["currentPhase"],
        "legacy": {"commit": record["phaseLineage"]["legacyFrozenCommit"], "status": "PASS" if legacy_result["returnCode"] == 0 else "FAIL", "report": legacy_result["report"], "stderr": legacy_result["stderr"]},
        "current": {"version": record["contractVersion"], "status": "PASS" if current_result["returnCode"] == 0 else "FAIL", "report": current_result["report"], "stderr": current_result["stderr"]},
        "overallStatus": "PASS" if all_pass else "FAIL",
        "safety": {"openAiCallsMade": 0, "webSearchCallsMade": 0, "canvaCallsMade": 0, "formalWrites": 0, "actionable": False},
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
