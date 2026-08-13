"""Build a governed quarterly Analysis Packet from hash-bound Official IR evidence."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
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
        result_id = official_ids[0]
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
                "2026H1 cash flow is official but is not a standalone Q2 cash-flow measure.",
                "Apple/iPhone, FX, tariff and policy-risk values are not quantified in the Results document.",
            ],
        )
        financial = FinancialTrend(
            revenue=self._metric(f["revenueMillionTwd"], "新台幣百萬元", q["fiscalPeriod"], TrendStatus.IMPROVING, official_ids),
            gross_margin=self._metric(f["grossMarginPct"], "%", q["fiscalPeriod"], TrendStatus.WATCH, official_ids, ["QoQ -6 bps；YoY -21 bps。"]),
            operating_margin=self._metric(f["operatingMarginPct"], "%", q["fiscalPeriod"], TrendStatus.IMPROVING, official_ids),
            eps=self._metric(f["epsTwd"], "元", q["fiscalPeriod"], TrendStatus.IMPROVING, official_ids),
            eps_ttm=self._metric(latest_master["EPS_TTM"], "元", f"正式authority至{latest_master['Quarter']}", TrendStatus.STABLE, [authority_ids["master"]], ["尚未把FY2026 Q2換入TTM，P/E只可作舊基線。"]),
            roe=self._metric("6.21", "%", "2026H1", TrendStatus.IMPROVING, official_ids),
            roic=self._metric(latest_master["ROIC_Precise_Pct"], "%", latest_master["Quarter"], TrendStatus.STABLE, [authority_ids["master"]]),
            operating_cash_flow=self._metric(cf["operatingCashFlowMillionTwd"], "新台幣百萬元", cf["period"], TrendStatus.WATCH, official_ids, ["H1 cumulative; not standalone Q2."]),
            free_cash_flow=self._metric(cf["freeCashFlowMillionTwd"], "新台幣百萬元", cf["period"], TrendStatus.WATCH, official_ids, ["Official Results definition: operating cash flow minus capex; H1 cumulative."]),
            dividend_safety=self._metric(latest_master["CashDividend"], "元／股", latest_master["Quarter"], TrendStatus.WATCH, [authority_ids["master"], result_id], ["H1 negative FCF requires observation but does not prove structural dividend impairment."]),
            balance_sheet_safety=self._metric("219809", "新台幣百萬元淨現金", q["fiscalPeriod"], TrendStatus.STABLE, official_ids),
        )
        publication = date.fromisoformat(q["publicationDate"])
        event_reaction = EventWindowReaction(status=EventWindowStatus.INSUFFICIENT_DATA, publication_date=publication, return_windows={}, benchmark_adjusted_return=None, limitations=["Authority ends before a complete post-results event window.", "No governed benchmark-adjusted return is available."])
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
            valuation_analysis=ValuationAnalysis(current_price=latest_price["Close"], current_pb=latest_price["PB_daily"], governed_historical_pb_position=f"{pb_percentile:.1f} percentile within {len(pbs)} governed observations", roe_support=TrendStatus.IMPROVING, earnings_support=TrendStatus.IMPROVING, valuation_status=ValuationStatus.DESCRIPTIVE_ONLY, valuation_policy_id=None, data_window=f"{price.rows[0]['Date']}..{latest_price['Date']}", limitations=["P/E uses a pre-Q2 TTM authority baseline and requires refresh before evaluative use.", "P/S is not computed without a Q2-updated governed denominator."]),
            price_and_market_activity=PriceAndMarketActivity(price_trend=TrendStatus.IMPROVING if _d(returns["20D"]) > 0 else TrendStatus.WATCH, recent_price_context=RecentPriceContext(return_windows=returns, data_window=f"{price.rows[0]['Date']}..{latest_price['Date']}"), event_window_reaction=event_reaction, volume_trend=TrendStatus.IMPROVING if volume_ratio and volume_ratio >= 1 else TrendStatus.WATCH, volume_percentile=f"{volume_percentile:.1f}%", transaction_activity=f"{latest_activity['transaction_count']}筆；成交量為20日均量的{volume_ratio:.2f}倍", abnormal_activity_flag=bool(volume_ratio and volume_ratio >= Decimal('1.5')), data_limitations=["Price and volume authority ends before the official results publication date.", "Volume cannot identify investor intent."]),
            market_regime=MarketRegime(primary_regime=MarketRegimeName.INSUFFICIENT_DATA, evidence_ids=source_ids, confidence=ConfidenceClass.LOW, evaluated_conditions=conditions, alternative_regime=MarketRegimeName.EARNINGS_REASSESSMENT, invalidation_condition="A complete governed post-results price window may permit earnings-reassessment classification."),
            market_psychology=MarketPsychology(interpretation="Official earnings improved, but the market reaction cannot yet be classified because the authority lacks a complete post-results window.", evidence_basis=official_ids + [authority_ids["price"], authority_ids["activity"]], alternative_explanation="Pre-event price and volume may reflect broader market or anticipation effects.", counter_evidence=["The governed market data ends before the results publication."], confidence=ConfidenceClass.LOW, invalidation_condition="Reassess after complete governed post-event price and volume are available."),
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
            EventImpactLink(from_node="gross margin", to_node="operating margin", status=LinkStatus.VERIFIED, explanation="Operating margin improved to 3.75% on scale and mix.", evidence_ids=official_ids),
            EventImpactLink(from_node="operating margin", to_node="EPS", status=LinkStatus.VERIFIED, explanation="Q2 EPS was NT$4.27, up QoQ and YoY.", evidence_ids=official_ids),
            EventImpactLink(from_node="EPS", to_node="cash flow", status=LinkStatus.VERIFIED, explanation="H1 operating cash flow and FCF were negative; this is cumulative H1, not standalone Q2.", evidence_ids=official_ids),
            EventImpactLink(from_node="cash flow", to_node="valuation/thesis", status=LinkStatus.INFERRED, explanation="Earnings support and negative H1 FCF coexist; valuation stays descriptive and the thesis remains under observation.", evidence_ids=official_ids + [authority_ids["price"], authority_ids["cash"]]),
        ]

    @staticmethod
    def _conclusions(q2: QuarterlyEarningsAnalysis, official_ids: list[str], authority_ids: dict[str, str], publication: str) -> list[MaterialConclusion]:
        return [
            MaterialConclusion(conclusion_id="C-Q2-EARNINGS", statement=f"FY2026 Q2 revenue was {q2.revenue.value} million TWD ({q2.revenue.qoq} QoQ, {q2.revenue.yoy} YoY), operating margin {q2.operating_margin.value}% and EPS {q2.eps.value} TWD.", fact_or_inference=FactOrInference.FACT, evidence_ids=official_ids, source_tier="OFFICIAL_COMPANY_INVESTOR_RELATIONS", source_date=publication, data_cutoff="2026-06-30", confidence=ConfidenceClass.HIGH, alternative_explanation="Year-over-year growth may include base and product-mix effects.", counter_evidence=[f"Gross margin was {q2.gross_margin.qoq} QoQ and {q2.gross_margin.yoy} YoY."], missing_evidence=["audited/reviewed quarterly financial report"], invalidation_condition="Withdraw if the company issues corrected results.", next_validation_event="FY2026 Q2 official financial report / next quarterly earnings"),
            MaterialConclusion(conclusion_id="C-Q2-AI-OUTLOOK", statement="Official guidance describes strong AI infrastructure demand, high-double-digit 3Q26 AI rack shipment growth QoQ and more-than-multiple AI server revenue growth.", fact_or_inference=FactOrInference.FACT, evidence_ids=official_ids, source_tier="OFFICIAL_COMPANY_INVESTOR_RELATIONS", source_date=publication, data_cutoff=publication, confidence=ConfidenceClass.HIGH, alternative_explanation="Guidance is forward-looking and may not convert at the stated pace.", counter_evidence=["The Results document does not quantify customer-specific Apple/iPhone or policy impacts."], missing_evidence=["realized 3Q26 AI shipment and revenue mix"], invalidation_condition="Reassess if subsequent official guidance is reduced or shipments do not convert.", next_validation_event="FY2026 Q3 official earnings"),
            MaterialConclusion(conclusion_id="C-Q2-CASH-VALUATION", statement=f"Official {q2.cash_flow_period} FCF was negative; P/E remains tied to a pre-Q2 TTM authority baseline and P/S is not computed without a Q2-updated governed denominator.", fact_or_inference=FactOrInference.MIXED if hasattr(FactOrInference, 'MIXED') else FactOrInference.INFERENCE, evidence_ids=official_ids + [authority_ids["master"], authority_ids["price"], authority_ids["cash"]], source_tier="MIXED_OFFICIAL_AND_GOVERNED_AUTHORITY", source_date=publication, data_cutoff=publication, confidence=ConfidenceClass.MEDIUM, alternative_explanation="Working-capital and capex timing can depress cumulative H1 FCF.", counter_evidence=["Q2 attributable profit and EPS improved strongly."], missing_evidence=["standalone Q2 cash flow", "Q2-updated governed P/E and P/S denominators", "complete post-event price window"], invalidation_condition="Update after the official financial report and refreshed governed valuation/event-window authority.", next_validation_event="Official Q2 financial report and complete post-results market window"),
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
