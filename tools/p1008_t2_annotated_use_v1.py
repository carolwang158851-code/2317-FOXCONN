"""Fail-closed T2 annotated-use contract and deterministic Owner gate.

This module extends the existing P1008_DERIVED_KPI_CANDIDATE_V1 research
candidate without redefining its tier semantics.  It never writes formal CSV,
never updates formal authority, never enables formal scoring, and never changes
the T1 authority bridge.  Owner approval is candidate-hash and scope bound.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from p1008_derived_kpi_candidate_v1 import (
    REQUIRED_FIELDS as SOURCE_REQUIRED_FIELDS,
    T0,
    T1,
    T2,
    T3,
    T4,
    recompute,
    validate_candidate,
)
from p1008_t1_derived_kpi_bridge_v1 import (
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)


ADAPTER_VERSION = "P1008_T2_ANNOTATED_USE_ADAPTER_V1"
T2_CANDIDATE_SCHEMA = "P1008_T2_RESEARCH_CANDIDATE_V1"
T2_APPROVAL_SCHEMA = "P1008_T2_ANNOTATED_USE_APPROVAL_V1"
T2_DISPLAY_SCHEMA = "P1008_T2_ANNOTATED_DISPLAY_V1"
T2_RECONCILIATION_SCHEMA = "P1008_T2_RECONCILIATION_V1"

CONFIDENCE_CLASSES = ("HIGH", "MEDIUM", "LOW")
RECONCILIATION_STATES = (
    "ESTIMATE_ACTIVE",
    "OFFICIAL_REPLACEMENT_AVAILABLE",
    "RECONCILED",
    "ESTIMATE_REJECTED",
)
USE_SCOPE_STATUS = {
    "REPORT_MAIN_TEXT": "ISOLATED_FORMATTER_READY",
    "REPORT_KPI_TABLE": "ISOLATED_FORMATTER_READY",
    "RESEARCH_APPENDIX": "ISOLATED_FORMATTER_READY",
    "RESEARCH_DASHBOARD_DISPLAY": "NOT_WIRED",
}
MAIN_KPI_SCOPES = frozenset({"REPORT_MAIN_TEXT", "REPORT_KPI_TABLE"})
HASH_RE = re.compile(r"^[A-F0-9]{64}$")
UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
T2_CANDIDATE_FIELDS = (
    "schema_version", "candidate_id", "source_candidate_id", "source_candidate_hash",
    "synthetic_fixture", "metric_id", "metric_name", "dimension", "period", "as_of_date",
    "point_estimate", "unit", "data_tier", "formula_id", "formula_version",
    "formula_expression", "input_metric_ids", "input_values", "input_units", "input_periods",
    "input_source_ids", "input_source_tiers", "input_source_locators", "input_hashes",
    "assumptions", "rounding_rule", "estimation_method", "confidence", "limitations",
    "estimate_lower_bound", "estimate_upper_bound", "range_method", "sensitivity_notes",
    "semantic_name", "semantic_match_status", "period_basis", "unit_basis",
    "denominator_definition", "reconciliation_state", "adapter_version", "adapter_hash",
    "created_at", "candidate_owner", "origin", "display_label_zh", "directly_disclosed",
    "claims_official", "owner_review_required", "owner_approved_for_annotated_use",
    "formal_authority", "formal_scoring_eligible", "formal_publish_eligible",
    "production_scoring_enabled", "research_only", "actionable",
)


class T2AnnotatedUseError(ValueError):
    """Raised when a T2 candidate, approval, display, or reconciliation fails."""


@dataclass(frozen=True)
class ValidationResult:
    status: str
    errors: tuple[str, ...]
    recomputed_point_estimate: str | None = None


def _valid_timestamp(value: str, field: str) -> None:
    if not isinstance(value, str) or not UTC_TIMESTAMP_RE.fullmatch(value):
        raise T2AnnotatedUseError(f"{field} must be a whole-second UTC timestamp ending in Z")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise T2AnnotatedUseError(f"{field} is not a valid UTC timestamp") from exc


def _decimal_string(value: Any, field: str) -> str:
    from decimal import Decimal, InvalidOperation

    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise T2AnnotatedUseError(f"{field} must be a decimal number") from exc
    if not number.is_finite():
        raise T2AnnotatedUseError(f"{field} must be finite")
    return format(number, "f")


def _clean_nonempty_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise T2AnnotatedUseError(f"{field} must be a non-empty array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise T2AnnotatedUseError(f"{field} must contain only non-empty strings")
    return [item.strip() for item in value]


def semantic_substitution_allowed(source_semantic: str, target_semantic: str) -> bool:
    """T2 estimates the same semantic metric; proxy relabelling is never allowed."""

    return bool(source_semantic.strip()) and source_semantic.strip().upper() == target_semantic.strip().upper()


def validate_t2_source_candidate(
    source: Mapping[str, Any],
    *,
    limitations: Sequence[str],
    sensitivity_notes: str,
    estimated_semantic_name: str | None = None,
    claims_official: bool = False,
) -> ValidationResult:
    """Validate the completed derived-candidate contract plus T2 use requirements."""

    candidate = dict(source)
    errors: list[str] = []
    tier = candidate.get("data_tier")
    if tier != T2:
        if tier in {T0, T1, T3, T4}:
            errors.append(f"data_tier {tier} is not a T2 annotated-use candidate")
        else:
            errors.append(f"unknown or missing data_tier: {tier!r}")
        return ValidationResult("FAIL", tuple(errors))

    contract_errors = validate_candidate(candidate)
    errors.extend(f"input contract: {item}" for item in contract_errors)
    unexpected = sorted(set(candidate) - set(SOURCE_REQUIRED_FIELDS))
    if unexpected:
        errors.append("input contract contains unsupported fields: " + ", ".join(unexpected))

    assumptions = candidate.get("assumptions")
    if not isinstance(assumptions, list) or not assumptions:
        errors.append("T2 assumptions are required")
    confidence = candidate.get("confidence")
    if confidence not in CONFIDENCE_CLASSES:
        errors.append("confidence must be HIGH, MEDIUM, or LOW")
    elif confidence == "HIGH":
        errors.append("completed derived-candidate contract does not allow HIGH confidence for T2")
    if not limitations or any(not isinstance(item, str) or not item.strip() for item in limitations):
        errors.append("limitations are required")
    if not isinstance(sensitivity_notes, str) or not sensitivity_notes.strip():
        errors.append("sensitivity_notes are required")

    for field in ("formula_id", "formula_version", "formula_expression"):
        if not isinstance(candidate.get(field), str) or not candidate[field].strip():
            errors.append(f"{field} is required")
    for field in (
        "input_metric_ids",
        "input_values",
        "input_units",
        "input_periods",
        "input_source_ids",
        "input_source_tiers",
        "input_source_locators",
        "input_hashes",
    ):
        value = candidate.get(field)
        if not isinstance(value, list) or not value:
            errors.append(f"{field} lineage is required")
    hashes = candidate.get("input_hashes", [])
    if isinstance(hashes, list) and any(not isinstance(item, str) or not HASH_RE.fullmatch(item) for item in hashes):
        errors.append("all input hashes must be uppercase SHA-256 digests")
    if any(item == T4 for item in candidate.get("input_source_tiers", []) if isinstance(item, str)):
        errors.append("T4 scenario ancestry cannot represent a historical T2 estimate")

    if candidate.get("period_alignment_rule") != "ALL_INPUT_PERIODS_EQUAL_CANDIDATE_PERIOD":
        errors.append("period basis is ambiguous")
    if not isinstance(candidate.get("unit_conversion_rule"), str) or not candidate["unit_conversion_rule"].strip():
        errors.append("unit basis is ambiguous")
    if not isinstance(candidate.get("denominator_definition"), str) or candidate["denominator_definition"].strip().upper() in {
        "", "N/A", "NA", "NONE", "NULL", "UNKNOWN", "UNSPECIFIED"
    }:
        errors.append("denominator basis is ambiguous")

    sensitivity = candidate.get("sensitivity_range")
    if not isinstance(sensitivity, dict):
        errors.append("T2 estimate range is required")
    else:
        for field in ("low", "high", "unit", "method"):
            if field not in sensitivity or sensitivity[field] in (None, ""):
                errors.append(f"sensitivity_range.{field} is required")
        try:
            low = _decimal_string(sensitivity.get("low"), "estimate_lower_bound")
            high = _decimal_string(sensitivity.get("high"), "estimate_upper_bound")
            point = _decimal_string(candidate.get("value"), "point_estimate")
            from decimal import Decimal
            if not Decimal(low) <= Decimal(point) <= Decimal(high):
                errors.append("point estimate must fall within estimate bounds")
        except T2AnnotatedUseError as exc:
            errors.append(str(exc))
        if sensitivity.get("unit") != candidate.get("unit"):
            errors.append("estimate range unit must equal point-estimate unit")

    target_semantic = candidate.get("semantic_name", "")
    estimated_semantic = estimated_semantic_name or target_semantic
    if candidate.get("semantic_match_status") != "EXACT_MATCH" or not semantic_substitution_allowed(
        str(estimated_semantic), str(target_semantic)
    ):
        errors.append("semantic substitution is forbidden")
    if candidate.get("proxy_metric_used") is not False or candidate.get("proxy_relabelled_as_direct") is not False:
        errors.append("proxy relabelling as a direct fact is forbidden")
    if claims_official:
        errors.append("T2 cannot claim to be official or directly disclosed")
    if candidate.get("actionable") is not False:
        errors.append("actionable must be false")
    if candidate.get("publication") is not False:
        errors.append("publication must be false")
    if candidate.get("production_scoring_enabled") is not False:
        errors.append("production scoring must remain disabled")

    recomputed: str | None = None
    if not contract_errors:
        try:
            recomputed = format(recompute(candidate), "f")
        except Exception as exc:  # source validator has already constrained arithmetic
            errors.append(f"deterministic recomputation failed: {exc}")
        if recomputed is not None and recomputed != str(candidate.get("value")):
            errors.append(f"deterministic recomputation mismatch: {recomputed} != {candidate.get('value')}")

    return ValidationResult(
        "PASS" if not errors else "FAIL",
        tuple(dict.fromkeys(errors)),
        recomputed,
    )


def build_t2_research_candidate(
    source: Mapping[str, Any],
    *,
    limitations: Sequence[str],
    sensitivity_notes: str,
    created_at: str,
    estimated_semantic_name: str | None = None,
    claims_official: bool = False,
    adapter_path: str | Path | None = None,
) -> dict[str, Any]:
    """Create immutable-content T2 research candidate state A (not approved)."""

    _valid_timestamp(created_at, "created_at")
    result = validate_t2_source_candidate(
        source,
        limitations=limitations,
        sensitivity_notes=sensitivity_notes,
        estimated_semantic_name=estimated_semantic_name,
        claims_official=claims_official,
    )
    if result.status != "PASS":
        raise T2AnnotatedUseError("; ".join(result.errors))

    source_object = dict(source)
    source_hash = sha256_bytes(canonical_json_bytes(source_object))
    adapter_hash = sha256_file(Path(adapter_path) if adapter_path else Path(__file__))
    sensitivity = source_object["sensitivity_range"]
    candidate_id = f"T2C-{source_hash[:16]}-{adapter_hash[:12]}"
    return {
        "schema_version": T2_CANDIDATE_SCHEMA,
        "candidate_id": candidate_id,
        "source_candidate_id": source_object["candidate_id"],
        "source_candidate_hash": source_hash,
        "synthetic_fixture": source_object["synthetic_fixture"],
        "metric_id": source_object["metric_id"],
        "metric_name": source_object["metric_name"],
        "dimension": source_object["dimension"],
        "period": source_object["period"],
        "as_of_date": source_object["as_of_date"],
        "point_estimate": source_object["value"],
        "unit": source_object["unit"],
        "data_tier": T2,
        "formula_id": source_object["formula_id"],
        "formula_version": source_object["formula_version"],
        "formula_expression": source_object["formula_expression"],
        "input_metric_ids": list(source_object["input_metric_ids"]),
        "input_values": list(source_object["input_values"]),
        "input_units": list(source_object["input_units"]),
        "input_periods": list(source_object["input_periods"]),
        "input_source_ids": list(source_object["input_source_ids"]),
        "input_source_tiers": list(source_object["input_source_tiers"]),
        "input_source_locators": list(source_object["input_source_locators"]),
        "input_hashes": list(source_object["input_hashes"]),
        "assumptions": list(source_object["assumptions"]),
        "rounding_rule": source_object["rounding_rule"],
        "estimation_method": source_object["derivation_method"],
        "confidence": source_object["confidence"],
        "limitations": [item.strip() for item in limitations],
        "estimate_lower_bound": sensitivity["low"],
        "estimate_upper_bound": sensitivity["high"],
        "range_method": sensitivity["method"],
        "sensitivity_notes": sensitivity_notes.strip(),
        "semantic_name": source_object["semantic_name"],
        "semantic_match_status": "EXACT_MATCH",
        "period_basis": source_object["period_alignment_rule"],
        "unit_basis": source_object["unit_conversion_rule"],
        "denominator_definition": source_object["denominator_definition"],
        "reconciliation_state": "ESTIMATE_ACTIVE",
        "adapter_version": ADAPTER_VERSION,
        "adapter_hash": adapter_hash,
        "created_at": created_at,
        "candidate_owner": "WAR_ROOM_RESEARCH",
        "origin": "PLUGIN_DERIVED_T2",
        "display_label_zh": "推估值",
        "directly_disclosed": False,
        "claims_official": False,
        "owner_review_required": True,
        "owner_approved_for_annotated_use": False,
        "formal_authority": False,
        "formal_scoring_eligible": False,
        "formal_publish_eligible": False,
        "production_scoring_enabled": False,
        "research_only": True,
        "actionable": False,
    }


def _candidate_hash(candidate: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(dict(candidate)))


def validate_t2_research_candidate(candidate: Mapping[str, Any]) -> None:
    """Validate the exact immutable state-A envelope before any Owner gate."""

    keys = set(candidate)
    required = set(T2_CANDIDATE_FIELDS)
    missing = sorted(required - keys)
    extra = sorted(keys - required)
    if missing:
        raise T2AnnotatedUseError("T2 candidate missing fields: " + ", ".join(missing))
    if extra:
        raise T2AnnotatedUseError("T2 candidate has unsupported fields: " + ", ".join(extra))
    if candidate["schema_version"] != T2_CANDIDATE_SCHEMA or candidate["data_tier"] != T2:
        raise T2AnnotatedUseError("candidate is not a T2 research-candidate envelope")
    if candidate["reconciliation_state"] != "ESTIMATE_ACTIVE":
        raise T2AnnotatedUseError("new T2 candidate must start in ESTIMATE_ACTIVE")
    if candidate["confidence"] not in {"MEDIUM", "LOW"}:
        raise T2AnnotatedUseError("completed T2 input contract permits MEDIUM or LOW confidence")
    if not candidate["assumptions"] or not candidate["limitations"]:
        raise T2AnnotatedUseError("T2 assumptions and limitations are required")
    for field in ("source_candidate_hash", "adapter_hash"):
        if not isinstance(candidate[field], str) or not HASH_RE.fullmatch(candidate[field]):
            raise T2AnnotatedUseError(f"{field} must be an uppercase SHA-256 digest")
    _valid_timestamp(str(candidate["created_at"]), "created_at")
    from decimal import Decimal
    low = Decimal(_decimal_string(candidate["estimate_lower_bound"], "estimate_lower_bound"))
    point = Decimal(_decimal_string(candidate["point_estimate"], "point_estimate"))
    high = Decimal(_decimal_string(candidate["estimate_upper_bound"], "estimate_upper_bound"))
    if not low <= point <= high:
        raise T2AnnotatedUseError("point estimate must fall within estimate bounds")
    if candidate["semantic_match_status"] != "EXACT_MATCH":
        raise T2AnnotatedUseError("semantic substitution is forbidden")
    required_false = (
        "directly_disclosed", "claims_official", "owner_approved_for_annotated_use",
        "formal_authority", "formal_scoring_eligible", "formal_publish_eligible",
        "production_scoring_enabled", "actionable",
    )
    if any(candidate[field] is not False for field in required_false):
        raise T2AnnotatedUseError("T2 candidate violates its non-formal research boundary")
    if candidate["owner_review_required"] is not True or candidate["research_only"] is not True:
        raise T2AnnotatedUseError("T2 candidate must require Owner review and remain research-only")


def _ordered_scopes(scopes: Sequence[str]) -> list[str]:
    if not isinstance(scopes, Sequence) or isinstance(scopes, (str, bytes)) or not scopes:
        raise T2AnnotatedUseError("at least one approved use scope is required")
    requested = set(scopes)
    unknown = sorted(requested - set(USE_SCOPE_STATUS))
    if unknown:
        raise T2AnnotatedUseError("unknown annotated-use scope: " + ", ".join(unknown))
    not_wired = sorted(scope for scope in requested if USE_SCOPE_STATUS[scope] == "NOT_WIRED")
    if not_wired:
        raise T2AnnotatedUseError("annotated-use scope is NOT_WIRED: " + ", ".join(not_wired))
    return [scope for scope in USE_SCOPE_STATUS if scope in requested]


def required_owner_approval_phrase(candidate: Mapping[str, Any], scopes: Sequence[str]) -> str:
    ordered = _ordered_scopes(scopes)
    return (
        "OWNER_APPROVE_T2_ANNOTATED_USE "
        f"{candidate['candidate_id']} {_candidate_hash(candidate)} "
        f"SCOPES {','.join(ordered)}"
    )


def create_owner_annotated_use_approval(
    candidate: Mapping[str, Any],
    *,
    approved_use_scope: Sequence[str],
    approved_at: str,
    approval_phrase: str,
) -> dict[str, Any]:
    """Create state B without mutating the state-A candidate."""

    _valid_timestamp(approved_at, "approved_at")
    validate_t2_research_candidate(candidate)
    scopes = _ordered_scopes(approved_use_scope)
    if candidate.get("confidence") == "LOW" and MAIN_KPI_SCOPES.intersection(scopes):
        raise T2AnnotatedUseError(
            "LOW confidence main-KPI eligibility is UNDEFINED; only a separate Owner policy may authorize it"
        )
    expected_phrase = required_owner_approval_phrase(candidate, scopes)
    if approval_phrase != expected_phrase:
        raise T2AnnotatedUseError("exact candidate-hash and scope-bound Owner approval phrase is required")

    before = canonical_json_bytes(dict(candidate))
    candidate_hash = sha256_bytes(before)
    scope_hash = sha256_bytes(canonical_json_bytes(scopes))
    estimate_range = {
        "lower_bound": candidate["estimate_lower_bound"],
        "upper_bound": candidate["estimate_upper_bound"],
        "unit": candidate["unit"],
    }
    approval = {
        "schema_version": T2_APPROVAL_SCHEMA,
        "approval_id": f"T2APP-{candidate_hash[:16]}-{scope_hash[:12]}",
        "candidate_id": candidate["candidate_id"],
        "candidate_hash": candidate_hash,
        "metric_id": candidate["metric_id"],
        "period": candidate["period"],
        "point_estimate": candidate["point_estimate"],
        "estimate_range": estimate_range,
        "formula_id": candidate["formula_id"],
        "formula_version": candidate["formula_version"],
        "approved_use_scope": scopes,
        "scope_wiring_status": {scope: USE_SCOPE_STATUS[scope] for scope in scopes},
        "approved_at": approved_at,
        "approved_by": "Owner",
        "approval_phrase_hash": hashlib.sha256(approval_phrase.encode("utf-8")).hexdigest().upper(),
        "owner_approved_for_annotated_use": True,
        "formal_authority": False,
        "formal_scoring_eligible": False,
        "formal_publish_eligible": False,
        "research_only": True,
        "actionable": False,
    }
    if canonical_json_bytes(dict(candidate)) != before:
        raise T2AnnotatedUseError("approval gate altered candidate content")
    return approval


def validate_owner_approval(
    candidate: Mapping[str, Any], approval: Mapping[str, Any], *, required_scope: str
) -> None:
    validate_t2_research_candidate(candidate)
    if approval.get("schema_version") != T2_APPROVAL_SCHEMA:
        raise T2AnnotatedUseError("approval schema is invalid")
    if approval.get("candidate_id") != candidate.get("candidate_id"):
        raise T2AnnotatedUseError("approval candidate_id does not match")
    if approval.get("candidate_hash") != _candidate_hash(candidate):
        raise T2AnnotatedUseError("candidate content changed after Owner approval")
    if required_scope not in approval.get("approved_use_scope", []):
        raise T2AnnotatedUseError(f"scope was not Owner approved: {required_scope}")
    if USE_SCOPE_STATUS.get(required_scope) != "ISOLATED_FORMATTER_READY":
        raise T2AnnotatedUseError(f"scope is NOT_WIRED: {required_scope}")
    expected_range = {
        "lower_bound": candidate.get("estimate_lower_bound"),
        "upper_bound": candidate.get("estimate_upper_bound"),
        "unit": candidate.get("unit"),
    }
    bound_fields = {
        "metric_id": candidate.get("metric_id"),
        "period": candidate.get("period"),
        "point_estimate": candidate.get("point_estimate"),
        "estimate_range": expected_range,
        "formula_id": candidate.get("formula_id"),
        "formula_version": candidate.get("formula_version"),
    }
    for field, expected in bound_fields.items():
        if approval.get(field) != expected:
            raise T2AnnotatedUseError(f"approval binding mismatch: {field}")
    if approval.get("approved_by") != "Owner" or approval.get("owner_approved_for_annotated_use") is not True:
        raise T2AnnotatedUseError("explicit Owner annotated-use approval is absent")
    if any(
        approval.get(field) is not False
        for field in ("formal_authority", "formal_scoring_eligible", "formal_publish_eligible", "actionable")
    ):
        raise T2AnnotatedUseError("approval cannot grant formal, scoring, publish, or actionable status")


def compile_annotated_display(
    candidate: Mapping[str, Any], approval: Mapping[str, Any], *, use_scope: str
) -> dict[str, Any]:
    """Compile state B into an explicitly annotated, non-production display object."""

    validate_owner_approval(candidate, approval, required_scope=use_scope)
    confidence_zh = {"HIGH": "高", "MEDIUM": "中", "LOW": "低"}[str(candidate["confidence"])]
    assumptions = "；".join(str(item) for item in candidate["assumptions"])
    basis = f"{candidate['formula_id']} {candidate['formula_version']}；{assumptions}"
    display = (
        f"{candidate['metric_name']}（推估）"
        f"{candidate['estimate_lower_bound']}–{candidate['estimate_upper_bound']} {candidate['unit']}"
        f"（點估 {candidate['point_estimate']}；非公司直接揭露；信心：{confidence_zh}；基礎/假設：{basis}）"
    )
    return {
        "schema_version": T2_DISPLAY_SCHEMA,
        "display_state": "ANNOTATED_RESEARCH_KPI",
        "candidate_id": candidate["candidate_id"],
        "candidate_hash": _candidate_hash(candidate),
        "approval_id": approval["approval_id"],
        "metric_id": candidate["metric_id"],
        "metric_name": candidate["metric_name"],
        "period": candidate["period"],
        "use_scope": use_scope,
        "display_label_zh": "推估值",
        "display_text_zh": display,
        "point_estimate": candidate["point_estimate"],
        "estimate_lower_bound": candidate["estimate_lower_bound"],
        "estimate_upper_bound": candidate["estimate_upper_bound"],
        "unit": candidate["unit"],
        "confidence": candidate["confidence"],
        "confidence_label_zh": confidence_zh,
        "basis_assumptions_summary_zh": basis,
        "not_directly_disclosed": True,
        "disclosure_zh": "非公司直接揭露",
        "data_tier": T2,
        "owner_approved_for_annotated_use": True,
        "formal_authority": False,
        "formal_scoring_eligible": False,
        "formal_publish_eligible": False,
        "research_only": True,
        "actionable": False,
    }


def reconcile_with_official(
    candidate: Mapping[str, Any],
    *,
    replacement_data_tier: str,
    replacement_value: str,
    replacement_source_id: str,
    replacement_source_hash: str,
    recorded_at: str,
    state: str = "OFFICIAL_REPLACEMENT_AVAILABLE",
) -> dict[str, Any]:
    """Preserve T2 lineage while recording a later canonical T0/T1 value."""

    _valid_timestamp(recorded_at, "recorded_at")
    if replacement_data_tier not in {T0, T1}:
        raise T2AnnotatedUseError("canonical replacement must be T0 or T1")
    if state not in {"OFFICIAL_REPLACEMENT_AVAILABLE", "RECONCILED"}:
        raise T2AnnotatedUseError("official reconciliation state is invalid")
    if not replacement_source_id.strip() or not HASH_RE.fullmatch(replacement_source_hash):
        raise T2AnnotatedUseError("replacement source ID and uppercase SHA-256 are required")
    replacement = _decimal_string(replacement_value, "replacement_value")
    candidate_hash = _candidate_hash(candidate)
    return {
        "schema_version": T2_RECONCILIATION_SCHEMA,
        "reconciliation_id": f"T2REC-{candidate_hash[:16]}-{replacement_source_hash[:12]}",
        "candidate_id": candidate["candidate_id"],
        "candidate_hash": candidate_hash,
        "metric_id": candidate["metric_id"],
        "period": candidate["period"],
        "original_point_estimate": candidate["point_estimate"],
        "original_estimate_lower_bound": candidate["estimate_lower_bound"],
        "original_estimate_upper_bound": candidate["estimate_upper_bound"],
        "unit": candidate["unit"],
        "replacement_data_tier": replacement_data_tier,
        "replacement_value": replacement,
        "replacement_source_id": replacement_source_id,
        "replacement_source_hash": replacement_source_hash,
        "reconciliation_state": state,
        "recorded_at": recorded_at,
        "estimate_lineage_retained": True,
        "t2_current_canonical": False,
        "canonical_display_preference": "T0_T1_REPLACEMENT",
        "formal_authority_created": False,
        "formal_scoring_eligible": False,
        "actionable": False,
    }


def reject_estimate(
    candidate: Mapping[str, Any], *, reason: str, recorded_at: str
) -> dict[str, Any]:
    _valid_timestamp(recorded_at, "recorded_at")
    if not reason.strip():
        raise T2AnnotatedUseError("estimate rejection reason is required")
    candidate_hash = _candidate_hash(candidate)
    return {
        "schema_version": T2_RECONCILIATION_SCHEMA,
        "reconciliation_id": f"T2REJ-{candidate_hash[:24]}",
        "candidate_id": candidate["candidate_id"],
        "candidate_hash": candidate_hash,
        "metric_id": candidate["metric_id"],
        "period": candidate["period"],
        "original_point_estimate": candidate["point_estimate"],
        "original_estimate_lower_bound": candidate["estimate_lower_bound"],
        "original_estimate_upper_bound": candidate["estimate_upper_bound"],
        "unit": candidate["unit"],
        "replacement_data_tier": None,
        "replacement_value": None,
        "replacement_source_id": None,
        "replacement_source_hash": None,
        "reconciliation_state": "ESTIMATE_REJECTED",
        "recorded_at": recorded_at,
        "estimate_lineage_retained": True,
        "t2_current_canonical": False,
        "canonical_display_preference": "NO_T2_DISPLAY",
        "rejection_reason": reason.strip(),
        "formal_authority_created": False,
        "formal_scoring_eligible": False,
        "actionable": False,
    }


def select_canonical_display(
    candidate: Mapping[str, Any],
    approval: Mapping[str, Any],
    *,
    use_scope: str,
    reconciliation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Prefer later T0/T1 data and retain, but do not display, superseded T2 lineage."""

    if reconciliation is not None:
        if reconciliation.get("candidate_hash") != _candidate_hash(candidate):
            raise T2AnnotatedUseError("reconciliation does not bind current candidate")
        state = reconciliation.get("reconciliation_state")
        if state in {"OFFICIAL_REPLACEMENT_AVAILABLE", "RECONCILED"}:
            return {
                "display_state": "CANONICAL_T0_T1_SUPERSEDES_T2",
                "metric_id": candidate["metric_id"],
                "period": candidate["period"],
                "value": reconciliation["replacement_value"],
                "unit": candidate["unit"],
                "data_tier": reconciliation["replacement_data_tier"],
                "source_id": reconciliation["replacement_source_id"],
                "source_hash": reconciliation["replacement_source_hash"],
                "t2_candidate_id": candidate["candidate_id"],
                "t2_lineage_retained": True,
                "t2_current_canonical": False,
                "formal_authority_created_by_t2_contract": False,
                "actionable": False,
            }
        if state == "ESTIMATE_REJECTED":
            return {
                "display_state": "T2_ESTIMATE_REJECTED",
                "metric_id": candidate["metric_id"],
                "period": candidate["period"],
                "t2_candidate_id": candidate["candidate_id"],
                "t2_lineage_retained": True,
                "t2_current_canonical": False,
                "actionable": False,
            }
    return compile_annotated_display(candidate, approval, use_scope=use_scope)


def assert_t2_excluded_from_formal_scoring(candidate: Mapping[str, Any]) -> str:
    if candidate.get("data_tier") != T2:
        raise T2AnnotatedUseError("formal-scoring exclusion guard expects T2")
    if candidate.get("formal_scoring_eligible") is not False or candidate.get("production_scoring_enabled") is not False:
        raise T2AnnotatedUseError("T2 cannot enter formal scoring")
    return "EXCLUDED_T2_RESEARCH_ONLY"


def assert_t2_excluded_from_formal_publish(candidate: Mapping[str, Any]) -> str:
    if candidate.get("data_tier") != T2 or candidate.get("formal_authority") is not False or candidate.get("formal_publish_eligible") is not False:
        raise T2AnnotatedUseError("T2 cannot enter formal publish authority")
    return "EXCLUDED_T2_RESEARCH_ONLY"


def current_kpi_t2_audit() -> dict[str, Any]:
    """Return the current evidence-backed eligibility audit without minting values."""

    return {
        "ROIC_T2_STATUS": "ELIGIBLE",
        "ROIC_T2_ELIGIBLE_METRIC": "PARTIAL_OPERATING_INVESTED_CAPITAL_ROIC_ESTIMATE",
        "ROIC_T2_REQUIRED_LABEL": "部分營運投入資本ROIC（推估）",
        "ROIC_PRECISE_T2_STATUS": "INSUFFICIENT_INPUTS",
        "ROIC_NOTE": "The governed partial-operating-IC model is reproducible; it cannot be relabelled as canonical precise ROIC.",
        "INDUSTRY_AI_T2_STATUS": "NOT_ELIGIBLE",
        "INDUSTRY_AI_NOTE": "No same-semantic governed numeric input supports AI revenue share.",
        "POSITIONING_T2_STATUS": "NOT_ELIGIBLE",
        "POSITIONING_NOTE": "Missing TWSE ingestion requires raw-source remediation, not estimation.",
        "MACRO_T2_STATUS": "NOT_ELIGIBLE",
        "MACRO_NOTE": "Direct observation paths remain preferred; proxy duplicates are forbidden.",
    }


def main() -> int:
    """Print policy/audit status only; no approval or production write is exposed by CLI."""

    print(json.dumps({
        "policy": "D-T2-ANNOTATED-USE=AUTHORIZED",
        "default_state": "RESEARCH_ONLY",
        "use_scope_status": USE_SCOPE_STATUS,
        "low_confidence_t2_main_kpi_eligibility": "UNDEFINED",
        "current_kpi_audit": current_kpi_t2_audit(),
        "formal_authority": False,
        "formal_scoring": False,
        "actionable": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
