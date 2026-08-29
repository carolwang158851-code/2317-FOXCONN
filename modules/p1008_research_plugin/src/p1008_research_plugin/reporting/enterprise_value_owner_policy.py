"""Inactive Owner-policy candidate for enterprise-value interpretation.

This module calibrates auditable candidate thresholds.  It has no authority to
activate a policy, produce a report, publish, or generate trading instructions.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence


class OwnerPolicyCandidateError(ValueError):
    """The inactive Owner-policy candidate violates its contract."""


POLICY_ID = "ENTERPRISE_VALUE_OWNER_POLICY_CANDIDATE_V1"
POLICY_VERSION = "1.0.0-candidate"
REQUIRED_THRESHOLD_FIELDS = {
    "threshold_id", "dimension", "metric", "formula", "unit",
    "candidate_value_or_range", "economic_rationale",
    "historical_calibration_basis", "evidence_requirement",
    "persistence_requirement", "hard_blocker", "recovery_condition",
    "hysteresis_rule", "missing_input_behavior", "owner_approval_state",
    "version",
}
_CONTRACT_PATH = (
    Path(__file__).resolve().parents[5]
    / "contracts" / "p1008_report_production" / "v1.1"
    / "ENTERPRISE_VALUE_OWNER_POLICY_CANDIDATE_V1.json"
)


def _d(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise OwnerPolicyCandidateError("NUMERIC_INPUT_INVALID") from exc


def load_policy_candidate(path: Path | None = None) -> dict[str, Any]:
    target = path or _CONTRACT_PATH
    try:
        policy = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OwnerPolicyCandidateError("POLICY_CANDIDATE_UNREADABLE") from exc
    validate_policy_candidate(policy)
    return policy


def validate_policy_candidate(policy: Mapping[str, Any]) -> None:
    if policy.get("policy_id") != POLICY_ID or policy.get("policy_version") != POLICY_VERSION:
        raise OwnerPolicyCandidateError("POLICY_ID_OR_VERSION_INVALID")
    if policy.get("activation_state") != "NOT_ACTIVE":
        raise OwnerPolicyCandidateError("POLICY_CANDIDATE_MUST_NOT_BE_ACTIVE")
    if policy.get("owner_approval_required") is not True:
        raise OwnerPolicyCandidateError("OWNER_APPROVAL_MUST_BE_REQUIRED")
    if policy.get("actionable") is not False or policy.get("trading_execution") is not False:
        raise OwnerPolicyCandidateError("POLICY_CANDIDATE_MUST_NOT_BE_ACTIONABLE")
    if policy.get("publication") is not False:
        raise OwnerPolicyCandidateError("POLICY_CANDIDATE_MUST_NOT_PUBLISH")
    thresholds = policy.get("thresholds")
    if not isinstance(thresholds, list) or not thresholds:
        raise OwnerPolicyCandidateError("THRESHOLDS_REQUIRED")
    ids: set[str] = set()
    for threshold in thresholds:
        if set(threshold) != REQUIRED_THRESHOLD_FIELDS:
            raise OwnerPolicyCandidateError("THRESHOLD_FIELDS_INVALID")
        threshold_id = str(threshold["threshold_id"])
        if threshold_id in ids:
            raise OwnerPolicyCandidateError("THRESHOLD_ID_DUPLICATE")
        ids.add(threshold_id)
        if threshold["owner_approval_state"] != "PENDING":
            raise OwnerPolicyCandidateError("THRESHOLD_NOT_PENDING")
        if threshold["candidate_value_or_range"] in (None, "", []):
            raise OwnerPolicyCandidateError("UNEXPLAINED_THRESHOLD_VALUE")
        if not threshold["economic_rationale"] or not threshold["historical_calibration_basis"]:
            raise OwnerPolicyCandidateError("THRESHOLD_RATIONALE_REQUIRED")
        if not isinstance(threshold["hard_blocker"], bool):
            raise OwnerPolicyCandidateError("HARD_BLOCKER_CLASS_REQUIRED")
    decisions = policy.get("owner_decisions", {})
    if set(decisions) != ids or any(value != "PENDING" for value in decisions.values()):
        raise OwnerPolicyCandidateError("OWNER_DECISION_TABLE_INVALID")
    dependencies = policy.get("dependencies", {})
    for key in ("WACC_CURRENT_VALUE", "POST_EVENT_PRICE", "SAME_BASIS_NET_CASH_STRESS_DENOMINATOR"):
        if dependencies.get(key) != "UNAVAILABLE_GOVERNED":
            raise OwnerPolicyCandidateError("MISSING_DEPENDENCY_NOT_EXPLICIT")


def owner_decision_table(policy: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    candidate = dict(policy or load_policy_candidate())
    validate_policy_candidate(candidate)
    return [
        {
            "Dimension": item["dimension"],
            "Metric": item["metric"],
            "Candidate threshold": item["candidate_value_or_range"],
            "Why this threshold": item["economic_rationale"],
            "Historical evidence": item["historical_calibration_basis"],
            "Required evidence tier": item["evidence_requirement"],
            "Persistence": item["persistence_requirement"],
            "Hard blocker?": item["hard_blocker"],
            "Recovery condition": item["recovery_condition"],
            "Open dependency": item["missing_input_behavior"],
            "Owner decision": item["owner_approval_state"],
        }
        for item in candidate["thresholds"]
    ]


def evaluate_roic_spread(
    *, roic_pct: Any | None, wacc_pct: Any | None, evidence_class: str,
    partial_estimate: bool = False, anchored_sensitivity: bool = False,
) -> dict[str, Any]:
    if anchored_sensitivity:
        return {"state": "CANNOT_EVALUATE", "reason": "ANCHORED_SENSITIVITY_NOT_ACTUAL", "severe_downgrade_allowed": False}
    if roic_pct is None:
        return {"state": "CANNOT_EVALUATE", "reason": "ROIC_UNAVAILABLE", "severe_downgrade_allowed": False}
    if wacc_pct is None:
        return {"state": "PENDING_REQUIRED_INPUT", "reason": "WACC_CURRENT_VALUE_UNAVAILABLE_GOVERNED", "wacc_used": None, "severe_downgrade_allowed": False}
    spread = _d(roic_pct) - _d(wacc_pct)
    if spread >= Decimal("5"):
        state = "STRONG_VALUE_CREATION"
    elif spread >= Decimal("2"):
        state = "VALUE_CREATION"
    elif spread >= Decimal("0"):
        state = "NARROW_SPREAD"
    elif spread > Decimal("-2"):
        state = "WATCH"
    else:
        state = "VALUE_DESTRUCTION"
    severe_allowed = evidence_class in {"T0_DIRECT_OFFICIAL", "T1_EXACT_DERIVED"} and not partial_estimate
    if partial_estimate and state == "VALUE_DESTRUCTION":
        state = "WATCH"
    return {"state": state, "spread_pct_points": str(spread), "evidence_class": evidence_class, "severe_downgrade_allowed": severe_allowed}


def evaluate_fcf_conversion(periods: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not periods:
        return {"state": "CANNOT_EVALUATE", "reason": "FCF_HISTORY_UNAVAILABLE"}
    negative = [item for item in periods if item.get("fcf_negative") is True]
    corroborator_names = ("cfo_weak", "ccc_worsening", "working_capital_outpaces_scale", "roic_deteriorating", "capex_without_return")
    corroborators = {name for name in corroborator_names if any(item.get(name) is True for item in periods)}
    consecutive_negative = 0
    for item in reversed(periods):
        if item.get("fcf_negative") is True:
            consecutive_negative += 1
        else:
            break
    if consecutive_negative >= 3 and len(corroborators) >= 2 and "cfo_weak" in corroborators:
        state = "STRUCTURAL_DETERIORATION"
    elif consecutive_negative >= 2 and corroborators:
        state = "STRUCTURAL_RISK_NOT_RULED_OUT"
    elif negative:
        state = "CYCLICAL_OR_TIMING_PRESSURE"
    else:
        state = "SUPPORTED"
    return {
        "state": state,
        "negative_period_count": len(negative),
        "consecutive_negative_periods": consecutive_negative,
        "corroborators": sorted(corroborators),
        "single_negative_period_structural": False,
    }


def evaluate_working_capital_funding(
    *, incremental_funding_need: Any, available_liquidity: Any | None,
    net_cash: Any | None, cfo_capacity: Any | None,
) -> dict[str, Any]:
    need = _d(incremental_funding_need)
    denominators = {
        "AVAILABLE_LIQUIDITY": available_liquidity,
        "NET_CASH": net_cash,
        "CFO_CAPACITY": cfo_capacity,
    }
    if any(value is None for value in denominators.values()):
        return {"sensitivity_state": "AVAILABLE", "funding_hard_blocker": "PENDING_REQUIRED_INPUT", "ratios": {}, "missing": [key for key, value in denominators.items() if value is None]}
    ratios = {key: str(need / _d(value)) for key, value in denominators.items() if _d(value) > 0}
    if len(ratios) != 3:
        return {"sensitivity_state": "AVAILABLE", "funding_hard_blocker": "CANNOT_EVALUATE", "ratios": ratios, "missing": ["NON_POSITIVE_DENOMINATOR"]}
    return {"sensitivity_state": "AVAILABLE", "funding_hard_blocker": max(_d(value) for value in ratios.values()) >= Decimal("0.50"), "ratios": ratios, "missing": []}


def evaluate_balance_sheet(*, actual_state: str, stress_resilience_state: str) -> dict[str, str]:
    if actual_state not in {"STRONG", "ADEQUATE", "WATCH", "STRESSED"}:
        raise OwnerPolicyCandidateError("ACTUAL_BALANCE_SHEET_STATE_INVALID")
    if stress_resilience_state not in {"HIGH", "MODERATE", "LOW", "INCONCLUSIVE"}:
        raise OwnerPolicyCandidateError("STRESS_RESILIENCE_STATE_INVALID")
    return {"CURRENT_BALANCE_SHEET_STATE": actual_state, "STRESS_RESILIENCE_STATE": stress_resilience_state}


def per_share_compounding_spread(numerator_growth_pct: Any, share_growth_pct: Any) -> Decimal:
    numerator = _d(numerator_growth_pct) / Decimal("100")
    denominator = _d(share_growth_pct) / Decimal("100")
    if denominator <= Decimal("-1"):
        raise OwnerPolicyCandidateError("SHARE_GROWTH_DENOMINATOR_INVALID")
    return ((Decimal("1") + numerator) / (Decimal("1") + denominator) - Decimal("1")) * Decimal("100")


def evaluate_per_share_compounding(*, numerator_growth_pct: Any | None, share_growth_pct: Any | None, compatible_denominator: bool, consecutive_periods: int) -> dict[str, Any]:
    if numerator_growth_pct is None or share_growth_pct is None or not compatible_denominator:
        return {"state": "INSUFFICIENT_DATA", "spread_pct": None}
    spread = per_share_compounding_spread(numerator_growth_pct, share_growth_pct)
    if spread >= Decimal("3") and consecutive_periods >= 2:
        state = "COMPOUNDING"
    elif spread >= Decimal("-1"):
        state = "NEUTRAL"
    elif spread > Decimal("-5") or consecutive_periods < 2:
        state = "DILUTION_PRESSURE"
    else:
        state = "DETERIORATING"
    return {"state": state, "spread_pct": str(spread), "formula": "(1 + numerator growth) / (1 + denominator growth) - 1"}


def evaluate_dilution(*, share_growth_pct: Any, per_share_states: Sequence[str], consecutive_periods: int) -> dict[str, Any]:
    share_growth = _d(share_growth_pct)
    adverse = sum(state in {"DILUTION_PRESSURE", "DETERIORATING"} for state in per_share_states)
    if share_growth <= 0 or adverse == 0:
        state = "NO_DILUTION_FAILURE"
    elif adverse >= 2 and consecutive_periods >= 2:
        state = "PERSISTENT_DILUTION_RISK"
    else:
        state = "WATCH"
    return {"state": state, "share_growth_pct": str(share_growth), "adverse_compatible_numerators": adverse, "share_growth_alone_is_failure": False}


def evaluate_capital_light(factor_groups: Sequence[Mapping[str, Any]], *, consecutive_periods: int) -> dict[str, Any]:
    expected = {"RECEIVABLE_EFFICIENCY", "INVENTORY_EFFICIENCY", "SUPPLIER_FINANCING", "CASH_CONVERSION", "CAPITAL_INTENSITY"}
    by_group = {str(item.get("factor_group")): item for item in factor_groups}
    if set(by_group) != expected:
        return {"state": "INCONCLUSIVE", "reason": "FIVE_FACTOR_GROUPS_REQUIRED"}
    improving = sum(item.get("trend_signal") == "IMPROVING" for item in by_group.values())
    deteriorating = sum(item.get("trend_signal") == "DETERIORATING" for item in by_group.values())
    if improving >= 3 and deteriorating == 0 and consecutive_periods >= 2:
        state = "IMPROVING"
    elif deteriorating >= 3 and consecutive_periods >= 2:
        state = "DETERIORATING"
    else:
        state = "NEUTRAL"
    return {"state": state, "factor_group_count": 5, "improving_groups": improving, "deteriorating_groups": deteriorating, "raw_metric_vote_count": None}


def evaluate_valuation(
    *, valuation_context: str, multiple_percentiles: Mapping[str, Any],
    roic_support: bool, fcf_support: bool, per_share_support: bool,
) -> dict[str, Any]:
    if valuation_context != "POST_EVENT_PRICE":
        return {"state": "INCONCLUSIVE", "current_add_on_eligible": False, "reason": "CURRENT_POST_EVENT_PRICE_REQUIRED"}
    if len(multiple_percentiles) < 2:
        return {"state": "INCONCLUSIVE", "current_add_on_eligible": False, "reason": "MULTIPLE_TRIANGULATION_REQUIRED"}
    values = [_d(value) for value in multiple_percentiles.values()]
    fundamentals = sum((roic_support, fcf_support, per_share_support))
    low = sum(value <= 30 for value in values)
    high = sum(value >= 70 for value in values)
    extreme = sum(value >= 90 for value in values)
    if low >= 2 and fundamentals >= 2:
        state = "ATTRACTIVE"
    elif extreme >= 2 and fundamentals <= 1:
        state = "EXPENSIVE"
    elif high >= 2:
        state = "FULL"
    else:
        state = "FAIR"
    return {"state": state, "current_add_on_eligible": state == "ATTRACTIVE", "multiple_count": len(values), "fundamental_support_count": fundamentals}


def evaluate_add_on_gate(*, supports: Mapping[str, bool | None], hard_blockers: Sequence[bool], valuation_context: str) -> dict[str, Any]:
    required = {"ROIC", "FCF", "WORKING_CAPITAL", "CURRENT_BALANCE_SHEET", "STRESS_RESILIENCE", "PER_SHARE", "VALUATION"}
    if set(supports) != required:
        return {"analytical_state": "CANNOT_EVALUATE", "decision_authority": "NOT_ACTIVE", "trading_action": None}
    if valuation_context != "POST_EVENT_PRICE" or supports["VALUATION"] is None:
        state = "尚未通過"
    elif any(hard_blockers):
        state = "尚未通過"
    else:
        count = sum(value is True for value in supports.values())
        state = "通過" if count >= 6 else ("PARTIAL" if count >= 3 else "尚未通過")
    return {"analytical_state": state, "decision_authority": "NOT_ACTIVE", "partial_is_trading_instruction": False, "trading_action": None}


def evaluate_thesis_downgrade(*, adverse_actual_factors: int, t4_only_factors: int, consecutive_periods: int, hard_blocker_confirmed: bool) -> dict[str, Any]:
    if hard_blocker_confirmed and adverse_actual_factors >= 2 and consecutive_periods >= 2:
        state = "TRIGGERED"
    elif adverse_actual_factors >= 1 or t4_only_factors > 0:
        state = "WATCH"
    else:
        state = "尚未觸發"
    return {"state": state, "t4_alone_can_trigger": False, "decision_authority": "NOT_ACTIVE"}


def hysteresis_transition(*, current_state: str, proposed_state: str, consecutive_confirmations: int, entry_required: int, recovery_required: int) -> str:
    required = recovery_required if current_state == "TRIGGERED" and proposed_state != "TRIGGERED" else entry_required
    return proposed_state if consecutive_confirmations >= required else current_state


def candidate_runtime_state(policy: Mapping[str, Any] | None = None, approval_artifact: Mapping[str, Any] | None = None) -> dict[str, Any]:
    candidate = dict(policy or load_policy_candidate())
    validate_policy_candidate(candidate)
    if approval_artifact is not None:
        raise OwnerPolicyCandidateError("ACTIVATION_OUT_OF_SCOPE_REQUIRES_LATER_EXPLICIT_OWNER_STEP")
    return {
        "ANALYTICAL_STATE": "AVAILABLE",
        "OWNER_POLICY_STATE": "PENDING_POLICY_CALIBRATION",
        "DECISION_AUTHORITY": "NOT_ACTIVE",
        "OWNER_POLICY_CANDIDATE_READY": True,
        "OWNER_POLICY_ACTIVATED": False,
        "OWNER_APPROVAL_REQUIRED": True,
        "actionable": False,
    }
