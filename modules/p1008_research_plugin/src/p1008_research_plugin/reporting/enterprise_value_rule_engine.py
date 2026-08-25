"""Rule-assisted enterprise-value and SMART decisions.

The engine is deterministic and evidence-tier aware.  It has no trading or
publication authority and intentionally does not invent commercial thresholds.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence


class DecisionRuleError(RuntimeError):
    """A decision or SMART state violates its governed contract."""


RULE_ENGINE_ID = "ENTERPRISE_VALUE_RULE_ENGINE_V1"
SMART_ALLOWED = {"SUPPORTED", "ON_TRACK", "PARTIAL", "WATCH", "NOT_PROVEN", "TRIGGERED", "UNAVAILABLE"}


def _rule(rule_id: str, dimension: str, state: str, evidence: Sequence[str], evidence_tiers: Sequence[str], rationale: str, estimated: bool = False) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "dimension": dimension,
        "calculated_state": state,
        "evidence_state": "UNAVAILABLE" if state == "UNAVAILABLE" else ("SUPPORTED" if state == "SUPPORTED" else "PARTIAL"),
        "risk_state": "TRIGGERED" if state in {"DETERIORATING", "FAIL", "TRIGGERED"} else ("WATCH" if state == "WATCH" else "NORMAL"),
        "policy_state": "PENDING_POLICY_CALIBRATION",
        "rule_evidence": list(evidence),
        "evidence_tiers": list(evidence_tiers),
        "estimated_data_dependence": estimated,
        "threshold_policy_id": None,
        "threshold_status": "NOT_OWNER_APPROVED",
        "rationale": rationale,
        "actionable": False,
    }


def evaluate_enterprise_value_rules(
    *, forward: Mapping[str, Any], fcf_classification: str,
    operating_profit_supported: bool, balance_sheet_status: str,
    valuation_support: str, evidence_ids: Sequence[str],
) -> dict[str, Any]:
    roic = forward["roic_sensitivity"]
    cap_light = forward["capital_light_proxy"]
    dilution = forward["dilution_sensitivity"]
    stress = {item["scenario"]: item["result"] for item in forward["working_capital_stress"]["scenarios"]}
    rules = []
    rules.append(_rule(
        "EVR-OPERATING-PROFIT-V1", "OPERATING_PROFIT_STATE",
        "SUPPORTED" if operating_profit_supported else "WATCH", evidence_ids, ["T0_DIRECT_OFFICIAL"],
        "營業利益增速與營益率由正式季度證據支持。" if operating_profit_supported else "營業利益證據不足或轉弱。",
    ))
    fcf_state = {
        "CYCLICAL_OR_TIMING_PRESSURE": "PARTIAL",
        "STRUCTURAL_RISK_NOT_RULED_OUT": "WATCH",
        "STRUCTURAL_DETERIORATION": "DETERIORATING",
    }.get(fcf_classification, "UNAVAILABLE")
    rules.append(_rule(
        "EVR-FCF-CONVERSION-V1", "FCF_CONVERSION_STATE", fcf_state, evidence_ids,
        ["T0_DIRECT_OFFICIAL", "T1_EXACT_DERIVED"],
        "負FCF與營運資金／Capex證據共同判讀；單一負值不會自動觸發降級。",
    ))
    rules.append(_rule(
        "EVR-ROIC-V1", "ROIC_STATE", "PARTIAL" if roic["scenarios"] else "UNAVAILABLE", evidence_ids,
        ["T0_DIRECT_OFFICIAL", "T1_EXACT_DERIVED", "T4_MODEL_SCENARIO"],
        "Q2同口徑實際ROIC仍缺，但具透明投入資本情境的推估敏感度可支持部分判讀。",
        estimated=True,
    ))
    capital_state = {"IMPROVING": "SUPPORTED", "NEUTRAL": "PARTIAL", "DETERIORATING": "WATCH", "INCONCLUSIVE": "PARTIAL"}[cap_light["signal"]]
    rules.append(_rule(
        "EVR-CAPITAL-LIGHT-V1", "CAPITAL_LIGHT_STATE", capital_state, evidence_ids,
        ["T0_DIRECT_OFFICIAL", "T1_EXACT_DERIVED"],
        "多項資本占用指標共同判讀；不以CCC單項或未揭露的Consignment比例建立因果。",
    ))
    rules.append(_rule(
        "EVR-PER-SHARE-V1", "PER_SHARE_VALUE_STATE", "PARTIAL", evidence_ids,
        ["T0_DIRECT_OFFICIAL", "T2_ESTIMATED_DERIVED", "T4_MODEL_SCENARIO"],
        "EPS有正式證據，FCF／股使用相容加權平均股數估算；Q2期末股數不足使BVPS敏感度仍為情境。",
        estimated=True,
    ))
    severe_funding = float(stress["RESEARCH_STRESS_B"]["funding_need_indication"])
    balance_rule_state = "SUPPORTED" if balance_sheet_status == "STABLE" else "PARTIAL"
    rules.append(_rule(
        "EVR-CURRENT-BALANCE-SHEET-V1", "CURRENT_BALANCE_SHEET_STATE", balance_rule_state, evidence_ids,
        ["T0_DIRECT_OFFICIAL", "T1_EXACT_DERIVED"],
        "現況資產負債表僅依實際淨現金與正式現金流證據判讀，不受假設壓力情境降級。",
    ))
    stress_state = "LOW_RESILIENCE" if severe_funding > 0 else "MODERATE_RESILIENCE"
    rules.append(_rule(
        "EVR-STRESS-RESILIENCE-V1", "STRESS_RESILIENCE_STATE", stress_state, evidence_ids,
        ["T4_MODEL_SCENARIO"],
        "研究敏感度B顯示額外資金需求；這是情境韌性，不是現況資產負債表狀態。",
        estimated=True,
    ))
    valuation_state = "PARTIAL" if valuation_support in {"PARTIAL", "DESCRIPTIVE_ONLY"} else valuation_support
    if valuation_state not in {"SUPPORTED", "PARTIAL", "NO", "UNAVAILABLE"}:
        valuation_state = "UNAVAILABLE"
    rules.append(_rule(
        "EVR-VALUATION-V1", "VALUATION_STATE", valuation_state, evidence_ids,
        ["T0_DIRECT_OFFICIAL", "T1_EXACT_DERIVED"],
        "估值須同時連結ROIC、FCF與每股價值；目前缺Owner核准安全邊際門檻，僅作描述與部分支持。",
    ))
    decisions = decide_from_rules(rules)
    return {
        "rule_engine_id": RULE_ENGINE_ID,
        "state_semantics": {
            "EVIDENCE_STATE": ["SUPPORTED", "PARTIAL", "UNAVAILABLE"],
            "RISK_STATE": ["NORMAL", "WATCH", "TRIGGERED"],
            "POLICY_STATE": ["PENDING_POLICY_CALIBRATION", "OWNER_APPROVED", "NOT_APPLICABLE"],
        },
        "rules": rules,
        "decisions": decisions,
        "aggregate_numeric_score": None,
        "commercial_threshold_policy": "NOT_OWNER_APPROVED",
        "publication": False,
        "actionable": False,
    }


def decide_from_rules(rules: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    states = {str(item["dimension"]): str(item["calculated_state"]) for item in rules}
    hard_deterioration = states.get("FCF_CONVERSION_STATE") == "DETERIORATING" and states.get("ROIC_STATE") in {"DETERIORATING", "WATCH"}
    operating_failed = states.get("OPERATING_PROFIT_STATE") in {"DETERIORATING", "FAIL"}
    if hard_deterioration and operating_failed:
        core, downgrade = "降級", "TRIGGERED"
    elif hard_deterioration or operating_failed or states.get("CURRENT_BALANCE_SHEET_STATE") == "STRESSED":
        core, downgrade = "REVIEW", "WATCH"
    else:
        core = "維持"
        downgrade = "WATCH" if any(states.get(key) in {"WATCH", "DETERIORATING"} for key in ("FCF_CONVERSION_STATE", "CURRENT_BALANCE_SHEET_STATE")) else "尚未觸發"
    hard_blocker = downgrade == "TRIGGERED" or states.get("CURRENT_BALANCE_SHEET_STATE") == "STRESSED"
    full_support = all(states.get(key) == "SUPPORTED" for key in (
        "ROIC_STATE", "FCF_CONVERSION_STATE", "CAPITAL_LIGHT_STATE", "PER_SHARE_VALUE_STATE", "CURRENT_BALANCE_SHEET_STATE", "VALUATION_STATE",
    ))
    if hard_blocker:
        add_on = "尚未通過"
    elif full_support:
        add_on = "通過"
    else:
        add_on = "PARTIAL"
    return {
        "CORE_HOLDING_THESIS": core,
        "ADD_ON_CAPITAL_GATE": add_on,
        "THESIS_DOWNGRADE_GATE": downgrade,
    }


def structural_deterioration_scenario(*, negative_fcf: bool, roic_falling: bool, ccc_worsening: bool, cfo_conversion_weak: bool, operating_profit_weak: bool = True) -> dict[str, Any]:
    """Synthetic deterministic decision helper used to prove multi-factor gates."""
    rules = [
        _rule("SYN-OP", "OPERATING_PROFIT_STATE", "FAIL" if operating_profit_weak else "SUPPORTED", [], ["T0_DIRECT_OFFICIAL"], "synthetic"),
        _rule("SYN-FCF", "FCF_CONVERSION_STATE", "DETERIORATING" if negative_fcf and ccc_worsening and cfo_conversion_weak else ("WATCH" if negative_fcf else "SUPPORTED"), [], ["T0_DIRECT_OFFICIAL"], "synthetic"),
        _rule("SYN-ROIC", "ROIC_STATE", "DETERIORATING" if roic_falling else "SUPPORTED", [], ["T0_DIRECT_OFFICIAL"], "synthetic"),
        _rule("SYN-CL", "CAPITAL_LIGHT_STATE", "WATCH" if ccc_worsening else "SUPPORTED", [], ["T1_EXACT_DERIVED"], "synthetic"),
        _rule("SYN-PS", "PER_SHARE_VALUE_STATE", "PARTIAL", [], ["T1_EXACT_DERIVED"], "synthetic"),
        _rule("SYN-BS", "CURRENT_BALANCE_SHEET_STATE", "PARTIAL", [], ["T0_DIRECT_OFFICIAL"], "synthetic"),
        _rule("SYN-STRESS", "STRESS_RESILIENCE_STATE", "LOW_RESILIENCE", [], ["T4_MODEL_SCENARIO"], "synthetic"),
        _rule("SYN-VAL", "VALUATION_STATE", "PARTIAL", [], ["T1_EXACT_DERIVED"], "synthetic"),
    ]
    return decide_from_rules(rules)


def build_decision_state(previous: Mapping[str, Any] | None, rule_result: Mapping[str, Any], evidence: Sequence[str]) -> dict[str, Any]:
    previous_decisions = (previous or {}).get("decision", {})
    items = []
    for dimension, state in rule_result["decisions"].items():
        prior = previous_decisions.get(dimension, "INITIALIZED_BASELINE")
        supporting_rules = [item for item in rule_result["rules"] if item["dimension"] in {
            "OPERATING_PROFIT_STATE", "FCF_CONVERSION_STATE", "ROIC_STATE", "CAPITAL_LIGHT_STATE",
            "PER_SHARE_VALUE_STATE", "CURRENT_BALANCE_SHEET_STATE", "STRESS_RESILIENCE_STATE", "VALUATION_STATE",
        }]
        items.append({
            "dimension": dimension,
            "AUTOMATED_STATE": state,
            "AUTOMATED_ANALYTICAL_STATE": state,
            "PROVISIONAL_ANALYTICAL_STATE": state,
            "OWNER_POLICY_STATE": "PENDING_POLICY_CALIBRATION",
            "POLICY_CALIBRATION_REQUIRED": True,
            "RATIONALE": "Deterministic analytical result; no Owner-approved commercial threshold is applied.",
            "FINAL_STATE": "PENDING_OWNER_POLICY_CALIBRATION",
            "OVERRIDE": False,
            "OVERRIDE_REASON": None,
            "PREVIOUS_STATE": prior,
            "CURRENT_STATE": state,
            "CHANGE": "UNCHANGED" if prior == state else f"{prior}→{state}",
            "RULE_EVIDENCE": list(evidence),
            "ESTIMATED_DATA_DEPENDENCE": any(item["estimated_data_dependence"] for item in supporting_rules),
            "NEXT_GATE": "下一次正式季報：現金回收、同口徑ROIC、每股價值與估值安全邊際",
        })
    return {"dimension_count": 3, "items": items, "aggregate_numeric_score": None}


def apply_smart_override(item: Mapping[str, Any], final_state: str, reason: str | None) -> dict[str, Any]:
    if final_state not in SMART_ALLOWED:
        raise DecisionRuleError("SMART_STATE_INVALID")
    if not reason or not reason.strip():
        raise DecisionRuleError("SMART_OVERRIDE_REASON_REQUIRED")
    result = deepcopy(dict(item))
    result.update({"final_state": final_state, "current_state": final_state, "override": True, "override_reason": reason.strip()})
    result["changed"] = result.get("previous_state") != final_state
    return result


def build_smart_state(previous: Mapping[str, Any] | None, rule_result: Mapping[str, Any], evidence: Sequence[str]) -> dict[str, Any]:
    prior_items = {item["id"]: item for item in (previous or {}).get("smart", {}).get("items", [])}
    rules = {item["dimension"]: item for item in rule_result["rules"]}
    specs = (
        ("Operating Margin", "OPERATING_PROFIT_STATE"),
        ("ROE", "OPERATING_PROFIT_STATE"),
        ("EPS", "OPERATING_PROFIT_STATE", "METRIC_AVAILABILITY"),
        ("ASIC/Consignment", "CAPITAL_LIGHT_STATE"),
        ("CFO/FCF", "FCF_CONVERSION_STATE"),
        ("ROIC", "ROIC_STATE"),
        ("P/S rerating", "VALUATION_STATE"),
        ("Apple/NVIDIA long-term risk", "STRESS_RESILIENCE_STATE"),
        ("3+3+3 capital allocation", "ROIC_STATE"),
        ("PER_SHARE_VALUE_COMPOUNDING", "PER_SHARE_VALUE_STATE", "THESIS"),
    )
    state_map = {"SUPPORTED": "SUPPORTED", "PARTIAL": "PARTIAL", "WATCH": "WATCH", "DETERIORATING": "WATCH", "NO": "NOT_PROVEN", "UNAVAILABLE": "UNAVAILABLE"}
    items = []
    normalized_specs = [item if len(item) == 3 else (item[0], item[1], "RISK_OR_THESIS") for item in specs]
    for index, (metric, dimension, evaluation_type) in enumerate(normalized_specs, 1):
        rule = rules[dimension]
        automated = state_map.get(rule["calculated_state"], "NOT_PROVEN")
        item_id = f"SMART-{index:02d}"
        previous_state = prior_items.get(item_id, {}).get("current_state", "INITIALIZED_BASELINE")
        item = {
            "id": item_id,
            "metric_or_thesis": metric,
            "evaluation_type": evaluation_type,
            "rule_id": rule["rule_id"],
            "inputs": rule["rule_evidence"],
            "thresholds": {"policy_id": rule["threshold_policy_id"], "status": rule["threshold_status"]},
            "evidence_tiers": rule["evidence_tiers"],
            "automated_state": automated,
            "final_state": automated,
            "override": False,
            "override_reason": None,
            "previous_state": previous_state,
            "current_state": automated,
            "changed": previous_state != automated,
            "evidence": list(evidence),
            "next_verification": "下一次正式財務揭露",
            "time_horizon": "1至4季",
        }
        if item["final_state"] not in SMART_ALLOWED:
            raise DecisionRuleError("SMART_STATE_INVALID")
        items.append(item)
    return {"items": items, "allowed_states": sorted(SMART_ALLOWED), "aggregate_numeric_score": None, "actionable": False}
