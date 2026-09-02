#!/usr/bin/env python3
"""Pure, non-publishing MAJOR_EVENT analysis/report provenance materialization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import warroom_major_event_baseline as baseline_registry


class MajorEventMaterializationError(RuntimeError):
    """Bound baseline provenance changed or could not be validated."""


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return baseline_registry._sha256(value)


def _with_hash(payload: dict[str, Any], field: str) -> dict[str, Any]:
    return {**payload, field: _sha256(_canonical_json_bytes(payload))}


def _validate_hash(payload: Mapping[str, Any], field: str, label: str) -> dict[str, Any]:
    supplied = payload.get(field)
    unhashed = {key: value for key, value in payload.items() if key != field}
    if supplied != _sha256(_canonical_json_bytes(unhashed)):
        raise MajorEventMaterializationError(f"{label}_HASH_INVALID")
    return dict(payload)


def _failure(status: str, reason: str) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "analysis_candidate": None,
        "report_candidate": None,
        "owner_review": None,
        "fallback_used": False,
        "fallback_event_type": None,
        "formal_report_generated": False,
        "publication": False,
        "publishAuthorized": False,
        "actionable": False,
    }


def _canonical_event_from_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "canonical_event_id": receipt.get("canonical_event_id"),
        "event_fingerprint": receipt.get("event_fingerprint"),
        "event_type": receipt.get("source_event_type"),
        "occurred_at_utc": receipt.get("canonical_event_occurred_at_utc"),
        "actionable": False,
    }


def _provenance(binding: Mapping[str, Any], receipt: Mapping[str, Any]) -> dict[str, Any]:
    selected = binding.get("selected_baseline")
    if binding.get("status") != "BOUND" or not isinstance(selected, Mapping):
        raise MajorEventMaterializationError("BOUND_MAJOR_EVENT_BASELINE_REQUIRED")
    required_binding = (
        "registry_id", "registry_version", "registry_sha256",
        "canonical_event_id", "event_fingerprint",
    )
    required_baseline = (
        "baseline_id", "version", "content_sha256", "governed_source_reference",
        "analysis_contract_reference", "analysis_contract_sha256",
    )
    if any(not binding.get(field) for field in required_binding) or any(
        not selected.get(field) for field in required_baseline
    ):
        raise MajorEventMaterializationError("BASELINE_PROVENANCE_INCOMPLETE")
    if not (
        binding["canonical_event_id"] == receipt.get("canonical_event_id")
        and binding["event_fingerprint"] == receipt.get("event_fingerprint")
        and binding.get("fallback_used") is False
        and binding.get("actionable") is False
        and selected.get("actionable") is False
    ):
        raise MajorEventMaterializationError("BASELINE_EVENT_PROVENANCE_MISMATCH")
    return {
        "canonical_event_id": binding["canonical_event_id"],
        "event_fingerprint": binding["event_fingerprint"],
        "canonical_event_occurred_at_utc": receipt["canonical_event_occurred_at_utc"],
        "baseline_id": selected["baseline_id"],
        "baseline_version": selected["version"],
        "baseline_content_sha256": selected["content_sha256"],
        "baseline_registry_id": binding["registry_id"],
        "baseline_registry_version": binding["registry_version"],
        "baseline_registry_sha256": binding["registry_sha256"],
        "analysis_contract_reference": selected["analysis_contract_reference"],
        "analysis_contract_sha256": selected["analysis_contract_sha256"],
        "governed_source_reference": selected["governed_source_reference"],
        "fallback_used": False,
        "fallback_event_type": None,
        "authoritative": False,
        "publishAuthorized": False,
        "actionable": False,
    }


def _materialize_analysis(
    package_root: Path, receipt: Mapping[str, Any], binding: Mapping[str, Any],
) -> dict[str, Any]:
    provenance = _provenance(binding, receipt)
    source = baseline_registry._safe_reference(
        package_root,
        provenance["governed_source_reference"],
        baseline_registry.ALLOWED_SOURCE_PREFIX,
    )
    verified = baseline_registry._verified_content(
        source.read_bytes(), provenance["baseline_content_sha256"]
    )
    try:
        baseline_content = json.loads(verified.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MajorEventMaterializationError("BASELINE_CONTENT_INVALID") from exc
    if not isinstance(baseline_content, dict):
        raise MajorEventMaterializationError("BASELINE_CONTENT_INVALID")
    payload = {
        "record_type": "P1008_MAJOR_EVENT_ANALYSIS_CANDIDATE_V1",
        "schema_version": "1.0",
        "state": "ANALYSIS_CANDIDATE_READY",
        "event_type": "MAJOR_EVENT",
        "analysis_role": "BOUND_REFERENCE_BASELINE_NOT_EVENT_DELTA",
        "baseline_provenance": provenance,
        "baseline_content": baseline_content,
        "baseline_content_canonical_sha256": _sha256(
            _canonical_json_bytes(baseline_content)
        ),
        "evidence_trigger_decision_id": receipt.get("decision_id"),
        "trigger_receipt_sha256": receipt.get("canonical_sha256"),
        "formal_report_generated": False,
        "ownerReviewRequired": True,
        "publication": False,
        "publishAuthorized": False,
        "actionable": False,
    }
    return _with_hash(payload, "analysis_candidate_sha256")


def _validate_content_against_governed_source(
    package_root: Path, candidate: Mapping[str, Any], provenance: Mapping[str, Any],
) -> None:
    source = baseline_registry._safe_reference(
        package_root,
        provenance["governed_source_reference"],
        baseline_registry.ALLOWED_SOURCE_PREFIX,
    )
    verified = baseline_registry._verified_content(
        source.read_bytes(), provenance["baseline_content_sha256"]
    )
    try:
        governed_content = json.loads(verified.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MajorEventMaterializationError("BASELINE_CONTENT_INVALID") from exc
    content = candidate.get("baseline_content")
    if not isinstance(content, dict) or content != governed_content:
        raise MajorEventMaterializationError("ANALYSIS_BASELINE_CONTENT_CHANGED")
    if _sha256(_canonical_json_bytes(content)) != candidate.get(
        "baseline_content_canonical_sha256"
    ):
        raise MajorEventMaterializationError("ANALYSIS_BASELINE_CONTENT_HASH_INVALID")


def validate_analysis_candidate(
    package_root: Path | str, candidate: Mapping[str, Any],
    binding: Mapping[str, Any], receipt: Mapping[str, Any],
) -> dict[str, Any]:
    validated = _validate_hash(candidate, "analysis_candidate_sha256", "ANALYSIS_CANDIDATE")
    if not (
        validated.get("record_type") == "P1008_MAJOR_EVENT_ANALYSIS_CANDIDATE_V1"
        and validated.get("state") == "ANALYSIS_CANDIDATE_READY"
        and validated.get("event_type") == "MAJOR_EVENT"
        and validated.get("analysis_role") == "BOUND_REFERENCE_BASELINE_NOT_EVENT_DELTA"
        and validated.get("formal_report_generated") is False
        and validated.get("ownerReviewRequired") is True
        and validated.get("publication") is False
        and validated.get("publishAuthorized") is False
        and validated.get("actionable") is False
        and validated.get("baseline_provenance") == _provenance(binding, receipt)
    ):
        raise MajorEventMaterializationError("ANALYSIS_CANDIDATE_PROVENANCE_INVALID")
    _validate_content_against_governed_source(
        Path(package_root).resolve(), validated, validated["baseline_provenance"]
    )
    return validated


def _materialize_report(
    package_root: Path, analysis: Mapping[str, Any],
    binding: Mapping[str, Any], receipt: Mapping[str, Any],
) -> dict[str, Any]:
    validated_analysis = validate_analysis_candidate(
        package_root, analysis, binding, receipt
    )
    payload = {
        "record_type": "P1008_MAJOR_EVENT_REPORT_PROVENANCE_CANDIDATE_V1",
        "schema_version": "1.0",
        "state": "REPORT_PROVENANCE_CANDIDATE_READY",
        "event_type": "MAJOR_EVENT",
        "analysis_candidate_sha256": validated_analysis["analysis_candidate_sha256"],
        "baseline_provenance": dict(validated_analysis["baseline_provenance"]),
        "formal_report_generated": False,
        "ownerReviewRequired": True,
        "publication": False,
        "publishAuthorized": False,
        "actionable": False,
    }
    return _with_hash(payload, "report_candidate_sha256")


def validate_report_candidate(
    package_root: Path | str, candidate: Mapping[str, Any], analysis: Mapping[str, Any],
    binding: Mapping[str, Any], receipt: Mapping[str, Any],
) -> dict[str, Any]:
    validated_analysis = validate_analysis_candidate(
        package_root, analysis, binding, receipt
    )
    validated = _validate_hash(candidate, "report_candidate_sha256", "REPORT_CANDIDATE")
    if not (
        validated.get("record_type") == "P1008_MAJOR_EVENT_REPORT_PROVENANCE_CANDIDATE_V1"
        and validated.get("state") == "REPORT_PROVENANCE_CANDIDATE_READY"
        and validated.get("event_type") == "MAJOR_EVENT"
        and validated.get("analysis_candidate_sha256") == validated_analysis["analysis_candidate_sha256"]
        and validated.get("baseline_provenance") == validated_analysis["baseline_provenance"]
        and validated.get("formal_report_generated") is False
        and validated.get("ownerReviewRequired") is True
        and validated.get("publication") is False
        and validated.get("publishAuthorized") is False
        and validated.get("actionable") is False
    ):
        raise MajorEventMaterializationError("REPORT_CANDIDATE_PROVENANCE_INVALID")
    return validated


def _materialize_owner_review(
    package_root: Path, report: Mapping[str, Any], analysis: Mapping[str, Any],
    binding: Mapping[str, Any], receipt: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_report_candidate(
        package_root, report, analysis, binding, receipt
    )
    payload = {
        "record_type": "P1008_MAJOR_EVENT_OWNER_REVIEW_ENVELOPE_V1",
        "schema_version": "1.0",
        "status": "OWNER_REVIEW_REQUIRED",
        "event_type": "MAJOR_EVENT",
        "report_candidate_sha256": validated["report_candidate_sha256"],
        "baseline_provenance": dict(validated["baseline_provenance"]),
        "ownerReviewRequired": True,
        "ownerApproved": False,
        "publication": False,
        "publishAuthorized": False,
        "actionable": False,
    }
    return _with_hash(payload, "owner_review_sha256")


def validate_owner_review(
    package_root: Path | str, owner_review: Mapping[str, Any], report: Mapping[str, Any],
    analysis: Mapping[str, Any], binding: Mapping[str, Any], receipt: Mapping[str, Any],
) -> dict[str, Any]:
    validated_report = validate_report_candidate(
        package_root, report, analysis, binding, receipt
    )
    validated = _validate_hash(owner_review, "owner_review_sha256", "OWNER_REVIEW")
    if not (
        validated.get("record_type") == "P1008_MAJOR_EVENT_OWNER_REVIEW_ENVELOPE_V1"
        and validated.get("status") == "OWNER_REVIEW_REQUIRED"
        and validated.get("event_type") == "MAJOR_EVENT"
        and validated.get("report_candidate_sha256") == validated_report["report_candidate_sha256"]
        and validated.get("baseline_provenance") == validated_report["baseline_provenance"]
        and validated.get("ownerReviewRequired") is True
        and validated.get("ownerApproved") is False
        and validated.get("publication") is False
        and validated.get("publishAuthorized") is False
        and validated.get("actionable") is False
    ):
        raise MajorEventMaterializationError("OWNER_REVIEW_PROVENANCE_INVALID")
    return validated


def materialize_major_event_provenance(
    package_root: Path | str,
    receipt: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Materialize three hash-bound envelopes without filesystem side effects."""

    root = Path(package_root).resolve()
    if not (
        receipt.get("event_type") == "MAJOR_EVENT"
        and receipt.get("report_trigger_valid") is True
        and receipt.get("actionable") is False
        and isinstance(receipt.get("analysis_baseline_binding"), Mapping)
        and receipt["analysis_baseline_binding"].get("status") == "BOUND"
    ):
        return _failure("FAIL_CLOSED", "BOUND_MAJOR_EVENT_REQUIRED")
    binding = receipt["analysis_baseline_binding"]
    selected = baseline_registry.select_major_event_baseline(
        root, _canonical_event_from_receipt(receipt), registry=registry
    )
    if selected.get("status") == "REVIEW_REQUIRED":
        return _failure("REVIEW_REQUIRED", str(selected.get("reason")))
    if selected.get("status") != "BOUND":
        return _failure("FAIL_CLOSED", str(selected.get("reason")))
    if selected != binding:
        return _failure("FAIL_CLOSED", "BASELINE_BINDING_PROVENANCE_CHANGED")
    try:
        analysis = _materialize_analysis(root, receipt, binding)
        report = _materialize_report(root, analysis, binding, receipt)
        owner_review = _materialize_owner_review(
            root, report, analysis, binding, receipt
        )
        return {
            "status": "OWNER_REVIEW_REQUIRED",
            "reason": "BOUND_PROVENANCE_MATERIALIZED",
            "analysis_candidate": analysis,
            "report_candidate": report,
            "owner_review": owner_review,
            "fallback_used": False,
            "fallback_event_type": None,
            "formal_report_generated": False,
            "publication": False,
            "publishAuthorized": False,
            "actionable": False,
        }
    except (MajorEventMaterializationError, OSError, TypeError, ValueError) as exc:
        return _failure("FAIL_CLOSED", str(exc) or type(exc).__name__)
