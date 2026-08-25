from __future__ import annotations

import inspect
import unittest
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

try:
    from .helpers import PACKAGE_ROOT
except ImportError:
    from helpers import PACKAGE_ROOT

from p1008_research_plugin.phaseb1_common import sha256_file
from p1008_research_plugin.reporting.historical_research_reconstruction import (
    T0, T1, T2, T3, T4,
    build_layered_historical_research_baseline,
    estimate_weighted_average_shares,
    fcf_per_share,
    load_source_catalog,
    reconcile_estimate,
    research_observations_for,
    resolve_crosscheck,
)
from p1008_research_plugin.reporting.war_report_production_runtime import _build_chapters


PROTECTED = (
    "data/CSV_AUTHORITY_MANIFEST.json", "data/2317_master_v9.csv",
    "data/2317_daily_price.csv", "data/2317_daily_market_activity.csv",
    "data/2317_cash_flow_authority.csv", "data/macro_snapshot.csv",
    "data/macro_event_observations.csv", "data/fx_trend_observations.csv",
    "rules/RULE_STATUS_MANIFEST.json",
)


class HistoricalSourceEstimationV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import json
        config = json.loads((PACKAGE_ROOT / "modules/p1008_research_plugin/config/quarterly_earnings/FY2026_Q2.json").read_text(encoding="utf-8"))
        q = SimpleNamespace(
            source_hash=config["expectedSourceSha256"],
            attributable_profit=SimpleNamespace(value=config["financials"]["attributableProfitMillionTwd"]),
            eps=SimpleNamespace(value=config["financials"]["epsTwd"], evidence_ids=["OFFICIAL-Q2-EPS"]),
        )
        analysis = SimpleNamespace(event_type="QUARTERLY_EARNINGS", quarterly_earnings=q)
        cls.before = {path: sha256_file(PACKAGE_ROOT / path) for path in PROTECTED}
        cls.baseline = build_layered_historical_research_baseline(PACKAGE_ROOT, analysis)
        cls.after = {path: sha256_file(PACKAGE_ROOT / path) for path in PROTECTED}

    def test_e1_t0_direct_observations_remain_canonical(self) -> None:
        primary = {"value": "10", "data_class": T0}
        result = resolve_crosscheck(primary, [{"value": "12", "source_id": "T3"}])
        self.assertEqual((result["canonical_value"], result["canonical_data_class"]), ("10", T0))
        self.assertFalse(result["averaged"])

    def test_e2_t1_preserves_full_formula_lineage(self) -> None:
        exact = [x for x in self.baseline["observations"] if x["data_class"] == T1]
        self.assertTrue(exact)
        self.assertTrue(all(x.get("formula_version") and x.get("input_observation_ids") for x in exact))

    def test_e3_t2_cannot_be_mislabeled_direct(self) -> None:
        estimates = [x for x in self.baseline["observations"] if x["data_class"] == T2]
        self.assertTrue(estimates)
        self.assertTrue(all(x["direct_or_derived"] == "ESTIMATED" for x in estimates))

    def test_e4_estimated_wa_shares_use_parent_ni_over_basic_eps(self) -> None:
        item = research_observations_for(self.baseline, "WA_SHARES_BASIC_EST")[0]
        self.assertEqual(Decimal(item["value"]), Decimal("59974") / Decimal("4.27"))
        self.assertIn("PARENT_NET_INCOME_DIVIDED_BY_REPORTED_BASIC_EPS", item["estimate_method"])

    def test_e5_eps_rounding_interval_bounds_share_estimate(self) -> None:
        item = research_observations_for(self.baseline, "WA_SHARES_BASIC_EST")[0]
        self.assertLess(Decimal(item["lower_bound"]), Decimal(item["value"]))
        self.assertLess(Decimal(item["value"]), Decimal(item["upper_bound"]))
        self.assertIn("[4.265, 4.275)", item["rounding_effect"])

    def test_e6_fcf_per_share_uses_compatible_wa_shares(self) -> None:
        rows = research_observations_for(self.baseline, "FCF_PER_SHARE")
        self.assertTrue(rows)
        self.assertEqual({x["formula_version"] for x in rows}, {"FCF_PER_SHARE_V1"})
        self.assertTrue(all("加權平均" in x["formula"] for x in rows))

    def test_e7_fcf_per_share_rejects_period_end_shares(self) -> None:
        with self.assertRaisesRegex(Exception, "DENOMINATOR_INVALID"):
            fcf_per_share(fcf_million_twd="1", weighted_average_shares={"value": "10", "basis": "PERIOD_END", "data_class": T0}, period="2026Q2", fcf_observation_id="FCF")

    def test_e8_t2_denominator_propagates_t2_to_fcf_per_share(self) -> None:
        latest = research_observations_for(self.baseline, "FCF_PER_SHARE")[-1]
        self.assertEqual((latest["period"], latest["data_class"]), ("2026Q2", T2))
        self.assertIn("lower_bound", latest)

    def test_e9_official_replacement_preserves_estimate_history(self) -> None:
        estimate = research_observations_for(self.baseline, "WA_SHARES_BASIC_EST")[0]
        result = reconcile_estimate(estimate, "14000")
        self.assertEqual(result["canonical_data_class"], T0)
        self.assertTrue(result["estimate_lineage_preserved"])
        self.assertEqual(result["reconciliation_state"], "OFFICIAL_REPLACEMENT_AVAILABLE")

    def test_e10_t3_does_not_overwrite_t0_or_t1(self) -> None:
        t3 = research_observations_for(self.baseline, "PERIOD_END_SHARES")
        self.assertEqual({x["data_class"] for x in t3}, {T3})
        self.assertEqual(self.baseline["external_crosscheck_results"]["policy"], "T3_NEVER_OVERWRITES_T0_T1_AND_CONFLICTS_ARE_NOT_AVERAGED")

    def test_e11_t3_conflict_is_surfaced_not_averaged(self) -> None:
        result = resolve_crosscheck({"value": "100", "data_class": T0}, [{"value": "105", "source_id": "A"}])
        self.assertEqual(result["state"], "CROSSCHECK_CONFLICT")
        self.assertFalse(result["averaged"])

    def test_e12_t4_cannot_enter_historical_actual_series(self) -> None:
        self.assertEqual(self.baseline["scenario_contract"], {"data_class": T4, "historical_actual_series_allowed": False})
        self.assertFalse(any(x["data_class"] == T4 for x in self.baseline["observations"]))

    def test_e13_full_history_retains_estimate_classification(self) -> None:
        self.assertEqual({x["data_class"] for x in research_observations_for(self.baseline, "CCC_EST")}, {T2})
        self.assertEqual(self.baseline["metric_tier_counts"]["CCC_EST"][T2], 3)

    def test_e14_different_ccc_bases_are_not_merged(self) -> None:
        governed = research_observations_for(self.baseline, "CCC")
        estimated = research_observations_for(self.baseline, "CCC_EST")
        self.assertEqual({x["basis"] for x in governed}, {"EXISTING_GOVERNED_CCC_METHOD_V1"})
        self.assertEqual({x["basis"] for x in estimated}, {"CCC_EST_V1_END_BALANCE_90_DAY"})

    def test_e15_appendix_ledger_contains_material_t1_t2_methodology(self) -> None:
        ledger = self.baseline["estimation_derivation_ledger"]
        self.assertTrue(any(x["classification"] == T1 for x in ledger))
        self.assertTrue(any(x["classification"] == T2 and x["assumptions"] for x in ledger))
        self.assertTrue(all(x["formula"] and x["sources"] for x in ledger))

    def test_e16_main_report_marks_t2_as_estimate(self) -> None:
        source = inspect.getsource(_build_chapters)
        self.assertIn("估算分母與FCF／股", source)
        self.assertIn("此數值屬估算，不是公司直接揭露", source)

    def test_e17_weak_t2_cannot_trigger_thesis_downgrade_alone(self) -> None:
        self.assertEqual(self.baseline["decision_engine_evidence_policy"][T2], "WATCH_OR_PARTIAL_ONLY_WITHOUT_CORROBORATION")

    def test_e18_network_source_receipt_is_captured(self) -> None:
        receipts = self.baseline["source_receipts"]
        self.assertGreaterEqual(len(receipts), 7)
        self.assertTrue(all(x["retrieval_date"] and x["source_locator"].startswith("https://") and len(x["content_hash"]) == 64 for x in receipts))

    def test_e19_protected_production_hashes_unchanged(self) -> None:
        self.assertEqual(self.before, self.after)
        self.assertFalse(self.baseline["raw_authority_modified"])

    def test_e20_search_snippet_is_not_primary_financial_evidence(self) -> None:
        catalog = load_source_catalog(PACKAGE_ROOT)
        official = [x for x in catalog["source_receipts"] if x["source_tier"] == T0]
        self.assertTrue(all(x["source_type"].startswith("OFFICIAL_") for x in official))
        self.assertFalse(any("snippet" in x["notes"].casefold() for x in official))

    def test_e21_2026q1_price_discrepancy_has_reconciliation_record(self) -> None:
        record = self.baseline["price_reconciliation"]
        self.assertEqual((record["master_price_value"], record["daily_authority_value"]), ("165.5", "187.5"))
        self.assertEqual(record["canonical_runtime_value"], "187.5")
        self.assertFalse(record["raw_master_modified"])

    def test_e22_standalone_fcf_uses_same_basis_cumulative_statements(self) -> None:
        rows = [x for x in research_observations_for(self.baseline, "FCF", basis="Q_STANDALONE") if x["period"] in {"2025Q2", "2025Q3", "2025Q4"}]
        self.assertEqual(len(rows), 3)
        self.assertTrue(all("MINUS" in x["formula_version"] and len(x["input_observation_ids"]) == 2 for x in rows))
        q4 = next(x for x in rows if x["period"] == "2025Q4")
        self.assertEqual(q4["value"], "215424")
        inputs = {x["observation_id"]: x for x in self.baseline["observations"]}
        q4_inputs = [inputs[x] for x in q4["input_observation_ids"]]
        self.assertEqual({x["value"] for x in q4_inputs}, {"-162335", "53089"})
        self.assertTrue(all("IR_RESULTS_ROUNDED" in (x.get("notes") or "") for x in q4_inputs))

    def test_e23_no_fake_historical_peer_snapshot_is_generated(self) -> None:
        self.assertEqual(self.baseline["unavailable"]["historical_peer_snapshot"], "NOT_GENERATED")
        self.assertFalse(any(x["metric_family"] == "PEER" for x in self.baseline["observations"]))


if __name__ == "__main__":
    unittest.main()
