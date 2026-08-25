from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[4]
SRC = PACKAGE_ROOT / "modules" / "p1008_research_plugin" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from p1008_research_plugin.reporting.enterprise_value_owner_policy import load_policy_candidate
from p1008_research_plugin.reporting.enterprise_value_owner_policy_revision import (
    evaluate_fcf_recovery,
    evaluate_revised_add_on,
    evaluate_revised_capital_light,
    evaluate_revised_core_holding,
    evaluate_revised_downgrade,
    evaluate_revised_fcf,
    evaluate_revised_funding,
    evaluate_revised_per_share,
    evaluate_revised_valuation,
    evaluate_triggered_recovery,
    load_policy_revision,
    owner_revision_table,
    revision_runtime_state,
    select_funding_denominator,
)


CONTRACT = PACKAGE_ROOT / "contracts" / "p1008_report_production" / "v1.1" / "ENTERPRISE_VALUE_OWNER_POLICY_REVISION_V1.json"
SOURCE = SRC / "p1008_research_plugin" / "reporting" / "enterprise_value_owner_policy_revision.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class EnterpriseValueOwnerPolicyRevisionV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.revision = load_policy_revision(CONTRACT)
        cls.base = load_policy_candidate()
        cls.base_by_id = {x["threshold_id"]: x for x in cls.base["thresholds"]}

    def test_r01_only_eight_modify_items_receive_substantive_changes(self):
        self.assertEqual(len(self.revision["revised_items"]), 8)
        self.assertEqual({x["threshold_id"] for x in self.revision["revised_items"]}, {
            "EVOP-FCF-CONVERSION-01", "EVOP-WC-FUNDING-01", "EVOP-PER-SHARE-01",
            "EVOP-CAPITAL-LIGHT-01", "EVOP-VALUATION-01", "EVOP-CORE-HOLDING-01",
            "EVOP-ADD-ON-01", "EVOP-DOWNGRADE-01",
        })
        self.assertFalse(self.revision["policy_universe_regenerated"])

    def test_r02_five_approved_dimensions_semantically_frozen(self):
        self.assertEqual(len(self.revision["frozen_approved_items"]), 5)
        for item in self.revision["frozen_approved_items"]:
            canonical = json.dumps(self.base_by_id[item["threshold_id"]], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            self.assertEqual(hashlib.sha256(canonical).hexdigest().upper(), item["semantic_sha256"])

    def test_r03_roic_wacc_design_unchanged(self):
        item = self.base_by_id["EVOP-ROIC-SPREAD-01"]
        self.assertEqual(item["candidate_value_or_range"]["STRONG_VALUE_CREATION"], ">=5")
        self.assertEqual(next(x for x in self.revision["frozen_approved_items"] if x["threshold_id"] == item["threshold_id"])["owner_decision"], "APPROVED_DESIGN")

    def test_r04_current_balance_sheet_states_unchanged(self):
        self.assertEqual(self.base_by_id["EVOP-BALANCE-SHEET-01"]["candidate_value_or_range"], ["STRONG", "ADEQUATE", "WATCH", "STRESSED"])

    def test_r05_stress_resilience_states_unchanged(self):
        self.assertEqual(set(self.base_by_id["EVOP-STRESS-RESILIENCE-01"]["candidate_value_or_range"]), {"HIGH", "MODERATE", "LOW", "INCONCLUSIVE"})

    def test_r06_dilution_logic_unchanged(self):
        item = self.base_by_id["EVOP-DILUTION-01"]
        self.assertIn(">=2 adverse numerator spreads for >=2 periods", item["candidate_value_or_range"]["PERSISTENT_DILUTION_RISK"])

    def test_r07_smart_semantics_unchanged(self):
        item = self.base_by_id["EVOP-SMART-01"]
        self.assertIn("Evidence/Risk/Policy separation", item["formula"])

    def test_r08_three_negative_standalone_quarters_not_structural(self):
        result = evaluate_revised_fcf([{"standalone_fcf_negative": True, "comparison_basis": "STANDALONE_QUARTER"}] * 3)
        self.assertEqual(result["state"], "CYCLICAL_OR_TIMING_PRESSURE")
        self.assertFalse(result["standalone_negative_count_is_primary_rule"])

    def test_r09_fcf_is_same_season_ttm_fy_aware(self):
        observations = [
            {"comparison_basis": "SAME_SEASON", "period_basis": "H1", "cash_conversion_weak": True, "cash_flow_repair_failed": True, "cfo_conversion_deteriorating": True, "working_capital_outpaces_scale": True},
            {"comparison_basis": "TTM", "period_basis": "TTM", "cash_conversion_weak": True, "cash_flow_repair_failed": True},
        ]
        result = evaluate_revised_fcf(observations)
        self.assertEqual(result["state"], "STRUCTURAL_DETERIORATION")
        self.assertEqual(result["same_season_bases"], ["H1"])

    def test_r10_one_good_quarter_cannot_clear_structural_state(self):
        self.assertEqual(evaluate_fcf_recovery(prior_state="STRUCTURAL_DETERIORATION", ttm_or_fy_repaired=True, cfo_conversion_improved=True, continuing_structural_factors=0, confirming_observations=1), "STRUCTURAL_DETERIORATION")

    def test_r11_wc_25_not_owner_approved(self):
        result = evaluate_revised_funding(incremental_funding_requirement=30, immediately_available_liquidity=100, net_cash=None, normalized_cfo_capacity=None)
        self.assertFalse(result["WC_25_PERCENT_APPROVED"])

    def test_r12_wc_50_not_approved_hard_blocker(self):
        result = evaluate_revised_funding(incremental_funding_requirement=60, immediately_available_liquidity=100, net_cash=None, normalized_cfo_capacity=None)
        self.assertFalse(result["WC_50_PERCENT_HARD_BLOCKER_APPROVED"])
        self.assertFalse(result["hard_blocker"])

    def test_r13_funding_denominator_hierarchy(self):
        self.assertEqual(select_funding_denominator(immediately_available_liquidity=100, net_cash=200, normalized_cfo_capacity=300)["denominator"], "PRIMARY_IMMEDIATELY_AVAILABLE_LIQUIDITY")
        self.assertEqual(select_funding_denominator(immediately_available_liquidity=None, net_cash=200, normalized_cfo_capacity=300)["denominator"], "SECONDARY_NET_CASH")
        self.assertEqual(select_funding_denominator(immediately_available_liquidity=None, net_cash=None, normalized_cfo_capacity=300)["denominator"], "SUPPORTING_NORMALIZED_CFO_CAPACITY")

    def test_r14_negative_cfo_cannot_create_ratio(self):
        result = evaluate_revised_funding(incremental_funding_requirement=60, immediately_available_liquidity=None, net_cash=None, normalized_cfo_capacity=-5)
        self.assertEqual(result["status"], "CFO_CAPACITY_RATIO=CANNOT_EVALUATE")
        self.assertIsNone(result["ratio"])

    def test_r15_standalone_fcf_share_supporting_only(self):
        result = evaluate_revised_per_share([{"metric": "FCF_PER_SHARE", "period_basis": "STANDALONE_QUARTER", "compatible": True, "compounding_spread_pct": -20}], relevant_reporting_periods=3)
        self.assertEqual(result["state"], "INSUFFICIENT_DATA")
        self.assertEqual(result["standalone_quarterly_fcf_share_role"], "SUPPORTING_SIGNAL_ONLY")

    def test_r16_strong_compounding_needs_two_metrics_and_persistence(self):
        metrics = [
            {"metric": "EPS", "period_basis": "TTM", "compatible": True, "compounding_spread_pct": 3},
            {"metric": "BVPS", "period_basis": "YOY", "compatible": True, "compounding_spread_pct": 2},
        ]
        self.assertEqual(evaluate_revised_per_share(metrics, relevant_reporting_periods=2)["state"], "COMPOUNDING")
        self.assertNotEqual(evaluate_revised_per_share(metrics[:1], relevant_reporting_periods=2)["state"], "COMPOUNDING")

    def test_r17_capital_light_needs_four_evaluable_groups(self):
        groups = [{"factor_group": x, "data_completeness": "EVALUABLE", "trend_signal": "IMPROVING"} for x in ["RECEIVABLE_EFFICIENCY", "INVENTORY_EFFICIENCY", "CASH_CONVERSION"]]
        result = evaluate_revised_capital_light(groups, relevant_reporting_periods=2)
        self.assertEqual(result["state"], "INCONCLUSIVE")
        self.assertEqual(result["EVALUABLE_FACTOR_GROUPS"], 3)

    def test_r18_capital_light_alignment_and_persistence(self):
        groups = [
            {"factor_group": "RECEIVABLE_EFFICIENCY", "data_completeness": "EVALUABLE", "trend_signal": "IMPROVING"},
            {"factor_group": "INVENTORY_EFFICIENCY", "data_completeness": "EVALUABLE", "trend_signal": "IMPROVING"},
            {"factor_group": "SUPPLIER_FINANCING", "data_completeness": "EVALUABLE", "trend_signal": "IMPROVING"},
            {"factor_group": "CASH_CONVERSION", "data_completeness": "EVALUABLE", "trend_signal": "NEUTRAL"},
        ]
        self.assertEqual(evaluate_revised_capital_light(groups, relevant_reporting_periods=2)["state"], "IMPROVING")
        self.assertNotEqual(evaluate_revised_capital_light(groups, relevant_reporting_periods=1)["state"], "IMPROVING")

    def test_r19_percentiles_descriptive_only(self):
        result = evaluate_revised_valuation(valuation_context="REPORT_CUTOFF_PRICE", multiple_percentiles={"P/E": 30, "P/B": 70}, roic_support=True, roe_support=True, fcf_support=True, per_share_support=False)
        self.assertFalse(result["HISTORICAL_PERCENTILE_IS_POLICY_THRESHOLD"])

    def test_r20_percentile_not_margin_of_safety(self):
        result = evaluate_revised_valuation(valuation_context="REPORT_CUTOFF_PRICE", multiple_percentiles={"P/E": 30, "P/B": 70}, roic_support=True, roe_support=True, fcf_support=True, per_share_support=False)
        self.assertEqual(result["MARGIN_OF_SAFETY_POLICY_STATE"], "PENDING_OWNER_NUMERIC_CALIBRATION")

    def test_r21_current_valuation_requires_current_basis(self):
        result = evaluate_revised_valuation(valuation_context="PRE_EVENT_PRICE", multiple_percentiles={"P/E": 30, "P/B": 70}, roic_support=True, roe_support=True, fcf_support=True, per_share_support=True)
        self.assertEqual(result["CURRENT_VALUATION_DECISION_STATE"], "CANNOT_EVALUATE")

    def test_r22_core_holding_event_path(self):
        result = evaluate_revised_core_holding(confirmed_thesis_invalidating_event=True, event_evidence_quality="T0_DIRECT_OFFICIAL", event_material=True, adverse_actual_dimensions=0, persistent_observations=0)
        self.assertEqual((result["state"], result["path"]), ("REVIEW", "PATH_A_THESIS_INVALIDATING_EVENT"))

    def test_r23_gradual_downgrade_needs_multifactor_persistence(self):
        one = evaluate_revised_core_holding(confirmed_thesis_invalidating_event=False, event_evidence_quality="NONE", event_material=False, adverse_actual_dimensions=1, persistent_observations=2)
        two = evaluate_revised_core_holding(confirmed_thesis_invalidating_event=False, event_evidence_quality="NONE", event_material=False, adverse_actual_dimensions=2, persistent_observations=2)
        self.assertEqual(one["state"], "REVIEW")
        self.assertEqual(two["state"], "降級")

    def _add_on(self, **updates):
        args = dict(thesis_downgrade_state="尚未觸發", current_balance_sheet_state="ADEQUATE", valuation_context="REPORT_CUTOFF_PRICE", owner_hard_blocker_active=False, core_support={"ROIC": "VALUE_CREATION", "FCF": "SUPPORTED", "WORKING_CAPITAL": "MANAGEABLE", "PER_SHARE": "COMPOUNDING"}, secondary_confidence={"STRESS_RESILIENCE": "HIGH", "CAPITAL_LIGHT": "IMPROVING"})
        args.update(updates)
        return evaluate_revised_add_on(**args)

    def test_r24_equal_weight_six_of_seven_removed(self):
        self.assertFalse(self._add_on()["equal_weight_6_of_7_rule"])

    def test_r25_mandatory_add_on_gates_enforced(self):
        self.assertEqual(self._add_on(current_balance_sheet_state="STRESSED")["state"], "尚未通過")

    def test_r26_secondary_cannot_override_mandatory(self):
        result = self._add_on(valuation_context="PRE_EVENT_PRICE", secondary_confidence={"STRESS_RESILIENCE": "HIGH", "CAPITAL_LIGHT": "IMPROVING"})
        self.assertEqual(result["state"], "尚未通過")
        self.assertFalse(result["secondary_can_override_failed_mandatory_gate"])

    def test_r27_partial_is_not_trading_action(self):
        result = self._add_on(core_support={"ROIC": "NARROW_SPREAD", "FCF": "SUPPORTED", "WORKING_CAPITAL": "MANAGEABLE", "PER_SHARE": "COMPOUNDING"})
        self.assertEqual(result["state"], "PARTIAL")
        self.assertFalse(result["partial_is_trading_instruction"])
        self.assertIsNone(result["trading_action"])

    def _downgrade(self, **updates):
        args = dict(adverse_actual_items=0, adverse_t2_items=0, independent_corroborators=0, t4_scenario_flags=0, persistent_observations=0, confirmed_thesis_invalidating_event=False, high_quality_event_evidence=False)
        args.update(updates)
        return evaluate_revised_downgrade(**args)

    def test_r28_t4_alone_cannot_watch(self):
        result = self._downgrade(t4_scenario_flags=1)
        self.assertEqual(result["state"], "尚未觸發")
        self.assertTrue(result["SCENARIO_RISK_FLAG"])
        self.assertFalse(result["T4_ONLY_CAN_TRIGGER_WATCH"])

    def test_r29_t4_alone_cannot_trigger(self):
        result = self._downgrade(t4_scenario_flags=3, persistent_observations=3)
        self.assertNotEqual(result["state"], "TRIGGERED")
        self.assertFalse(result["T4_ONLY_CAN_TRIGGER_DOWNGRADE"])

    def test_r30_watch_requires_adverse_evidence(self):
        self.assertEqual(self._downgrade()["state"], "尚未觸發")
        self.assertEqual(self._downgrade(adverse_actual_items=1)["state"], "WATCH")

    def test_r31_triggered_recovery_hysteresis(self):
        self.assertEqual(evaluate_triggered_recovery(prior_state="TRIGGERED", confirming_observations=1, thesis_invalidating_event_resolved=True, adverse_actual_items=0), "TRIGGERED")
        self.assertEqual(evaluate_triggered_recovery(prior_state="TRIGGERED", confirming_observations=2, thesis_invalidating_event_resolved=True, adverse_actual_items=0), "WATCH")

    def test_r32_all_revised_items_pending_owner_review(self):
        self.assertTrue(all(x["owner_decision"] == "REVISION_PENDING_OWNER_REVIEW" for x in self.revision["revised_items"]))
        self.assertTrue(all(x["Owner Decision"] == "PENDING_REVIEW" for x in owner_revision_table(self.revision)))

    def test_r33_no_owner_approval_artifact(self):
        self.assertFalse(self.revision["owner_approval_artifact_created"])
        self.assertFalse(revision_runtime_state(self.revision)["OWNER_APPROVAL_ARTIFACT_CREATED"])

    def test_r34_policy_inactive(self):
        state = revision_runtime_state(self.revision)
        self.assertEqual(self.revision["activation_state"], "NOT_ACTIVE")
        self.assertFalse(state["OWNER_POLICY_ACTIVATED"])
        self.assertFalse(state["READY_FOR_POLICY_ACTIVATION"])

    def test_r35_no_war_report_production(self):
        self.assertEqual(self.revision["formal_report_production_runs"], 0)
        self.assertNotIn("run_war_report_production", SOURCE.read_text(encoding="utf-8"))

    def test_r36_no_launcher_changes(self):
        self.assertNotIn("launcher", SOURCE.read_text(encoding="utf-8").lower())
        self.assertNotIn("launcher", CONTRACT.read_text(encoding="utf-8").lower())

    def test_r37_no_external_calls(self):
        self.assertEqual(self.revision["external_calls"], {"network_requests": 0, "openai_api_calls": 0, "canva_calls": 0})

    def test_r38_raw_production_hashes_unchanged(self):
        expected = {
            "data/CSV_AUTHORITY_MANIFEST.json": "C6FF94A1FB2C9C877D7620184BDDD9A6270355ED833318638C3D87EB634A5398",
            "data/2317_master_v9.csv": "0BB2FEC6FA3035AC642738BC12EA6959C81C8A79D5221E694BF780427051CF79",
            "data/2317_daily_price.csv": "1C32081288731725CBA000C1CCC5144A24DD2A6F9A15A2964F930D8953839C6D",
            "data/2317_daily_market_activity.csv": "021244A6E25894DB93C2223CA493EBA0BD72610D7CE06D4B95BCB5FBFD82D4BB",
            "data/2317_cash_flow_authority.csv": "082ECA44A96A06F7DAE10DD33CBAF77C75DABA9B1B4DEA27B5B930F8CE8CD95C",
            "data/macro_snapshot.csv": "30A4755E87CECD4230FA8A521DF485385A89AC2A4E1E2B5726CBFD14AB96C86F",
            "data/macro_event_observations.csv": "76B93F8932BA606390D44D68BD0D57D0BE7CB5D1D1364183F192A062D8B94BF2",
            "data/fx_trend_observations.csv": "BFEC53845C68D689D20CC29972550279E3A4AE8D473816EFDB0855FF0DD091CD",
            "rules/RULE_STATUS_MANIFEST.json": "054DA1FDAF0C75BB27B56DF45B96F1CC1720558D44C700F1AB70AB0280A2FE5C",
        }
        for rel, digest in expected.items():
            self.assertEqual(sha(PACKAGE_ROOT / rel), digest, rel)
        sqlite = Path(os.environ["LOCALAPPDATA"]) / "P1008" / "data" / "warroom.sqlite3"
        self.assertEqual(sha(sqlite), "B365CB5540BDEDD2E0E0EF924DC9DFA2B4FD6F7954904BCBA5194DA0966BB832")


if __name__ == "__main__":
    unittest.main()
