from __future__ import annotations

import hashlib
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[4]
SRC = PACKAGE_ROOT / "modules" / "p1008_research_plugin" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from p1008_research_plugin.reporting.enterprise_value_rule_engine import (  # noqa: E402
    build_decision_state,
    build_smart_state,
    evaluate_enterprise_value_rules,
)
from p1008_research_plugin.analysis.quarterly_analysis_builder import ttm_eps_valuation  # noqa: E402
from p1008_research_plugin.reporting.forward_enterprise_value_analytics import (  # noqa: E402
    build_estimated_invested_capital,
    build_transmission_layer,
    capital_light_proxy,
    historical_valuation_context,
    presentation_value,
    roic_sensitivity,
    working_capital_stress,
)
from p1008_research_plugin.reporting.report_contracts import ChartData, ChartSeries  # noqa: E402
from p1008_research_plugin.reporting.report_renderer_formal import FormalPreviewRenderer  # noqa: E402
from p1008_research_plugin.reporting.war_report_production_runtime import _indexed, _reader_text  # noqa: E402


CONFIG = json.loads((PACKAGE_ROOT / "modules/p1008_research_plugin/config/quarterly_earnings/FY2026_Q2.json").read_text(encoding="utf-8"))
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


def bridge():
    b = CONFIG["balanceSheet"]
    return {
        "periods": ["2026Q1", "2026Q2"],
        "accountsReceivableMillionTwd": [b["q1"]["accountsReceivableNetMillionTwd"], b["accountsReceivableNetMillionTwd"]],
        "inventoryMillionTwd": [b["q1"]["inventoryMillionTwd"], b["inventoryMillionTwd"]],
        "propertyPlantEquipmentMillionTwd": [b["q1"]["propertyPlantEquipmentMillionTwd"], b["propertyPlantEquipmentMillionTwd"]],
        "accountsPayableMillionTwd": [b["q1"]["accountsPayableMillionTwd"], b["accountsPayableMillionTwd"]],
        "cashTreatment": "EXCLUDED_FROM_OPERATING_INVESTED_CAPITAL",
    }


def roic_model():
    return roic_sensitivity(
        operating_profit="94803", pretax_income="94866", income_tax="24810",
        latest_actual_roic_pct="12.57", input_ids=["OFFICIAL_Q2"], invested_capital_bridge=bridge(),
    )


def forward_stub():
    return {
        "roic_sensitivity": roic_model(),
        "capital_light_proxy": {"signal": "INCONCLUSIVE"},
        "dilution_sensitivity": {},
        "working_capital_stress": {"scenarios": [
            {"scenario": "BASE", "result": {"funding_need_indication": "0"}},
            {"scenario": "RESEARCH_STRESS_A", "result": {"funding_need_indication": "100"}},
            {"scenario": "RESEARCH_STRESS_B", "result": {"funding_need_indication": "200"}},
        ]},
    }


class ForwardModelAnalyticalQAV1Tests(unittest.TestCase):
    def test_qa01_current_roic_anchoring_detected(self):
        audit = roic_model()["anchoring_audit"]
        self.assertTrue(audit["confirmed"])
        self.assertEqual(audit["scenario_multipliers"], ["0.85", "1.00", "1.15"])

    def test_qa02_anchor_not_independent_estimate(self):
        model = roic_model()
        self.assertTrue(model["persistence_sensitivity"]["not_independent_q2_estimate"])
        self.assertFalse(model["anchoring_audit"]["independent_estimate_claim_allowed"])

    def test_qa03_transparent_invested_capital_components(self):
        result = roic_model()["independent_q2_invested_capital"]
        self.assertTrue(result["available"])
        self.assertEqual(result["endpoint_components"][0]["partial_operating_invested_capital"], "1615269")
        self.assertEqual(result["endpoint_components"][1]["partial_operating_invested_capital"], "1804642")

    def test_qa04_missing_ic_reclassified_not_fabricated(self):
        result = build_estimated_invested_capital(bridge=None, quarterly_nopat=Decimal("1"), input_ids=[])
        self.assertFalse(result["available"])
        self.assertTrue(result["reclassified"])

    def test_qa05_quarterly_and_annualized_roic_separate(self):
        result = roic_model()["independent_q2_invested_capital"]
        self.assertNotEqual(result["quarterly_roic_pct"], result["annualized_quarterly_roic_sensitivity_pct"])
        self.assertFalse(result["annualized_is_ttm"])

    def test_qa06_q4_2025_eps_canonical_lineage(self):
        correction = CONFIG["historicalEpsCorrections"]["2025Q4"]
        self.assertEqual(correction["basicEpsTwd"], "3.23")
        self.assertEqual(correction["sourceDocumentSha256"], "91E4994341856DF0E1985DD87704DBE17E1E35CA66FF730CE8CA833CA7766EC0")
        self.assertIn("honhai.com", correction["sourceLocator"])

    def test_qa07_ttm_eps_and_pe_recomputed(self):
        result = ttm_eps_valuation(price=Decimal("263"), q3_2025=Decimal("4.15"), q4_2025=Decimal("3.23"), q1_2026=Decimal("3.56"), q2_2026=Decimal("4.27"))
        self.assertEqual(result["ttm_eps"], Decimal("15.21"))
        self.assertEqual(result["ttm_pe"], Decimal("17.29"))

    def test_qa08_h2_2025_eps_recomputed(self):
        result = ttm_eps_valuation(price=Decimal("263"), q3_2025=Decimal("4.15"), q4_2025=Decimal("3.23"), q1_2026=Decimal("3.56"), q2_2026=Decimal("4.27"))
        self.assertEqual(result["h2_2025_eps"], Decimal("7.38"))

    def test_qa09_price_label_is_event_time_aware(self):
        body = (PACKAGE_ROOT / "modules/p1008_research_plugin/src/p1008_research_plugin/reporting/report_builder.py").read_text(encoding="utf-8")
        self.assertIn('valuation["price"]["readerLabel"]', body)
        self.assertIn("財報公布後報告截止日", body)
        self.assertNotIn('f"現價{valuation', body)

    def test_qa10_price_date_preserved(self):
        contract = json.loads((PACKAGE_ROOT / "contracts/p1008_report_production/v1.1/P1008_FORWARD_MODEL_ANALYTICAL_QA_CONTRACT_V1.json").read_text(encoding="utf-8"))
        self.assertIn("price_date", contract["valuation_time_basis"]["required_fields"])

    def test_qa11_actual_balance_state_ignores_t4_funding(self):
        result = evaluate_enterprise_value_rules(forward=forward_stub(), fcf_classification="CYCLICAL_OR_TIMING_PRESSURE", operating_profit_supported=True, balance_sheet_status="STABLE", valuation_support="DESCRIPTIVE_ONLY", evidence_ids=["E"])
        states = {r["dimension"]: r["calculated_state"] for r in result["rules"]}
        self.assertEqual(states["CURRENT_BALANCE_SHEET_STATE"], "SUPPORTED")

    def test_qa12_stress_resilience_separate(self):
        result = evaluate_enterprise_value_rules(forward=forward_stub(), fcf_classification="CYCLICAL_OR_TIMING_PRESSURE", operating_profit_supported=True, balance_sheet_status="STABLE", valuation_support="DESCRIPTIVE_ONLY", evidence_ids=["E"])
        states = {r["dimension"]: r["calculated_state"] for r in result["rules"]}
        self.assertEqual(states["STRESS_RESILIENCE_STATE"], "LOW_RESILIENCE")

    def test_qa13_wc_bridge_sums(self):
        result = working_capital_stress(revenue=900, cogs=600, baseline_cfo=50, capex=20, delta_dso=5, delta_dio=10, delta_dpo=2)
        total = Decimal(result["delta_ar_cash_requirement"]) + Decimal(result["delta_inventory_cash_requirement"]) - Decimal(result["delta_ap_funding_relief"])
        self.assertEqual(total, Decimal(result["net_incremental_working_capital_requirement"]))

    def test_qa14_wc_day_basis_is_quarterly_90(self):
        result = working_capital_stress(revenue=900, cogs=600, baseline_cfo=50, capex=20, delta_dso=1, delta_dio=1, delta_dpo=1)
        self.assertEqual(result["day_basis"], "90")
        self.assertIn("QUARTERLY", result["day_basis_interpretation"])

    def test_qa15_capital_light_uses_five_groups(self):
        wc = {"accountsReceivableMillionTwd": [100, 110], "inventoryMillionTwd": [100, 90], "accountsPayableMillionTwd": [80, 85], "cashConversionCycleDays": [48, 42], "accountsReceivableDays": [51, 46], "inventoryDays": [54, 50], "accountsPayableDays": [57, 54]}
        result = capital_light_proxy(periods=["Q1", "Q2"], revenue=[1000, 1200], wc=wc, cfo=-10, fcf=-20, capex=30)
        self.assertEqual(len(result["factor_groups"]), 5)
        self.assertNotIn("raw_vote_count", result)

    def test_qa16_unavailable_prior_is_not_deteriorating_trend(self):
        wc = {"accountsReceivableMillionTwd": [100, 110], "inventoryMillionTwd": [100, 90], "accountsPayableMillionTwd": [80, 85], "cashConversionCycleDays": [48, 42], "accountsReceivableDays": [51, 46], "inventoryDays": [54, 50], "accountsPayableDays": [57, 54]}
        result = capital_light_proxy(periods=["Q1", "Q2"], revenue=[1000, 1200], wc=wc, cfo=-10, fcf=-20, capex=30)
        cash = next(item for item in result["factor_groups"] if item["factor_group"] == "CASH_CONVERSION")
        self.assertEqual(cash["level_signal"], "NEGATIVE")
        self.assertNotEqual(cash["trend_signal"], "DETERIORATING")

    def test_qa17_cumulative_cashflow_is_not_continuous_line(self):
        source = (PACKAGE_ROOT / "modules/p1008_research_plugin/src/p1008_research_plugin/reporting/war_report_production_runtime.py").read_text(encoding="utf-8")
        self.assertIn('visualization_type="EVIDENCE_TABLE"', source)

    def test_qa18_stale_cumulative_narrative_rejected(self):
        source = (PACKAGE_ROOT / "modules/p1008_research_plugin/src/p1008_research_plugin/reporting/war_report_production_runtime.py").read_text(encoding="utf-8")
        self.assertNotIn("目前只有2026H1具本機可驗證官方累計資料", source)
        self.assertIn("2025M9", source)

    def test_qa19_evidence_and_risk_states_distinct(self):
        rule = evaluate_enterprise_value_rules(forward=forward_stub(), fcf_classification="STRUCTURAL_RISK_NOT_RULED_OUT", operating_profit_supported=True, balance_sheet_status="STABLE", valuation_support="DESCRIPTIVE_ONLY", evidence_ids=["E"])["rules"][1]
        self.assertIn(rule["evidence_state"], {"SUPPORTED", "PARTIAL", "UNAVAILABLE"})
        self.assertIn(rule["risk_state"], {"NORMAL", "WATCH", "TRIGGERED"})

    def test_qa20_eps_metric_not_per_share_thesis(self):
        rules = evaluate_enterprise_value_rules(forward=forward_stub(), fcf_classification="CYCLICAL_OR_TIMING_PRESSURE", operating_profit_supported=True, balance_sheet_status="STABLE", valuation_support="DESCRIPTIVE_ONLY", evidence_ids=["E"])
        smart = build_smart_state(None, rules, ["E"])["items"]
        eps = next(item for item in smart if item["metric_or_thesis"] == "EPS")
        thesis = next(item for item in smart if item["metric_or_thesis"] == "PER_SHARE_VALUE_COMPOUNDING")
        self.assertEqual(eps["evaluation_type"], "METRIC_AVAILABILITY")
        self.assertEqual(thesis["evaluation_type"], "THESIS")

    def test_qa21_threshold_decision_is_provisional(self):
        rules = evaluate_enterprise_value_rules(forward=forward_stub(), fcf_classification="CYCLICAL_OR_TIMING_PRESSURE", operating_profit_supported=True, balance_sheet_status="STABLE", valuation_support="DESCRIPTIVE_ONLY", evidence_ids=["E"])
        decision = build_decision_state(None, rules, ["E"])
        self.assertTrue(all("PROVISIONAL_ANALYTICAL_STATE" in item for item in decision["items"]))

    def test_qa22_owner_policy_pending(self):
        rules = evaluate_enterprise_value_rules(forward=forward_stub(), fcf_classification="CYCLICAL_OR_TIMING_PRESSURE", operating_profit_supported=True, balance_sheet_status="STABLE", valuation_support="DESCRIPTIVE_ONLY", evidence_ids=["E"])
        decision = build_decision_state(None, rules, ["E"])
        self.assertTrue(all(item["OWNER_POLICY_STATE"] == "PENDING_POLICY_CALIBRATION" for item in decision["items"]))

    def test_qa23_reader_blocks_p1008(self):
        self.assertNotIn("P1008", _reader_text("P1008 投資判讀"))

    def test_qa24_reader_blocks_owner_review_required(self):
        self.assertNotIn("OWNER REVIEW REQUIRED", _reader_text("OWNER REVIEW REQUIRED"))

    def test_qa25_reader_blocks_raw_tier_codes(self):
        self.assertNotIn("T4_MODEL_SCENARIO", _reader_text("T4_MODEL_SCENARIO"))

    def test_qa26_reader_blocks_authority_ids(self):
        self.assertNotIn("AUTH-MASTER-ABC", _reader_text("AUTH-MASTER-ABC"))

    def test_qa27_reader_blocks_raw_internal_enums(self):
        text = _reader_text("CORE_HOLDING_THESIS ADD_ON_CAPITAL_GATE THESIS_DOWNGRADE_GATE")
        self.assertNotIn("CORE_HOLDING_THESIS", text)
        self.assertNotIn("ADD_ON_CAPITAL_GATE", text)

    def test_qa28_presentation_precision(self):
        self.assertEqual(presentation_value("1893653.293853452982", "TWD_MILLION"), "1893653")
        self.assertEqual(presentation_value("0.548414541544", "RATIO_PCT"), "0.55")
        self.assertEqual(FormalPreviewRenderer._display("0.548414541544"), "0.548")

    def test_qa29_pb_denominator_period_required(self):
        contract = json.loads((PACKAGE_ROOT / "contracts/p1008_report_production/v1.1/P1008_FORWARD_MODEL_ANALYTICAL_QA_CONTRACT_V1.json").read_text(encoding="utf-8"))
        self.assertTrue(contract["valuation"]["pb_denominator_period_required"])

    def test_qa30_ps_has_valid_estimated_basis(self):
        price, shares, revenue = Decimal("263"), Decimal("59974") / Decimal("4.27"), Decimal("9310748")
        ps = price * shares / revenue
        self.assertEqual(ps.quantize(Decimal("0.01")), Decimal("0.40"))

    def test_qa31_historical_percentile_has_no_lookahead(self):
        baseline = {"observations": [{"metric_id": "PB", "period": "2025Q4", "value": "1"}, {"metric_id": "PB", "period": "2026Q1", "value": "2"}, {"metric_id": "PB", "period": "2026Q3", "value": "99"}]}
        result = historical_valuation_context(baseline, metric_id="PB", current_value="1.5", cutoff_period="2026Q2")
        self.assertEqual(result["observation_count"], 2)
        self.assertEqual(result["look_ahead_observations"], 0)

    def test_qa32_chapter6_transmission_schema(self):
        rows = build_transmission_layer()
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(set(row) == {"external_driver", "first_order_financial_effect", "second_order_effect", "fcf_or_roic_transmission", "current_evidence", "unresolved_variable"} for row in rows))

    def test_qa33_consignment_reader_term(self):
        self.assertIn("Consignment（客供料）", _reader_text("Consignment交易模式"))

    def test_qa34_full_history_count_unchanged(self):
        artifacts = sorted((PACKAGE_ROOT / "runtime/phaseb1_test_scratch").glob("**/historical_kpi_baseline.json"))
        self.assertTrue(artifacts)
        baseline = json.loads(artifacts[-1].read_text(encoding="utf-8"))
        self.assertEqual(baseline["observation_count"], 145)

    def test_qa35_label_density_without_point_deletion(self):
        labels = [f"202{i // 4}Q{i % 4 + 1}" for i in range(20)]
        chart = ChartData(chart_id="density", title_zh="完整歷史", decision_question="標籤是否精簡？", period="20季", source_evidence_ids=["AUTH-MASTER-X"], labels=labels, series=[ChartSeries(label_zh="指數", unit="首期=100", values=[str(i + 1) for i in range(20)])], commentary_zh=["保留全部資料點。"], observation_zh="完整", interpretation_zh="精簡標籤", p1008_implication_zh="研究", signal="YELLOW", actionable=False)
        rendered = FormalPreviewRenderer()._line_svg(chart)
        self.assertIn('data-point-count="20"', rendered)
        self.assertLess(len(FormalPreviewRenderer.visible_label_indexes(labels)), 20)

    def test_qa36_protected_source_hashes_unchanged(self):
        for relative, expected in PROTECTED.items():
            actual = hashlib.sha256((PACKAGE_ROOT / relative).read_bytes()).hexdigest().upper()
            self.assertEqual(actual, expected, relative)


if __name__ == "__main__":
    unittest.main()
