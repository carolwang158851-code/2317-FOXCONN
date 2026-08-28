from __future__ import annotations

import hashlib
import os
import unittest
from pathlib import Path

from p1008_research_plugin.reporting.owner_communication_renderer import (
    OwnerCommunicationRenderer,
)


class OwnerCommunicationContractV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = os.environ.get("P1008_V141_FINAL_ARTIFACT_ROOT")
        if not source:
            raise unittest.SkipTest("frozen v1.4.1 FINAL artifact root is not configured")
        cls.source = Path(source).resolve()
        cls.renderer = OwnerCommunicationRenderer(cls.source)
        cls.markdown = cls.renderer.markdown()
        cls.html = cls.renderer.html().decode("utf-8")
        cls.combined = cls.markdown + cls.html

    def test_research_pack_is_frozen_and_governed(self) -> None:
        actual = hashlib.sha256((self.source / "validated_research_pack.json").read_bytes()).hexdigest().upper()
        self.assertEqual(actual, "80E7FD111ECEA751BCC1DC614A04BC6CADB70C42F87B4D416C3C4BC42FAE001D")
        self.assertEqual(self.renderer.pack["templateVersion"], "1.4.1")
        self.assertIs(self.renderer.pack["actionable"], False)

    def test_human_units_and_exact_appendix_are_both_present(self) -> None:
        for text in ("約2.53兆元", "約1,545億元", "約948億元", "約-723億元", "約-1,175億元"):
            self.assertIn(text, self.combined)
        appendix = self.markdown.split("## Technical Evidence Appendix", 1)[1]
        for exact in ("2525894百萬元", "154533百萬元", "94803百萬元", "-72339.154百萬元", "-117450.809百萬元"):
            self.assertIn(exact, appendix)
        main = self.markdown.split("## Technical Evidence Appendix", 1)[0]
        self.assertNotIn("154533百萬元", main)

    def test_glossary_and_first_use_expansion_cover_major_terms(self) -> None:
        self.assertIn("## 本報告關鍵財務名詞", self.markdown)
        self.assertEqual(len(self.renderer._glossary_rows()), 14)
        for term in ("每股盈餘（EPS）", "營業現金流（CFO）", "資本支出（Capex）", "自由現金流（FCF）", "稅後營業利益（NOPAT）", "投入資本報酬率（ROIC）", "股東權益報酬率（ROE）", "每股淨值（BVPS）", "現金循環週期（CCC）", "本益比（P/E）", "股價淨值比（P/B）", "毛利率（Gross Margin）", "營業利益率（Operating Margin）"):
            self.assertIn(term, self.combined)

    def test_six_deep_explainers_preserve_formula_limits(self) -> None:
        explainers = self.renderer._deep_explainers()
        self.assertEqual(len(explainers), 6)
        text = " ".join(value for item in explainers for value in item.values())
        for required in ("NOPAT", "平均投入資本", "資料不足，不是0%", "CFO", "Capex", "完整杜邦分析", "48天→44天→42天", "P/B不能單獨判斷"):
            self.assertIn(required, text)
        self.assertNotIn("ROIC＝0", text)

    def test_enterprise_value_scorecard_excludes_price_as_core_kpi(self) -> None:
        rows = self.renderer._kpi_rows()
        self.assertEqual(len(rows), 12)
        labels = " ".join(row[0] for row in rows)
        self.assertNotIn("股價", labels)
        self.assertIn("市場定價與基本面支持", self.markdown)
        self.assertIn("次要脈絡", self.combined)

    def test_six_core_charts_have_explicit_highlights(self) -> None:
        self.assertEqual(self.html.count('class="highlight"'), 6)
        for text in ("營業利益明顯跑贏營收與毛利", "毛利率未擴張，營益率卻改善", "資金占用增加，但週轉效率反而改善", "2025Q2降至105.14元", "Q2證據缺口，不是0%"):
            self.assertIn(text, self.html)

    def test_outlook_is_kpi_based_and_conclusion_is_ordered(self) -> None:
        rows = self.renderer._outlook_rows()
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(len(row) == 8 for row in rows))
        for heading in ("營運端正在強化什麼？", "目前最大的負偏差是什麼？", "最大的資料缺口是什麼？", "AI下一階段真正要驗證什麼？", "什麼條件會讓P1008判斷升級／降級？"):
            self.assertIn(heading, self.combined)
        self.assertIn("## 最終投資判讀", self.markdown)

    def test_citations_auditability_and_governance_are_separated(self) -> None:
        main = self.markdown.split("## Technical Evidence Appendix", 1)[0]
        self.assertNotIn("IR-EVIDENCE-", main)
        self.assertNotIn("AUTH-MASTER-", main)
        self.assertIn("## 參考資料", self.markdown)
        self.assertIn("## Technical Evidence Appendix", self.markdown)
        self.assertIn("Evidence IDs", self.markdown)
        for forbidden in ("目標價", "買進", "賣出"):
            if forbidden == "目標價":
                self.assertIn("不提供目標價", self.combined)
            else:
                self.assertNotIn(forbidden, self.combined)
        self.assertIn("actionable=false", self.combined)
        self.assertIn("publication=false", self.combined)
        self.assertIn("OWNER_REVIEW_REQUIRED=true", self.combined)


if __name__ == "__main__":
    unittest.main()
