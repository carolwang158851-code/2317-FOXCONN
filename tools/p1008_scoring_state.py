"""Read-only scoring consumer: evidence availability never grants score authority.

The active registry governs MIDR, not five-dimension or six-IC scoring. Preserve
the legacy research transformations, but never activate their formulas/weights.
No runtime overlay, prior-quarter carry, publisher or data writes are performed.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "modules/p1008_research_plugin/src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from p1008_research_plugin.quarterly_authority import validate_quarterly_authority_row

DECISION = "contracts/p1008_report_production/v1.1/P1008_DECISION_RULES_CONTRACT_V1.json"
REGISTRY = "contracts/p1008_formula_registry/v1.2/formula_registry.json"
BRIDGE = "contracts/p1008_t1_derived_kpi_bridge/v1.0/P1008_T1_DERIVED_KPI_BRIDGE_POLICY_V1.json"
SUPPLEMENT = "contracts/p1008_kpi_supplement/v1.0/P1008_KPI_SUPPLEMENT_POLICY_V1.json"
Q2 = "modules/p1008_research_plugin/config/quarterly_earnings/FY2026_Q2.json"
DIMENSIONS = (
    ("fund", "基本面", .35, "ROE / ROIC / OPM 推導品質分"),
    ("industry", "產業 / AI", .25, "AI 基礎設施需求 / 曝險；不可用產品組合代換 AI-specific"),
    ("chip", "籌碼面", .05, "ForeignHoldChange / Trend"),
    ("macro", "總經面", .20, "DIMAS CAP 反向換算"),
    ("valuation", "估值面", .15, "PB 參考區間換算"),
)


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def clamp(value):
    return max(0, min(100, math.floor(value + .5))) if value is not None else None


def quality(row):
    inputs = [number(row.get(key)) for key in ("ROE_TTM_Pct", "ROIC_Precise_Pct", "OperatingMarginPct")]
    if any(value is None for value in inputs):
        return None
    roe, roic, opm = inputs
    return clamp(min(roe / 15 * 40, 40) + min(roic / 15 * 40, 40) + min(opm / 5 * 20, 20))


def build_scoring_state(package_root):
    root = Path(package_root)
    identities = {}
    blockers = []

    def raw(path):
        try:
            data = (root / path).read_bytes()
            identities[path] = hashlib.sha256(data).hexdigest().upper()
            return data
        except OSError:
            identities[path] = "MISSING"
            return b""

    def read_json(path):
        try:
            return json.loads(raw(path).decode("utf-8-sig"))
        except (ValueError, UnicodeError):
            blockers.append(f"CONTRACT_UNAVAILABLE:{path}")
            return {}

    manifest = read_json("data/CSV_AUTHORITY_MANIFEST.json")
    decision, registry, bridge, supplement, q2 = [read_json(p) for p in (DECISION, REGISTRY, BRIDGE, SUPPLEMENT, Q2)]
    # Observation-only sidecars are byte-governed, not investment-score authority.
    entries = {item.get("path"): item for group in ("authoritativeFiles", "nonAuthoritativeFiles") for item in manifest.get(group, [])}

    def rows(path):
        data = raw(path)
        entry = entries.get(path, {})
        if not data or entry.get("sha256", "").upper() != identities[path] or entry.get("fileSizeBytes") != len(data):
            blockers.append(f"AUTHORITY_BYTES_UNVERIFIED:{path}")
            return []
        try:
            return list(csv.DictReader(line for line in data.decode("utf-8-sig").splitlines() if not line.startswith("##")))
        except (ValueError, UnicodeError):
            blockers.append(f"INPUT_UNREADABLE:{path}")
            return []

    master_rows = sorted(rows("data/2317_master_v9.csv"), key=lambda row: row.get("Quarter", ""))
    master = master_rows[-1] if master_rows else {}
    try:
        if master:
            validate_quarterly_authority_row(master)
    except ValueError as error:
        blockers.append(f"CURRENT_QUARTER_INVALID:{error}")
        master = {}  # Never select the preceding quarter as current.

    def latest(path):
        values = rows(path)
        return max(values, key=lambda row: row.get("Date", "")) if values else {}

    daily = latest("data/2317_daily_price.csv")
    fx = latest("data/fx_trend_observations.csv")
    macro = latest("data/macro_snapshot.csv")
    roe, roic, opm = [number(master.get(key)) for key in ("ROE_TTM_Pct", "ROIC_Precise_Pct", "OperatingMarginPct")]
    pb, close, bvps = [number(daily.get(key)) for key in ("PB_daily", "Close", "BVPS_ref")]
    change = number(master.get("ForeignHoldChange_Pct"))
    cap_inputs = [number(fx.get("US_10Y_Yield")), number(macro.get("Fed_Hike_Prob_YE")), number(macro.get("VIX")), close, bvps, number(master.get("EPS_YoY_Pct"))]
    cap = None
    if all(value is not None for value in cap_inputs) and bvps > 0:
        us10y, fed, vix, price, _, eps = cap_inputs
        def points(value, limits):
            return next((3 - i for i, limit in enumerate(limits) if value >= limit), 0)
        cap = points(us10y, (4.5, 4.2, 4.0)) + points(fed, (70, 60, 50)) + points(vix, (27, 22, 18))
        cap += points((price - bvps * 1.923) / (bvps * 1.923), (.25, .15, .05))
        cap += 3 if eps <= 5 else 2 if eps <= 15 else 1 if eps <= 25 else 0
    mix = q2.get("productMix", {})
    ai_value = number(master.get("AI_Revenue_Pct"))
    ai_authorized_input = (master.get("AI_Revenue_Denominator") in {"TOTAL_REVENUE", "SERVER_REVENUE", "CLOUD_NETWORK_REVENUE", "OTHER"}
                           and master.get("DataSupportLevel") in {"L1", "L2", "OFFICIAL", "AUTHORITATIVE"})
    research = {
        "fund": quality(master),
        "industry": clamp(ai_value / 50 * 100) if ai_value is not None and ai_authorized_input else None,
        "chip": clamp(50 + change * 6) if change is not None else None,
        "macro": clamp(100 - cap * 8) if cap is not None else None,
        "valuation": clamp(95 - ((pb - 1.162) / (2.115 - 1.162)) * 70) if pb is not None else None,
    }
    policy_reason = "現行 registry 僅啟用 MIDR；五維數值公式、正規化與聚合權重未啟用。"
    industry_reason = ("Industry / AI 缺少已啟用的需求 / 曝險數值映射與正規化；"
                       f"現行 bridge guard={bridge.get('domain_guards', {}).get('INDUSTRY_AI', 'CONTRACT_UNAVAILABLE')}。"
                       "AI-specific 官方未揭露；Cloud & Networking 及官方需求展望保留為研究證據，不代換 AI 營收占比、不轉為分數。")
    blockers.extend([policy_reason, industry_reason])
    if decision.get("rule_principles", {}).get("aggregate_numeric_score_allowed") is not False:
        blockers.append("NO_SUPPORTED_ACTIVE_FIVE_DIMENSION_SCORING_CONTRACT")
    if roic is None:
        blockers.append(f"基本面：當期 {master.get('Quarter', 'UNKNOWN')} ROIC={master.get('ROIC_Status', 'DATA_MISSING')}；不得承接前季。")
    if change is None:
        blockers.append("籌碼面：當期外資變動缺值，不承接前季、無正式數值映射。")
    dimensions = [{"key": key, "label": label, "weight": weight, "score": research[key],
                   "research_score": research[key], "formal_score": None, "formal_eligible": False,
                   "weighted_contribution": None, "weight_status": "LEGACY_REFERENCE_NOT_ACTIVATED",
                   "source": source, "note": industry_reason if key == "industry" else policy_reason}
                  for key, label, weight, source in DIMENSIONS]
    count = sum(value is not None for value in research.values())
    prior = master_rows[-2] if len(master_rows) > 1 else {}
    historical = {"value": quality(prior), "period": prior.get("Quarter"), "tier": "HISTORICAL_RESEARCH_ONLY",
                  "current": False, "formal_scoring_eligible": False, "source": "data/2317_master_v9.csv",
                  "fields": ["ROE_TTM_Pct", "ROIC_Precise_Pct", "OperatingMarginPct"]}
    state = {
        "schema_version": "P1008_SCORING_READINESS_STATE_V1", "formal_score": None, "formal_score_available": False,
        "formal_dimension_scores": {key: None for key in research},
        "formal_dimension_eligibility": {key: {"eligible": False, "reason": industry_reason if key == "industry" else policy_reason} for key in research},
        "research_kpi_values": {"dimension_models": research, "roe_ttm_pct": roe, "roic_pct": roic, "opm_pct": opm,
                                "cloud_networking_share_pct": number(mix.get("cloudAndNetworkingRevenueSharePct")),
                                "ai_specific_share_pct": mix.get("aiSpecificRevenueSharePct"),
                                "official_ai_demand_evidence": q2.get("aiCloudNetworking", []), "historical_quality": historical},
        "research_kpi_tiers": {"dimension_models": "RESEARCH_MODEL_NOT_FORMAL", "product_mix": "OFFICIAL_REPORTED_NOT_AI_SPECIFIC", "supplements": "OBSERVATION_ONLY"},
        "research_confidence": "NOT_AN_INVESTMENT_CONFIDENCE_SCORE",
        "data_coverage": {"research_model_count": count, "dimension_count": 5, "percent": count / 5 * 100,
                          "meaning": "CURRENT_RESEARCH_MODEL_AVAILABILITY_NOT_FORMAL_ELIGIBILITY"},
        "formal_scoring_coverage": {"eligible_count": 0, "dimension_count": 5, "percent": 0},
        "ic_readiness": {"score_count": 0, "monitor_count": 6, "ready": False,
                         "meaning": "SIX_MONITORING_PANELS_NOT_SIX_INVESTMENT_DIMENSIONS"},
        "aggregate_eligibility": {"eligible": False, "reason": policy_reason},
        "decision_actionable": False, "decision_label": "未形成正式評等", "decision_reason": policy_reason,
        "blocking_inputs": blockers, "industry_ai_blocker": industry_reason,
        "formula_version": registry.get("registryVersion", "CONTRACT_UNAVAILABLE"),
        "weight_version": "LEGACY_FIVE_DIMENSION_WEIGHTS_NOT_ACTIVATED",
        "dimensions": dimensions, "current_period": master.get("Quarter"),
        "current_source_rows": {"master": master, "daily": daily, "fx": fx, "macro": macro},
        "provenance": {"formula_registry": REGISTRY, "decision_contract": DECISION, "industry_guard": BRIDGE,
                       "supplement_policy": SUPPLEMENT, "supplement_scoring_eligible": supplement.get("formal_scoring_eligible") is True,
                       "research_formula_source": "src/index_p1008_v7.source.html:calculateQualityScore/calculateDimasCap/calculateRadarPackage",
                       "consumers": ["index_p1008_v7.html", "ui/P1008_WARROOM_COMMAND_CENTER_v24.html"],
                       "source_sha256": identities},
    }
    state["state_id"] = hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return state
