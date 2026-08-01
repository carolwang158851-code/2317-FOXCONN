"""Build one governed MONTHLY_REVENUE analysis packet from verified inputs."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from .analysis_contracts import (
    AnalysisPacket,
    AudienceLens,
    EventImpactLink,
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
    ThesisScorecard,
    TrendStatus,
    ValuationAnalysis,
    ValuationStatus,
)
from ..adapters.authority_adapter import AuthorityAdapter
from ..phaseb1_common import canonical_json_bytes, sha256_bytes, sha256_file
from ..plugin_module.contracts import ValidatedEvidence


AUTH_MASTER = "AUTH-MASTER-2026Q1"
AUTH_PRICE = "AUTH-PRICE-20260727"
AUTH_ACTIVITY = "AUTH-MARKET-ACTIVITY-20260727"
AUTH_CASH_FLOW = "AUTH-CASHFLOW-2026Q1"


def _decimal(value: str) -> Decimal:
    return Decimal(value.replace("+", "").replace("%", "").strip())


def _pct(current: Decimal, prior: Decimal) -> str:
    if prior == 0:
        return "INSUFFICIENT_DATA"
    return f"{((current / prior) - 1) * 100:.2f}%"


def _trend(value: Decimal, positive: Decimal = Decimal("0")) -> TrendStatus:
    if value > positive:
        return TrendStatus.IMPROVING
    if value == positive:
        return TrendStatus.STABLE
    return TrendStatus.WATCH


class AnalysisBuilder:
    CONTRACT_VERSION = "1.0"

    def __init__(self, package_root: Path, authority: AuthorityAdapter) -> None:
        self.package_root = package_root.resolve()
        self.authority = authority

    def build(
        self,
        *,
        run_id: str,
        generated_at_utc: datetime,
        validated_evidence: ValidatedEvidence,
    ) -> AnalysisPacket:
        verified = self.authority.verify_all()
        hashes = {
            item["relative_path"]: item["sha256"] for item in verified["verified"]
        }
        manifest_path = self.package_root / self.authority.MANIFEST_PATH
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        entries = {
            item["path"]: item
            for item in manifest.get("authoritativeFiles", [])
            + manifest.get("nonAuthoritativeFiles", [])
        }

        master = self.authority.read_csv("data/2317_master_v9.csv")
        price = self.authority.read_csv("data/2317_daily_price.csv")
        activity = self.authority.read_csv("data/2317_daily_market_activity.csv")
        cash = self.authority.read_csv("data/2317_cash_flow_authority.csv")

        latest_master = master.rows[-1]
        latest_price = price.rows[-1]
        latest_activity = activity.rows[-1]
        latest_cash = cash.rows[-1]
        prices = [_decimal(row["Close"]) for row in price.rows]
        pbs = [_decimal(row["PB_daily"]) for row in price.rows]
        volumes = [Decimal(row["trade_volume"]) for row in activity.rows]

        returns = {
            name: _pct(prices[-1], prices[-1 - distance])
            if len(prices) > distance
            else "INSUFFICIENT_DATA"
            for name, distance in (("1D", 1), ("5D", 5), ("20D", 20))
        }
        latest_volume = volumes[-1]
        volume_average = sum(volumes[-20:]) / Decimal(len(volumes[-20:]))
        volume_ratio = latest_volume / volume_average if volume_average else Decimal("0")
        volume_percentile = (
            Decimal(sum(item <= latest_volume for item in volumes))
            / Decimal(len(volumes))
            * 100
        )
        pb_percentile = (
            Decimal(sum(item <= pbs[-1] for item in pbs)) / Decimal(len(pbs)) * 100
        )

        official_evidence_ids = sorted(validated_evidence.evidence_ids)
        source_evidence_ids = sorted(
            [*official_evidence_ids, AUTH_MASTER, AUTH_PRICE, AUTH_ACTIVITY, AUTH_CASH_FLOW]
        )
        evidence_hashes = {
            packet.packet_id: sha256_bytes(
                canonical_json_bytes(packet.model_dump(mode="json", by_alias=True))
            )
            for packet in validated_evidence.packets
        }
        revenue_fact = next(
            item.field_values["revenue"]
            for item in validated_evidence.evidence
            if "revenue" in item.field_values
        )
        fcf_value = latest_cash["free_cash_flow_core_100m_ntd"]
        fcf_status = TrendStatus.WATCH if _decimal(fcf_value) < 0 else TrendStatus.IMPROVING
        pb = _decimal(latest_price["PB_daily"])
        valuation_status = (
            ValuationStatus.ATTRACTIVE
            if pb < Decimal("1.4")
            else ValuationStatus.FAIR
            if pb < Decimal("1.8")
            else ValuationStatus.FAIR_TO_EXPENSIVE
            if pb <= Decimal("2.0")
            else ValuationStatus.EXPENSIVE
            if pb <= Decimal("2.3")
            else ValuationStatus.EXTREME
        )
        price_trend = (
            TrendStatus.IMPROVING
            if _decimal(returns["5D"]) > 0 and _decimal(returns["20D"]) > 0
            else TrendStatus.WATCH
        )
        volume_trend = (
            TrendStatus.IMPROVING if volume_ratio >= Decimal("1") else TrendStatus.WATCH
        )

        financial = FinancialTrend(
            revenue=self._metric(revenue_fact, "新台幣百萬元／%", "2026-06及2026H1", TrendStatus.IMPROVING, official_evidence_ids),
            gross_margin=self._metric(latest_master["GrossMarginPct"], "%", "2026Q1", TrendStatus.STABLE, [AUTH_MASTER]),
            operating_margin=self._metric(latest_master["OperatingMarginPct"], "%", "2026Q1", TrendStatus.STABLE, [AUTH_MASTER]),
            eps=self._metric(latest_master["EPS_Q"], "元", "2026Q1", _trend(_decimal(latest_master["EPS_YoY_Pct"])), [AUTH_MASTER]),
            eps_ttm=self._metric(latest_master["EPS_TTM"], "元", "TTM至2026Q1", TrendStatus.STABLE, [AUTH_MASTER]),
            roe=self._metric(latest_master["ROE_TTM_Pct"], "%", "TTM至2026Q1", TrendStatus.STABLE, [AUTH_MASTER]),
            roic=self._metric(latest_master["ROIC_Precise_Pct"], "%", "2026Q1", TrendStatus.STABLE, [AUTH_MASTER]),
            operating_cash_flow=self._metric(latest_cash["operating_cash_flow_thousand_ntd"], "新台幣千元", "2026Q1", TrendStatus.IMPROVING, [AUTH_CASH_FLOW]),
            free_cash_flow=self._metric(fcf_value, "新台幣億元", "2026Q1", fcf_status, [AUTH_CASH_FLOW], ["單季FCF受營運資金與資本支出時點影響，需由2026Q2及TTM確認。"]),
            dividend_safety=self._metric(latest_master["CashDividend"], "元／股", "2025年度配息", TrendStatus.WATCH, [AUTH_MASTER, AUTH_CASH_FLOW], ["負的單季FCF不足以單獨證明結構性股利風險。"]),
            balance_sheet_safety=self._metric(latest_master["NetDebtToEBITDA_Approx"], "倍", "2026Q1", TrendStatus.STABLE, [AUTH_MASTER]),
        )

        valuation = ValuationAnalysis(
            current_price=latest_price["Close"],
            current_pb=latest_price["PB_daily"],
            governed_historical_pb_position=f"{pb_percentile:.1f} percentile within {len(pbs)} governed observations",
            roe_support=TrendStatus.STABLE,
            earnings_support=TrendStatus.IMPROVING,
            valuation_status=valuation_status,
            data_window=f"{price.rows[0]['Date']}..{latest_price['Date']}",
            limitations=["PB歷史位置僅涵蓋現有正式日價authority窗口，不等同完整景氣循環。"],
        )

        market = PriceAndMarketActivity(
            price_trend=price_trend,
            return_windows=returns,
            volume_trend=volume_trend,
            volume_percentile=f"{volume_percentile:.1f}%",
            transaction_activity=(
                f"{latest_activity['transaction_count']}筆；成交量為20日均量的{volume_ratio:.2f}倍"
            ),
            abnormal_activity_flag=volume_ratio >= Decimal("1.5"),
            price_reaction_to_event=f"公告後截至{latest_price['Date']}的20期報酬為{returns['20D']}；此為價格觀察，不等同因果證明。",
            data_limitations=["成交量只能描述市場活動，不能推論法人、主力或特定投資人意圖。"],
        )

        return AnalysisPacket(
            run_id=run_id,
            event_type="MONTHLY_REVENUE",
            generated_at_utc=generated_at_utc,
            authority_manifest_sha256=sha256_file(manifest_path),
            authority_file_hashes=hashes,
            authority_data_cutoffs={path: self._cutoff(entries[path]) for path in sorted(entries)},
            input_evidence_hashes=evidence_hashes,
            financial_trend=financial,
            valuation_analysis=valuation,
            price_and_market_activity=market,
            market_regime=MarketRegime(
                primary_regime=MarketRegimeName.EARNINGS_REASSESSMENT,
                evidence_ids=official_evidence_ids + [AUTH_PRICE, AUTH_ACTIVITY],
                confidence=0.67,
                alternative_regime=MarketRegimeName.RANGE_BOUND,
                invalidation_condition="若2026Q2獲利與現金流未隨營收成長改善，應改判為基本面下修檢視。",
            ),
            market_psychology=MarketPsychology(
                interpretation="營收年增強勁但月減，加上估值位於現有窗口較高區間，市場可能正在重新評估成長能否轉成利潤與現金流。",
                evidence_basis=official_evidence_ids + [AUTH_PRICE, AUTH_CASH_FLOW],
                alternative_explanation="價格波動也可能源自大盤、指數或總體因素；目前證據不足以拆解各自貢獻。",
                counter_evidence=["最近5期價格報酬仍為正時，不能把單一回落直接解讀為市場否定基本面。"],
                confidence=0.58,
                invalidation_condition="若後續獲利率與FCF同步改善且價格仍落後，市場重新評價解釋將需要更新。",
            ),
            event_impact_chain=self._impact_chain(official_evidence_ids),
            thesis_scorecard=ThesisScorecard(
                earnings_quality=TrendStatus.WATCH,
                ai_monetization=TrendStatus.INSUFFICIENT_DATA,
                dividend_safety=TrendStatus.WATCH,
                balance_sheet=TrendStatus.STABLE,
                valuation=TrendStatus.WATCH,
                overall_thesis=OverallThesis.MAINTAINED,
                evidence_ids=source_evidence_ids,
            ),
            investor_views=InvestorViews(
                new_money_view=NewMoneyView.WAIT,
                existing_holding_view=ExistingHoldingView.HOLD,
                trim_review="NOT_TRIGGERED",
                sell_review="NOT_TRIGGERED",
                rationale="營收成長提供部分支持，但負FCF與獲利轉換仍待2026Q2驗證；WAIT不等同SELL，HOLD不構成交易指令。",
                actionable=False,
            ),
            audience_lenses=self._audience_lenses(),
            material_conclusions=self._conclusions(
                official_evidence_ids, revenue_fact, latest_price["Date"], fcf_value
            ),
            source_evidence_ids=source_evidence_ids,
            actionable=False,
        )

    @staticmethod
    def _metric(value: str | None, unit: str, period: str, status: TrendStatus, evidence_ids: Iterable[str], limitations: list[str] | None = None) -> MetricAssessment:
        return MetricAssessment(
            value=value if value not in ("", "N/A") else None,
            unit=unit,
            period=period,
            status=status if value not in ("", "N/A") else TrendStatus.INSUFFICIENT_DATA,
            evidence_ids=list(evidence_ids),
            limitations=limitations or [],
        )

    @staticmethod
    def _cutoff(entry: dict[str, object]) -> str:
        for key in ("cutoffDate", "financialCutoffPeriod"):
            if entry.get(key):
                return str(entry[key])
        date_range = entry.get("dateRange")
        if isinstance(date_range, dict) and date_range.get("end"):
            return str(date_range["end"])
        period_range = entry.get("periodRange")
        if isinstance(period_range, dict) and period_range.get("end"):
            return str(period_range["end"])
        return "DECLARED_IN_AUTHORITY_FILE"

    @staticmethod
    def _impact_chain(evidence_ids: list[str]) -> list[EventImpactLink]:
        return [
            EventImpactLink(from_node="event", to_node="demand/orders/cost/supply", status=LinkStatus.VERIFIED, explanation="官方月營收證明出貨與需求轉成營收，但未拆解訂單、成本或供應因素。", evidence_ids=evidence_ids),
            EventImpactLink(from_node="demand/orders/cost/supply", to_node="revenue", status=LinkStatus.VERIFIED, explanation="2026年6月營收年增52.11%、月減4.38%。", evidence_ids=evidence_ids),
            EventImpactLink(from_node="revenue", to_node="margin", status=LinkStatus.UNCONFIRMED, explanation="本次月營收公告未提供毛利率或營益率。", evidence_ids=evidence_ids),
            EventImpactLink(from_node="margin", to_node="EPS", status=LinkStatus.UNCONFIRMED, explanation="缺少2026Q2正式損益資料，不能由營收直接推算EPS。", evidence_ids=evidence_ids),
            EventImpactLink(from_node="EPS", to_node="cash flow", status=LinkStatus.UNCONFIRMED, explanation="2026Q1 FCF為負；月營收不足以證明現金轉化改善。", evidence_ids=[AUTH_CASH_FLOW]),
            EventImpactLink(from_node="cash flow", to_node="dividend/valuation", status=LinkStatus.INFERRED, explanation="FCF尚未支持估值擴張，但單季負值也不足以證明結構性股利風險。", evidence_ids=[AUTH_CASH_FLOW, AUTH_PRICE]),
        ]

    @staticmethod
    def _audience_lenses() -> list[AudienceLens]:
        return [
            AudienceLens(lens_id="ACCUMULATION_35_45", narrative="關注營收成長是否在下一季轉成EPS與FCF，避免只因價格回落而提高確定性。", decision_focus="成長轉化與估值紀律"),
            AudienceLens(lens_id="RETIREMENT_TRANSITION_46_60", narrative="以獲利品質、現金流與資產負債表承受度為主，等待2026Q2驗證。", decision_focus="波動承受度與現金轉化"),
            AudienceLens(lens_id="RETIREMENT_INCOME_60_PLUS", narrative="股利安全需觀察TTM現金流而非單季負值；目前不提供個人化配置。", decision_focus="股利可持續性與資本保全"),
        ]

    @staticmethod
    def _conclusions(evidence_ids: list[str], revenue_fact: str, price_cutoff: str, fcf_value: str) -> list[MaterialConclusion]:
        return [
            MaterialConclusion(
                conclusion_id="C-REVENUE-202606",
                statement=f"官方月營收顯示年增動能強，但月減代表相較5月正常化：{revenue_fact}",
                fact_or_inference=FactOrInference.FACT,
                evidence_ids=evidence_ids,
                source_tier="OFFICIAL_COMPANY_RELEASE",
                source_date="2026-07-05",
                data_cutoff="2026-06-30",
                confidence=0.99,
                alternative_explanation="基期效應可能放大年增率。",
                counter_evidence=["單月營收較前月下降4.38%。"],
                missing_evidence=["2026Q2產品組合與獲利率"],
                invalidation_condition="若公司更正公告或MOPS數字不一致，立即撤回結論。",
                next_validation_event="2026Q2財報／法說",
            ),
            MaterialConclusion(
                conclusion_id="C-CASH-CONVERSION-2026Q1",
                statement=f"2026Q1核心FCF為{fcf_value}億元，現金轉化暫未支持估值擴張。",
                fact_or_inference=FactOrInference.FACT,
                evidence_ids=[AUTH_CASH_FLOW],
                source_tier="OFFICIAL_HONHAI_PDF_A1_L1_DERIVED",
                source_date="2026-05-15",
                data_cutoff="2026Q1",
                confidence=0.98,
                alternative_explanation="營運資金與資本支出時點可能造成單季FCF波動。",
                counter_evidence=["2026Q1營業現金流已由2025Q1負值轉正。"],
                missing_evidence=["2026Q2與TTM現金流"],
                invalidation_condition="若2026Q2與TTM FCF顯著轉正，現金流警戒應調升為改善。",
                next_validation_event="2026Q2正式財報",
            ),
            MaterialConclusion(
                conclusion_id="C-VALUATION-REACTION",
                statement="營收成長與現金轉化形成矛盾，現有證據支持等待獲利與FCF驗證，而非把價格變動解讀為確定的低估或高估。",
                fact_or_inference=FactOrInference.INFERENCE,
                evidence_ids=[*evidence_ids, AUTH_PRICE, AUTH_ACTIVITY, AUTH_CASH_FLOW],
                source_tier="MIXED_GOVERNED_AUTHORITY_AND_OFFICIAL_RELEASE",
                source_date=price_cutoff,
                data_cutoff=price_cutoff,
                confidence=0.68,
                alternative_explanation="大盤或總體因素可能主導短期價格。",
                counter_evidence=["營收年增與上半年累計年增均維持高檔。"],
                missing_evidence=["benchmark-adjusted return", "2026Q2獲利率", "2026Q2 FCF"],
                invalidation_condition="若獲利率與FCF同步改善且估值回落，需重新評估WAIT分類。",
                next_validation_event="2026Q2財報／法說",
            ),
        ]
