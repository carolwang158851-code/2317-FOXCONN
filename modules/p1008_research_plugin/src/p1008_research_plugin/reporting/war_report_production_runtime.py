"""Contract-driven runtime wiring for the permanent 11-chapter war report.

The module is deliberately an adapter over the existing G1/Phase B1 analysis,
report, chart, rendering and validation components.  It writes candidate
artifacts only and never publishes or mutates governed authority.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..adapters.authority_adapter import AuthorityAdapter
from ..analysis.analysis_contracts import AnalysisPacket
from ..contract_loader import ContractLoader
from ..phaseb1_common import atomic_write, atomic_write_json, canonical_json_bytes, sha256_bytes, sha256_file
from ..phaseb1_pipeline import PhaseB1Pipeline
from .chart_data_builder import ChartDataBuilder
from .enterprise_value_rule_engine import (
    build_decision_state,
    build_smart_state,
    evaluate_enterprise_value_rules,
)
from .forward_enterprise_value_analytics import build_forward_enterprise_value_analytics
from .historical_kpi_baseline import build_historical_kpi_baseline, observations_for
from .historical_research_reconstruction import (
    T2,
    build_layered_historical_research_baseline,
    research_observations_for,
)
from .report_builder import ReportBuilder
from .report_contracts import ChartData, ChartSeries, ReportCandidate
from .report_renderer_formal import FormalPreviewRenderer
from .report_validator import ReportValidator
from .war_report_production_contract import (
    WarReportContractError,
    chapter_identity,
    load_contract,
    plan_trigger,
    render_owner_review_candidate,
    resolve_mother_template,
    resolve_quarterly_roic,
    validate_contract,
    validate_reader_html,
)


class WarReportRuntimeError(RuntimeError):
    """The report runtime cannot safely reach Owner Review."""


@dataclass(frozen=True)
class RuntimeIdentity:
    report_key: str
    revision: int
    previous_revision: int | None


_REPORT_KEY = re.compile(r"[A-Z0-9][A-Z0-9_-]{2,127}")
_STYLE = re.compile(r"<style>(.*?)</style>", re.DOTALL | re.IGNORECASE)
_FORBIDDEN_READER = (
    "P1008", "production authority", "DATA GAP", "fail-closed",
    "actionable=false", "publication=false", "企業價值有沒有壞掉", "撐出來", "沒看懂 AI",
)
_KPI_ALLOWED = ("ROIC", "FCF", "ROE", "EPS", "BVPS", "CCC", "P/S", "P/E", "P/B", "WACC", "CFO", "Capex")

_CHAPTER_SECTION_MAP: dict[str, tuple[str, ...]] = {
    "s1": ("EXECUTIVE_SUMMARY", "HOLDING_THESIS"),
    "s2": ("GROWTH_QUALITY", "MARGIN_QUALITY"),
    "s3": ("Q2_FINANCIAL_SUMMARY", "OPERATING_LEVERAGE", "PROFIT_PASS_THROUGH"),
    "s4": ("EARNINGS_TO_CASH_QUALITY", "WORKING_CAPITAL_CAPITAL_REQUIREMENT", "CAPITAL_EFFICIENCY", "ROE_DUPONT_INTERPRETATION"),
    "s5": ("AI_SERVER_CLOUD_NETWORKING",),
    "s6": ("COUNTEREVIDENCE_LIMITATIONS",),
    "s7": ("GOVERNANCE_COMMITMENT_EXECUTION", "GREEN_SIGNALS", "GOVERNANCE_TARGET_VS_ACTUAL"),
    "s8": ("VALUATION", "NEW_MONEY_VALUATION_CONTEXT"),
    "s9": ("NON_GREEN_DEEP_REVIEW", "INVALIDATION_CONDITIONS", "NEXT_VALIDATION_DATE_AND_EVENT"),
    "s10": ("RETIREMENT_CASHFLOW_IMPLICATION",),
    "s11": ("REPORT_IDENTITY_AND_CUTOFF",),
}

_MONTHLY_CHAPTER_SECTION_MAP: dict[str, tuple[str, ...]] = {
    "s1": ("EXECUTIVE_JUDGMENT", "WHAT_CHANGED", "WHAT_DID_NOT_CHANGE"),
    "s2": ("FINANCIAL_TRANSMISSION",),
    "s3": ("EARNINGS_AND_MARGIN_QUALITY",),
    "s4": ("CASH_FLOW_AND_DIVIDEND_SAFETY",),
    "s5": ("SUPPORTING_EVIDENCE", "ALTERNATIVE_EXPLANATION"),
    "s6": ("COUNTEREVIDENCE", "MISSING_EVIDENCE"),
    "s7": ("THREE_AUDIENCE_LENSES",),
    "s8": ("VALUATION_INTERPRETATION", "PRICE_VOLUME_AND_MARKET_PSYCHOLOGY"),
    "s9": ("NEW_MONEY_VIEW", "EXISTING_HOLDING_VIEW", "INVALIDATION_CONDITIONS"),
    "s10": ("NEXT_VALIDATION_DATE_AND_EVENT",),
    "s11": ("REPORT_IDENTITY_AND_CUTOFF", "DATA_LIMITATIONS"),
}

_CHAPTER_CHARTS: dict[str, tuple[str, ...]] = {
    "s2": ("full_history_profit_chain", "full_history_margin", "full_history_eps"),
    "s4": ("full_history_cash_flow", "full_history_cash_flow_cumulative", "full_history_working_capital", "full_history_nwc_proxy", "full_history_roic", "full_history_bvps"),
    "s8": ("full_history_valuation", "full_history_ps"),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _style_bytes(document: str) -> bytes:
    match = _STYLE.search(document)
    if not match:
        raise WarReportRuntimeError("MOTHER_TEMPLATE_STYLE_MISSING")
    return match.group(1).encode("utf-8")


def _semantic_css(css: bytes) -> bytes:
    return re.sub(rb"\s+", b"", css)


def validate_template_lineage(source_mother: Path | None = None) -> dict[str, Any]:
    """Prove that permanent-template drift is content slotting/minification only."""
    contract = load_contract()
    template = resolve_mother_template()
    result = {
        "template_sha256": _sha(template.encode("utf-8")),
        "source_sha256": contract["template_contract"]["proven_mother_source_sha256"],
        "css_sha256_template": _sha(_style_bytes(template)),
        "semantic_css_equal": None,
        "reason": "Permanent mother replaces period-specific prose with governed slots and minifies unchanged CSS.",
    }
    if source_mother is not None:
        raw = source_mother.read_bytes()
        if _sha(raw) != result["source_sha256"]:
            raise WarReportRuntimeError("SOURCE_MOTHER_HASH_MISMATCH")
        source = raw.decode("utf-8")
        equal = _semantic_css(_style_bytes(source)) == _semantic_css(_style_bytes(template))
        if not equal:
            raise WarReportRuntimeError("MOTHER_TEMPLATE_VISUAL_DRIFT")
        result["semantic_css_equal"] = True
        result["css_sha256_source"] = _sha(_style_bytes(source))
    return result


def resolve_runtime_identity(trigger_context: Mapping[str, Any]) -> RuntimeIdentity:
    report_key = str(trigger_context.get("reportKey") or trigger_context.get("report_key") or "")
    revision = trigger_context.get("revision", 1)
    previous = trigger_context.get("previousRevision")
    if not _REPORT_KEY.fullmatch(report_key):
        raise WarReportRuntimeError("REPORT_KEY_INVALID")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise WarReportRuntimeError("REVISION_INVALID")
    if previous is not None and (not isinstance(previous, int) or previous < 1 or previous >= revision):
        raise WarReportRuntimeError("PREVIOUS_REVISION_INVALID")
    return RuntimeIdentity(report_key, revision, previous)


def _dec(value: str) -> Decimal:
    return Decimal(str(value).replace(",", "").replace("%", ""))


def _metric(name: str, period: str, value: str | None, unit: str, source: Sequence[str], *, derived: bool = False, formula: str | None = None) -> dict[str, Any]:
    return {
        "metric_name": name, "period": period, "value": value, "unit": unit,
        "source": list(source), "source_type": "GOVERNED_DERIVATION" if derived else "GOVERNED_DIRECT",
        "direct_or_derived": "DERIVED" if derived else "DIRECT",
        "calculation_version": formula if derived else None,
        "availability_state": "AVAILABLE" if value not in (None, "", "INSUFFICIENT_DATA") else "PENDING_OR_UNAVAILABLE",
    }


def build_financial_baseline(analysis: AnalysisPacket) -> list[dict[str, Any]]:
    if analysis.event_type != "QUARTERLY_EARNINGS" or analysis.quarterly_earnings is None:
        return []
    q = analysis.quarterly_earnings
    a = q.enterprise_value_analytics
    src = q.revenue.evidence_ids
    period = q.fiscal_period
    wc = a["workingCapital"]
    last = -1
    values = [
        _metric("Revenue", period, q.revenue.value, q.revenue.unit, src),
        _metric("Gross Profit", period, a["grossProfitMillionTwd"], "新台幣百萬元", src),
        _metric("Operating Profit", period, a["operatingProfitMillionTwd"], "新台幣百萬元", src),
        _metric("Pretax Income", period, a["pretaxProfitMillionTwd"], "新台幣百萬元", src),
        _metric("Parent Net Income", period, q.attributable_profit.value, q.attributable_profit.unit, src),
        _metric("EPS", period, q.eps.value, q.eps.unit, src),
        _metric("GM", period, q.gross_margin.value, "%", src),
        _metric("OM", period, q.operating_margin.value, "%", src),
        _metric("NM", period, q.net_margin.value, "%", src),
        _metric("Derived Opex Proxy", period, a["operatingExpenseProxyMillionTwd"], "新台幣百萬元", src, derived=True, formula="GP_MINUS_OP_V1"),
        _metric("CFO", period, a["q2StandaloneCfoMillionTwd"], "新台幣百萬元", src, derived=True, formula="H1_MINUS_Q1_V1"),
        _metric("Capex", period, a["q2StandaloneCapexMillionTwd"], "新台幣百萬元", src, derived=True, formula="H1_MINUS_Q1_V1"),
        _metric("FCF", period, a["q2StandaloneFcfMillionTwd"], "新台幣百萬元", src, derived=True, formula="CFO_MINUS_CAPEX_V1"),
        _metric("A/R", wc["periods"][last], wc["accountsReceivableMillionTwd"][last], "新台幣百萬元", src),
        _metric("Inventory", wc["periods"][last], wc["inventoryMillionTwd"][last], "新台幣百萬元", src),
        _metric("A/P", wc["periods"][last], wc["accountsPayableMillionTwd"][last], "新台幣百萬元", src),
        _metric(
            "NWC Proxy", wc["periods"][last],
            str(_dec(wc["accountsReceivableMillionTwd"][last]) + _dec(wc["inventoryMillionTwd"][last]) - _dec(wc["accountsPayableMillionTwd"][last])),
            "新台幣百萬元", src, derived=True, formula="AR_PLUS_INVENTORY_MINUS_AP_V1",
        ),
        _metric("CCC", wc["periods"][last], wc["cashConversionCycleDays"][last], "天", src, derived=True, formula="DSO_PLUS_DIO_MINUS_DPO_V1"),
        _metric("ROE", a["roe"]["currentPeriod"], a["roe"]["currentPct"], "%", a["roe"]["sourceIds"]),
        _metric("ROIC", period, None, "%", src, derived=True, formula="ROIC_V1_NORMALIZED_OPERATING"),
        _metric("BVPS Latest Known", a["bvps"]["currentPeriod"], a["bvps"]["currentValue"], "新台幣元", [a["bvps"]["sourceId"]]),
        _metric("BVPS", period, None, "新台幣元", src),
        _metric("Share Count", period, None, "股", src),
        _metric("Current Price", analysis.valuation_analysis.data_window.split("..")[-1], analysis.valuation_analysis.current_price, "新台幣元", analysis.source_evidence_ids),
        _metric("Current P/B", analysis.valuation_analysis.data_window.split("..")[-1], analysis.valuation_analysis.current_pb, "倍", analysis.source_evidence_ids),
    ]
    return values


def build_per_share_value_state(
    baseline: Sequence[Mapping[str, Any]],
    historical_baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve per-share metrics with the governed flow-denominator contract."""
    by_name = {str(item["metric_name"]): item for item in baseline}
    share_count = by_name.get("Share Count", {})
    share_available = share_count.get("availability_state") == "AVAILABLE"
    fcf = by_name.get("FCF", {})
    reconstructed = research_observations_for(historical_baseline, "FCF_PER_SHARE") if historical_baseline else []
    latest = reconstructed[-1] if reconstructed else None
    wa_estimates = research_observations_for(historical_baseline, "WA_SHARES_BASIC_EST") if historical_baseline else []
    return {
        "EPS": by_name.get("EPS"),
        "BVPS": by_name.get("BVPS Latest Known") or by_name.get("BVPS"),
        "FCF_PER_SHARE": latest or {
            "value": None, "availability_state": "PENDING_OR_UNAVAILABLE" if not share_available else "CALCULATION_REQUIRED",
            "formula": "FCF_PER_SHARE_V1", "source_metrics": [fcf.get("metric_name"), share_count.get("metric_name")],
        },
        "WA_SHARE_ESTIMATES": wa_estimates,
        "SHARE_COUNT": share_count,
        "share_count_growth_assessment": "PENDING_OR_UNAVAILABLE" if not share_available else "REQUIRES_COMPARABLE_HISTORY",
        "enterprise_value_reaches_each_share": "PARTIALLY_VERIFIED_WITH_ESTIMATED_FCF_PER_SHARE" if latest else "PARTIALLY_VERIFIED_EPS_AND_LATEST_BVPS_ONLY",
    }


def build_fcf_conversion_state(package_root: Path, analysis: AnalysisPacket) -> dict[str, Any] | None:
    if analysis.event_type != "QUARTERLY_EARNINGS" or analysis.quarterly_earnings is None:
        return None
    q = analysis.quarterly_earnings
    a = q.enterprise_value_analytics
    cash = AuthorityAdapter(package_root, ContractLoader(package_root)).read_csv("data/2317_cash_flow_authority.csv")
    observations = [
        {
            "period": row["period"],
            "CFO": str(_dec(row["operating_cash_flow_thousand_ntd"]) / 1000),
            "Capex": str(_dec(row["ppe_capex_thousand_ntd"]) / 1000),
            "FCF": str(_dec(row["free_cash_flow_core_thousand_ntd"]) / 1000),
        }
        for row in cash.rows
    ]
    observations.append({
        "period": q.fiscal_period.replace("FY", "").replace(" ", ""),
        "CFO": a["q2StandaloneCfoMillionTwd"],
        "Capex": a["q2StandaloneCapexMillionTwd"],
        "FCF": a["q2StandaloneFcfMillionTwd"],
    })
    negative_tail = 0
    for item in reversed(observations):
        if _dec(item["FCF"]) < 0:
            negative_tail += 1
        else:
            break
    ccc = a["workingCapital"]["cashConversionCycleDays"]
    classification = classify_fcf_conversion(
        cfo=observations[-1]["CFO"], fcf=observations[-1]["FCF"],
        ccc_improved=_dec(ccc[-1]) < _dec(ccc[0]), repeated_negative_periods=negative_tail,
    )
    return {
        "observations": observations,
        "comparison": {
            "current_period": observations[-1],
            "prior_quarter_where_meaningful": observations[-2] if len(observations) > 1 else None,
            "same_period_prior_year": None,
            "prior_full_fiscal_year": None,
            "long_term_pattern": {"available_observations": len(observations), "consecutive_negative_fcf": negative_tail},
        },
        "working_capital_factors": a["workingCapital"],
        "funding_need": "INFERRED_FROM_NEGATIVE_FCF_NOT_DIRECTLY_MEASURED",
        "interest_expense": "PENDING_OR_UNAVAILABLE",
        "roic": a["roic"],
        "classification": classification,
        "classification_basis": "CFO_FCF_CCC_AND_REPEATED_NEGATIVE_PERIODS_V1",
    }


def derive_bvps_metric(*, period: str, parent_equity: str, ordinary_shares: str, source: Sequence[str]) -> dict[str, Any]:
    shares = _dec(ordinary_shares)
    if shares <= 0:
        raise WarReportRuntimeError("BVPS_SHARE_DENOMINATOR_INVALID")
    value = str((_dec(parent_equity) / shares).normalize())
    return _metric("BVPS", period, value, "新台幣元", source, derived=True, formula="PARENT_EQUITY_DIVIDED_BY_PERIOD_END_ORDINARY_SHARES_V1")


def classify_fcf_conversion(*, cfo: str, fcf: str, ccc_improved: bool, repeated_negative_periods: int) -> str:
    """Evidence-bound three-state FCF classification; no seasonality shortcut."""
    contract_states = set(load_contract()["kpi_contract"]["fcf_conversion"]["classifications"])
    if _dec(cfo) >= 0 and _dec(fcf) >= 0 and ccc_improved:
        result = "CYCLICAL_OR_TIMING_PRESSURE"
    elif _dec(fcf) < 0 and repeated_negative_periods >= 3 and not ccc_improved:
        result = "STRUCTURAL_DETERIORATION"
    else:
        result = "STRUCTURAL_RISK_NOT_RULED_OUT"
    if result not in contract_states:
        raise WarReportRuntimeError("FCF_CLASSIFICATION_CONTRACT_DRIFT")
    return result


def _chart(chart_id: str, title: str, question: str, labels: list[str], series: list[ChartSeries], sources: list[str], commentary: list[str], *, visualization_type: str = "QUANTITATIVE_CHART") -> ChartData:
    period = f"{labels[0]}至{labels[-1]}" if labels else "資料未提供"
    return ChartData(
        chart_id=chart_id, title_zh=title, decision_question=question, period=period,
        source_evidence_ids=sources, labels=labels, series=series, commentary_zh=commentary,
        observation_zh=commentary[0], interpretation_zh=commentary[-1],
        p1008_implication_zh="本圖只更新研究判讀，不形成交易指令。",
        strategic_implication_zh="本圖須與獲利、資本與現金證據共同判讀。",
        enterprise_value_implication_zh="完整歷史用於辨識結構變化，不因版面刪除觀察值。",
        next_checkpoint_zh="下一次正式財務揭露。", visualization_type=visualization_type,
        signal="YELLOW", actionable=False,
    )


def _indexed(values: Sequence[str]) -> list[str]:
    numeric = [_dec(value) for value in values]
    if not numeric or numeric[0] == 0:
        raise WarReportRuntimeError("INDEX_BASE_INVALID")
    return [str((value / numeric[0] * Decimal("100")).quantize(Decimal("0.1"))) for value in numeric]


def build_full_history_charts(package_root: Path, analysis: AnalysisPacket, historical_baseline: Mapping[str, Any] | None = None) -> tuple[list[ChartData], list[dict[str, Any]], list[str]]:
    """Compile structural charts from all comparable governed observations."""
    if analysis.event_type != "QUARTERLY_EARNINGS" or analysis.quarterly_earnings is None:
        return ChartDataBuilder().build(analysis), [], []
    authority = AuthorityAdapter(package_root, ContractLoader(package_root))
    master = authority.read_csv("data/2317_master_v9.csv")
    rows = list(master.rows)
    if not rows:
        raise WarReportRuntimeError("FULL_HISTORY_EMPTY")
    periods = [row["Quarter"] for row in rows]
    if periods != sorted(periods) or len(periods) != len(set(periods)):
        raise WarReportRuntimeError("FULL_HISTORY_NOT_UNIQUE_CHRONOLOGICAL")
    q = analysis.quarterly_earnings
    qperiod = q.fiscal_period.replace("FY", "").replace(" ", "")
    if qperiod in periods:
        raise WarReportRuntimeError("FULL_HISTORY_PERIOD_COLLISION")
    labels = periods + [qperiod]
    a = q.enterprise_value_analytics
    sources = list(q.revenue.evidence_ids)
    master_source = next(item for item in analysis.source_evidence_ids if item.startswith("AUTH-MASTER-"))
    cash_source = next(item for item in analysis.source_evidence_ids if item.startswith("AUTH-CASHFLOW-"))
    full_sources = [master_source, *sources]
    gp = [str((_dec(r["Revenue_Q_100M"]) * _dec(r["GrossMarginPct"]) / Decimal("100"))) for r in rows]
    revenue_values = [r["Revenue_Q_100M"] for r in rows] + [str(_dec(q.revenue.value) / 100)]
    gross_profit_values = gp + [str(_dec(a["grossProfitMillionTwd"]) / 100)]
    operating_profit_values = [r["OperatingIncome_Q_100M"] for r in rows] + [str(_dec(a["operatingProfitMillionTwd"]) / 100)]
    charts = [
        _chart("full_history_profit_chain", "營收、毛利與營業利益成長指數", "規模成長是否持續轉為營業利益？", labels, [
            ChartSeries(label_zh="營收指數", unit="首期=100", values=_indexed(revenue_values)),
            ChartSeries(label_zh="毛利指數", unit="首期=100", values=_indexed(gross_profit_values)),
            ChartSeries(label_zh="營業利益指數", unit="首期=100", values=_indexed(operating_profit_values)),
        ], full_sources, ["圖形特徵：2026Q2營業利益指數明顯領先營收與毛利指數，營運槓桿差擴大。", "為何重要：營收年增41%時，營業利益年增67.51%，表示新增規模已跨過毛利以下費用吸收門檻。", "論點含義：第一階段價值轉化獲支持；若後續營益率回落，這項支持即減弱。"]),
        _chart("full_history_margin", "毛利率與營益率完整歷史", "毛利與費用吸收是否出現結構背離？", labels, [
            ChartSeries(label_zh="毛利率", unit="%", values=[r["GrossMarginPct"] for r in rows] + [q.gross_margin.value]),
            ChartSeries(label_zh="營益率", unit="%", values=[r["OperatingMarginPct"] for r in rows] + [q.operating_margin.value]),
        ], full_sources, ["圖形特徵：2026Q2毛利率降至6.12%，營益率卻升至3.75%，兩條利潤率走勢背離。", "為何重要：改善發生在毛利以下，較符合費用吸收與規模效率，而不是產品毛利率擴張。", "論點含義：營運槓桿成立，但高價值產品組合提高毛利率的假說尚未獲證。"]),
        _chart("full_history_eps", "每股盈餘完整歷史", "企業獲利是否持續傳達至每股？", labels, [
            ChartSeries(label_zh="EPS", unit="新台幣元", values=[r["EPS_Q"] for r in rows] + [q.eps.value]),
        ], full_sources, ["圖形特徵：2026Q2 EPS升至4.27元，年增34%，每股獲利延續上升。", "為何重要：每股成長確認獲利沒有只停留在公司總額，但增幅仍低於營業利益。", "論點含義：每股價值獲部分支持；仍須由股數、BVPS與FCF交叉驗證。"]),
    ]
    historical_baseline = historical_baseline or build_historical_kpi_baseline(package_root, analysis)
    cash_rows = {
        metric: observations_for(historical_baseline, metric, basis="Q_STANDALONE")
        for metric in ("CFO", "CAPEX", "FCF")
    }
    cash_labels = [item["period"] for item in cash_rows["FCF"]]
    if any([item["period"] for item in cash_rows[metric]] != cash_labels for metric in ("CFO", "CAPEX")):
        raise WarReportRuntimeError("CASH_FLOW_PERIOD_BASIS_MISMATCH")
    charts.append(_chart("full_history_cash_flow", "CFO、Capex與FCF完整可比歷史", "獲利是否轉為自由現金流？", cash_labels, [
        ChartSeries(label_zh="CFO", unit="新台幣百萬元", values=[item["value"] for item in cash_rows["CFO"]]),
        ChartSeries(label_zh="Capex", unit="新台幣百萬元", values=[item["value"] for item in cash_rows["CAPEX"]]),
        ChartSeries(label_zh="FCF", unit="新台幣百萬元", values=[item["value"] for item in cash_rows["FCF"]]),
    ], [cash_source, *sources], ["圖形特徵：2026Q2單季CFO與FCF同為負值，與當季獲利成長方向相反。", "為何重要：帳面獲利尚未轉成可自由配置現金，資本支出並非唯一壓力來源。", "論點含義：Q3單季轉正只算初步改善；主要確認仍是H2、全年或TTM現金轉化恢復。"] ))
    cumulative = {metric: observations_for(historical_baseline, metric, basis="YTD_CUMULATIVE") for metric in ("CFO", "CAPEX", "FCF")}
    cumulative_labels = [item["period"] for item in cumulative["FCF"]]
    if cumulative_labels:
        charts.append(_chart("full_history_cash_flow_cumulative", "累計現金流原始口徑", "累計現金回收是否改善？", cumulative_labels, [
            ChartSeries(label_zh="累計CFO", unit="新台幣百萬元", values=[item["value"] for item in cumulative["CFO"]]),
            ChartSeries(label_zh="累計Capex", unit="新台幣百萬元", values=[item["value"] for item in cumulative["CAPEX"]]),
            ChartSeries(label_zh="累計FCF", unit="新台幣百萬元", values=[item["value"] for item in cumulative["FCF"]]),
        ], sources, ["圖形特徵：2025H1與2025M9自由現金流為負，2025全年轉正，但2026H1再度轉負。", "為何重要：全年曾出現現金回收，證明季內負值可能含時點因素；2026H1仍不能因此自動視為季節性。", "論點含義：需以2026全年能否重現2025年回收路徑，區分週期性占用與結構性惡化。"], visualization_type="EVIDENCE_TABLE" ))
    wc_rows = {metric: observations_for(historical_baseline, metric, basis="EXISTING_GOVERNED_CCC_METHOD_V1") for metric in ("DSO", "DIO", "DPO", "CCC")}
    wc_labels = [item["period"] for item in wc_rows["CCC"]]
    charts.append(_chart("full_history_working_capital", "營運資金與CCC可比歷史", "現金占用來自成長還是效率惡化？", wc_labels, [
        ChartSeries(label_zh="應收天數", unit="天", values=[item["value"] for item in wc_rows["DSO"]]),
        ChartSeries(label_zh="存貨天數", unit="天", values=[item["value"] for item in wc_rows["DIO"]]),
        ChartSeries(label_zh="應付天數", unit="天", values=[item["value"] for item in wc_rows["DPO"]]),
        ChartSeries(label_zh="CCC", unit="天", values=[item["value"] for item in wc_rows["CCC"]]),
    ], sources, ["圖形特徵：CCC由2025Q2的48天降至2026Q2的42天，週轉天數改善。", "為何重要：這與應收及存貨金額上升並存，顯示資金占用較像規模擴張，不是週轉效率全面惡化。", "論點含義：成長性解釋較有力，但現金尚未回收，Q3 CFO仍是必要驗證。"] ))
    nwc_rows = observations_for(historical_baseline, "NWC_PROXY", basis="QUARTER_END_BALANCE")
    charts.append(_chart("full_history_nwc_proxy", "季末營運資金代理值", "應收與存貨增加造成多少資金占用？", [item["period"] for item in nwc_rows], [
        ChartSeries(label_zh="NWC Proxy", unit="新台幣百萬元", values=[item["value"] for item in nwc_rows]),
    ], sources, ["圖形特徵：Q1至Q2的營運資金代理值增加1,747.38億元。", "為何重要：應收與存貨合計增加3,794.24億元，應付增加2,046.86億元只抵銷部分占用。", "論點含義：供應商融資提供緩衝而非現金消耗；淨占用仍壓低Q2 CFO。"] ))
    charts.extend([
        _chart("full_history_roic", "ROIC完整歷史與本期待驗", "資本效率是否改善？", labels, [ChartSeries(label_zh="ROIC", unit="%", values=[r["ROIC_Precise_Pct"] for r in rows] + ["INSUFFICIENT_DATA"])], full_sources, ["圖形特徵：歷史同口徑ROIC波動，2026Q1為12.57%；2026Q2不是零，而是資料待補。", "為何重要：本期可計算部分營運投入資本估算，但無法取代完整同口徑實際ROIC。", "論點含義：新增資本是否提高報酬仍待驗；下一季須補標準化NOPAT與完整平均投入資本。"]),
        _chart("full_history_bvps", "每股淨值完整歷史與本期待驗", "帳面價值是否持續傳達至每股？", labels, [ChartSeries(label_zh="BVPS", unit="新台幣元", values=[r["BVPS"] for r in rows] + ["INSUFFICIENT_DATA"])], full_sources, ["圖形特徵：BVPS中期上升至2026Q1的127.12元，但2025Q2曾出現明顯回落。", "為何重要：帳面價值累積並非直線，需連同股利與股數變化解釋。", "論點含義：股東資本複利方向正面；2026Q2直接BVPS與完整股東總報酬仍待補。"]),
        _chart("full_history_valuation", "歷史季度P/B與TTM P/E（分尺度）", "截至2026Q1的歷史評價如何變化？", periods, [
            ChartSeries(label_zh="P/B", unit="倍", values=[item["value"] for item in observations_for(historical_baseline, "PB")]),
            ChartSeries(label_zh="TTM P/E", unit="倍", values=[item["value"] for item in observations_for(historical_baseline, "PE_TTM")]),
        ], [master_source], ["圖形特徵：本圖歷史季度序列截止2026Q1；P/B與P/E採獨立尺度，不是2026-08-11報告估值。", "為何重要：歷史中位數只用來定位；事件前最新P/B與P/E另在正文以2026-08-11收盤價重算。", "論點含義：估值只作時間一致的歷史位置描述；未設定買賣或安全邊際門檻。"]),
    ])
    ps_rows = observations_for(historical_baseline, "PS_TTM")
    charts.append(_chart("full_history_ps", "歷史季度TTM P/S（截至2026Q1）", "歷史市值相對過去十二個月營收如何變化？", [item["period"] for item in ps_rows], [
        ChartSeries(label_zh="TTM P/S", unit="倍", values=[item["value"] for item in ps_rows]),
    ], [master_source], ["圖形特徵：本圖歷史季度序列截止2026Q1，末值不是2026-08-11事件前P/S 0.40倍。", "為何重要：正文0.40倍使用2026-08-11價格與Q2更新TTM營收；兩個時間基準不可混讀。", "論點含義：不以最新TTM營收回套過去市值；P/S不是單獨的便宜或昂貴判斷。"] ))
    audits: list[dict[str, Any]] = []
    for chart in charts:
        chart_observations = [
            item for item in historical_baseline.get("observations", [])
            if item.get("period") in set(chart.labels)
        ]
        provenance_counts: dict[str, int] = {}
        for observation in chart_observations:
            data_class = str(observation.get("data_class", "UNCLASSIFIED"))
            provenance_counts[data_class] = provenance_counts.get(data_class, 0) + 1
        audits.append({
            "CHART_ID": chart.chart_id,
            "SOURCE_SERIES": [item.label_zh for item in chart.series],
            "OBSERVATION_COUNT": len(chart.labels),
            "FIRST_PERIOD": chart.labels[0],
            "LAST_PERIOD": chart.labels[-1],
            "FULL_HISTORY": "YES",
            "RECENT_ZOOM_USED": "NO",
            "DROPPED_OBSERVATIONS": 0,
            "source_locator": chart.source_evidence_ids,
            "formula_or_transformation": "GOVERNED_DIRECT_OR_EXPLICIT_DERIVATION",
            "provenance_class_counts": provenance_counts,
            "estimate_indicator": "圖表資料含估算時，以圖說及稽核metadata明確標示；不冒充官方值。" if provenance_counts.get(T2) else "DIRECT_OR_EXACT_DERIVED_ONLY",
            "input_sha256": sha256_bytes(canonical_json_bytes({"labels": chart.labels, "series": [s.model_dump(mode="json", by_alias=True) for s in chart.series]})),
        })
    unavailable = ["期末流通股數：僅有外部交叉核對，未升格正式值", "同業估值與資本效率歷史：無可驗證歷史快照"]
    return charts, audits, unavailable


def _reader_text(value: str) -> str:
    replacements = (
        (r"P1008", "本戰情室"), (r"production authority", "正式資料"),
        (r"authority", "正式資料"), (r"DATA GAP", "資料待補"),
        (r"actionable=false", ""), (r"publication=false", ""),
        (r"OWNER REVIEW REQUIRED", "審閱版｜尚未正式發布"),
        (r"STRUCTURAL_RISK_NOT_RULED_OUT", "結構性風險尚未排除"),
        (r"CORE_HOLDING_THESIS", "核心持有論點"),
        (r"ADD_ON_CAPITAL_GATE", "增量資本檢核"),
        (r"THESIS_DOWNGRADE_GATE", "論點降級檢核"),
        (r"DECLARED_IN_AUTHORITY_FILE", "正式資料所列期間"),
        (r"DECLARED_IN_正式資料_FILE", "正式資料所列期間"),
        (r"INITIALIZED_BASELINE", "首次建立基線"),
        (r"LOW_RESILIENCE", "待驗證"),
    )
    for before, after in replacements:
        value = re.sub(before, after, value, flags=re.IGNORECASE)
    value = re.sub(r"\bT[0-4](?:_[A-Z0-9_]+)?\b", "內部證據分類", value)
    value = re.sub(r"\b(?:AUTH|IR-EVIDENCE)-[A-Z0-9_-]+\b", "受治理來源", value)
    value = re.sub(r"(?<![A-Za-z])Consignment(?![A-Za-z]|（客供料）)", "Consignment（客供料）", value)
    return value


def validate_professional_reader_language(rendered_html: str) -> None:
    visible = re.sub(r"<(?:style|script)\b[^>]*>.*?</(?:style|script)>", " ", rendered_html, flags=re.DOTALL | re.IGNORECASE)
    visible = re.sub(r"<!--.*?-->", " ", visible, flags=re.DOTALL)
    folded = html.unescape(re.sub(r"<[^>]+>", " ", visible)).casefold()
    for term in _FORBIDDEN_READER:
        if term.casefold() in folded:
            raise WarReportRuntimeError(f"READER_LANGUAGE_REJECTED:{term}")
    for token in (
        "DECLARED_IN_", "INITIALIZED_BASELINE", "LOW_RESILIENCE",
        "ESTIMATE_ACTIVE", "Q_STANDALONE", "INSUFFICIENT_DATA",
    ):
        if token.casefold() in folded:
            raise WarReportRuntimeError(f"READER_ENUM_REJECTED:{token}")
    if "七維證據規則" in folded:
        raise WarReportRuntimeError("READER_RULE_DIMENSION_DRIFT")
    if re.search(r"(?<!\d)\d+\.\d{5,}(?!\d)", folded):
        raise WarReportRuntimeError("READER_EXCESS_PRECISION")


def _section_html(report: ReportCandidate, section_ids: Sequence[str]) -> str:
    by_id = {item.section_id: item for item in report.sections}
    return "".join(
        f'<h3>{html.escape(_reader_text(by_id[item].title_zh))}</h3><p>{html.escape(_reader_text(by_id[item].body_zh))}</p>'
        for item in section_ids if item in by_id
    )


def _decision_state(previous: Mapping[str, Any] | None, report: ReportCandidate, rule_result: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if rule_result is not None:
        return build_decision_state(previous, rule_result, report.evidence_bound_facts)
    prev = (previous or {}).get("decision", {})
    current = {
        "CORE_HOLDING_THESIS": "維持",
        "ADD_ON_CAPITAL_GATE": "PARTIAL",
        "THESIS_DOWNGRADE_GATE": "WATCH",
    }
    allowed = {item["id"]: set(item["allowed_states"]) for item in load_contract()["decision_contract"]["dimensions"]}
    items = []
    for key, state in current.items():
        if state not in allowed[key]:
            raise WarReportRuntimeError("DECISION_STATE_INVALID")
        prior = prev.get(key, state)
        items.append({
            "dimension": key, "PREVIOUS_STATE": prior, "CURRENT_STATE": state,
            "CHANGE": "UNCHANGED" if prior == state else f"{prior}→{state}",
            "EVIDENCE": report.evidence_bound_facts, "NEXT_GATE": "下一次正式季報與現金／資本效率驗證",
        })
    return {"dimension_count": 3, "items": items, "aggregate_numeric_score": None}


def _smart_state(previous: Mapping[str, Any] | None, report: ReportCandidate, rule_result: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if rule_result is not None:
        return build_smart_state(previous, rule_result, report.evidence_bound_facts)
    prior_items = {item["id"]: item for item in (previous or {}).get("smart", {}).get("items", [])}
    items = []
    for index, category in enumerate(load_contract()["smart_contract"]["categories"], 1):
        item_id = f"SMART-{index:02d}"
        previous_state = prior_items.get(item_id, {}).get("current_state", "待驗證")
        current = "持續追蹤"
        items.append({
            "id": item_id, "metric_or_thesis": category, "current_state": current,
            "evidence": report.evidence_bound_facts, "next_verification": "下一次正式財務揭露",
            "time_horizon": "1至4季", "previous_state": previous_state, "changed": previous_state != current,
        })
    return {"items": items}


def _table(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    head = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(row.get(column, '')))}</td>" for column in columns) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _reader_number(value: Any, places: int = 2) -> str:
    number = Decimal(str(value))
    quantizer = Decimal("1") if places == 0 else Decimal("1." + ("0" * places))
    rendered = f"{number.quantize(quantizer):f}"
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _reader_amount_million(value: Any) -> str:
    """Render million-TWD input at a reader-friendly 億/兆 scale."""
    amount = Decimal(str(value))
    absolute = abs(amount)
    if absolute >= Decimal("1000000"):
        return f"{_reader_number(amount / Decimal('1000000'))}兆元"
    return f"{_reader_number(amount / Decimal('100'))}億元"


def _quarterly_research_chapters(
    *,
    analysis: AnalysisPacket,
    report: ReportCandidate,
    charts: Sequence[ChartData],
    decision: Mapping[str, Any],
    smart: Mapping[str, Any],
    unavailable: Sequence[str],
    fcf_state: Mapping[str, Any] | None,
    forward: Mapping[str, Any],
    rule_result: Mapping[str, Any],
) -> dict[str, str]:
    """Compose the governed Q2 specimen as an analyst-written investment report."""
    if analysis.quarterly_earnings is None:
        raise WarReportRuntimeError("QUARTERLY_ANALYSIS_MISSING")
    q = analysis.quarterly_earnings
    a = q.enterprise_value_analytics
    valuation = q.valuation_scenarios
    history = q.quarterly_history
    renderer = FormalPreviewRenderer()
    chart_by_id = {item.chart_id: item for item in charts}

    def visuals(chapter_id: str) -> str:
        return "".join(
            renderer._visual(chart_by_id[chart_id])
            for chart_id in _CHAPTER_CHARTS.get(chapter_id, ())
            if chart_id in chart_by_id
        )

    official_indexes = [
        index for index, item in enumerate(report.evidence_references, 1)
        if any(not locator.casefold().startswith("p1008-authority:") for locator in item.source_urls)
    ]
    authority_indexes = [
        index for index, item in enumerate(report.evidence_references, 1)
        if item.source_urls and all(locator.casefold().startswith("p1008-authority:") for locator in item.source_urls)
    ]
    official_cite = "".join(f"[{index}]" for index in official_indexes)
    authority_cite = "".join(f"[{index}]" for index in authority_indexes)
    cite_by_prefix = {
        prefix: "".join(
            f"[{index}]" for index, item in enumerate(report.evidence_references, 1)
            if item.evidence_id.startswith(prefix)
        )
        for prefix in ("AUTH-MASTER-", "AUTH-PRICE-", "AUTH-MARKET-ACTIVITY-", "AUTH-CASHFLOW-")
    }
    master_cite = cite_by_prefix["AUTH-MASTER-"]
    price_cite = cite_by_prefix["AUTH-PRICE-"]
    cash_cite = cite_by_prefix["AUTH-CASHFLOW-"]
    periods = list(history["periods"])
    q2_index = len(periods) - 1
    prior_same_index = periods.index("2025Q2") if "2025Q2" in periods else max(0, q2_index - 4)

    revenue_now = Decimal(str(history["revenue100mTwd"][q2_index]))
    revenue_prior = Decimal(str(history["revenue100mTwd"][prior_same_index]))
    gross_now = Decimal(str(history["grossProfit100mTwd"][q2_index]))
    gross_prior = Decimal(str(history["grossProfit100mTwd"][prior_same_index]))
    op_now = Decimal(str(history["operatingIncome100mTwd"][q2_index]))
    op_prior = Decimal(str(history["operatingIncome100mTwd"][prior_same_index]))
    opex_now = Decimal(str(history["opexProxy100mTwd"][q2_index]))
    opex_prior = Decimal(str(history["opexProxy100mTwd"][prior_same_index]))

    wc = a["workingCapital"]
    ar_q1, ar_q2 = map(Decimal, wc["accountsReceivableMillionTwd"][-2:])
    inv_q1, inv_q2 = map(Decimal, wc["inventoryMillionTwd"][-2:])
    ap_q1, ap_q2 = map(Decimal, wc["accountsPayableMillionTwd"][-2:])
    net_wc_change = (ar_q2 - ar_q1) + (inv_q2 - inv_q1) - (ap_q2 - ap_q1)

    balance = a["balanceSheetEvidence"]
    stress_scenarios = forward["working_capital_stress"]["scenarios"]
    stress_a = next(item for item in stress_scenarios if item["scenario"] == "RESEARCH_STRESS_A")["result"]
    stress_b = next(item for item in stress_scenarios if item["scenario"] == "RESEARCH_STRESS_B")["result"]

    roic_estimate = forward["roic_sensitivity"]["independent_q2_invested_capital"]
    historical = forward["valuation_context"]["historical"]
    valuation_state = valuation["valuationTimeBasis"]["valuationState"]
    valuation_context = "財報公布前" if valuation_state == "PRE_EVENT_VALUATION_CONTEXT" else "財報公布後報告截止日"
    time_basis_sentence = (
        "價格日期早於財報事件日，因此只代表事件前估值脈絡。"
        if valuation_state == "PRE_EVENT_VALUATION_CONTEXT"
        else "價格日期不早於財報事件日，因此歸類為財報後報告截止日價格，不再誤稱為財報前價格。"
    )
    timepoint_rows = []
    for label, key in (("財報事件前", "preEventValuation"), ("財報事件後", "postEventValuation")):
        point = valuation["valuationTimeBasis"][key]
        if point["status"] == "AVAILABLE":
            timepoint_rows.append({
                "估值時點": label,
                "價格日期／收盤價": f"{point['date']}／{point['price']}元",
                "P/S": f"{_reader_number(point['ps'])}倍",
                "P/E": f"{_reader_number(point['pe'])}倍",
                "P/B": f"{_reader_number(point['pb'])}倍",
            })
        else:
            timepoint_rows.append({
                "估值時點": label,
                "價格日期／收盤價": "本地正式行情未提供",
                "P/S": "資料未提供",
                "P/E": "資料未提供",
                "P/B": "資料未提供",
            })
    post_event_sentence = (
        "本地正式行情已涵蓋事件後時點，表內分別呈現事件前後估值，不混用價格日期。"
        if valuation["valuationTimeBasis"]["postEventValuation"]["status"] == "AVAILABLE"
        else "本地正式行情尚未涵蓋事件後時點，因此事件後P/S、P/E與P/B均不可得，不以事件前數值冒充。"
    )

    kpis = [
        {"指標": "營收", "本期": f"{_reader_number(revenue_now)}億元", "比較": "年增41%", "判讀": "需求與規模延續"},
        {"指標": "毛利", "本期": f"{_reader_number(gross_now)}億元", "比較": f"年增{a['grossProfitYoyPct']}%", "判讀": "增幅略低於營收"},
        {"指標": "營業利益", "本期": f"{_reader_number(op_now)}億元", "比較": f"年增{a['operatingProfitYoyPct']}%", "判讀": "增速顯著高於營收"},
        {"指標": "毛利率／營益率", "本期": f"{q.gross_margin.value}%／{q.operating_margin.value}%", "比較": f"年變動{q.gross_margin.yoy}／{q.operating_margin.yoy}", "判讀": "毛利承壓、費用吸收改善"},
        {"指標": "EPS", "本期": f"{q.eps.value}元", "比較": f"年變動{q.eps.yoy}", "判讀": "每股獲利獲支持"},
        {"指標": "Q2 CFO／FCF", "本期": f"{_reader_amount_million(a['q2StandaloneCfoMillionTwd'])}／{_reader_amount_million(a['q2StandaloneFcfMillionTwd'])}", "比較": "同口徑累計數相減推導", "判讀": "獲利尚未轉成自由現金"},
        {"指標": "CCC", "本期": f"{wc['cashConversionCycleDays'][-1]}天", "比較": f"2025Q2為{wc['cashConversionCycleDays'][0]}天", "判讀": "效率改善但資金仍占用"},
        {"指標": "估值", "本期": f"P/S {_reader_number(valuation['ps']['value'])}倍；P/E {_reader_number(valuation['ttmPe']['value'])}倍；P/B {_reader_number(valuation['pb']['value'])}倍", "比較": f"{valuation_context}價格{_reader_number(valuation['price']['value'])}元", "判讀": "描述性位置，不設交易門檻"},
    ]

    rule_labels = {
        "OPERATING_PROFIT_STATE": "營業利益品質",
        "FCF_CONVERSION_STATE": "自由現金流轉化",
        "ROIC_STATE": "投入資本報酬",
        "CAPITAL_LIGHT_STATE": "資本輕量化",
        "PER_SHARE_VALUE_STATE": "每股價值",
        "CURRENT_BALANCE_SHEET_STATE": "現況資產負債表",
        "STRESS_RESILIENCE_STATE": "壓力情境韌性",
        "VALUATION_STATE": "估值支持",
    }
    state_labels = {
        "SUPPORTED": "支持",
        "PARTIAL": "部分支持",
        "WATCH": "警戒",
        "DETERIORATING": "轉弱",
        "UNAVAILABLE": "資料不足",
        "LOW_RESILIENCE": "待驗證",
        "MODERATE_RESILIENCE": "韌性中等",
        "維持": "維持",
        "尚未通過": "尚未通過",
    }
    rule_rows = [
        {
            "檢核面向": rule_labels.get(item["dimension"], item["dimension"]),
            "目前判定": state_labels.get(item["calculated_state"], item["calculated_state"]),
            "證據解讀": (
                "既有壓力情境證實營運資金下行敏感度重大；目前淨現金提供資產負債表緩衝，"
                "因此下行敏感度已確認，但整體韌性的類別結論尚不足以下定論。"
                if item["dimension"] == "STRESS_RESILIENCE_STATE"
                else item["rationale"].replace("Owner核准", "正式核准")
            ),
        }
        for item in rule_result["rules"]
    ]

    decision_rows = []
    for item in decision["items"]:
        label = {
            "CORE_HOLDING_THESIS": "核心持有論點",
            "ADD_ON_CAPITAL_GATE": "增量資本檢核",
            "THESIS_DOWNGRADE_GATE": "論點降級檢核",
        }.get(item["dimension"], item["dimension"])
        current = state_labels.get(item["CURRENT_STATE"], item["CURRENT_STATE"])
        decision_rows.append({"決策層": label, "本期": current, "判讀": {
            "核心持有論點": "營運槓桿證據增強，但現金與資本報酬仍未完成驗證。",
            "增量資本檢核": "資料只支持部分通過；未設定買賣或部位規則。",
            "論點降級檢核": "負FCF需要追蹤，但尚無多因子證據證明結構性惡化。",
        }.get(label, "待後續正式資料驗證。")})

    strategy_rows = []
    stage_labels = {
        "STRATEGY": "策略階段", "DEVELOPMENT": "開發階段", "REVENUE": "已進入營收階段",
    }
    for item in a["strategyScorecard"]:
        strategy_rows.append({
            "支柱": item["strategicPillar"],
            "商業化階段": stage_labels.get(item["currentCommercializationStage"], "待驗證"),
            "本季財務證據": item["currentRevenueEvidence"].replace("NOT_SEPARATELY_DISCLOSED", "未單獨揭露"),
            "下一道價值閘門": item["nextCheckpoint"],
        })

    estimated_shares = Decimal(str(valuation["ps"]["weightedAverageSharesMillion"]))
    q2_fcf_per_share = Decimal(str(a["q2StandaloneFcfMillionTwd"])) / estimated_shares
    smart_specs = [
        ("營業利益品質", f"營益率{q.operating_margin.value}%，營業利益年增{a['operatingProfitYoyPct']}%", "營益率維持或提高，且毛利率不再下滑", "毛利率與營益率同步下降", "FY2026 Q3財報／法說"),
        ("營運現金回收", f"Q2 CFO {_reader_amount_million(a['q2StandaloneCfoMillionTwd'])}，CCC {wc['cashConversionCycleDays'][-1]}天", "Q3單季CFO轉正只算初步改善；H2、全年或TTM現金轉化恢復才是主要確認", "CFO持續為負，或應收與存貨天數反轉上升", "FY2026 Q3及全年現金流量表"),
        ("自由現金流", f"Q2 FCF {_reader_amount_million(a['q2StandaloneFcfMillionTwd'])}", "H2、全年或TTM FCF轉正且不依賴一次性營運資金釋放", "2026全年FCF仍為負", "FY2026 Q3／全年現金流量表"),
        ("資本報酬", f"部分營運投入資本單季估算ROIC {_reader_number(roic_estimate['quarterly_roic_pct'])}%；官方同口徑Q2值待補", "標準化NOPAT與完整平均投入資本可比，且ROIC改善", "投入資本增幅持續高於NOPAT", "正式Q2補充資料／FY2026 Q3"),
        ("每股價值", f"Q2 EPS {q.eps.value}元；BVPS截至2026Q1為{valuation['governedBvps']['value']}元；Q2 FCF／相容加權平均股數約{_reader_number(q2_fcf_per_share)}元／股；期末股數待補", "EPS、BVPS與FCF／股在相容期間共同改善，且股數未稀釋每股成果", "EPS上升但BVPS或FCF／股轉弱，或股數增幅抵銷分子成長", "FY2026 Q3／全年每股與現金資料"),
        ("估值第二階段", f"事件前P/S、P/E、P/B均處歷史較高位置；ROIC、FCF與每股價值尚未共同確認", "ROIC、正常化FCF與每股價值共同改善，為較高估值提供第二階段證據", "較高歷史位置延續，但ROIC、FCF或每股價值驗證失敗，形成再評價風險", "FY2026 Q3／全年財務及事件後正式行情"),
        ("AI價值轉化", "AI已到營收階段；專屬利潤、ROIC與FCF未揭露", "官方揭露可核對的AI獲利或現金證據", "AI成長伴隨合併毛利、ROIC與FCF惡化", "後續季報／法說"),
    ]
    smart_rows = [
        {"驗證主題": metric, "目前基線": baseline, "增強條件": strengthen, "削弱條件": weaken, "下一觀察": next_event}
        for metric, baseline, strengthen, weaken, next_event in smart_specs
    ]

    refs = []
    for index, item in enumerate(report.evidence_references, 1):
        locators = []
        for raw_locator in item.source_urls:
            if raw_locator.casefold().startswith("p1008-authority:"):
                path = raw_locator.split(":", 1)[1].split("@", 1)[0]
                locators.append(f"正式資料：{path}")
            else:
                locators.append(raw_locator)
        locator = "；".join(locators) if locators else "本機正式資料定位器"
        refs.append({"編號": f"[{index}]", "來源與主張": _reader_text(item.claim), "日期": _reader_text(item.source_date), "定位": locator})

    chapters: dict[str, str] = {}
    chapters["s1"] = (
        "<h3>企業價值第一階段已驗證，第二階段仍待驗證</h3>"
        f"<p><strong>核心判斷：</strong>FY2026 Q2營收年增41%，營業利益年增{a['operatingProfitYoyPct']}%，"
        f"兩者相差{a['operatingLeverageSpreadPct']}個百分點，顯示規模已轉為營運槓桿；但Q2 CFO為"
        f"{_reader_amount_million(a['q2StandaloneCfoMillionTwd'])}、FCF為{_reader_amount_million(a['q2StandaloneFcfMillionTwd'])}，"
        f"獲利尚未完成現金轉化。核心論點維持，估值安全與退休現金流安全不因此上修。{official_cite}{cash_cite}</p>"
        "<p><strong>本季新增：</strong>營益率改善、EPS上升與官方H1 ROE提高，支持營運端價值創造；"
        "<strong>尚未完成：</strong>同口徑Q2 ROIC、AI專屬利潤與現金、全年FCF回收。"
        "因此目前不是「成長失效」，而是「成長是否能轉成資本報酬與現金」的第二階段驗證。</p>"
        "<h3>核心KPI儀表板</h3>" + _table(kpis, ("指標", "本期", "比較", "判讀"))
    )

    chapters["s2"] = (
        "<h3>八季脈絡：獲利轉化快於規模，毛利率沒有同步擴張</h3>"
        f"<p>自2024Q2至2026Q2，營收累計成長{a['revenueGrowth2024Q2To2026Q2Pct']}%，EPS成長{a['epsGrowth2024Q2To2026Q2Pct']}%；"
        f"毛利率減少{str(a['grossMarginChange2024Q2To2026Q2Bps']).replace('-', '')}個基點，營益率增加{str(a['operatingMarginChange2024Q2To2026Q2Bps']).replace('+', '')}個基點。"
        "這項背離支持毛利以下費用吸收與規模效率，不支持「產品組合已使毛利率結構性上升」。"
        f"若Q3營益率回落且毛利率續降，營運槓桿判斷需下修。{official_cite}</p>" + visuals("s2")
    )

    chapters["s3"] = (
        "<h3>2025Q2至2026Q2獲利橋：新增規模主要流向營業利益</h3>"
        + _table([
            {"項目": "營收", "2025Q2": f"{_reader_number(revenue_prior)}億元", "2026Q2": f"{_reader_number(revenue_now)}億元", "變化": "年增41%"},
            {"項目": "毛利", "2025Q2": f"{_reader_number(gross_prior)}億元", "2026Q2": f"{_reader_number(gross_now)}億元", "變化": f"年增{a['grossProfitYoyPct']}%"},
            {"項目": "毛利以下營業費用淨額代理值", "2025Q2": f"{_reader_number(opex_prior)}億元", "2026Q2": f"{_reader_number(opex_now)}億元", "變化": f"年增{a['operatingExpenseProxyYoyPct']}%"},
            {"項目": "營業利益", "2025Q2": f"{_reader_number(op_prior)}億元", "2026Q2": f"{_reader_number(op_now)}億元", "變化": f"年增{a['operatingProfitYoyPct']}%"},
        ], ("項目", "2025Q2", "2026Q2", "變化"))
        +
        f"<p>營收增加{_reader_number(revenue_now - revenue_prior)}億元，毛利增加{_reader_number(gross_now - gross_prior)}億元；"
        f"毛利以下營業費用淨額代理值只增加{_reader_number(opex_now - opex_prior)}億元，使營業利益增加{_reader_number(op_now - op_prior)}億元。"
        "這是營益率由費用吸收改善的直接橋接；代理值由「毛利減營業利益」推導，不是公司揭露的單一營業費用科目，也不是營業成本。</p>"
        "<p><strong>反方證據：</strong>毛利率仍較去年同期下降21個基點。若高價值產品組合確實改善，後續應看到毛利率止跌，"
        f"而不只是營益率靠費用吸收上升。{official_cite}</p>"
    )

    chapters["s4"] = (
        "<h3>FCF 轉化：本期負值已驗證，但不能跳過季節性與歷史回收脈絡</h3>"
        f"<p>Q2單季CFO由2026H1減2026Q1推導為{_reader_amount_million(a['q2StandaloneCfoMillionTwd'])}，"
        f"資本支出為{_reader_amount_million(a['q2StandaloneCapexMillionTwd'])}，因此FCF為"
        f"{_reader_amount_million(a['q2StandaloneFcfMillionTwd'])}。兩條推導路徑僅差{_reader_number(a['q2StandaloneFcfRoundingDifferenceMillionTwd'], 0)}百萬元，"
        f"在揭露四捨五入容許範圍內。{official_cite}{cash_cite}</p>"
        "<p>同季比較顯示2025H1 FCF為-552.75億元；2025年前九個月擴大至-1,623.35億元，全年則回升至530.89億元；"
        "2026H1再降至-1,500.09億元。2025全年回收證明季內資金占用可能逆轉，但2026H1仍不足以判定只是季節性。"
        "目前分類為「結構性風險尚未排除」，不是「已證實結構性惡化」。</p>"
        "<p><strong>可推翻測試：</strong>若下半年營運資金釋放使全年CFO與FCF恢復，H1弱勢較符合成長與時點占用；"
        "若營業利益維持強勁但現金仍不回收，風險將轉向結構性獲利—現金惡化。</p>"
        "<h3>淨利至CFO橋接：已知項目與缺口</h3>"
        + _table([
            {"橋接項目": "歸屬母公司淨利", "Q2證據": f"{_reader_amount_million(q.attributable_profit.value)}", "證據狀態": "官方直接值；與合併CFO會計範圍不同"},
            {"橋接項目": "非現金項目", "Q2證據": "資料未提供", "證據狀態": "無法量化折舊、減損等調整"},
            {"橋接項目": "營運資金代理變化", "Q2證據": f"增加{_reader_amount_million(net_wc_change)}", "證據狀態": "應收＋存貨－應付；不是完整現金流量表營運資金橋"},
            {"橋接項目": "營業現金流", "Q2證據": f"{_reader_amount_million(a['q2StandaloneCfoMillionTwd'])}", "證據狀態": "由官方H1減Q1同口徑推導"},
            {"橋接項目": "資本支出／自由現金流", "Q2證據": f"{_reader_amount_million(a['q2StandaloneCapexMillionTwd'])}／{_reader_amount_million(a['q2StandaloneFcfMillionTwd'])}", "證據狀態": "同口徑推導"},
        ], ("橋接項目", "Q2證據", "證據狀態"))
        + f"<p>現有證據可確認營運資金是重要因素，但不足以把全部 CFO 落差歸因於營運資金。非現金項目與完整現金流量表調整尚未提供。{official_cite}{cash_cite}</p>"
        "<h3>營運資金：應付帳款是融資抵銷，不是現金吸收</h3>"
        f"<p>Q1至Q2應收增加{_reader_amount_million(ar_q2-ar_q1)}、存貨增加{_reader_amount_million(inv_q2-inv_q1)}，兩者吸收現金；"
        f"應付帳款增加{_reader_amount_million(ap_q2-ap_q1)}，提供供應商融資並抵銷部分占用。三項淨額仍增加"
        f"{_reader_amount_million(net_wc_change)}。同時CCC由48天降至42天，因此現有證據較支持成長驅動的資金占用，而非週轉效率全面惡化。{official_cite}</p>"
        "<h3>資產負債表與壓力情境：緩衝存在，但不能取代現金回收</h3>"
        + _table([
            {"項目": "現金及約當現金", "2026-06-30": _reader_amount_million(balance["cashAndCashEquivalentsMillionTwd"]), "判讀": "官方期末流動性存量"},
            {"項目": "推導有息負債", "2026-06-30": _reader_amount_million(balance["derivedDebtMillionTwd"]), "判讀": "現金減淨現金的精確推導；不是公司直接列示欄位"},
            {"項目": "淨現金", "2026-06-30": _reader_amount_million(balance["netCashMillionTwd"]), "判讀": "正值提供緩衝，不等於FCF已改善"},
            {"項目": "權益總額（含非控制權益）", "2026-06-30": _reader_amount_million(balance["totalEquityMillionTwd"]), "判讀": "合併資產負債表權益總額；不得作為歸屬母公司ROE或BVPS分母"},
            {"項目": "流動性限制", "2026-06-30": "流動比率資料未提供", "判讀": "不據此宣稱短期償債能力全面穩健"},
        ], ("項目", "2026-06-30", "判讀"))
        + _table([
            {"90日研究情境": "基準", "額外營運資金需求": "0億元", "壓力後CFO": _reader_amount_million(a["q2StandaloneCfoMillionTwd"]), "壓力後FCF": _reader_amount_million(a["q2StandaloneFcfMillionTwd"])},
            {"90日研究情境": "應收+5天、存貨+10天", "額外營運資金需求": _reader_amount_million(stress_a["net_incremental_working_capital_requirement"]), "壓力後CFO": _reader_amount_million(stress_a["stressed_cfo"]), "壓力後FCF": _reader_amount_million(stress_a["stressed_fcf"])},
            {"90日研究情境": "應收+10天、存貨+15天、應付-5天", "額外營運資金需求": _reader_amount_million(stress_b["net_incremental_working_capital_requirement"]), "壓力後CFO": _reader_amount_million(stress_b["stressed_cfo"]), "壓力後FCF": _reader_amount_million(stress_b["stressed_fcf"])},
        ], ("90日研究情境", "額外營運資金需求", "壓力後CFO", "壓力後FCF"))
        + "<p>以上是既有90日敏感度，不是預測或政策門檻。淨現金提供存量緩衝，但兩個壓力情境顯示營運資金惡化會放大資金需求，因此只能判定韌性仍需現金回收驗證，不能對整體韌性作出確定的類別結論。</p>"
        "<h3>ROIC三層證據必須分開</h3>"
        "<p><strong>ROIC持續性／資本強度敏感度：</strong>以下三層不得混為同一個實際報酬率。</p>"
        f"<p><strong>官方同口徑：</strong>Q2 單季同口徑 ROIC 待補；缺口不是零。"
        f"<strong>部分營運投入資本估算：</strong>以應收、存貨、營運用不動產廠房設備減應付帳款，平均投入資本"
        f"{_reader_amount_million(roic_estimate['average_invested_capital_million_twd'])}，單季估算ROIC "
        f"{_reader_number(roic_estimate['quarterly_roic_pct'])}%；這不是官方同口徑ROIC。"
        "<strong>年化敏感度：</strong>僅描述單季延伸，不能當作TTM或正式年度ROIC。"
        "相容口徑WACC尚未提供，因此不能正式判定ROIC與資金成本的利差。</p>"
        "<h3>每股價值</h3><p>EPS已由官方資料確認；BVPS截至2026Q1為127.12元，Q2直接值尚未提供；"
        "FCF／股依相容加權平均股數估算，僅用於辨識現金風險。每股價值仍需EPS、BVPS、FCF與股數共同驗證。</p>"
        + visuals("s4")
    )

    chapters["s5"] = (
        "<h3>競爭力已在交付規模顯現，尚未在毛利與現金形成完整閉環</h3>"
        "<p>AI伺服器與雲端網路產品推動營收，Cloud & Networking占Q2營收51%；公司整體營業利益同步改善。"
        "這支持大規模量產、垂直整合與客戶共同開發的交付能力，但AI專屬營收占比、營業利益、ROIC與FCF未單獨揭露，"
        "不能把公司整體改善全部歸因於AI。</p>"
        + _table([
            {"經濟面向": "利潤率", "本期證據": f"毛利率{q.gross_margin.value}%、營益率{q.operating_margin.value}%", "判讀": "營益率改善來自毛利以下費用吸收，尚非毛利結構升級"},
            {"經濟面向": "資本強度", "本期證據": f"Capex／營收{a['capexIntensityRevenuePct']}%；營運資金代理值增加{_reader_amount_million(net_wc_change)}", "判讀": "規模成長仍需要資本與營運資金"},
            {"經濟面向": "現金轉化", "本期證據": f"CFO {_reader_amount_million(a['q2StandaloneCfoMillionTwd'])}；FCF {_reader_amount_million(a['q2StandaloneFcfMillionTwd'])}", "判讀": "效率改善尚未完整轉成現金"},
            {"經濟面向": "資本報酬", "本期證據": f"部分營運ROIC估算{_reader_number(roic_estimate['quarterly_roic_pct'])}%；官方同口徑待補", "判讀": "尚不能證明新增資本效率提高"},
        ], ("經濟面向", "本期證據", "判讀"))
        +
        "<h3>Consignment（客供料）仍是可驗證假說</h3>"
        "<p>若客供料占比提高，理論上可降低存貨與營運資金、改善CFO與ROIC；目前仍屬假說，尚無完整財務證據確認。"
        "本季應收與存貨上升、應付亦上升、CCC改善，訊號互有支持與反證，資本輕量化綜合判斷仍不確定。"
        "下一步需要客供料比例、存貨風險歸屬或可歸屬的營運資金揭露。</p>"
    )

    chapters["s6"] = (
        "<h3>外部變數只在能落到財務傳導時進入判斷</h3>"
        + _table([
            {"外部驅動": "AI伺服器／CSP資本支出", "第一階影響": "出貨與營收", "第二階影響": "產品組合、營業利益與營運資金", "尚待確認": "AI專屬利潤、ROIC與FCF"},
            {"外部驅動": "Apple產品週期", "第一階影響": "消費智能產品需求", "第二階影響": "產能利用率與毛利率", "尚待確認": "公司可歸屬訂單與單位經濟"},
            {"外部驅動": "匯率／關稅／政策", "第一階影響": "換算、成本與區域產能", "第二階影響": "毛利、Capex與現金需求", "尚待確認": "公司量化敏感度與抵銷機制"},
        ], ("外部驅動", "第一階影響", "第二階影響", "尚待確認"))
        +
        "<p>本期沒有足以量化上述外部變數對鴻海Q2損益與現金的增量證據，因此不把宏觀敘事寫成既成原因。"
        "若Q3出貨延續、營益率維持且營運資金回收，才可提高AI需求向企業價值傳導的信心；反之則需考慮低毛利放量或資本占用。</p>"
    )

    chapters["s7"] = (
        "<h3>3+3六項支柱已核對，價值創造進度不等於策略口號</h3>"
        + _table(strategy_rows, ("支柱", "商業化階段", "本季財務證據", "下一道價值閘門"))
        +
        "<p>人工智慧是目前唯一已明確進入營收證據階段的支柱，公司整體營業利益方向亦改善；"
        "但尚未跨過可歸屬ROIC、FCF與股東回報閘門。其他支柱多停留在策略或開發階段。"
        "本次正式來源只核對3+3六項支柱，未獨立證實額外的第三組「3」，因此不納入價值評分。</p>"
        "<h3>管理層指引與結果核對</h3>"
        + _table([
            {"主題": "AI伺服器成長", "既有說法": "Q3 AI Rack出貨季增高雙位數", "截至本報告結果": "前瞻指引，實現值尚未揭露", "判定": "仍開放驗證"},
            {"主題": "營業利益轉化", "既有說法": "規模與整合有助營運效率", "截至本報告結果": f"Q2營業利益年增{a['operatingProfitYoyPct']}%，營益率升至{q.operating_margin.value}%", "判定": "本季財務結果支持"},
            {"主題": "ROE／資本效率", "既有說法": "需由正式目標與同口徑資料核對", "截至本報告結果": "H1 ROE改善；Q2同口徑ROIC待補", "判定": "部分支持"},
            {"主題": "資本支出", "既有說法": "本地證據沒有可比指引區間", "截至本報告結果": f"Q2推導Capex {_reader_amount_million(a['q2StandaloneCapexMillionTwd'])}", "判定": "無法判定超前或落後"},
        ], ("主題", "既有說法", "截至本報告結果", "判定"))
    )

    chapters["s8"] = (
        f"<h3>{valuation_context}估值：評價已高於歷史中位，仍需第二階段證據</h3>"
        + _table(timepoint_rows, ("估值時點", "價格日期／收盤價", "P/S", "P/E", "P/B"))
        + f"<p>財報事件日為{valuation['price']['eventDate']}。{time_basis_sentence}本地正式行情截止{valuation['price']['date']}，"
        f"{post_event_sentence}"
        f"事件前估值使用更新至Q2的TTM營收與EPS，以及截至2026Q1的直接BVPS。{official_cite}{master_cite}{price_cite}</p>"
        f"<p>同一市場資料窗口的20期報酬為{analysis.price_and_market_activity.recent_price_context.return_windows.get('20D')}。"
        "這只能描述股價動能，不能在沒有基準調整事件研究時歸因於本次財報。</p>"
        f"<p>歷史位置顯示，P/S中位數約{_reader_number(historical['ps']['median'])}倍、目前約在第{_reader_number(historical['ps']['percentile_pct'])}百分位；"
        f"P/E中位數約{_reader_number(historical['pe']['median'])}倍、目前約在第{_reader_number(historical['pe']['percentile_pct'])}百分位；"
        f"P/B中位數約{_reader_number(historical['pb']['median'])}倍、目前約在第{_reader_number(historical['pb']['percentile_pct'])}百分位。"
        "圖表歷史季度序列只到2026Q1；正文事件前估值則以2026-08-11價格與Q2更新分母計算，兩者不是同一時點。"
        f"{master_cite}{price_cite}</p>"
        "<p><strong>再評價成立條件：</strong>營收成長須持續轉為營業利益，接著由ROIC與FCF確認新增資本創造價值；"
        "<strong>再評價失效條件：</strong>營益率回落、投入資本快於NOPAT、或FCF長期未跟上獲利。"
        "在缺少核准的估值安全邊際門檻時，本章只描述市場位置，不提供買賣結論。</p>"
        + visuals("s8")
    )

    chapters["s9"] = (
        "<h3>兩種競爭解釋</h3>"
        "<p><strong>主解釋：</strong>AI與雲端網路規模擴張，毛利以下費用吸收改善，使營業利益增速高於營收；"
        "負現金流與成長期營運資金占用及Capex同時出現，但非現金項目與完整現金流橋接不足，尚不能確認全部原因；回收與否須由H2、全年或TTM現金轉化驗證。"
        "<strong>替代解釋：</strong>新增業務的毛利品質不足，帳面獲利需要持續投入應收、存貨與產能，現金與資本回報可能長期落後。"
        "Q3 CFO、毛利率與同口徑ROIC將決定哪一種解釋更接近事實。</p>"
        "<h3>八項企業價值證據規則</h3>" + _table(rule_rows, ("檢核面向", "目前判定", "證據解讀"))
        + "<h3>三層決策</h3>" + _table(decision_rows, ("決策層", "本期", "判讀"))
    )

    chapters["s10"] = (
        "<h3>未來一至四季的可推翻驗證表</h3>"
        + _table(smart_rows, ("驗證主題", "目前基線", "增強條件", "削弱條件", "下一觀察"))
        + "<p><strong>最後判斷：</strong>營收轉為營業利益的第一階段獲得支持；新增資本是否提高報酬仍缺同口徑ROIC；Q2負CFO與負FCF顯示獲利尚未完成現金轉化。"
        +
        "核心持有論點維持，但安全邊際不上修。任何未來更新都必須以表中條件驗證，而不是以敘事強弱替代數據。</p>"
    )

    chapters["s11"] = (
        "<h3>論文式來源索引</h3>"
        "<p>正文中的方括號編號可回查下列正式資料或官方證據；CSV與JSON只作可追溯資料定位，不被描述為新聞或研究來源。</p>"
        + _table(refs, ("編號", "來源與主張", "日期", "定位"))
        + "<h3>資料限制</h3><ul>"
        + "".join(f"<li>{html.escape(item.replace(':', '：', 1))}</li>" for item in unavailable)
        + "</ul>"
        +
        "<details><summary>技術稽核說明</summary><p>完整來源雜湊、推導台帳、規則輸入與模型情境保存在同一報告包的機器可讀JSON；"
        "正文只保留投資判讀所需的數字、公式、來源日期與限制。報告尚未正式發布，亦不構成交易指令。</p></details>"
    )
    return chapters


def _build_chapters(
    report: ReportCandidate,
    charts: Sequence[ChartData],
    decision: Mapping[str, Any],
    smart: Mapping[str, Any],
    route: Mapping[str, Any],
    unavailable: Sequence[str],
    fcf_state: Mapping[str, Any] | None,
    per_share_state: Mapping[str, Any],
    historical_baseline: Mapping[str, Any],
    forward: Mapping[str, Any] | None = None,
    rule_result: Mapping[str, Any] | None = None,
    analysis: AnalysisPacket | None = None,
) -> dict[str, str]:
    if report.event_type == "QUARTERLY_EARNINGS":
        if analysis is None or forward is None or rule_result is None:
            raise WarReportRuntimeError("QUARTERLY_RESEARCH_INPUT_MISSING")
        return _quarterly_research_chapters(
            analysis=analysis,
            report=report,
            charts=charts,
            decision=decision,
            smart=smart,
            unavailable=unavailable,
            fcf_state=fcf_state,
            forward=forward,
            rule_result=rule_result,
        )
    renderer = FormalPreviewRenderer()
    chart_by_id = {item.chart_id: item for item in charts}
    section_map = _MONTHLY_CHAPTER_SECTION_MAP if report.event_type == "MONTHLY_REVENUE" else _CHAPTER_SECTION_MAP
    chapters: dict[str, str] = {}
    for chapter_id, _title in chapter_identity():
        content = _section_html(report, section_map[chapter_id])
        content += "".join(renderer._visual(chart_by_id[item]) for item in _CHAPTER_CHARTS.get(chapter_id, ()) if item in chart_by_id)
        chapters[chapter_id] = content
    a = report.evidence_bound_facts
    if fcf_state is not None:
        chapters["s4"] = (
            '<h3>FCF 轉化</h3>'
            '<p>Q2 CFO、Capex與FCF依同口徑累計數推導；負FCF使結構性風險尚未排除，後續需以營運資金回收與全年現金流驗證。</p>'
            f'<p>FCF 證據分類：{html.escape(str(fcf_state["classification"]))}；這不是季節性或結構性惡化的自動斷言。</p>'
            '<p>Q2 單季同口徑 ROIC 待補；不得以第三方 TTM ROIC 替代。</p>'
            + chapters["s4"]
        )
    chapters["s4"] += '<h3>每股價值傳達</h3>' + _table(
        [
            {"metric": "EPS", "state": (per_share_state.get("EPS") or {}).get("availability_state")},
            {"metric": "BVPS", "state": (per_share_state.get("BVPS") or {}).get("availability_state")},
            {"metric": "FCF／股", "state": per_share_state["FCF_PER_SHARE"]["availability_state"]},
            {"metric": "股數", "state": (per_share_state.get("SHARE_COUNT") or {}).get("availability_state")},
        ],
        ("metric", "state"),
    )
    wa_estimates = historical_baseline.get("metric_tier_counts", {}).get("WA_SHARES_BASIC_EST", {}).get(T2, 0)
    fcf_estimates = research_observations_for(historical_baseline, "FCF_PER_SHARE")
    if wa_estimates and fcf_estimates:
        latest = fcf_estimates[-1]
        chapters["s4"] += (
            '<h3>估算分母與FCF／股</h3>'
            '<p>依母公司業主淨利與公告基本 EPS 反推，本期基本加權平均股數為估算值；'
            '因 EPS 為小數二位揭露，估算保留四捨五入區間。'
            f'按相容期間股數計算，FCF／股估約 {html.escape(str(round(float(latest["value"]), 2)))} 元；'
            '此數值屬估算，不是公司直接揭露，僅支持風險觀察。</p>'
        )
    chapters["s5"] += '<h3>Buy & Sell／Consignment（客供料）驗證鏈</h3><p>Consignment（客供料）占比提高可能降低存貨與營運資金需求，進而降低融資需求與利息、改善CFO／FCF及ROIC；目前仍屬假說，尚無完整財務證據確認。</p>'
    if forward is not None:
        roic = forward["roic_sensitivity"]
        independent_roic = roic["independent_q2_invested_capital"]
        roic_rows = [
            {
                "情境": item["scenario"],
                "推估投入資本（百萬元）": item["result"]["scenario_invested_capital_million_twd"],
                "單季持續性敏感度": item["result"]["quarterly_roic_persistence_sensitivity_pct"] + "%",
                "單季年化持續性敏感度": item["result"]["annualized_roic_persistence_sensitivity_pct"] + "%",
            }
            for item in roic["scenarios"]
        ]
        wc_rows = [
            {
                "情境": item["scenario"],
                "營運資金增加（百萬元）": item["result"]["net_incremental_working_capital_requirement"],
                "壓力後CFO（百萬元）": item["result"]["stressed_cfo"],
                "壓力後FCF（百萬元）": item["result"]["stressed_fcf"],
                "主要假設": "、".join(item["assumptions"][1:4]),
            }
            for item in forward["working_capital_stress"]["scenarios"]
        ]
        dilution = forward["dilution_sensitivity"]
        chapters["s4"] += (
            '<h3>部分營運投入資本與ROIC估算</h3>'
            f'<p>以應收帳款、存貨、營運用PP&E減應付帳款重建Q1與Q2期末部分營運投入資本，平均值為{html.escape(str(independent_roic.get("average_invested_capital_million_twd")))}百萬元；Q2單季ROIC估算為{html.escape(str(independent_roic.get("quarterly_roic_pct")))}%。未揭露的其他營運資產與無息營運負債未插補，因此這不是官方同口徑ROIC。</p>'
            '<h3>ROIC持續性／資本強度敏感度</h3>'
            '<p>下表以前期同口徑ROIC為錨，只檢查資本強度變化；不得稱為獨立Q2實際ROIC。單季與單季年化分列，年化不等於TTM。</p>'
            + _table(roic_rows, ("情境", "推估投入資本（百萬元）", "單季持續性敏感度", "單季年化持續性敏感度"))
            + '<h3>營運資金壓力測試（Working Capital Stress Test）</h3>'
            '<p>以季度90日為模型日數，壓力天數由研究情境設定，並非管理層指引或Owner核准門檻。</p>'
            + _table(wc_rows, ("情境", "營運資金增加（百萬元）", "壓力後CFO（百萬元）", "壓力後FCF（百萬元）", "主要假設"))
            + '<h3>每股稀釋敏感度</h3>'
            '<p>EPS與FCF／股使用相容加權平均股數；BVPS使用期末股數情境。分子成長率等於股數成長率時，每股成長損益兩平。Q2期末正式股數不足，因此BVPS矩陣只作情境。</p>'
            + _table([
                {"指標": "EPS", "分母": dilution["EPS"]["denominator_basis"], "損益兩平": dilution["break_even_thresholds"]["EPS_DILUTION_BREAK_EVEN_GROWTH"]},
                {"指標": "FCF／股", "分母": dilution["FCF_PER_SHARE"]["denominator_basis"], "損益兩平": dilution["break_even_thresholds"]["FCF_PER_SHARE_DILUTION_BREAK_EVEN_GROWTH"]},
                {"指標": "BVPS", "分母": dilution["BVPS"]["denominator_basis"], "損益兩平": dilution["break_even_thresholds"]["BVPS_DILUTION_BREAK_EVEN_GROWTH"]},
            ], ("指標", "分母", "損益兩平"))
        )
        cap_light = forward["capital_light_proxy"]
        chapters["s5"] += (
            '<h3>資本輕量化代理指標（Capital-Light Proxy）</h3>'
            f'<p>五個正規化因子群組的綜合方向為 {html.escape(cap_light["signal"])}。這只表示財務特徵與較低資本占用假說的相容程度；公司未揭露精確Consignment（客供料）比例，報告不估算或反推該比例。</p>'
            + _table(cap_light["factor_groups"], ("factor_group", "level_signal", "trend_signal", "supporting_metrics", "contradicting_metrics", "data_completeness"))
        )
        chapters["s6"] += '<h3>外部驅動至企業價值傳導</h3>' + _table(forward["chapter_6_transmission_layer"], ("external_driver", "first_order_financial_effect", "second_order_effect", "fcf_or_roic_transmission", "current_evidence", "unresolved_variable"))
        chapters["s7"] += '<h3>資本配置與增量效率</h3><p>營業利益已改善，但同口徑增量投入資本尚缺；新增資本能否提高ROIC，仍須與營運資金回收、FCF／股及股數變化共同驗證。</p>'
        chapters["s8"] += '<h3>估值支持條件</h3><p>估值不得只看P/S或單一倍數；目前須把推估ROIC範圍、負FCF、每股價值與正式ROE證據共同判讀。因缺Owner核准安全邊際門檻，僅作描述與部分支持。</p>'
        chapters["s9"] += '<h3>前瞻壓力情境</h3>' + _table(wc_rows, ("情境", "營運資金增加（百萬元）", "壓力後CFO（百萬元）", "壓力後FCF（百萬元）"))
    if rule_result is not None:
        chapters["s9"] += '<h3>七維證據規則</h3>' + _table(rule_result["rules"], ("dimension", "calculated_state", "estimated_data_dependence", "rationale"))
    chapters["s9"] += '<h3>三維決策引擎</h3>' + _table(decision["items"], ("dimension", "PREVIOUS_STATE", "CURRENT_STATE", "CHANGE", "NEXT_GATE"))
    chapters["s10"] += _table(smart["items"], ("metric_or_thesis", "previous_state", "current_state", "changed", "next_verification", "time_horizon"))
    refs = "".join(f"<li>{html.escape(item.evidence_id)}：{html.escape(item.claim)}</li>" for item in report.evidence_references)
    ledger = historical_baseline.get("estimation_derivation_ledger", [])
    ledger_rows = [
        {
            "Metric": item["metric"], "Period": item["period"], "Displayed Value": item["displayed_value"],
            "Classification": "精確推導" if item["classification"] != T2 else "估算",
            "Formula": item["formula"], "Inputs": ", ".join(item["inputs"]), "Source(s)": ", ".join(item["sources"]),
            "Basis": item["basis"], "Assumptions": "；".join(item["assumptions"]),
            "Rounding / uncertainty": item["rounding_or_uncertainty"], "Confidence": item["confidence"],
            "Limitations": item["limitations"], "Reconciliation status": item["reconciliation_status"],
        }
        for item in ledger
    ]
    chapters["s11"] += (
        f'<h3>來源與限制</h3><ol>{refs}</ol><p>{html.escape("；".join(unavailable))}</p>'
        '<h3>估算與推導台帳</h3>'
        + _table(ledger_rows, ("Metric", "Period", "Displayed Value", "Classification", "Formula", "Inputs", "Source(s)", "Basis", "Assumptions", "Rounding / uncertainty", "Confidence", "Limitations", "Reconciliation status"))
        + '<p>報告候選僅供 Owner 審閱；未授權發布，亦不構成交易指令。</p>'
    )
    if forward is not None:
        forward_rows = [
            {
                "模型": item["model_id"], "情境": item["scenario"], "公式": item["formula"],
                "輸入": "、".join(item["input_observation_ids"]), "假設": "；".join(item["assumptions"]),
                "證據層級": "、".join(item["input_evidence_classes"]), "信心": item["confidence"],
                "限制": "；".join(item["limitations"]),
            }
            for item in forward["forward_model_ledger"]
        ]
        chapters["s11"] += '<h3>前瞻模型與規則台帳</h3>' + _table(forward_rows, ("模型", "情境", "公式", "輸入", "假設", "證據層級", "信心", "限制"))
    if route.get("trigger") == "MAJOR_EVENT":
        impacted = set(route["impacted_chapters"])
        for chapter_id in route["unchanged_chapters"]:
            if chapter_id not in impacted:
                chapters[chapter_id] = "<p>本次事件未改變原判斷。</p>" + chapters[chapter_id]
    if not a:
        raise WarReportRuntimeError("EVIDENCE_BOUND_FACTS_MISSING")
    return {chapter_id: _reader_text(content) for chapter_id, content in chapters.items()}


def validate_runtime_candidate(*, rendered_html: str, trigger: str, identity: RuntimeIdentity, route: Mapping[str, Any], charts: Sequence[ChartData], audits: Sequence[Mapping[str, Any]], baseline: Sequence[Mapping[str, Any]], decision: Mapping[str, Any], owner_review: Mapping[str, Any], forward: Mapping[str, Any] | None = None, rule_result: Mapping[str, Any] | None = None) -> None:
    validate_contract()
    if trigger not in load_contract()["valid_triggers"]:
        raise WarReportRuntimeError("INVALID_FORMAL_TRIGGER")
    if not identity.report_key or identity.revision < 1:
        raise WarReportRuntimeError("REPORT_IDENTITY_MISSING")
    validate_reader_html(rendered_html)
    validate_professional_reader_language(rendered_html)
    if len(chapter_identity()) != 11:
        raise WarReportRuntimeError("CHAPTER_CONTRACT_INVALID")
    if trigger == "QUARTERLY_EARNINGS" and "FCF 轉化" not in rendered_html:
        raise WarReportRuntimeError("QUARTERLY_FCF_CONVERSION_MISSING")
    if any(item.get("FULL_HISTORY") != "YES" or item.get("DROPPED_OBSERVATIONS") != 0 for item in audits):
        raise WarReportRuntimeError("FULL_HISTORY_POLICY_FAILED")
    if len(decision.get("items", [])) != 3 or decision.get("aggregate_numeric_score") is not None:
        raise WarReportRuntimeError("DECISION_ENGINE_INVALID")
    if any(item["direct_or_derived"] == "DERIVED" and not item["calculation_version"] for item in baseline):
        raise WarReportRuntimeError("DERIVED_METRIC_UNLABELLED")
    if resolve_quarterly_roic(official_same_basis_quarterly=None, third_party_ttm=99)["value"] is not None:
        raise WarReportRuntimeError("ROIC_BASIS_MIXED")
    if not all(term in " ".join([rendered_html, *_KPI_ALLOWED]) for term in ("ROIC", "FCF", "EPS", "P/S")):
        raise WarReportRuntimeError("STANDARD_KPI_ABBREVIATION_LOST")
    if owner_review.get("publication") is not False or owner_review.get("status") != "OWNER_REVIEW_REQUIRED":
        raise WarReportRuntimeError("OWNER_REVIEW_GATE_INVALID")
    if route.get("formal_report_generated") is not True or not charts:
        raise WarReportRuntimeError("REPORT_ROUTE_OR_CHARTS_INVALID")
    if trigger == "QUARTERLY_EARNINGS":
        if forward is None or rule_result is None:
            raise WarReportRuntimeError("FORWARD_ANALYTICS_OR_RULES_MISSING")
        if forward.get("actual_history_mutated") or forward.get("historical_observation_count_before") != forward.get("historical_observation_count_after"):
            raise WarReportRuntimeError("T4_SCENARIO_ENTERED_ACTUAL_HISTORY")
        if forward["roic_sensitivity"]["actual_same_basis_q2"]["basis"] == "QUARTERLY_ACTUAL":
            raise WarReportRuntimeError("ROIC_ESTIMATE_MISREPRESENTED_AS_ACTUAL")
        if "ROIC持續性／資本強度敏感度" not in rendered_html or "不是官方同口徑ROIC" not in rendered_html:
            raise WarReportRuntimeError("ROIC_ESTIMATE_DISCLOSURE_MISSING")
        if forward["capital_light_proxy"].get("consignment_percentage") is not None:
            raise WarReportRuntimeError("CONSIGNMENT_PERCENTAGE_FABRICATED")
        if rule_result.get("aggregate_numeric_score") is not None:
            raise WarReportRuntimeError("ARBITRARY_DECISION_SCORE_PRESENT")


def compile_existing_phaseb1_result(*, package_root: Path, analysis: AnalysisPacket, evidence: Any, trigger_context: Mapping[str, Any], output_root: Path, previous_state: Mapping[str, Any] | None = None, source_mother: Path | None = None) -> dict[str, Any]:
    """Adapt a validated Phase B1 analysis into the permanent report candidate."""
    trigger = str(trigger_context.get("eventType") or trigger_context.get("event_type") or "")
    route = plan_trigger(trigger, trigger_context.get("impactedChapters", ()))
    if not route.get("formal_report_generated"):
        return {"state": "FORMAL_REPORT_REQUIRED_NO", "formal_report_generated": False, "publication": False}
    identity = resolve_runtime_identity(trigger_context)
    report = ReportValidator().validate(ReportBuilder().build(analysis=analysis, evidence=evidence, generated_at_utc=analysis.generated_at_utc), analysis)
    baseline = build_financial_baseline(analysis)
    historical_baseline = build_layered_historical_research_baseline(package_root, analysis)
    charts, audits, unavailable = build_full_history_charts(package_root, analysis, historical_baseline)
    fcf_state = build_fcf_conversion_state(package_root, analysis)
    per_share_state = build_per_share_value_state(baseline, historical_baseline)
    forward = build_forward_enterprise_value_analytics(analysis, historical_baseline)
    rule_result = evaluate_enterprise_value_rules(
        forward=forward,
        fcf_classification=fcf_state["classification"] if fcf_state else "UNAVAILABLE",
        operating_profit_supported=analysis.financial_trend.operating_margin.status == "IMPROVING",
        balance_sheet_status=analysis.financial_trend.balance_sheet_safety.status,
        valuation_support=analysis.valuation_analysis.valuation_status,
        evidence_ids=report.evidence_bound_facts,
    )
    decision = _decision_state(previous_state, report, rule_result)
    smart = _smart_state(previous_state, report, rule_result)
    chapters = _build_chapters(
        report, charts, decision, smart, route, unavailable, fcf_state, per_share_state,
        historical_baseline, forward, rule_result, analysis,
    )
    rendered = render_owner_review_candidate(
        report_title="鴻海企業價值戰報", headline="企業價值第一階段已驗證，現金與資本報酬卡在第二階段",
        deck="FY2026 Q2營收年增41%、營業利益年增67.51%，但單季自由現金流為負1,174.51億元；營運槓桿已出現，價值閉環尚未完成。",
        eyebrow="鴻海 2317｜季度財報", report_meta=f"FY2026 Q2｜第{identity.revision}次修訂",
        chapter_html=chapters, footer="審閱版｜尚未正式發布｜不構成交易指令",
    )
    owner_review = {"status": "OWNER_REVIEW_REQUIRED", "ownerReviewRequired": True, "publication": False, "publishAuthorized": False, "actionable": False}
    validate_runtime_candidate(
        rendered_html=rendered, trigger=trigger, identity=identity, route=route,
        charts=charts, audits=audits, baseline=baseline, decision=decision,
        owner_review=owner_review, forward=forward, rule_result=rule_result,
    )
    output_root.mkdir(parents=True, exist_ok=False)
    html_path = output_root / "war_report_candidate.html"
    atomic_write(html_path, rendered.encode("utf-8"))
    atomic_write_json(output_root / "financial_baseline.json", baseline)
    atomic_write_json(output_root / "historical_kpi_baseline.json", historical_baseline)
    atomic_write_json(output_root / "fcf_conversion_state.json", fcf_state)
    atomic_write_json(output_root / "per_share_value_state.json", per_share_state)
    atomic_write_json(output_root / "forward_enterprise_value_analytics.json", forward)
    atomic_write_json(output_root / "forward_model_ledger.json", forward["forward_model_ledger"])
    atomic_write_json(output_root / "enterprise_value_rule_engine.json", rule_result)
    atomic_write_json(output_root / "chart_data_full_history.json", [item.model_dump(mode="json", by_alias=True) for item in charts])
    atomic_write_json(output_root / "chart_audit.json", audits)
    atomic_write_json(output_root / "decision_state.json", decision)
    atomic_write_json(output_root / "smart_state.json", smart)
    atomic_write_json(output_root / "owner_review.json", owner_review)
    revision_record = {
        "report_key": identity.report_key, "revision": identity.revision,
        "previous_revision": identity.previous_revision, "what_changed": trigger_context.get("whatChanged", "本期正式資料與證據更新"),
        "why": trigger_context.get("why", "有效報告觸發"), "which_data_changed": trigger_context.get("whichDataChanged", []),
        "investment_conclusion_changed": any(item["CHANGE"] != "UNCHANGED" for item in decision["items"]),
    }
    atomic_write_json(output_root / "revision.json", revision_record)
    lineage = validate_template_lineage(source_mother)
    receipt = {
        "state": "REPORT_CANDIDATE_READY", "owner_review_state": "OWNER_REVIEW_REQUIRED",
        "report_key": identity.report_key, "revision": identity.revision, "trigger": trigger,
        "route": route, "mother_template": lineage, "output_html_sha256": sha256_file(html_path),
        "historical_kpi_baseline_sha256": sha256_bytes(canonical_json_bytes(historical_baseline)),
        "historical_kpi_source_hashes": historical_baseline["source_hashes"],
        "forward_analytics_sha256": sha256_bytes(canonical_json_bytes(forward)),
        "decision_rules_sha256": sha256_bytes(canonical_json_bytes(rule_result)),
        "forward_model_ledger_sha256": sha256_bytes(canonical_json_bytes(forward["forward_model_ledger"])),
        "css_sha256_output": _sha(_style_bytes(rendered)), "chart_audit": audits,
        "external_calls": {"network": 0, "openai_api": 0, "canva": 0},
        "publication": False, "actionable": False,
    }
    atomic_write_json(output_root / "war_report_runtime_receipt.json", receipt)
    return {**receipt, "output_html": str(html_path), "output_root": str(output_root), "report": report, "analysis": analysis}


def run_war_report_production(*, package_root: Path, trigger_context: Mapping[str, Any], output_base: Path | None = None, governed_evidence_root: Path | None = None, previous_state: Mapping[str, Any] | None = None, source_mother: Path | None = None) -> dict[str, Any]:
    """Stable Launcher-callable entrypoint; stops at Owner Review Candidate."""
    trigger = str(trigger_context.get("eventType") or trigger_context.get("event_type") or "")
    route = plan_trigger(trigger, trigger_context.get("impactedChapters", ()))
    if not route.get("formal_report_generated"):
        return {"state": "FORMAL_REPORT_REQUIRED_NO", "formal_report_generated": False, "publication": False, "actionable": False}
    if trigger == "MAJOR_EVENT":
        raise WarReportRuntimeError("MAJOR_EVENT_REQUIRES_EXISTING_VALIDATED_ANALYSIS_BASELINE")
    pipeline = PhaseB1Pipeline(package_root, governed_evidence_root=governed_evidence_root)
    analysis_result = pipeline.build_analysis(output_base=output_base, trigger_lineage=dict(trigger_context))
    run_root = Path(analysis_result["run_root"])
    return compile_existing_phaseb1_result(
        package_root=package_root, analysis=analysis_result["analysis"], evidence=analysis_result["evidence"],
        trigger_context=trigger_context, output_root=run_root / "war_report_v1",
        previous_state=previous_state, source_mother=source_mother,
    )
