"""Build a governed quarterly Analysis Packet from hash-bound Official IR evidence."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from ..adapters.authority_adapter import AuthorityAdapter
from ..phaseb1_common import canonical_json_bytes, sha256_bytes, sha256_file
from ..plugin_module.contracts import ValidatedEvidence
from ..quarterly_earnings import QuarterlyEarningsPacket
from .analysis_contracts import (
    AnalysisPacket,
    AudienceLens,
    ConfidenceClass,
    EventImpactLink,
    EventWindowReaction,
    EventWindowStatus,
    ExistingHoldingView,
    FactOrInference,
    FinancialTrend,
    InvestorViews,
    LinkStatus,
    MarketPsychology,
    MarketRegime,
    MarketRegimeName,
    MaterialConclusion,
    MetricAssessment,
    NewMoneyView,
    OverallThesis,
    PriceAndMarketActivity,
    QuarterlyEarningsAnalysis,
    QuarterlyMetric,
    RecentPriceContext,
    RegimeCondition,
    ThesisScorecard,
    TrendStatus,
    ValuationAnalysis,
    ValuationStatus,
)


def _d(value: str) -> Decimal:
    return Decimal(value.replace("%", "").replace("+", ""))


def _pct(current: Decimal, prior: Decimal) -> str:
    return f"{((current / prior) - 1) * 100:.2f}%" if prior else "INSUFFICIENT_DATA"


def normalized_q4_eps(master_value: str, correction: dict[str, object]) -> Decimal:
    """Select official Q4 basic EPS in research normalization, never by mutation."""
    if correction.get("sourceDocumentSha256") != "91E4994341856DF0E1985DD87704DBE17E1E35CA66FF730CE8CA833CA7766EC0":
        raise ValueError("2025Q4 official EPS normalization evidence is unavailable or hash-invalid")
    corrected = _d(str(correction.get("basicEpsTwd", "")))
    if corrected != Decimal("3.23") or _d(master_value) == corrected:
        raise ValueError("2025Q4 EPS normalization lineage is not the expected official-over-L3 correction")
    return corrected


def ttm_eps_valuation(*, price: Decimal, q3_2025: Decimal, q4_2025: Decimal, q1_2026: Decimal, q2_2026: Decimal) -> dict[str, Decimal]:
    ttm = q3_2025 + q4_2025 + q1_2026 + q2_2026
    return {"ttm_eps": ttm, "ttm_pe": (price / ttm).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "h2_2025_eps": q3_2025 + q4_2025}


def valuation_time_basis_labels(price_date_value: str, event_date_value: str) -> dict[str, str | bool]:
    """Classify market evidence from the actual event date, never availability alone."""
    price_date = date.fromisoformat(price_date_value)
    event_date = date.fromisoformat(event_date_value)
    is_pre_event = price_date < event_date
    return {
        "is_pre_event": is_pre_event,
        "price_context": "PRE_EVENT_PRICE" if is_pre_event else "POST_EVENT_REPORT_CUTOFF_PRICE",
        "reader_label": "財報公布前收盤價" if is_pre_event else "財報公布後報告截止日收盤價",
        "valuation_state": "PRE_EVENT_VALUATION_CONTEXT" if is_pre_event else "POST_EVENT_REPORT_CUTOFF_CONTEXT",
        "cutoff_status": "AVAILABLE_PRE_EVENT" if is_pre_event else "AVAILABLE_POST_EVENT",
    }


class QuarterlyAnalysisBuilder:
    def __init__(self, package_root: Path, authority: AuthorityAdapter) -> None:
        self.package_root = package_root.resolve()
        self.authority = authority

    def build(
        self,
        *,
        run_id: str,
        generated_at_utc: datetime,
        validated_evidence: ValidatedEvidence,
        quarterly_packet: QuarterlyEarningsPacket,
    ) -> AnalysisPacket:
        verified = self.authority.verify_all()
        hashes = {item["relative_path"]: item["sha256"] for item in verified["verified"]}
        manifest_path = self.package_root / self.authority.MANIFEST_PATH
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        entries = {
            item["path"]: item
            for item in manifest.get("authoritativeFiles", []) + manifest.get("nonAuthoritativeFiles", [])
        }
        cutoffs = {path: self._cutoff(entries[path]) for path in sorted(entries)}
        master = self.authority.read_csv("data/2317_master_v9.csv")
        price = self.authority.read_csv("data/2317_daily_price.csv")
        activity = self.authority.read_csv("data/2317_daily_market_activity.csv")
        cash = self.authority.read_csv("data/2317_cash_flow_authority.csv")
        latest_master, latest_price, latest_activity, latest_cash = (
            master.rows[-1], price.rows[-1], activity.rows[-1], cash.rows[-1]
        )
        price_values = [_d(row["Close"]) for row in price.rows]
        volumes = [_d(row["trade_volume"]) for row in activity.rows]
        returns = {
            name: _pct(price_values[-1], price_values[-1 - distance]) if len(price_values) > distance else "INSUFFICIENT_DATA"
            for name, distance in (("1D", 1), ("5D", 5), ("20D", 20))
        }
        volume_window = volumes[-20:]
        volume_average = sum(volume_window) / Decimal(len(volume_window))
        volume_ratio = volumes[-1] / volume_average if volume_average else None
        volume_percentile = Decimal(sum(item <= volumes[-1] for item in volumes)) / Decimal(len(volumes)) * 100
        pbs = [_d(row["PB_daily"]) for row in price.rows]
        pb_percentile = Decimal(sum(item <= pbs[-1] for item in pbs)) / Decimal(len(pbs)) * 100

        official_ids = sorted(validated_evidence.evidence_ids)
        authority_ids = {
            "master": f"AUTH-MASTER-{self._safe(cutoffs['data/2317_master_v9.csv'])}",
            "price": f"AUTH-PRICE-{self._safe(cutoffs['data/2317_daily_price.csv'])}",
            "activity": f"AUTH-MARKET-ACTIVITY-{self._safe(cutoffs['data/2317_daily_market_activity.csv'])}",
            "cash": f"AUTH-CASHFLOW-{self._safe(cutoffs['data/2317_cash_flow_authority.csv'])}",
        }
        source_ids = sorted([*official_ids, *authority_ids.values()])
        evidence_hashes = {
            packet.packet_id: sha256_bytes(canonical_json_bytes(packet.model_dump(mode="json", by_alias=True)))
            for packet in validated_evidence.packets
        }
        q = quarterly_packet.values
        f = q["financials"]
        cf = q["cashFlow"]
        prior = q["priorYearQuarterFinancials"]
        balance = q["balanceSheet"]
        pre_event_prices = [row for row in price.rows if row["Date"] < q["publicationDate"]]
        post_event_prices = [row for row in price.rows if row["Date"] >= q["publicationDate"]]
        latest_pre_event_price = pre_event_prices[-1] if pre_event_prices else None
        latest_post_event_price = post_event_prices[-1] if post_event_prices else None
        working_capital_days = q["workingCapitalDays"]
        product_mix = q["productMix"]
        strategy = q["strategyFramework"]
        result_id = official_ids[0]
        q1_cfo = _d(latest_cash["operating_cash_flow_thousand_ntd"]) / Decimal("1000")
        q1_capex = _d(latest_cash["ppe_capex_thousand_ntd"]) / Decimal("1000")
        q1_fcf = _d(latest_cash["free_cash_flow_core_thousand_ntd"]) / Decimal("1000")
        h1_cfo = _d(cf["operatingCashFlowMillionTwd"])
        h1_capex = _d(cf["capexMillionTwd"])
        h1_fcf = _d(cf["freeCashFlowMillionTwd"])
        cash_scope_comparable = (
            latest_cash["statement_scope"] == "CONSOLIDATED"
            and latest_cash["currency"] == "TWD"
            and latest_cash["source_unit"] == "THOUSAND_TWD"
            and latest_cash["formula_core"] == "OPERATING_CASH_FLOW_MINUS_PPE_CAPEX"
            and cf["definition"] == "Operating cash flow minus capital expenditure"
        )
        if not cash_scope_comparable:
            raise ValueError("Q1 and H1 cash-flow definitions are not comparable")
        q2_cfo = h1_cfo - q1_cfo
        q2_capex = h1_capex - q1_capex
        q2_fcf_direct = q2_cfo - q2_capex
        q2_fcf_cumulative = h1_fcf - q1_fcf
        q2_fcf_rounding_difference = abs(q2_fcf_direct - q2_fcf_cumulative)
        q2_fcf_rounding_tolerance = Decimal("1")
        if q2_fcf_rounding_difference > q2_fcf_rounding_tolerance:
            raise ValueError("Q2 FCF derivations do not reconcile within rounding tolerance")
        history_rows = list(master.rows[-7:])
        q4_2025_rows = [row for row in master.rows if row["Quarter"] == "2025Q4"]
        if len(q4_2025_rows) != 1 or not q4_2025_rows[0].get("EPS_Q"):
            raise ValueError("2025Q4 master EPS is not uniquely available")
        master_q4_2025_eps = _d(q4_2025_rows[0]["EPS_Q"])
        q4_correction = q.get("historicalEpsCorrections", {}).get("2025Q4", {})
        q4_2025_eps = normalized_q4_eps(q4_2025_rows[0]["EPS_Q"], q4_correction)
        historical_gross_profit = [
            (_d(row["Revenue_Q_100M"]) * _d(row["GrossMarginPct"]) / Decimal("100"))
            for row in history_rows
        ]
        historical_opex_proxy = [
            gross_profit - _d(row["OperatingIncome_Q_100M"])
            for row, gross_profit in zip(history_rows, historical_gross_profit)
        ]
        q2_opex_proxy = _d(f["grossProfitMillionTwd"]) - _d(f["operatingIncomeMillionTwd"])
        history = {
            "periods": [row["Quarter"] for row in history_rows] + [q["fiscalPeriod"].replace("FY", "").replace(" ", "")],
            "revenue100mTwd": [row["Revenue_Q_100M"] for row in history_rows]
            + [str((_d(f["revenueMillionTwd"]) / Decimal("100")).quantize(Decimal("0.01")))],
            "grossProfit100mTwd": [str(item.quantize(Decimal("0.01"))) for item in historical_gross_profit]
            + [str((_d(f["grossProfitMillionTwd"]) / Decimal("100")).quantize(Decimal("0.01")))],
            "grossProfitOrigin": ["DERIVED_FROM_GOVERNED_AUTHORITY"] * len(history_rows) + ["OFFICIAL"],
            "operatingProfitOrigin": ["GOVERNED_AUTHORITY"] * len(history_rows) + ["OFFICIAL"],
            "grossMarginPct": [row["GrossMarginPct"] for row in history_rows] + [f["grossMarginPct"]],
            "operatingIncome100mTwd": [row["OperatingIncome_Q_100M"] for row in history_rows]
            + [str((_d(f["operatingIncomeMillionTwd"]) / Decimal("100")).quantize(Decimal("0.01")))],
            "operatingMarginPct": [row["OperatingMarginPct"] for row in history_rows] + [f["operatingMarginPct"]],
            "opexProxy100mTwd": [str(item.quantize(Decimal("0.01"))) for item in historical_opex_proxy]
            + [str((q2_opex_proxy / Decimal("100")).quantize(Decimal("0.01")))],
            "opexProxyRevenuePct": [
                str((item / _d(row["Revenue_Q_100M"]) * Decimal("100")).quantize(Decimal("0.001")))
                for row, item in zip(history_rows, historical_opex_proxy)
            ] + [str((q2_opex_proxy / _d(f["revenueMillionTwd"]) * Decimal("100")).quantize(Decimal("0.001")))],
            "epsTwd": [row["EPS_Q"] for row in history_rows] + [f["epsTwd"]],
            "roicPct": [row["ROIC_Precise_Pct"] for row in history_rows] + ["INSUFFICIENT_DATA"],
            "bvpsTwd": [row["BVPS"] for row in history_rows] + ["INSUFFICIENT_DATA"],
            "roeTtmPct": [row["ROE_TTM_Pct"] for row in history_rows] + ["INSUFFICIENT_DATA"],
            "roeAnnualPct": [row["ROE_Annual_Pct"] for row in history_rows] + ["INSUFFICIENT_DATA"],
            "sourceEvidenceIds": [authority_ids["master"], *official_ids],
            "historyStatus": "EIGHT_QUARTERS_AVAILABLE",
        }
        price_value = _d(latest_price["Close"])
        pb_value = _d(latest_price["PB_daily"])
        ttm_components = [Decimal("4.15"), q4_2025_eps, Decimal("3.56"), _d(f["epsTwd"])]
        valuation_arithmetic = ttm_eps_valuation(price=price_value, q3_2025=ttm_components[0], q4_2025=ttm_components[1], q1_2026=ttm_components[2], q2_2026=ttm_components[3])
        ttm_eps = valuation_arithmetic["ttm_eps"]
        implied_bvps = price_value / pb_value
        governed_bvps = _d(latest_master["BVPS"])
        dividend = Decimal("7.2")
        h2_2025_eps = valuation_arithmetic["h2_2025_eps"]
        ttm_revenue_periods = ("2025Q3", "2025Q4", "2026Q1")
        revenue_by_period = {row["Quarter"]: _d(row["Revenue_Q_100M"]) * Decimal("100") for row in master.rows}
        if any(period not in revenue_by_period for period in ttm_revenue_periods):
            raise ValueError("TTM revenue components are incomplete")
        ttm_revenue_million_twd = sum(revenue_by_period[period] for period in ttm_revenue_periods) + _d(f["revenueMillionTwd"])
        estimated_weighted_average_shares_million = _d(f["attributableProfitMillionTwd"]) / _d(f["epsTwd"])
        estimated_market_cap_million_twd = price_value * estimated_weighted_average_shares_million
        ps_value = estimated_market_cap_million_twd / ttm_revenue_million_twd

        def valuation_at_price(row: dict[str, str] | None) -> dict[str, Any]:
            if row is None:
                return {"status": "UNAVAILABLE_LOCAL_AUTHORITY", "date": None, "price": None, "ps": None, "pe": None, "pb": None}
            point_price = _d(row["Close"])
            return {
                "status": "AVAILABLE",
                "date": row["Date"],
                "price": str(point_price),
                "ps": f"{(point_price * estimated_weighted_average_shares_million / ttm_revenue_million_twd).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}",
                "pe": f"{(point_price / ttm_eps).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}",
                "pb": row["PB_daily"],
                "sourceId": authority_ids["price"],
            }

        pre_event_valuation = valuation_at_price(latest_pre_event_price)
        post_event_valuation = valuation_at_price(latest_post_event_price)
        time_basis = valuation_time_basis_labels(latest_price["Date"], q["publicationDate"])
        is_pre_event_price = bool(time_basis["is_pre_event"])
        price_context = str(time_basis["price_context"])
        price_reader_label = str(time_basis["reader_label"])
        valuation_state = str(time_basis["valuation_state"])
        cutoff_status = str(time_basis["cutoff_status"])
        forward_scenarios: list[dict[str, str]] = []
        for growth in (Decimal("0.10"), Decimal("0.20"), Decimal("0.30")):
            fy_eps = Decimal("7.83") + h2_2025_eps * (Decimal("1") + growth)
            forward_scenarios.append({
                "h2Yoy": f"+{int(growth * 100)}%",
                "fy26Eps": f"{fy_eps.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}",
                "peAtCurrentPrice": f"{(price_value / fy_eps).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}",
                "classification": "SCENARIO",
            })
        valuation_scenarios = {
            "price": {"value": str(price_value), "unit": "新台幣元", "date": latest_price["Date"], "eventDate": q["publicationDate"], "valuationContext": price_context, "readerLabel": price_reader_label, "classification": "OFFICIAL"},
            "valuationTimeBasis": {
                "contractId": "VALUATION_TIME_BASIS_V1",
                "eventDate": q["publicationDate"],
                "preEventPrice": ({"value": str(price_value), "date": latest_price["Date"], "sourceId": authority_ids["price"], "status": "AVAILABLE"} if is_pre_event_price else {"value": None, "date": None, "status": "NOT_SELECTED_REPORT_CUTOFF_IS_POST_EVENT"}),
                "postEventPrice": ({"value": None, "date": None, "status": "UNAVAILABLE_LOCAL_AUTHORITY"} if is_pre_event_price else {"value": str(price_value), "date": latest_price["Date"], "sourceId": authority_ids["price"], "status": "AVAILABLE"}),
                "reportCutoffPrice": {"value": str(price_value), "date": latest_price["Date"], "sourceId": authority_ids["price"], "status": cutoff_status},
                "preEventValuation": pre_event_valuation,
                "postEventValuation": post_event_valuation,
                "valuationState": valuation_state,
            },
            "pb": {"value": str(pb_value), "unit": "倍", "classification": "DIRECT_PRICE_WITH_LAGGED_DENOMINATOR", "denominatorPeriod": latest_master["Quarter"], "readerLabel": "以最新直接揭露BVPS計算的P/B"},
            "ttmEpsComponents": {"values": [str(item) for item in ttm_components], "unit": "元", "classification": "OFFICIAL"},
            "q4_2025Eps": {
                "value": str(q4_2025_eps),
                "unit": "元",
                "classification": "RESEARCH_NORMALIZED_FROM_OFFICIAL_RESULTS",
                "sourceId": q4_correction["sourceId"],
                "sourceLocator": q4_correction["sourceLocator"],
                "sourceDocumentSha256": q4_correction["sourceDocumentSha256"],
                "masterObservedValue": str(master_q4_2025_eps),
                "masterObservedSourceLevel": q4_2025_rows[0].get("DataSupportLevel"),
            },
            "ttmEps": {"value": str(ttm_eps), "unit": "元", "classification": "DERIVED"},
            "ttmPe": {"value": f"{(price_value / ttm_eps).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}", "unit": "倍", "classification": "DERIVED"},
            "impliedBvps": {"value": f"{implied_bvps.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}", "unit": "元", "classification": "DERIVED"},
            "governedBvps": {
                "value": str(governed_bvps),
                "unit": "元",
                "period": latest_master["Quarter"],
                "classification": "GOVERNED_AUTHORITY",
                "sourceId": authority_ids["master"],
            },
            "dividend": {"value": str(dividend), "unit": "元", "classification": "OFFICIAL"},
            "dividendYield": {"value": f"{(dividend / price_value * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}", "unit": "%", "classification": "DERIVED"},
            "h1Eps": {"value": "7.83", "unit": "元", "classification": "OFFICIAL"},
            "priorH2Eps": {"value": str(h2_2025_eps), "unit": "元", "classification": "OFFICIAL"},
            "ps": {
                "value": f"{ps_value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}",
                "unit": "倍",
                "classification": "T2_ESTIMATED_DERIVED",
                "priceContext": price_context,
                "priceDate": latest_price["Date"],
                "ttmRevenueMillionTwd": str(ttm_revenue_million_twd),
                "ttmRevenuePeriods": [*ttm_revenue_periods, "2026Q2"],
                "weightedAverageSharesMillion": str(estimated_weighted_average_shares_million),
                "shareBasis": "Q2 attributable profit / officially reported basic EPS; estimated compatible weighted-average shares",
                "formula": "report-cutoff price × estimated compatible weighted-average shares / TTM revenue",
            },
            "forwardPeScenarios": forward_scenarios,
            "peMatrix": [
                {"eps": item["fy26Eps"], "multiple": multiple, "referenceValue": f"{(_d(item['fy26Eps']) * Decimal(multiple)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}", "classification": "SCENARIO"}
                for item in forward_scenarios for multiple in ("16", "18")
            ],
            "pbScenarios": [
                {"multiple": str(multiple), "referenceValue": f"{(governed_bvps * multiple).quantize(Decimal('1'), rounding=ROUND_HALF_UP)}", "classification": "SCENARIO"}
                for multiple in (Decimal("1.6"), Decimal("1.8"), Decimal("2.0"), Decimal("2.069"), Decimal("2.2"))
            ],
            "dividendYieldScenarios": [
                {"yield": f"{yield_pct}%", "referenceValue": f"{(dividend / (yield_pct / 100)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)}", "classification": "SCENARIO"}
                for yield_pct in (Decimal("2.5"), Decimal("3.0"), Decimal("3.5"))
            ],
            "psStatus": f"AVAILABLE_T2_{valuation_state}",
            "scenarioDisclaimer": "情境參考值，不是目標價或交易指令。",
        }
        revenue_yoy = (_d(f["revenueMillionTwd"]) / _d(prior["revenueMillionTwd"]) - 1) * 100
        gross_profit_yoy = (_d(f["grossProfitMillionTwd"]) / _d(prior["grossProfitMillionTwd"]) - 1) * 100
        operating_profit_yoy = (_d(f["operatingIncomeMillionTwd"]) / _d(prior["operatingIncomeMillionTwd"]) - 1) * 100
        prior_opex_proxy = _d(prior["grossProfitMillionTwd"]) - _d(prior["operatingIncomeMillionTwd"])
        opex_proxy_yoy = (q2_opex_proxy / prior_opex_proxy - 1) * 100
        working_capital_amounts = {
            "accountsReceivable": [balance["priorYear"]["accountsReceivableNetMillionTwd"], balance["q1"]["accountsReceivableNetMillionTwd"], balance["accountsReceivableNetMillionTwd"]],
            "inventory": [balance["priorYear"]["inventoryMillionTwd"], balance["q1"]["inventoryMillionTwd"], balance["inventoryMillionTwd"]],
            "accountsPayable": [balance["priorYear"]["accountsPayableMillionTwd"], balance["q1"]["accountsPayableMillionTwd"], balance["accountsPayableMillionTwd"]],
        }
        working_capital_index = {
            key: [
                str((_d(value) / _d(values[0]) * Decimal("100")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
                for value in values
            ]
            for key, values in working_capital_amounts.items()
        }
        cash_warning_proxy = q2_cfo / _d(f["attributableProfitMillionTwd"]) * 100
        reported_effective_tax_rate = _d(f["incomeTaxExpenseMillionTwd"]) / _d(f["pretaxProfitMillionTwd"])
        q2_nopat = _d(f["operatingIncomeMillionTwd"]) * (Decimal("1") - reported_effective_tax_rate)
        q1_partial_operating_ic = _d(balance["q1"]["accountsReceivableNetMillionTwd"]) + _d(balance["q1"]["inventoryMillionTwd"]) + _d(balance["q1"]["propertyPlantEquipmentMillionTwd"]) - _d(balance["q1"]["accountsPayableMillionTwd"])
        q2_partial_operating_ic = _d(balance["accountsReceivableNetMillionTwd"]) + _d(balance["inventoryMillionTwd"]) + _d(balance["propertyPlantEquipmentMillionTwd"]) - _d(balance["accountsPayableMillionTwd"])
        average_partial_operating_ic = (q1_partial_operating_ic + q2_partial_operating_ic) / Decimal("2")
        q2_partial_roic = q2_nopat / average_partial_operating_ic * Decimal("100")
        formula_cards = [
            {"metric": "營運槓桿差", "whyItMatters": "檢查規模成長是否轉為更快的營業利益成長。", "formula": "營業利益年增率－營收年增率", "currentInputs": f"{operating_profit_yoy:.2f}%－{revenue_yoy:.2f}%", "currentResult": f"{operating_profit_yoy - revenue_yoy:.2f}個百分點", "plainLanguage": "營業利益成長快於營收，代表每一單位新增營收帶來更多營業利益。", "decisionUse": "判斷規模吸收是否出現，但不指定原因。", "limitation": "不能單獨區分成本吸收、產品組合、定價、自動化或匯率。"},
            {"metric": "營業費用代理值", "whyItMatters": "觀察毛利到營業利益之間的費用吸收。", "formula": "毛利－營業利益", "currentInputs": f"{f['grossProfitMillionTwd']}－{f['operatingIncomeMillionTwd']}百萬元", "currentResult": f"{q2_opex_proxy}百萬元；年增{opex_proxy_yoy:.2f}%", "plainLanguage": "營收大增時，毛利以下營業費用淨額代理值只小幅增加，與營益率改善一致。", "decisionUse": "比較營業費用代理值與營收成長速度。", "limitation": "這是依損益表結構推導的代理值，不是公司直接揭露的營業費用科目，更不是營業成本。"},
            {"metric": "自由現金流", "whyItMatters": "衡量本業現金扣除維持或擴張產能後可運用的資源。", "formula": "FCF＝CFO－Capex", "currentInputs": f"{q2_cfo}－{q2_capex}百萬元", "currentResult": f"{q2_fcf_direct}百萬元", "plainLanguage": "CFO代表本業真正產生的營運現金；Capex代表維持或擴大產能需要投入的資本支出；兩者相減後，才更接近公司可用於還債、配息、回購或再投資的自由資源。", "decisionUse": "檢查獲利是否真正轉為可分配或再投資的現金。", "limitation": "Q2單季由同口徑H1減Q1推導；簡報整數四捨五入造成1百萬元差異。"},
            {"metric": "CFO／歸母淨利警示代理值", "whyItMatters": "辨識獲利與營運現金的嚴重背離。", "formula": "合併CFO／歸屬母公司淨利", "currentInputs": f"{q2_cfo}／{f['attributableProfitMillionTwd']}百萬元", "currentResult": f"{q2_cfo / _d(f['attributableProfitMillionTwd']) * 100:.2f}%", "plainLanguage": "負值只表示獲利與現金方向背離，不能當成同口徑的標準現金轉化率。", "decisionUse": "配合營運資金與CCC判讀現金占用。", "limitation": "合併CFO與歸屬母公司淨利會計範圍不同，本指標只作警示代理值。"},
            {"metric": "ROIC", "whyItMatters": "衡量投入資本使用效率。", "formula": "NOPAT／平均部分營運投入資本", "currentInputs": f"Q2 NOPAT {q2_nopat.quantize(Decimal('1'))}百萬元；Q1/Q2部分營運投入資本平均{average_partial_operating_ic.quantize(Decimal('1'))}百萬元", "currentResult": f"單季估算{q2_partial_roic.quantize(Decimal('0.01'))}%", "plainLanguage": "以應收、存貨、營運用PP&E減應付帳款重建部分投入資本；回答這些可辨識營運資本使用效率。", "decisionUse": "作為部分營運投入資本估算，不取代官方同口徑ROIC。", "limitation": "所得稅率採本季帳面有效稅率，並非正常化營運稅率；未揭露的其他營運資產與無息負債未插補；單季年化不是TTM。"},
            {"metric": "增量ROIC", "whyItMatters": "衡量最近新增資本帶來多少新增稅後營業利益。", "formula": "NOPAT變化／投入資本變化", "currentInputs": "可比投入資本變化未提供", "currentResult": "INSUFFICIENT_DATA", "plainLanguage": "最近新增投入的資本，到底創造多少新的稅後營業利益。", "decisionUse": "驗證AI擴張的新增資本效率。", "limitation": "缺可比投入資本分母，不能估算。"},
            {"metric": "股東權益報酬率 ROE", "whyItMatters": "衡量累積股東資本創造淨利的效率。", "formula": "歸屬股東淨利／平均股東權益", "currentInputs": "官方2026H1 ROE 6.21%；2025H1 5.48%", "currentResult": "+0.73個百分點", "plainLanguage": "公司每使用1元股東自己的資本，能替股東創造多少淨利。", "decisionUse": "檢查BVPS增加是否同時帶來足夠獲利，並評估P/B的經濟支持。", "limitation": "ROE可能受利潤率、資產周轉或槓桿影響；缺完整DuPont時不能全歸因於營運改善。"},
            {"metric": "本益比", "whyItMatters": "描述市場為每1元盈餘支付多少價格。", "formula": "股價／每股盈餘", "currentInputs": f"{price_value}元／TTM EPS {ttm_eps}元", "currentResult": f"{(price_value / ttm_eps).quantize(Decimal('0.01'))}倍", "plainLanguage": "TTM本益比反映市場為過去12個月每1元EPS支付多少價格；Forward本益比是情境。", "decisionUse": "比較估值敏感度。", "limitation": "無Owner核准估值門檻，不判定便宜或昂貴。"},
            {"metric": "股價淨值比", "whyItMatters": "連結市場對股東資本的評價與ROE。", "formula": "股價／每股淨值", "currentInputs": f"股價{price_value}元；受治理BVPS {governed_bvps}元；正式P/B {pb_value}倍", "currentResult": f"{pb_value}倍", "plainLanguage": "P/B只有在ROE可持續且資本效率改善時，才獲得更強的經濟支持。", "decisionUse": "檢查BVPS累積與ROE是否同向改善。", "limitation": "無Owner核准門檻，不判定便宜、昂貴或形成交易規則。"},
            {"metric": "股息殖利率", "whyItMatters": "連結估值與退休現金流收益。", "formula": "年度股利／股價", "currentInputs": f"{dividend}元／{price_value}元", "currentResult": f"{dividend / price_value * 100:.2f}%", "plainLanguage": f"衡量{price_reader_label}對應的現金股利收益率。", "decisionUse": "評估退休現金流基線。", "limitation": "殖利率不等於股利可持續性；仍需FCF支持。"},
        ]
        strategy_scorecard = [
            {"strategicPillar": "電動車", "managementCommitment": "3+3三大新興產業", "currentCommercializationStage": "DEVELOPMENT", "currentRevenueEvidence": "Q2運算及其他產品占比5%，不能等同電動車", "currentProfitEvidence": "UNPROVEN", "capitalRequirementEvidence": "UNQUANTIFIED", "cashFlowEvidence": "UNPROVEN", "durability": "EVIDENCE_BUILDING", "competitorReplicability": "UNRESOLVED", "valueCreationStage": "DEVELOPMENT", "nextCheckpoint": "客戶／訂單與分部營收正式揭露"},
            {"strategicPillar": "數位健康", "managementCommitment": "3+3三大新興產業", "currentCommercializationStage": "STRATEGY", "currentRevenueEvidence": "NOT_SEPARATELY_DISCLOSED", "currentProfitEvidence": "UNPROVEN", "capitalRequirementEvidence": "UNQUANTIFIED", "cashFlowEvidence": "UNPROVEN", "durability": "UNRESOLVED", "competitorReplicability": "UNRESOLVED", "valueCreationStage": "STRATEGY", "nextCheckpoint": "正式商業化與財務揭露"},
            {"strategicPillar": "機器人", "managementCommitment": "3+3三大新興產業", "currentCommercializationStage": "DEVELOPMENT", "currentRevenueEvidence": "NOT_SEPARATELY_DISCLOSED", "currentProfitEvidence": "UNPROVEN", "capitalRequirementEvidence": "UNQUANTIFIED", "cashFlowEvidence": "UNPROVEN", "durability": "EVIDENCE_BUILDING", "competitorReplicability": "UNRESOLVED", "valueCreationStage": "DEVELOPMENT", "nextCheckpoint": "客戶／訂單與分部財務揭露"},
            {"strategicPillar": "人工智慧", "managementCommitment": "3+3三項新技術", "currentCommercializationStage": "REVENUE", "currentRevenueEvidence": "AI伺服器與Cloud & Networking推動Q2成長；精確AI占比未揭露", "currentProfitEvidence": "公司整體營業利益改善方向一致；AI特定金額未揭露", "capitalRequirementEvidence": "AI擴產存在資本需求，AI特定投入未揭露", "cashFlowEvidence": "AI特定現金流未揭露", "durability": "SUPPORTED_BY_GUIDANCE", "competitorReplicability": "UNRESOLVED", "valueCreationStage": "REVENUE", "nextCheckpoint": "FY2026 Q3 AI出貨、利潤率與現金轉化"},
            {"strategicPillar": "半導體", "managementCommitment": "3+3三項新技術", "currentCommercializationStage": "DEVELOPMENT", "currentRevenueEvidence": "NOT_SEPARATELY_DISCLOSED", "currentProfitEvidence": "UNPROVEN", "capitalRequirementEvidence": "UNQUANTIFIED", "cashFlowEvidence": "UNPROVEN", "durability": "EVIDENCE_BUILDING", "competitorReplicability": "UNRESOLVED", "valueCreationStage": "DEVELOPMENT", "nextCheckpoint": "正式商業化與財務揭露"},
            {"strategicPillar": "新世代通訊技術", "managementCommitment": "3+3三項新技術", "currentCommercializationStage": "DEVELOPMENT", "currentRevenueEvidence": "Cloud & Networking占比51%，不能全數歸因此技術", "currentProfitEvidence": "UNPROVEN", "capitalRequirementEvidence": "UNQUANTIFIED", "cashFlowEvidence": "UNPROVEN", "durability": "EVIDENCE_BUILDING", "competitorReplicability": "UNRESOLVED", "valueCreationStage": "DEVELOPMENT", "nextCheckpoint": "技術商業化與可歸屬財務揭露"},
        ]
        for item in strategy_scorecard:
            item.update({
                "officialStatus": "OFFICIAL_VERIFIED",
                "priorStage": "INSUFFICIENT_DATA",
                "currentStage": item["currentCommercializationStage"],
                "changeThisQuarter": "本次治理來源未提供可比前期階段；不推測升級",
                "capitalEfficiencyEvidence": "尚無可歸屬ROIC證據",
                "nextGate": "客戶／訂單→營收→營業利益→ROIC→FCF→股東回報逐級驗證",
            })
        enterprise_value_analytics = {
            "headline": "治理政策開始兌現，但真正的價值創造只完成前半程",
            "revenueMillionTwd": f["revenueMillionTwd"],
            "revenueProvenance": "OFFICIAL",
            "grossProfitMillionTwd": f["grossProfitMillionTwd"],
            "grossProfitProvenance": "OFFICIAL",
            "operatingProfitMillionTwd": f["operatingIncomeMillionTwd"],
            "operatingProfitProvenance": "OFFICIAL",
            "pretaxProfitMillionTwd": f["pretaxProfitMillionTwd"],
            "pretaxProfitProvenance": "OFFICIAL",
            "incomeTaxExpenseMillionTwd": f["incomeTaxExpenseMillionTwd"],
            "incomeTaxProvenance": "OFFICIAL",
            "grossProfitYoyPct": f"{gross_profit_yoy:.2f}",
            "operatingProfitYoyPct": f"{operating_profit_yoy:.2f}",
            "operatingLeverageSpreadPct": f"{operating_profit_yoy - revenue_yoy:.2f}",
            "grossProfitSpreadPct": f"{gross_profit_yoy - revenue_yoy:.2f}",
            "grossProfitLagPct": f"{revenue_yoy - gross_profit_yoy:.2f}",
            "profitGrowthPassThroughGapPct": f"{operating_profit_yoy - Decimal('35'):.2f}",
            "operatingExpenseProxyMillionTwd": str(q2_opex_proxy),
            "operatingExpenseProxyOrigin": "DERIVED_FROM_OFFICIAL",
            "operatingExpenseProxyYoyPct": f"{opex_proxy_yoy:.2f}",
            "operatingExpenseProxyRevenuePct": f"{q2_opex_proxy / _d(f['revenueMillionTwd']) * 100:.3f}",
            "revenueGrowthMinusOpexProxyGrowthPct": f"{revenue_yoy - opex_proxy_yoy:.2f}",
            "revenueGrowth2024Q2To2026Q2Pct": "63.0",
            "epsGrowth2024Q2To2026Q2Pct": "68.8",
            "grossMarginChange2024Q2To2026Q2Bps": "-30",
            "operatingMarginChange2024Q2To2026Q2Bps": "+87",
            "netMarginChange2024Q2To2026Q2Bps": "+11",
            "cashFlow2025Q1Cfo100mTwd": "-510.63465",
            "cashFlow2025Q1FcfCore100mTwd": "-948.98803",
            "cashFlow2026Q1Cfo100mTwd": str((_d(latest_cash["operating_cash_flow_thousand_ntd"]) / Decimal("100000")).quantize(Decimal("0.00001"))),
            "cashFlow2026Q1PpeCapex100mTwd": "357.74345",
            "cashFlow2026Q1FcfCore100mTwd": latest_cash["free_cash_flow_core_100m_ntd"],
            "cashFlow2026Q1CfoToOperatingProfitPct": "4.255495",
            "cashFlow2026Q1FcfToNetIncomePct": "-65.244872",
            "q2StandaloneCfoMillionTwd": str(q2_cfo),
            "q2StandaloneCfoFormula": "2026H1 CFO - 2026Q1 CFO",
            "q2StandaloneCapexMillionTwd": str(q2_capex),
            "q2StandaloneCapexFormula": "2026H1 Capex - 2026Q1 PP&E Capex",
            "q2StandaloneFcfMillionTwd": str(q2_fcf_direct),
            "q2StandaloneFcfFormula": "Q2 CFO - Q2 Capex",
            "q2StandaloneFcfCumulativeReconciliationMillionTwd": str(q2_fcf_cumulative),
            "q2StandaloneFcfRoundingDifferenceMillionTwd": str(q2_fcf_rounding_difference),
            "q2StandaloneFcfRoundingToleranceMillionTwd": str(q2_fcf_rounding_tolerance),
            "q2CashMetricOrigin": "DERIVED_FROM_OFFICIAL",
            "q2CashConfidence": "HIGH",
            "cashConversionStatus": "WEAK_VERIFIED_DERIVED_Q2",
            "fcfSupportStatus": "UNSUPPORTED_VERIFIED_DERIVED_Q2",
            "cashConversionMetric": "CFO／歸母淨利警示代理值",
            "cashConversionScope": "合併CFO／歸屬母公司淨利；非同一會計範圍，不是標準現金轉化率",
            "cashConversionClassification": "WARNING_PROXY_SCOPE_MISMATCH",
            "workingCapital": {
                "periods": working_capital_days["periods"],
                "accountsReceivableMillionTwd": [balance["priorYear"]["accountsReceivableNetMillionTwd"], balance["q1"]["accountsReceivableNetMillionTwd"], balance["accountsReceivableNetMillionTwd"]],
                "inventoryMillionTwd": [balance["priorYear"]["inventoryMillionTwd"], balance["q1"]["inventoryMillionTwd"], balance["inventoryMillionTwd"]],
                "accountsPayableMillionTwd": [balance["priorYear"]["accountsPayableMillionTwd"], balance["q1"]["accountsPayableMillionTwd"], balance["accountsPayableMillionTwd"]],
                "accountsReceivableDays": working_capital_days["accountsReceivableDays"],
                "inventoryDays": working_capital_days["inventoryDays"],
                "accountsPayableDays": working_capital_days["accountsPayableDays"],
                "cashConversionCycleDays": working_capital_days["cashConversionCycleDays"],
                "indexedTo2025Q2": working_capital_index,
                "assessment": "GROWTH_DRIVEN_ABSORPTION_WITH_EFFICIENCY_IMPROVEMENT",
            },
            "balanceSheetEvidence": {
                "periodEnd": balance["periodEnd"],
                "cashAndCashEquivalentsMillionTwd": balance["cashAndCashEquivalentsMillionTwd"],
                "derivedDebtMillionTwd": str(_d(balance["cashAndCashEquivalentsMillionTwd"]) - _d(balance["netCashMillionTwd"])),
                "netCashMillionTwd": balance["netCashMillionTwd"],
                "totalEquityMillionTwd": balance["totalEquityMillionTwd"],
                "liquidityAssessment": "NET_CASH_POSITIVE_CASH_BALANCE_AVAILABLE_CURRENT_RATIO_UNAVAILABLE",
                "classification": "OFFICIAL_AND_EXACT_DERIVED",
                "sourceIds": official_ids,
            },
            "investedCapitalBridge": {
                "periods": ["2026Q1", "2026Q2"],
                "accountsReceivableMillionTwd": [balance["q1"]["accountsReceivableNetMillionTwd"], balance["accountsReceivableNetMillionTwd"]],
                "inventoryMillionTwd": [balance["q1"]["inventoryMillionTwd"], balance["inventoryMillionTwd"]],
                "propertyPlantEquipmentMillionTwd": [balance["q1"]["propertyPlantEquipmentMillionTwd"], balance["propertyPlantEquipmentMillionTwd"]],
                "accountsPayableMillionTwd": [balance["q1"]["accountsPayableMillionTwd"], balance["accountsPayableMillionTwd"]],
                "cashTreatment": "EXCLUDED_FROM_OPERATING_INVESTED_CAPITAL",
                "marketableSecuritiesTreatment": "EXCLUDED_NOT_SEPARATELY_AVAILABLE",
                "debtTreatment": "FINANCING_SOURCE_EXCLUDED",
                "leaseTreatment": "EXCLUDED_NOT_SEPARATELY_AVAILABLE",
                "equityTreatment": "FINANCING_SOURCE_EXCLUDED",
                "otherAssetsLiabilitiesTreatment": "EXCLUDED_UNSUPPORTED_LINE_ITEMS",
                "methodology": "AVERAGE_OF_Q1_AND_Q2_PERIOD_END_PARTIAL_OPERATING_INVESTED_CAPITAL",
            },
            "capexIntensityRevenuePct": f"{q2_capex / _d(f['revenueMillionTwd']) * 100:.2f}",
            "capexToOperatingProfitPct": f"{q2_capex / _d(f['operatingIncomeMillionTwd']) * 100:.2f}",
            "governanceOperating": "PASS",
            "governanceCapital": "WHITE_INSUFFICIENT_DATA",
            "governanceCash": "FAIL_VERIFIED",
            "nopat": {
                "valueMillionTwd": str(q2_nopat),
                "formula": "Operating profit × (1 - reported accounting effective tax rate)",
                "taxRatePct": str(reported_effective_tax_rate * Decimal("100")),
                "classification": "T1_EXACT_DERIVED_REPORTED_EFFECTIVE_TAX_RATE_NOT_NORMALIZED",
            },
            "roic": {
                "quarterlyPartialOperatingIcEstimatePct": str(q2_partial_roic),
                "averagePartialOperatingInvestedCapitalMillionTwd": str(average_partial_operating_ic),
                "classification": "T2_ESTIMATED_DERIVED_PARTIAL_OPERATING_IC",
                "annualizedIsTtm": False,
            },
            "incrementalRoic": "INSUFFICIENT_DATA_COMPARABLE_INVESTED_CAPITAL",
            "roe": {
                "currentPeriod": "2026H1",
                "currentPct": "6.21",
                "comparablePeriod": "2025H1",
                "comparablePct": "5.48",
                "yoyChangePp": "+0.73",
                "fullYearBaselinePeriod": "2025FY",
                "fullYearBaselinePct": "11.3",
                "targetStatus": "NOT_VERIFIED",
                "sourceIds": official_ids + [authority_ids["master"]],
                "periodDiscipline": "H1只與H1比較；2025FY另列，不年化H1，也不與未驗證目標混比",
            },
            "bvps": {
                "currentValue": str(governed_bvps),
                "currentPeriod": latest_master["Quarter"],
                "provenance": "GOVERNED_AUTHORITY_DIRECT",
                "sourceId": authority_ids["master"],
                "periods": [row["Quarter"] for row in history_rows],
                "values": [row["BVPS"] for row in history_rows],
                "q2Status": "INSUFFICIENT_DATA",
            },
            "dupont": "PARTIAL_DUPONT_ASSET_TURNOVER_AND_LEVERAGE_UNAVAILABLE",
            "earningsQualitySpread": "Q2_DERIVED_FROM_OFFICIAL_COMPARABLE_PERIODS",
            "cashConversion": f"{cash_warning_proxy:.2f}%",
            "capexIntensity": "DERIVED_FROM_OFFICIAL_COMPARABLE_PERIODS",
            "profitPassThrough": "OFFICIAL_PRETAX_AND_TAX_AVAILABLE",
            "aiRevenueStatus": "SUPPORTED",
            "aiForwardGrowthStatus": "SUPPORTED_MANAGEMENT_GUIDANCE",
            "aiMaterialOperatingProfitContributionDirection": "PARTIALLY_PROVEN_HIGH_CONFIDENCE_INFERENCE",
            "aiOperatingProfitStatus": "UNPROVEN_SPECIFIC_AMOUNT",
            "aiSpecificMarginStatus": "UNPROVEN",
            "aiCapitalEfficiencyStatus": "UNPROVEN",
            "aiCashGenerationStatus": "UNPROVEN",
            "aiFcfContributionStatus": "UNPROVEN",
            "cloudNetworkingRevenueSharePct": product_mix["cloudAndNetworkingRevenueSharePct"],
            "aiSpecificRevenueShareStatus": product_mix["aiSpecificShareStatus"],
            "strategyFramework": strategy,
            "strategyFrameworkVerification": "PARTIAL_OFFICIAL_3_PLUS_3_VERIFIED_THIRD_3_NOT_VERIFIED",
            "strategyScorecard": strategy_scorecard,
            "strategyEvidenceGap": {
                "topic": "第三組『3』",
                "status": "NOT_VERIFIED",
                "renderLocation": "STRATEGY_EVIDENCE_GAP",
                "ownerWording": "本次受治理官方來源已完成3+3六項支柱驗證；第三組『3』尚未由本次治理來源完成正式驗證，因此不納入本季價值轉化評分。",
            },
            "strategyValueCreationStages": ["STRATEGY", "DEVELOPMENT", "CUSTOMER_ORDER", "REVENUE", "OPERATING_PROFIT", "ROIC", "FCF", "SHAREHOLDER_RETURN"],
            "managementOperatingModel": [
                {"theme": "規模", "managementClaim": "AI與雲端網路產品需求擴張並進入大規模量產。", "financialEvidence": "Q2營收年增40.84%，營業利益年增67.51%。", "counterevidence": "Q2毛利率年減21個基點。", "assessment": "SUPPORTED_WITH_MARGIN_CAVEAT"},
                {"theme": "垂直整合", "managementClaim": "元件、散熱、模組與系統整合可支援AI基礎設施交付。", "financialEvidence": "Cloud & Networking占Q2營收51%，但AI專屬占比未揭露。", "counterevidence": "缺少AI專屬營業利益、資本效率與現金流拆分。", "assessment": "PARTIALLY_SUPPORTED"},
                {"theme": "自動化", "managementClaim": "自動化與製造效率有助費用吸收。", "financialEvidence": f"營業費用代理值年增{opex_proxy_yoy:.2f}%，低於營收年增40.84%。", "counterevidence": "代理值不是正式費用科目橋接。", "assessment": "INFERRED_REQUIRES_DETAIL"},
                {"theme": "高價值產品組合", "managementClaim": "AI伺服器與高階雲網產品提高成長品質。", "financialEvidence": "營益率升至3.75%，營業利益增速高於營收。", "counterevidence": "毛利率降至6.12%，尚未證明產品組合提高毛利率。", "assessment": "MIXED_EVIDENCE"},
                {"theme": "共同開發", "managementClaim": "從共同設計到量產的協作可深化客戶關係。", "financialEvidence": "官方揭露AI rack後續出貨成長指引。", "counterevidence": "缺客戶留存、訂單期間與經濟利益分配數據。", "assessment": "STRATEGIC_CLAIM_FINANCIAL_PROOF_PENDING"},
                {"theme": "技術平台", "managementClaim": "3+3平台可擴張長期價值來源。", "financialEvidence": "六個官方支柱已核對；Q2財務貢獻未逐支柱揭露。", "counterevidence": "不存在經核准證據支持額外的第三組『3』。", "assessment": "FRAMEWORK_VERIFIED_MONETIZATION_UNPROVEN"},
            ],
            "formulaCards": formula_cards,
            "finalResearchConclusion": {
                "whatChanged": "FY2026 Q2不只證明營收成長，也證明營業利益增速顯著快於營收；八季營業費用代理值占營收由約3.2%降至2.365%，營運端規模吸收具可信財務證據。",
                "whatNotProven": "Q2尚未證明AI特定利潤率、Q2 ROIC、完整DuPont、正向自由現金流、正常化股利能力或退休現金流安全邊際上升。",
                "governanceDelivery": "管理層規模、整合與效率敘事已在營業利益端獲得部分兌現；3+3六支柱已核對，第三組『3』仍是獨立證據缺口。",
                "strategyValueCreation": "人工智慧已到營收證據，公司整體營業利益方向亦改善；但AI專屬營業利益、ROIC、現金轉化與FCF尚未揭露。",
                "roeBvpsCompounding": "官方2026H1 ROE 6.21%，高於2025H1的5.48%；受治理BVPS截至2026Q1為127.12元。這支持股東資本效率改善方向，但Q2 BVPS與完整DuPont仍缺，不能把ROE改善全部歸因於營運。",
                "cashOpenQuestion": "Q2 CFO與FCF為負，但CCC由48天降至44天再降至42天；現有證據較符合高速擴張造成的營運資金占用加上資本支出，而非已證實的週轉效率惡化，後續現金回收仍未證明。",
                "enterpriseValueProgress": "企業價值論點已由營收推進至營業利益與可比H1 ROE證據，但尚未完整通過ROIC、自由現金流、股利能力及退休現金流安全。",
                "invalidationConditions": "若AI相關出貨成長而毛利率與營益率同步惡化、營運資金長期快於營收、Capex上升卻未改善增量ROIC，或CFO／FCF持續未跟上獲利，則目前『規模開始轉為營運槓桿』的解讀失效。",
                "nextOneToFourQuarterPriority": "依序驗證Q3毛利率與營益率耐久度、營運資金回收、Q2／TTM ROIC、ROE與BVPS延續性、全年FCF及股利政策。",
                "retirementMissionJudgment": "核心論點存續，但估值安全、退休現金流安全與股利能力都不得因本季營收及EPS成長而自動上修；真正的退休任務升級仍需ROE／BVPS複利與正常化FCF共同支持。",
            },
            "futureCheckpoints": [
                {"priority": 1, "metric": "毛利率與營益率", "whyItMatters": "判斷費用槓桿是否可持續且未以毛利惡化為代價。", "currentBaseline": "FY2026 Q2毛利率6.12%、營益率3.75%。", "improvementCondition": "毛利率不再下滑且營益率維持或提高。", "deteriorationCondition": "毛利率與營益率同步下降。", "nextExpectedDisclosure": "FY2026 Q3財報／法說"},
                {"priority": 2, "metric": "營運資金與CFO", "whyItMatters": "驗證帳面獲利能否轉為營運現金。", "currentBaseline": f"Q2推導CFO {q2_cfo}百萬元、CCC 42天。", "improvementCondition": "單季CFO轉正且CCC不惡化。", "deteriorationCondition": "CFO持續為負或應收、存貨天數反轉上升。", "nextExpectedDisclosure": "FY2026 Q3現金流量表"},
                {"priority": 3, "metric": "自由現金流", "whyItMatters": "決定成長是否能自我融資並支撐股東回報。", "currentBaseline": f"Q2推導FCF {q2_fcf_direct}百萬元。", "improvementCondition": "TTM FCF轉正且不依賴一次性營運資金釋放。", "deteriorationCondition": "全年FCF持續為負。", "nextExpectedDisclosure": "FY2026 Q3／全年現金流量表"},
                {"priority": 4, "metric": "TTM ROIC與增量ROIC", "whyItMatters": "判斷AI擴張是否創造超越資金成本的企業價值。", "currentBaseline": "資料不足，未計算。", "improvementCondition": "可比投入資本與標準化NOPAT足以計算且報酬改善。", "deteriorationCondition": "投入資本增幅高於NOPAT且增量ROIC下降。", "nextExpectedDisclosure": "正式Q2財報補充資料與FY2026 Q3"},
                {"priority": 5, "metric": "AI專屬獲利與現金轉化", "whyItMatters": "區分AI相關業務成長與AI實際價值創造。", "currentBaseline": "AI方向性獲利貢獻為高信心推論，專屬金額與利潤率未揭露。", "improvementCondition": "官方提供可核對的AI獲利、資本效率或現金流證據。", "deteriorationCondition": "AI相關業務成長但合併毛利、ROIC與FCF惡化。", "nextExpectedDisclosure": "後續季報／法說"},
                {"priority": 6, "metric": "股利能力", "whyItMatters": "連結企業價值與退休現金流安全。", "currentBaseline": "正常化FCF與資本需求橋接不足。", "improvementCondition": "正常化FCF覆蓋股利與必要資本支出。", "deteriorationCondition": "股利依賴資產負債表或外部融資支應。", "nextExpectedDisclosure": "FY2026全年財報與董事會股利政策"},
            ],
            "retirementMission": {
                "thesisSurvival": "SURVIVES",
                "valuationSafety": "NOT_IMPROVED",
                "cashflowSafety": "NOT_PROVEN",
                "dividendCapacity": "NOT_UPGRADED_WITHOUT_NORMALIZED_FCF",
                "shareholderEquityCompounding": "IMPROVING_INTERIM_ROE_BUT_Q2_BVPS_PENDING",
                "explanation": "論點存續、估值安全性與現金流安全性是三個不同問題；本期只支持第一項。",
            },
            "valueChain": ["Management Commitment", "Strategy", "Execution", "Revenue", "Gross Profit", "Operating Profit", "NOPAT", "ROIC", "Net Income", "ROE", "BVPS / Equity Compounding", "CFO", "FCF", "Dividend Capacity", "Shareholder Return", "Retirement Cashflow Safety"],
            "valueChainEvidenceMatrix": [
                {"link": "Management Commitment", "grade": "PARTIALLY_PROVEN", "evidence": "3+3六項支柱由受治理官方來源核對", "limitation": "第三組『3』未驗證", "enterpriseValueImplication": "治理承諾可追蹤", "nextCheckpoint": "後續正式策略揭露"},
                {"link": "Strategy", "grade": "PARTIALLY_PROVEN", "evidence": "人工智慧支柱已到營收階段", "limitation": "其他支柱財務證據有限", "enterpriseValueImplication": "策略價值轉化不均", "nextCheckpoint": "逐支柱正式財務揭露"},
                {"link": "Execution", "grade": "PROVEN", "evidence": "營業利益增速高於營收且費用代理比下降", "limitation": "因果來源未完整拆分", "enterpriseValueImplication": "規模吸收已出現", "nextCheckpoint": "FY2026 Q3營益率與費用吸收"},
                {"link": "Revenue", "grade": "PROVEN", "evidence": "FY2026 Q2營收及年增率由官方Results揭露", "limitation": "不單獨代表獲利或現金改善", "enterpriseValueImplication": "規模成長已確認", "nextCheckpoint": "FY2026 Q3營收與財報"},
                {"link": "Gross Profit", "grade": "PROVEN", "evidence": "FY2026 Q2毛利154,533百萬元由官方Results直接揭露", "limitation": "毛利率年減21個基點，毛利護城河未擴張", "enterpriseValueImplication": "毛利成長落後營收", "nextCheckpoint": "FY2026 Q3毛利率"},
                {"link": "Operating Profit", "grade": "PROVEN", "evidence": "FY2026 Q2營業利益94,803百萬元由官方Results直接揭露", "limitation": "完整費用科目橋接未揭露", "enterpriseValueImplication": "毛利以下轉化效率改善", "nextCheckpoint": "FY2026 Q3營益率與費用吸收"},
                {"link": "NOPAT", "grade": "INSUFFICIENT_DATA", "evidence": "尚無可用標準化稅率", "limitation": "不能以歸屬淨利替代", "enterpriseValueImplication": "無法計算稅後營業報酬", "nextCheckpoint": "正式Q2財務報告"},
                {"link": "ROIC", "grade": "INSUFFICIENT_DATA", "evidence": "缺Q2同口徑投入資本", "limitation": "舊期ROIC不可外推", "enterpriseValueImplication": "資本效率改善未證實", "nextCheckpoint": "正式Q2資產負債表"},
                {"link": "Net Income", "grade": "PROVEN", "evidence": "Q2歸屬母公司淨利59,974百萬元", "limitation": "不等同NOPAT或現金", "enterpriseValueImplication": "股東獲利端改善", "nextCheckpoint": "FY2026 Q3淨利"},
                {"link": "ROE", "grade": "PROVEN", "evidence": "官方2026H1 ROE 6.21%，2025H1 5.48%", "limitation": "缺完整DuPont，不能全歸因營運", "enterpriseValueImplication": "股東資本效率同比改善", "nextCheckpoint": "FY2026全年ROE與DuPont分解"},
                {"link": "BVPS / Equity Compounding", "grade": "PARTIALLY_PROVEN", "evidence": "受治理BVPS截至2026Q1為127.12元", "limitation": "FY2026 Q2直接BVPS未提供", "enterpriseValueImplication": "股東資本複利方向可追蹤", "nextCheckpoint": "正式Q2 BVPS與ROE"},
                {"link": "CFO", "grade": "PROVEN_DERIVED", "evidence": f"同口徑2026H1減2026Q1推導Q2 CFO {q2_cfo}百萬元", "limitation": "由官方累計數相減，受簡報整數四捨五入影響", "enterpriseValueImplication": "獲利未轉為營運現金", "nextCheckpoint": "FY2026 Q3／全年CFO"},
                {"link": "FCF", "grade": "PROVEN_DERIVED", "evidence": f"Q2 CFO減Capex推導FCF {q2_fcf_direct}百萬元", "limitation": "兩條推導路徑差1百萬元並已在容許範圍內揭露", "enterpriseValueImplication": "現金治理尚未通過", "nextCheckpoint": "FY2026 Q3／全年FCF"},
                {"link": "Dividend Capacity", "grade": "UNPROVEN", "evidence": "既有股利輸入可得", "limitation": "缺正常化FCF與資本需求橋接", "enterpriseValueImplication": "股利能力不可上修", "nextCheckpoint": "FY2026全年FCF與股利政策"},
                {"link": "Shareholder Return", "grade": "INSUFFICIENT_DATA", "evidence": ("市場資料截止早於結果發布" if is_pre_event_price else "市場資料已涵蓋結果發布後，但尚未完成受治理事件窗口歸因"), "limitation": "缺完整基準調整事件窗口與資本回報橋接", "enterpriseValueImplication": "市場重估尚不能單獨歸因於本次財報", "nextCheckpoint": "完整基準調整事件窗口"},
                {"link": "Retirement Cashflow Safety", "grade": "UNPROVEN", "evidence": "核心持有論點尚未失效", "limitation": "論點存續不等於安全性已證實", "enterpriseValueImplication": "安全邊際不提高", "nextCheckpoint": "Q2現金流、ROIC及後續股利能力"},
            ],
        }
        provenance_by_link = {
            "Management Commitment": "OFFICIAL", "Strategy": "OFFICIAL",
            "Execution": "MIXED_OFFICIAL_AND_DERIVED",
            "Revenue": "OFFICIAL", "Gross Profit": "OFFICIAL",
            "Operating Profit": "OFFICIAL", "NOPAT": "INSUFFICIENT_DATA",
            "ROIC": "INSUFFICIENT_DATA", "Net Income": "OFFICIAL",
            "ROE": "OFFICIAL", "BVPS / Equity Compounding": "GOVERNED_AUTHORITY",
            "CFO": "DERIVED_FROM_OFFICIAL",
            "FCF": "DERIVED_FROM_OFFICIAL", "Dividend Capacity": "INFERENCE",
            "Shareholder Return": "INSUFFICIENT_DATA",
            "Retirement Cashflow Safety": "INFERENCE",
        }
        trend_by_link = {
            "Management Commitment": "TRACKING", "Strategy": "PARTIAL_MONETIZATION",
            "Execution": "IMPROVING",
            "Revenue": "IMPROVING", "Gross Profit": "IMPROVING_BUT_LAGGING_REVENUE",
            "Operating Profit": "IMPROVING_FASTER_THAN_REVENUE", "NOPAT": "UNRESOLVED",
            "ROIC": "UNRESOLVED", "Net Income": "IMPROVING", "ROE": "IMPROVING_COMPARABLE_H1",
            "BVPS / Equity Compounding": "RISING_THROUGH_2026Q1", "CFO": "WEAKENING", "FCF": "WEAKENING",
            "Dividend Capacity": "WATCH", "Shareholder Return": "UNRESOLVED",
            "Retirement Cashflow Safety": "THESIS_SURVIVES_SAFETY_NOT_IMPROVED",
        }
        for row in enterprise_value_analytics["valueChainEvidenceMatrix"]:
            row["evidenceStatus"] = row["grade"]
            row["provenance"] = provenance_by_link[row["link"]]
            row["currentEvidence"] = row["evidence"]
            row["trend"] = trend_by_link[row["link"]]
            row["valueImplication"] = row["enterpriseValueImplication"]
        governance_signals = [
            {"signal": "GREEN", "advantage": "AI基礎設施規模與整合能力", "source_of_advantage": "共同開發、系統整合與量產能力", "history": "Q2 AI／Cloud & Networking營收規模與後續成長指引", "durability": "EVIDENCE_BUILDING", "competitor_replicability": "尚未由本次證據證明可快速複製", "capital_requirement": "AI產能與供應鏈整合需要資本", "cash_conversion": "AI特定現金轉化尚未證實", "invalidation_condition": "後續AI出貨未按指引轉化", "next_checkpoint": "FY2026 Q3官方財報", "skill_mode": "SKILL_GUIDED_ONLY", "actionable": False},
            {"signal": "YELLOW", "what_happened": "毛利率下降而營益率上升", "trend": "營益率改善、毛利率承壓", "divergence": "營業利益成長高於營收，毛利成長低於營收", "root_cause": "較符合規模吸收與費用槓桿，產品組合仍待驗", "management_explanation": "公司指引AI與雲網需求強勁", "supporting_evidence": "Q2營收、毛利率與營益率官方結果", "counterevidence": "毛利率季減6個基點、年減21個基點", "temporary_vs_structural": "UNCERTAIN", "enterprise_value_impact": "需確認費用槓桿能否轉為資本效率", "retirement_mission_impact": "暫不改變HOLD，但提高現金轉化驗證優先序", "clear_condition": "毛利率穩定且ROIC、FCF改善", "deterioration_condition": "營益率回落且現金流持續為負", "next_checkpoint": "FY2026 Q3官方財報", "confidence": "MEDIUM", "skill_mode": "SKILL_GUIDED_ONLY", "actionable": False},
            {"signal": "WHITE", "missing_data": "Q2可比平均投入資本、標準化NOPAT、完整DuPont分母及AI特定獲利／現金流", "why_it_matters": "決定AI成長是否提高ROIC與退休現金流安全", "acquisition_path": "正式財務報告與後續季報", "next_calculation": "TTM ROIC、增量ROIC、DuPont與AI現金轉化", "next_checkpoint": "FY2026 Q3／全年正式財務揭露", "skill_mode": "SKILL_GUIDED_ONLY", "actionable": False},
        ]
        q2 = QuarterlyEarningsAnalysis(
            fiscal_period=q["fiscalPeriod"],
            revenue=QuarterlyMetric(value=f["revenueMillionTwd"], unit="新台幣百萬元", period=q["fiscalPeriod"], qoq=f"{f['revenueQoqPct']}%", yoy=f"{f['revenueYoyPct']}%", evidence_ids=official_ids),
            gross_margin=QuarterlyMetric(value=f["grossMarginPct"], unit="%", period=q["fiscalPeriod"], qoq=f"{f['grossMarginQoqBps']} bps", yoy=f"{f['grossMarginYoyBps']} bps", evidence_ids=official_ids),
            operating_margin=QuarterlyMetric(value=f["operatingMarginPct"], unit="%", period=q["fiscalPeriod"], qoq=f"{f['operatingMarginQoqBps']} bps", yoy=f"{f['operatingMarginYoyBps']} bps", evidence_ids=official_ids),
            net_margin=QuarterlyMetric(value=f["netMarginPct"], unit="%", period=q["fiscalPeriod"], qoq=f"{f['netMarginQoqBps']} bps", yoy=f"{f['netMarginYoyBps']} bps", evidence_ids=official_ids),
            attributable_profit=QuarterlyMetric(value=f["attributableProfitMillionTwd"], unit="新台幣百萬元", period=q["fiscalPeriod"], qoq="20%", yoy="35%", evidence_ids=official_ids),
            eps=QuarterlyMetric(value=f["epsTwd"], unit="元", period=q["fiscalPeriod"], qoq=f"{f['epsQoqPct']}%", yoy=f"{f['epsYoyPct']}%", evidence_ids=official_ids),
            business_disclosures=q["businessDisclosures"],
            ai_server_cloud_networking=q["aiCloudNetworking"],
            official_outlook=q["officialOutlook"],
            apple_iphone_exposure_status="REVIEW_REQUIRED",
            fx_tariff_policy_risk_status="REVIEW_REQUIRED",
            cash_flow_period=cf["period"],
            cash_flow_status=cf["status"],
            free_cash_flow_status="OFFICIAL_H1_UPDATED",
            source_receipt=quarterly_packet.event["provenance"]["receipt_path"],
            source_hash=q["expectedSourceSha256"],
            source_pages=q["sourcePages"],
            limitations=[
                "Q2 standalone cash flow is derived from comparable official H1 minus official Q1 inputs; the two FCF paths differ by 1 million TWD due to presentation rounding.",
                "Apple/iPhone, FX, tariff and policy-risk values are not quantified in the Results document.",
            ],
            enterprise_value_analytics=enterprise_value_analytics,
            valuation_scenarios=valuation_scenarios,
            quarterly_history=history,
            governance_signals=governance_signals,
        )
        financial = FinancialTrend(
            revenue=self._metric(f["revenueMillionTwd"], "新台幣百萬元", q["fiscalPeriod"], TrendStatus.IMPROVING, official_ids),
            gross_margin=self._metric(f["grossMarginPct"], "%", q["fiscalPeriod"], TrendStatus.WATCH, official_ids, ["QoQ -6 bps；YoY -21 bps。"]),
            operating_margin=self._metric(f["operatingMarginPct"], "%", q["fiscalPeriod"], TrendStatus.IMPROVING, official_ids),
            eps=self._metric(f["epsTwd"], "元", q["fiscalPeriod"], TrendStatus.IMPROVING, official_ids),
            eps_ttm=self._metric(latest_master["EPS_TTM"], "元", f"正式authority至{latest_master['Quarter']}", TrendStatus.STABLE, [authority_ids["master"]], ["尚未把FY2026 Q2換入TTM，P/E只可作舊基線。"]),
            roe=self._metric("6.21", "%", "2026H1", TrendStatus.IMPROVING, official_ids),
            roic=self._metric(latest_master["ROIC_Precise_Pct"], "%", latest_master["Quarter"], TrendStatus.STABLE, [authority_ids["master"]]),
            operating_cash_flow=self._metric(str(q2_cfo), "新台幣百萬元", q["fiscalPeriod"], TrendStatus.WEAKENING, official_ids + [authority_ids["cash"]], ["DERIVED_FROM_OFFICIAL: 2026H1 CFO minus 2026Q1 CFO under the same consolidated TWD scope."]),
            free_cash_flow=self._metric(str(q2_fcf_direct), "新台幣百萬元", q["fiscalPeriod"], TrendStatus.WEAKENING, official_ids + [authority_ids["cash"]], [f"DERIVED_FROM_OFFICIAL; cumulative-path reconciliation difference {q2_fcf_rounding_difference} million TWD within documented rounding tolerance."]),
            dividend_safety=self._metric(latest_master["CashDividend"], "元／股", latest_master["Quarter"], TrendStatus.WATCH, [authority_ids["master"], result_id], ["H1 negative FCF requires observation but does not prove structural dividend impairment."]),
            balance_sheet_safety=self._metric("219809", "新台幣百萬元淨現金", q["fiscalPeriod"], TrendStatus.STABLE, official_ids),
        )
        publication = date.fromisoformat(q["publicationDate"])
        event_reaction = EventWindowReaction(
            status=EventWindowStatus.INSUFFICIENT_DATA,
            publication_date=publication,
            return_windows={},
            benchmark_adjusted_return=None,
            limitations=[
                ("Market authority ends before the results event." if is_pre_event_price else "Post-event market authority exists, but a governed benchmark-adjusted event window has not been completed."),
                "No governed benchmark-adjusted return is available.",
            ],
        )
        conditions = [
            RegimeCondition(condition_id="OFFICIAL_QUARTERLY_RESULTS", description="Official Q2 results are hash-bound and validated.", result="PASS", evidence_ids=official_ids),
            RegimeCondition(condition_id="PROFIT_CONVERSION_VERIFIED", description="Revenue, margins, attributable profit and EPS are disclosed.", result="PASS", evidence_ids=official_ids),
            RegimeCondition(condition_id="EVENT_WINDOW_AVAILABLE", description="Complete post-results price window is available.", result="INSUFFICIENT_DATA", evidence_ids=[authority_ids["price"]]),
        ]
        return AnalysisPacket(
            run_id=run_id,
            event_type="QUARTERLY_EARNINGS",
            generated_at_utc=generated_at_utc,
            authority_manifest_sha256=sha256_file(manifest_path),
            authority_file_hashes=hashes,
            authority_data_cutoffs=cutoffs,
            input_evidence_hashes=evidence_hashes,
            financial_trend=financial,
            quarterly_earnings=q2,
            valuation_analysis=ValuationAnalysis(current_price=latest_price["Close"], current_pb=latest_price["PB_daily"], governed_historical_pb_position=f"{pb_percentile:.1f} percentile within {len(pbs)} governed observations", roe_support=TrendStatus.IMPROVING, earnings_support=TrendStatus.IMPROVING, valuation_status=ValuationStatus.DESCRIPTIVE_ONLY, valuation_policy_id=None, data_window=f"{price.rows[0]['Date']}..{latest_price['Date']}", limitations=[f"The report-cutoff market price is classified as {valuation_state} by comparing price date {latest_price['Date']} with earnings event date {q['publicationDate']}.", "Q4 2025 basic EPS is normalized in the research layer to the official Results value of 3.23 without mutating the master authority.", "P/S uses TTM revenue and an estimated compatible weighted-average-share denominator and is classified T2."]),
            price_and_market_activity=PriceAndMarketActivity(price_trend=TrendStatus.IMPROVING if _d(returns["20D"]) > 0 else TrendStatus.WATCH, recent_price_context=RecentPriceContext(return_windows=returns, data_window=f"{price.rows[0]['Date']}..{latest_price['Date']}"), event_window_reaction=event_reaction, volume_trend=TrendStatus.IMPROVING if volume_ratio and volume_ratio >= 1 else TrendStatus.WATCH, volume_percentile=f"{volume_percentile:.1f}%", transaction_activity=f"{latest_activity['transaction_count']}筆；成交量為20日均量的{volume_ratio:.2f}倍", abnormal_activity_flag=bool(volume_ratio and volume_ratio >= Decimal('1.5')), data_limitations=[("Market authority ends before the official results publication date." if is_pre_event_price else "Market authority extends beyond the results publication date, but event attribution is not yet governed."), "Volume cannot identify investor intent."]),
            market_regime=MarketRegime(primary_regime=MarketRegimeName.INSUFFICIENT_DATA, evidence_ids=source_ids, confidence=ConfidenceClass.LOW, evaluated_conditions=conditions, alternative_regime=MarketRegimeName.EARNINGS_REASSESSMENT, invalidation_condition="A complete governed post-results price window may permit earnings-reassessment classification."),
            market_psychology=MarketPsychology(interpretation="Official earnings improved, but the market reaction cannot yet be attributed to the event without a governed benchmark-adjusted window.", evidence_basis=official_ids + [authority_ids["price"], authority_ids["activity"]], alternative_explanation="Price and volume may reflect broader market, positioning or anticipation effects.", counter_evidence=[("The governed market data ends before the results publication." if is_pre_event_price else "Post-event market data exists, but causal attribution and benchmark adjustment remain incomplete.")], confidence=ConfidenceClass.LOW, invalidation_condition="Reassess after a complete governed benchmark-adjusted event window is available."),
            event_impact_chain=self._impact_chain(official_ids, authority_ids),
            thesis_scorecard=ThesisScorecard(earnings_quality=TrendStatus.IMPROVING, ai_monetization=TrendStatus.IMPROVING, dividend_safety=TrendStatus.WATCH, balance_sheet=TrendStatus.STABLE, valuation=TrendStatus.WATCH, overall_thesis=OverallThesis.MAINTAINED, evidence_ids=source_ids),
            investor_views=InvestorViews(new_money_view=NewMoneyView.WAIT, existing_holding_view=ExistingHoldingView.HOLD, trim_review="NOT_TRIGGERED", sell_review="NOT_TRIGGERED", rationale="Q2 earnings and AI outlook support the thesis, while H1 negative FCF, stale valuation denominators and incomplete event reaction require WATCH/OBSERVE rather than a trading instruction.", actionable=False),
            audience_lenses=[AudienceLens(lens_id="ACCUMULATION_35_45", narrative="Observe whether AI growth converts into sustained margins and cash flow.", decision_focus="growth conversion and valuation discipline"), AudienceLens(lens_id="RETIREMENT_TRANSITION_46_60", narrative="Balance improved earnings against negative H1 FCF and event volatility.", decision_focus="cash conversion and drawdown tolerance"), AudienceLens(lens_id="RETIREMENT_INCOME_60_PLUS", narrative="Dividend durability requires updated full-year cash-flow evidence.", decision_focus="income durability and capital preservation")],
            material_conclusions=self._conclusions(q2, official_ids, authority_ids, q["publicationDate"]),
            source_evidence_ids=source_ids,
            actionable=False,
        )

    @staticmethod
    def _impact_chain(official_ids: list[str], authority_ids: dict[str, str]) -> list[EventImpactLink]:
        return [
            EventImpactLink(from_node="AI/cloud demand", to_node="revenue", status=LinkStatus.VERIFIED, explanation="Official Q2 revenue and AI/cloud-networking commentary confirm scale growth.", evidence_ids=official_ids),
            EventImpactLink(from_node="revenue", to_node="gross margin", status=LinkStatus.VERIFIED, explanation="Revenue increased while gross margin was 6.12%, down QoQ and YoY in basis points.", evidence_ids=official_ids),
            EventImpactLink(from_node="gross margin", to_node="operating margin", status=LinkStatus.INFERRED, explanation="Operating margin improved to 3.75%; scale, expense absorption and mix are compatible explanations, but the source is not attributable without a cost bridge.", evidence_ids=official_ids),
            EventImpactLink(from_node="operating margin", to_node="EPS", status=LinkStatus.VERIFIED, explanation="Q2 EPS was NT$4.27, up QoQ and YoY.", evidence_ids=official_ids),
            EventImpactLink(from_node="EPS", to_node="cash flow", status=LinkStatus.VERIFIED, explanation="H1 operating cash flow and FCF were negative; this is cumulative H1, not standalone Q2.", evidence_ids=official_ids),
            EventImpactLink(from_node="cash flow", to_node="valuation/thesis", status=LinkStatus.INFERRED, explanation="Earnings support and negative H1 FCF coexist; valuation stays descriptive and the thesis remains under observation.", evidence_ids=official_ids + [authority_ids["price"], authority_ids["cash"]]),
        ]

    @staticmethod
    def _conclusions(q2: QuarterlyEarningsAnalysis, official_ids: list[str], authority_ids: dict[str, str], publication: str) -> list[MaterialConclusion]:
        valuation_state = q2.valuation_scenarios["valuationTimeBasis"]["valuationState"]
        valuation_context_zh = "財報公布前估值脈絡" if valuation_state == "PRE_EVENT_VALUATION_CONTEXT" else "財報公布後報告截止日估值脈絡"
        return [
            MaterialConclusion(conclusion_id="C-Q2-EARNINGS", statement=f"FY2026 Q2 revenue was {q2.revenue.value} million TWD ({q2.revenue.qoq} QoQ, {q2.revenue.yoy} YoY), operating margin {q2.operating_margin.value}% and EPS {q2.eps.value} TWD.", fact_or_inference=FactOrInference.FACT, evidence_ids=official_ids, source_tier="OFFICIAL_COMPANY_INVESTOR_RELATIONS", source_date=publication, data_cutoff="2026-06-30", confidence=ConfidenceClass.HIGH, alternative_explanation="Year-over-year growth may include base and product-mix effects.", counter_evidence=[f"Gross margin was {q2.gross_margin.qoq} QoQ and {q2.gross_margin.yoy} YoY."], missing_evidence=["audited/reviewed quarterly financial report"], invalidation_condition="Withdraw if the company issues corrected results.", next_validation_event="FY2026 Q2 official financial report / next quarterly earnings"),
            MaterialConclusion(conclusion_id="C-Q2-AI-OUTLOOK", statement="Official guidance describes strong AI infrastructure demand, high-double-digit 3Q26 AI rack shipment growth QoQ and more-than-multiple AI server revenue growth.", fact_or_inference=FactOrInference.FACT, evidence_ids=official_ids, source_tier="OFFICIAL_COMPANY_INVESTOR_RELATIONS", source_date=publication, data_cutoff=publication, confidence=ConfidenceClass.HIGH, alternative_explanation="Guidance is forward-looking and may not convert at the stated pace.", counter_evidence=["The Results document does not quantify customer-specific Apple/iPhone or policy impacts."], missing_evidence=["realized 3Q26 AI shipment and revenue mix"], invalidation_condition="Reassess if subsequent official guidance is reduced or shipments do not convert.", next_validation_event="FY2026 Q3 official earnings"),
            MaterialConclusion(conclusion_id="C-Q2-CASH-VALUATION", statement=f"Official {q2.cash_flow_period} FCF was negative; Q2-updated TTM P/E and estimated P/S are descriptive {valuation_context_zh}, not a valuation decision.", fact_or_inference=FactOrInference.MIXED if hasattr(FactOrInference, 'MIXED') else FactOrInference.INFERENCE, evidence_ids=official_ids + [authority_ids["master"], authority_ids["price"], authority_ids["cash"]], source_tier="MIXED_OFFICIAL_AND_GOVERNED_AUTHORITY", source_date=publication, data_cutoff=publication, confidence=ConfidenceClass.MEDIUM, alternative_explanation="Working-capital and capex timing can depress cumulative H1 FCF.", counter_evidence=["Q2 attributable profit and EPS improved strongly."], missing_evidence=["complete benchmark-adjusted event window", "direct same-period weighted-average shares", "official same-basis Q2 ROIC"], invalidation_condition="Update after the official financial report and refreshed governed valuation/event-window authority.", next_validation_event="Official Q2 financial report and complete post-results market window"),
        ]

    @staticmethod
    def _metric(value: str, unit: str, period: str, status: TrendStatus, evidence_ids: list[str], limitations: list[str] | None = None) -> MetricAssessment:
        return MetricAssessment(value=value, unit=unit, period=period, status=status, evidence_ids=evidence_ids, limitations=limitations or [])

    @staticmethod
    def _cutoff(entry: dict[str, object]) -> str:
        for key in ("cutoffDate", "financialCutoffPeriod"):
            if entry.get(key):
                return str(entry[key])
        for key in ("dateRange", "periodRange"):
            value = entry.get(key)
            if isinstance(value, dict) and value.get("end"):
                return str(value["end"])
        return "DECLARED_IN_AUTHORITY_FILE"

    @staticmethod
    def _safe(value: str) -> str:
        return "".join(character for character in value.upper() if character.isalnum()) or "UNDECLARED"
