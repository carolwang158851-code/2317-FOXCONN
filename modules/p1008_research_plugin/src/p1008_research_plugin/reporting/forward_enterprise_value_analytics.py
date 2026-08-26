"""Deterministic forward enterprise-value analytics for the war report.

All scenarios are research-only T4 model outputs.  They are never appended to
historical observations and never mutate production authority.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from ..analysis.analysis_contracts import AnalysisPacket
from .historical_research_reconstruction import T2, T4


class ForwardAnalyticsError(RuntimeError):
    """Forward analytics cannot be reproduced from the governed inputs."""


MODEL_VERSION = "1.1.0"
DAY_BASIS_DEFAULT = Decimal("90")


def _d(value: Any) -> Decimal:
    try:
        return Decimal(str(value).replace(",", "").replace("%", ""))
    except (InvalidOperation, TypeError) as exc:
        raise ForwardAnalyticsError(f"NUMERIC_INPUT_INVALID:{value}") from exc


def _pct(value: Decimal, places: str = "0.0001") -> str:
    return str((value * Decimal("100")).quantize(Decimal(places)))


def _result(
    *, model_id: str, scenario: str, formula: str, result: Mapping[str, Any],
    unit: str, input_ids: Sequence[str], evidence_classes: Sequence[str],
    assumptions: Sequence[str], confidence: str, limitations: Sequence[str],
) -> dict[str, Any]:
    return {
        "model_id": model_id,
        "model_version": MODEL_VERSION,
        "input_observation_ids": list(input_ids),
        "input_evidence_classes": list(evidence_classes),
        "assumptions": list(assumptions),
        "formula": formula,
        "scenario": scenario,
        "result": dict(result),
        "unit": unit,
        "confidence": confidence,
        "limitations": list(limitations),
        "data_class": T4,
        "actionable": False,
    }


def per_share_growth(numerator_growth_pct: Any, share_growth_pct: Any) -> Decimal:
    """Exact per-share growth: (1+n)/(1+s)-1, with percentage inputs."""
    numerator = _d(numerator_growth_pct) / Decimal("100")
    shares = _d(share_growth_pct) / Decimal("100")
    if shares <= Decimal("-1"):
        raise ForwardAnalyticsError("SHARE_GROWTH_DENOMINATOR_INVALID")
    return ((Decimal("1") + numerator) / (Decimal("1") + shares) - Decimal("1")) * Decimal("100")


def calculate_roic(nopat: Any, invested_capital: Any) -> Decimal:
    capital = _d(invested_capital)
    if capital <= 0:
        raise ForwardAnalyticsError("INVESTED_CAPITAL_INVALID")
    return _d(nopat) / capital


def dilution_matrix(
    *, metric: str, numerator_growth_axis: Sequence[Any], share_growth_axis: Sequence[Any],
    denominator_basis: str,
) -> dict[str, Any]:
    rows = []
    for numerator in numerator_growth_axis:
        rows.append({
            "numerator_growth_pct": str(_d(numerator)),
            "values": [
                {
                    "share_growth_pct": str(_d(shares)),
                    "per_share_growth_pct": str(per_share_growth(numerator, shares).quantize(Decimal("0.0001"))),
                }
                for shares in share_growth_axis
            ],
        })
    return {
        "metric": metric,
        "formula": "(1 + numerator growth) / (1 + share growth) - 1",
        "denominator_basis": denominator_basis,
        "numerator_growth_axis_pct": [str(_d(item)) for item in numerator_growth_axis],
        "share_growth_axis_pct": [str(_d(item)) for item in share_growth_axis],
        "rows": rows,
        "break_even": "numerator growth equals share-count growth",
        "data_class": T4,
        "actionable": False,
    }


def working_capital_stress(
    *, revenue: Any, cogs: Any, baseline_cfo: Any, capex: Any,
    delta_dso: Any, delta_dio: Any, delta_dpo: Any,
    day_basis: Any = DAY_BASIS_DEFAULT,
) -> dict[str, str]:
    day_base = _d(day_basis)
    if day_base <= 0:
        raise ForwardAnalyticsError("DAY_BASIS_INVALID")
    rev, cost = _d(revenue), _d(cogs)
    cfo, capex_value = _d(baseline_cfo), _d(capex)
    delta_ar = rev * _d(delta_dso) / day_base
    delta_inventory = cost * _d(delta_dio) / day_base
    delta_ap_relief = cost * _d(delta_dpo) / day_base
    net_wc = delta_ar + delta_inventory - delta_ap_relief
    stressed_cfo = cfo - net_wc
    stressed_fcf = stressed_cfo - capex_value
    baseline_fcf = cfo - capex_value
    return {
        "day_basis": str(day_base),
        "day_basis_interpretation": "QUARTERLY_90_DAY_SENSITIVITY_NOT_ANNUAL_RUN_RATE",
        "delta_dso_days": str(_d(delta_dso)),
        "delta_dio_days": str(_d(delta_dio)),
        "delta_dpo_days": str(_d(delta_dpo)),
        "delta_ar_cash_requirement": str(delta_ar),
        "delta_inventory_cash_requirement": str(delta_inventory),
        "delta_ap_funding_relief": str(delta_ap_relief),
        "net_incremental_working_capital_requirement": str(net_wc),
        "baseline_cfo": str(cfo),
        "baseline_fcf": str(baseline_fcf),
        "capex_assumption": str(capex_value),
        "stressed_cfo": str(stressed_cfo),
        "stressed_fcf": str(stressed_fcf),
        "fcf_delta_vs_baseline": str(stressed_fcf - baseline_fcf),
        "funding_need_indication": str(max(Decimal("0"), -stressed_fcf)),
    }


def apply_working_capital_event_overlay(base_assumptions: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, str]:
    """Combine a named event overlay with an existing T4 scenario assumption."""
    allowed = {"delta_dso", "delta_dio", "delta_dpo"}
    if set(overlay) - allowed or set(base_assumptions) - allowed:
        raise ForwardAnalyticsError("WORKING_CAPITAL_OVERLAY_FIELD_INVALID")
    return {key: str(_d(base_assumptions.get(key, 0)) + _d(overlay.get(key, 0))) for key in sorted(allowed)}


def roic_sensitivity(
    *, operating_profit: Any, pretax_income: Any, income_tax: Any,
    latest_actual_roic_pct: Any, input_ids: Sequence[str],
    invested_capital_bridge: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    op, pretax, tax = _d(operating_profit), _d(pretax_income), _d(income_tax)
    if op <= 0 or pretax <= 0 or tax < 0:
        raise ForwardAnalyticsError("ROIC_SENSITIVITY_INPUT_INVALID")
    tax_rate = tax / pretax
    if not Decimal("0") <= tax_rate < Decimal("1"):
        raise ForwardAnalyticsError("EFFECTIVE_TAX_RATE_INVALID")
    quarterly_nopat = op * (Decimal("1") - tax_rate)
    annualized_nopat = quarterly_nopat * Decimal("4")
    reference_roic = _d(latest_actual_roic_pct) / Decimal("100")
    if reference_roic <= 0:
        raise ForwardAnalyticsError("ROIC_REFERENCE_INVALID")
    reference_capital = annualized_nopat / reference_roic
    scenario_specs = (
        ("LOW_CAPITAL_INTENSITY", Decimal("0.85")),
        ("BASE_CAPITAL_INTENSITY", Decimal("1.00")),
        ("HIGH_CAPITAL_INTENSITY", Decimal("1.15")),
    )
    scenarios = []
    for scenario_id, multiplier in scenario_specs:
        invested_capital = reference_capital * multiplier
        q_roic = calculate_roic(quarterly_nopat, invested_capital)
        annualized_roic = calculate_roic(annualized_nopat, invested_capital)
        scenarios.append(_result(
            model_id="ROIC_PERSISTENCE_CAPITAL_INTENSITY_SENSITIVITY_V1", scenario=scenario_id,
            formula="NOPAT / scenario invested capital",
            result={
                "quarterly_nopat_million_twd": str(quarterly_nopat),
                "annualized_nopat_million_twd": str(annualized_nopat),
                "scenario_invested_capital_million_twd": str(invested_capital),
                "quarterly_roic_persistence_sensitivity_pct": _pct(q_roic),
                "annualized_roic_persistence_sensitivity_pct": _pct(annualized_roic),
                "wacc_spread": None,
            },
            unit="% / 新台幣百萬元", input_ids=input_ids,
            evidence_classes=["T0_DIRECT_OFFICIAL", "T1_EXACT_DERIVED", T4],
            assumptions=[
                f"投入資本為參考投入資本的 {multiplier} 倍",
                "參考投入資本以單季NOPAT乘4後除以最新受治理實際ROIC反推",
                "現金排除於營運投入資本參考值；負債視為融資來源；租賃資料未提供且未插補",
                "期初與期末同口徑投入資本不足，故不宣稱實際平均投入資本",
            ],
            confidence="MEDIUM", limitations=[
                "這是以前期同口徑ROIC為錨的持續性／資本強度敏感度，不是獨立推估FY2026 Q2實際ROIC。",
                "單季年化只是假設全年四季等速，不是TTM。",
                "缺少同口徑期初／期末營運投入資本與受治理WACC。",
            ],
        ))
    independent = build_estimated_invested_capital(
        bridge=invested_capital_bridge,
        quarterly_nopat=quarterly_nopat,
        input_ids=input_ids,
    )
    return {
        "model_id": "ESTIMATED_INVESTED_CAPITAL_AND_ROIC_V1",
        "anchoring_audit": {
            "confirmed": True,
            "reference_roic_pct": str(_d(latest_actual_roic_pct)),
            "reference_period": "LATEST_GOVERNED_ACTUAL_REFERENCE",
            "reference_invested_capital_formula": "quarterly NOPAT × 4 / prior same-basis ROIC",
            "scenario_multipliers": ["0.85", "1.00", "1.15"],
            "independent_estimate_claim_allowed": False,
        },
        "independent_q2_invested_capital": independent,
        "actual_same_basis_q2": {
            "status": "PENDING_OR_UNAVAILABLE",
            "value": None,
            "basis": "ACTUAL_SAME_BASIS_Q2_UNAVAILABLE",
        },
        "effective_tax_rate": {"value_pct": _pct(tax_rate), "formula": "Income Tax Expense / Pretax Income", "data_class": "T1_EXACT_DERIVED", "classification": "REPORTED_ACCOUNTING_EFFECTIVE_TAX_RATE_NOT_NORMALIZED_OPERATING_TAX_RATE"},
        "nopat": {"quarterly_million_twd": str(quarterly_nopat), "annualized_million_twd": str(annualized_nopat), "annualization_rule": "quarterly NOPAT * 4"},
        "ttm_roic_reference": {"value_pct": str(_d(latest_actual_roic_pct)), "period": "LATEST_GOVERNED_ACTUAL_REFERENCE", "not_q2_actual": True},
        "persistence_sensitivity": {"model_id": "ROIC_PERSISTENCE_CAPITAL_INTENSITY_SENSITIVITY_V1", "scenarios": scenarios, "not_independent_q2_estimate": True},
        "scenarios": scenarios,
        "scenario_history_write_allowed": False,
        "actionable": False,
    }


def build_estimated_invested_capital(
    *, bridge: Mapping[str, Any] | None, quarterly_nopat: Decimal,
    input_ids: Sequence[str],
) -> dict[str, Any]:
    """Build a transparent partial operating-invested-capital bridge.

    Unsupported other operating assets and liabilities are excluded rather
    than invented.  This makes the estimate reproducible but explicitly
    partial rather than a same-basis official ROIC.
    """
    if not bridge:
        return {"available": False, "reason": "COMPATIBLE_Q1_Q2_ENDPOINTS_UNAVAILABLE", "reclassified": True}
    required = ("accountsReceivableMillionTwd", "inventoryMillionTwd", "propertyPlantEquipmentMillionTwd", "accountsPayableMillionTwd")
    if any(key not in bridge or len(bridge[key]) != 2 for key in required):
        return {"available": False, "reason": "REQUIRED_PARTIAL_OPERATING_IC_COMPONENTS_UNAVAILABLE", "reclassified": True}
    endpoints = []
    components = []
    for index, period in enumerate(bridge.get("periods", ["Q1", "Q2"])):
        ar = _d(bridge["accountsReceivableMillionTwd"][index])
        inventory = _d(bridge["inventoryMillionTwd"][index])
        ppe = _d(bridge["propertyPlantEquipmentMillionTwd"][index])
        ap = _d(bridge["accountsPayableMillionTwd"][index])
        endpoint = ar + inventory + ppe - ap
        endpoints.append(endpoint)
        components.append({"period": period, "accounts_receivable": str(ar), "inventory": str(inventory), "operating_ppe": str(ppe), "accounts_payable": str(ap), "partial_operating_invested_capital": str(endpoint)})
    average = sum(endpoints) / Decimal("2")
    quarterly_roic = calculate_roic(quarterly_nopat, average)
    return {
        "available": True,
        "model_id": "ESTIMATED_INVESTED_CAPITAL_V1",
        "formula": "Accounts receivable + Inventory + Operating PP&E - Accounts payable",
        "endpoint_components": components,
        "average_invested_capital_million_twd": str(average),
        "average_method": "(Q1 endpoint + Q2 endpoint) / 2",
        "quarterly_nopat_million_twd": str(quarterly_nopat),
        "quarterly_roic_pct": _pct(quarterly_roic),
        "annualized_quarterly_roic_sensitivity_pct": _pct(quarterly_roic * Decimal("4")),
        "annualized_is_ttm": False,
        "cash_treatment": bridge.get("cashTreatment", "EXCLUDED"),
        "marketable_securities_treatment": bridge.get("marketableSecuritiesTreatment", "EXCLUDED_UNAVAILABLE"),
        "debt_treatment": bridge.get("debtTreatment", "FINANCING_SOURCE_EXCLUDED"),
        "lease_treatment": bridge.get("leaseTreatment", "EXCLUDED_UNAVAILABLE"),
        "equity_treatment": bridge.get("equityTreatment", "FINANCING_SOURCE_EXCLUDED"),
        "other_assets_liabilities_treatment": bridge.get("otherAssetsLiabilitiesTreatment", "EXCLUDED_UNSUPPORTED_LINE_ITEMS"),
        "classification": "T2_ESTIMATED_DERIVED_PARTIAL_OPERATING_IC",
        "limitations": ["未納入缺乏同口徑證據的其他營運資產與無息營運負債。", "單季年化只作敏感度，不是TTM ROIC。"],
        "input_observation_ids": list(input_ids),
        "actionable": False,
    }


def capital_light_proxy(*, periods: Sequence[str], revenue: Sequence[Any], wc: Mapping[str, Sequence[Any]], cfo: Any, fcf: Any, capex: Any) -> dict[str, Any]:
    if len(periods) < 2 or any(len(wc[key]) != len(periods) for key in ("accountsReceivableMillionTwd", "inventoryMillionTwd", "accountsPayableMillionTwd", "cashConversionCycleDays", "accountsReceivableDays", "inventoryDays", "accountsPayableDays")):
        raise ForwardAnalyticsError("CAPITAL_LIGHT_COMPARABLE_PERIODS_INVALID")
    if len(revenue) != len(periods):
        raise ForwardAnalyticsError("CAPITAL_LIGHT_REVENUE_PERIOD_MISMATCH")
    prev, current = -2, -1
    prev_rev, current_rev = _d(revenue[prev]), _d(revenue[current])
    if prev_rev <= 0 or current_rev <= 0:
        raise ForwardAnalyticsError("CAPITAL_LIGHT_REVENUE_INVALID")
    indicators = []

    def direction(metric: str, before: Decimal, after: Decimal, lower_is_better: bool) -> None:
        if after == before:
            state = "NEUTRAL"
        elif (after < before) == lower_is_better:
            state = "SUPPORTING"
        else:
            state = "CONTRADICTING"
        indicators.append({"metric": metric, "prior": str(before), "current": str(after), "state": state})

    direction("CCC", _d(wc["cashConversionCycleDays"][prev]), _d(wc["cashConversionCycleDays"][current]), True)
    direction("DSO", _d(wc["accountsReceivableDays"][prev]), _d(wc["accountsReceivableDays"][current]), True)
    direction("DIO", _d(wc["inventoryDays"][prev]), _d(wc["inventoryDays"][current]), True)
    direction("DPO", _d(wc["accountsPayableDays"][prev]), _d(wc["accountsPayableDays"][current]), False)
    for metric, key, lower in (
        ("AR_TO_REVENUE", "accountsReceivableMillionTwd", True),
        ("INVENTORY_TO_REVENUE", "inventoryMillionTwd", True),
        ("AP_TO_REVENUE", "accountsPayableMillionTwd", False),
    ):
        direction(metric, _d(wc[key][prev]) / prev_rev, _d(wc[key][current]) / current_rev, lower)
    prior_nwc = _d(wc["accountsReceivableMillionTwd"][prev]) + _d(wc["inventoryMillionTwd"][prev]) - _d(wc["accountsPayableMillionTwd"][prev])
    current_nwc = _d(wc["accountsReceivableMillionTwd"][current]) + _d(wc["inventoryMillionTwd"][current]) - _d(wc["accountsPayableMillionTwd"][current])
    direction("NWC_TO_REVENUE", prior_nwc / prev_rev, current_nwc / current_rev, True)
    indicators.extend([
        {"metric": "CFO_TO_REVENUE", "current": str(_d(cfo) / current_rev), "state": "SUPPORTING" if _d(cfo) > 0 else "CONTRADICTING", "prior": "UNAVAILABLE"},
        {"metric": "FCF_TO_REVENUE", "current": str(_d(fcf) / current_rev), "state": "SUPPORTING" if _d(fcf) > 0 else "CONTRADICTING", "prior": "UNAVAILABLE"},
        {"metric": "CAPEX_TO_REVENUE", "current": str(_d(capex) / current_rev), "state": "UNVERIFIED_TREND", "prior": "UNAVAILABLE"},
    ])
    by_metric = {item["metric"]: item for item in indicators}
    factor_specs = (
        ("RECEIVABLE_EFFICIENCY", ("DSO", "AR_TO_REVENUE")),
        ("INVENTORY_EFFICIENCY", ("DIO", "INVENTORY_TO_REVENUE")),
        ("SUPPLIER_FINANCING", ("DPO", "AP_TO_REVENUE")),
        ("CASH_CONVERSION", ("CCC", "CFO_TO_REVENUE", "FCF_TO_REVENUE")),
        ("CAPITAL_INTENSITY", ("NWC_TO_REVENUE", "CAPEX_TO_REVENUE")),
    )
    factors = []
    for factor, metrics in factor_specs:
        rows = [by_metric[name] for name in metrics]
        supporting_metrics = [row["metric"] for row in rows if row["state"] == "SUPPORTING"]
        contradicting_metrics = [row["metric"] for row in rows if row["state"] == "CONTRADICTING"]
        level_signal = "NEGATIVE" if any(row["metric"] in {"CFO_TO_REVENUE", "FCF_TO_REVENUE"} and _d(row["current"]) < 0 for row in rows) else ("POSITIVE" if len(supporting_metrics) > len(contradicting_metrics) else ("NEGATIVE" if len(contradicting_metrics) > len(supporting_metrics) else "MIXED"))
        comparable = [row for row in rows if row.get("prior") != "UNAVAILABLE"]
        trend_signal = "UNAVAILABLE" if not comparable else ("IMPROVING" if sum(row["state"] == "SUPPORTING" for row in comparable) > sum(row["state"] == "CONTRADICTING" for row in comparable) else ("DETERIORATING" if sum(row["state"] == "CONTRADICTING" for row in comparable) > sum(row["state"] == "SUPPORTING" for row in comparable) else "MIXED"))
        factors.append({"factor_group": factor, "level_signal": level_signal, "trend_signal": trend_signal, "supporting_metrics": supporting_metrics, "contradicting_metrics": contradicting_metrics, "data_completeness": f"{len(comparable)}/{len(rows)} comparable trends", "metrics": rows})
    positive = sum(item["level_signal"] == "POSITIVE" for item in factors)
    negative = sum(item["level_signal"] == "NEGATIVE" for item in factors)
    signal = "IMPROVING" if positive >= 4 and negative == 0 else ("DETERIORATING" if negative >= 4 and positive == 0 else "INCONCLUSIVE")
    return {
        "model_id": "CAPITAL_LIGHT_PROXY_V1", "model_version": MODEL_VERSION,
        "period_comparison": f"{periods[prev]}→{periods[current]}",
        "signal": signal, "supporting_factor_count": positive, "contradicting_factor_count": negative,
        "factor_groups": factors,
        "evidence_components": indicators, "confidence": "MEDIUM" if signal != "INCONCLUSIVE" else "LOW",
        "consignment_percentage": None,
        "interpretation": "五個正規化因子群組用於檢驗較低資本占用假說；相關指標不重複投票，也不能證明或量化Consignment（客供料）比例。",
        "future_calibration_labels": ["CONSIGNMENT_PERCENT", "ASIC_MIX", "BUY_AND_SELL_MIX"],
        "data_class": "T1_EXACT_DERIVED", "actionable": False,
    }


def presentation_value(value: Any, metric: str) -> str:
    """Apply reader display precision without changing analytical precision."""
    places = {
        "EPS": "0.01", "BVPS": "0.01", "ROIC": "0.01", "ROE": "0.01",
        "MARGIN": "0.01", "PE": "0.01", "PB": "0.01", "PS": "0.01",
        "DAYS": "0.1", "RATIO_PCT": "0.01", "TWD_BILLION": "0.1",
        "TWD_MILLION": "1", "SHARES_MILLION": "0.001",
    }
    if metric not in places:
        raise ForwardAnalyticsError(f"PRESENTATION_METRIC_UNSUPPORTED:{metric}")
    return str(_d(value).quantize(Decimal(places[metric])))


def historical_valuation_context(historical_baseline: Mapping[str, Any], *, metric_id: str, current_value: Any, cutoff_period: str) -> dict[str, Any]:
    rows = [
        item for item in historical_baseline.get("observations", [])
        if item.get("metric_id") == metric_id and str(item.get("period", "")) <= cutoff_period
    ]
    values = sorted(_d(item["value"]) for item in rows)
    if not values:
        return {"status": "UNAVAILABLE", "reason": "NO_COMPARABLE_HISTORY", "metric_id": metric_id}
    current = _d(current_value)
    midpoint = len(values) // 2
    median = values[midpoint] if len(values) % 2 else (values[midpoint - 1] + values[midpoint]) / 2
    less_or_equal = sum(value <= current for value in values)
    return {
        "status": "AVAILABLE_DESCRIPTIVE_ONLY",
        "metric_id": metric_id,
        "observation_count": len(values),
        "median": str(median),
        "minimum": str(values[0]),
        "maximum": str(values[-1]),
        "current_or_pre_event_value": str(current),
        "percentile_pct": str((Decimal(less_or_equal) / Decimal(len(values)) * Decimal("100")).quantize(Decimal("0.1"))),
        "cutoff_period": cutoff_period,
        "look_ahead_observations": 0,
        "policy_interpretation_allowed": False,
    }


def build_transmission_layer() -> list[dict[str, str]]:
    """Reader-facing causal structure using only already governed Q2 evidence."""
    return [
        {"external_driver": "AI Rack需求", "first_order_financial_effect": "伺服器出貨與營收規模", "second_order_effect": "產品組合、費用吸收與營益率", "fcf_or_roic_transmission": "若營運資金與資本支出增幅低於營業利益增幅，FCF與ROIC較可能改善", "current_evidence": "公司指引第三季AI Rack出貨季增高雙位數；實現值尚待揭露", "unresolved_variable": "實際出貨、毛利率與客供料占比：NOT QUANTIFIED"},
        {"external_driver": "GPU／ASIC交易模式", "first_order_financial_effect": "Buy & Sell與Consignment（客供料）改變營收認列與存貨占用", "second_order_effect": "機械性影響P/S分母與資金需求", "fcf_or_roic_transmission": "較低存貨與資金需求才可能轉為較高FCF／ROIC", "current_evidence": "正式資料未分拆交易模式占比", "unresolved_variable": "GPU／ASIC與Consignment占比：NOT QUANTIFIED"},
        {"external_driver": "新台幣匯率", "first_order_financial_effect": "外幣營收換算與毛利", "second_order_effect": "營業利益及應收帳款換算", "fcf_or_roic_transmission": "利潤與營運資金共同影響FCF／ROIC", "current_evidence": "結果文件未量化敏感度", "unresolved_variable": "幣別曝險與避險比率：NOT QUANTIFIED"},
        {"external_driver": "關稅／供應地調整", "first_order_financial_effect": "成本、定價與產能移轉", "second_order_effect": "毛利率、Capex與折舊", "fcf_or_roic_transmission": "額外Capex與營運資金可能壓低FCF及短期ROIC", "current_evidence": "結果文件未量化關稅影響", "unresolved_variable": "客戶轉嫁、地區成本差與時程：NOT QUANTIFIED"},
        {"external_driver": "主要客戶需求", "first_order_financial_effect": "出貨量與產能利用率", "second_order_effect": "費用吸收、毛利與議價", "fcf_or_roic_transmission": "需求轉為現金回收後才支持企業價值", "current_evidence": "未提供客戶別量化資料", "unresolved_variable": "客戶集中度與產品週期：NOT QUANTIFIED"},
        {"external_driver": "資本支出需求", "first_order_financial_effect": "PP&E與折舊增加", "second_order_effect": "產能、技術能力與固定成本", "fcf_or_roic_transmission": "Capex先壓低FCF；後續需由NOPAT增幅驗證ROIC", "current_evidence": "2026H1 Capex與FCF有官方累計證據", "unresolved_variable": "AI專屬Capex與回收期：NOT QUANTIFIED"},
    ]


def build_forward_enterprise_value_analytics(analysis: AnalysisPacket, historical_baseline: Mapping[str, Any]) -> dict[str, Any]:
    if analysis.event_type != "QUARTERLY_EARNINGS" or analysis.quarterly_earnings is None:
        raise ForwardAnalyticsError("QUARTERLY_EARNINGS_REQUIRED")
    q = analysis.quarterly_earnings
    a = q.enterprise_value_analytics
    wc = a["workingCapital"]
    revenue = _d(a["revenueMillionTwd"])
    gross_profit = _d(a["grossProfitMillionTwd"])
    cogs = revenue - gross_profit
    source_ids = list(q.revenue.evidence_ids)
    roic = roic_sensitivity(
        operating_profit=a["operatingProfitMillionTwd"], pretax_income=a["pretaxProfitMillionTwd"],
        income_tax=a["incomeTaxExpenseMillionTwd"], latest_actual_roic_pct=analysis.financial_trend.roic.value,
        input_ids=source_ids, invested_capital_bridge=a.get("investedCapitalBridge"),
    )
    scenario_inputs = (
        ("BASE", 0, 0, 0),
        ("RESEARCH_STRESS_A", 5, 10, 0),
        ("RESEARCH_STRESS_B", 10, 15, -5),
    )
    wc_scenarios = []
    for scenario, dso, dio, dpo in scenario_inputs:
        output = working_capital_stress(
            revenue=revenue, cogs=cogs, baseline_cfo=a["q2StandaloneCfoMillionTwd"],
            capex=a["q2StandaloneCapexMillionTwd"], delta_dso=dso, delta_dio=dio, delta_dpo=dpo,
        )
        wc_scenarios.append(_result(
            model_id="WORKING_CAPITAL_STRESS_TEST_V1", scenario=scenario,
            formula="ΔAR + ΔInventory - ΔAP; stressed CFO = baseline CFO - net ΔWC; stressed FCF = stressed CFO - Capex",
            result=output, unit="新台幣百萬元", input_ids=source_ids,
            evidence_classes=["T0_DIRECT_OFFICIAL", "T1_EXACT_DERIVED", T4],
            assumptions=[f"DAY_BASIS={DAY_BASIS_DEFAULT}", f"ΔDSO={dso}", f"ΔDIO={dio}", f"ΔDPO={dpo}", "研究敏感度情境；並非Owner核准的嚴重度政策"],
            confidence="MEDIUM", limitations=["不含利率敏感度，因缺受治理資金成本假設。", "未估算精確淨現金影響，因Q2同口徑期末淨現金橋接不足。"],
        ))
    revenue_history = [_d(item) * Decimal("100") for item in q.quarterly_history["revenue100mTwd"][-3:]]
    cap_light = capital_light_proxy(
        periods=wc["periods"], revenue=revenue_history, wc=wc,
        cfo=a["q2StandaloneCfoMillionTwd"], fcf=a["q2StandaloneFcfMillionTwd"], capex=a["q2StandaloneCapexMillionTwd"],
    )
    share_axis = (0, Decimal("0.5"), 1, 2, 3)
    numerator_axis = (0, 5, 10, 15, 20)
    dilution = {
        "model_id": "DILUTION_SENSITIVITY_V1", "model_version": MODEL_VERSION,
        "EPS": dilution_matrix(metric="EPS", numerator_growth_axis=numerator_axis, share_growth_axis=share_axis, denominator_basis="COMPATIBLE_WEIGHTED_AVERAGE_SHARES"),
        "FCF_PER_SHARE": dilution_matrix(metric="FCF_PER_SHARE", numerator_growth_axis=numerator_axis, share_growth_axis=share_axis, denominator_basis="FCF_PER_SHARE_V1_COMPATIBLE_WEIGHTED_AVERAGE_SHARES"),
        "BVPS": dilution_matrix(metric="BVPS", numerator_growth_axis=numerator_axis, share_growth_axis=share_axis, denominator_basis="PERIOD_END_SHARES_T4_SCENARIO"),
        "period_end_share_actual_status": "INSUFFICIENT_DATA",
        "weighted_average_share_estimate_class": T2,
        "break_even_thresholds": {
            "EPS_DILUTION_BREAK_EVEN_GROWTH": "equal to compatible weighted-average share growth",
            "BVPS_DILUTION_BREAK_EVEN_GROWTH": "equal to period-end share growth",
            "FCF_PER_SHARE_DILUTION_BREAK_EVEN_GROWTH": "equal to compatible weighted-average share growth",
        },
        "data_class": T4, "actionable": False,
    }
    ledger = [*roic["scenarios"], *wc_scenarios]
    for metric in ("EPS", "FCF_PER_SHARE", "BVPS"):
        ledger.append(_result(
            model_id="DILUTION_SENSITIVITY_V1", scenario=metric,
            formula=dilution[metric]["formula"], result={"matrix": dilution[metric]["rows"], "break_even": dilution[metric]["break_even"]},
            unit="%", input_ids=source_ids, evidence_classes=[T2 if metric != "BVPS" else T4, T4],
            assumptions=[f"denominator={dilution[metric]['denominator_basis']}", "情境軸不是公司預測或Owner核准政策門檻"],
            confidence="MEDIUM" if metric != "BVPS" else "LOW", limitations=["矩陣為數學敏感度，不是盈餘、FCF、權益或股數預測。"],
        ))
    ledger.append(_result(
        model_id="CAPITAL_LIGHT_PROXY_V1", scenario="CURRENT_COMPARABLE_PERIODS",
        formula="five normalized factor groups; no raw-metric vote count or numeric composite score", result={"signal": cap_light["signal"], "factor_groups": cap_light["factor_groups"]},
        unit="directional state", input_ids=source_ids, evidence_classes=["T0_DIRECT_OFFICIAL", "T1_EXACT_DERIVED"],
        assumptions=["比較期間與財務口徑相容"], confidence=cap_light["confidence"],
        limitations=["未揭露Consignment百分比，代理訊號不得視為因果證明。"],
    ))
    valuation_state = q.valuation_scenarios["valuationTimeBasis"]["valuationState"]
    price_context = q.valuation_scenarios["price"]["valuationContext"]
    return {
        "contract_id": "P1008_FORWARD_ENTERPRISE_VALUE_ANALYTICS_V1",
        "framework_axes": [
            "OPERATING_PROFIT_QUALITY", "FCF_CONVERSION", "CAPITAL_EFFICIENCY",
            "PER_SHARE_VALUE_COMPOUNDING", "FORWARD_STRESS_AND_SENSITIVITY", "RULE_BASED_DECISION_ENGINE",
        ],
        "roic_sensitivity": roic,
        "working_capital_stress": {"model_id": "WORKING_CAPITAL_STRESS_TEST_V1", "scenarios": wc_scenarios, "day_basis": str(DAY_BASIS_DEFAULT)},
        "capital_light_proxy": cap_light,
        "dilution_sensitivity": dilution,
        "valuation_time_basis": q.valuation_scenarios["valuationTimeBasis"],
        "valuation_context": {
            "pe": {**q.valuation_scenarios["ttmPe"], "context": valuation_state, "price_date": q.valuation_scenarios["price"]["date"]},
            "pb": {**q.valuation_scenarios["pb"], "context": valuation_state},
            "ps": {**q.valuation_scenarios["ps"], "context": valuation_state, "priceContext": price_context},
            "historical": {
                "pe": historical_valuation_context(historical_baseline, metric_id="PE_TTM", current_value=q.valuation_scenarios["ttmPe"]["value"], cutoff_period="2026Q2"),
                "pb": historical_valuation_context(historical_baseline, metric_id="PB", current_value=q.valuation_scenarios["pb"]["value"], cutoff_period="2026Q2"),
                "ps": historical_valuation_context(historical_baseline, metric_id="PS_TTM", current_value=q.valuation_scenarios["ps"]["value"], cutoff_period="2026Q2"),
            },
        },
        "chapter_6_transmission_layer": build_transmission_layer(),
        "presentation_precision_contract": "REPORT_PRESENTATION_PRECISION_V1",
        "forward_model_ledger": ledger,
        "historical_observation_count_before": historical_baseline.get("observation_count"),
        "historical_observation_count_after": historical_baseline.get("observation_count"),
        "actual_history_mutated": False,
        "network_requests": 0, "openai_api_calls": 0, "canva_calls": 0,
        "publication": False, "actionable": False,
    }
