"""Create decision-oriented chart data from a validated Analysis Packet only."""

from __future__ import annotations

import re

from ..analysis.analysis_contracts import AnalysisPacket
from .report_contracts import ChartData, ChartSeries


class ChartDataBuilder:
    @staticmethod
    def _authority_id(analysis: AnalysisPacket, prefix: str) -> str:
        matches = [item for item in analysis.source_evidence_ids if item.startswith(prefix)]
        if len(matches) != 1:
            raise ValueError(f"analysis does not contain exactly one {prefix} identity")
        return matches[0]

    @staticmethod
    def _revenue_values(value: str | None) -> tuple[list[str], list[str]]:
        if value is None:
            return ["月增率", "年增率", "累計年增率"], ["INSUFFICIENT_DATA"] * 3
        patterns = (
            ("月增率", r"MoM\s*([+-]?\d+(?:\.\d+)?)%"),
            ("年增率", r"YoY\s*([+-]?\d+(?:\.\d+)?)%"),
            ("累計年增率", r"累計YoY\s*([+-]?\d+(?:\.\d+)?)%"),
        )
        values: list[str] = []
        for _label, pattern in patterns:
            match = re.search(pattern, value, re.IGNORECASE)
            values.append(match.group(1) if match else "INSUFFICIENT_DATA")
        return [label for label, _pattern in patterns], values

    def build(self, analysis: AnalysisPacket) -> list[ChartData]:
        if analysis.event_type == "QUARTERLY_EARNINGS":
            q = analysis.quarterly_earnings
            if q is None:
                raise ValueError("quarterly chart data requires quarterly analysis")
            official_ids = [item for item in analysis.source_evidence_ids if not item.startswith("AUTH-")]
            return [
                ChartData(
                    chart_id="quarterly_financial_summary",
                    title_zh=f"{q.fiscal_period}財務摘要",
                    decision_question="營收成長是否同時轉成營業利益率與EPS改善？",
                    period=q.fiscal_period,
                    source_evidence_ids=official_ids,
                    labels=["營收YoY", "營收QoQ", "EPS YoY", "EPS QoQ"],
                    series=[ChartSeries(label_zh="成長率", unit="%", values=[q.revenue.yoy.rstrip("%"), q.revenue.qoq.rstrip("%"), q.eps.yoy.rstrip("%"), q.eps.qoq.rstrip("%")])],
                    commentary_zh=["營收與EPS均呈現年增及季增。", "毛利率仍較前季及去年同期下滑，不能只用營收成長代表全面改善。"],
                    actionable=False,
                ),
                ChartData(
                    chart_id="quarterly_margin_and_fcf",
                    title_zh="利潤率與現金轉化",
                    decision_question="獲利改善是否已轉成累計自由現金流？",
                    period=f"{q.fiscal_period}／{q.cash_flow_period}",
                    source_evidence_ids=official_ids,
                    labels=["毛利率", "營益率", "淨利率", "H1 FCF"],
                    series=[
                        ChartSeries(label_zh="利潤率", unit="%", values=[q.gross_margin.value, q.operating_margin.value, q.net_margin.value]),
                        ChartSeries(label_zh="自由現金流", unit="新台幣百萬元", values=[analysis.financial_trend.free_cash_flow.value or "INSUFFICIENT_DATA"]),
                    ],
                    commentary_zh=["營業利益率改善，但毛利率仍需觀察。", "H1自由現金流為負且不是Q2單季數字，維持WATCH。"],
                    actionable=False,
                ),
            ]
        revenue = analysis.financial_trend.revenue
        fcf = analysis.financial_trend.free_cash_flow
        valuation = analysis.valuation_analysis
        official_ids = [item for item in analysis.source_evidence_ids if item.startswith("E-")]
        price_id = self._authority_id(analysis, "AUTH-PRICE-")
        cash_id = self._authority_id(analysis, "AUTH-CASHFLOW-")
        labels, revenue_values = self._revenue_values(revenue.value)
        return [
            ChartData(
                chart_id="monthly_revenue_signal",
                title_zh=f"{revenue.period}營收變化",
                decision_question="月營收動能是加速、正常化，或仍不足以驗證獲利轉換？",
                period=revenue.period,
                source_evidence_ids=official_ids,
                labels=labels,
                series=[ChartSeries(label_zh="營收變化", unit="%", values=revenue_values)],
                commentary_zh=[
                    "年增與累計年增描述需求動能；月增率用來辨識相較前月的正常化。",
                    "月營收本身不提供毛利率、EPS或自由現金流結論。",
                ],
                actionable=False,
            ),
            ChartData(
                chart_id="valuation_cash_conversion",
                title_zh="估值與現金轉化對照",
                decision_question="現有價格與P/B描述，是否得到自由現金流支持？",
                period=f"價格至{valuation.data_window.split('..')[-1]}；現金流{fcf.period}",
                source_evidence_ids=[price_id, cash_id],
                labels=["收盤價", "P/B", "核心自由現金流"],
                series=[
                    ChartSeries(label_zh="收盤價", unit="新台幣元", values=[valuation.current_price]),
                    ChartSeries(label_zh="P/B", unit="倍", values=[valuation.current_pb]),
                    ChartSeries(label_zh="核心自由現金流", unit="新台幣億元", values=[fcf.value or "INSUFFICIENT_DATA"]),
                ],
                commentary_zh=[
                    "P/B僅描述目前authority窗口內的位置，不套用未核准的便宜或昂貴門檻。",
                    f"{fcf.period}核心自由現金流狀態為{fcf.status.value}，現金轉化仍是估值驗證重點。",
                ],
                actionable=False,
            ),
        ]
