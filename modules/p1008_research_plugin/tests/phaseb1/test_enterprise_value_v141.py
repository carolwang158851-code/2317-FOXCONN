from __future__ import annotations

import json
import os
import unittest
from decimal import Decimal
from pathlib import Path

try:
    from .helpers import PACKAGE_ROOT, scratch
except ImportError:
    from helpers import PACKAGE_ROOT, scratch

from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline
from p1008_research_plugin.reporting.report_contracts import QUARTERLY_VISIBLE_GROUPS


class EnterpriseValueV141Tests(unittest.TestCase):
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
            "reportKey": trigger["report_key"],
            "revision": trigger["revision"],
            "eventType": trigger["event_type"],
            "canonicalEventId": trigger["canonical_event_id"],
            "triggerDecisionId": trigger["decision_id"],
            "triggerReceiptSha256": trigger["canonical_sha256"],
            "evidenceIds": trigger["qualifying_evidence_ids"],
            "authorityCutoffs": trigger["authority_cutoffs"],
            "actionable": False,
        }
        cls._scratch = scratch("enterprise-value-v141-")
        cls.output = cls._scratch.__enter__()
        pipeline = PhaseB1Pipeline(PACKAGE_ROOT, governed_evidence_root=cls.evidence_root)
        analysis_result = pipeline.build_analysis(output_base=cls.output, trigger_lineage=lineage)
        cls.result = pipeline.build_report(
            run_id=analysis_result["run_id"], output_base=cls.output, trigger_lineage=lineage
        )
        cls.run_root = Path(cls.result["run_root"])
        cls.analysis = cls.result["analysis"]
        cls.q = cls.analysis.quarterly_earnings
        cls.analytics = cls.q.enterprise_value_analytics
        cls.valuation = cls.q.valuation_scenarios
        cls.charts = json.loads((cls.run_root / "chart_data.json").read_text(encoding="utf-8"))
        cls.markdown = (cls.run_root / "report_candidate.md").read_text(encoding="utf-8")
        cls.html = (cls.run_root / "report_candidate.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "_scratch"):
            cls._scratch.__exit__(None, None, None)

    def chart(self, chart_id: str) -> dict:
        return next(item for item in self.charts if item["chartId"] == chart_id)

    def test_eps_single_source_and_valuation_reconcile(self) -> None:
        self.assertEqual(self.valuation["q4_2025Eps"]["value"], "3.23")
        self.assertEqual(self.valuation["q4_2025Eps"]["classification"], "GOVERNED_AUTHORITY")
        self.assertEqual(self.valuation["ttmEpsComponents"]["values"], ["4.15", "3.23", "3.56", "4.27"])
        total = sum(Decimal(item) for item in self.valuation["ttmEpsComponents"]["values"])
        self.assertEqual(total, Decimal(self.valuation["ttmEps"]["value"]))
        self.assertEqual(self.valuation["ttmEps"]["value"], "15.21")
        self.assertEqual(self.valuation["ttmPe"]["value"], "17.29")
        self.assertEqual(self.valuation["priorH2Eps"]["value"], "7.40")
        self.assertEqual([row["fy26Eps"] for row in self.valuation["forwardPeScenarios"]], ["15.95", "16.69", "17.42"])
        governed_text = self.markdown + self.html + json.dumps(self.valuation, ensure_ascii=False)
        self.assertNotIn("2025Q4的3.23", governed_text)

    def test_cash_proxy_preserves_scope_and_owner_interpretation(self) -> None:
        self.assertEqual(self.analytics["cashConversionMetric"], "CFO／歸母淨利警示代理值")
        self.assertEqual(self.analytics["cashConversionClassification"], "WARNING_PROXY_SCOPE_MISMATCH")
        self.assertIn("不是標準現金轉化率", self.analytics["cashConversionScope"])
        card = next(row for row in self.analytics["formulaCards"] if row["metric"] == "CFO／歸母淨利警示代理值")
        self.assertIn("範圍不同", card["limitation"])
        self.assertIn("48天", self.markdown)
        self.assertIn("42天", self.markdown)
        self.assertIn("而非已證實的週轉效率惡化", self.markdown)

    def test_operating_expense_proxy_and_visual_units_are_valid(self) -> None:
        card = next(row for row in self.analytics["formulaCards"] if row["metric"] == "營業費用代理值")
        self.assertNotEqual(card["metric"], "營業成本")
        self.assertIn("不是公司直接揭露", card["limitation"])
        chart = self.chart("operating_cost_absorption_8q")
        self.assertEqual(len(chart["series"]), 1)
        self.assertEqual(chart["series"][0]["unit"], "%")
        self.assertEqual(chart["series"][0]["values"], ["3.235", "3.123", "3.282", "3.174", "2.926", "2.596", "2.630", "2.365"])
        self.assertIn("597.30億元", " ".join(chart["commentaryZh"]))

    def test_working_capital_and_ccc_do_not_share_absolute_axis(self) -> None:
        chart = self.chart("working_capital_3period")
        self.assertEqual(chart["visualizationType"], "QUANTITATIVE_CHART")
        self.assertEqual([s["unit"] for s in chart["series"][:3]], ["2025Q2=100"] * 3)
        self.assertIn("不共用指數尺度", chart["series"][3]["unit"])
        self.assertEqual(chart["series"][3]["values"], ["48", "44", "42"])
        self.assertFalse(any(s["unit"] == "新台幣百萬元" for s in chart["series"]))

    def test_capex_and_roic_visual_governance(self) -> None:
        capex = self.chart("capex_intensity_limited")
        self.assertEqual(capex["visualizationType"], "EVIDENCE_TABLE")
        self.assertIn("LIMITED_HISTORY", capex["period"])
        roic = self.chart("capital_validation_status")
        self.assertEqual(roic["series"][0]["values"], ["10.51", "13.16", "7.91", "10.66", "11.77", "14.41", "12.57", "INSUFFICIENT_DATA"])
        self.assertNotEqual(roic["series"][0]["values"][-1], "0")

    def test_roe_is_first_class_and_dupont_is_partial(self) -> None:
        roe = self.analytics["roe"]
        self.assertEqual((roe["comparablePeriod"], roe["comparablePct"]), ("2025H1", "5.48"))
        self.assertEqual((roe["currentPeriod"], roe["currentPct"]), ("2026H1", "6.21"))
        self.assertEqual(roe["yoyChangePp"], "+0.73")
        self.assertEqual(roe["fullYearBaselinePct"], "11.3")
        self.assertEqual(roe["targetStatus"], "NOT_VERIFIED")
        self.assertIn("H1只與H1比較", roe["periodDiscipline"])
        self.assertTrue(self.analytics["dupont"].startswith("PARTIAL_DUPONT"))
        self.assertTrue(any(card["metric"] == "股東權益報酬率 ROE" for card in self.analytics["formulaCards"]))

    def test_bvps_direct_authority_and_pb_roe_linkage(self) -> None:
        bvps = self.analytics["bvps"]
        self.assertEqual(bvps["currentValue"], "127.12")
        self.assertEqual(bvps["provenance"], "GOVERNED_AUTHORITY_DIRECT")
        self.assertEqual(len(bvps["periods"]), 7)
        self.assertEqual(len(bvps["values"]), 7)
        self.assertEqual(self.valuation["governedBvps"]["value"], "127.12")
        self.assertIn("P/B不能脫離ROE", self.markdown)
        for forbidden in ("買進", "賣出", "目標價", "P/B顯示便宜", "P/B顯示昂貴"):
            self.assertNotIn(forbidden, self.markdown)
        self.assertIn("不判定2.069倍便宜或昂貴", self.markdown)
        self.assertEqual(self.chart("roe_equity_compounding")["series"][0]["labelZh"], "每股淨值")
        self.assertIn("2025Q2曾降至105.14元", self.markdown)
        self.assertIn("原因待驗證", self.markdown)

    def test_strategy_has_six_longitudinal_pillars_and_separate_gap(self) -> None:
        scorecard = self.analytics["strategyScorecard"]
        self.assertEqual(len(scorecard), 6)
        self.assertNotIn("第三個3", " ".join(row["strategicPillar"] for row in scorecard))
        for row in scorecard:
            for key in ("priorStage", "currentStage", "changeThisQuarter", "currentRevenueEvidence", "currentProfitEvidence", "capitalEfficiencyEvidence", "cashFlowEvidence", "nextGate", "nextCheckpoint"):
                self.assertTrue(row[key], (row["strategicPillar"], key))
        self.assertEqual(self.analytics["strategyEvidenceGap"]["renderLocation"], "STRATEGY_EVIDENCE_GAP")

    def test_owner_rendering_has_no_raw_strategy_codes(self) -> None:
        rendered = self.markdown + self.html
        for code in ("NOT_SEPARATELY_DISCLOSED", "OFFICIAL_VERIFIED", ">DEVELOPMENT<", ">STRATEGY<", ">REVENUE<"):
            self.assertNotIn(code, rendered)

    def test_visual_hierarchy_and_formula_cards(self) -> None:
        self.assertEqual(len(QUARTERLY_VISIBLE_GROUPS), 12)
        self.assertEqual(len(self.charts), 12)
        self.assertNotIn("operating_leverage_spread", {row["chartId"] for row in self.charts})
        self.assertNotIn("governance_target_vs_actual", {row["chartId"] for row in self.charts})
        cards = self.analytics["formulaCards"]
        self.assertEqual(len(cards), 10)
        self.assertEqual({row["metric"] for row in cards}, {"營運槓桿差", "營業費用代理值", "自由現金流", "CFO／歸母淨利警示代理值", "ROIC", "增量ROIC", "股東權益報酬率 ROE", "本益比", "股價淨值比", "股息殖利率"})

    def test_closing_thesis_and_governance_flags(self) -> None:
        closing = next(section for section in self.result["report"].sections if section.section_id == "RETIREMENT_CASHFLOW_IMPLICATION")
        for term in ("管理", "企業價值", "ROE", "BVPS", "CFO", "FCF", "AI", "未來一至四季", "退休"):
            self.assertIn(term, closing.body_zh)
        mission = self.analytics["retirementMission"]
        self.assertEqual(mission["thesisSurvival"], "SURVIVES")
        self.assertEqual(mission["valuationSafety"], "NOT_IMPROVED")
        self.assertEqual(mission["cashflowSafety"], "NOT_PROVEN")
        self.assertIn("NOT_UPGRADED", mission["dividendCapacity"])
        owner = json.loads((self.run_root / "owner_review.json").read_text(encoding="utf-8"))
        manifest = json.loads((self.run_root / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(owner["templateVersion"], "1.4.1")
        self.assertFalse(owner["actionable"])
        self.assertFalse(owner["publication"])
        self.assertTrue(owner["ownerReviewRequired"])
        self.assertEqual(set(manifest["externalCalls"].values()), {0})


if __name__ == "__main__":
    unittest.main()
