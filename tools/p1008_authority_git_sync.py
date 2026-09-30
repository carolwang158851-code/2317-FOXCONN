#!/usr/bin/env python3
"""Read-only P1008 formal-authority to canonical-Git sync evaluator.

Formal authority remains governed by the existing exact-byte SHA-256 manifest
and Owner approval lineage. Git synchronization is a separate observation made
with path-aware Git blob identities. This module never mutates Git or authority
files and never makes Git synchronization a formal-publish prerequisite.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import p1008_canonical_warroom as canonical_warroom


MANIFEST_REL = "data/CSV_AUTHORITY_MANIFEST.json"
SHA256_PATTERN = re.compile(r"[0-9A-F]{64}")
GIT_OID_PATTERN = re.compile(r"[0-9a-f]{40,64}")
READ_ONLY_GIT_SUBCOMMANDS = {"remote", "ls-remote", "hash-object", "ls-tree"}
FORBIDDEN_GIT_SUBCOMMANDS = {
    "add", "commit", "push", "merge", "rebase", "reset", "stash", "clean"
}

GitRunner = Callable[..., subprocess.CompletedProcess[str]]


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest().upper()


def _safe_relative_path(value: Any) -> str:
    raw = str(value or "").replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or raw != path.as_posix():
        raise ValueError(f"UNSAFE_GOVERNED_PATH:{raw}")
    return raw


def _identity(kind: str, algorithm: str, value: str | None, source: str) -> dict[str, Any]:
    return {
        "domain": kind,
        "algorithm": algorithm,
        "value": value,
        "source": source,
    }


def validate_formal_authority(repository: Path) -> dict[str, Any]:
    """Validate current exact bytes against the existing authority manifest.

    This deliberately performs no Git comparison. Repository identity belongs
    to the separate Git-canonical domain evaluated later.
    """
    root = repository.resolve()
    manifest_path = root / MANIFEST_REL
    errors: list[str] = []
    evidence: list[dict[str, Any]] = []
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
        if not isinstance(manifest, dict):
            raise ValueError("AUTHORITY_MANIFEST_NOT_OBJECT")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return {
            "valid": False,
            "manifest": None,
            "governedFiles": [],
            "errors": [f"AUTHORITY_MANIFEST_MISSING_OR_INVALID:{exc}"],
        }

    manifest_sha = _sha256_bytes(manifest_bytes)
    evidence.append(
        {
            "path": MANIFEST_REL,
            "authorityClass": "FORMAL_AUTHORITY_MANIFEST",
            "formalAuthorityIdentity": _identity(
                "FORMAL_AUTHORITY_IDENTITY",
                "SHA-256_EXACT_BYTES",
                manifest_sha,
                "CURRENT_OWNER_GOVERNED_MANIFEST_BYTES",
            ),
            "worktreeByteIdentity": _identity(
                "WORKTREE_BYTE_IDENTITY", "SHA-256_EXACT_BYTES", manifest_sha, MANIFEST_REL
            ),
        }
    )

    policy = manifest.get("authorityPolicy")
    if not isinstance(policy, dict) or policy.get("hashAlgorithm") != "SHA-256":
        errors.append("AUTHORITY_HASH_ALGORITHM_INVALID")
    if not isinstance(policy, dict) or policy.get("automaticRecovery") is not False:
        errors.append("AUTHORITY_AUTOMATIC_RECOVERY_POLICY_INVALID")
    if manifest.get("approvedBy") != "Owner":
        errors.append("AUTHORITY_OWNER_APPROVAL_METADATA_INVALID")

    validation_classes = manifest.get("validationClasses")
    production_class = (
        validation_classes.get("productionAuthority", {})
        if isinstance(validation_classes, dict)
        else {}
    )
    research_class = (
        validation_classes.get("researchCurrentState", {})
        if isinstance(validation_classes, dict)
        else {}
    )
    if production_class.get("manifestSection") != "authoritativeFiles":
        errors.append("PRODUCTION_AUTHORITY_CLASS_INVALID")
    if research_class.get("manifestSection") != "nonAuthoritativeFiles":
        errors.append("RESEARCH_CURRENT_STATE_CLASS_INVALID")

    seen = {MANIFEST_REL}
    sections = (
        ("authoritativeFiles", "PRODUCTION_AUTHORITY", "sha256"),
        ("nonAuthoritativeFiles", "GOVERNED_NON_AUTHORITATIVE_CURRENT_STATE", "currentSha256"),
    )
    for section, authority_class, hash_field in sections:
        entries = manifest.get(section)
        if not isinstance(entries, list):
            errors.append(f"AUTHORITY_MANIFEST_SECTION_INVALID:{section}")
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                errors.append(f"AUTHORITY_MANIFEST_ENTRY_INVALID:{section}")
                continue
            try:
                relative = _safe_relative_path(entry.get("path"))
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if relative in seen:
                errors.append(f"DUPLICATE_GOVERNED_PATH:{relative}")
                continue
            seen.add(relative)
            expected = str(entry.get(hash_field) or "").upper()
            if not SHA256_PATTERN.fullmatch(expected):
                errors.append(f"AUTHORITY_IDENTITY_INVALID:{relative}")
            if section == "nonAuthoritativeFiles":
                if str(entry.get("sha256") or "").upper() != expected:
                    errors.append(f"RESEARCH_CURRENT_IDENTITY_INCONSISTENT:{relative}")
                baseline = str(entry.get("acceptedBaselineSha256") or "").upper()
                revision = str(entry.get("acceptedBaselineRevision") or "")
                if not SHA256_PATTERN.fullmatch(baseline) or not revision:
                    errors.append(f"RESEARCH_BASELINE_LINEAGE_INVALID:{relative}")

            path = root / relative
            try:
                actual = _sha256_file(path)
            except OSError:
                actual = None
                errors.append(f"GOVERNED_FILE_MISSING:{relative}")
            if actual is not None and actual != expected:
                errors.append(f"FORMAL_BYTE_IDENTITY_MISMATCH:{relative}")
            expected_size = entry.get("fileSizeBytes")
            if actual is not None and isinstance(expected_size, int):
                try:
                    if path.stat().st_size != expected_size:
                        errors.append(f"FORMAL_FILE_SIZE_MISMATCH:{relative}")
                except OSError:
                    errors.append(f"FORMAL_FILE_SIZE_UNAVAILABLE:{relative}")

            evidence.append(
                {
                    "path": relative,
                    "authorityClass": authority_class,
                    "formalAuthorityIdentity": _identity(
                        "FORMAL_AUTHORITY_IDENTITY",
                        "SHA-256_EXACT_BYTES",
                        expected if SHA256_PATTERN.fullmatch(expected) else None,
                        f"{MANIFEST_REL}::{section}.{hash_field}",
                    ),
                    "worktreeByteIdentity": _identity(
                        "WORKTREE_BYTE_IDENTITY",
                        "SHA-256_EXACT_BYTES",
                        actual,
                        relative,
                    ),
                }
            )

    return {
        "valid": not errors,
        "manifest": manifest,
        "governedFiles": evidence,
        "errors": errors,
    }


class ReadOnlyGitRunner:
    """Reject every Git subcommand outside the evaluator's read-only allowlist."""

    def __init__(self, runner: GitRunner | None = None) -> None:
        self.runner = runner or subprocess.run
        self.commands: list[list[str]] = []

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        command = [str(item) for item in args]
        if not command or command[0] != "git":
            raise RuntimeError("NON_GIT_COMMAND_REJECTED")
        try:
            index = command.index("-C")
            subcommand = command[index + 2]
        except (ValueError, IndexError) as exc:
            raise RuntimeError("GIT_COMMAND_SHAPE_REJECTED") from exc
        if subcommand in FORBIDDEN_GIT_SUBCOMMANDS:
            raise RuntimeError(f"GIT_MUTATION_REJECTED:{subcommand}")
        if subcommand not in READ_ONLY_GIT_SUBCOMMANDS:
            raise RuntimeError(f"NON_READ_ONLY_GIT_COMMAND_REJECTED:{subcommand}")
        if subcommand == "remote" and len(command) != index + 3:
            raise RuntimeError("REMOTE_MUTATION_REJECTED")
        self.commands.append(command)
        return self.runner(command, **kwargs)


def _blocked_result(
    canonical_remote: str | None,
    canonical_ref: str | None,
    canonical_sha: str | None,
    formal_valid: bool,
    evidence: list[dict[str, Any]],
    errors: list[str],
    commands: list[list[str]],
) -> dict[str, Any]:
    return {
        "canonicalRemote": canonical_remote,
        "canonicalRef": canonical_ref,
        "canonicalSha": canonical_sha,
        "formalAuthorityValid": formal_valid,
        "authorityGitSyncStatus": "BLOCKED",
        "authorityGitSyncPending": False,
        "authorityGitSynced": False,
        "perFileEvidence": evidence,
        "errors": errors,
        "gitMutationPerformed": False,
        "gitCommands": commands,
        "actionable": False,
    }


def not_evaluated_result() -> dict[str, Any]:
    """Stable status placeholder; explicit evaluation is available via the API."""
    return _blocked_result(
        "github", "refs/heads/main", None, False, [], ["NOT_EVALUATED"], []
    )


def evaluate_authority_git_sync(
    repository: Path,
    runner: GitRunner | None = None,
    expected_canonical_sha: str | None = None,
) -> dict[str, Any]:
    """Return SYNCED, PENDING, or BLOCKED without changing Git or authority."""
    root = repository.resolve()
    read_only_runner = ReadOnlyGitRunner(runner)
    canonical_remote: str | None = None
    canonical_ref: str | None = None
    canonical_sha: str | None = None
    evidence: list[dict[str, Any]] = []

    try:
        record = canonical_warroom.load_record()
        remote_contract = record.get("canonicalGitRemote")
        lifecycle = record.get("authorityGitLifecycle")
        if not isinstance(remote_contract, dict) or not isinstance(lifecycle, dict):
            raise ValueError("AUTHORITY_GIT_LIFECYCLE_CONTRACT_MISSING")
        canonical_remote = remote_contract.get("canonical_remote")
        canonical_ref = remote_contract.get("canonical_main_ref")
        if (
            lifecycle.get("formal_authority_identity_model")
            != "EXISTING_MANIFEST_EXACT_BYTE_SHA256_AND_OWNER_APPROVAL_LINEAGE"
            or lifecycle.get("git_canonical_identity_model") != "PATH_AWARE_GIT_BLOB_OID"
            or lifecycle.get("status_values") != ["SYNCED", "PENDING", "BLOCKED"]
            or lifecycle.get("formal_publish_implies_git_commit") is not False
            or lifecycle.get("git_sync_required_for_formal_publish") is not False
            or lifecycle.get("automatic_git_mutation") is not False
        ):
            raise ValueError("AUTHORITY_GIT_LIFECYCLE_CONTRACT_INVALID")
    except (canonical_warroom.CanonicalWarroomError, ValueError) as exc:
        return _blocked_result(
            canonical_remote,
            canonical_ref,
            None,
            False,
            [],
            [str(exc)],
            read_only_runner.commands,
        )

    formal = validate_formal_authority(root)
    evidence = formal["governedFiles"]
    if not formal["valid"]:
        return _blocked_result(
            canonical_remote,
            canonical_ref,
            None,
            False,
            evidence,
            formal["errors"],
            read_only_runner.commands,
        )

    try:
        remote = canonical_warroom.verify_canonical_git_remote(
            expected_sha=expected_canonical_sha,
            repository=root,
            runner=read_only_runner,
        )
        canonical_sha = remote["CANONICAL_DIRECT_SHA"]
    except canonical_warroom.CanonicalGitRemoteError as exc:
        return _blocked_result(
            canonical_remote,
            canonical_ref,
            None,
            True,
            evidence,
            [str(exc)],
            read_only_runner.commands,
        )

    comparison_errors: list[str] = []
    for item in evidence:
        relative = item["path"]
        common = {
            "capture_output": True,
            "text": True,
            "timeout": 15,
            "check": False,
        }
        try:
            expected_result = read_only_runner(
                ["git", "-C", str(root), "hash-object", "--path", relative, relative],
                **common,
            )
            if expected_result.returncode:
                raise RuntimeError("PATH_AWARE_HASH_FAILED")
            expected_oid = expected_result.stdout.strip().lower()
            if not GIT_OID_PATTERN.fullmatch(expected_oid):
                raise RuntimeError("PATH_AWARE_HASH_AMBIGUOUS")

            canonical_result = read_only_runner(
                ["git", "-C", str(root), "ls-tree", canonical_sha, "--", relative],
                **common,
            )
            if canonical_result.returncode:
                raise RuntimeError("CANONICAL_TREE_UNAVAILABLE")
            lines = [line for line in canonical_result.stdout.splitlines() if line.strip()]
            canonical_oid: str | None = None
            if lines:
                if len(lines) != 1:
                    raise RuntimeError("CANONICAL_TREE_IDENTITY_AMBIGUOUS")
                match = re.fullmatch(
                    r"[0-7]{6} blob ([0-9a-f]{40,64})\t(.+)", lines[0].strip()
                )
                if not match or match.group(2).replace("\\", "/") != relative:
                    raise RuntimeError("CANONICAL_TREE_IDENTITY_AMBIGUOUS")
                canonical_oid = match.group(1)
        except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
            item["gitCanonicalExpectedIdentity"] = _identity(
                "GIT_CANONICAL_IDENTITY", "GIT_BLOB_OID", None, "git hash-object --path"
            )
            item["canonicalMainGitIdentity"] = _identity(
                "GIT_CANONICAL_IDENTITY", "GIT_BLOB_OID", None, f"{canonical_sha}:{relative}"
            )
            item["syncMatch"] = None
            comparison_errors.append(f"GIT_IDENTITY_UNAVAILABLE:{relative}:{exc}")
            continue

        item["gitCanonicalExpectedIdentity"] = _identity(
            "GIT_CANONICAL_IDENTITY",
            "GIT_BLOB_OID",
            expected_oid,
            f"git hash-object --path {relative} {relative}",
        )
        item["canonicalMainGitIdentity"] = _identity(
            "GIT_CANONICAL_IDENTITY",
            "GIT_BLOB_OID",
            canonical_oid,
            f"{canonical_sha}:{relative}",
        )
        item["syncMatch"] = expected_oid == canonical_oid

    if comparison_errors:
        return _blocked_result(
            canonical_remote,
            canonical_ref,
            canonical_sha,
            True,
            evidence,
            comparison_errors,
            read_only_runner.commands,
        )

    synced = all(item.get("syncMatch") is True for item in evidence)
    status = "SYNCED" if synced else "PENDING"
    return {
        "canonicalRemote": canonical_remote,
        "canonicalRef": canonical_ref,
        "canonicalSha": canonical_sha,
        "formalAuthorityValid": True,
        "authorityGitSyncStatus": status,
        "authorityGitSyncPending": status == "PENDING",
        "authorityGitSynced": status == "SYNCED",
        "perFileEvidence": evidence,
        "errors": [],
        "gitMutationPerformed": False,
        "gitCommands": read_only_runner.commands,
        "actionable": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--expected-canonical-sha")
    args = parser.parse_args()
    result = evaluate_authority_git_sync(
        args.repository, expected_canonical_sha=args.expected_canonical_sha
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if result["authorityGitSyncStatus"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
