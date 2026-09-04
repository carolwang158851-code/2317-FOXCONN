"""Pinned, read-only operational-root preflight; never promotes or publishes."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
RECORD = CODE_ROOT / "contracts/p1008_operational_governance/v1.0/canonical_warroom.json"
APPROVED_RECORD_SHA256 = "73D2A805771BF03EA48A6FA6D32DA04602C8B2A82D218C1165DFC6B008F97708"


class CanonicalWarroomError(RuntimeError):
    pass


def load_record() -> dict:
    try:
        record = json.loads(RECORD.read_bytes())
        digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"),
                                          ensure_ascii=False).encode("utf-8")).hexdigest().upper()
        if digest != APPROVED_RECORD_SHA256:
            raise CanonicalWarroomError("CANONICAL_RECORD_HASH_MISMATCH")
        return record
    except (OSError, ValueError) as exc:
        raise CanonicalWarroomError("CANONICAL_RECORD_MISSING_OR_INVALID") from exc


def resolve_canonical(package_root: Path | None = None) -> dict:
    record = load_record()  # Explicit overrides never bypass record validation.
    canonical = CODE_ROOT.parent / record["canonicalRoot"]
    if not canonical.is_dir() or canonical.resolve() != canonical.absolute():
        raise CanonicalWarroomError("CANONICAL_ROOT_MISSING_OR_REDIRECTED")
    try:
        result = subprocess.run(
            ["git", "-C", str(canonical), "merge-base", "--is-ancestor", record["acceptedHead"], "HEAD"],
            capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CanonicalWarroomError("ACCEPTED_HEAD_VALIDATION_FAILED") from exc
    if result.returncode:
        raise CanonicalWarroomError("ACCEPTED_HEAD_NOT_PRESERVED")
    selected = package_root.resolve() if package_root is not None else canonical.resolve()
    if not (selected / "launcher.html").is_file():
        raise CanonicalWarroomError("SELECTED_PACKAGE_INVALID")
    override = selected != canonical.resolve()
    return {"status": "EXPLICIT_NON_CANONICAL_OVERRIDE" if override else "CANONICAL_VERIFIED",
            "canonicalRoot": str(canonical), "resolvedPackageRoot": str(selected),
            "explicitPackageRoot": package_root is not None, "override": override,
            "recordSha256": APPROVED_RECORD_SHA256, "acceptedHead": record["acceptedHead"],
            "phase4dAcceptanceRun": record["phase4dAcceptanceRun"],
            "rollbackRoot": str(CODE_ROOT.parent / record["previousOperationalRoot"]),
            "publishAuthorized": False, "publication": False}
