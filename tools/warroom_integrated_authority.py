#!/usr/bin/env python3
"""Fail-closed, read-only Phase3A candidate authority binding."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping


class IntegratedAuthorityError(RuntimeError):
    """The embedded candidate or its promotion boundary is invalid."""


BINDING_REL = Path(
    "contracts/p1008_authority_integration/v1.0/"
    "P1008_PHASE3A_CANONICAL_AUTHORITY_BINDING_V1.json"
)
EXPECTED_MANIFEST_SHA256 = (
    "AACF739D02261CFD70C82B2E97D47C01340FCE344B6D49CAA1F135CDF6285DEF"
)
GOVERNANCE = {
    "classification": "CANDIDATE_NON_AUTHORITATIVE",
    "authoritative": False,
    "actionable": False,
    "publishAuthorized": False,
    "ownerPromotionRequired": True,
    "promotionStatus": "OWNER_PROMOTION_REQUIRED",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegratedAuthorityError(f"{label}_INVALID") from exc
    if not isinstance(value, dict):
        raise IntegratedAuthorityError(f"{label}_INVALID")
    return value


def _safe_path(root: Path, relative: Any) -> Path:
    raw = Path(str(relative or ""))
    if raw.is_absolute() or not raw.parts or ".." in raw.parts:
        raise IntegratedAuthorityError("CANDIDATE_PATH_INVALID")
    resolved = (root / raw).resolve()
    if not resolved.is_relative_to(root):
        raise IntegratedAuthorityError("CANDIDATE_PATH_INVALID")
    return resolved


def _csv_rows(payload: bytes, path: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        lines = payload.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        raise IntegratedAuthorityError(f"CANDIDATE_CSV_ENCODING_INVALID:{path}") from exc
    data_lines = [line for line in lines if line.strip() and not line.lstrip().startswith("##")]
    if not data_lines:
        raise IntegratedAuthorityError(f"CANDIDATE_CSV_EMPTY:{path}")
    reader = csv.DictReader(io.StringIO("\n".join(data_lines)))
    if not reader.fieldnames:
        raise IntegratedAuthorityError(f"CANDIDATE_CSV_HEADER_INVALID:{path}")
    return list(reader.fieldnames), [dict(row) for row in reader]


def load_candidate(code_root: Path | str) -> dict[str, Any]:
    """Validate and expose a non-authoritative candidate snapshot."""

    root = Path(code_root).resolve()
    binding_path = _safe_path(root, BINDING_REL)
    binding = _read_json(binding_path, "AUTHORITY_BINDING")
    if not (
        binding.get("recordType") == "P1008_PHASE3A_CANONICAL_AUTHORITY_BINDING_V1"
        and binding.get("bindingVersion") == "1.0"
        and binding.get("candidateManifestSha256") == EXPECTED_MANIFEST_SHA256
        and binding.get("governance") == GOVERNANCE
        and binding.get("runtimePolicy", {}).get("sourceWorktreeDependency") is False
        and binding.get("runtimePolicy", {}).get("productionAuthorityReplacement") is False
        and binding.get("runtimePolicy", {}).get("publicationAuthorizationImplied") is False
    ):
        raise IntegratedAuthorityError("AUTHORITY_BINDING_GOVERNANCE_INVALID")
    embedded = _safe_path(root, binding.get("embeddedCandidateRoot"))
    manifest_path = _safe_path(embedded, binding.get("sourceManifestRelativePath"))
    manifest_bytes = manifest_path.read_bytes()
    if _sha256(manifest_bytes) != EXPECTED_MANIFEST_SHA256:
        raise IntegratedAuthorityError("CANDIDATE_MANIFEST_HASH_MISMATCH")
    manifest = _read_json(manifest_path, "CANDIDATE_MANIFEST")
    if not (
        manifest.get("candidateId") == binding.get("candidateId")
        and manifest.get("manifestVersion") == binding.get("candidateManifestVersion")
        and manifest.get("classification") == GOVERNANCE["classification"]
        and manifest.get("authoritative") is False
        and manifest.get("actionable") is False
        and manifest.get("publishAuthorized") is False
        and manifest.get("ownerPromotionRequired") is True
        and manifest.get("promotionGate", {}).get("status")
        == GOVERNANCE["promotionStatus"]
    ):
        raise IntegratedAuthorityError("CANDIDATE_MANIFEST_GOVERNANCE_INVALID")
    declared = {
        str(item.get("path")): item
        for item in manifest.get("candidateFiles", [])
        if isinstance(item, Mapping)
    }
    bound = binding.get("files")
    if not isinstance(bound, list) or len(bound) != 5:
        raise IntegratedAuthorityError("AUTHORITY_BINDING_FILE_SET_INVALID")
    verified: list[dict[str, Any]] = []
    for item in bound:
        if not isinstance(item, Mapping):
            raise IntegratedAuthorityError("AUTHORITY_BINDING_FILE_SET_INVALID")
        relative = str(item.get("path") or "")
        manifest_item = declared.get(relative)
        path = _safe_path(embedded, relative)
        if not path.is_file():
            raise IntegratedAuthorityError(f"CANDIDATE_FILE_MISSING:{relative}")
        payload = path.read_bytes()
        actual = _sha256(payload)
        if not (
            actual == item.get("sha256") == (manifest_item or {}).get("sha256")
            and len(payload) == item.get("sizeBytes") == (manifest_item or {}).get("fileSizeBytes")
        ):
            raise IntegratedAuthorityError(f"CANDIDATE_FILE_IDENTITY_MISMATCH:{relative}")
        headers, rows = _csv_rows(payload, relative)
        if not (
            headers == manifest_item.get("columns")
            and len(rows) == manifest_item.get("rowCount")
            and manifest_item.get("authoritative") is False
            and manifest_item.get("actionable") is False
            and manifest_item.get("ownerPromotionRequired") is True
        ):
            raise IntegratedAuthorityError(f"CANDIDATE_FILE_SCHEMA_INVALID:{relative}")
        verified.append({
            "path": relative,
            "sha256": actual,
            "sizeBytes": len(payload),
            "rowCount": len(rows),
            "dateRange": manifest_item.get("dateRange"),
            "classification": manifest_item.get("classification"),
            "validationStatus": manifest_item.get("validationStatus"),
        })
    binding_sha = _sha256(_canonical_bytes(binding))
    return {
        "recordType": "P1008_INTEGRATED_AUTHORITY_VIEW_V1",
        "bindingId": binding["bindingId"],
        "bindingVersion": binding["bindingVersion"],
        "bindingSha256": binding_sha,
        "candidateId": manifest["candidateId"],
        "candidateManifestVersion": manifest["manifestVersion"],
        "candidateManifestSha256": EXPECTED_MANIFEST_SHA256,
        "sourcePackage": binding["sourcePackage"],
        "sourceLineages": manifest.get("sourceLineages"),
        "q2Lineage": manifest.get("q2Lineage"),
        "twseReceipts": manifest.get("twseReceipts"),
        "observationProvenance": manifest.get("observationProvenance"),
        "quarantine": manifest.get("quarantine"),
        "files": verified,
        **GOVERNANCE,
        "readOnly": True,
    }


def report_authority_context(code_root: Path | str) -> dict[str, Any]:
    """Return a compact, hash-bound composition context."""

    view = load_candidate(code_root)
    context = {
        "recordType": "P1008_REPORT_AUTHORITY_CONTEXT_V1",
        "bindingId": view["bindingId"],
        "bindingVersion": view["bindingVersion"],
        "bindingSha256": view["bindingSha256"],
        "candidateId": view["candidateId"],
        "candidateManifestVersion": view["candidateManifestVersion"],
        "candidateManifestSha256": view["candidateManifestSha256"],
        "fileIdentities": [
            {
                "path": item["path"], "sha256": item["sha256"],
                "rowCount": item["rowCount"], "dateRange": item["dateRange"],
            }
            for item in view["files"]
        ],
        "q2Lineage": view["q2Lineage"],
        "twseReceipts": view["twseReceipts"],
        "observationProvenance": view["observationProvenance"],
        "quarantine": view["quarantine"],
        **GOVERNANCE,
    }
    return {**context, "contextSha256": _sha256(_canonical_bytes(context))}
