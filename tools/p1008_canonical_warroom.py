"""Pinned, read-only operational-root preflight; never promotes or publishes."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Callable

CODE_ROOT = Path(__file__).resolve().parents[1]
RECORD = CODE_ROOT / "contracts/p1008_operational_governance/v1.0/canonical_warroom.json"
APPROVED_RECORD_SHA256 = "9DCE85BCD3079FFB90BEE7C5D968FFBC82A123314C32430217E39987C636F225"


class CanonicalWarroomError(RuntimeError):
    pass


class CanonicalGitRemoteError(RuntimeError):
    """Fail-closed canonical Git remote identity error."""


GitRunner = Callable[..., subprocess.CompletedProcess[str]]


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


def verify_canonical_git_remote(
    expected_sha: str | None = None,
    requested_remote: str | None = None,
    repository: Path | None = None,
    runner: GitRunner | None = None,
) -> dict:
    """Verify canonical authority by direct remote query, never by cached refs.

    ``origin`` and every other configured remote remain non-authoritative even
    when their histories are identical to, ahead of, or divergent from github.
    The function is read-only and never repairs remote or upstream config.
    """
    record = load_record()
    contract = record.get("canonicalGitRemote")
    if not isinstance(contract, dict):
        raise CanonicalGitRemoteError("CANONICAL_REMOTE_CONTRACT_MISSING_OR_INVALID")

    canonical_remote = contract.get("canonical_remote")
    canonical_ref = contract.get("canonical_main_ref")
    origin_role = contract.get("origin_role")
    if (
        canonical_remote != "github"
        or canonical_ref != "refs/heads/main"
        or origin_role != "NON_AUTHORITATIVE_LOCAL_SIBLING"
        or contract.get("direct_query_required") is not True
        or contract.get("fallback_allowed") is not False
        or contract.get("fail_closed") is not True
    ):
        raise CanonicalGitRemoteError("CANONICAL_REMOTE_CONTRACT_MISSING_OR_INVALID")

    if requested_remote is not None and requested_remote != canonical_remote:
        raise CanonicalGitRemoteError("REQUESTED_REMOTE_IS_NOT_CANONICAL")

    run = runner or subprocess.run
    repo = (repository or CODE_ROOT).resolve()
    common = {"capture_output": True, "text": True, "timeout": 15, "check": False}
    try:
        remotes_result = run(["git", "-C", str(repo), "remote"], **common)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CanonicalGitRemoteError("REMOTE_IDENTITY_GATE_QUERY_FAILED") from exc
    if remotes_result.returncode:
        raise CanonicalGitRemoteError("REMOTE_IDENTITY_GATE_QUERY_FAILED")

    configured_remotes = {
        line.strip() for line in remotes_result.stdout.splitlines() if line.strip()
    }
    if canonical_remote not in configured_remotes:
        raise CanonicalGitRemoteError("CANONICAL_REMOTE_MISSING")

    try:
        direct_result = run(
            ["git", "-C", str(repo), "ls-remote", canonical_remote, canonical_ref],
            **common,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CanonicalGitRemoteError("CANONICAL_DIRECT_QUERY_FAILED") from exc
    if direct_result.returncode:
        raise CanonicalGitRemoteError("CANONICAL_DIRECT_QUERY_FAILED")

    lines = [line.strip() for line in direct_result.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise CanonicalGitRemoteError("CANONICAL_REMOTE_IDENTITY_AMBIGUOUS")
    fields = lines[0].split()
    if (
        len(fields) != 2
        or not re.fullmatch(r"[0-9a-fA-F]{40}", fields[0])
        or fields[1] != canonical_ref
    ):
        raise CanonicalGitRemoteError("CANONICAL_REMOTE_IDENTITY_AMBIGUOUS")

    direct_sha = fields[0].lower()
    if expected_sha is not None:
        expected = expected_sha.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}", expected) or direct_sha != expected:
            raise CanonicalGitRemoteError("CANONICAL_DIRECT_SHA_MISMATCH")

    declared_non_authoritative = set(contract.get("non_authoritative_remotes", []))
    non_authoritative = sorted(
        remote for remote in configured_remotes
        if remote != canonical_remote or remote in declared_non_authoritative
    )
    return {
        "CANONICAL_REMOTE": canonical_remote,
        "CANONICAL_REF": canonical_ref,
        "CANONICAL_DIRECT_SHA": direct_sha,
        "NON_AUTHORITATIVE_REMOTES": non_authoritative,
        "REMOTE_IDENTITY_GATE": "PASS",
        "origin_role": origin_role,
        "queryMode": "DIRECT_LS_REMOTE",
        "fallbackUsed": False,
    }


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
