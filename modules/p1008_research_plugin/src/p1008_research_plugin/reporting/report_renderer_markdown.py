"""Canonical Markdown rendering for a validated report candidate."""

from __future__ import annotations

from typing import Sequence

from .report_contracts import ChartData, QUARTERLY_VISIBLE_GROUPS, ReportCandidate


class MarkdownRenderer:
    _FORMULA_CARD_GROUP = {
        "營運槓桿與費用吸收": "營運槓桿差",
        "營運資金與現金轉化": "自由現金流",
        "資本效率與ROIC": "ROIC",
        "ROE、股東權益與每股淨值複利": "股東權益報酬率 ROE",
        "估值、P/B、股利與新資金情境": "股價淨值比",
    }
    _FORMULA_CARD_TITLES = {
        "營運槓桿差": "營運槓桿怎麼看？",
        "自由現金流": "自由現金流怎麼看？",
        "ROIC": "ROIC在看什麼？",
        "股東權益報酬率 ROE": "ROE在看什麼？",
        "股價淨值比": "P/B為什麼一定要配ROE看？",
    }
    _DISPLAY_CODES = {
        "PROVEN": "已證實", "PROVEN_DERIVED": "官方數字推導／已驗證",
        "PARTIALLY_PROVEN": "部分證實",
        "PARTIALLY_PROVEN_HIGH_CONFIDENCE_INFERENCE": "部分證實／高信心推論",
        "UNPROVEN": "尚未證實", "INSUFFICIENT_DATA": "資料不足",
        "UNPROVEN_SPECIFIC_AMOUNT": "特定金額尚未證實",
        "SUPPORTED": "已獲支持",
        "SUPPORTED_MANAGEMENT_GUIDANCE": "管理層指引支持",
        "SUPPORTED_BY_GUIDANCE": "管理層指引支持",
        "EVIDENCE_BUILDING": "證據累積中", "OFFICIAL_VERIFIED": "官方治理來源已驗證",
        "NOT_VERIFIED": "尚未驗證", "NOT_SEPARATELY_DISCLOSED": "未單獨揭露",
        "UNRESOLVED": "尚未釐清", "UNQUANTIFIED": "尚未量化",
        "STRATEGY": "策略階段", "DEVELOPMENT": "開發／商業化準備",
        "CUSTOMER_ORDER": "客戶／訂單驗證", "REVENUE": "已進入營收",
        "OPERATING_PROFIT": "已進入營業獲利驗證", "SHAREHOLDER_RETURN": "已進入股東回報驗證",
    }
    _CHART_GROUP = {
        "growth_quality_divergence": "成長品質與產品組合",
        "operating_leverage_spread": "營運槓桿與費用吸收",
        "operating_cost_absorption_8q": "營運槓桿與費用吸收",
        "margin_divergence_8q": "利潤率與獲利傳導",
        "profit_pass_through_evidence_gap": "利潤率與獲利傳導",
        "cash_quality_evidence": "營運資金與現金轉化",
        "working_capital_3period": "營運資金與現金轉化",
        "capex_intensity_limited": "資本效率與ROIC",
        "capital_validation_status": "資本效率與ROIC",
        "roe_equity_compounding": "ROE、股東權益與每股淨值複利",
        "strategy_scorecard_3plus3": "3+3戰略落地與價值轉化",
        "governance_target_vs_actual": "治理、企業價值與退休任務總結",
        "valuation_matrix": "估值、P/B、股利與新資金情境",
        "ai_growth_quality": "AI成長品質與價值轉化",
    }

    @classmethod
    def _visual(cls, chart: ChartData) -> list[str]:
        headers = ["項目", *(series.label_zh for series in chart.series)]
        lines = [
            f"### {chart.title_zh}",
            "",
            f"**決策問題：** {chart.decision_question}  ",
            f"**期間：** {chart.period.replace('LIMITED_HISTORY', '歷史資料有限')}  ",
            "",
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]
        for index, label in enumerate(chart.labels):
            values = [
                cls._DISPLAY_CODES.get(
                    series.values[index] if index < len(series.values) else "資料未提供",
                    series.values[index] if index < len(series.values) else "資料未提供",
                )
                for series in chart.series
            ]
            lines.append("| " + " | ".join([label, *values]) + " |")
        lines.extend(["", *(f"- {item}" for item in chart.commentary_zh), ""])
        lines.extend([
            f"**觀察：** {chart.observation_zh}",
            f"**解讀：** {chart.interpretation_zh}",
            f"**戰略含義：** {chart.strategic_implication_zh}",
            f"**企業價值含義：** {chart.enterprise_value_implication_zh}",
            f"**下一驗證點：** {chart.next_checkpoint_zh}",
            "",
        ])
        return lines

    @classmethod
    def _formula_card(cls, card: dict[str, str]) -> list[str]:
        derived = ["**DERIVED FROM OFFICIAL COMPARABLE PERIODS**", ""] if card["metric"] == "自由現金流" else []
        return [
            f"### {cls._FORMULA_CARD_TITLES[card['metric']]}", "",
            f"**公式：** {card['formula']}",
            card["plainLanguage"],
            f"**本期：** {cls._DISPLAY_CODES.get(card['currentResult'], card['currentResult'])}", "",
            *derived,
        ]

    @staticmethod
    def _value_branches() -> list[str]:
        return [
            "### 企業價值三分支驗證模型", "",
            "**管理承諾 → 策略 → 執行 → 營收 → 毛利 → 營業利益**", "",
            "- **企業資本效率：** 營業利益 → NOPAT → ROIC。營運資本是否有效創造報酬？",
            "- **股東資本效率：** 營業利益 → 稅前利益 → 淨利 → ROE → BVPS。股東資本是否被有效使用？",
            "- **現金生成：** 淨利＋非現金項目±營運資金 → CFO－Capex → FCF。帳面獲利是否變成自由現金？", "",
            "**ROIC ＋ ROE／BVPS ＋ FCF → 股利能力／股東回報 → 退休現金流安全**", "",
        ]

    def render(self, report: ReportCandidate, charts: Sequence[ChartData] = (), formula_cards: Sequence[dict[str, str]] = ()) -> str:
        title = (
            "# P1008｜鴻海 FY2026 Q2 企業價值戰報\n\n"
            "**治理政策開始兌現，但真正的價值創造只完成前半程**"
            if report.event_type == "QUARTERLY_EARNINGS"
            else "# 鴻海月營收戰情報告：成長動能與現金轉化的落差"
        )
        lines = [
            title,
            "",
            f"**Run ID：** `{report.run_id}`  ",
            f"**核心問題：** {report.primary_investor_question}",
            "",
        ]
        if report.event_type == "QUARTERLY_EARNINGS":
            lines.extend([
                "## 執行決策卡", "",
                "| 欄位 | 判定 |", "| --- | --- |",
                "| 核心論點 | 治理政策開始兌現，但真正的價值創造只完成前半程 |",
                "| 既有持有 | 維持 |", "| 新資金 | 估值觀察 |",
                "| 信心水準 | 中等 |", "| 營運治理 | 通過 |",
                "| 資本治理 | 待驗 |", "| 現金治理 | 未通過 |",
                "| 安全邊際 | 不上修 |", "",
                "**已證實**", "",
                "- 營收年增40.84%，需求規模持續擴張。",
                "- 營業利益年增67.51%，比營收快約26.67個百分點。",
                "- 營益率升至3.75%，毛利以下轉化效率改善。",
                "- AI營收規模與管理層前瞻出貨指引已有官方支持。", "",
                "**尚未證實**", "",
                "- AI特定營業利益與自由現金流貢獻。",
                "- AI特定營業利益金額與利潤率。",
                "- 資本報酬率與增量資本報酬率改善。",
                "- 股利能力與退休現金流安全邊際上升。", "",
                "**退休任務結論：** 核心資產安全性尚未被推翻，但現金與資本效率證據不足，安全邊際不予上修。", "",
            ])
            section_map = {item.section_id: item for item in report.sections}
            for title, section_ids in QUARTERLY_VISIBLE_GROUPS:
                items = [section_map[section_id] for section_id in section_ids]
                lines.extend([f"## {title}", ""])
                for item in items:
                    lines.extend([item.body_zh, ""])
                metric = self._FORMULA_CARD_GROUP.get(title)
                selected = next((card for card in formula_cards if card.get("metric") == metric), None)
                if selected is not None:
                    lines.extend(self._formula_card(selected))
                if title == "治理、企業價值與退休任務總結":
                    lines.extend(self._value_branches())
                evidence_ids = list(dict.fromkeys(value for item in items for value in item.evidence_ids))
                if evidence_ids:
                    lines.extend([f"引用：{', '.join(f'[{item}]' for item in evidence_ids)}", ""])
                for chart in charts:
                    if self._CHART_GROUP.get(chart.chart_id) == title:
                        lines.extend(self._visual(chart))
        else:
            for section in report.sections:
                lines.extend([f"## {section.title_zh}", "", section.body_zh, ""])
                if section.evidence_ids:
                    lines.extend([f"引用：{', '.join(f'[{item}]' for item in section.evidence_ids)}", ""])
        footer = (
            "本文件為研究候選，不具交易可執行性；不構成個人化投資建議或交易指令。"
            if report.event_type == "QUARTERLY_EARNINGS"
            else "本文件為研究候選，actionable=false；不構成個人化投資建議或交易指令。"
        )
        lines.extend(["---", "", footer, ""])
        return "\n".join(lines)
