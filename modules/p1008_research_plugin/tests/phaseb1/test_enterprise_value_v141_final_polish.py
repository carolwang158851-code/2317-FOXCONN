from __future__ import annotations

import hashlib
import json
import os
import unittest
from pathlib import Path

try:
    from .helpers import PACKAGE_ROOT, scratch
except ImportError:
    from helpers import PACKAGE_ROOT, scratch

from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline


class EnterpriseValueV141FinalPolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence_root = Path(
            os.environ.get("P1008_GOVERNED_EVIDENCE_ROOT", PACKAGE_ROOT / "runtime")
        ).resolve()
        trigger_path = cls.evidence_root / "report_trigger/latest_decision.json"
        integration_path = cls.evidence_root / "research_plugin/latest_content_integration.json"
        if not trigger_path.is_file() or not integration_path.is_file():
            raise unittest.SkipTest("governed FY2026 Q2 evidence is unavailable")
        trigger = json.loads(trigger_path.read_text(encoding="utf-8"))
        lineage = {
            "reportKey": trigger["report_key"], "revision": trigger["revision"],
            "eventType": trigger["event_type"], "canonicalEventId": trigger["canonical_event_id"],
            "triggerDecisionId": trigger["decision_id"], "triggerReceiptSha256": trigger["canonical_sha256"],
            "evidenceIds": trigger["qualifying_evidence_ids"], "authorityCutoffs": trigger["authority_cutoffs"],
            "actionable": False,
        }
        cls._scratch = scratch("enterprise-value-v141-final-")
        cls.output = cls._scratch.__enter__()
        pipeline = PhaseB1Pipeline(PACKAGE_ROOT, governed_evidence_root=cls.evidence_root)
        analysis = pipeline.build_analysis(output_base=cls.output, trigger_lineage=lineage)
        cls.result = pipeline.build_report(run_id=analysis["run_id"], output_base=cls.output, trigger_lineage=lineage)
        cls.root = Path(cls.result["run_root"])
        cls.pack_bytes = (cls.root / "validated_research_pack.json").read_bytes()
        cls.pack = json.loads(cls.pack_bytes)
        cls.charts = json.loads((cls.root / "chart_data.json").read_text(encoding="utf-8"))
        cls.formulas = json.loads((cls.root / "formula_cards.json").read_text(encoding="utf-8"))
        cls.md = (cls.root / "report_candidate.md").read_text(encoding="utf-8")
        cls.html = (cls.root / "report_candidate.html").read_text(encoding="utf-8")
        from pypdf import PdfReader
        cls.pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(cls.root / "report_candidate.pdf").pages)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "_scratch"):
            cls._scratch.__exit__(None, None, None)

    def chart(self, chart_id: str) -> dict:
        return next(item for item in self.charts if item["chartId"] == chart_id)

    def test_research_metrics_and_backend_formula_meaning_are_frozen(self) -> None:
        valuation = self.pack["valuationScenarios"]
        self.assertEqual(valuation["q4_2025Eps"]["value"], "3.23")
        self.assertEqual(valuation["ttmEps"]["value"], "15.21")
        self.assertEqual(valuation["ttmPe"]["value"], "17.29")
        self.assertEqual(len(self.formulas), 10)
        self.assertEqual(self.formulas, self.pack["enterpriseValueAnalytics"]["formulaCards"])
        self.assertEqual(hashlib.sha256(self.pack_bytes).hexdigest().upper(), "72B33BD7040F3B55870FC3CA707FB069E9B21DA56C7C153F8541CEADC0114EEE")

    def test_working_capital_is_index_chart_with_separate_ccc(self) -> None:
        chart = self.chart("working_capital_3period")
        self.assertEqual(chart["visualizationType"], "QUANTITATIVE_CHART")
        self.assertEqual([row["values"] for row in chart["series"][:3]], [["100.0", "124.0", "147.3"], ["100.0", "129.3", "146.4"], ["100.0", "131.8", "152.2"]])
        self.assertEqual(chart["series"][3]["values"], ["48", "44", "42"])
        self.assertIn("series_limit=3", Path(__file__).parents[2].joinpath("src/p1008_research_plugin/reporting/report_renderer_formal.py").read_text(encoding="utf-8"))
        self.assertIn("48天 → 44天 → 42天", self.html + self.pdf_text)

    def test_bvps_and_roe_are_separate_and_non_monotonic_language_is_correct(self) -> None:
        chart = self.chart("roe_equity_compounding")
        self.assertEqual(chart["series"][0]["values"], ["115.16", "118.45", "118.2", "105.14", "117.18", "126.96", "127.12"])
        rendered = self.md + self.html + self.pdf_text
        self.assertIn("105.14", rendered)
        self.assertIn("5.48% → 6.21%", rendered)
        self.assertIn("H1不年化", rendered)
        self.assertIn("原因待驗證", rendered)
        self.assertNotIn("BVPS一路上升", rendered)
        self.assertNotIn("股東權益持續單調累積", rendered)
        self.assertNotIn("ROE（新台幣元）", rendered)

    def test_exactly_five_backend_selected_formula_cards_are_visible(self) -> None:
        expected = ["營運槓桿怎麼看？", "自由現金流怎麼看？", "ROIC在看什麼？", "ROE在看什麼？", "P/B為什麼一定要配ROE看？"]
        for title in expected:
            self.assertEqual(self.html.count(title), 1)
            self.assertEqual(self.pdf_text.count(title), 1)
        self.assertEqual(self.html.count('class="formula-card"'), 5)
        self.assertIn("DERIVED FROM OFFICIAL COMPARABLE PERIODS", self.html + self.pdf_text)

    def test_three_branch_model_replaces_linear_misstatement(self) -> None:
        rendered = self.md + self.html + self.pdf_text
        for label in ("企業資本效率", "股東資本效率", "現金生成"):
            self.assertIn(label, rendered)
        self.assertNotIn("ROIC→淨利→ROE→BVPS／股東權益複利→CFO", rendered)
        self.assertNotIn("BVPS → CFO", rendered)

    def test_page_one_and_final_thesis_are_distinct(self) -> None:
        from p1008_research_plugin.reporting.report_contracts import QUARTERLY_VISIBLE_GROUPS
        self.assertNotIn("RETIREMENT_CASHFLOW_IMPLICATION", QUARTERLY_VISIBLE_GROUPS[0][1])
        self.assertIn("治理、企業價值與退休任務總結", self.md)
        report = self.result["report"]
        executive = next(row.body_zh for row in report.sections if row.section_id == "EXECUTIVE_SUMMARY")
        closing = next(row.body_zh for row in report.sections if row.section_id == "RETIREMENT_CASHFLOW_IMPLICATION")
        self.assertLess(len(executive), len(closing) // 2)
        self.assertNotEqual(executive, closing)

    def test_owner_surfaces_remove_renderer_codes_and_preserve_governance(self) -> None:
        for code in ("LIMITED_HISTORY", "QUANTITATIVE_CHART", "STATUS_MATRIX", "EVIDENCE_TABLE", "SCENARIO_MATRIX"):
            self.assertNotIn(code, self.pdf_text)
        owner = json.loads((self.root / "owner_review.json").read_text(encoding="utf-8"))
        self.assertEqual(owner["templateVersion"], "1.4.1")
        self.assertFalse(owner["actionable"])
        self.assertFalse(owner["publication"])
        self.assertTrue(owner["ownerReviewRequired"])


if __name__ == "__main__":
    unittest.main()
