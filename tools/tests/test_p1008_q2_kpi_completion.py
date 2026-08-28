from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PACKAGE / "tools"))

import p1008_q2_kpi_completion as completion


class Q2KpiCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.candidate = completion.build_candidate()

    def test_q2_official_kpis_are_completed_while_roic_remains_conditional(self) -> None:
        self.assertEqual("136.02", self.candidate["kpis"]["bvps"]["value"])
        self.assertEqual("6.21", self.candidate["kpis"]["roe"]["value"])
        self.assertEqual("16.46", self.candidate["kpis"]["roic"]["candidateValue"])
        self.assertIsNone(self.candidate["kpis"]["roic"]["canonicalValue"])
        self.assertEqual("PASS_WITH_ROIC_CONDITIONAL_PENDING", self.candidate["result"])

    def test_classifications_and_periods_are_explicit(self) -> None:
        self.assertEqual("OFFICIAL_REPORTED", self.candidate["kpis"]["bvps"]["classification"])
        self.assertEqual("OFFICIAL_REPORTED", self.candidate["kpis"]["roe"]["classification"])
        self.assertEqual("2026H1", self.candidate["kpis"]["roe"]["period"])
        self.assertFalse(self.candidate["kpis"]["roe"]["annualized"])
        self.assertEqual("OWNER_CONDITIONAL_PENDING", self.candidate["kpis"]["roic"]["classification"])

    def test_roic_release_gate_records_exact_failure(self) -> None:
        gate = self.candidate["kpis"]["roic"]["releaseGate"]
        self.assertEqual("FAIL", gate["gates"]["A"]["status"])
        self.assertEqual("PASS", gate["gates"]["B"]["status"])
        self.assertEqual("PASS", gate["gates"]["C"]["status"])
        self.assertEqual("PASS", gate["gates"]["D"]["status"])
        self.assertFalse(gate["trendComparable"])

    def test_roic_reproduces_from_recorded_inputs(self) -> None:
        roic = self.candidate["kpis"]["roic"]
        numerator = Decimal(roic["numerator"]["valueMillionTwd"])
        denominator = Decimal(roic["denominator"]["valueMillionTwd"])
        self.assertEqual(Decimal("16.46"), (numerator / denominator * 100).quantize(Decimal("0.01")))
        self.assertNotIn("ROIC_Approx_Pct", json.dumps(roic))

    def test_candidate_cannot_mutate_authority_or_issue_action(self) -> None:
        self.assertFalse(self.candidate["authorityMutation"])
        self.assertFalse(self.candidate["formalCsvModified"])
        self.assertFalse(self.candidate["actionable"])

    def test_owner_promotion_is_unique_and_duplicate_safe(self) -> None:
        master = completion._read_csv(PACKAGE / "data/2317_master_v9.csv")[2]
        q2 = [row for row in master if row["Quarter"] == "2026Q2"]
        self.assertEqual(1, len(q2))
        self.assertEqual("136.02", q2[0]["BVPS"])
        self.assertEqual("N/A", q2[0]["ROE_TTM_Pct"])
        self.assertEqual("N/A", q2[0]["ROIC_Precise_Pct"])
        self.assertEqual("N/A", q2[0]["AI_Revenue_Pct"])
        daily = completion._read_csv(PACKAGE / "data/2317_daily_price.csv")[2]
        current = next(row for row in daily if row["Date"] == "2026-08-27")
        self.assertEqual(("2026Q2", "136.02", "1.853"), (current["QuarterKey"], current["BVPS_ref"], current["PB_daily"]))
        pre_event = next(row for row in daily if row["Date"] == "2026-08-12")
        self.assertEqual("2026Q1", pre_event["QuarterKey"])
        config = json.loads((PACKAGE / completion.CONFIG_REL).read_text(encoding="utf-8"))
        self.assertEqual("2026H1", config["canonicalPromotion"]["roe"]["period"])
        self.assertFalse(config["canonicalPromotion"]["roe"]["annualized"])
        with self.assertRaisesRegex(ValueError, "Q2_ALREADY_PRESENT"):
            completion.promote(PACKAGE)


if __name__ == "__main__":
    unittest.main()
