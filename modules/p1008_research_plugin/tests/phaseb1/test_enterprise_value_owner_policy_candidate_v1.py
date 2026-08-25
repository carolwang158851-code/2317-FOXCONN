from __future__ import annotations

import hashlib
import sys
import unittest
from decimal import Decimal
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[4]
SRC = PACKAGE_ROOT / "modules" / "p1008_research_plugin" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from p1008_research_plugin.reporting.enterprise_value_owner_policy import (  # noqa: E402
    OwnerPolicyCandidateError,
    candidate_runtime_state,
    evaluate_add_on_gate,
    evaluate_balance_sheet,
    evaluate_capital_light,
    evaluate_dilution,
    evaluate_fcf_conversion,
    evaluate_per_share_compounding,
    evaluate_roic_spread,
    evaluate_thesis_downgrade,
    evaluate_valuation,
    evaluate_working_capital_funding,
    hysteresis_transition,
    load_policy_candidate,
    owner_decision_table,
    per_share_compounding_spread,
)


PROTECTED = {
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


def five_factors(state: str) -> list[dict[str, str]]:
    return [
        {"factor_group": group, "level_signal": "NEUTRAL", "trend_signal": state}
        for group in (
            "RECEIVABLE_EFFICIENCY", "INVENTORY_EFFICIENCY",
            "SUPPLIER_FINANCING", "CASH_CONVERSION", "CAPITAL_INTENSITY",
        )
    ]


class EnterpriseValueOwnerPolicyCandidateV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = load_policy_candidate()

    def test_t01_no_threshold_auto_approved(self):
        self.assertTrue(all(item["owner_approval_state"] == "PENDING" for item in self.policy["thresholds"]))

    def test_t02_calibration_does_not_activate_policy(self):
        state = candidate_runtime_state(self.policy)
        self.assertFalse(state["OWNER_POLICY_ACTIVATED"])
        self.assertEqual(state["DECISION_AUTHORITY"], "NOT_ACTIVE")

    def test_t03_missing_wacc_never_becomes_zero(self):
        result = evaluate_roic_spread(roic_pct="12.57", wacc_pct=None, evidence_class="T0_DIRECT_OFFICIAL")
        self.assertEqual(result["state"], "PENDING_REQUIRED_INPUT")
        self.assertIsNone(result["wacc_used"])

    def test_t04_estimated_roic_cannot_trigger_severe_downgrade(self):
        result = evaluate_roic_spread(roic_pct="5", wacc_pct="8", evidence_class="T2_ESTIMATED_DERIVED", partial_estimate=True)
        self.assertEqual(result["state"], "WATCH")
        self.assertFalse(result["severe_downgrade_allowed"])

    def test_t05_one_negative_fcf_is_not_structural(self):
        result = evaluate_fcf_conversion([{"fcf_negative": True, "cfo_weak": True}])
        self.assertEqual(result["state"], "CYCLICAL_OR_TIMING_PRESSURE")
        self.assertFalse(result["single_negative_period_structural"])

    def test_t06_structural_fcf_requires_persistence_and_corroboration(self):
        two = evaluate_fcf_conversion([{"fcf_negative": True}, {"fcf_negative": True}])
        three = evaluate_fcf_conversion([
            {"fcf_negative": True, "cfo_weak": True},
            {"fcf_negative": True, "ccc_worsening": True},
            {"fcf_negative": True},
        ])
        self.assertNotEqual(two["state"], "STRUCTURAL_DETERIORATION")
        self.assertEqual(three["state"], "STRUCTURAL_DETERIORATION")

    def test_t07_t4_stress_cannot_downgrade_actual_balance_sheet(self):
        states = evaluate_balance_sheet(actual_state="STRONG", stress_resilience_state="LOW")
        self.assertEqual(states["CURRENT_BALANCE_SHEET_STATE"], "STRONG")
        self.assertEqual(states["STRESS_RESILIENCE_STATE"], "LOW")

    def test_t08_per_share_uses_exact_ratio_formula(self):
        result = per_share_compounding_spread("10", "5")
        self.assertEqual(result.quantize(Decimal("0.0001")), Decimal("4.7619"))
        self.assertNotEqual(result, Decimal("5"))

    def test_t09_share_growth_alone_is_not_dilution_failure(self):
        result = evaluate_dilution(share_growth_pct="3", per_share_states=["COMPOUNDING", "NEUTRAL", "COMPOUNDING"], consecutive_periods=2)
        self.assertEqual(result["state"], "NO_DILUTION_FAILURE")
        self.assertFalse(result["share_growth_alone_is_failure"])

    def test_t10_capital_light_uses_five_factor_groups(self):
        result = evaluate_capital_light(five_factors("IMPROVING"), consecutive_periods=2)
        self.assertEqual(result["factor_group_count"], 5)
        self.assertIsNone(result["raw_metric_vote_count"])

    def test_t11_pre_event_valuation_cannot_activate_add_on(self):
        result = evaluate_valuation(valuation_context="PRE_EVENT_PRICE", multiple_percentiles={"PE": 10, "PB": 20}, roic_support=True, fcf_support=True, per_share_support=True)
        self.assertFalse(result["current_add_on_eligible"])
        self.assertEqual(result["state"], "INCONCLUSIVE")

    def test_t12_ps_alone_cannot_determine_valuation(self):
        result = evaluate_valuation(valuation_context="POST_EVENT_PRICE", multiple_percentiles={"PS": 10}, roic_support=True, fcf_support=True, per_share_support=True)
        self.assertEqual(result["state"], "INCONCLUSIVE")

    def test_t13_add_on_gate_is_multifactor(self):
        supports = {key: True for key in ("ROIC", "FCF", "WORKING_CAPITAL", "CURRENT_BALANCE_SHEET", "STRESS_RESILIENCE", "PER_SHARE", "VALUATION")}
        supports["FCF"] = False
        result = evaluate_add_on_gate(supports=supports, hard_blockers=[], valuation_context="POST_EVENT_PRICE")
        self.assertEqual(result["analytical_state"], "通過")
        self.assertEqual(len(supports), 7)

    def test_t14_partial_is_not_a_trading_action(self):
        supports = {key: key in {"ROIC", "FCF", "CURRENT_BALANCE_SHEET"} for key in ("ROIC", "FCF", "WORKING_CAPITAL", "CURRENT_BALANCE_SHEET", "STRESS_RESILIENCE", "PER_SHARE", "VALUATION")}
        result = evaluate_add_on_gate(supports=supports, hard_blockers=[], valuation_context="POST_EVENT_PRICE")
        self.assertEqual(result["analytical_state"], "PARTIAL")
        self.assertFalse(result["partial_is_trading_instruction"])
        self.assertIsNone(result["trading_action"])

    def test_t15_downgrade_watch_means_adverse_evidence(self):
        result = evaluate_thesis_downgrade(adverse_actual_factors=1, t4_only_factors=0, consecutive_periods=1, hard_blocker_confirmed=False)
        self.assertEqual(result["state"], "WATCH")

    def test_t16_triggered_is_stronger_than_watch(self):
        watch = evaluate_thesis_downgrade(adverse_actual_factors=1, t4_only_factors=0, consecutive_periods=1, hard_blocker_confirmed=False)
        triggered = evaluate_thesis_downgrade(adverse_actual_factors=2, t4_only_factors=0, consecutive_periods=2, hard_blocker_confirmed=True)
        self.assertEqual(watch["state"], "WATCH")
        self.assertEqual(triggered["state"], "TRIGGERED")

    def test_t17_hysteresis_prevents_immediate_flapping(self):
        state = hysteresis_transition(current_state="TRIGGERED", proposed_state="尚未觸發", consecutive_confirmations=1, entry_required=1, recovery_required=2)
        self.assertEqual(state, "TRIGGERED")

    def test_t18_missing_inputs_are_explicit(self):
        funding = evaluate_working_capital_funding(incremental_funding_need=100, available_liquidity=None, net_cash=200, cfo_capacity=None)
        per_share = evaluate_per_share_compounding(numerator_growth_pct=None, share_growth_pct="1", compatible_denominator=True, consecutive_periods=2)
        self.assertEqual(funding["funding_hard_blocker"], "PENDING_REQUIRED_INPUT")
        self.assertEqual(per_share["state"], "INSUFFICIENT_DATA")

    def test_t19_hard_blockers_and_soft_signals_are_distinct(self):
        by_id = {item["threshold_id"]: item for item in self.policy["thresholds"]}
        self.assertTrue(by_id["EVOP-WC-FUNDING-01"]["hard_blocker"])
        self.assertFalse(by_id["EVOP-STRESS-RESILIENCE-01"]["hard_blocker"])
        self.assertFalse(by_id["EVOP-VALUATION-01"]["hard_blocker"])

    def test_t20_t4_alone_cannot_trigger_thesis_impairment(self):
        result = evaluate_thesis_downgrade(adverse_actual_factors=0, t4_only_factors=5, consecutive_periods=4, hard_blocker_confirmed=False)
        self.assertEqual(result["state"], "WATCH")
        self.assertFalse(result["t4_alone_can_trigger"])

    def test_t21_owner_table_initializes_pending(self):
        table = owner_decision_table(self.policy)
        self.assertEqual(len(table), len(self.policy["thresholds"]))
        self.assertTrue(all(row["Owner decision"] == "PENDING" for row in table))

    def test_t22_activation_requires_later_explicit_artifact(self):
        with self.assertRaisesRegex(OwnerPolicyCandidateError, "ACTIVATION_OUT_OF_SCOPE"):
            candidate_runtime_state(self.policy, approval_artifact={"accepted_by": "Owner"})

    def test_t23_no_report_production_is_invoked(self):
        source = (SRC / "p1008_research_plugin/reporting/enterprise_value_owner_policy.py").read_text(encoding="utf-8")
        self.assertNotIn("run_war_report_production", source)
        self.assertNotIn("REPORT_CANDIDATE_READY", source)
        self.assertNotIn("war_report_candidate.html", source)

    def test_t24_raw_production_hashes_unchanged(self):
        for relative, expected in PROTECTED.items():
            actual = hashlib.sha256((PACKAGE_ROOT / relative).read_bytes()).hexdigest().upper()
            self.assertEqual(actual, expected, relative)


if __name__ == "__main__":
    unittest.main()
