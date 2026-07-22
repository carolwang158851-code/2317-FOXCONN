from __future__ import annotations

import csv
import hashlib
import json
import re
import unittest
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def read_csv(name: str) -> list[dict[str, str]]:
    with (DATA / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class AuthorityBaseline20260722Tests(unittest.TestCase):
    def test_cash_flow_authority_formula_source_and_safety(self) -> None:
        rows = read_csv("2317_cash_flow_authority.csv")
        self.assertEqual({row["ticker"] for row in rows}, {"2317"})
        self.assertEqual({row["period"] for row in rows}, {"2025Q1", "2026Q1"})

        row = next(item for item in rows if item["period"] == "2026Q1")
        self.assertEqual(row["operating_cash_flow_thousand_ntd"], "3217154")
        self.assertEqual(row["ppe_capex_thousand_ntd"], "35774345")
        self.assertEqual(row["intangible_capex_thousand_ntd"], "300141")
        self.assertEqual(row["free_cash_flow_core_thousand_ntd"], "-32557191")
        self.assertEqual(row["free_cash_flow_core_100m_ntd"], "-325.57191")
        self.assertEqual(row["verification_status"], "OFFICIAL_HONHAI_PDF_VERIFIED")
        self.assertEqual(row["actionable"].lower(), "false")

        cfo = int(row["operating_cash_flow_thousand_ntd"])
        ppe = int(row["ppe_capex_thousand_ntd"])
        intangible = int(row["intangible_capex_thousand_ntd"])
        self.assertEqual(int(row["free_cash_flow_core_thousand_ntd"]), cfo - ppe)
        self.assertEqual(
            int(row["free_cash_flow_after_intangibles_thousand_ntd"]),
            cfo - ppe - intangible,
        )
        self.assertEqual(
            Decimal(row["free_cash_flow_core_100m_ntd"]),
            Decimal(row["free_cash_flow_core_thousand_ntd"]) / Decimal("100000"),
        )
        self.assertTrue(row["source_report_url"].startswith("https://"))
        self.assertTrue(row["source_landing_url"].startswith("https://"))
        self.assertTrue(row["source_pages"])
        self.assertRegex(row["source_document_sha256"], re.compile(r"^[0-9A-F]{64}$"))

    def test_daily_price_is_sorted_unique_weekday_only_and_reconciled(self) -> None:
        rows = read_csv("2317_daily_price.csv")
        dates = [date.fromisoformat(row["Date"]) for row in rows]
        self.assertEqual(len(rows), 111)
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(len(dates), len(set(dates)))
        self.assertTrue(all(item.weekday() < 5 for item in dates))
        self.assertNotIn(date(2026, 7, 19), dates)
        self.assertNotIn(date(2026, 7, 21), dates)
        self.assertTrue(all(Decimal(row["Close"]) > 0 for row in rows))

        for row in rows:
            expected_pb = (Decimal(row["Close"]) / Decimal(row["BVPS_ref"])).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )
            self.assertEqual(Decimal(row["PB_daily"]), expected_pb, row["Date"])

        cutoff = next(row for row in rows if row["Date"] == "2026-07-20")
        self.assertEqual(cutoff["Close"], "234.5")
        self.assertEqual(cutoff["PB_daily"], "1.845")
        self.assertEqual(cutoff["DataSupportLevel"], "OFFICIAL_TWSE_A1")
        self.assertEqual(cutoff["Status"], "OK")

    def test_manifest_hashes_and_cutoffs_match_authority_bytes(self) -> None:
        manifest = json.loads((DATA / "CSV_AUTHORITY_MANIFEST.json").read_text(encoding="utf-8"))
        entries = {entry["path"]: entry for entry in manifest["authoritativeFiles"]}

        price_path = DATA / "2317_daily_price.csv"
        price = entries["data/2317_daily_price.csv"]
        self.assertEqual(price["sha256"], sha256(price_path))
        self.assertEqual(price["fileSizeBytes"], price_path.stat().st_size)
        self.assertEqual(price["rowCount"], len(read_csv(price_path.name)))
        self.assertEqual(price["dataCutoff"], "2026-07-20")
        self.assertEqual(price["dateRange"]["end"], "2026-07-20")
        self.assertEqual(price["cutoffRowSourceTier"], "OFFICIAL_TWSE_A1")

        cash_path = DATA / "2317_cash_flow_authority.csv"
        cash = entries["data/2317_cash_flow_authority.csv"]
        self.assertEqual(cash["sha256"], sha256(cash_path))
        self.assertEqual(cash["fileSizeBytes"], cash_path.stat().st_size)
        self.assertEqual(cash["rowCount"], len(read_csv(cash_path.name)))
        self.assertEqual(cash["financialCutoffPeriod"], "2026Q1")
        self.assertEqual(cash["actionable"], False)

        self.assertEqual(manifest["authorityBaselinePromotion"]["scopeId"], "P1008-AUTHORITY-BASELINE-20260722")
        self.assertEqual(manifest["authorityBaselinePromotion"]["actionable"], False)


if __name__ == "__main__":
    unittest.main()
