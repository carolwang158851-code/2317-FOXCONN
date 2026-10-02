import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import p1008_scoring_state as scoring


class ScoringStateTests(unittest.TestCase):
    def setUp(self):
        self.state = scoring.build_scoring_state(ROOT)

    def test_current_quarter_is_not_replaced_by_valid_historical_row(self):
        self.assertEqual("2026Q2", self.state["current_period"])
        self.assertEqual("INSUFFICIENT_DATA", self.state["current_source_rows"]["master"]["ROIC_Status"])
        self.assertIsNone(self.state["research_kpi_values"]["dimension_models"]["fund"])
        self.assertIsNone(self.state["research_kpi_values"]["dimension_models"]["chip"])

    def test_78_is_retained_only_as_period_labelled_historical_research(self):
        item = self.state["research_kpi_values"]["historical_quality"]
        self.assertEqual(78, item["value"])
        self.assertEqual("2026Q1", item["period"])
        self.assertFalse(item["current"])
        self.assertFalse(item["formal_scoring_eligible"])

    def test_data_coverage_is_not_formal_scoring_coverage(self):
        self.assertEqual(2, self.state["data_coverage"]["research_model_count"])
        self.assertEqual(40, self.state["data_coverage"]["percent"])
        self.assertEqual(0, self.state["formal_scoring_coverage"]["eligible_count"])
        self.assertEqual(5, self.state["formal_scoring_coverage"]["dimension_count"])

    def test_six_monitors_do_not_create_a_sixth_investment_dimension(self):
        self.assertEqual({"score_count": 0, "monitor_count": 6, "ready": False,
                          "meaning": "SIX_MONITORING_PANELS_NOT_SIX_INVESTMENT_DIMENSIONS"}, self.state["ic_readiness"])
        self.assertEqual(5, len(self.state["formal_dimension_eligibility"]))

    def test_unactivated_035_never_produces_formal_contribution(self):
        fund = self.state["dimensions"][0]
        self.assertEqual(.35, fund["weight"])
        self.assertEqual("LEGACY_REFERENCE_NOT_ACTIVATED", fund["weight_status"])
        self.assertTrue(all(item["weighted_contribution"] is None for item in self.state["dimensions"]))
        self.assertTrue(all(item["formal_score"] is None for item in self.state["dimensions"]))

    def test_industry_blocks_on_mapping_not_exclusively_ai_share(self):
        reason = self.state["industry_ai_blocker"]
        self.assertIn("NO_ELIGIBLE_CURRENT_NUMERIC_KPI", reason)
        self.assertIn("數值映射與正規化", reason)
        self.assertIn(scoring.BRIDGE, self.state["provenance"].values())
        self.assertFalse(self.state["formal_dimension_eligibility"]["industry"]["eligible"])

    def test_official_exposure_evidence_survives_but_is_not_ai_specific(self):
        kpi = self.state["research_kpi_values"]
        self.assertEqual(51, kpi["cloud_networking_share_pct"])
        self.assertIsNone(kpi["ai_specific_share_pct"])
        self.assertEqual(3, len(kpi["official_ai_demand_evidence"]))
        self.assertIsNone(kpi["dimension_models"]["industry"])

    def test_formal_aggregate_and_action_remain_fail_closed_with_exact_reason(self):
        self.assertIsNone(self.state["formal_score"])
        self.assertFalse(self.state["formal_score_available"])
        self.assertFalse(self.state["aggregate_eligibility"]["eligible"])
        self.assertFalse(self.state["decision_actionable"])
        self.assertEqual("未形成正式評等", self.state["decision_label"])
        self.assertIn("五維數值公式", self.state["decision_reason"])

    def test_read_only_state_is_stable_and_does_not_write(self):
        paths = [ROOT / path for path in self.state["provenance"]["source_sha256"]]
        before = {str(p): p.read_bytes() for p in paths}
        self.assertEqual(self.state, scoring.build_scoring_state(ROOT))
        self.assertEqual(before, {str(p): p.read_bytes() for p in paths})
        self.assertEqual(64, len(self.state["state_id"]))

    def test_empty_package_never_activates_legacy_fallback(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests", prefix=".tmp-scoring-") as directory:
            state = scoring.build_scoring_state(directory)
            self.assertFalse(state["formal_score_available"])
            self.assertEqual(0, state["data_coverage"]["research_model_count"])
            self.assertIsNone(state["current_period"])

    def test_tampered_current_master_is_not_replaced_with_q1(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests", prefix=".tmp-scoring-") as directory:
            root = Path(directory)
            for path in self.state["provenance"]["source_sha256"]:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / path, target)
            with (root / "data/2317_master_v9.csv").open("ab") as handle:
                handle.write(b"tamper")
            state = scoring.build_scoring_state(root)
            self.assertIsNone(state["current_period"])
            self.assertIsNone(state["research_kpi_values"]["historical_quality"]["value"])
            self.assertIn("AUTHORITY_BYTES_UNVERIFIED:data/2317_master_v9.csv", state["blocking_inputs"])

    def radar(self, state):
        text = (ROOT / "src/index_p1008_v7.source.html").read_text(encoding="utf-8")
        start = text.index("function clampScore(")
        end = text.index("const DataBadge", start)
        script = text[start:end] + "\nconsole.log(JSON.stringify(calculateRadarPackage(" + json.dumps({
            "quality": 78, "aiRevPct": 50, "capScore": 2, "currentPB": 1.5,
            "foreignHoldChange": 1, "foreignHoldTrend": "RISING", "scoringState": state,
        }) + ")));"
        return json.loads(subprocess.check_output(["node", "-e", script], text=True, encoding="utf-8"))

    def test_javascript_finite_inputs_never_activate_legacy_aggregate(self):
        view = self.radar(None)
        self.assertIsNone(view["total"])
        self.assertIsNone(view["radarValues"])
        self.assertIsNone(view["knownContribution"])
        self.assertTrue(all(item["score"] is None for item in view["dimensions"]))

    def test_javascript_views_use_exact_canonical_state(self):
        view = self.radar(self.state)
        self.assertEqual(self.state, view["scoringState"])
        self.assertEqual(self.state["dimensions"], view["dimensions"])
        self.assertEqual(0, view["scoredCount"])
        self.assertEqual(2, view["researchCount"])

    def test_both_dashboards_request_same_state_and_avoid_stale_current_selection(self):
        source = (ROOT / "src/index_p1008_v7.source.html").read_text(encoding="utf-8")
        new = (ROOT / "ui/P1008_WARROOM_COMMAND_CENTER_v24.html").read_text(encoding="utf-8")
        self.assertIn("/api/p1008/scoring-state", source)
        self.assertIn("api/p1008/scoring-state", new)
        self.assertIn("const latestMaster = scoringState?.current_source_rows?.master || {}", source)
        self.assertNotIn("const latestMaster = validMas[0]", source)
        self.assertNotIn("HOLD / 觀察", new)
        self.assertIn("item.formal_eligible && Number.isFinite(item.weighted_contribution)", source)


if __name__ == "__main__":
    unittest.main()
