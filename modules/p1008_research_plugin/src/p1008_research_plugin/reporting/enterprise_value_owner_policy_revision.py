"""Narrow eight-item revision overlay for the inactive Owner-policy candidate.

The original thirteen-item candidate remains immutable.  This module freezes
five approved-design dimensions and evaluates only the eight Owner-MODIFY
items.  It cannot activate policy, produce reports, publish, or trade.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

from .enterprise_value_owner_policy import load_policy_candidate


class OwnerPolicyRevisionError(ValueError):
    """The narrow revision or its frozen baseline is invalid."""


REVISION_ID = "ENTERPRISE_VALUE_OWNER_POLICY_REVISION_V1"
REVISION_VERSION = "1.0.0-review"
_CONTRACT_DIR = Path(__file__).resolve().parents[5] / "contracts" / "p1008_report_production" / "v1.1"
_REVISION_PATH = _CONTRACT_DIR / "ENTERPRISE_VALUE_OWNER_POLICY_REVISION_V1.json"
_BASE_PATH = _CONTRACT_DIR / "ENTERPRISE_VALUE_OWNER_POLICY_CANDIDATE_V1.json"


def _d(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise OwnerPolicyRevisionError("NUMERIC_INPUT_INVALID") from exc


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _semantic_hash(value: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha(raw)


def load_policy_revision(path: Path | None = None) -> dict[str, Any]:
    target = path or _REVISION_PATH
    try:
        revision = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OwnerPolicyRevisionError("REVISION_UNREADABLE") from exc
    validate_policy_revision(revision)
    return revision


def validate_policy_revision(revision: Mapping[str, Any]) -> None:
    if revision.get("revision_id") != REVISION_ID or revision.get("revision_version") != REVISION_VERSION:
        raise OwnerPolicyRevisionError("REVISION_ID_OR_VERSION_INVALID")
    if revision.get("policy_universe_regenerated") is not False:
        raise OwnerPolicyRevisionError("POLICY_UNIVERSE_MUST_NOT_BE_REGENERATED")
    if revision.get("activation_state") != "NOT_ACTIVE" or revision.get("owner_approval_artifact_created") is not False:
        raise OwnerPolicyRevisionError("REVISION_MUST_REMAIN_INACTIVE")
    if revision.get("ready_for_policy_activation") is not False or revision.get("ready_for_second_owner_review") is not True:
        raise OwnerPolicyRevisionError("REVISION_READINESS_STATE_INVALID")
    if revision.get("publication") is not False or revision.get("actionable") is not False:
        raise OwnerPolicyRevisionError("REVISION_MUST_NOT_PUBLISH_OR_ACT")
    if revision.get("formal_report_production_runs") != 0 or revision.get("external_calls") != {
        "network_requests": 0,
        "openai_api_calls": 0,
        "canva_calls": 0,
    }:
        raise OwnerPolicyRevisionError("REVISION_EXECUTION_BOUNDARY_INVALID")
    # The governance receipt pins canonical LF bytes.  Windows worktrees may
    # materialize the tracked JSON with CRLF, so normalize only line endings
    # before comparing the immutable content hash.
    base_bytes = (
        _BASE_PATH.read_text(encoding="utf-8")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .encode("utf-8")
    )
    base_ref = revision.get("original_candidate", {})
    if base_ref.get("policy_id") != "ENTERPRISE_VALUE_OWNER_POLICY_CANDIDATE_V1" or base_ref.get("sha256") != _sha(base_bytes):
        raise OwnerPolicyRevisionError("ORIGINAL_CANDIDATE_REFERENCE_MISMATCH")
    base = load_policy_candidate(_BASE_PATH)
    by_id = {item["threshold_id"]: item for item in base["thresholds"]}
    frozen = revision.get("frozen_approved_items", [])
    revised = revision.get("revised_items", [])
    if len(frozen) != 5 or len(revised) != 8:
        raise OwnerPolicyRevisionError("OWNER_REVIEW_COUNTS_INVALID")
    if any(item.get("owner_decision") != "APPROVED_DESIGN" for item in frozen):
        raise OwnerPolicyRevisionError("FROZEN_ITEM_DECISION_INVALID")
    if any(item.get("owner_decision") != "REVISION_PENDING_OWNER_REVIEW" for item in revised):
        raise OwnerPolicyRevisionError("REVISED_ITEM_DECISION_INVALID")
    frozen_ids = {item["threshold_id"] for item in frozen}
    revised_ids = {item["threshold_id"] for item in revised}
    if frozen_ids & revised_ids or frozen_ids | revised_ids != set(by_id):
        raise OwnerPolicyRevisionError("POLICY_SCOPE_PARTITION_INVALID")
    for item in frozen:
        if item["semantic_sha256"] != _semantic_hash(by_id[item["threshold_id"]]):
            raise OwnerPolicyRevisionError("APPROVED_POLICY_SEMANTIC_DRIFT")
    if revision.get("approved_design_count") != 5 or revision.get("revision_pending_owner_review_count") != 8 or revision.get("rejected_count") != 0:
        raise OwnerPolicyRevisionError("REVISION_SUMMARY_COUNTS_INVALID")


def owner_revision_table(revision: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    value = dict(revision or load_policy_revision())
    validate_policy_revision(value)
    return [
        {
            "Policy Dimension": item["dimension"],
            "V1 Candidate": item["v1_candidate"],
            "Owner Concern": item["owner_concern"],
            "V1 Revised Proposal": item["revised_proposal"],
            "Behavioral Difference": item["behavioral_difference"],
            "Remaining Input Dependency": item["remaining_input_dependency"],
            "Owner Decision": "PENDING_REVIEW",
        }
        for item in value["revised_items"]
    ]


def evaluate_revised_fcf(observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Seasonality-aware FCF policy; standalone negative counts are support only."""
    if not observations:
        return {"state": "CANNOT_EVALUATE", "reason": "CASH_FLOW_OBSERVATIONS_UNAVAILABLE"}
    comparable = [item for item in observations if item.get("comparison_basis") in {"SAME_SEASON", "TTM", "FY"}]
    weak = [item for item in comparable if item.get("cash_conversion_weak") is True]
    ttm_fy_repair_failure = any(
        item.get("comparison_basis") in {"TTM", "FY", "SAME_SEASON"}
        and item.get("cash_flow_repair_failed") is True
        for item in comparable
    )
    cfo_weak = any(item.get("cfo_conversion_deteriorating") is True for item in comparable)
    extra_names = ("working_capital_outpaces_scale", "ccc_deteriorating", "roic_deteriorating", "capex_without_return")
    extra = {name for name in extra_names if any(item.get(name) is True for item in comparable)}
    if ttm_fy_repair_failure and cfo_weak and extra and len(weak) >= 2:
        state = "STRUCTURAL_DETERIORATION"
    elif len(weak) >= 2 and (cfo_weak or extra):
        state = "STRUCTURAL_RISK_NOT_RULED_OUT"
    elif any(item.get("standalone_fcf_negative") is True for item in observations):
        state = "CYCLICAL_OR_TIMING_PRESSURE"
    else:
        state = "SUPPORTED"
    return {
        "state": state,
        "comparable_observation_count": len(comparable),
        "weak_comparable_observation_count": len(weak),
        "same_season_bases": sorted({str(item.get("period_basis")) for item in comparable if item.get("comparison_basis") == "SAME_SEASON"}),
        "standalone_negative_count_is_primary_rule": False,
        "corroborators": sorted(extra | ({"CFO_CONVERSION"} if cfo_weak else set())),
    }


def evaluate_fcf_recovery(*, prior_state: str, ttm_or_fy_repaired: bool, cfo_conversion_improved: bool, continuing_structural_factors: int, confirming_observations: int) -> str:
    if prior_state not in {"STRUCTURAL_RISK_NOT_RULED_OUT", "STRUCTURAL_DETERIORATION"}:
        return prior_state
    if ttm_or_fy_repaired and cfo_conversion_improved and continuing_structural_factors == 0 and confirming_observations >= 2:
        return "CYCLICAL_OR_TIMING_PRESSURE"
    return prior_state


def select_funding_denominator(
    *, immediately_available_liquidity: Any | None,
    net_cash: Any | None,
    normalized_cfo_capacity: Any | None,
) -> dict[str, Any]:
    candidates = (
        ("PRIMARY_IMMEDIATELY_AVAILABLE_LIQUIDITY", immediately_available_liquidity),
        ("SECONDARY_NET_CASH", net_cash),
        ("SUPPORTING_NORMALIZED_CFO_CAPACITY", normalized_cfo_capacity),
    )
    for name, value in candidates:
        if value is None:
            continue
        numeric = _d(value)
        if numeric > 0:
            return {"denominator": name, "value": str(numeric), "status": "AVAILABLE"}
        if name == "SUPPORTING_NORMALIZED_CFO_CAPACITY":
            return {"denominator": name, "value": None, "status": "CFO_CAPACITY_RATIO=CANNOT_EVALUATE"}
    return {"denominator": None, "value": None, "status": "PENDING_REQUIRED_INPUT"}


def evaluate_revised_funding(*, incremental_funding_requirement: Any, immediately_available_liquidity: Any | None, net_cash: Any | None, normalized_cfo_capacity: Any | None, t4_only: bool = False) -> dict[str, Any]:
    denominator = select_funding_denominator(
        immediately_available_liquidity=immediately_available_liquidity,
        net_cash=net_cash,
        normalized_cfo_capacity=normalized_cfo_capacity,
    )
    if denominator["status"] != "AVAILABLE":
        return {**denominator, "ratio": None, "research_band": None, "hard_blocker": False}
    ratio = _d(incremental_funding_requirement) / _d(denominator["value"])
    research_band = "RESEARCH_50_PERCENT" if ratio >= Decimal("0.50") else ("RESEARCH_25_PERCENT" if ratio >= Decimal("0.25") else "BELOW_RESEARCH_25_PERCENT")
    return {
        **denominator,
        "ratio": str(ratio),
        "research_band": research_band,
        "WC_25_PERCENT_APPROVED": False,
        "WC_50_PERCENT_HARD_BLOCKER_APPROVED": False,
        "hard_blocker": False,
        "t4_can_activate_hard_blocker": False,
        "reason": "RESEARCH_CANDIDATE_ONLY" if t4_only or research_band != "BELOW_RESEARCH_25_PERCENT" else "NO_RESEARCH_BREACH",
    }


def evaluate_revised_per_share(metrics: Sequence[Mapping[str, Any]], *, relevant_reporting_periods: int) -> dict[str, Any]:
    allowed = {
        "EPS": {"QUARTERLY_YOY", "TTM", "FY"},
        "BVPS": {"YOY", "MULTI_QUARTER", "FY"},
        "FCF_PER_SHARE": {"TTM", "FY", "COMPARABLE_CUMULATIVE"},
    }
    compatible = [item for item in metrics if item.get("metric") in allowed and item.get("period_basis") in allowed[item["metric"]] and item.get("compatible") is True]
    positive = [item for item in compatible if _d(item.get("compounding_spread_pct")) > 0]
    adverse = [item for item in compatible if _d(item.get("compounding_spread_pct")) < 0]
    standalone_fcf = [item for item in metrics if item.get("metric") == "FCF_PER_SHARE" and item.get("period_basis") == "STANDALONE_QUARTER"]
    if len(compatible) < 2:
        state = "INSUFFICIENT_DATA"
    elif len(positive) >= 2 and relevant_reporting_periods >= 2:
        state = "COMPOUNDING"
    elif len(adverse) >= 2 and relevant_reporting_periods >= 2:
        state = "DETERIORATING"
    elif adverse:
        state = "DILUTION_PRESSURE"
    else:
        state = "NEUTRAL"
    return {
        "state": state,
        "compatible_metric_count": len(compatible),
        "positive_metric_count": len(positive),
        "standalone_quarterly_fcf_share_role": "SUPPORTING_SIGNAL_ONLY" if standalone_fcf else "NOT_PRESENT",
        "standalone_quarterly_fcf_share_can_set_deteriorating": False,
    }


def evaluate_revised_capital_light(factor_groups: Sequence[Mapping[str, Any]], *, relevant_reporting_periods: int) -> dict[str, Any]:
    expected = {"RECEIVABLE_EFFICIENCY", "INVENTORY_EFFICIENCY", "SUPPLIER_FINANCING", "CASH_CONVERSION", "CAPITAL_INTENSITY"}
    by_group = {str(item.get("factor_group")): item for item in factor_groups if item.get("factor_group") in expected}
    evaluable = [item for item in by_group.values() if item.get("data_completeness") == "EVALUABLE"]
    improving = sum(item.get("trend_signal") == "IMPROVING" for item in evaluable)
    deteriorating = sum(item.get("trend_signal") == "DETERIORATING" for item in evaluable)
    if len(evaluable) < 4:
        state, confidence = "INCONCLUSIVE", "PARTIAL"
    elif improving >= 3 and relevant_reporting_periods >= 2:
        state, confidence = "IMPROVING", "FULL"
    elif deteriorating >= 3 and relevant_reporting_periods >= 2:
        state, confidence = "DETERIORATING", "FULL"
    else:
        state, confidence = "NEUTRAL", "PARTIAL"
    return {
        "state": state,
        "confidence": confidence,
        "EVALUABLE_FACTOR_GROUPS": len(evaluable),
        "aligned_improving_groups": improving,
        "aligned_deteriorating_groups": deteriorating,
        "consignment_causal_claim_allowed": False,
    }


def evaluate_revised_valuation(*, valuation_context: str, multiple_percentiles: Mapping[str, Any], roic_support: bool, roe_support: bool, fcf_support: bool, per_share_support: bool) -> dict[str, Any]:
    descriptive_bands = {key: str(value) for key, value in multiple_percentiles.items()}
    if valuation_context not in {"POST_EVENT_PRICE", "REPORT_CUTOFF_PRICE"}:
        return {
            "CURRENT_VALUATION_DECISION_STATE": "CANNOT_EVALUATE",
            "historical_position_bands": descriptive_bands,
            "HISTORICAL_PERCENTILE_IS_POLICY_THRESHOLD": False,
            "MARGIN_OF_SAFETY_POLICY_STATE": "PENDING_OWNER_NUMERIC_CALIBRATION",
        }
    if len(multiple_percentiles) < 2:
        state = "CANNOT_EVALUATE"
    else:
        support_count = sum((roic_support, roe_support, fcf_support, per_share_support))
        state = "COMPOSITE_SUPPORT" if support_count >= 3 else "COMPOSITE_CAUTION"
    return {
        "CURRENT_VALUATION_DECISION_STATE": state,
        "historical_position_bands": descriptive_bands,
        "HISTORICAL_PERCENTILE_IS_POLICY_THRESHOLD": False,
        "MARGIN_OF_SAFETY_POLICY_STATE": "PENDING_OWNER_NUMERIC_CALIBRATION",
    }


def evaluate_revised_core_holding(
    *, confirmed_thesis_invalidating_event: bool, event_evidence_quality: str,
    event_material: bool, adverse_actual_dimensions: int,
    persistent_observations: int, t2_only: bool = False,
) -> dict[str, Any]:
    high_quality = event_evidence_quality in {"T0_DIRECT_OFFICIAL", "T1_EXACT_DERIVED"}
    if confirmed_thesis_invalidating_event and high_quality and event_material:
        state, path = "REVIEW", "PATH_A_THESIS_INVALIDATING_EVENT"
    elif adverse_actual_dimensions >= 2 and persistent_observations >= 2 and not t2_only:
        state, path = "降級", "PATH_B_FUNDAMENTAL_DETERIORATION"
    elif adverse_actual_dimensions >= 1 or t2_only:
        state, path = "REVIEW", "PATH_B_FUNDAMENTAL_DETERIORATION"
    else:
        state, path = "維持", "NO_ADVERSE_PATH"
    return {"state": state, "path": path, "t2_alone_can_downgrade": False, "decision_authority": "NOT_ACTIVE"}


def evaluate_revised_add_on(
    *, thesis_downgrade_state: str, current_balance_sheet_state: str,
    valuation_context: str, owner_hard_blocker_active: bool,
    core_support: Mapping[str, str], secondary_confidence: Mapping[str, str],
) -> dict[str, Any]:
    mandatory = {
        "THESIS_NOT_TRIGGERED": thesis_downgrade_state != "TRIGGERED",
        "BALANCE_SHEET_NOT_STRESSED": current_balance_sheet_state != "STRESSED",
        "CURRENT_VALUATION_AVAILABLE": valuation_context in {"POST_EVENT_PRICE", "REPORT_CUTOFF_PRICE"},
        "NO_OWNER_HARD_BLOCKER": not owner_hard_blocker_active,
    }
    required_core = {"ROIC", "FCF", "WORKING_CAPITAL", "PER_SHARE"}
    if set(core_support) != required_core:
        state = "CANNOT_EVALUATE"
    elif not all(mandatory.values()):
        state = "尚未通過"
    elif any(value in {"VALUE_DESTRUCTION", "STRUCTURAL_DETERIORATION", "HARD_FUNDING_STRESS", "DETERIORATING"} for value in core_support.values()):
        state = "尚未通過"
    elif all(value in {"SUPPORTED", "VALUE_CREATION", "COMPOUNDING", "MANAGEABLE"} for value in core_support.values()):
        state = "通過"
    else:
        state = "PARTIAL"
    return {
        "state": state,
        "mandatory_gates": mandatory,
        "core_support": dict(core_support),
        "secondary_confidence": dict(secondary_confidence),
        "secondary_can_override_failed_mandatory_gate": False,
        "equal_weight_6_of_7_rule": False,
        "partial_is_trading_instruction": False,
        "trading_action": None,
        "decision_authority": "NOT_ACTIVE",
    }


def evaluate_revised_downgrade(
    *, adverse_actual_items: int, adverse_t2_items: int,
    independent_corroborators: int, t4_scenario_flags: int,
    persistent_observations: int, confirmed_thesis_invalidating_event: bool,
    high_quality_event_evidence: bool,
) -> dict[str, Any]:
    path_a = confirmed_thesis_invalidating_event and high_quality_event_evidence
    path_b = adverse_actual_items >= 2 and independent_corroborators >= 1 and persistent_observations >= 2
    if path_a or path_b:
        state = "TRIGGERED"
    elif adverse_actual_items >= 1 or (adverse_t2_items >= 1 and independent_corroborators >= 1):
        state = "WATCH"
    else:
        state = "尚未觸發"
    return {
        "state": state,
        "SCENARIO_RISK_FLAG": t4_scenario_flags > 0,
        "T4_ONLY_CAN_TRIGGER_WATCH": False,
        "T4_ONLY_CAN_TRIGGER_DOWNGRADE": False,
        "path": "PATH_A" if path_a else ("PATH_B" if path_b else "NONE"),
        "decision_authority": "NOT_ACTIVE",
    }


def evaluate_triggered_recovery(*, prior_state: str, confirming_observations: int, thesis_invalidating_event_resolved: bool, adverse_actual_items: int) -> str:
    if prior_state != "TRIGGERED":
        return prior_state
    if confirming_observations >= 2 and thesis_invalidating_event_resolved and adverse_actual_items == 0:
        return "WATCH"
    return "TRIGGERED"


def revision_runtime_state(revision: Mapping[str, Any] | None = None) -> dict[str, Any]:
    value = dict(revision or load_policy_revision())
    validate_policy_revision(value)
    return {
        "APPROVED_DESIGN_COUNT": 5,
        "REVISION_PENDING_OWNER_REVIEW_COUNT": 8,
        "REJECTED_COUNT": 0,
        "OWNER_POLICY_ACTIVATED": False,
        "OWNER_APPROVAL_ARTIFACT_CREATED": False,
        "READY_FOR_POLICY_ACTIVATION": False,
        "READY_FOR_SECOND_OWNER_REVIEW": True,
        "actionable": False,
    }
