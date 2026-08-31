"""Owner-facing communication rendering for a frozen v1.4.1 research pack.

This module is deliberately presentation-only.  It consumes an already
validated Owner Review artifact set, verifies that the research pack bytes do
not move, and produces a more readable Markdown/HTML/PDF candidate without
writing to authority, runtime governance, or report-library state.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .report_contracts import ChartData
from .report_renderer_formal import FormalPreviewRenderer
from ..contract_loader import ContractLoader
from ..governance import GovernanceBoundary, GovernanceError
from ..phaseb1_common import PhaseB1BoundaryError, atomic_write


CONTRACT_VERSION = "1"
REQUIRED_INPUTS = (
    "validated_research_pack.json",
    "chart_data.json",
    "formula_cards.json",
    "strategy_scorecard.json",
    "report_candidate.md",
    "report_candidate.html",
    "report_candidate.pdf",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _escape(value: object) -> str:
    return html.escape(str(value))


class OwnerCommunicationRenderer:
    """Render the frozen FY2026 Q2 pack for an Owner decision audience."""

    def __init__(self, source_dir: Path) -> None:
        self.package_root = Path(__file__).resolve().parents[5]
        self.filesystem_governance = GovernanceBoundary(
            ContractLoader(self.package_root)
        )
        self.source_dir = source_dir.resolve()
        missing = [name for name in REQUIRED_INPUTS if not (self.source_dir / name).is_file()]
        if missing:
            raise ValueError(f"frozen v1.4.1 inputs missing: {missing}")
        self.pack_path = self.source_dir / "validated_research_pack.json"
        self.pack_sha = _sha(self.pack_path)
        self.pack = json.loads(self.pack_path.read_text(encoding="utf-8"))
        if self.pack.get("templateVersion") != "1.4.1" or self.pack.get("actionable") is not False:
            raise ValueError("source research pack is not governed v1.4.1 actionable=false")
        self.analytics = self.pack["enterpriseValueAnalytics"]
        self.valuation = self.pack["valuationScenarios"]
        self.charts = {
            item["chartId"]: ChartData.model_validate(item)
            for item in json.loads((self.source_dir / "chart_data.json").read_text(encoding="utf-8"))
        }
        self.formulas = {
            item["metric"]: item
            for item in json.loads((self.source_dir / "formula_cards.json").read_text(encoding="utf-8"))
        }

    def authorize_output_dir(self, output_dir: Path) -> Path:
        try:
            return self.filesystem_governance.authorize_write(
                "OWNER_COMMUNICATION", output_dir
            )
        except GovernanceError as exc:
            raise RuntimeError(f"Owner Communication output denied: {exc}") from exc

    def authorize_profile_cleanup(self, output_dir: Path, profile: Path) -> Path:
        try:
            return self.filesystem_governance.authorize_tree_delete(
                "OWNER_COMMUNICATION",
                profile,
                owned_parent=output_dir,
                expected_name=".edge-profile",
            )
        except GovernanceError as exc:
            raise RuntimeError(f"Owner Communication cleanup denied: {exc}") from exc

    @property
    def exact(self) -> dict[str, str]:
        a = self.analytics
        return {
            "revenue": a["revenueMillionTwd"],
            "gross_profit": a["grossProfitMillionTwd"],
            "operating_profit": a["operatingProfitMillionTwd"],
            "net_income": "59974",
            "cfo": a["q2StandaloneCfoMillionTwd"],
            "capex": a["q2StandaloneCapexMillionTwd"],
            "fcf": a["q2StandaloneFcfMillionTwd"],
        }

    @staticmethod
    def _glossary_rows() -> list[tuple[str, str]]:
        return [
            ("每股盈餘（EPS）", "公司平均每一股賺多少淨利。"),
            ("營業現金流（CFO）", "公司日常營運實際產生或使用多少現金。"),
            ("資本支出（Capex）", "公司為設備、產能與長期營運能力投入的資金。"),
            ("自由現金流（FCF）", "營業現金流扣除資本支出後可還債、配息或再投資的資源。"),
            ("稅後營業利益（NOPAT）", "排除融資結構干擾後，用來衡量本業稅後報酬的概念。"),
            ("投入資本報酬率（ROIC）", "每1元營運投入資本能創造多少稅後營業報酬。"),
            ("股東權益報酬率（ROE）", "每1元股東資本能創造多少歸屬股東淨利。"),
            ("每股淨值（BVPS）", "每一股背後對應的帳面股東權益。"),
            ("現金循環週期（CCC）", "投入現金至銷售回收現金所需的大致天數。"),
            ("本益比（P/E）", "市場為每1元每股盈餘支付多少價格。"),
            ("股價淨值比（P/B）", "市場為每1元每股淨值支付多少價格。"),
            ("毛利率（Gross Margin）", "營收扣除直接銷售成本後留下的比例。"),
            ("營業利益率（Operating Margin）", "營收扣除營業成本與費用後留下的營業利益比例。"),
            ("杜邦分析（DuPont）", "把ROE拆成利潤率、資產周轉與財務槓桿來追查來源。"),
        ]

    def _kpi_rows(self) -> list[list[str]]:
        return [
            ["成長品質｜營收成長", "+40.84%", "去年同期", "🟢 正向｜規模擴張", "營運槓桿尚待現金驗證", "規模擴張強", "FY2026 Q3營收"],
            ["獲利品質｜營業利益成長", "+67.51%", "營收+40.84%", "🟢 正向背離", "+26.67個百分點", "營運槓桿強化", "Q3營益率"],
            ["獲利品質｜毛利率", "6.12%", "年減21個基點", "🟡 觀察｜負向背離", "未隨規模改善", "產品組合品質未證實", "Q3毛利率"],
            ["獲利品質｜營益率", "3.75%", "2024Q2至今+87個基點", "🟢 正向", "毛利以下改善", "費用吸收增強", "Q3營益率"],
            ["費用效率｜費用代理值／營收", "2.365%", "八季約3.2%", "🟢 持續改善", "代理值非正式科目", "規模吸收具支持", "正式費用拆分"],
            ["現金轉化｜CCC", "42天", "48天→44天→42天", "🟢 持續改善", "資金占用仍增加", "週轉效率未惡化", "Q3應收／存貨／應付"],
            ["現金轉化｜CFO", "約-723億元", "Q2同口徑推導", "🔴 重大負向", "獲利與現金背離", "現金回收未完成", "Q3 CFO"],
            ["現金轉化｜FCF", "約-1,175億元", "CFO－Capex", "🔴 重大負向", "負CFO與Capex雙重壓力", "股利能力不上修", "Q3／全年FCF"],
            ["資本效率｜ROIC", "資料不足", "2026Q1 12.57%", "⚪ 證據缺口", "不是0%", "新增資本價值尚未可算", "標準化NOPAT與平均投入資本"],
            ["股東資本效率｜ROE", "6.21%", "2025H1 5.48%", "🟢 正向", "+0.73個百分點", "股東資本使用效率改善", "Q2 BVPS與完整杜邦分析"],
            ["策略價值｜AI", "營收獲支持", "專屬獲利／ROIC／FCF未證實", "🟡 混合訊號", "價值鏈不完整", "成長尚未完整轉為價值", "Q3 AI獲利與現金"],
            ["股利／退休安全", "尚未升級", "正常化FCF不足", "🟡 觀察", "現金證據不足", "核心論點存續但安全邊際不上修", "全年FCF與股利政策"],
        ]

    def _outlook_rows(self) -> list[list[str]]:
        return [
            ["營收成長", "+40.84%", "去年同期", "正向", "規模擴張", "Q3營收", "維持高成長且獲利跟進", "成長急降且庫存升高"],
            ["營業利益成長", "+67.51%", "營收+40.84%", "正向背離", "規模轉為獲利", "Q3營益率", "持續跑贏營收", "低於營收增速"],
            ["營運槓桿差", "+26.67個百分點", "營業利益－營收增速", "正向", "費用吸收改善", "Q3費用代理值", "維持正差", "轉負"],
            ["毛利率", "6.12%", "年減21個基點", "負向背離", "產品組合尚未改善", "Q3毛利率", "止跌或回升", "與營益率同步下降"],
            ["營益率", "3.75%", "長期+87個基點", "正向", "毛利以下效率改善", "Q3營益率", "維持或提高", "持續下滑"],
            ["費用代理值／營收", "2.365%", "八季約3.2%", "持續改善", "規模吸收", "正式費用科目", "維持低檔", "反轉上升"],
            ["CCC", "42天", "48天→44天→42天", "正向", "週轉加快", "Q3營運資金", "不惡化且CFO轉正", "天數反轉上升"],
            ["CFO", "約-723億元", "Q2推導", "重大負向", "現金回收未跟上獲利", "Q3 CFO", "單季轉正", "持續為負"],
            ["FCF", "約-1,175億元", "CFO－Capex", "重大負向", "自由資源不足", "Q3／全年FCF", "TTM轉正且非一次性", "全年仍為負"],
            ["ROIC", "資料不足", "2026Q1 12.57%", "證據缺口", "資本效率未知", "Q2／TTM ROIC", "資料完備且改善", "投入資本增速高於NOPAT"],
            ["ROE", "6.21%", "2025H1 5.48%", "正向", "股東資本效率改善", "全年ROE／BVPS", "可比基礎續升", "ROE下降或槓桿驅動"],
            ["AI價值轉化", "營收獲支持", "獲利方向部分支持", "混合訊號", "ROIC／FCF未證實", "Q3 AI拆分", "正式獲利與現金證據", "成長伴隨毛利、ROIC、FCF惡化"],
        ]

    def _deep_explainers(self) -> list[dict[str, str]]:
        return [
            {"title": "營運槓桿差", "acronym": "Operating Leverage Spread", "question": "規模成長是否轉成更快的營業利益？", "formula": "營業利益成長率－營收成長率", "terms": "營收是規模；營業利益是扣除營業成本與費用後的本業成果。", "input": "67.51%－40.84%", "result": "+26.67個百分點", "read": "新增營收正轉成較高比例的營業利益。", "limit": "可能由規模吸收、成本、費用、產品組合、定價或匯率共同造成，不能鎖定單一原因。", "value": "營運治理改善，但仍須由ROIC與FCF確認是否形成完整價值。"},
            {"title": "自由現金流", "acronym": "FCF", "question": "帳面獲利最後留下多少可自由運用的現金？", "formula": "FCF＝CFO－Capex", "terms": "營業現金流（CFO）是本業實際產生或使用的現金；資本支出（Capex）是維持或擴張長期產能的投入。", "input": "約-723億元－約451億元", "result": "約-1,175億元", "read": "每股盈餘（EPS）增加，但現金尚未跟上；帳面獲利未充分變成可分配資源。", "limit": "Q2為官方H1減Q1的同口徑推導，整數揭露有1百萬元四捨五入差。", "value": "負FCF使股利能力與退休現金流安全不能升級。"},
            {"title": "投入資本報酬率", "acronym": "ROIC", "question": "每1元營運投入資本創造多少稅後營業報酬？", "formula": "ROIC＝NOPAT÷平均投入資本", "terms": "稅後營業利益（NOPAT）概念上約等於營業利益×（1－正常化稅率）；平均投入資本須依統一治理口徑，以期初與期末真正投入營運且被綁住的資本計算。", "input": "Q2缺標準化NOPAT與同口徑平均投入資本", "result": "資料不足，不是0%", "read": "ROIC上升代表同樣資本創造更多營運報酬；下降代表新增資本回報可能不足。", "limit": "不發明投入資本公式，也不以單季年化冒充TTM；精確資金成本未受治理。", "value": "這是AI與擴產能否真正創造企業價值的最大資料缺口。"},
            {"title": "股東權益報酬率", "acronym": "ROE", "question": "每1元股東資本替股東創造多少淨利？", "formula": "歸屬股東淨利÷平均股東權益", "terms": "歸屬股東淨利是普通股股東可歸屬的獲利；平均股東權益是期初與期末股東資本的平均。", "input": "2025H1 5.48%→2026H1 6.21%", "result": "+0.73個百分點", "read": "可比H1股東資本使用效率改善。", "limit": "ROE也受利潤率、資產周轉與財務槓桿影響；缺完整杜邦分析，不能全歸因於營運。", "value": "為P/B提供方向性支持，但仍需ROIC、BVPS與FCF共同驗證。"},
            {"title": "現金循環週期", "acronym": "CCC", "question": "投入現金到銷售回收現金大約需要幾天？", "formula": "存貨天數＋應收天數－應付天數", "terms": "天數越低通常表示營運資金回收越快。", "input": "48天→44天→42天", "result": "持續改善", "read": "應收與存貨金額增加，但週轉效率反而改善。", "limit": "較低CCC不代表現金已回收完成，仍須看CFO。", "value": "目前較支持成長驅動的資金吸收，而非已證實的週轉效率惡化。"},
            {"title": "股價淨值比與ROE", "acronym": "P/B × ROE", "question": "市場為每1元股東淨值支付的價格是否有基本面支持？", "formula": "P/B＝股價÷每股淨值（BVPS）", "terms": "BVPS是每股背後的帳面股東權益；ROE是這些權益創造淨利的效率。", "input": "263元÷127.12元", "result": "2.069倍", "read": "P/B不能單獨判斷，必須連結ROE、ROIC與FCF。", "limit": "沒有Owner核准估值門檻，不判定便宜或昂貴。", "value": "市場定價只是結果，企業價值證據才是因果層；本報告不產生目標價。"},
        ]

    @staticmethod
    def _references() -> list[str]:
        return [
            "鴻海精密工業股份有限公司，《FY2026 Q2 Results》，2026年8月12日，官方投資人關係資料。",
            "P1008 Governed Financial Authority，2317_master_v9.csv，財務資料截至FY2026 Q2。",
            "臺灣證券交易所，2317正式每日價格資料，截至2026年8月11日。",
            "P1008 Cash Flow Authority，FY2026 Q1，官方季報驗證。",
            "臺灣證券交易所，2317正式每日市場活動資料，截至2026年8月11日。",
            "P1008依官方FY2026 H1及Q1現金流資料推導：Q2 CFO＝H1 CFO－Q1 CFO；FCF＝CFO－Capex。",
        ]

    @staticmethod
    def _md_table(headers: list[str], rows: list[list[str]]) -> str:
        return "\n".join([
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(row) + " |" for row in rows),
        ])

    @staticmethod
    def _html_table(headers: list[str], rows: list[list[str]], css: str = "") -> str:
        return (
            f'<table class="{css}"><thead><tr>'
            + "".join(f"<th>{_escape(value)}</th>" for value in headers)
            + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(f"<td>{_escape(value)}</td>" for value in row) + "</tr>" for row in rows)
            + "</tbody></table>"
        )

    def _chart_html(self, chart_id: str, highlight: str) -> str:
        chart = self.charts[chart_id]
        if chart_id == "working_capital_3period":
            visual = FormalPreviewRenderer._line_svg(chart, 3)
        elif chart_id == "roe_equity_compounding":
            visual = FormalPreviewRenderer._line_svg(chart, 1)
        elif chart_id == "operating_leverage_spread":
            visual = FormalPreviewRenderer._bar_svg(chart)
        elif chart.visualization_type == "QUANTITATIVE_CHART":
            visual = FormalPreviewRenderer._line_svg(chart)
        else:
            visual = FormalPreviewRenderer._table(chart)
        return (
            f'<figure data-chart-id="{_escape(chart_id)}"><h3>{_escape(chart.title_zh)}</h3>'
            f'<p class="question"><strong>問題：</strong>{_escape(chart.decision_question)}</p>'
            f'{visual}<p class="highlight">{_escape(highlight)}</p>'
            f'<p><strong>判讀：</strong>{_escape(chart.enterprise_value_implication_zh)}</p>'
            f'<p><strong>下一驗證：</strong>{_escape(chart.next_checkpoint_zh)}</p></figure>'
        )

    def markdown(self) -> str:
        e = self.exact
        glossary = self._md_table(["名詞", "白話解釋"], [list(row) for row in self._glossary_rows()])
        kpis = self._md_table(["KPI", "目前值", "比較基準", "趨勢", "偏差", "企業價值判讀", "下一驗證點"], self._kpi_rows())
        outlook = self._md_table(["KPI", "目前", "基準", "偏差", "意義", "下一驗證", "改善條件", "惡化條件"], self._outlook_rows())
        explainers = []
        for item in self._deep_explainers():
            explainers.extend([
                f"### {item['title']}（{item['acronym']}）",
                f"**它回答什麼問題？** {item['question']}",
                f"**主公式：** {item['formula']}",
                f"**名詞：** {item['terms']}",
                f"**本期代入：** {item['input']}",
                f"**本期結果：** {item['result']}",
                f"**怎麼判讀？** {item['read']}",
                f"**限制：** {item['limit']}",
                f"**企業價值意義：** {item['value']}", "",
            ])
        refs = "\n".join(f"{index}. {value}" for index, value in enumerate(self._references(), 1))
        appendix_rows = [
            ["營收", e["revenue"] + "百萬元", "OFFICIAL", "FY2026 Q2", "1,2"],
            ["毛利", e["gross_profit"] + "百萬元", "OFFICIAL", "FY2026 Q2", "1,2"],
            ["營業利益", e["operating_profit"] + "百萬元", "OFFICIAL", "FY2026 Q2", "1,2"],
            ["歸母淨利", e["net_income"] + "百萬元", "OFFICIAL", "FY2026 Q2", "1,2"],
            ["Q2 CFO", e["cfo"] + "百萬元", "DERIVED_FROM_OFFICIAL", "H1－Q1", "4,6"],
            ["Q2 Capex", e["capex"] + "百萬元", "DERIVED_FROM_OFFICIAL", "H1－Q1", "4,6"],
            ["Q2 FCF", e["fcf"] + "百萬元", "DERIVED_FROM_OFFICIAL", "CFO－Capex", "4,6"],
        ]
        appendix = self._md_table(["項目", "精確值", "來源類別", "期間／公式", "參考資料"], appendix_rows)
        return "\n".join([
            "# 鴻海FY2026 Q2：成長已轉為營業利益，現金與資本效率仍待證明", "",
            "**Owner Communication & Editorial Contract v1｜Template 1.4.1｜待Owner審閱｜未授權發布**", "",
            "## 執行摘要", "",
            "- **本季真正證明：** 營收年增40.84%，營業利益年增67.51%，營業利益比營收快26.67個百分點，規模開始轉為更快的本業獲利。¹",
            "- **最大負偏差：** 營業現金流（CFO）約-723億元、資本支出（Capex）約451億元，自由現金流（FCF）約-1,175億元；帳面獲利尚未充分轉成現金。⁶",
            "- **最大資料缺口：** FY2026 Q2投入資本報酬率（ROIC）缺少標準化稅後營業利益（NOPAT）與同口徑平均投入資本，因此是資料不足，不是0%。",
            "- **P1008判定：** 核心持有論點維持；估值安全性未改善；安全邊際不上修；退休現金流安全尚未證實提升。", "",
            "## 本季企業價值變化", "",
            f"Q2營收約2.53兆元、毛利約1,545億元、營業利益約948億元、歸屬母公司淨利約600億元，每股盈餘（EPS）為4.27元。¹ 營業利益跑贏營收，但毛利率（Gross Margin）6.12%年減21個基點，營業利益率（Operating Margin）反而升至3.75%；改善主要出現在毛利以下，而非毛利率擴張。",
            "現金循環週期（CCC）由48天降至44天再降至42天，應收、存貨與應付金額卻隨規模上升。這較支持成長型營運資金吸收，而非已證實的週轉效率惡化；但負CFO表示現金回收仍未完成。", "",
            "## 企業價值KPI總表", "", kpis, "",
            "## 本報告關鍵財務名詞", "", glossary, "",
            "## 成長品質與營運槓桿", "",
            "**關鍵差異：營業利益指數173，明顯跑贏營收136與毛利135。** 規模已開始轉為營業利益，但不能單獨斷言是產品組合、成本、費用、定價或匯率中的哪一項造成。", "",
            "## 利潤率與獲利品質", "",
            "**毛利率未擴張，營益率卻改善。** 毛利率6.12%，營益率3.75%；現有證據顯示改善主要發生在毛利以下的費用吸收。", "",
            "## 現金轉化與營運資金", "",
            "**資金占用增加，但週轉效率反而改善。** 應收指數147.3、存貨146.4、應付152.2；CCC由48天降至42天。負CFO與FCF仍是本季最大負偏差。", "",
            "## 資本效率：ROIC", "",
            "**Q2證據缺口，不是0%。** 沒有治理合格的標準化NOPAT與平均投入資本，不能計算Q2 ROIC，也不能把單季數字年化。", "",
            "## 股東資本效率：ROE／BVPS", "",
            "股東權益報酬率（ROE）由2025H1的5.48%升至2026H1的6.21%，增加0.73個百分點。每股淨值（BVPS）由2024Q3的115.16元至2026Q1的127.12元中期淨增加，但2025Q2曾降至105.14元，**明顯下降，原因待驗證**。完整股東複利仍須合併BVPS變化與已分配股利。", "",
            "## 六個企業價值公式解釋", "", *explainers,
            "## AI與3+3價值轉化", "",
            "AI營收獲官方證據支持，公司整體營業利益改善方向提供部分支持；但AI專屬營業利益、ROIC與FCF均未證實。3+3六項支柱已核對，並不代表六項都已完成財務價值轉化。", "",
            "## 市場定價與基本面支持", "",
            "財報公布前收盤價263元（2026-08-11）、過去十二個月每股盈餘15.21元、財報前本益比（P/E）17.29倍；以最新直接揭露2026Q1 BVPS 127.12元計算的股價淨值比（P/B）為2.069倍。³ 這些只描述財報前市場定價；是否獲基本面支持，取決於ROE、ROIC與FCF能否共同改善。本報告不提供目標價或買賣價。", "",
            "## 企業價值趨勢與未來1–4季觀察", "",
            "### 營運端正在強化什麼？", "營業利益成長顯著快於營收，費用代理值占營收下降，營運槓桿改善。", "",
            "### 目前最大的負偏差是什麼？", "CFO與FCF為負，帳面獲利尚未充分轉為現金。", "",
            "### 最大的資料缺口是什麼？", "Q2 ROIC及增量ROIC不可算，無法驗證新增資本是否創造足夠報酬。", "",
            "### AI下一階段真正要驗證什麼？", "不是只看出貨與營收，而是AI專屬獲利、資本效率與現金轉化。", "",
            "### 什麼條件會讓P1008判斷升級／降級？", "升級需要毛利與營益率耐久、CFO／FCF轉正、ROIC可算且改善；若AI成長伴隨利潤率、ROIC或FCF惡化，判斷降級。", "", outlook, "",
            "## 最終投資判讀", "",
            "1. **最重要的正向證據：** 營業利益跑贏營收，營運治理改善。",
            "2. **最大負偏差：** CFO與FCF雙負，現金回收未完成。",
            "3. **最大證據缺口：** Q2 ROIC與AI專屬資本效率不可驗。",
            "4. **未來最重要的驗證：** Q3利潤率耐久、營運資金回收、TTM ROIC及全年FCF。",
            "5. **P1008最終判定：** 核心持有論點維持；估值安全性未改善；安全邊際不上修；退休現金流安全尚未證實提升；股利能力不因負FCF而上修。", "",
            "## 參考資料", "", refs, "",
            "## Technical Evidence Appendix", "",
            f"**Research Pack SHA-256：** `{self.pack_sha}`", "", appendix, "",
            "**Evidence IDs：** " + ", ".join(self.pack["sourceEvidenceIds"]), "",
            "**來源雜湊與定位：** 本附件以Research Pack SHA綁定全部研究語意；個別來源定位、文件雜湊與原始證據鏈保留於既有受治理evidence manifest及receipt。", "",
            "本報告為研究候選，不具交易可執行性；actionable=false；publication=false；OWNER_REVIEW_REQUIRED=true。", "",
        ]).replace("\r\n", "\n")

    def html(self) -> bytes:
        markdown = self.markdown()
        glossary = self._html_table(["名詞", "白話解釋"], [list(row) for row in self._glossary_rows()], "glossary")
        kpis = self._html_table(["KPI", "目前值", "比較基準", "趨勢", "偏差", "企業價值判讀", "下一驗證點"], self._kpi_rows(), "kpi-table")
        outlook = self._html_table(["KPI", "目前", "基準", "偏差", "意義", "下一驗證", "改善條件", "惡化條件"], self._outlook_rows(), "outlook-table")
        explainers = "".join(
            '<article class="explainer">'
            f'<h3>{_escape(item["title"])}（{_escape(item["acronym"])}）</h3>'
            f'<p><strong>問題：</strong>{_escape(item["question"])}</p>'
            f'<p class="formula">{_escape(item["formula"])}</p>'
            f'<p><strong>名詞：</strong>{_escape(item["terms"])}</p>'
            f'<p><strong>本期代入：</strong>{_escape(item["input"])}　<strong>結果：</strong>{_escape(item["result"])}</p>'
            f'<p><strong>判讀：</strong>{_escape(item["read"])}</p>'
            f'<p class="limit"><strong>限制：</strong>{_escape(item["limit"])}</p>'
            f'<p><strong>企業價值：</strong>{_escape(item["value"])}</p></article>'
            for item in self._deep_explainers()
        )
        refs = "".join(f"<li>{_escape(value)}</li>" for value in self._references())
        appendix_rows = [
            ["營收", self.exact["revenue"] + "百萬元", "OFFICIAL", "FY2026 Q2", "1,2"],
            ["毛利", self.exact["gross_profit"] + "百萬元", "OFFICIAL", "FY2026 Q2", "1,2"],
            ["營業利益", self.exact["operating_profit"] + "百萬元", "OFFICIAL", "FY2026 Q2", "1,2"],
            ["歸母淨利", self.exact["net_income"] + "百萬元", "OFFICIAL", "FY2026 Q2", "1,2"],
            ["Q2 CFO", self.exact["cfo"] + "百萬元", "DERIVED_FROM_OFFICIAL", "H1－Q1", "4,6"],
            ["Q2 Capex", self.exact["capex"] + "百萬元", "DERIVED_FROM_OFFICIAL", "H1－Q1", "4,6"],
            ["Q2 FCF", self.exact["fcf"] + "百萬元", "DERIVED_FROM_OFFICIAL", "CFO－Capex", "4,6"],
        ]
        appendix = self._html_table(["項目", "精確值", "來源類別", "期間／公式", "參考"], appendix_rows, "appendix")
        chart_blocks = {
            "growth": self._chart_html("growth_quality_divergence", "營業利益明顯跑贏營收與毛利"),
            "margin": self._chart_html("margin_divergence_8q", "毛利率未擴張，營益率卻改善；目前改善主要發生在毛利以下"),
            "opex": self._chart_html("operating_cost_absorption_8q", "費用代理值占營收比重呈多季下降"),
            "wc": self._chart_html("working_capital_3period", "資金占用增加，但週轉效率反而改善；CCC 48天→44天→42天"),
            "roic": self._chart_html("capital_validation_status", "Q2證據缺口，不是0%"),
            "bvps": self._chart_html("roe_equity_compounding", "2025Q2降至105.14元：明顯下降，原因待驗證"),
        }
        style = """
@page{size:A4;margin:15mm 14mm 15mm}*{box-sizing:border-box}body{font-family:"Noto Sans TC","Microsoft JhengHei",sans-serif;color:#172433;line-height:1.6;max-width:1120px;margin:0 auto;padding:24px;background:#f3f1eb}main{background:#fff;padding:34px 42px}h1{font-family:"Noto Serif TC","PMingLiU",serif;font-size:2.25rem;line-height:1.25;color:#132b45;border-top:8px solid #132b45;padding-top:20px}h2{color:#173b62;border-left:5px solid #bc8428;padding-left:12px;margin-top:36px}h3{color:#22527f}.meta{color:#6b7785}.status{display:inline-block;padding:7px 12px;background:#fff1cc;border:1px solid #c6922d}.summary{display:grid;grid-template-columns:1fr 1fr;gap:12px}.summary>div{padding:14px;border-top:4px solid #245b8a;background:#f4f7fa}.negative{border-top-color:#a85b42!important}.gap{border-top-color:#8a7a45!important}.decision{border-top-color:#23395d!important}.metric-strip{display:flex;gap:10px;flex-wrap:wrap}.metric{flex:1;min-width:145px;padding:12px;background:#f4f7fa;border-bottom:3px solid #245b8a}.metric strong{display:block;font-size:1.35rem;color:#183a5e}table{width:100%;border-collapse:collapse;font-size:.78rem;margin:14px 0 22px}th,td{border:1px solid #ccd5df;padding:7px;vertical-align:top}th{background:#eaf0f6;color:#173b62}.kpi-table td:nth-child(4),.outlook-table td:nth-child(4){font-weight:700}.explainer{break-inside:avoid;border-left:5px solid #245b8a;background:#f5f8fb;padding:12px 16px;margin:14px 0}.formula{font-size:1.15rem;font-weight:800;color:#173b62}.limit{color:#665a48}.question{color:#4d5c6c}.highlight{font-size:1.05rem;font-weight:800;color:#8b5b0d;background:#fff1cc;border-left:5px solid #bc8428;padding:10px 12px}figure{break-inside:avoid;margin:20px 0;padding:16px;border:1px solid #d6dde5;background:#fff}.actual-chart{width:100%;height:auto}.axis-label,.legend-label,.point-label,.bar-value,.spread-label,.spread-value{font-family:"Microsoft JhengHei",sans-serif;fill:#25384d}.axis-label,.legend-label{font-size:12px}.point-label,.bar-value{font-size:13px;font-weight:700}.spread-label{font-size:16px}.spread-value{font-size:22px;font-weight:800;fill:#9b6b15}.final-judgment{padding:18px;background:#f7f2e6;border:2px solid #bc8428}.technical{font-size:.8rem;color:#465464}.page-break{break-before:page}.references li{margin:7px 0}.footer{border-top:1px solid #ccd5df;margin-top:28px;padding-top:10px;color:#667481;font-size:.78rem}@media(max-width:760px){main{padding:18px}.summary{grid-template-columns:1fr}table{display:block;overflow-x:auto;font-size:.7rem}}@media print{body{background:#fff;padding:0}main{padding:0}h2{break-after:avoid}figure,.explainer{break-inside:avoid}}
"""
        return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>鴻海FY2026 Q2企業價值Owner Communication</title><style>{style}</style></head><body><main>
<header><h1>鴻海FY2026 Q2：成長已轉為營業利益，現金與資本效率仍待證明</h1><p class="meta">Owner Communication &amp; Editorial Contract v1｜Template 1.4.1</p><p class="status">待Owner審閱｜未授權發布</p></header>
<section><h2>執行摘要</h2><div class="summary"><div><strong>本季真正證明</strong><p>營收年增40.84%，營業利益年增67.51%，比營收快26.67個百分點；規模開始轉為更快的本業獲利。<sup>1</sup></p></div><div class="negative"><strong>最大負偏差</strong><p>營業現金流（CFO）約-723億元，自由現金流（FCF）約-1,175億元；帳面獲利未充分轉為現金。<sup>6</sup></p></div><div class="gap"><strong>最大資料缺口</strong><p>Q2投入資本報酬率（ROIC）缺標準化稅後營業利益（NOPAT）與同口徑平均投入資本；是資料不足，不是0%。</p></div><div class="decision"><strong>P1008判定</strong><p>核心持有論點維持；估值安全性未改善；安全邊際不上修；退休現金流安全尚未證實提升。</p></div></div></section>
<section><h2>本季企業價值變化</h2><div class="metric-strip"><div class="metric"><span>營收</span><strong>約2.53兆元</strong></div><div class="metric"><span>毛利</span><strong>約1,545億元</strong></div><div class="metric"><span>營業利益</span><strong>約948億元</strong></div><div class="metric"><span>歸母淨利</span><strong>約600億元</strong></div></div><p>每股盈餘（EPS）為4.27元。毛利率（Gross Margin）6.12%年減21個基點，營業利益率（Operating Margin）卻升至3.75%；改善主要出現在毛利以下。<sup>1</sup></p></section>
<section><h2>企業價值KPI總表</h2>{kpis}</section>
<section><h2>本報告關鍵財務名詞</h2>{glossary}</section>
<section><h2>成長品質與營運槓桿</h2><p><strong>營業利益指數173，明顯跑贏營收136與毛利135。</strong>規模已開始轉為營業利益，但不能鎖定單一驅動原因。</p>{chart_blocks['growth']}{chart_blocks['opex']}</section>
<section><h2>利潤率與獲利品質</h2><p><strong>毛利率未擴張，營益率卻改善。</strong>現有證據顯示改善主要發生在毛利以下的費用吸收。</p>{chart_blocks['margin']}</section>
<section><h2>現金轉化與營運資金</h2><p><strong>資金占用增加，但週轉效率反而改善。</strong>應收指數147.3、存貨146.4、應付152.2；現金循環週期（CCC）由48天降至42天。負CFO與FCF仍是最大負偏差。</p>{chart_blocks['wc']}</section>
<section><h2>資本效率：ROIC</h2><p><strong>Q2證據缺口，不是0%。</strong>缺治理合格的標準化NOPAT與平均投入資本，不能計算Q2 ROIC。</p>{chart_blocks['roic']}</section>
<section><h2>股東資本效率：ROE／BVPS</h2><p>股東權益報酬率（ROE）由2025H1的5.48%升至2026H1的6.21%。每股淨值（BVPS）中期淨增加，但2025Q2曾降至105.14元，<strong>明顯下降，原因待驗證</strong>。完整股東複利仍須合併BVPS與已分配股利。</p>{chart_blocks['bvps']}</section>
<section class="page-break"><h2>六個企業價值公式解釋</h2>{explainers}</section>
<section><h2>AI與3+3價值轉化</h2><p>AI營收獲官方證據支持，公司整體營業利益改善方向提供部分支持；AI專屬營業利益、ROIC與FCF仍未證實。3+3六項支柱已核對，不代表六項都已完成財務價值轉化。</p></section>
<section><h2>市場定價與基本面支持</h2><p>財報公布前收盤價263元（2026-08-11）、過去十二個月每股盈餘15.21元、財報前本益比（P/E）17.29倍；以最新直接揭露2026Q1 BVPS 127.12元計算的股價淨值比（P/B）為2.069倍。<sup>3</sup> 這些是財報前市場定價的次要脈絡；企業價值的因果層仍是ROE、ROIC與FCF。本報告不提供目標價或買賣價。</p></section>
<section><h2>企業價值趨勢與未來1–4季觀察</h2><h3>營運端正在強化什麼？</h3><p>營業利益成長快於營收，費用代理值占營收下降。</p><h3>目前最大的負偏差是什麼？</h3><p>CFO與FCF為負，帳面獲利未充分轉為現金。</p><h3>最大的資料缺口是什麼？</h3><p>Q2 ROIC與增量ROIC不可算，新增資本報酬未獲驗證。</p><h3>AI下一階段真正要驗證什麼？</h3><p>AI專屬獲利、資本效率與現金轉化，而不只是出貨與營收。</p><h3>什麼條件會讓P1008判斷升級／降級？</h3><p>升級需利潤率耐久、CFO／FCF轉正及ROIC可算且改善；AI成長若伴隨利潤率、ROIC或FCF惡化則降級。</p>{outlook}</section>
<section class="final-judgment"><h2>最終投資判讀</h2><ol><li><strong>最重要正向證據：</strong>營業利益跑贏營收，營運治理改善。</li><li><strong>最大負偏差：</strong>CFO與FCF雙負，現金回收未完成。</li><li><strong>最大證據缺口：</strong>Q2 ROIC與AI專屬資本效率不可驗。</li><li><strong>最重要驗證：</strong>Q3利潤率耐久、營運資金回收、TTM ROIC及全年FCF。</li><li><strong>P1008判定：</strong>核心持有論點維持；估值安全性未改善；安全邊際不上修；退休現金流安全尚未證實提升；股利能力不因負FCF而上修。</li></ol></section>
<section class="references page-break"><h2>參考資料</h2><ol>{refs}</ol></section>
<section class="technical"><h2>Technical Evidence Appendix</h2><p><strong>Research Pack SHA-256：</strong><code>{self.pack_sha}</code></p>{appendix}<p><strong>Evidence IDs：</strong>{_escape(', '.join(self.pack['sourceEvidenceIds']))}</p><p>本附件以Research Pack SHA綁定全部研究語意；個別來源定位、文件雜湊與原始證據鏈保留於既有受治理evidence manifest及receipt。</p></section>
<footer class="footer">研究候選｜actionable=false｜publication=false｜OWNER_REVIEW_REQUIRED=true</footer>
</main></body></html>""".encode("utf-8")

    @staticmethod
    def _edge_executable() -> Path:
        candidates = [
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        located = shutil.which("msedge")
        if located:
            return Path(located)
        raise RuntimeError("Microsoft Edge is unavailable for local PDF export")

    def write(self, output_dir: Path) -> dict[str, Any]:
        output_dir = self.authorize_output_dir(output_dir)
        output_dir.mkdir(parents=True, exist_ok=False)
        pre_sha = self.pack_sha
        markdown_path = output_dir / "report_candidate.md"
        html_path = output_dir / "report_candidate.html"
        pdf_path = output_dir / "report_candidate.pdf"
        atomic_write(
            markdown_path,
            self.markdown().encode("utf-8"),
            capability="OWNER_COMMUNICATION",
        )
        atomic_write(
            html_path, self.html(), capability="OWNER_COMMUNICATION"
        )
        for name in ("validated_research_pack.json", "chart_data.json", "formula_cards.json", "strategy_scorecard.json"):
            destination = self.filesystem_governance.authorize_write(
                "OWNER_COMMUNICATION", output_dir / name
            )
            shutil.copyfile(self.source_dir / name, destination)
        post_sha = _sha(output_dir / "validated_research_pack.json")
        if post_sha != pre_sha or (output_dir / "validated_research_pack.json").read_bytes() != self.pack_path.read_bytes():
            raise RuntimeError("research pack drifted during Owner Communication rendering")
        edge = self._edge_executable()
        profile = self.filesystem_governance.authorize_write(
            "OWNER_COMMUNICATION", output_dir / ".edge-profile"
        )
        pdf_path = self.filesystem_governance.authorize_write(
            "OWNER_COMMUNICATION", pdf_path
        )
        command = [
            str(edge), "--headless", "--disable-gpu", "--no-pdf-header-footer",
            f"--user-data-dir={profile}", f"--print-to-pdf={pdf_path}", html_path.as_uri(),
        ]
        completed = subprocess.run(command, cwd=output_dir, capture_output=True, text=False, timeout=90)
        if completed.returncode != 0 or not pdf_path.is_file() or pdf_path.stat().st_size == 0:
            diagnostic = (completed.stderr or completed.stdout or b"").decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"PDF export failed: {diagnostic}")
        disposable_profile = self.authorize_profile_cleanup(output_dir, profile)
        shutil.rmtree(disposable_profile, ignore_errors=False)
        review = {
            "recordType": "P1008_OWNER_COMMUNICATION_REVIEW",
            "contractVersion": CONTRACT_VERSION,
            "templateVersion": "1.4.1",
            "status": "OWNER_REVIEW_REQUIRED",
            "presentationOnly": True,
            "researchPackPreSha256": pre_sha,
            "researchPackPostSha256": post_sha,
            "researchPackIdentical": True,
            "deepFormulaExplainerCount": len(self._deep_explainers()),
            "enterpriseValueKpiCount": len(self._kpi_rows()),
            "chartHighlightCount": 6,
            "openaiCalls": 0,
            "anysearchCalls": 0,
            "publication": False,
            "ownerReviewRequired": True,
            "actionable": False,
        }
        review_path = output_dir / "owner_communication_review.json"
        try:
            atomic_write(
                review_path,
                (json.dumps(review, ensure_ascii=False, indent=2) + "\n").encode(
                    "utf-8"
                ),
                capability="OWNER_COMMUNICATION",
            )
        except PhaseB1BoundaryError as exc:
            raise RuntimeError(f"Owner Communication review denied: {exc}") from exc
        return {
            "markdown": str(markdown_path), "html": str(html_path), "pdf": str(pdf_path),
            "review": str(review_path), "research_pack_sha256": post_sha,
        }
