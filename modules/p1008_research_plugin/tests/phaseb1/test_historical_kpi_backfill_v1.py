from __future__ import annotations

import inspect
import json
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

try:
    from .helpers import PACKAGE_ROOT
except ImportError:
    from helpers import PACKAGE_ROOT

from p1008_research_plugin.phaseb1_common import sha256_file
from p1008_research_plugin.analysis.quarterly_analysis_builder import normalized_q4_eps
from p1008_research_plugin.quarterly_authority import quarterly_metric_availability
from p1008_research_plugin.reporting.historical_kpi_baseline import (
    HistoricalKPIBaselineError,
    ObservationStore,
    build_historical_kpi_baseline,
    derive_standalone,
    observation,
    observations_for,
    select_quarter_end_price,
)
from p1008_research_plugin.reporting.war_report_production_contract import recent_zoom
from p1008_research_plugin.reporting.war_report_production_runtime import (
    build_full_history_charts,
    derive_bvps_metric,
)


PROTECTED = (
    "data/CSV_AUTHORITY_MANIFEST.json",
    "data/2317_master_v9.csv",
    "data/2317_daily_price.csv",
    "data/2317_daily_market_activity.csv",
    "data/2317_cash_flow_authority.csv",
    "data/macro_snapshot.csv",
    "data/macro_event_observations.csv",
    "data/fx_trend_observations.csv",
    "rules/RULE_STATUS_MANIFEST.json",
)


def direct(metric: str, period: str, value: str, basis: str = "YTD_CUMULATIVE") -> dict:
    quarter = int(period[-1]) if "Q" in period else None
    return observation(
        metric_id=metric, metric_family="TEST", period=period,
        period_type="H1_CUMULATIVE" if "H1" in period else (f"Q{quarter}_STANDALONE" if quarter else "FY_CUMULATIVE"),
        period_start=f"{period[:4]}-01-01", period_end=f"{period[:4]}-12-31",
        fiscal_year=int(period[:4]), fiscal_quarter=quarter, value=value,
        unit="新台幣百萬元", currency="TWD", basis=basis,
        direct_or_derived="DIRECT", formula_version="DIRECT_V1", source_id="LOCAL-OFFICIAL",
        source_type="OFFICIAL_LOCAL_FILING", source_locator="local.pdf#p1",
        source_hash="A" * 64, notes="synthetic contract input",
    )


class HistoricalKPIBackfillV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        qconfig = json.loads((PACKAGE_ROOT / "modules/p1008_research_plugin/config/quarterly_earnings/FY2026_Q2.json").read_text(encoding="utf-8"))
        analysis = SimpleNamespace(
            event_type="QUARTERLY_EARNINGS",
            quarterly_earnings=SimpleNamespace(source_sha256=qconfig["expectedSourceSha256"]),
        )
        cls.before = {path: sha256_file(PACKAGE_ROOT / path) for path in PROTECTED}
        cls.baseline = build_historical_kpi_baseline(PACKAGE_ROOT, analysis)
        cls.after = {path: sha256_file(PACKAGE_ROOT / path) for path in PROTECTED}

    def test_h1_historical_backfill_never_modifies_raw_authority(self) -> None:
        self.assertEqual(self.before, self.after)
        self.assertFalse(self.baseline["raw_authority_modified"])

    def test_h2_same_observation_cannot_duplicate(self) -> None:
        store = ObservationStore()
        item = direct("CFO", "2026H1", "1")
        self.assertEqual(store.upsert(item), "APPENDED")
        self.assertEqual(store.upsert(deepcopy(item)), "NO_OP_IDENTICAL")
        self.assertEqual(len(store.values()), 1)

    def test_h3_conflicting_same_key_fails_closed(self) -> None:
        store = ObservationStore()
        item = direct("CFO", "2026H1", "1")
        store.upsert(item)
        changed = deepcopy(item)
        changed["value"] = "2"
        with self.assertRaisesRegex(HistoricalKPIBaselineError, "CONFLICTING_OBSERVATION"):
            store.upsert(changed)

    def test_h4_cumulative_and_standalone_periods_remain_distinct(self) -> None:
        h1 = observations_for(self.baseline, "CFO", basis="YTD_CUMULATIVE")
        q2 = [x for x in observations_for(self.baseline, "CFO", basis="Q_STANDALONE") if x["period"] == "2026Q2"]
        self.assertEqual(h1[0]["period_type"], "H1_CUMULATIVE")
        self.assertEqual(q2[0]["period_type"], "Q2_STANDALONE")
        self.assertNotEqual(h1[0]["observation_key"], q2[0]["observation_key"])

    def test_h5_q2_standalone_uses_h1_minus_q1_same_basis(self) -> None:
        q2 = next(x for x in observations_for(self.baseline, "CFO") if x["period"] == "2026Q2")
        self.assertEqual(q2["value"], "-72339.154")
        self.assertEqual(q2["formula_version"], "H1_MINUS_Q1_SAME_BASIS_V1")
        self.assertEqual(len(q2["input_observation_ids"]), 2)

    def test_h6_q3_standalone_uses_9m_minus_h1_same_basis(self) -> None:
        result = derive_standalone(direct("CFO", "2026M9", "90"), direct("CFO", "2026H1", "60"), result_period="2026Q3", result_period_type="Q3_STANDALONE", formula_version="9M_MINUS_H1_SAME_BASIS_V1")
        self.assertEqual(result["value"], "30")

    def test_h7_q4_standalone_uses_fy_minus_9m_same_basis(self) -> None:
        result = derive_standalone(direct("CFO", "2026FY", "120"), direct("CFO", "2026M9", "90"), result_period="2026Q4", result_period_type="Q4_STANDALONE", formula_version="FY_MINUS_9M_SAME_BASIS_V1")
        self.assertEqual(result["value"], "30")

    def test_h8_fcf_formula_uses_stable_positive_capex_outflow(self) -> None:
        q2 = {x["metric_id"]: x for x in self.baseline["observations"] if x["period"] == "2026Q2" and x["metric_id"] in {"CFO", "CAPEX", "FCF"}}
        self.assertEqual(float(q2["FCF"]["value"]), float(q2["CFO"]["value"]) - float(q2["CAPEX"]["value"]))
        self.assertEqual(q2["FCF"]["formula_version"], "CFO_MINUS_CAPEX_V1")

    def test_h9_nwc_proxy_formula_is_stable(self) -> None:
        for period in ("2025Q2", "2026Q1", "2026Q2"):
            rows = {x["metric_id"]: x for x in self.baseline["observations"] if x["period"] == period and x["metric_id"] in {"AR", "INVENTORY", "AP", "NWC_PROXY"}}
            self.assertEqual(float(rows["NWC_PROXY"]["value"]), float(rows["AR"]["value"]) + float(rows["INVENTORY"]["value"]) - float(rows["AP"]["value"]))

    def test_h10_ccc_cannot_mix_methodologies(self) -> None:
        rows = observations_for(self.baseline, "CCC")
        self.assertEqual({x["basis"] for x in rows}, {"EXISTING_GOVERNED_CCC_METHOD_V1"})
        self.assertEqual({x["formula_version"] for x in rows}, {"DSO_PLUS_DIO_MINUS_DPO_V1"})

    def test_h11_period_end_and_weighted_average_shares_remain_separate(self) -> None:
        self.assertEqual(self.baseline["unavailable"]["period_end_share_count"], "LOCAL_SOURCE_GAP")
        self.assertEqual(self.baseline["unavailable"]["weighted_average_share_count"], "LOCAL_SOURCE_GAP")
        self.assertNotIn("SHARE_COUNT", self.baseline["metric_counts"])

    def test_h12_bvps_uses_period_end_shares(self) -> None:
        metric = derive_bvps_metric(period="2026Q2", parent_equity="100", ordinary_shares="10", source=["LOCAL"])
        self.assertEqual(metric["calculation_version"], "PARENT_EQUITY_DIVIDED_BY_PERIOD_END_ORDINARY_SHARES_V1")

    def test_h13_pe_uses_ttm_eps(self) -> None:
        rows = observations_for(self.baseline, "PE_TTM")
        expected = [
            f"{year}Q{quarter}"
            for year in range(2021, 2027)
            for quarter in range(1, 5)
            if (year, quarter) <= (2026, 2)
        ]
        self.assertEqual([row["period"] for row in rows], expected)
        self.assertEqual(len({row["period"] for row in rows}), len(rows))
        self.assertEqual({x["formula_version"] for x in rows}, {"QUARTER_END_PRICE_DIVIDED_BY_TTM_EPS_V1"})

    def test_h14_ps_uses_ttm_revenue(self) -> None:
        rows = observations_for(self.baseline, "PS_TTM")
        self.assertEqual(len(rows), 18)
        self.assertEqual(rows[0]["period"], "2021Q4")
        self.assertEqual({x["formula_version"] for x in rows}, {"QUARTER_END_MARKET_CAP_DIVIDED_BY_TTM_REVENUE_V1"})

    def test_h15_pb_uses_period_end_bvps_basis(self) -> None:
        rows = observations_for(self.baseline, "PB")
        expected = [
            f"{year}Q{quarter}"
            for year in range(2021, 2027)
            for quarter in range(1, 5)
            if (year, quarter) <= (2026, 2)
        ]
        self.assertEqual([row["period"] for row in rows], expected)
        self.assertEqual(len({row["period"] for row in rows}), len(rows))
        self.assertEqual({x["basis"] for x in rows}, {"QUARTER_END_LAST_VALID_TRADING_DAY"})
        self.assertTrue(all(abs(float(x["price"]) / float(next(row["BVPS"] for row in self._master_rows() if row["Quarter"] == x["period"])) - float(x["value"])) <= 0.01 for x in rows))
        q1 = next(x for x in rows if x["period"] == "2026Q1")
        self.assertEqual((q1["valuation_date"], q1["price"]), ("2026-03-31", "187.5"))
        self.assertIn("daily_price", q1["component_source_hashes"])

    def test_h15a_q4_eps_accepts_promoted_and_historical_lineage_only(self) -> None:
        config = json.loads(
            (
                PACKAGE_ROOT
                / "modules/p1008_research_plugin/config/quarterly_earnings/FY2026_Q2.json"
            ).read_text(encoding="utf-8")
        )
        correction = config["historicalEpsCorrections"]["2025Q4"]
        notes = (
            "EPS_Q_OFFICIAL_CORRECTION_3.25_TO_3.23;"
            "EPS_SOURCE_CORRECTION_NOT_STANDALONE_EARNINGS_DETERIORATION"
        )
        self.assertEqual(normalized_q4_eps("3.23", correction, master_notes=notes), Decimal("3.23"))
        self.assertEqual(normalized_q4_eps("3.25", correction), Decimal("3.23"))
        with self.assertRaisesRegex(ValueError, "neither the governed historical nor promoted value"):
            normalized_q4_eps("3.24", correction, master_notes=notes)
        with self.assertRaisesRegex(ValueError, "missing governed correction lineage"):
            normalized_q4_eps("3.23", correction)

    def test_h15b_current_formal_roe_and_roic_availability_is_explicit(self) -> None:
        rows = self._master_rows()
        availability = quarterly_metric_availability(rows)
        self.assertEqual(rows[-1]["Quarter"], "2026Q2")
        self.assertEqual(availability["latestValidRoeQuarter"], "2026Q2")
        self.assertEqual(availability["roe"]["values"][-1], "12.61")
        self.assertEqual(availability["latestValidRoicQuarter"], "2026Q1")
        self.assertEqual(availability["roic"]["values"][-1], "12.57")
        self.assertEqual(availability["unavailableRoicQuarters"], ["2026Q2"])

    @staticmethod
    def _master_rows() -> list[dict[str, str]]:
        import csv
        with (PACKAGE_ROOT / "data/2317_master_v9.csv").open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(line for line in handle if line.strip() and not line.startswith("##")))

    def test_h16_quarter_end_price_selects_last_valid_date_on_or_before_end(self) -> None:
        row = select_quarter_end_price([{"Date": "2026-03-30", "Close": "1"}, {"Date": "2026-04-01", "Close": "2"}], "2026-03-31")
        self.assertEqual(row["Date"], "2026-03-30")

    def test_h17_full_history_runtime_consumes_normalized_baseline(self) -> None:
        source = inspect.getsource(build_full_history_charts)
        self.assertIn("historical_baseline", source)
        self.assertIn("observations_for", source)

    def test_h18_dropped_observations_remain_zero(self) -> None:
        source = inspect.getsource(build_full_history_charts)
        self.assertIn('"DROPPED_OBSERVATIONS": 0', source)

    def test_h19_recent_8q_does_not_mutate_full_history(self) -> None:
        rows = observations_for(self.baseline, "PB")
        snapshot = deepcopy(rows)
        self.assertEqual(len(recent_zoom(rows, 8)), 8)
        self.assertEqual(rows, snapshot)

    def test_h20_no_third_party_historical_values_inserted(self) -> None:
        self.assertLessEqual({x["source_type"] for x in self.baseline["observations"]}, {"GOVERNED_PRODUCTION_AUTHORITY", "OFFICIAL_LOCAL_FILING"})

    def test_h21_missing_source_provenance_rejects_observation(self) -> None:
        with self.assertRaisesRegex(HistoricalKPIBaselineError, "OBSERVATION_PROVENANCE_INVALID"):
            observation(metric_id="X", metric_family="X", period="2026Q1", period_type="Q1_STANDALONE", period_start="2026-01-01", period_end="2026-03-31", fiscal_year=2026, fiscal_quarter=1, value="1", unit="x", currency=None, basis="x", direct_or_derived="DIRECT", formula_version="DIRECT_V1", source_id="x", source_type="OFFICIAL_LOCAL_FILING", source_locator="", source_hash="A" * 64)

    def test_h22_derived_metric_retains_formula_and_input_lineage(self) -> None:
        rows = [x for x in self.baseline["observations"] if x["direct_or_derived"] == "DERIVED"]
        self.assertTrue(rows)
        self.assertTrue(all(x["formula_version"] and x["input_observation_ids"] for x in rows))

    def test_h23_no_test_fixture_leaks_into_persistent_data(self) -> None:
        self.assertEqual(self.before, self.after)
        self.assertFalse(any("fixture" in x["source_locator"].casefold() for x in self.baseline["observations"]))


if __name__ == "__main__":
    unittest.main()
