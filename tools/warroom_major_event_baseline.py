#!/usr/bin/env python3
"""Deterministic, read-only MAJOR_EVENT analysis-baseline binding."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping


REGISTRY_REL = Path(
    "contracts/p1008_report_production/v1.1/"
    "P1008_MAJOR_EVENT_ANALYSIS_BASELINE_REGISTRY_V1.json"
)
REGISTRY_FIELDS = frozenset({
    "recordType", "registryVersion", "classification", "baselines",
    "authoritative", "publishAuthorized", "actionable",
})
BASELINE_FIELDS = frozenset({
    "baselineId", "version", "status", "governedSourceReference",
    "contentSha256", "analysisContractReference", "analysisContractSha256",
    "supportedCanonicalEventScope", "ownerReviewRequired", "authoritative",
    "publishAuthorized", "actionable",
})
SCOPE_FIELDS = frozenset({
    "sourceEventTypes", "canonicalEventIdPattern", "effectiveFromUtc",
    "effectiveThroughUtc",
})
SHA256 = re.compile(r"^[A-F0-9]{64}$")
BASELINE_ID = re.compile(r"^P1008_[A-Z0-9_:-]+$")
SUPPORTED_BASELINE_VERSION = "1.0"
APPROVED_REGISTRY_SHA256 = "85A2709DDCE14D518704C4243B29BFF15E5626904D8390DE0FFFF616715139D8"
APPROVED_MAJOR_EVENT_SOURCE_TYPES = frozenset({
    "MAJOR_EVENT", "EARNINGS_CALL", "MATERIAL_COMPANY_DISCLOSURE",
    "APPLE_OFFICIAL_PRODUCT_EVENT", "APPLE_OFFICIAL_GUIDANCE_EVENT",
    "AI_SERVER_MAJOR_ORDER", "AI_SERVER_MATERIAL_SUPPLY_CHAIN_CHANGE",
    "MATERIAL_FX_CHANGE", "MATERIAL_TARIFF_OR_POLICY_CHANGE",
    "APPROVED_PRICE_VOLUME_POSITIONING_ANOMALY",
})
ALLOWED_SOURCE_PREFIX = Path("modules/p1008_research_plugin/config/quarterly_earnings")
ALLOWED_CONTRACT_PREFIX = Path("contracts/p1008_analysis")


class MajorEventBaselineError(RuntimeError):
    """A baseline registry or canonical-event binding failed closed."""


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _verified_content(raw: bytes, expected_sha256: str) -> bytes:
    if not isinstance(expected_sha256, str) or not SHA256.fullmatch(expected_sha256):
        raise MajorEventBaselineError("BASELINE_HASH_IDENTITY_INVALID")
    if _sha256(raw) == expected_sha256:
        return raw
    normalized = raw.replace(b"\r\n", b"\n")
    if b"\r" in normalized or normalized == raw or _sha256(normalized) != expected_sha256:
        raise MajorEventBaselineError("BASELINE_HASH_MISMATCH")
    return normalized


def _safe_reference(package_root: Path, reference: object, allowed_prefix: Path) -> Path:
    if not isinstance(reference, str):
        raise MajorEventBaselineError("BASELINE_REFERENCE_INVALID")
    relative = Path(reference)
    if relative.is_absolute() or ".." in relative.parts or not relative.is_relative_to(allowed_prefix):
        raise MajorEventBaselineError("BASELINE_REFERENCE_OUTSIDE_GOVERNED_SCOPE")
    target = (package_root / relative).resolve()
    if not target.is_relative_to(package_root) or not target.is_file():
        raise MajorEventBaselineError("BASELINE_REFERENCE_UNAVAILABLE")
    current = target
    while current != package_root:
        is_junction = getattr(os.path, "isjunction", lambda _path: False)
        try:
            attributes = current.stat(follow_symlinks=False).st_file_attributes
        except (AttributeError, OSError):
            attributes = 0
        if (
            current.is_symlink() or is_junction(current)
            or bool(attributes & getattr(os, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        ):
            raise MajorEventBaselineError("BASELINE_REFERENCE_REPARSE_DENIED")
        current = current.parent
    return target


def _utc(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise MajorEventBaselineError(f"{label}_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MajorEventBaselineError(f"{label}_INVALID") from exc
    if parsed.tzinfo is None:
        raise MajorEventBaselineError(f"{label}_INVALID")
    return parsed


def _validate_registry(
    package_root: Path, registry: Mapping[str, Any], *, require_approved_identity: bool = False,
) -> dict[str, Any]:
    if set(registry) != REGISTRY_FIELDS:
        raise MajorEventBaselineError("BASELINE_REGISTRY_SHAPE_INVALID")
    if not (
        registry.get("recordType") == "P1008_MAJOR_EVENT_ANALYSIS_BASELINE_REGISTRY_V1"
        and registry.get("registryVersion") == SUPPORTED_BASELINE_VERSION
        and registry.get("classification") == "GOVERNED_ANALYSIS_BASELINE_REGISTRY"
        and registry.get("authoritative") is False
        and registry.get("publishAuthorized") is False
        and registry.get("actionable") is False
    ):
        raise MajorEventBaselineError("BASELINE_REGISTRY_GOVERNANCE_INVALID")
    baselines = registry.get("baselines")
    if not isinstance(baselines, list) or not baselines:
        raise MajorEventBaselineError("BASELINE_REGISTRY_EMPTY")
    identities: set[tuple[str, str]] = set()
    for baseline in baselines:
        if not isinstance(baseline, dict) or set(baseline) != BASELINE_FIELDS:
            raise MajorEventBaselineError("BASELINE_ENTRY_SHAPE_INVALID")
        identity = (baseline.get("baselineId"), baseline.get("version"))
        if not (
            isinstance(identity[0], str) and BASELINE_ID.fullmatch(identity[0])
            and identity[1] == SUPPORTED_BASELINE_VERSION
        ):
            raise MajorEventBaselineError("BASELINE_ID_OR_VERSION_INVALID")
        if identity in identities:
            raise MajorEventBaselineError("BASELINE_IDENTITY_DUPLICATED")
        identities.add(identity)
        if not (
            baseline.get("status") == "APPROVED"
            and baseline.get("ownerReviewRequired") is True
            and baseline.get("authoritative") is False
            and baseline.get("publishAuthorized") is False
            and baseline.get("actionable") is False
        ):
            raise MajorEventBaselineError("BASELINE_APPROVAL_STATE_INVALID")
        source = _safe_reference(
            package_root, baseline.get("governedSourceReference"), ALLOWED_SOURCE_PREFIX
        )
        contract = _safe_reference(
            package_root, baseline.get("analysisContractReference"), ALLOWED_CONTRACT_PREFIX
        )
        _verified_content(source.read_bytes(), baseline.get("contentSha256"))
        _verified_content(contract.read_bytes(), baseline.get("analysisContractSha256"))
        scope = baseline.get("supportedCanonicalEventScope")
        if not isinstance(scope, dict) or set(scope) != SCOPE_FIELDS:
            raise MajorEventBaselineError("BASELINE_SCOPE_INVALID")
        source_types = scope.get("sourceEventTypes")
        if not isinstance(source_types, list) or not source_types or not all(
            isinstance(item, str) and item for item in source_types
        ):
            raise MajorEventBaselineError("BASELINE_SCOPE_EVENT_TYPES_INVALID")
        if len(set(source_types)) != len(source_types) or not set(source_types).issubset(
            APPROVED_MAJOR_EVENT_SOURCE_TYPES
        ):
            raise MajorEventBaselineError("BASELINE_SCOPE_EVENT_TYPES_INVALID")
        pattern = scope.get("canonicalEventIdPattern")
        if not isinstance(pattern, str):
            raise MajorEventBaselineError("BASELINE_SCOPE_PATTERN_INVALID")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise MajorEventBaselineError("BASELINE_SCOPE_PATTERN_INVALID") from exc
        start = _utc(scope.get("effectiveFromUtc"), "BASELINE_SCOPE_START")
        end_raw = scope.get("effectiveThroughUtc")
        if end_raw is not None and _utc(end_raw, "BASELINE_SCOPE_END") < start:
            raise MajorEventBaselineError("BASELINE_SCOPE_WINDOW_INVALID")
    validated = dict(registry)
    if require_approved_identity and _sha256(
        _canonical_json_bytes(validated)
    ) != APPROVED_REGISTRY_SHA256:
        raise MajorEventBaselineError("BASELINE_REGISTRY_HASH_MISMATCH")
    return validated


def load_registry(package_root: Path | str) -> dict[str, Any]:
    root = Path(package_root).resolve()
    path = (root / REGISTRY_REL).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise MajorEventBaselineError("BASELINE_REGISTRY_UNAVAILABLE")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MajorEventBaselineError("BASELINE_REGISTRY_INVALID") from exc
    if not isinstance(value, dict):
        raise MajorEventBaselineError("BASELINE_REGISTRY_INVALID")
    return _validate_registry(root, value, require_approved_identity=True)


def _validate_canonical_event(event: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "canonical_event_id", "event_fingerprint", "event_type",
        "occurred_at_utc", "actionable",
    }
    if not required.issubset(event) or event.get("actionable") is not False:
        raise MajorEventBaselineError("VALIDATED_CANONICAL_EVENT_REQUIRED")
    event_id = event.get("canonical_event_id")
    event_type = event.get("event_type")
    occurred = event.get("occurred_at_utc")
    if not all(isinstance(item, str) and item for item in (event_id, event_type, occurred)):
        raise MajorEventBaselineError("VALIDATED_CANONICAL_EVENT_REQUIRED")
    expected = _sha256(_canonical_json_bytes({
        "event_type": event_type,
        "canonical_event_id": event_id,
        "occurred_at_utc": occurred,
    }))
    if event.get("event_fingerprint") != expected:
        raise MajorEventBaselineError("CANONICAL_EVENT_FINGERPRINT_INVALID")
    _utc(occurred, "CANONICAL_EVENT_TIME")
    return dict(event)


def select_major_event_baseline(
    package_root: Path | str,
    canonical_event: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Select exactly one approved baseline, returning review/fail state safely."""

    root = Path(package_root).resolve()
    try:
        selected_registry = (
            load_registry(root) if registry is None else _validate_registry(root, registry)
        )
        event = _validate_canonical_event(canonical_event)
        occurred = _utc(event["occurred_at_utc"], "CANONICAL_EVENT_TIME")
        matches: list[dict[str, Any]] = []
        for baseline in selected_registry["baselines"]:
            scope = baseline["supportedCanonicalEventScope"]
            if event["event_type"] not in scope["sourceEventTypes"]:
                continue
            if re.fullmatch(scope["canonicalEventIdPattern"], event["canonical_event_id"]) is None:
                continue
            if occurred < _utc(scope["effectiveFromUtc"], "BASELINE_SCOPE_START"):
                continue
            end = scope["effectiveThroughUtc"]
            if end is not None and occurred > _utc(end, "BASELINE_SCOPE_END"):
                continue
            matches.append(baseline)
        registry_sha = _sha256(_canonical_json_bytes(selected_registry))
        common = {
            "registry_id": selected_registry["recordType"],
            "registry_version": selected_registry["registryVersion"],
            "registry_sha256": registry_sha,
            "canonical_event_id": event["canonical_event_id"],
            "event_fingerprint": event["event_fingerprint"],
            "fallback_used": False,
            "fallback_event_type": None,
            "authoritative": False,
            "publishAuthorized": False,
            "actionable": False,
        }
        if not matches:
            return {**common, "status": "REVIEW_REQUIRED", "reason": "NO_APPROVED_BASELINE_MATCH", "selected_baseline": None}
        if len(matches) != 1:
            return {**common, "status": "REVIEW_REQUIRED", "reason": "AMBIGUOUS_APPROVED_BASELINE_MATCH", "selected_baseline": None}
        match = matches[0]
        return {
            **common,
            "status": "BOUND",
            "reason": "UNIQUE_APPROVED_BASELINE_MATCH",
            "selected_baseline": {
                "baseline_id": match["baselineId"],
                "version": match["version"],
                "governed_source_reference": match["governedSourceReference"],
                "content_sha256": match["contentSha256"],
                "analysis_contract_reference": match["analysisContractReference"],
                "analysis_contract_sha256": match["analysisContractSha256"],
                "owner_review_required": True,
                "authoritative": False,
                "publishAuthorized": False,
                "actionable": False,
            },
        }
    except (MajorEventBaselineError, OSError, TypeError, ValueError) as exc:
        return {
            "status": "FAIL_CLOSED",
            "reason": str(exc) or type(exc).__name__,
            "selected_baseline": None,
            "fallback_used": False,
            "fallback_event_type": None,
            "authoritative": False,
            "publishAuthorized": False,
            "actionable": False,
        }
