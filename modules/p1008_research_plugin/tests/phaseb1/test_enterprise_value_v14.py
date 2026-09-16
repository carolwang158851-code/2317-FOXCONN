from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

try:
    from .helpers import GOVERNED_Q2_EVIDENCE_ROOT, PACKAGE_ROOT, scratch
except ImportError:
    from helpers import GOVERNED_Q2_EVIDENCE_ROOT, PACKAGE_ROOT, scratch

from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline
from p1008_research_plugin.reporting.report_contracts import QUARTERLY_VISIBLE_GROUPS


class EnterpriseValueV14Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence_root = Path(
            os.environ.get("P1008_GOVERNED_EVIDENCE_ROOT", GOVERNED_Q2_EVIDENCE_ROOT)
        ).resolve()
        trigger_path = cls.evidence_root / "report_trigger/latest_decision.json"
        integration_path = cls.evidence_root / "research_plugin/latest_content_integration.json"
        if not trigger_path.is_file() or not integration_path.is_file():
            raise unittest.SkipTest("governed FY2026 Q2 evidence is unavailable")
        trigger = json.loads(trigger_path.read_text(encoding="utf-8"))
        cls.lineage = {
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
        cls._scratch = scratch("enterprise-value-v14-")
        cls.output = cls._scratch.__enter__()
        pipeline = PhaseB1Pipeline(PACKAGE_ROOT, governed_evidence_root=cls.evidence_root)
        analysis_result = pipeline.build_analysis(output_base=cls.output, trigger_lineage=cls.lineage)
        cls.result = pipeline.build_report(
            run_id=analysis_result["run_id"], output_base=cls.output, trigger_lineage=cls.lineage
        )
        cls.run_root = Path(cls.result["run_root"])
        cls.analytics = cls.result["analysis"].quarterly_earnings.enterprise_value_analytics
        cls.charts = json.loads((cls.run_root / "chart_data.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "_scratch"):
            cls._scratch.__exit__(None, None, None)

    def test_official_direct_profit_values_are_preserved(self) -> None:
        self.assertEqual(self.analytics["revenueMillionTwd"], "2525894")
        self.assertEqual(self.analytics["revenueProvenance"], "OFFICIAL")
        self.assertEqual(self.analytics["grossProfitMillionTwd"], "154533")
        self.assertEqual(self.analytics["operatingProfitMillionTwd"], "94803")
        self.assertEqual(self.analytics["pretaxProfitMillionTwd"], "94866")
        self.assertEqual(self.analytics["incomeTaxExpenseMillionTwd"], "24810")
        self.assertEqual(self.analytics["grossProfitProvenance"], "OFFICIAL")
        self.assertEqual(self.analytics["operatingProfitProvenance"], "OFFICIAL")

    def test_q2_cash_derivation_is_reconciled_and_transparent(self) -> None:
        self.assertEqual(self.analytics["q2StandaloneCfoMillionTwd"], "-72339.154")
        self.assertEqual(self.analytics["q2StandaloneCapexMillionTwd"], "45111.655")
        self.assertEqual(self.analytics["q2StandaloneFcfMillionTwd"], "-117450.809")
        self.assertEqual(self.analytics["q2StandaloneFcfRoundingDifferenceMillionTwd"], "1.000")
        self.assertEqual(self.analytics["q2CashMetricOrigin"], "DERIVED_FROM_OFFICIAL")
        self.assertEqual(self.analytics["q2CashConfidence"], "HIGH")

    def test_working_capital_and_limited_capex_history_are_explicit(self) -> None:
        wc = self.analytics["workingCapital"]
        self.assertEqual(wc["periods"], ["2025Q2", "2026Q1", "2026Q2"])
        self.assertEqual(wc["cashConversionCycleDays"], ["48", "44", "42"])
        self.assertEqual(wc["assessment"], "GROWTH_DRIVEN_ABSORPTION_WITH_EFFICIENCY_IMPROVEMENT")
        capex = next(item for item in self.charts if item["chartId"] == "capex_intensity_limited")
        self.assertIn("2026H1", capex["period"])
        self.assertIn("官方累計值", capex["period"])

    def test_eight_quarter_operating_leverage_history_is_complete(self) -> None:
        history = self.result["analysis"].quarterly_earnings.quarterly_history
        for key in ("periods", "revenue100mTwd", "grossProfit100mTwd", "operatingIncome100mTwd", "opexProxy100mTwd", "opexProxyRevenuePct"):
            self.assertEqual(len(history[key]), 8, key)
        self.assertEqual(history["grossProfitOrigin"][-1], "OFFICIAL")
        self.assertEqual(history["operatingProfitOrigin"][-1], "OFFICIAL")

    def test_formula_cards_define_formula_inputs_result_use_and_limit(self) -> None:
        cards = self.analytics["formulaCards"]
        self.assertGreaterEqual(len(cards), 8)
        for card in cards:
            for key in ("metric", "whyItMatters", "formula", "currentInputs", "currentResult", "plainLanguage", "decisionUse", "limitation"):
                self.assertTrue(card[key], (card["metric"], key))

    def test_strategy_scorecard_uses_only_verified_three_plus_three(self) -> None:
        scorecard = self.analytics["strategyScorecard"]
        verified = [item for item in scorecard if item["officialStatus"] == "OFFICIAL_VERIFIED"]
        self.assertEqual(len(verified), 6)
        self.assertEqual(len(scorecard), 6)
        self.assertEqual(self.analytics["strategyEvidenceGap"]["status"], "NOT_VERIFIED")
        self.assertNotIn("智慧平台", " ".join(item["strategicPillar"] for item in verified))

    def test_ai_evidence_states_separate_direction_from_amount(self) -> None:
        self.assertEqual(
            self.analytics["aiMaterialOperatingProfitContributionDirection"],
            "PARTIALLY_PROVEN_HIGH_CONFIDENCE_INFERENCE",
        )
        self.assertEqual(self.analytics["aiOperatingProfitStatus"], "UNPROVEN_SPECIFIC_AMOUNT")
        self.assertEqual(self.analytics["aiSpecificMarginStatus"], "UNPROVEN")
        self.assertEqual(self.analytics["aiFcfContributionStatus"], "UNPROVEN")

    def test_value_chain_has_evidence_provenance_trend_and_next_checkpoint(self) -> None:
        matrix = self.analytics["valueChainEvidenceMatrix"]
        self.assertEqual(len(matrix), 16)
        for row in matrix:
            for key in ("evidenceStatus", "provenance", "currentEvidence", "trend", "valueImplication", "nextCheckpoint"):
                self.assertTrue(row[key], (row["link"], key))

    def test_report_has_twelve_visible_groups_and_governed_chart_meaning(self) -> None:
        self.assertEqual(len(QUARTERLY_VISIBLE_GROUPS), 12)
        self.assertEqual(len(self.charts), 12)
        for chart in self.charts:
            for key in ("decisionQuestion", "period", "sourceEvidenceIds", "observationZh", "interpretationZh", "strategicImplicationZh", "enterpriseValueImplicationZh", "nextCheckpointZh"):
                self.assertTrue(chart[key], (chart["chartId"], key))

    def test_required_owner_review_artifacts_exist_and_are_non_actionable(self) -> None:
        for name in (
            "validated_research_pack.json", "report_candidate.md", "report_candidate.html",
            "report_candidate.pdf", "chart_data.json", "formula_cards.json",
            "strategy_scorecard.json", "owner_review.json", "skill_execution_summary.json",
        ):
            self.assertTrue((self.run_root / name).is_file(), name)
        owner = json.loads((self.run_root / "owner_review.json").read_text(encoding="utf-8"))
        manifest = json.loads((self.run_root / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(owner["templateVersion"], "1.4.1")
        self.assertFalse(owner["actionable"])
        self.assertEqual(set(manifest["externalCalls"].values()), {0})

    def test_final_conclusion_answers_six_questions_and_separates_retirement_states(self) -> None:
        conclusion = self.analytics["finalResearchConclusion"]
        self.assertGreaterEqual(len(conclusion), 9)
        self.assertTrue(all(conclusion.values()))
        mission = self.analytics["retirementMission"]
        self.assertEqual(mission["thesisSurvival"], "SURVIVES")
        self.assertEqual(mission["valuationSafety"], "NOT_IMPROVED")
        self.assertEqual(mission["cashflowSafety"], "NOT_PROVEN")

    def test_management_claims_and_future_checkpoints_are_governed(self) -> None:
        operating_model = self.analytics["managementOperatingModel"]
        self.assertEqual(len(operating_model), 6)
        for row in operating_model:
            for key in ("theme", "managementClaim", "financialEvidence", "counterevidence", "assessment"):
                self.assertTrue(row[key], (row["theme"], key))
        checkpoints = self.analytics["futureCheckpoints"]
        self.assertEqual([row["priority"] for row in checkpoints], list(range(1, 7)))
        for row in checkpoints:
            for key in ("metric", "whyItMatters", "currentBaseline", "improvementCondition", "deteriorationCondition", "nextExpectedDisclosure"):
                self.assertTrue(row[key], (row["priority"], key))
        self.assertEqual(
            self.analytics["strategyFrameworkVerification"],
            "PARTIAL_OFFICIAL_3_PLUS_3_VERIFIED_THIRD_3_NOT_VERIFIED",
        )


if __name__ == "__main__":
    unittest.main()
