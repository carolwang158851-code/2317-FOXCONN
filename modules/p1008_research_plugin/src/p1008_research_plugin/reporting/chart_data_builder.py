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
