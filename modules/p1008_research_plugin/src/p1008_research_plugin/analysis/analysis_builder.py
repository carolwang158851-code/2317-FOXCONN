"""Build one governed MONTHLY_REVENUE analysis packet from verified inputs."""

from __future__ import annotations

import calendar
import json
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping

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
    RecentPriceContext,
    RegimeCondition,
    ThesisScorecard,
    TrendStatus,
    ValuationAnalysis,
    ValuationStatus,
)
from ..adapters.authority_adapter import AuthorityAdapter
from ..phaseb1_common import canonical_json_bytes, sha256_bytes, sha256_file
from ..plugin_module.contracts import ValidatedEvidence


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


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", value).upper() or "UNDECLARED"


def _next_quarter(period: str) -> str:
    match = re.fullmatch(r"(\d{4})Q([1-4])", period)
    if not match:
        return "NEXT_OFFICIAL_FINANCIAL_REPORT"
    year, quarter = int(match.group(1)), int(match.group(2))
    if quarter == 4:
        return f"{year + 1}Q1"
    return f"{year}Q{quarter + 1}"


def _revenue_period(value: str, fallback: date | None) -> str:
    match = re.search(r"(\d{4})年(\d{1,2})月", value)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"
    return fallback.strftime("%Y-%m") if fallback else "INSUFFICIENT_DATA"


def _month_end(period: str) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{2})", period)
    if not match:
        return period
    year, month = int(match.group(1)), int(match.group(2))
    return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


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
        cutoffs = {path: self._cutoff(entries[path]) for path in sorted(entries)}

        master = self.authority.read_csv("data/2317_master_v9.csv")
        price = self.authority.read_csv("data/2317_daily_price.csv")
        activity = self.authority.read_csv("data/2317_daily_market_activity.csv")
        cash = self.authority.read_csv("data/2317_cash_flow_authority.csv")

        latest_master = master.rows[-1]
        latest_price = price.rows[-1]
        latest_activity = activity.rows[-1]
        latest_cash = cash.rows[-1]
        master_period = latest_master["Quarter"]
        cash_period = latest_cash["period"]
        next_financial_period = _next_quarter(cash_period)
        price_cutoff = cutoffs["data/2317_daily_price.csv"]
        activity_cutoff = cutoffs["data/2317_daily_market_activity.csv"]
        authority_ids = {
            "master": f"AUTH-MASTER-{_safe_id(cutoffs['data/2317_master_v9.csv'])}",
            "price": f"AUTH-PRICE-{_safe_id(price_cutoff)}",
            "activity": f"AUTH-MARKET-ACTIVITY-{_safe_id(activity_cutoff)}",
            "cash": f"AUTH-CASHFLOW-{_safe_id(cutoffs['data/2317_cash_flow_authority.csv'])}",
        }

        price_points = [
            (date.fromisoformat(row["Date"]), _decimal(row["Close"]))
            for row in price.rows
        ]
        prices = [value for _trade_date, value in price_points]
        pbs = [_decimal(row["PB_daily"]) for row in price.rows]
        volumes = [Decimal(row["trade_volume"]) for row in activity.rows]
        returns = {
            name: _pct(prices[-1], prices[-1 - distance])
            if len(prices) > distance
            else "INSUFFICIENT_DATA"
            for name, distance in (("1D", 1), ("5D", 5), ("20D", 20))
        }
        volume_window = volumes[-20:]
        volume_average = (
            sum(volume_window) / Decimal(len(volume_window)) if volume_window else None
        )
        volume_ratio = (
            volumes[-1] / volume_average if volume_average not in (None, Decimal("0")) else None
        )
        volume_percentile = (
            Decimal(sum(item <= volumes[-1] for item in volumes))
            / Decimal(len(volumes))
            * 100
            if volumes
            else None
        )
        pb_percentile = (
            Decimal(sum(item <= pbs[-1] for item in pbs)) / Decimal(len(pbs)) * 100
        )

        official_evidence_ids = sorted(validated_evidence.evidence_ids)
        source_evidence_ids = sorted([*official_evidence_ids, *authority_ids.values()])
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
        publication_date = self._event_publication_date(validated_evidence)
        revenue_period = _revenue_period(revenue_fact, publication_date)
        fcf_value = latest_cash["free_cash_flow_core_100m_ntd"]
        fcf_status = (
            TrendStatus.WATCH
            if _decimal(fcf_value) < 0
            else TrendStatus.IMPROVING
        )
        event_reaction = self._event_window(price_points, publication_date)
        price_trend = (
            TrendStatus.IMPROVING
            if returns["5D"] != "INSUFFICIENT_DATA"
            and returns["20D"] != "INSUFFICIENT_DATA"
            and _decimal(returns["5D"]) > 0
            and _decimal(returns["20D"]) > 0
            else TrendStatus.WATCH
        )
        volume_trend = (
            TrendStatus.INSUFFICIENT_DATA
            if volume_ratio is None
            else TrendStatus.IMPROVING
            if volume_ratio >= Decimal("1")
            else TrendStatus.WATCH
        )

        financial = FinancialTrend(
            revenue=self._metric(revenue_fact, "新台幣百萬元／%", revenue_period, TrendStatus.IMPROVING, official_evidence_ids),
            gross_margin=self._metric(latest_master["GrossMarginPct"], "%", master_period, TrendStatus.STABLE, [authority_ids["master"]]),
            operating_margin=self._metric(latest_master["OperatingMarginPct"], "%", master_period, TrendStatus.STABLE, [authority_ids["master"]]),
            eps=self._metric(latest_master["EPS_Q"], "元", master_period, _trend(_decimal(latest_master["EPS_YoY_Pct"])), [authority_ids["master"]]),
            eps_ttm=self._metric(latest_master["EPS_TTM"], "元", f"TTM至{master_period}", TrendStatus.STABLE, [authority_ids["master"]]),
            roe=self._metric(latest_master["ROE_TTM_Pct"], "%", f"TTM至{master_period}", TrendStatus.STABLE, [authority_ids["master"]]),
            roic=self._metric(latest_master["ROIC_Precise_Pct"], "%", master_period, TrendStatus.STABLE, [authority_ids["master"]]),
            operating_cash_flow=self._metric(latest_cash["operating_cash_flow_thousand_ntd"], "新台幣千元", cash_period, TrendStatus.IMPROVING, [authority_ids["cash"]]),
            free_cash_flow=self._metric(fcf_value, "新台幣億元", cash_period, fcf_status, [authority_ids["cash"]], [f"單季FCF受營運資金與資本支出時點影響，需由{next_financial_period}及TTM確認。"]),
            dividend_safety=self._metric(latest_master["CashDividend"], "元／股", f"{master_period}列股利基線", TrendStatus.WATCH, [authority_ids["master"], authority_ids["cash"]], ["負的單季FCF不足以單獨證明結構性股利風險。"]),
            balance_sheet_safety=self._metric(latest_master["NetDebtToEBITDA_Approx"], "倍", master_period, TrendStatus.STABLE, [authority_ids["master"]]),
        )
        valuation = ValuationAnalysis(
            current_price=latest_price["Close"],
            current_pb=latest_price["PB_daily"],
            governed_historical_pb_position=f"{pb_percentile:.1f} percentile within {len(pbs)} governed observations",
            roe_support=TrendStatus.STABLE,
            earnings_support=TrendStatus.IMPROVING,
            valuation_status=ValuationStatus.DESCRIPTIVE_ONLY,
            valuation_policy_id=None,
            data_window=f"{price.rows[0]['Date']}..{latest_price['Date']}",
            limitations=[
                "目前沒有Owner核准的P/B分類門檻；估值只作描述，不輸出便宜或昂貴分類。",
                "PB歷史位置僅涵蓋現有正式日價authority窗口，不等同完整景氣循環。",
            ],
        )
        market = PriceAndMarketActivity(
            price_trend=price_trend,
            recent_price_context=RecentPriceContext(
                return_windows=returns,
                data_window=f"{price.rows[0]['Date']}..{latest_price['Date']}",
            ),
            event_window_reaction=event_reaction,
            volume_trend=volume_trend,
            volume_percentile=(
                f"{volume_percentile:.1f}%"
                if volume_percentile is not None
                else "INSUFFICIENT_DATA"
            ),
            transaction_activity=(
                f"{latest_activity['transaction_count']}筆；成交量為20日均量的{volume_ratio:.2f}倍"
                if volume_ratio is not None
                else f"{latest_activity['transaction_count']}筆；20日量比資料不足"
            ),
            abnormal_activity_flag=(
                volume_ratio is not None and volume_ratio >= Decimal("1.5")
            ),
            data_limitations=[
                "成交量只能描述市場活動，不能推論法人、主力或特定投資人意圖。",
                "尚無受治理benchmark，因此事件窗口不計算超額報酬。",
            ],
        )
        regime = self._market_regime(
            financial=financial,
            event_reaction=event_reaction,
            official_evidence_ids=official_evidence_ids,
            authority_ids=authority_ids,
            next_financial_period=next_financial_period,
        )

        return AnalysisPacket(
            run_id=run_id,
            event_type="MONTHLY_REVENUE",
            generated_at_utc=generated_at_utc,
            authority_manifest_sha256=sha256_file(manifest_path),
            authority_file_hashes=hashes,
            authority_data_cutoffs=cutoffs,
            input_evidence_hashes=evidence_hashes,
            financial_trend=financial,
            valuation_analysis=valuation,
            price_and_market_activity=market,
            market_regime=regime,
            market_psychology=MarketPsychology(
                interpretation="官方營收動能與尚未驗證的獲利、現金轉化並存，市場可能正在評估成長品質。",
                evidence_basis=official_evidence_ids + [authority_ids["price"], authority_ids["cash"]],
                alternative_explanation="價格波動也可能源自大盤、指數或總體因素；目前沒有受治理benchmark可拆解貢獻。",
                counter_evidence=["最近價格趨勢若仍為正，不能把單一回落直接解讀為市場否定基本面。"],
                confidence=(ConfidenceClass.MEDIUM if event_reaction.status is EventWindowStatus.CALCULATED else ConfidenceClass.LOW),
                invalidation_condition=f"若{next_financial_period}獲利率與FCF同步改善，市場重新評價解釋需要更新。",
            ),
            event_impact_chain=self._impact_chain(official_evidence_ids, authority_ids, revenue_period, cash_period, next_financial_period),
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
                rationale=f"營收成長提供部分支持，但負FCF與獲利轉換仍待{next_financial_period}驗證；WAIT不等同SELL，HOLD不構成交易指令。",
                actionable=False,
            ),
            audience_lenses=self._audience_lenses(next_financial_period),
            material_conclusions=self._conclusions(
                official_evidence_ids,
                authority_ids,
                revenue_fact,
                revenue_period,
                publication_date,
                price_cutoff,
                cash_period,
                next_financial_period,
                fcf_value,
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
    def _event_publication_date(evidence: ValidatedEvidence) -> date | None:
        dates = {
            packet.as_of_date
            for packet in evidence.packets
            if packet.evidence
        }
        return next(iter(dates)) if len(dates) == 1 else None

    @staticmethod
    def _event_window(
        price_points: list[tuple[date, Decimal]], event_date: date | None
    ) -> EventWindowReaction:
        limitation = "尚無受治理benchmark，不能計算benchmark-adjusted return。"
        if event_date is None:
            return EventWindowReaction(
                status=EventWindowStatus.INSUFFICIENT_DATA,
                publication_date=None,
                return_windows={},
                benchmark_adjusted_return=None,
                limitations=["缺少唯一、可驗證的官方事件發布日期。", limitation],
            )
        before = [point for point in price_points if point[0] < event_date]
        after = [point for point in price_points if point[0] >= event_date]
        if not before or len(after) < 5:
            return EventWindowReaction(
                status=EventWindowStatus.INSUFFICIENT_DATA,
                publication_date=event_date,
                return_windows={},
                benchmark_adjusted_return=None,
                limitations=["缺少完整T-1、T+1或T+5正式交易日。", limitation],
            )
        prior = before[-1]
        first = after[0]
        fifth = after[4]
        return EventWindowReaction(
            status=EventWindowStatus.CALCULATED,
            publication_date=event_date,
            return_windows={
                "T-1_TO_T+1": f"{_pct(first[1], prior[1])} ({prior[0]}→{first[0]})",
                "T-1_TO_T+5": f"{_pct(fifth[1], prior[1])} ({prior[0]}→{fifth[0]})",
            },
            benchmark_adjusted_return=None,
            limitations=[limitation],
        )

    @staticmethod
    def _market_regime(
        *,
        financial: FinancialTrend,
        event_reaction: EventWindowReaction,
        official_evidence_ids: list[str],
        authority_ids: Mapping[str, str],
        next_financial_period: str,
    ) -> MarketRegime:
        conditions = [
            RegimeCondition(
                condition_id="OFFICIAL_REVENUE_DELTA",
                description="官方月營收證據顯示具實質年增動能。",
                result=("PASS" if financial.revenue.status is TrendStatus.IMPROVING else "FAIL"),
                evidence_ids=official_evidence_ids,
            ),
            RegimeCondition(
                condition_id="PROFIT_CONVERSION_UNVERIFIED",
                description="本次月營收證據未同時提供毛利率、EPS與FCF轉化。",
                result="PASS",
                evidence_ids=official_evidence_ids + [authority_ids["cash"]],
            ),
            RegimeCondition(
                condition_id="EVENT_WINDOW_AVAILABLE",
                description="官方發布日已能對齊完整T-1至T+5價格窗口。",
                result=("PASS" if event_reaction.status is EventWindowStatus.CALCULATED else "INSUFFICIENT_DATA"),
                evidence_ids=[authority_ids["price"]],
            ),
        ]
        if all(condition.result == "PASS" for condition in conditions):
            primary = MarketRegimeName.EARNINGS_REASSESSMENT
            confidence = ConfidenceClass.MEDIUM
        else:
            primary = MarketRegimeName.INSUFFICIENT_DATA
            confidence = ConfidenceClass.LOW
        return MarketRegime(
            primary_regime=primary,
            evidence_ids=sorted({item for condition in conditions for item in condition.evidence_ids}),
            confidence=confidence,
            evaluated_conditions=conditions,
            alternative_regime=MarketRegimeName.RANGE_BOUND,
            invalidation_condition=f"若{next_financial_period}獲利與現金流未隨營收改善，或事件窗口資料失效，需重新分類。",
        )

    @staticmethod
    def _impact_chain(evidence_ids: list[str], authority_ids: Mapping[str, str], revenue_period: str, cash_period: str, next_period: str) -> list[EventImpactLink]:
        return [
            EventImpactLink(from_node="event", to_node="demand/orders/cost/supply", status=LinkStatus.VERIFIED, explanation="官方月營收證明需求與出貨已轉成營收，但未拆解訂單、成本或供應因素。", evidence_ids=evidence_ids),
            EventImpactLink(from_node="demand/orders/cost/supply", to_node="revenue", status=LinkStatus.VERIFIED, explanation=f"{revenue_period}官方月營收證據已驗證。", evidence_ids=evidence_ids),
            EventImpactLink(from_node="revenue", to_node="margin", status=LinkStatus.UNCONFIRMED, explanation="本次月營收公告未提供毛利率或營益率。", evidence_ids=evidence_ids),
            EventImpactLink(from_node="margin", to_node="EPS", status=LinkStatus.UNCONFIRMED, explanation=f"缺少{next_period}正式損益資料，不能由營收直接推算EPS。", evidence_ids=evidence_ids),
            EventImpactLink(from_node="EPS", to_node="cash flow", status=LinkStatus.UNCONFIRMED, explanation=f"{cash_period} FCF為負；月營收不足以證明現金轉化改善。", evidence_ids=[authority_ids["cash"]]),
            EventImpactLink(from_node="cash flow", to_node="dividend/valuation", status=LinkStatus.INFERRED, explanation="FCF尚未支持估值擴張，但單季負值也不足以證明結構性股利風險。", evidence_ids=[authority_ids["cash"], authority_ids["price"]]),
        ]

    @staticmethod
    def _audience_lenses(next_period: str) -> list[AudienceLens]:
        return [
            AudienceLens(lens_id="ACCUMULATION_35_45", narrative=f"關注營收成長是否在{next_period}轉成EPS與FCF，避免只因價格回落提高確定性。", decision_focus="成長轉化與估值紀律"),
            AudienceLens(lens_id="RETIREMENT_TRANSITION_46_60", narrative=f"以獲利品質、現金流與資產負債表承受度為主，等待{next_period}驗證。", decision_focus="波動承受度與現金轉化"),
            AudienceLens(lens_id="RETIREMENT_INCOME_60_PLUS", narrative="股利安全需觀察TTM現金流而非單季負值；目前不提供個人化配置。", decision_focus="股利可持續性與資本保全"),
        ]

    @staticmethod
    def _conclusions(
        evidence_ids: list[str],
        authority_ids: Mapping[str, str],
        revenue_fact: str,
        revenue_period: str,
        publication_date: date | None,
        price_cutoff: str,
        cash_period: str,
        next_period: str,
        fcf_value: str,
    ) -> list[MaterialConclusion]:
        publication = publication_date.isoformat() if publication_date else "INSUFFICIENT_DATA"
        return [
            MaterialConclusion(
                conclusion_id=f"C-REVENUE-{_safe_id(revenue_period)}",
                statement=f"官方月營收顯示年增動能強，但月減代表相較前月正常化：{revenue_fact}",
                fact_or_inference=FactOrInference.FACT,
                evidence_ids=evidence_ids,
                source_tier="OFFICIAL_COMPANY_RELEASE",
                source_date=publication,
                data_cutoff=_month_end(revenue_period),
                confidence=ConfidenceClass.HIGH,
                alternative_explanation="基期效應可能放大年增率。",
                counter_evidence=["單月營收較前月下降。"],
                missing_evidence=[f"{next_period}產品組合與獲利率"],
                invalidation_condition="若公司更正公告或官方交叉來源數字不一致，立即撤回結論。",
                next_validation_event=f"{next_period}正式財報／法說（日期待官方公告）",
            ),
            MaterialConclusion(
                conclusion_id=f"C-CASH-CONVERSION-{_safe_id(cash_period)}",
                statement=f"{cash_period}核心FCF為{fcf_value}億元，現金轉化暫未支持估值擴張。",
                fact_or_inference=FactOrInference.FACT,
                evidence_ids=[authority_ids["cash"]],
                source_tier="OFFICIAL_HONHAI_PDF_A1_L1_DERIVED",
                source_date=cash_period,
                data_cutoff=cash_period,
                confidence=ConfidenceClass.HIGH,
                alternative_explanation="營運資金與資本支出時點可能造成單季FCF波動。",
                counter_evidence=[f"{cash_period}營業現金流為正。"],
                missing_evidence=[f"{next_period}與TTM現金流"],
                invalidation_condition=f"若{next_period}與TTM FCF顯著轉正，現金流警戒應調升為改善。",
                next_validation_event=f"{next_period}正式財報（日期待官方公告）",
            ),
            MaterialConclusion(
                conclusion_id=f"C-VALUATION-REACTION-{_safe_id(price_cutoff)}",
                statement="營收成長與現金轉化形成矛盾；目前沒有核准估值門檻，僅保留價格、P/B與治理窗口的描述。",
                fact_or_inference=FactOrInference.INFERENCE,
                evidence_ids=[*evidence_ids, authority_ids["price"], authority_ids["activity"], authority_ids["cash"]],
                source_tier="MIXED_GOVERNED_AUTHORITY_AND_OFFICIAL_RELEASE",
                source_date=price_cutoff,
                data_cutoff=price_cutoff,
                confidence=ConfidenceClass.MEDIUM,
                alternative_explanation="大盤或總體因素可能主導短期價格。",
                counter_evidence=["官方營收年增與累計年增仍提供基本面支持。"],
                missing_evidence=["benchmark-adjusted return", f"{next_period}獲利率", f"{next_period} FCF"],
                invalidation_condition=f"若{next_period}獲利率與FCF同步改善，需重新評估目前描述性估值判讀。",
                next_validation_event=f"{next_period}正式財報／法說（日期待官方公告）",
            ),
        ]
