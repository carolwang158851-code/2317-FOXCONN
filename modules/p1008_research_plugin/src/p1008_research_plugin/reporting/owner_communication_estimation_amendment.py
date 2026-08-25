"""Transparent estimate overlay for the FY2026 Q2 Owner Communication.

The frozen research pack remains the semantic baseline.  This module adds a
presentation-only estimate layer from governed local inputs and never writes
the calculations back to authority or the research pack.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from .owner_communication_renderer import OwnerCommunicationRenderer, _escape, _sha


EXPECTED_PACK_SHA = "72B33BD7040F3B55870FC3CA707FB069E9B21DA56C7C153F8541CEADC0114EEE"
EXPECTED_MASTER_SHA = "0BB2FEC6FA3035AC642738BC12EA6959C81C8A79D5221E694BF780427051CF79"
HISTORICAL_ROIC = {
    "2024Q3": Decimal("10.51"), "2024Q4": Decimal("13.16"),
    "2025Q1": Decimal("7.91"), "2025Q2": Decimal("10.66"),
    "2025Q3": Decimal("11.77"), "2025Q4": Decimal("14.41"),
    "2026Q1": Decimal("12.57"),
}


def _q(value: Decimal, places: str) -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _pct(value: Decimal, places: str = "0.01") -> str:
    return f"{_q(value, places):f}%"


@dataclass(frozen=True)
class RoicEstimate:
    effective_tax_pct: Decimal
    nopat_effective_million: Decimal
    historical_tax_pct: Decimal
    nopat_method_annual_100m: Decimal
    invested_capital_begin_100m: Decimal
    invested_capital_base_end_100m: Decimal
    invested_capital_range_low_100m: Decimal
    invested_capital_range_high_100m: Decimal
    roic_low_pct: Decimal
    roic_base_pct: Decimal
    roic_high_pct: Decimal
    nopat_growth_pct: Decimal
    capital_productivity_base_pp: Decimal


class OwnerCommunicationEstimationAmendmentRenderer(OwnerCommunicationRenderer):
    """Render an estimate-transparent amendment without mutating the baseline."""

    def __init__(self, source_dir: Path, master_path: Path) -> None:
        super().__init__(source_dir)
        if self.pack_sha != EXPECTED_PACK_SHA:
            raise ValueError("frozen Research Pack SHA is not the accepted baseline")
        self.master_path = master_path.resolve()
        if _sha(self.master_path) != EXPECTED_MASTER_SHA:
            raise ValueError("governed master SHA is not the accepted authority input")
        self.master_rows = self._read_master(self.master_path)
        self._validate_roic_lineage()
        self.estimate = self._calculate_estimate()

    @staticmethod
    def _read_master(path: Path) -> dict[str, dict[str, str]]:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        header = next((index for index, line in enumerate(lines) if line.startswith("Quarter,")), None)
        if header is None:
            raise ValueError("master authority has no Quarter header")
        return {row["Quarter"]: row for row in csv.DictReader(lines[header:])}

    def _validate_roic_lineage(self) -> None:
        for quarter, expected in HISTORICAL_ROIC.items():
            row = self.master_rows.get(quarter)
            if row is None or Decimal(row["ROIC_Precise_Pct"]) != expected:
                raise ValueError(f"historical ROIC drift: {quarter}")
            reproduced = Decimal(row["NOPAT_Annual_100M"]) / Decimal(row["InvestedCapital_100M"]) * 100
            if abs(reproduced - expected) > Decimal("0.01"):
                raise ValueError(f"historical ROIC cannot be reproduced: {quarter}")

    def _calculate_estimate(self) -> RoicEstimate:
        op_m = Decimal(self.analytics["operatingProfitMillionTwd"])
        pretax_m = Decimal(self.analytics["pretaxProfitMillionTwd"])
        tax_m = Decimal(self.analytics["incomeTaxExpenseMillionTwd"])
        effective_tax = tax_m / pretax_m
        nopat_effective = op_m * (1 - effective_tax)

        q1 = self.master_rows["2026Q1"]
        q1_op = Decimal(q1["OperatingIncome_Q_100M"])
        q1_nopat = Decimal(q1["NOPAT_Annual_100M"])
        historical_tax = 1 - q1_nopat / (q1_op * 4)
        q2_op_100m = op_m / 100
        method_nopat = q2_op_100m * 4 * (1 - historical_tax)
        begin = Decimal(q1["InvestedCapital_100M"])

        recent = [self.master_rows[q] for q in ("2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1")]
        recent_taxes = [
            1 - Decimal(row["NOPAT_Annual_100M"]) / (Decimal(row["OperatingIncome_Q_100M"]) * 4)
            for row in recent
        ]
        invested = [Decimal(row["InvestedCapital_100M"]) for row in recent]
        max_tax, min_tax = max(recent_taxes), min(recent_taxes)
        low_ic, high_ic = min(invested), max(invested)
        roic_low = q2_op_100m * 4 * (1 - max_tax) / high_ic * 100
        roic_base = method_nopat / begin * 100
        roic_high = q2_op_100m * 4 * (1 - min_tax) / low_ic * 100
        nopat_growth = (method_nopat / q1_nopat - 1) * 100
        return RoicEstimate(
            effective_tax_pct=effective_tax * 100,
            nopat_effective_million=nopat_effective,
            historical_tax_pct=historical_tax * 100,
            nopat_method_annual_100m=method_nopat,
            invested_capital_begin_100m=begin,
            invested_capital_base_end_100m=begin,
            invested_capital_range_low_100m=low_ic,
            invested_capital_range_high_100m=high_ic,
            roic_low_pct=roic_low,
            roic_base_pct=roic_base,
            roic_high_pct=roic_high,
            nopat_growth_pct=nopat_growth,
            capital_productivity_base_pp=nopat_growth,
        )

    def _estimated_kpi_rows(self) -> list[list[str]]:
        e = self.estimate
        base = super()._kpi_rows()
        mapped = [[r[0], r[1], "官方值／官方資料衍生", "HIGH", r[2], r[3], r[4], r[5], r[6]] for r in base]
        mapped = [row for row in mapped if row[0] != "資本效率｜ROIC"]
        mapped.extend([
            ["資本效率｜NOPAT", f"單季約{_q(e.nopat_effective_million / 100, '0.1'):f}億元；同口徑年化約{_q(e.nopat_method_annual_100m, '0.1'):f}億元", "估算值", "MEDIUM", "Q2官方營業利益與稅額", "↑", "與歷史口徑接近", "本業稅後獲利增強", "Q3／TTM正常化稅率"],
            ["資本效率｜ROIC", f"約{_q(e.roic_base_pct, '0.1'):f}%（{_q(e.roic_low_pct, '0.1'):f}%–{_q(e.roic_high_pct, '0.1'):f}%）", "估算值", "LOW", "2026Q1 12.57%", "↑（方向性）", f"約+{_q(e.roic_base_pct-Decimal('12.57'),'0.1'):f}個百分點", "資本效率可能改善，尚非官方結論", "Q2期末投入資本／Q3"],
            ["資本效率｜Capital Productivity", f"基準約+{_q(e.capital_productivity_base_pp,'0.1'):f}個百分點", "方向性推論", "LOW", "NOPAT成長－投入資本成長", "↑（假設期末資本持平）", "分母未直接揭露", "稅後營業利益增速可能快於資本", "正式Q2投入資本"],
            ["資本效率｜增量ROIC", "本期不可靠", "資料不足", "LOW", "ΔNOPAT／Δ投入資本", "?", "基準分母變化為0", "不強行產生失真比率", "正式Q2投入資本變化"],
        ])
        return mapped

    def _outlook_rows(self) -> list[list[str]]:
        e = self.estimate
        rows = super()._outlook_rows()
        return [
            (["ROIC", f"估算約{_q(e.roic_base_pct,'0.1'):f}%（{_q(e.roic_low_pct,'0.1'):f}%–{_q(e.roic_high_pct,'0.1'):f}%）", "2026Q1 12.57%", "方向性改善", "歷史年化NOPAT／期末投入資本口徑；分母仍為估算", "正式Q2投入資本／Q3", "正式值維持高於Q1且現金回收", "正式分母使ROIC回落或低於Q1"] if row[0] == "ROIC" else row)
            for row in rows
        ]

    def _deep_explainers(self) -> list[dict[str, str]]:
        e = self.estimate
        rows = super()._deep_explainers()
        for item in rows:
            if item["acronym"] == "ROIC":
                item.update({
                    "formula": "既有口徑：單季營業利益×（1－年度稅率）×4÷期末投入資本",
                    "terms": "歷史序列使用年化單季NOPAT與期末投入資本，不使用平均投入資本。Q2期末投入資本未直接揭露，因此以Q1期末值為基準並用近五季實際區間做敏感度。",
                    "input": f"年化NOPAT約{_q(e.nopat_method_annual_100m,'0.1'):f}億元；投入資本基準{e.invested_capital_base_end_100m:f}億元",
                    "result": f"約{_q(e.roic_base_pct,'0.1'):f}%；敏感區間{_q(e.roic_low_pct,'0.1'):f}%–{_q(e.roic_high_pct,'0.1'):f}%",
                    "read": "估算中樞高於Q1 12.57%與近期歷史上緣14.41%，方向偏改善；但分母不確定，不能視為正式ROIC。",
                    "limit": "Q2投入資本未直接揭露；基準是假設期末資本與Q1持平，範圍使用近五季實際期末投入資本與稅率，不代表公司正式數字。",
                    "value": "資本效率可能改善，但正式升級仍須Q2資產負債表與後續現金回收共同確認。",
                })
        return rows

    def _estimated_roic_svg(self) -> str:
        labels = list(HISTORICAL_ROIC) + ["2026Q2估算"]
        values = list(HISTORICAL_ROIC.values()) + [self.estimate.roic_base_pct]
        width, height, left, top, plot_w, plot_h = 900, 390, 75, 45, 760, 260
        lo, hi = Decimal("6"), Decimal("20")
        x = lambda i: left + i * plot_w / (len(values) - 1)
        y = lambda v: top + float((hi - v) / (hi - lo)) * plot_h
        hist_points = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values[:-1]))
        grid = "".join(f'<line x1="{left}" y1="{y(Decimal(str(t))):.1f}" x2="{left+plot_w}" y2="{y(Decimal(str(t))):.1f}" stroke="#dce3ea"/><text x="{left-12}" y="{y(Decimal(str(t)))+4:.1f}" text-anchor="end" class="axis-label">{t}%</text>' for t in (8, 12, 16, 20))
        hist = "".join(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="5" fill="#245b8a"/><text x="{x(i):.1f}" y="{y(v)-10:.1f}" text-anchor="middle" class="point-label">{v:f}%</text>' for i, v in enumerate(values[:-1]))
        ix, iy = x(len(values)-1), y(values[-1])
        ry1, ry2 = y(self.estimate.roic_high_pct), y(self.estimate.roic_low_pct)
        axes = "".join(f'<text x="{x(i):.1f}" y="{top+plot_h+26}" text-anchor="middle" class="axis-label">{_escape(label)}</text>' for i, label in enumerate(labels))
        return f'''<svg class="actual-chart roic-estimate-chart" viewBox="0 0 {width} {height}" role="img" aria-label="歷史ROIC與2026Q2估算區間">{grid}<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="#617284"/><polyline points="{hist_points}" fill="none" stroke="#245b8a" stroke-width="3"/>{hist}<line x1="{x(len(values)-2):.1f}" y1="{y(values[-2]):.1f}" x2="{ix:.1f}" y2="{iy:.1f}" stroke="#bc8428" stroke-width="3" stroke-dasharray="8 6"/><line x1="{ix:.1f}" y1="{ry1:.1f}" x2="{ix:.1f}" y2="{ry2:.1f}" stroke="#bc8428" stroke-width="5"/><line x1="{ix-10:.1f}" y1="{ry1:.1f}" x2="{ix+10:.1f}" y2="{ry1:.1f}" stroke="#bc8428" stroke-width="3"/><line x1="{ix-10:.1f}" y1="{ry2:.1f}" x2="{ix+10:.1f}" y2="{ry2:.1f}" stroke="#bc8428" stroke-width="3"/><circle cx="{ix:.1f}" cy="{iy:.1f}" r="8" fill="#fff" stroke="#bc8428" stroke-width="4"/><text x="{ix-12:.1f}" y="{iy-14:.1f}" text-anchor="end" class="point-label" fill="#8b5b0d">估算{_q(values[-1],'0.1'):f}%</text>{axes}<text x="{left}" y="{height-12}" class="axis-label">藍色實心＝受治理歷史值；金色空心／虛線＝估算；直線＝敏感區間</text></svg>'''

    def _chart_html(self, chart_id: str, highlight: str) -> str:
        if chart_id != "capital_validation_status":
            return super()._chart_html(chart_id, highlight)
        e = self.estimate
        return (
            '<figure data-chart-id="capital_validation_status"><h3>歷史ROIC與FY2026 Q2估算</h3>'
            '<p class="question"><strong>問題：</strong>沿用歷史口徑後，Q2資本效率可能位於何處？</p>'
            + self._estimated_roic_svg()
            + f'<p class="highlight">2026Q2估算約{_q(e.roic_base_pct,"0.1"):f}%；敏感區間{_q(e.roic_low_pct,"0.1"):f}%–{_q(e.roic_high_pct,"0.1"):f}%</p>'
            '<p><strong>判讀：</strong>方向高於Q1與近期歷史上緣，但Q2期末投入資本未直接揭露，信心為LOW。</p>'
            '<p><strong>下一驗證：</strong>正式Q2資產負債表、Q3 ROIC與現金回收。</p></figure>'
        )

    def _appendix_a_markdown(self) -> str:
        e = self.estimate
        rows = [
            ["營運槓桿差", "判斷規模吸收", "67.51%－40.84%", "+26.67個百分點", "官方資料衍生", "HIGH"],
            ["費用代理值", "觀察毛利以下吸收", "154,533－94,803百萬元", "59,730百萬元", "官方資料衍生", "HIGH"],
            ["Q2 CFO", "檢查獲利轉現金", "H1 CFO－Q1 CFO", "-72,339.154百萬元", "官方資料衍生", "HIGH"],
            ["Q2 Capex", "衡量長期投入", "H1 Capex－Q1 Capex", "45,111.655百萬元", "官方資料衍生", "HIGH"],
            ["Q2 FCF", "衡量可自由運用現金", "CFO－Capex", "-117,450.809百萬元", "官方資料衍生", "HIGH"],
            ["Q2 NOPAT代理值", "ROIC分子／本業稅後獲利", "94,803×(1－24,810÷94,866)", f"{_q(e.nopat_effective_million,'0.001'):f}百萬元（約{_q(e.nopat_effective_million/100,'0.1'):f}億元）", "估算值", "MEDIUM"],
            ["估算ROIC", "資本效率趨勢", "年化同口徑NOPAT÷期末投入資本", f"中樞{_q(e.roic_base_pct,'0.01'):f}%；區間{_q(e.roic_low_pct,'0.1'):f}%–{_q(e.roic_high_pct,'0.1'):f}%", "估算值", "LOW"],
            ["Capital Productivity", "稅後獲利是否跑贏資本", "NOPAT成長－投入資本成長", f"基準+{_q(e.capital_productivity_base_pp,'0.1'):f}個百分點", "方向性推論", "LOW"],
            ["增量ROIC", "新增資本效率", "ΔNOPAT÷Δ投入資本", "本期不可靠（基準Δ投入資本＝0）", "資料不足", "LOW"],
            ["CCC", "營運資金週轉", "存貨天數＋應收天數－應付天數", "42天", "官方資料衍生", "HIGH"],
            ["ROE", "股東資本效率", "歸屬股東淨利÷平均股東權益", "2026H1 6.21%（官方）", "官方值", "HIGH"],
        ]
        table = self._md_table(["指標", "決策用途", "公式／原始輸入", "精確結果／Owner顯示", "數據性質", "信心"], rows)
        return "\n".join([
            "## Appendix A｜企業價值KPI計算與估算", "", table, "",
            "### NOPAT逐步計算", "",
            f"1. 有效稅率代理值＝24,810÷94,866＝**{_pct(e.effective_tax_pct, '0.0001')}**。",
            f"2. 單季NOPAT代理值＝94,803×（1－{_pct(e.effective_tax_pct, '0.0001')}）＝**{_q(e.nopat_effective_million,'0.001'):f}百萬元（約{_q(e.nopat_effective_million/100,'0.1'):f}億元）**。",
            f"3. 歷史口徑稅率由2026Q1表內數值反推：1－2,216÷（756×4）＝**{_pct(e.historical_tax_pct,'0.0001')}**。",
            f"4. 同口徑年化NOPAT＝948.03×4×（1－{_pct(e.historical_tax_pct,'0.0001')}）＝**{_q(e.nopat_method_annual_100m,'0.001'):f}億元**。",
            "限制：有效稅率使用公司整體所得稅費用作營運稅率代理；不是公司正式揭露的NOPAT。", "",
            "### ROIC方法與敏感度", "",
            "歷史正式方法為年化單季NOPAT÷期末投入資本；沒有使用平均投入資本。Q2期末投入資本未直接揭露，基準假設與Q1期末17,633億元持平；敏感度只使用2025Q1至2026Q1實際稅率與投入資本區間15,568–17,633億元。",
            self._md_table(["情境", "NOPAT假設", "投入資本假設", "ROIC", "理由"], [
                ["LOW", "近期最高稅率26.7376%", "近期最高17,633億元", _pct(e.roic_low_pct), "最保守的既有稅率與分母組合"],
                ["BASE", "2026Q1同口徑稅率26.7196%", "Q1期末17,633億元持平", _pct(e.roic_base_pct), "沿用最近一期口徑"],
                ["HIGH", "近期最低稅率26.7196%", "近期最低15,568億元", _pct(e.roic_high_pct), "既有歷史範圍內較低分母"],
            ]), "",
            f"**趨勢判讀：** 中樞較Q1 12.57%高約{_q(e.roic_base_pct-Decimal('12.57'),'0.1'):f}個百分點，且區間下緣仍高於近期歷史上緣14.41%；方向偏改善，但分母估算使信心僅LOW。",
            f"**Capital Productivity：** 同口徑NOPAT較Q1增加{_pct(e.nopat_growth_pct)}；在期末投入資本持平假設下，Spread約+{_q(e.capital_productivity_base_pp,'0.1'):f}個百分點，僅屬方向性推論。",
            "**增量ROIC：** 基準假設的Δ投入資本為0，分母不具經濟意義，因此顯示「本期不可靠」，不強行計算。", "",
        ])

    @staticmethod
    def _appendix_b_markdown() -> str:
        items = [
            ("NOPAT", "本業營業利益扣除營運稅負後的報酬，是ROIC分子；不等於歸母淨利。"),
            ("投入資本", "為營運而占用的債務與權益資本扣除現金；本報告沿用既有Debt＋Equity－Cash口徑。"),
            ("ROIC", "衡量每1元投入資本產生多少稅後營業報酬；估算高於歷史不等於正式改善。"),
            ("增量ROIC", "新增NOPAT除以新增投入資本；分母接近零或不可比時比率會失真，應拒絕計算。"),
            ("Capital Productivity", "NOPAT成長減投入資本成長；正值表示稅後獲利可能跑贏資本需求。"),
            ("CFO", "本業營運實際產生或使用的現金；可受營運資金時點大幅影響。"),
            ("FCF", "CFO扣除Capex後可用於還債、配息或再投資的資源。"),
            ("CCC", "存貨天數＋應收天數－應付天數，描述現金被營運流程占用的時間。"),
            ("ROE", "歸屬股東淨利除以平均股東權益；本期H1只與H1比較，不年化。"),
            ("BVPS", "每股對應的帳面股東權益；需與ROE及股利一起看股東複利。"),
            ("DuPont", "把ROE拆為淨利率、資產周轉與財務槓桿；缺完整組件時不能指定改善來源。"),
        ]
        return "## Appendix B｜財務方法白話解釋\n\n" + "\n".join(f"- **{name}：** {body}" for name, body in items) + "\n"

    def markdown(self) -> str:
        text = super().markdown()
        kpi = self._md_table(["KPI", "目前值", "數據性質", "信心", "比較基準", "趨勢", "偏差", "企業價值判讀", "下一驗證點"], self._estimated_kpi_rows())
        text = re.sub(r"## 企業價值KPI總表\n\n.*?\n\n## 本報告關鍵財務名詞", "## 企業價值KPI總表\n\n" + kpi + "\n\n## 本報告關鍵財務名詞", text, count=1, flags=re.S)
        e = self.estimate
        text = text.replace("- **最大資料缺口：** FY2026 Q2投入資本報酬率（ROIC）缺少標準化稅後營業利益（NOPAT）與同口徑平均投入資本，因此是資料不足，不是0%。", f"- **透明估算：** Q2單季NOPAT代理值約{_q(e.nopat_effective_million/100,'0.1'):f}億元；依既有年化NOPAT／期末投入資本口徑，ROIC估算約{_q(e.roic_base_pct,'0.1'):f}%（{_q(e.roic_low_pct,'0.1'):f}%–{_q(e.roic_high_pct,'0.1'):f}%）。分母屬估算，信心LOW。")
        text = re.sub(r"## 資本效率：ROIC\n\n.*?\n\n## 股東資本效率", f"## 資本效率：ROIC\n\n**Q2方向偏改善，但不是正式值。** 單季NOPAT代理值約{_q(e.nopat_effective_million/100,'0.1'):f}億元；沿用歷史年化單季NOPAT／期末投入資本口徑，ROIC中樞約{_q(e.roic_base_pct,'0.1'):f}%、敏感區間{_q(e.roic_low_pct,'0.1'):f}%–{_q(e.roic_high_pct,'0.1'):f}%。中樞高於Q1 12.57%，且高於近期歷史7.91%–14.41%；惟Q2期末投入資本未直接揭露，僅作企業價值趨勢判讀。\n\n## 股東資本效率", text, count=1, flags=re.S)
        text = text.replace("## Technical Evidence Appendix", self._appendix_a_markdown() + "\n" + self._appendix_b_markdown() + "\n## Appendix C｜Technical Evidence")
        text = text.replace("| Q2 FCF | " + self.exact["fcf"] + "百萬元 | DERIVED_FROM_OFFICIAL | CFO－Capex | 4,6 |", "| Q2 FCF | " + self.exact["fcf"] + "百萬元 | DERIVED_FROM_OFFICIAL | CFO－Capex | 4,6 |\n| Q2 NOPAT代理值 | " + f"{_q(e.nopat_effective_million,'0.001'):f}百萬元" + " | ESTIMATED_FROM_GOVERNED_INPUTS | 營業利益×（1－有效稅率代理） | 1,2 |\n| Q2 ROIC估算 | " + f"{_q(e.roic_base_pct,'0.01'):f}%" + " | ESTIMATED_FROM_GOVERNED_INPUTS | 歷史年化NOPAT／估算期末投入資本 | 2 |")
        return text

    def _appendix_html(self) -> str:
        e = self.estimate
        rows = [
            ["營運槓桿差", "判斷規模吸收", "67.51%－40.84%", "+26.67個百分點", "官方資料衍生", "HIGH"],
            ["費用代理值", "觀察毛利以下吸收", "154,533－94,803百萬元", "59,730百萬元", "官方資料衍生", "HIGH"],
            ["Q2 CFO", "檢查獲利轉現金", "H1 CFO－Q1 CFO", "-72,339.154百萬元", "官方資料衍生", "HIGH"],
            ["Q2 Capex", "衡量長期投入", "H1 Capex－Q1 Capex", "45,111.655百萬元", "官方資料衍生", "HIGH"],
            ["Q2 FCF", "衡量可自由運用現金", "CFO－Capex", "-117,450.809百萬元", "官方資料衍生", "HIGH"],
            ["Q2 NOPAT代理值", "ROIC分子／本業稅後獲利", "94,803×(1－24,810÷94,866)", f"{_q(e.nopat_effective_million,'0.001'):f}百萬元／約{_q(e.nopat_effective_million/100,'0.1'):f}億元", "估算值", "MEDIUM"],
            ["估算ROIC", "資本效率趨勢", "年化同口徑NOPAT÷期末投入資本", f"中樞{_q(e.roic_base_pct,'0.01'):f}%／區間{_q(e.roic_low_pct,'0.1'):f}%–{_q(e.roic_high_pct,'0.1'):f}%", "估算值", "LOW"],
            ["Capital Productivity", "稅後獲利是否跑贏資本", "NOPAT成長－投入資本成長", f"基準+{_q(e.capital_productivity_base_pp,'0.1'):f}個百分點", "方向性推論", "LOW"],
            ["增量ROIC", "新增資本效率", "ΔNOPAT÷Δ投入資本", "本期不可靠", "資料不足", "LOW"],
            ["CCC", "營運資金週轉", "存貨天數＋應收天數－應付天數", "42天", "官方資料衍生", "HIGH"],
            ["ROE", "股東資本效率", "歸屬股東淨利÷平均股東權益", "2026H1 6.21%", "官方值", "HIGH"],
        ]
        calc_table = self._html_table(["指標", "決策用途", "公式／輸入", "結果／Owner顯示", "數據性質", "信心"], rows, "appendix calculation-table")
        sensitivity = self._html_table(["情境", "NOPAT假設", "投入資本假設", "ROIC", "理由"], [
            ["LOW", "近期最高稅率26.7376%", "近期最高17,633億元", _pct(e.roic_low_pct), "最保守既有組合"],
            ["BASE", "2026Q1同口徑稅率26.7196%", "Q1期末17,633億元持平", _pct(e.roic_base_pct), "沿用最近一期口徑"],
            ["HIGH", "近期最低稅率26.7196%", "近期最低15,568億元", _pct(e.roic_high_pct), "既有歷史範圍內較低分母"],
        ], "appendix sensitivity-table")
        methods = "".join(f"<li><strong>{_escape(name)}：</strong>{_escape(body)}</li>" for name, body in [
            ("NOPAT", "本業稅後營業報酬，並非歸母淨利。"), ("投入資本", "債務＋權益－現金。"),
            ("ROIC", "年化單季NOPAT除以期末投入資本；本期為估算。"), ("增量ROIC", "ΔNOPAT除以Δ投入資本；分母不穩定時拒絕計算。"),
            ("Capital Productivity", "NOPAT成長減投入資本成長。"), ("CFO", "本業營運現金。"),
            ("FCF", "CFO扣除Capex。"), ("CCC", "存貨天數＋應收天數－應付天數。"),
            ("ROE", "歸屬股東淨利除以平均股東權益。"), ("BVPS", "每股帳面股東權益。"),
            ("DuPont", "淨利率、資產周轉及財務槓桿的ROE分解。"),
        ])
        return f'''<section class="page-break appendix-a"><h2>Appendix A｜企業價值KPI計算與估算</h2>{calc_table}
<h3>NOPAT逐步計算</h3><ol><li>有效稅率代理值＝24,810÷94,866＝<strong>{_pct(e.effective_tax_pct,'0.0001')}</strong>。</li><li>單季NOPAT代理值＝94,803×（1－{_pct(e.effective_tax_pct,'0.0001')}）＝<strong>{_q(e.nopat_effective_million,'0.001'):f}百萬元（約{_q(e.nopat_effective_million/100,'0.1'):f}億元）</strong>。</li><li>歷史口徑稅率＝1－2,216÷（756×4）＝<strong>{_pct(e.historical_tax_pct,'0.0001')}</strong>。</li><li>同口徑年化NOPAT＝948.03×4×（1－{_pct(e.historical_tax_pct,'0.0001')}）＝<strong>{_q(e.nopat_method_annual_100m,'0.001'):f}億元</strong>。</li></ol><p class="limit">有效稅率是公司整體所得稅費用代理營運稅率，不是公司正式NOPAT。</p>
<h3>ROIC方法與敏感度</h3><p>歷史方法為年化單季NOPAT÷期末投入資本，沒有使用平均投入資本。Q2期末投入資本未直接揭露；基準假設與Q1期末17,633億元持平，區間只採2025Q1至2026Q1實際稅率及投入資本15,568–17,633億元。</p>{sensitivity}<p><strong>趨勢：</strong>中樞較Q1高約{_q(e.roic_base_pct-Decimal('12.57'),'0.1'):f}個百分點；方向偏改善，但分母估算使信心僅LOW。</p><p><strong>Capital Productivity：</strong>基準約+{_q(e.capital_productivity_base_pp,'0.1'):f}個百分點，屬方向性推論。<strong>增量ROIC：</strong>基準Δ投入資本為0，拒絕產生失真比率。</p></section>
<section class="page-break appendix-b"><h2>Appendix B｜財務方法白話解釋</h2><ul>{methods}</ul></section>'''

    def html(self) -> bytes:
        text = super().html().decode("utf-8")
        e = self.estimate
        kpi = self._html_table(["KPI", "目前值", "數據性質", "信心", "比較基準", "趨勢", "偏差", "企業價值判讀", "下一驗證點"], self._estimated_kpi_rows(), "kpi-table")
        text = re.sub(r'<section><h2>企業價值KPI總表</h2>.*?</section>', f'<section><h2>企業價值KPI總表</h2>{kpi}</section>', text, count=1, flags=re.S)
        text = text.replace('<div class="gap"><strong>最大資料缺口</strong><p>Q2投入資本報酬率（ROIC）缺標準化稅後營業利益（NOPAT）與同口徑平均投入資本；是資料不足，不是0%。</p></div>', f'<div class="gap"><strong>透明估算</strong><p>Q2單季NOPAT代理值約{_q(e.nopat_effective_million/100,"0.1"):f}億元；沿用歷史口徑，ROIC估算約{_q(e.roic_base_pct,"0.1"):f}%（{_q(e.roic_low_pct,"0.1"):f}%–{_q(e.roic_high_pct,"0.1"):f}%）。分母屬估算，信心LOW。</p></div>')
        text = re.sub(r'<section><h2>資本效率：ROIC</h2>.*?</section>', f'<section><h2>資本效率：ROIC</h2><p><strong>Q2方向偏改善，但不是正式值。</strong> 單季NOPAT代理值約{_q(e.nopat_effective_million/100,"0.1"):f}億元；ROIC中樞約{_q(e.roic_base_pct,"0.1"):f}%、敏感區間{_q(e.roic_low_pct,"0.1"):f}%–{_q(e.roic_high_pct,"0.1"):f}%。中樞高於Q1 12.57%及近期歷史上緣14.41%，但Q2期末投入資本未直接揭露。</p>{self._chart_html("capital_validation_status", "")}</section>', text, count=1, flags=re.S)
        text = text.replace('<section class="technical"><h2>Technical Evidence Appendix</h2>', self._appendix_html() + '<section class="technical page-break"><h2>Appendix C｜Technical Evidence</h2>')
        fcf_row = f'<tr><td>Q2 FCF</td><td>{_escape(self.exact["fcf"])}百萬元</td><td>DERIVED_FROM_OFFICIAL</td><td>CFO－Capex</td><td>4,6</td></tr>'
        estimate_rows = fcf_row + f'<tr><td>Q2 NOPAT代理值</td><td>{_q(e.nopat_effective_million,"0.001"):f}百萬元</td><td>ESTIMATED_FROM_GOVERNED_INPUTS</td><td>營業利益×（1－有效稅率代理）</td><td>1,2</td></tr><tr><td>Q2 ROIC估算</td><td>{_q(e.roic_base_pct,"0.01"):f}%</td><td>ESTIMATED_FROM_GOVERNED_INPUTS</td><td>歷史年化NOPAT／估算期末投入資本</td><td>2</td></tr>'
        text = text.replace(fcf_row, estimate_rows)
        text = text.replace("</style>", ".calculation-ledger{font-size:.78rem;line-height:1.5;background:#f7f8fa;padding:12px;border:1px solid #d6dde5}.roic-estimate-chart{background:#fff}.appendix-a,.appendix-b{font-size:.85rem}</style>")
        return text.encode("utf-8")
