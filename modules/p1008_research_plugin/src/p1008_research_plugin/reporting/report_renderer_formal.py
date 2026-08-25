"""Formal, non-publishing HTML/PDF preview renderer for Owner review."""

from __future__ import annotations

import html
import re
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Sequence

from .report_contracts import ChartData, QUARTERLY_VISIBLE_GROUPS, ReportCandidate


class FormalPreviewRenderer:
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
    _DISPLAY_CODES = {
        "PROVEN": "已證實",
        "PROVEN_DERIVED": "官方數字推導／已驗證",
        "PARTIALLY_PROVEN": "部分證實",
        "PARTIALLY_PROVEN_HIGH_CONFIDENCE_INFERENCE": "部分證實／高信心推論",
        "UNPROVEN": "尚未證實",
        "UNPROVEN_SPECIFIC_AMOUNT": "特定金額尚未證實",
        "INSUFFICIENT_DATA": "資料不足",
        "SUPPORTED": "已獲支持",
        "SUPPORTED_MANAGEMENT_GUIDANCE": "管理層指引支持",
        "SUPPORTED_BY_GUIDANCE": "管理層指引支持",
        "EVIDENCE_BUILDING": "證據累積中",
        "OFFICIAL_VERIFIED": "官方治理來源已驗證",
        "NOT_VERIFIED": "尚未驗證",
        "NOT_SEPARATELY_DISCLOSED": "未單獨揭露",
        "UNRESOLVED": "尚未釐清",
        "UNQUANTIFIED": "尚未量化",
        "STRATEGY": "策略階段",
        "DEVELOPMENT": "開發／商業化準備",
        "CUSTOMER_ORDER": "客戶／訂單驗證",
        "REVENUE": "已進入營收",
        "OPERATING_PROFIT": "已進入營業獲利驗證",
        "SHAREHOLDER_RETURN": "已進入股東回報驗證",
        "MEDIUM": "中等",
        "HOLD": "維持",
        "WAIT": "估值觀察",
        "Revenue": "營收",
        "Gross Profit": "毛利",
        "Operating Profit": "營業利益",
        "NOPAT": "稅後營業利益",
        "ROIC": "資本報酬率",
        "CFO": "營業現金流",
        "FCF": "自由現金流",
        "Dividend Capacity": "股利能力",
        "Shareholder Return": "股東回報",
        "Retirement Cashflow Safety": "退休現金流安全",
    }
    _COLORS = ("#245b8a", "#b8872b", "#6b7f3f", "#8a4569")

    @classmethod
    def _display(cls, value: str) -> str:
        value = str(value)
        value = cls._DISPLAY_CODES.get(value, value)
        for source, target in (
            ("OBSERVATION：", "發現："),
            ("INTERPRETATION：", "解釋："),
            ("P1008_IMPLICATION：", "投資研究含義："),
            ("P1008含義：", "投資研究含義："),
            ("P1008", "戰情室"),
            ("OWNER REVIEW REQUIRED", "審閱版｜尚未正式發布"),
            ("STRUCTURAL_RISK_NOT_RULED_OUT", "結構性風險尚未排除"),
            ("CORE_HOLDING_THESIS", "核心持有論點"),
            ("ADD_ON_CAPITAL_GATE", "增量資本檢核"),
            ("THESIS_DOWNGRADE_GATE", "論點降級檢核"),
            ("官方Results", "官方結果簡報"),
        ):
            value = value.replace(source, target)
        value = re.sub(r"\bT[0-4](?:_[A-Z0-9_]+)?\b", "內部證據分類", value)
        value = re.sub(r"\b(?:AUTH|IR-EVIDENCE)-[A-Z0-9_-]+\b", "受治理來源", value)
        value = re.sub(r"(?<![A-Za-z])Consignment(?![A-Za-z]|（客供料）)", "Consignment（客供料）", value)
        match = re.fullmatch(r"([+-]?\d+\.\d{4,})(%?)", value)
        if match:
            try:
                rounded = Decimal(match.group(1)).quantize(Decimal("0.001"))
                value = f"{format(rounded, 'f').rstrip('0').rstrip('.')}{match.group(2)}"
            except InvalidOperation:
                pass
        return value.replace("LIMITED_HISTORY", "歷史資料有限")

    @staticmethod
    def _source_label(value: str) -> str:
        if value.startswith("AUTH-MASTER-"):
            return "正式財務基線"
        if value.startswith("AUTH-PRICE-") or value.startswith("AUTH-MARKET-ACTIVITY-"):
            return "臺灣證券交易所資料"
        if value.startswith("AUTH-CASHFLOW-"):
            return "鴻海官方財報"
        if value.startswith("IR-EVIDENCE-"):
            return "鴻海法說資料"
        return "本報告推導"

    @staticmethod
    def visible_label_indexes(labels: Sequence[str]) -> list[int]:
        if len(labels) <= 8:
            return list(range(len(labels)))
        selected = {0, len(labels) - 1}
        selected.update(index for index, label in enumerate(labels) if str(label).endswith("Q4"))
        if len(selected) < 4:
            selected.update(range(0, len(labels), max(1, len(labels) // 5)))
        return sorted(selected)

    @classmethod
    def _pdf_text(cls, value: str) -> str:
        value = cls._display(value)
        return (
            value.replace("≈", "約")
            .replace("÷", "除以")
            .replace("×", "乘以")
            .replace("OWNER_REVIEW_REQUIRED", "待Owner審閱")
            .replace("PUBLICATION=NO", "未授權發布")
        )

    @staticmethod
    def _number(value: str) -> float | None:
        try:
            return float(value.replace("%", "").replace(",", ""))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _table(cls, chart: ChartData, indexes: list[int] | None = None) -> str:
        indexes = indexes if indexes is not None else list(range(len(chart.labels)))
        header = "<th>項目</th>" + "".join(
            f"<th>{html.escape(series.label_zh)}</th>" for series in chart.series
        )
        rows = []
        for index in indexes:
            cells = [f"<td>{html.escape(chart.labels[index])}</td>"]
            for series in chart.series:
                raw = series.values[index] if index < len(series.values) else "資料未提供"
                cells.append(f"<td>{html.escape(cls._display(raw))}</td>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
        return f'<table><thead><tr>{header}</tr></thead><tbody>{"".join(rows)}</tbody></table>'

    @classmethod
    def _line_svg(cls, chart: ChartData, series_limit: int | None = None) -> str:
        rendered_series = chart.series[:series_limit] if series_limit is not None else chart.series
        width, height = 860, 360
        left, right, top, bottom = 66, 24, 28, 60
        plot_w, plot_h = width - left - right, height - top - bottom
        all_values = [
            number
            for series in rendered_series
            for value in series.values
            if (number := cls._number(value)) is not None
        ]
        if not all_values:
            return '<p class="chart-unavailable">資料不足，無法繪圖。</p>'
        low, high = min(all_values), max(all_values)
        padding = max((high - low) * 0.12, 0.5)
        low, high = low - padding, high + padding
        span = high - low or 1.0
        x_at = lambda index: left + (plot_w * index / max(1, len(chart.labels) - 1))
        y_at = lambda value: top + plot_h - ((value - low) / span * plot_h)
        label_indexes = set(cls.visible_label_indexes(chart.labels))
        parts = [
            f'<svg class="actual-chart line-chart" data-chart-object="line" data-point-count="{len(chart.labels)}" data-label-count="{len(label_indexes)}" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(chart.title_zh)}">',
            '<rect x="0" y="0" width="860" height="360" fill="#ffffff"/>',
        ]
        for step in range(5):
            value = low + span * step / 4
            y = y_at(value)
            parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#d8dee6" stroke-width="1"/>')
            parts.append(f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" class="axis-label">{value:.1f}</text>')
        parts.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#536273"/>')
        parts.append(f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#536273"/>')
        for index, label in enumerate(chart.labels):
            if index not in label_indexes:
                continue
            x = x_at(index)
            parts.append(f'<text x="{x:.1f}" y="{height-bottom+22}" text-anchor="middle" class="axis-label">{html.escape(label)}</text>')
        for series_index, series in enumerate(rendered_series):
            points = []
            for index, raw in enumerate(series.values):
                number = cls._number(raw)
                if number is not None:
                    points.append((x_at(index), y_at(number), raw))
            color = cls._COLORS[series_index % len(cls._COLORS)]
            parts.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y, _ in points)}" fill="none" stroke="{color}" stroke-width="3"/>')
            for index, (x, y, raw) in enumerate(points):
                radius = 5 if index == len(points) - 1 else 3
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{color}"/>')
                if index == len(points) - 1:
                    parts.append(f'<text x="{x-4:.1f}" y="{y-10:.1f}" text-anchor="end" class="point-label">{html.escape(raw)}</text>')
            legend_x = left + series_index * 210
            parts.append(f'<line x1="{legend_x}" y1="344" x2="{legend_x+24}" y2="344" stroke="{color}" stroke-width="4"/>')
            parts.append(f'<text x="{legend_x+31}" y="348" class="legend-label">{html.escape(series.label_zh)}（{html.escape(series.unit)}）</text>')
        parts.append("</svg>")
        return "".join(parts)

    @classmethod
    def _working_capital_visual(cls, chart: ChartData) -> str:
        ccc = chart.series[3].values
        return (
            cls._line_svg(chart, series_limit=3)
            + '<div class="ccc-callout"><span>現金循環週期</span>'
            + f'<strong>{html.escape("天 → ".join(ccc))}天</strong>'
            + '<small>獨立KPI，不與指數共用尺度</small></div>'
        )

    @classmethod
    def _roe_bvps_visual(cls, chart: ChartData) -> str:
        return (
            cls._line_svg(chart, series_limit=1)
            + '<div class="roe-callout"><span>可比H1 ROE</span><strong>5.48% → 6.21%</strong>'
            + '<small>年增 +0.73個百分點；2025全年11.3%僅作全年脈絡，H1不年化</small></div>'
        )

    @classmethod
    def _formula_card_html(cls, card: dict[str, str]) -> str:
        metric = card["metric"]
        result = cls._display(card["currentResult"])
        derived = '<span class="formula-scope">DERIVED FROM OFFICIAL COMPARABLE PERIODS</span>' if metric == "自由現金流" else ""
        return (
            f'<aside class="formula-card" data-formula-card="{html.escape(metric)}">'
            f'<h3>{html.escape(cls._FORMULA_CARD_TITLES[metric])}</h3>'
            f'<p class="formula">{html.escape(cls._display(card["formula"]))}</p>'
            f'<p>{html.escape(cls._display(card["plainLanguage"]))}</p>'
            f'<p class="formula-current"><strong>本期：</strong>{html.escape(result)}</p>{derived}</aside>'
        )

    @staticmethod
    def _branched_value_chain_html() -> str:
        return (
            '<div class="value-branches" aria-label="企業價值三分支驗證模型">'
            '<p class="value-trunk"><strong>管理承諾 → 策略 → 執行 → 營收 → 毛利 → 營業利益</strong></p>'
            '<table class="branch-grid"><tbody><tr>'
            '<td><h3>企業資本效率</h3><p>營業利益 → NOPAT → ROIC</p><small>營運資本是否有效創造報酬？</small></td>'
            '<td><h3>股東資本效率</h3><p>營業利益 → 稅前利益 → 淨利 → ROE → BVPS</p><small>股東資本是否被有效使用？</small></td>'
            '<td><h3>現金生成</h3><p>淨利＋非現金項目±營運資金 → CFO－Capex → FCF</p><small>帳面獲利是否變成自由現金？</small></td>'
            '</tr></tbody></table><p class="value-convergence">ROIC ＋ ROE／BVPS ＋ FCF → 股利能力／股東回報 → 退休現金流安全</p></div>'
        )

    @classmethod
    def _bar_svg(cls, chart: ChartData) -> str:
        width, height = 860, 360
        values = [cls._number(value) or 0.0 for value in chart.series[0].values]
        maximum = max(max(values), 80.0)
        parts = [
            f'<svg class="actual-chart bar-chart" data-chart-object="bar" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(chart.title_zh)}">',
            '<rect x="0" y="0" width="860" height="360" fill="#ffffff"/>',
        ]
        left, base_y, plot_h = 86, 292, 230
        for step in range(5):
            value = maximum * step / 4
            y = base_y - plot_h * step / 4
            parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="790" y2="{y:.1f}" stroke="#d8dee6"/>')
            parts.append(f'<text x="{left-9}" y="{y+4:.1f}" text-anchor="end" class="axis-label">{value:.0f}%</text>')
        for index, (label, value) in enumerate(zip(chart.labels[:2], values[:2])):
            x = 205 + index * 250
            bar_h = plot_h * value / maximum
            color = cls._COLORS[index]
            parts.append(f'<rect x="{x}" y="{base_y-bar_h:.1f}" width="120" height="{bar_h:.1f}" fill="{color}" rx="5"/>')
            parts.append(f'<text x="{x+60}" y="{base_y-bar_h-12:.1f}" text-anchor="middle" class="bar-value">+{value:.1f}%</text>')
            parts.append(f'<text x="{x+60}" y="{base_y+24}" text-anchor="middle" class="axis-label">{html.escape(label)}</text>')
        spread = values[2] if len(values) > 2 else values[1] - values[0]
        parts.append('<rect x="606" y="103" width="190" height="104" fill="#fff5d9" stroke="#b8872b" rx="8"/>')
        parts.append('<text x="701" y="137" text-anchor="middle" class="spread-label">營運槓桿差</text>')
        parts.append(f'<text x="701" y="183" text-anchor="middle" class="spread-value">+{spread:.1f}個百分點</text>')
        parts.append("</svg>")
        return "".join(parts)

    @classmethod
    def _scenario_matrices(cls, chart: ChartData) -> str:
        values = chart.series[0].values
        translations = {
            "Forward P/E": "前瞻本益比情境矩陣",
            "P/B": "股價淨值比情境矩陣",
            "Dividend Yield": "股息殖利率情境矩陣",
        }
        blocks = ['<p class="current-price">財報公布前收盤價：<strong>263元</strong></p>']
        for name in dict.fromkeys(values):
            indexes = [index for index, value in enumerate(values) if value == name]
            if name == "Forward P/E":
                inputs = list(dict.fromkeys(chart.series[1].values[index] for index in indexes))
                multiples = list(dict.fromkeys(chart.series[2].values[index] for index in indexes))
                lookup = {
                    (chart.series[1].values[index], chart.series[2].values[index]): chart.series[3].values[index]
                    for index in indexes
                }
                header = "<th>每股盈餘情境</th>" + "".join(f"<th>{html.escape(value)}</th>" for value in multiples)
                rows = [
                    "<tr><td>" + html.escape(input_value) + "</td>" + "".join(
                        f"<td>{html.escape(lookup[(input_value, multiple)])}</td>" for multiple in multiples
                    ) + "</tr>"
                    for input_value in inputs
                ]
            else:
                header = "<th>倍數／殖利率</th><th>情境參考值</th>"
                rows = []
                for index in indexes:
                    cells = [chart.series[2].values[index], chart.series[3].values[index]]
                    current = any(cls._number(cell) == 263.0 for cell in cells)
                    row_class = ' class="current-row"' if current else ""
                    rows.append(f"<tr{row_class}>" + "".join(f"<td>{html.escape(cls._display(cell))}</td>" for cell in cells) + "</tr>")
            blocks.append(
                f'<div class="scenario-block" data-scenario-matrix="{html.escape(name)}">'
                f'<h4>{translations.get(name, name)}</h4><table><thead><tr>{header}</tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table></div>'
            )
        blocks.append('<p class="matrix-note">以上均為敏感度情境，只供比較，不形成估值結論或交易建議。</p>')
        return "".join(blocks)

    def _visual(self, chart: ChartData) -> str:
        if chart.visualization_type == "QUANTITATIVE_CHART":
            if chart.chart_id == "working_capital_3period":
                body = self._working_capital_visual(chart)
            elif chart.chart_id == "roe_equity_compounding":
                body = self._roe_bvps_visual(chart)
            else:
                body = self._bar_svg(chart) if chart.chart_id == "operating_leverage_spread" else self._line_svg(chart)
        elif chart.visualization_type == "SCENARIO_MATRIX":
            body = self._scenario_matrices(chart)
        else:
            body = self._table(chart)
        commentary = "".join(f"<li>{html.escape(self._display(item))}</li>" for item in chart.commentary_zh)
        decision_context = "".join(
            f'<p class="chart-meaning"><strong>{label}</strong>{html.escape(self._display(value))}</p>'
            for label, value in (
                ("觀察：", chart.observation_zh),
                ("解讀：", chart.interpretation_zh),
                ("戰略含義：", chart.strategic_implication_zh),
                ("企業價值含義：", chart.enterprise_value_implication_zh),
                ("下一驗證點：", chart.next_checkpoint_zh),
            )
        )
        return (
            f'<figure data-chart-id="{html.escape(chart.chart_id)}" data-visualization-type="{chart.visualization_type}">'
            f'<figcaption><strong>{html.escape(chart.title_zh)}</strong><br>{html.escape(chart.decision_question)}'
            f'<span class="period">期間：{html.escape(self._display(chart.period))}</span></figcaption>{body}'
            f'<ul class="commentary">{commentary}</ul>{decision_context}<p class="chart-source">來源：{html.escape(", ".join(dict.fromkeys(self._source_label(item) for item in chart.source_evidence_ids)))}</p></figure>'
        )

    @staticmethod
    def _decision_card_html() -> str:
        fields = (
            ("核心論點", "治理政策開始兌現，但真正的價值創造只完成前半程"),
            ("既有持有", "維持"), ("新資金", "估值觀察"), ("信心水準", "中等"),
            ("營運治理", "通過"), ("資本治理", "待驗"), ("現金治理", "未通過"),
            ("安全邊際", "不上修"),
        )
        cells = "".join(f'<div class="decision-field"><span>{label}</span><strong>{value}</strong></div>' for label, value in fields)
        proven = "".join(f"<li>{item}</li>" for item in (
            "營收年增41%，需求規模持續擴張。",
            "營業利益年增67.51%，比營收快約26.67個百分點。",
            "營益率升至3.75%，毛利以下轉化效率改善。",
            "AI營收規模與管理層前瞻出貨指引已有官方支持。",
        ))
        unproven = "".join(f"<li>{item}</li>" for item in (
            "AI特定營業利益與自由現金流貢獻。",
            "AI特定營業利益金額與利潤率。",
            "資本報酬率與增量資本報酬率改善。",
            "股利能力與退休現金流安全邊際上升。",
        ))
        return (
            f'<section class="decision-card" aria-label="執行決策卡"><div class="decision-grid">{cells}</div>'
            f'<div class="evidence-split"><div><h3>已證實</h3><ul>{proven}</ul></div>'
            f'<div><h3>尚未證實</h3><ul>{unproven}</ul></div></div>'
            '<p class="retirement-conclusion"><strong>退休任務結論：</strong>核心資產安全性尚未被推翻，但現金與資本效率證據不足，安全邊際不予上修。</p></section>'
        )

    def html(self, report: ReportCandidate, charts: Sequence[ChartData] = (), formula_cards: Sequence[dict[str, str]] = ()) -> bytes:
        section_map = {item.section_id: item for item in report.sections}
        if report.event_type == "QUARTERLY_EARNINGS":
            grouped = []
            for title, section_ids in QUARTERLY_VISIBLE_GROUPS:
                items = [section_map[section_id] for section_id in section_ids]
                paragraphs = "".join(
                    f'<p data-source-section="{html.escape(item.section_id)}">{html.escape(item.body_zh)}</p>'
                    for item in items
                )
                evidence_ids = list(dict.fromkeys(value for item in items for value in item.evidence_ids))
                visuals = "".join(self._visual(chart) for chart in charts if self._CHART_GROUP.get(chart.chart_id) == title)
                if title == "治理、企業價值與退休任務總結":
                    visuals = self._branched_value_chain_html() + visuals
                metric = self._FORMULA_CARD_GROUP.get(title)
                formula = next((self._formula_card_html(card) for card in formula_cards if card.get("metric") == metric), "")
                grouped.append(
                    f'<section data-visible-group="{html.escape(title)}"><h2>{html.escape(title)}</h2>{paragraphs}{formula}{visuals}'
                    f'<p class="evidence">引用：{html.escape(", ".join(evidence_ids) or "治理邊界")}</p></section>'
                )
            sections = "\n".join(grouped)
        else:
            sections = "\n".join(
                f'<section data-section-id="{html.escape(item.section_id)}"><h2>{html.escape(item.title_zh)}</h2>'
                f'<p>{html.escape(item.body_zh)}</p><p class="evidence">引用：{html.escape(", ".join(item.evidence_ids) or "治理邊界")}</p></section>'
                for item in report.sections
            )
        references = "\n".join(
            f'<li><strong>{html.escape(item.evidence_id)}</strong> — {html.escape(item.claim)} '
            f'({html.escape(item.source_tier)}, {html.escape(item.source_date)})<br>'
            + " ".join(f'<a href="{html.escape(url)}">{html.escape(url)}</a>' for url in item.source_urls)
            + "</li>"
            for item in report.evidence_references
        )
        if report.event_type != "QUARTERLY_EARNINGS":
            document = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><title>P1008 鴻海 FY2026 Q2 企業價值戰報</title>
<style>body{{font-family:system-ui,"Noto Sans TC",sans-serif;max-width:1120px;margin:32px auto;padding:0 24px;color:#17202a;line-height:1.72}}header{{border-bottom:4px solid #23395d;padding-bottom:18px}}h1{{margin-bottom:4px}}h2{{color:#23395d;margin-top:34px;border-left:5px solid #b8872b;padding-left:12px}}h4{{margin:14px 0 6px}}.status{{display:inline-block;background:#fff3cd;border:1px solid #d6b656;padding:5px 10px}}.evidence{{font-size:.82rem;color:#52606d}}section,figure{{break-inside:avoid}}figure{{margin:22px 0;padding:18px;border:1px solid #d7dde5;background:#fbfcfe}}figcaption{{font-size:1.05rem;color:#23395d;margin-bottom:12px}}.period{{display:block;font-size:.82rem;color:#52606d}}table{{width:100%;border-collapse:collapse;margin:10px 0 18px;font-size:.86rem}}th,td{{border:1px solid #cbd3dc;padding:7px;vertical-align:top;text-align:left}}th{{background:#eef3f8}}.series{{margin:14px 0}}.bar-row{{display:grid;grid-template-columns:100px 1fr 150px;gap:8px;align-items:center;margin:5px 0;font-size:.82rem}}.bar-track{{display:block;background:#e6ebf0;height:14px}}.bar{{display:block;background:#356a9a;height:14px}}.commentary{{font-size:.88rem;margin-bottom:0}}a{{color:#174ea6;overflow-wrap:anywhere}}footer{{margin-top:36px;border-top:1px solid #ccd2d8;padding-top:16px}}@media(max-width:720px){{.bar-row{{grid-template-columns:80px 1fr}}.bar-row strong{{grid-column:2}}table{{font-size:.74rem}}}}</style></head>
<body data-run-id="{html.escape(report.run_id)}" data-event-type="{html.escape(report.event_type)}" data-publication="false">
<header><h1>P1008｜鴻海 FY2026 Q2 企業價值戰報</h1><p><strong>治理政策開始兌現，但真正的價值創造只完成前半程</strong></p><p>{html.escape(report.primary_investor_question)}</p><p class="status">OWNER_REVIEW_REQUIRED · PUBLICATION=NO</p></header>
{sections}<section><h2>證據來源</h2><ol>{references}</ol></section>
<footer>actionable=false · publishAuthorized=false · Owner-gated preview</footer></body></html>"""
            return document.encode("utf-8")
        decision_card = self._decision_card_html() if report.event_type == "QUARTERLY_EARNINGS" else ""
        document = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><title>P1008 鴻海 FY2026 Q2 企業價值戰報</title>
<style>body{{font-family:system-ui,"Noto Sans TC",sans-serif;max-width:1120px;margin:32px auto;padding:0 24px;color:#17202a;line-height:1.72}}header{{border-bottom:4px solid #23395d;padding-bottom:18px}}h1{{margin-bottom:4px}}h2{{color:#23395d;margin-top:34px;border-left:5px solid #b8872b;padding-left:12px}}h3{{color:#23395d}}h4{{margin:14px 0 6px}}.status{{display:inline-block;background:#fff3cd;border:1px solid #d6b656;padding:5px 10px}}.decision-card{{margin:24px 0;padding:22px;border:2px solid #23395d;background:#f7f9fc}}.decision-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.decision-field{{padding:10px;background:#fff;border-left:4px solid #b8872b}}.decision-field span{{display:block;color:#596575;font-size:.78rem}}.decision-field strong{{display:block;color:#1d3557}}.evidence-split{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}.retirement-conclusion{{padding:12px;background:#fff5d9}}.evidence{{font-size:.82rem;color:#52606d}}section,figure{{break-inside:avoid}}figure{{margin:22px 0;padding:18px;border:1px solid #d7dde5;background:#fbfcfe}}figcaption{{font-size:1.05rem;color:#23395d;margin-bottom:12px}}.period{{display:block;font-size:.82rem;color:#52606d}}table{{width:100%;border-collapse:collapse;margin:10px 0 18px;font-size:.82rem}}th,td{{border:1px solid #cbd3dc;padding:7px;vertical-align:top;text-align:left}}th{{background:#eef3f8}}.actual-chart{{width:100%;height:auto;border:1px solid #e0e5eb;background:white}}.axis-label,.legend-label,.point-label,.bar-value,.spread-label,.spread-value{{font-family:system-ui,"Noto Sans TC",sans-serif;fill:#25384d}}.axis-label,.legend-label{{font-size:12px}}.point-label,.bar-value{{font-size:13px;font-weight:700}}.spread-label{{font-size:16px}}.spread-value{{font-size:22px;font-weight:800;fill:#9b6b15}}.ccc-callout,.roe-callout{{display:grid;grid-template-columns:1fr auto;gap:4px 16px;align-items:center;margin:10px 0;padding:12px 16px;background:#fff5d9;border-left:4px solid #b8872b}}.ccc-callout strong,.roe-callout strong{{font-size:1.25rem;color:#23395d}}.ccc-callout small,.roe-callout small{{grid-column:1/-1;color:#596575}}.formula-card{{margin:14px 0;padding:12px 16px;background:#eef3f8;border-left:5px solid #245b8a}}.formula-card h3,.formula-card p{{margin:3px 0}}.formula{{font-weight:700;color:#1d3557}}.formula-current{{color:#8a5a10}}.formula-scope{{display:block;font-size:.72rem;color:#596575}}.value-branches{{margin:16px 0;padding:16px;background:#f7f9fc;border:1px solid #cbd3dc}}.value-trunk,.value-convergence{{text-align:center;padding:10px;background:#eef3f8}}.branch-grid{{table-layout:fixed;border-collapse:separate;border-spacing:12px;background:transparent}}.branch-grid td{{padding:12px;background:#fff;border:0;border-top:4px solid #245b8a}}.branch-grid h3{{margin:0}}.commentary{{font-size:.88rem;margin-bottom:4px}}.chart-source{{font-size:.76rem;color:#687687}}.current-price{{padding:9px 12px;background:#eaf2fb;border-left:4px solid #245b8a}}.current-row td{{background:#fff2c8;font-weight:700}}.scenario-block{{margin:18px 0}}.matrix-note{{font-size:.84rem;color:#596575}}a{{color:#174ea6;overflow-wrap:anywhere}}footer{{margin-top:36px;border-top:1px solid #ccd2d8;padding-top:16px}}@media(max-width:760px){{.decision-grid{{grid-template-columns:1fr 1fr}}.evidence-split{{grid-template-columns:1fr}}.branch-grid,.branch-grid tbody,.branch-grid tr,.branch-grid td{{display:block;width:auto}}table{{font-size:.72rem}}}}</style></head>
<body data-run-id="{html.escape(report.run_id)}" data-event-type="{html.escape(report.event_type)}" data-publication="false">
<header><h1>P1008｜鴻海 FY2026 Q2 企業價值戰報</h1><p><strong>治理政策開始兌現，但真正的價值創造只完成前半程</strong></p><p>{html.escape(report.primary_investor_question)}</p><p class="status">待Owner審閱 · 未授權發布</p></header>
{decision_card}{sections}<section><h2>證據來源</h2><ol>{references}</ol></section>
<footer>研究候選 · 不具交易可執行性 · 未授權發布</footer></body></html>"""
        return document.encode("utf-8")

    def _legacy_monthly_pdf(self, report: ReportCandidate, charts: Sequence[ChartData]) -> bytes:
        try:
            from reportlab.lib.enums import TA_CENTER
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
        except ImportError as exc:
            raise RuntimeError("PDF_PREVIEW_DEPENDENCY_MISSING: reportlab") from exc
        cjk_font = "STSong-Light"
        for font_path in (Path("C:/Windows/Fonts/msjh.ttc"), Path("C:/Windows/Fonts/msjh.ttf"), Path("C:/Windows/Fonts/mingliu.ttc")):
            if font_path.is_file():
                pdfmetrics.registerFont(TTFont("P1008CJK", str(font_path), subfontIndex=0))
                cjk_font = "P1008CJK"
                break
        else:
            pdfmetrics.registerFont(UnicodeCIDFont(cjk_font))
        buffer = BytesIO()
        document = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm, title="P1008 FY2026 Q2 Owner Review", author="P1008 Phase B1")
        styles = getSampleStyleSheet()
        title = ParagraphStyle("CJKTitle", parent=styles["Title"], fontName=cjk_font, fontSize=20, leading=27, alignment=TA_CENTER, textColor="#23395d")
        heading = ParagraphStyle("CJKHeading", parent=styles["Heading2"], fontName=cjk_font, fontSize=13, leading=18, textColor="#23395d", spaceBefore=12, spaceAfter=6)
        body = ParagraphStyle("CJKBody", parent=styles["BodyText"], fontName=cjk_font, fontSize=9.5, leading=15, spaceAfter=6)
        evidence = ParagraphStyle("CJKEvidence", parent=body, fontSize=7.5, leading=11, textColor="#52606d")
        story = [Paragraph("P1008｜鴻海 FY2026 Q2 企業價值戰報", title), Spacer(1, 8), Paragraph("治理政策開始兌現，但真正的價值創造只完成前半程", heading), Paragraph(html.escape(report.primary_investor_question), body), Paragraph("OWNER_REVIEW_REQUIRED · PUBLICATION=NO", heading), Spacer(1, 6)]
        for item in report.sections:
            story.extend([
                Paragraph(html.escape(item.title_zh), heading),
                Paragraph(html.escape(item.body_zh), body),
                Paragraph("Evidence: " + html.escape(", ".join(item.evidence_ids) or "governance boundary"), evidence),
            ])
        if charts:
            story.extend([PageBreak(), Paragraph("決策視覺與證據矩陣", heading)])
            for chart in charts:
                story.append(Paragraph(html.escape(f"{chart.title_zh}｜{chart.decision_question}"), heading))
                for index, label in enumerate(chart.labels):
                    values = "；".join(f"{series.label_zh}={series.values[index] if index < len(series.values) else '資料未提供'}" for series in chart.series)
                    story.append(Paragraph(html.escape(f"{label}：{values}"), body))
        story.extend([PageBreak(), Paragraph("Evidence references", heading)])
        for item in report.evidence_references:
            story.append(Paragraph(html.escape(f"{item.evidence_id} — {item.claim} ({item.source_tier}, {item.source_date})"), evidence))
            for url in item.source_urls:
                story.append(Paragraph(html.escape(url), evidence))
        story.append(Paragraph("actionable=false · publishAuthorized=false · Owner-gated preview", evidence))
        document.build(story)
        return buffer.getvalue()

    def pdf(self, report: ReportCandidate, charts: Sequence[ChartData] = (), formula_cards: Sequence[dict[str, str]] = ()) -> bytes:
        if report.event_type != "QUARTERLY_EARNINGS":
            return self._legacy_monthly_pdf(report, charts)
        try:
            from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Rect, String
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_CENTER
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        except ImportError as exc:
            raise RuntimeError("PDF_PREVIEW_DEPENDENCY_MISSING: reportlab") from exc
        cjk_font = "STSong-Light"
        for font_path in (Path("C:/Windows/Fonts/msjh.ttc"), Path("C:/Windows/Fonts/msjh.ttf"), Path("C:/Windows/Fonts/mingliu.ttc")):
            if font_path.is_file():
                pdfmetrics.registerFont(TTFont("P1008CJK", str(font_path), subfontIndex=0))
                cjk_font = "P1008CJK"
                break
        else:
            pdfmetrics.registerFont(UnicodeCIDFont(cjk_font))
        styles = getSampleStyleSheet()
        title = ParagraphStyle("CJKTitle", parent=styles["Title"], fontName=cjk_font, fontSize=20, leading=27, alignment=TA_CENTER, textColor="#23395d")
        heading = ParagraphStyle("CJKHeading", parent=styles["Heading2"], fontName=cjk_font, fontSize=13, leading=18, textColor="#23395d", spaceBefore=12, spaceAfter=6)
        body = ParagraphStyle("CJKBody", parent=styles["BodyText"], fontName=cjk_font, fontSize=9.2, leading=14, spaceAfter=6)
        small = ParagraphStyle("CJKSmall", parent=body, fontSize=7.1, leading=10, textColor="#52606d")
        card_label = ParagraphStyle("CardLabel", parent=small, textColor="#596575")
        card_value = ParagraphStyle("CardValue", parent=body, fontSize=9, leading=12, textColor="#1d3557")

        def paragraph(value: str, style=body):
            return Paragraph(html.escape(self._pdf_text(value)), style)

        def line_drawing(chart: ChartData, series_limit: int | None = None) -> Drawing:
            rendered_series = chart.series[:series_limit] if series_limit is not None else chart.series
            drawing = Drawing(470, 225)
            left, right, top, bottom = 50, 12, 20, 42
            plot_w, plot_h = 470 - left - right, 225 - top - bottom
            values = [number for series in rendered_series for raw in series.values if (number := self._number(raw)) is not None]
            low, high = min(values), max(values)
            pad = max((high - low) * 0.12, 0.5)
            low, high = low - pad, high + pad
            span = high - low or 1.0
            x_at = lambda index: left + plot_w * index / max(1, len(chart.labels) - 1)
            y_at = lambda value: bottom + (value - low) / span * plot_h
            drawing.add(Rect(0, 0, 470, 225, fillColor=colors.white, strokeColor=colors.HexColor("#d7dde5")))
            for step in range(5):
                value = low + span * step / 4
                y = y_at(value)
                drawing.add(Line(left, y, 470 - right, y, strokeColor=colors.HexColor("#d8dee6"), strokeWidth=0.5))
                drawing.add(String(left - 5, y - 2, f"{value:.1f}", fontName=cjk_font, fontSize=6, textAnchor="end", fillColor=colors.HexColor("#52606d")))
            drawing.add(Line(left, bottom, left, 225 - top, strokeColor=colors.HexColor("#536273")))
            drawing.add(Line(left, bottom, 470 - right, bottom, strokeColor=colors.HexColor("#536273")))
            for index, label in enumerate(chart.labels):
                drawing.add(String(x_at(index), bottom - 13, label, fontName=cjk_font, fontSize=5.8, textAnchor="middle", fillColor=colors.HexColor("#52606d")))
            for series_index, series in enumerate(rendered_series):
                color = colors.HexColor(self._COLORS[series_index % len(self._COLORS)])
                points = []
                for index, raw in enumerate(series.values):
                    number = self._number(raw)
                    if number is not None:
                        points.extend((x_at(index), y_at(number)))
                drawing.add(PolyLine(points, strokeColor=color, strokeWidth=2, fillColor=None))
                for point_index in range(0, len(points), 2):
                    drawing.add(Circle(points[point_index], points[point_index + 1], 3 if point_index == len(points) - 2 else 2, fillColor=color, strokeColor=None))
                legend_x = left + series_index * 135
                drawing.add(Line(legend_x, 10, legend_x + 18, 10, strokeColor=color, strokeWidth=3))
                drawing.add(String(legend_x + 23, 7, self._pdf_text(series.label_zh), fontName=cjk_font, fontSize=6.5, fillColor=colors.HexColor("#25384d")))
            return drawing

        def callout(title_text: str, value_text: str, note_text: str) -> Table:
            table = Table([[paragraph(title_text, card_label), paragraph(value_text, card_value)], [paragraph(note_text, small), ""]], colWidths=[80 * mm, 90 * mm])
            table.setStyle(TableStyle([
                ("SPAN", (0, 1), (1, 1)), ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#b8872b")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff5d9")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            return table

        def formula_card(card: dict[str, str]) -> Table:
            metric = card["metric"]
            rows = [
                [paragraph(self._FORMULA_CARD_TITLES[metric], card_value)],
                [paragraph(self._display(card["formula"]), card_value)],
                [paragraph(self._display(card["plainLanguage"]), small)],
                [paragraph("本期：" + self._display(card["currentResult"]), small)],
            ]
            if metric == "自由現金流":
                rows.append([paragraph("DERIVED FROM OFFICIAL COMPARABLE PERIODS", small)])
            table = Table(rows, colWidths=[170 * mm])
            table.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#245b8a")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef3f8")),
                ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            return table

        def value_branches() -> Table:
            rows = [
                [paragraph("管理承諾 → 策略 → 執行 → 營收 → 毛利 → 營業利益", card_value)],
                [plain_table([
                    ["企業資本效率", "股東資本效率", "現金生成"],
                    ["營業利益 → NOPAT → ROIC", "營業利益 → 稅前利益 → 淨利 → ROE → BVPS", "淨利＋非現金項目±營運資金 → CFO－Capex → FCF"],
                    ["營運資本是否有效創造報酬？", "股東資本是否被有效使用？", "帳面獲利是否變成自由現金？"],
                ])],
                [paragraph("ROIC ＋ ROE／BVPS ＋ FCF → 股利能力／股東回報 → 退休現金流安全", card_value)],
            ]
            table = Table(rows, colWidths=[170 * mm])
            table.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#245b8a")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3f8")), ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#fff5d9")), ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
            return table

        def bar_drawing(chart: ChartData) -> Drawing:
            drawing = Drawing(470, 225)
            values = [self._number(raw) or 0.0 for raw in chart.series[0].values]
            maximum = max(max(values), 80.0)
            left, bottom, plot_h = 52, 38, 150
            drawing.add(Rect(0, 0, 470, 225, fillColor=colors.white, strokeColor=colors.HexColor("#d7dde5")))
            for step in range(5):
                y = bottom + plot_h * step / 4
                value = maximum * step / 4
                drawing.add(Line(left, y, 430, y, strokeColor=colors.HexColor("#d8dee6"), strokeWidth=0.5))
                drawing.add(String(left - 5, y - 2, f"{value:.0f}%", fontName=cjk_font, fontSize=6, textAnchor="end"))
            for index, (label, value) in enumerate(zip(chart.labels[:2], values[:2])):
                x = 110 + index * 125
                height = plot_h * value / maximum
                color = colors.HexColor(self._COLORS[index])
                drawing.add(Rect(x, bottom, 68, height, fillColor=color, strokeColor=None))
                drawing.add(String(x + 34, bottom + height + 8, f"+{value:.1f}%", fontName=cjk_font, fontSize=8, textAnchor="middle"))
                drawing.add(String(x + 34, bottom - 14, self._pdf_text(label), fontName=cjk_font, fontSize=7, textAnchor="middle"))
            spread = values[2] if len(values) > 2 else values[1] - values[0]
            drawing.add(Rect(340, 88, 110, 65, rx=5, ry=5, fillColor=colors.HexColor("#fff5d9"), strokeColor=colors.HexColor("#b8872b")))
            drawing.add(String(395, 132, "營運槓桿差", fontName=cjk_font, fontSize=8, textAnchor="middle"))
            drawing.add(String(395, 105, f"+{spread:.1f}個百分點", fontName=cjk_font, fontSize=12, textAnchor="middle", fillColor=colors.HexColor("#9b6b15")))
            return drawing

        def chart_table(chart: ChartData, indexes: list[int] | None = None) -> Table:
            indexes = indexes if indexes is not None else list(range(len(chart.labels)))
            rows = [[paragraph("項目", small), *(paragraph(series.label_zh, small) for series in chart.series)]]
            for index in indexes:
                rows.append([paragraph(chart.labels[index], small), *(paragraph(self._display(series.values[index] if index < len(series.values) else "資料未提供"), small) for series in chart.series)])
            widths = [170 * mm / len(rows[0])] * len(rows[0])
            table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), cjk_font), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3f8")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd3dc")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            return table

        def plain_table(rows: list[list[str]], current_reference: str | None = None) -> Table:
            wrapped = [[paragraph(cell, small) for cell in row] for row in rows]
            widths = [170 * mm / len(rows[0])] * len(rows[0])
            table = Table(wrapped, colWidths=widths, repeatRows=1, hAlign="LEFT")
            commands = [
                ("FONTNAME", (0, 0), (-1, -1), cjk_font),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3f8")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd3dc")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
            if current_reference is not None:
                for row_index, row in enumerate(rows[1:], start=1):
                    if current_reference in row:
                        commands.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#fff2c8")))
            table.setStyle(TableStyle(commands))
            return table

        def chart_flowables(chart: ChartData) -> list[object]:
            title_block = [paragraph(f"{chart.title_zh}｜{chart.decision_question}", heading), paragraph(f"期間：{chart.period}", small)]
            result: list[object] = []
            if chart.visualization_type == "QUANTITATIVE_CHART":
                if chart.chart_id == "working_capital_3period":
                    result.append(KeepTogether([*title_block, line_drawing(chart, 3), callout("現金循環週期", "48天 → 44天 → 42天", "獨立KPI，不與指數共用尺度")]))
                elif chart.chart_id == "roe_equity_compounding":
                    result.append(KeepTogether([*title_block, line_drawing(chart, 1), callout("可比H1 ROE", "5.48% → 6.21%", "年增+0.73個百分點；2025全年11.3%僅作全年脈絡，H1不年化")]))
                else:
                    drawing = bar_drawing(chart) if chart.chart_id == "operating_leverage_spread" else line_drawing(chart)
                    result.append(KeepTogether([*title_block, drawing]))
            elif chart.visualization_type == "SCENARIO_MATRIX":
                result.extend(title_block)
                result.append(paragraph("財報公布前收盤價：263元", body))
                matrix_values = chart.series[0].values
                names = {"Forward P/E": "前瞻本益比情境矩陣", "P/B": "股價淨值比情境矩陣", "Dividend Yield": "股息殖利率情境矩陣"}
                for name in dict.fromkeys(matrix_values):
                    indexes = [i for i, value in enumerate(matrix_values) if value == name]
                    if name == "Forward P/E":
                        inputs = list(dict.fromkeys(chart.series[1].values[i] for i in indexes))
                        multiples = list(dict.fromkeys(chart.series[2].values[i] for i in indexes))
                        lookup = {
                            (chart.series[1].values[i], chart.series[2].values[i]): chart.series[3].values[i]
                            for i in indexes
                        }
                        rows = [["每股盈餘情境", *multiples]] + [
                            [input_value, *(lookup[(input_value, multiple)] for multiple in multiples)]
                            for input_value in inputs
                        ]
                        matrix_table = plain_table(rows)
                    else:
                        rows = [["倍數／殖利率", "情境參考值"]] + [
                            [chart.series[2].values[i], chart.series[3].values[i]]
                            for i in indexes
                        ]
                        matrix_table = plain_table(rows, current_reference="263元")
                    result.append(KeepTogether([paragraph(names.get(name, name), heading), matrix_table]))
                result.append(paragraph("以上均為敏感度情境，只供比較，不形成估值結論或交易建議。", small))
            else:
                result.extend(title_block)
                result.append(chart_table(chart))
            result.extend(paragraph(self._display(item), small) for item in chart.commentary_zh)
            result.extend(paragraph(f"{label}{self._display(value)}", small) for label, value in (
                ("觀察：", chart.observation_zh), ("解讀：", chart.interpretation_zh),
                ("戰略含義：", chart.strategic_implication_zh),
                ("企業價值含義：", chart.enterprise_value_implication_zh),
                ("下一驗證點：", chart.next_checkpoint_zh),
            ))
            result.append(paragraph("來源：" + ", ".join(dict.fromkeys(self._source_label(item) for item in chart.source_evidence_ids)), small))
            result.append(Spacer(1, 5))
            return result

        buffer = BytesIO()
        document = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm, title="P1008 FY2026 Q2 Owner Review", author="P1008 Phase B1")
        story: list[object] = [
            Paragraph("P1008｜鴻海 FY2026 Q2 企業價值戰報", title), Spacer(1, 7),
            paragraph("治理政策開始兌現，但真正的價值創造只完成前半程", heading),
            paragraph(report.primary_investor_question), paragraph("待Owner審閱 · 未授權發布", heading),
        ]
        if report.event_type == "QUARTERLY_EARNINGS":
            card_rows = [
                [paragraph("核心論點", card_label), paragraph("治理政策開始兌現，但真正的價值創造只完成前半程", card_value)],
                [paragraph("既有持有", card_label), paragraph("維持", card_value)],
                [paragraph("新資金", card_label), paragraph("估值觀察", card_value)],
                [paragraph("信心水準", card_label), paragraph("中等", card_value)],
                [paragraph("營運／資本／現金治理", card_label), paragraph("通過／待驗／未通過", card_value)],
                [paragraph("安全邊際", card_label), paragraph("不上修", card_value)],
            ]
            card = Table(card_rows, colWidths=[38 * mm, 132 * mm])
            card.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 1.2, colors.HexColor("#23395d")), ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d7dde5")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3f8")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.extend([
                card, Spacer(1, 7),
                paragraph("已證實：營收年增40.84%；營業利益年增67.51%；營益率升至3.75%；Q2推導CFO與FCF均為負。"),
                paragraph("尚未證實：AI特定獲利金額與利潤率；資本報酬率改善；股利能力與退休現金流安全邊際上升。"),
                paragraph("退休任務結論：核心資產安全性尚未被推翻，但現金與資本效率證據不足，安全邊際不予上修。"),
            ])
        if report.event_type == "QUARTERLY_EARNINGS":
            section_map = {item.section_id: item for item in report.sections}
            for visible_title, section_ids in QUARTERLY_VISIBLE_GROUPS:
                items = [section_map[section_id] for section_id in section_ids]
                evidence_ids = list(dict.fromkeys(value for item in items for value in item.evidence_ids))
                if visible_title == "ROE、股東權益與每股淨值複利":
                    story.append(PageBreak())
                story.append(paragraph(visible_title, heading))
                for item in items:
                    story.append(paragraph(item.body_zh))
                metric = self._FORMULA_CARD_GROUP.get(visible_title)
                selected = next((card for card in formula_cards if card.get("metric") == metric), None)
                if selected is not None:
                    story.append(formula_card(selected))
                    story.append(Spacer(1, 5))
                if visible_title == "治理、企業價值與退休任務總結":
                    story.append(value_branches())
                    story.append(Spacer(1, 5))
                for chart in charts:
                    if self._CHART_GROUP.get(chart.chart_id) == visible_title:
                        story.extend(chart_flowables(chart))
                story.append(paragraph("引用：" + (", ".join(evidence_ids) or "治理邊界"), small))
        else:
            for item in report.sections:
                story.extend([paragraph(item.title_zh, heading), paragraph(item.body_zh), paragraph("引用：" + (", ".join(item.evidence_ids) or "治理邊界"), small)])
        story.append(paragraph("證據來源", heading))
        for item in report.evidence_references:
            story.append(paragraph(f"{item.evidence_id} — {item.claim}（{item.source_tier}，{item.source_date}）", small))
            for url in item.source_urls:
                story.append(paragraph(url, small))
        story.append(paragraph("研究候選 · 不具交易可執行性 · 未授權發布", small))

        def page_number(canvas, doc):
            canvas.saveState(); canvas.setFont(cjk_font, 7); canvas.setFillColor(colors.HexColor("#687687"))
            canvas.drawRightString(A4[0] - 18 * mm, 8 * mm, f"P1008 Owner Review｜{doc.page}"); canvas.restoreState()

        document.build(story, onFirstPage=page_number, onLaterPages=page_number)
        return buffer.getvalue()
