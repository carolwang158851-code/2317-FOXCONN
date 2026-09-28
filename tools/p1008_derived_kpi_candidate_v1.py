"""Fail-closed validator for non-production P1008 derived KPI candidates.

This module validates an isolated candidate contract.  It has no formal-data
writer, no authority promotion operation, and no scoring integration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "P1008_DERIVED_KPI_CANDIDATE_V1"
T1 = "T1_EXACT_DERIVED"
T2 = "T2_ESTIMATED_DERIVED"
T3 = "T3_EXTERNAL_CROSSCHECK"
T4 = "T4_MODEL_SCENARIO"
T0 = "T0_DIRECT_OFFICIAL"
DATA_MISSING = "DATA_MISSING"

REQUIRED_FIELDS = (
    "schema_version", "candidate_id", "synthetic_fixture", "metric_id", "metric_name",
    "dimension", "period", "as_of_date", "value", "unit", "data_tier",
    "derivation_method", "formula_id", "formula_version", "formula_expression",
    "input_metric_ids", "input_values", "input_units", "input_periods",
    "input_source_ids", "input_source_tiers", "input_source_locators", "input_hashes",
    "input_semantic_names", "input_governed", "denominator_definition",
    "period_alignment_rule", "unit_conversion_rule", "rounding_rule", "assumptions",
    "assumption_count", "sensitivity_range", "derivation_trace", "recomputation",
    "semantic_name", "semantic_match_status", "proxy_metric_used",
    "proxy_relabelled_as_direct", "confidence", "validation_status", "candidate_status",
    "owner_review_required", "owner_authorization_reference", "actionable", "publication",
    "production_scoring_enabled",
)

INPUT_ARRAY_FIELDS = (
    "input_metric_ids", "input_values", "input_units", "input_periods",
    "input_source_ids", "input_source_tiers", "input_source_locators", "input_hashes",
    "input_semantic_names", "input_governed",
)

HASH_RE = re.compile(r"^[A-F0-9]{64}$")
ROUNDING_RE = re.compile(r"^DECIMAL_HALF_UP_([0-9]+)DP$")
FORBIDDEN_EMPTY_DENOMINATORS = {"", "N/A", "NA", "NONE", "NULL", "UNSPECIFIED", "UNKNOWN"}

PROTECTED_FORMAL_PATHS = (
    "data/2317_master_v9.csv",
    "data/2317_daily_price.csv",
    "data/2317_daily_market_activity.csv",
    "data/2317_cash_flow_authority.csv",
    "data/macro_snapshot.csv",
    "data/macro_event_observations.csv",
    "data/fx_trend_observations.csv",
    "data/CSV_AUTHORITY_MANIFEST.json",
)


class CandidateValidationError(ValueError):
    """Raised when a candidate violates the fail-closed contract."""


@dataclass(frozen=True)
class RemediationResult:
    status: str
    selected_tier: str | None
    candidate: dict[str, Any] | None
    trace: tuple[str, ...]


def _reject_json_constant(token: str) -> None:
    raise CandidateValidationError(f"non-finite JSON number rejected: {token}")


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle, parse_constant=_reject_json_constant)
    if not isinstance(value, dict):
        raise CandidateValidationError("candidate must be a JSON object")
    return value


def _decimal(value: Any, field: str, errors: list[str]) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        errors.append(f"{field} must be a decimal number")
        return None
    if not number.is_finite():
        errors.append(f"{field} must be finite")
        return None
    return number


def _safe_list(candidate: dict[str, Any], field: str, errors: list[str]) -> list[Any]:
    value = candidate.get(field)
    if not isinstance(value, list):
        errors.append(f"{field} must be an array")
        return []
    return value


def recompute(candidate: dict[str, Any]) -> Decimal:
    """Recompute a candidate using only the explicit safe arithmetic contract."""

    metric_ids = candidate["input_metric_ids"]
    values = candidate["input_values"]
    if len(metric_ids) != len(values):
        raise CandidateValidationError("input arrays are not aligned")
    by_id = {metric_id: Decimal(str(value)) for metric_id, value in zip(metric_ids, values)}
    spec = candidate["recomputation"]
    left_id = spec["left_input_metric_id"]
    right_id = spec["right_input_metric_id"]
    try:
        left = by_id[left_id]
        right = by_id[right_id]
    except KeyError as exc:
        raise CandidateValidationError(f"recomputation input is missing: {exc.args[0]}") from exc
    if not left.is_finite() or not right.is_finite():
        raise CandidateValidationError("recomputation inputs must be finite")
    operator = spec["operator"]
    if operator == "ADD":
        raw = left + right
    elif operator == "SUBTRACT":
        raw = left - right
    elif operator == "MULTIPLY":
        raw = left * right
    elif operator == "DIVIDE":
        if right == 0:
            raise CandidateValidationError("denominator must be non-zero")
        raw = left / right
    else:
        raise CandidateValidationError(f"unsupported recomputation operator: {operator}")
    multiplier = Decimal(str(spec["multiplier"]))
    if not multiplier.is_finite():
        raise CandidateValidationError("recomputation multiplier must be finite")
    match = ROUNDING_RE.fullmatch(str(candidate["rounding_rule"]))
    if not match:
        raise CandidateValidationError("rounding_rule must be DECIMAL_HALF_UP_<n>DP")
    places = int(match.group(1))
    quantum = Decimal("1").scaleb(-places)
    return (raw * multiplier).quantize(quantum, rounding=ROUND_HALF_UP)


def validate_candidate(candidate: dict[str, Any]) -> list[str]:
    """Return every deterministic validation failure; an empty list means valid."""

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in candidate:
            errors.append(f"missing required field: {field}")
    if errors:
        return errors

    if candidate["schema_version"] != SCHEMA_VERSION:
        errors.append("schema_version is not P1008_DERIVED_KPI_CANDIDATE_V1")
    for field in ("candidate_id", "metric_id", "metric_name", "period", "as_of_date",
                  "unit", "formula_id", "formula_version", "formula_expression",
                  "denominator_definition", "period_alignment_rule", "unit_conversion_rule",
                  "semantic_name"):
        if not isinstance(candidate[field], str) or not candidate[field].strip():
            errors.append(f"{field} must be a non-empty string")

    tier = candidate["data_tier"]
    if tier not in (T1, T2):
        errors.append("data_tier must be T1_EXACT_DERIVED or T2_ESTIMATED_DERIVED; T3/T4 cannot impersonate a derived candidate")

    arrays = {field: _safe_list(candidate, field, errors) for field in INPUT_ARRAY_FIELDS}
    lengths = {len(values) for values in arrays.values()}
    arrays_aligned = bool(lengths) and len(lengths) == 1 and next(iter(lengths)) > 0
    if not lengths or lengths == {0}:
        errors.append("at least one complete input lineage record is required")
    elif len(lengths) != 1:
        errors.append("all input lineage arrays must have equal length")

    for index, digest in enumerate(arrays["input_hashes"]):
        if not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
            errors.append(f"input_hashes[{index}] must be an uppercase SHA-256 digest")
    if arrays["input_governed"] and not all(value is True for value in arrays["input_governed"]):
        errors.append("all inputs must be governed")
    if arrays["input_source_tiers"]:
        allowed_source_tiers = {T0, T1} if tier == T1 else {T0, T1, T2}
        for index, source_tier in enumerate(arrays["input_source_tiers"]):
            if source_tier not in allowed_source_tiers:
                errors.append(f"input_source_tiers[{index}] is ineligible for {tier}")

    input_numbers = [
        _decimal(value, f"input_values[{index}]", errors)
        for index, value in enumerate(arrays["input_values"])
    ]
    output_value = _decimal(candidate["value"], "value", errors)

    if candidate["period_alignment_rule"] != "ALL_INPUT_PERIODS_EQUAL_CANDIDATE_PERIOD":
        errors.append("period_alignment_rule is not the exact supported rule")
    if any(period != candidate["period"] for period in arrays["input_periods"]):
        errors.append("input period mismatch")

    denominator = str(candidate["denominator_definition"]).strip()
    if denominator.upper() in FORBIDDEN_EMPTY_DENOMINATORS:
        errors.append("denominator_definition is missing or ambiguous")

    assumptions = candidate["assumptions"]
    if not isinstance(assumptions, list) or any(not isinstance(item, str) or not item.strip() for item in assumptions):
        errors.append("assumptions must be an array of non-empty declarations")
        assumptions = []
    if candidate["assumption_count"] != len(assumptions):
        errors.append("assumption_count does not match declared assumptions")
    if tier == T1:
        if candidate["derivation_method"] != "EXACT_DETERMINISTIC":
            errors.append("T1 cannot use an estimated derivation method")
        if assumptions:
            errors.append("T1 cannot contain estimation assumptions; classify as T2")
        if candidate["sensitivity_range"] is not None:
            errors.append("T1 must not carry an estimation sensitivity range")
    elif tier == T2:
        if candidate["derivation_method"] != "ESTIMATED_WITH_DECLARED_ASSUMPTIONS":
            errors.append("T2 must declare the estimated derivation method")
        if not assumptions:
            errors.append("T2 requires at least one explicit assumption")
        if candidate["sensitivity_range"] is None:
            errors.append("T2 requires a sensitivity range")
        elif not isinstance(candidate["sensitivity_range"], dict) or not {
            "low", "high", "unit", "method"
        }.issubset(candidate["sensitivity_range"]):
            errors.append("T2 sensitivity range must declare low, high, unit and method")
        if candidate["confidence"] == "HIGH":
            errors.append("T2 confidence must be lower than T1 exact confidence")

    if candidate["semantic_match_status"] != "EXACT_MATCH":
        errors.append("semantic mismatch")
    if candidate["proxy_metric_used"] is not False or candidate["proxy_relabelled_as_direct"] is not False:
        errors.append("proxy metric relabeling is forbidden")
    if candidate["validation_status"] != "VALIDATED_CANDIDATE":
        errors.append("validation_status must be VALIDATED_CANDIDATE")
    if candidate["candidate_status"] != "OWNER_REVIEW_REQUIRED":
        errors.append("candidate_status must remain OWNER_REVIEW_REQUIRED")
    if candidate["owner_review_required"] is not True:
        errors.append("owner_review_required must be true")
    if candidate["actionable"] is not False:
        errors.append("actionable must be false")
    if candidate["publication"] is not False:
        if not candidate["owner_authorization_reference"]:
            errors.append("publication=true requires explicit Owner authorization")
        errors.append("publication must remain false in this non-production contract")
    if candidate["production_scoring_enabled"] is not False:
        errors.append("production scoring must remain disabled")

    spec = candidate["recomputation"]
    if not isinstance(spec, dict):
        errors.append("recomputation must be an object")
        spec = {}
    required_spec = {"operator", "left_input_metric_id", "right_input_metric_id", "multiplier"}
    if not required_spec.issubset(spec):
        errors.append("recomputation contract is incomplete")
    else:
        left_id = spec["left_input_metric_id"]
        right_id = spec["right_input_metric_id"]
        if left_id not in arrays["input_metric_ids"] or right_id not in arrays["input_metric_ids"]:
            errors.append("recomputation inputs are absent from input_metric_ids")
        if left_id not in candidate["formula_expression"] or right_id not in candidate["formula_expression"]:
            errors.append("formula_expression does not bind both recomputation inputs")
        if spec["operator"] == "DIVIDE":
            if right_id not in denominator:
                errors.append("denominator_definition does not name the divisor")
            if arrays_aligned and left_id in arrays["input_metric_ids"] and right_id in arrays["input_metric_ids"]:
                left_unit = arrays["input_units"][arrays["input_metric_ids"].index(left_id)]
                right_unit = arrays["input_units"][arrays["input_metric_ids"].index(right_id)]
                if left_unit != right_unit or candidate["unit"] not in {"MULTIPLE", "PERCENT"}:
                    errors.append("unit mismatch for division")
        elif spec["operator"] in {"ADD", "SUBTRACT"}:
            if arrays_aligned and left_id in arrays["input_metric_ids"] and right_id in arrays["input_metric_ids"]:
                left_unit = arrays["input_units"][arrays["input_metric_ids"].index(left_id)]
                right_unit = arrays["input_units"][arrays["input_metric_ids"].index(right_id)]
                if not (left_unit == right_unit == candidate["unit"]):
                    errors.append("unit mismatch for additive arithmetic")

    if output_value is not None and arrays_aligned and all(value is not None for value in input_numbers) and required_spec.issubset(spec):
        try:
            calculated = recompute(candidate)
        except (CandidateValidationError, InvalidOperation, KeyError, ZeroDivisionError) as exc:
            errors.append(f"deterministic recomputation failed: {exc}")
        else:
            if calculated != output_value:
                errors.append(f"deterministic recomputation mismatch: expected {calculated}, stored {output_value}")

    return errors


def validate_or_raise(candidate: dict[str, Any]) -> dict[str, Any]:
    errors = validate_candidate(candidate)
    if errors:
        raise CandidateValidationError("; ".join(errors))
    return candidate


def evidence_can_be_numeric_candidate(
    *, source_semantic: str, target_semantic: str, evidence_kind: str
) -> bool:
    """Guard against qualitative/count/proxy evidence being turned into a numeric KPI."""

    if evidence_kind in {"QUALITATIVE", "NEWS_EVENT_COUNT", "T3_CROSSCHECK", "MODEL_SCENARIO"}:
        return False
    return source_semantic == target_semantic


def resolve_required_kpi(
    *,
    t0_value: Any | None,
    t1_candidate: dict[str, Any] | None,
    t2_candidate: dict[str, Any] | None,
    t3_evidence_available: bool,
) -> RemediationResult:
    """Apply the mandatory T0→T1→T2→T3→NULL decision order."""

    trace: list[str] = ["CHECK_T0_DIRECT_OFFICIAL"]
    if t0_value is not None:
        if isinstance(t0_value, float) and not math.isfinite(t0_value):
            raise CandidateValidationError("T0 value must be finite")
        return RemediationResult("DIRECT_VALUE_AVAILABLE", T0, None, tuple(trace))

    trace.append("CHECK_T1_EXACT_DERIVABILITY")
    if t1_candidate is not None and not validate_candidate(t1_candidate) and t1_candidate.get("data_tier") == T1:
        return RemediationResult("CANDIDATE_READY", T1, t1_candidate, tuple(trace))

    trace.append("CHECK_T2_ESTIMATED_DERIVABILITY")
    if t2_candidate is not None and not validate_candidate(t2_candidate) and t2_candidate.get("data_tier") == T2:
        return RemediationResult("RESEARCH_CANDIDATE_ONLY", T2, t2_candidate, tuple(trace))

    trace.append("CHECK_T3_RESEARCH_EVIDENCE")
    if t3_evidence_available:
        trace.append("T3_OBSERVATION_ONLY_NOT_NUMERIC_KPI")
    trace.append(DATA_MISSING)
    return RemediationResult(DATA_MISSING, None, None, tuple(trace))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def protected_hashes(root: str | Path) -> dict[str, str]:
    base = Path(root)
    return {path: sha256_file(base / path) for path in PROTECTED_FORMAL_PATHS}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, help="Path to a candidate JSON file")
    args = parser.parse_args()
    candidate = load_json(args.candidate)
    errors = validate_candidate(candidate)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("P1008_DERIVED_KPI_CANDIDATE_VALIDATION=PASS")
    print(f"candidate_id={candidate['candidate_id']}")
    print(f"data_tier={candidate['data_tier']}")
    print(f"recomputed_value={recompute(candidate)}")
    print("actionable=false")
    print("publication=false")
    print("production_scoring_enabled=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
