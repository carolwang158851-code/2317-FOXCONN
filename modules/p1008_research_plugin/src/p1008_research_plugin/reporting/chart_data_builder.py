"""Create decision-oriented chart data from a validated Analysis Packet only."""

from __future__ import annotations

from ..analysis.analysis_contracts import AnalysisPacket
from .report_contracts import ChartData, ChartSeries


class ChartDataBuilder:
    def build(self, analysis: AnalysisPacket) -> list[ChartData]:
        revenue = analysis.financial_trend.revenue
        fcf = analysis.financial_trend.free_cash_flow
        price = analysis.valuation_analysis.current_price
        pb = analysis.valuation_analysis.current_pb
        evidence_ids = analysis.source_evidence_ids
        return [
            ChartData(
                chart_id="monthly_revenue_signal",
                title_zh="2026年6月營收：年增強、月增轉弱",
                decision_question="營收動能是加速，還是高基期下的正常化？",
                period=revenue.period,
                source_evidence_ids=[item for item in evidence_ids if item.startswith("E-")],
                labels=["月增率", "年增率", "上半年累計年增率"],
                series=[ChartSeries(label_zh="成長率", unit="%", values=["-4.38", "52.11", "34.99"])],
                commentary_zh=["年增與上半年累計年增顯示需求動能仍強。", "月減4.38%說明不能只用年增率判斷短期加速。"],
                actionable=False,
            ),
            ChartData(
                chart_id="valuation_cash_conversion",
                title_zh="估值與現金轉化並未同步",
                decision_question="現有估值是否已獲現金流支持？",
                period=f"價格至{analysis.valuation_analysis.data_window.split('..')[-1]}；現金流{fcf.period}",
                source_evidence_ids=["AUTH-PRICE-20260727", "AUTH-CASHFLOW-2026Q1"],
                labels=["收盤價", "P/B", "核心FCF"],
                series=[
                    ChartSeries(label_zh="收盤價", unit="新台幣元", values=[price]),
                    ChartSeries(label_zh="P/B", unit="倍", values=[pb]),
                    ChartSeries(label_zh="核心FCF", unit="新台幣億元", values=[fcf.value or "INSUFFICIENT_DATA"]),
                ],
                commentary_zh=["P/B位於現有authority窗口較高位置。", "2026Q1核心FCF為負，因此現金流尚未支持估值擴張。"],
                actionable=False,
            ),
        ]
