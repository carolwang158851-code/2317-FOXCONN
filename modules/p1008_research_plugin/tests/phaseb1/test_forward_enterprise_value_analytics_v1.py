from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from uuid import uuid4

try:
    from .helpers import GOVERNED_Q2_EVIDENCE_ROOT, GOVERNED_Q2_SOURCE_MOTHER, PACKAGE_ROOT
except ImportError:
    from helpers import GOVERNED_Q2_EVIDENCE_ROOT, GOVERNED_Q2_SOURCE_MOTHER, PACKAGE_ROOT

from p1008_research_plugin.phaseb1_common import protected_state_hashes
from p1008_research_plugin.reporting.enterprise_value_rule_engine import (
    DecisionRuleError,
    apply_smart_override,
    build_smart_state,
    structural_deterioration_scenario,
)
from p1008_research_plugin.reporting.forward_enterprise_value_analytics import (
    calculate_roic,
    capital_light_proxy,
    dilution_matrix,
    per_share_growth,
    roic_sensitivity,
    working_capital_stress,
)
from p1008_research_plugin.reporting.war_report_production_runtime import run_war_report_production


EVIDENCE_ROOT = Path(
    os.environ.get(
        "P1008_GOVERNED_EVIDENCE_ROOT",
        GOVERNED_Q2_EVIDENCE_ROOT,
    )
).resolve()
SOURCE_MOTHER = GOVERNED_Q2_SOURCE_MOTHER.resolve()


class ForwardEnterpriseValueAnalyticsV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not EVIDENCE_ROOT.is_dir() or not SOURCE_MOTHER.is_file():
            raise AssertionError("governed local Q2 evidence or proven mother is unavailable")
        trigger = json.loads((EVIDENCE_ROOT / "report_trigger/latest_decision.json").read_text(encoding="utf-8"))
        lineage = {
            "reportKey": trigger["report_key"], "revision": trigger["revision"],
            "eventType": trigger["event_type"], "canonicalEventId": trigger["canonical_event_id"],
            "triggerDecisionId": trigger["decision_id"], "triggerReceiptSha256": trigger["canonical_sha256"],
            "evidenceIds": trigger["qualifying_evidence_ids"], "authorityCutoffs": trigger["authority_cutoffs"],
            "actionable": False,
        }
        parent = PACKAGE_ROOT / "runtime" / "phaseb1_test_scratch"
        parent.mkdir(parents=True, exist_ok=True)
        cls.output = parent / f"forward-ev-v1-{uuid4().hex}"
        cls.output.mkdir(parents=False, exist_ok=False)
        cls.before = protected_state_hashes(PACKAGE_ROOT)
        cls.result = run_war_report_production(
            package_root=PACKAGE_ROOT, trigger_context=lineage, output_base=cls.output,
            governed_evidence_root=EVIDENCE_ROOT, source_mother=SOURCE_MOTHER,
        )
        cls.after = protected_state_hashes(PACKAGE_ROOT)
        cls.root = Path(cls.result["output_root"])
        cls.forward = json.loads((cls.root / "forward_enterprise_value_analytics.json").read_text(encoding="utf-8"))
        cls.rules = json.loads((cls.root / "enterprise_value_rule_engine.json").read_text(encoding="utf-8"))
        cls.smart = json.loads((cls.root / "smart_state.json").read_text(encoding="utf-8"))
        cls.html = Path(cls.result["output_html"]).read_text(encoding="utf-8")

    def test_f1_t4_scenarios_cannot_enter_actual_history(self) -> None:
        self.assertFalse(self.forward["actual_history_mutated"])
        self.assertEqual(self.forward["historical_observation_count_before"], self.forward["historical_observation_count_after"])
        self.assertTrue(all(item["data_class"] == "T4_MODEL_SCENARIO" for item in self.forward["roic_sensitivity"]["scenarios"]))

    def test_f2_roic_sensitivity_monotonicity(self) -> None:
        result = roic_sensitivity(operating_profit=100, pretax_income=100, income_tax=20, latest_actual_roic_pct=10, input_ids=["X"])
        values = [float(item["result"]["annualized_roic_persistence_sensitivity_pct"]) for item in result["scenarios"]]
        self.assertGreater(values[0], values[1])
        self.assertGreater(values[1], values[2])
        self.assertGreater(calculate_roic(110, 1000), calculate_roic(100, 1000))

    def test_f3_quarterly_and_annualized_roic_are_separate(self) -> None:
        item = self.forward["roic_sensitivity"]["scenarios"][1]["result"]
        self.assertNotEqual(item["quarterly_roic_persistence_sensitivity_pct"], item["annualized_roic_persistence_sensitivity_pct"])
        self.assertIn(self.forward["roic_sensitivity"]["actual_same_basis_q2"]["status"], {"PENDING_OR_UNAVAILABLE", "ESTIMATED_PARTIAL_OPERATING_IC_AVAILABLE"})

    def test_f4_wc_delta_dso(self) -> None:
        result = working_capital_stress(revenue=900, cogs=600, baseline_cfo=100, capex=20, delta_dso=9, delta_dio=0, delta_dpo=0, day_basis=90)
        self.assertEqual(result["delta_ar_cash_requirement"], "90")

    def test_f5_wc_delta_dio(self) -> None:
        result = working_capital_stress(revenue=900, cogs=600, baseline_cfo=100, capex=20, delta_dso=0, delta_dio=9, delta_dpo=0, day_basis=90)
        self.assertEqual(result["delta_inventory_cash_requirement"], "60")

    def test_f6_wc_delta_dpo_relief_and_negative_change(self) -> None:
        positive = working_capital_stress(revenue=900, cogs=600, baseline_cfo=100, capex=20, delta_dso=0, delta_dio=0, delta_dpo=9, day_basis=90)
        negative = working_capital_stress(revenue=900, cogs=600, baseline_cfo=100, capex=20, delta_dso=0, delta_dio=0, delta_dpo=-9, day_basis=90)
        self.assertEqual(positive["delta_ap_funding_relief"], "60")
        self.assertEqual(negative["delta_ap_funding_relief"], "-60")

    def test_f7_wc_stressed_cfo(self) -> None:
        result = working_capital_stress(revenue=900, cogs=600, baseline_cfo=100, capex=20, delta_dso=9, delta_dio=9, delta_dpo=9, day_basis=90)
        self.assertEqual(result["net_incremental_working_capital_requirement"], "90")
        self.assertEqual(result["stressed_cfo"], "10")

    def test_f8_wc_stressed_fcf(self) -> None:
        result = working_capital_stress(revenue=900, cogs=600, baseline_cfo=100, capex=20, delta_dso=9, delta_dio=9, delta_dpo=9, day_basis=90)
        self.assertEqual(result["stressed_fcf"], "-10")
        self.assertEqual(result["funding_need_indication"], "10")

    def test_f9_dilution_matrix_exact_eps_math(self) -> None:
        self.assertAlmostEqual(float(per_share_growth(10, 10)), 0.0)
        self.assertGreater(per_share_growth(11, 10), 0)
        self.assertLess(per_share_growth(9, 10), 0)

    def test_f10_bvps_uses_period_end_shares(self) -> None:
        self.assertEqual(self.forward["dilution_sensitivity"]["BVPS"]["denominator_basis"], "PERIOD_END_SHARES_T4_SCENARIO")

    def test_f11_fcf_per_share_basis_is_preserved(self) -> None:
        basis = self.forward["dilution_sensitivity"]["FCF_PER_SHARE"]["denominator_basis"]
        self.assertIn("FCF_PER_SHARE_V1", basis)
        for growth in (0, 5, 10):
            self.assertAlmostEqual(float(per_share_growth(growth, growth)), 0.0)

    def test_f12_break_even_dilution(self) -> None:
        matrix = dilution_matrix(metric="EPS", numerator_growth_axis=[3], share_growth_axis=[3], denominator_basis="COMPATIBLE_WEIGHTED_AVERAGE_SHARES")
        self.assertEqual(matrix["rows"][0]["values"][0]["per_share_growth_pct"], "0.0000")

    def test_f13_capital_light_uses_multiple_indicators(self) -> None:
        wc = {
            "accountsReceivableMillionTwd": [100, 90], "inventoryMillionTwd": [100, 80], "accountsPayableMillionTwd": [50, 55],
            "cashConversionCycleDays": [50, 40], "accountsReceivableDays": [30, 25], "inventoryDays": [30, 25], "accountsPayableDays": [10, 10],
        }
        result = capital_light_proxy(periods=["P1", "P2"], revenue=[200, 220], wc=wc, cfo=20, fcf=10, capex=5)
        self.assertEqual(result["signal"], "IMPROVING")
        mixed = dict(wc)
        mixed["accountsReceivableMillionTwd"] = [100, 140]
        mixed["inventoryMillionTwd"] = [100, 130]
        mixed["accountsPayableMillionTwd"] = [50, 30]
        mixed["accountsReceivableDays"] = [40, 35]
        mixed["inventoryDays"] = [40, 35]
        self.assertIn(capital_light_proxy(periods=["P1", "P2"], revenue=[200, 220], wc=mixed, cfo=-1, fcf=2, capex=5)["signal"], {"INCONCLUSIVE", "NEUTRAL"})

    def test_f14_ccc_cannot_fabricate_consignment_percentage(self) -> None:
        self.assertIsNone(self.forward["capital_light_proxy"]["consignment_percentage"])
        self.assertNotIn("Consignment share", self.html)

    def test_f15_negative_fcf_alone_does_not_trigger_downgrade(self) -> None:
        result = structural_deterioration_scenario(negative_fcf=True, roic_falling=False, ccc_worsening=False, cfo_conversion_weak=False, operating_profit_weak=False)
        self.assertNotEqual(result["THESIS_DOWNGRADE_GATE"], "TRIGGERED")

    def test_f16_multi_factor_structural_deterioration_can_trigger(self) -> None:
        result = structural_deterioration_scenario(negative_fcf=True, roic_falling=True, ccc_worsening=True, cfo_conversion_weak=True)
        self.assertEqual(result["THESIS_DOWNGRADE_GATE"], "TRIGGERED")

    def test_f17_t2_does_not_become_actual(self) -> None:
        self.assertEqual(self.forward["dilution_sensitivity"]["weighted_average_share_estimate_class"], "T2_ESTIMATED_DERIVED")
        self.assertEqual(self.forward["roic_sensitivity"]["actual_same_basis_q2"]["value"], None)

    def test_f18_estimated_roic_alone_does_not_trigger(self) -> None:
        roic_rule = next(item for item in self.rules["rules"] if item["dimension"] == "ROIC_STATE")
        self.assertTrue(roic_rule["estimated_data_dependence"])
        self.assertNotEqual(self.rules["decisions"]["THESIS_DOWNGRADE_GATE"], "TRIGGERED")

    def test_f19_valuation_can_block_add_on(self) -> None:
        valuation = next(item for item in self.rules["rules"] if item["dimension"] == "VALUATION_STATE")
        self.assertNotEqual(valuation["calculated_state"], "SUPPORTED")
        self.assertEqual(self.rules["decisions"]["ADD_ON_CAPITAL_GATE"], "PARTIAL")

    def test_f20_smart_automatic_state_persists(self) -> None:
        second = build_smart_state({"smart": self.smart}, self.rules, ["E1"])
        self.assertEqual([item["id"] for item in self.smart["items"]], [item["id"] for item in second["items"]])
        self.assertTrue(all(not item["changed"] for item in second["items"]))

    def test_f21_smart_override_requires_reason(self) -> None:
        with self.assertRaisesRegex(DecisionRuleError, "SMART_OVERRIDE_REASON_REQUIRED"):
            apply_smart_override(self.smart["items"][0], "WATCH", None)
        changed = apply_smart_override(self.smart["items"][0], "WATCH", "Owner要求等待正式季報")
        self.assertTrue(changed["override"])
        self.assertTrue(changed["override_reason"])

    def test_f22_no_arbitrary_total_score(self) -> None:
        self.assertIsNone(self.rules["aggregate_numeric_score"])
        state = json.loads((self.root / "decision_state.json").read_text(encoding="utf-8"))
        self.assertIsNone(state["aggregate_numeric_score"])

    def test_f23_reader_report_has_estimate_disclosure(self) -> None:
        self.assertIn("ROIC持續性／資本強度敏感度", self.html)
        self.assertIn("不是官方同口徑ROIC", self.html)
        self.assertIn("核准的估值安全邊際門檻", self.html)
        self.assertNotIn("Owner", self.html)

    def test_f24_forward_ledger_is_complete(self) -> None:
        ledger = json.loads((self.root / "forward_model_ledger.json").read_text(encoding="utf-8"))
        required = {"model_id", "model_version", "input_observation_ids", "input_evidence_classes", "assumptions", "formula", "scenario", "result", "unit", "confidence", "limitations", "actionable"}
        self.assertGreaterEqual(len(ledger), 10)
        self.assertTrue(all(required <= set(item) for item in ledger))

    def test_f25_raw_production_hashes_unchanged(self) -> None:
        self.assertEqual(self.before, self.after)

    def test_f26_real_q2_forward_smoke_passes(self) -> None:
        self.assertEqual(self.result["state"], "REPORT_CANDIDATE_READY")
        self.assertEqual(self.result["owner_review_state"], "OWNER_REVIEW_REQUIRED")
        self.assertFalse(self.result["publication"])
        self.assertEqual(self.result["external_calls"], {"network": 0, "openai_api": 0, "canva": 0})
        self.assertTrue((self.root / "forward_enterprise_value_analytics.json").is_file())
        self.assertTrue((self.root / "enterprise_value_rule_engine.json").is_file())


if __name__ == "__main__":
    unittest.main()
