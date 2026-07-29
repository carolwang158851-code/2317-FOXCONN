from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SCRIPT = TOOLS / "phase_a_final_owner_review.py"
def load_module():
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location("phase_a_final_owner_review", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load Phase A owner review builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PhaseAFinalOwnerReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()
        lines = [
            '"115年07月 2317 鴻海 各日成交資訊"',
            '"日期","成交股數","成交金額","開盤價","最高價","最低價","收盤價","漲跌價差","成交筆數"',
            '"115/07/20","48,579,978","11,422,510,146","235.50","238.50","230.50","234.50","+0.50","37,763"',
            '"115/07/21","51,471,036","12,544,250,590","238.00","247.00","236.50","246.00","+11.50","47,986"',
            '"115/07/22","67,787,081","17,204,588,878","249.00","259.00","248.00","251.50","+5.50","57,938"',
            '"115/07/23","63,787,974","16,358,184,879","256.50","259.50","253.50","257.50","+6.00","53,611"',
            '"115/07/24","33,694,573","8,518,599,943","254.00","256.00","251.50","252.50","-5.00","32,769"',
            '"115/07/27","35,908,207","8,967,672,916","253.00","254.50","246.00","253.00","+0.50","32,663"',
        ]
        cls.raw = ("\r\n".join(lines) + "\r\n").encode("cp950")
        cls.twse = cls.module.parse_twse_month(cls.raw, "2026-07")

    def test_review_uses_preserved_receipt_without_network(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("fetch_twse_month(", source)
        self.assertNotIn("urllib", source)
        self.assertIn("load_offline_month(", source)
        self.assertIn("http_calls_this_review", source)

    def test_twse_receipt_verifies_both_daily_price_gaps(self) -> None:
        self.assertEqual(str(self.twse["2026-07-22"]["close"]), "251.50")
        self.assertEqual(str(self.twse["2026-07-24"]["close"]), "252.50")

    def test_daily_gap_candidate_refuses_already_published_dates(self) -> None:
        with self.assertRaisesRegex(ValueError, "gap is no longer missing"):
            self.module.build_daily_gap_candidate(
                ROOT, self.twse, ROOT / "runtime" / "test-review"
            )

    def test_complete_market_candidate_requires_six_close_matches(self) -> None:
        _, formal_rows = self.module.read_csv(ROOT / "data/2317_daily_price.csv")
        price_by_date = {
            row["Date"]: row["Close"]
            for row in formal_rows
            if row["Date"] != "2026-07-19"
        }
        price_by_date.update({"2026-07-22": "251.50", "2026-07-24": "252.50"})
        expected_price = {"price_by_date": price_by_date}
        writes: dict[str, bytes] = {}
        original_atomic_write = self.module.atomic_write
        original_read_formal_activity = self.module.read_formal_activity
        stage1_rows = [
            row
            for row in original_read_formal_activity(
                ROOT / "data/2317_daily_market_activity.csv"
            )
            if row["date"] not in self.module.FULL_MARKET_DATES
        ]
        self.module.atomic_write = (
            lambda path, value: writes.__setitem__(Path(path).name, value)
        )
        self.module.read_formal_activity = lambda _path: stage1_rows
        try:
            result = self.module.build_market_candidate(
                ROOT,
                self.twse,
                expected_price,
                ROOT / "runtime" / "test-review",
            )
        finally:
            self.module.atomic_write = original_atomic_write
            self.module.read_formal_activity = original_read_formal_activity
        self.assertEqual(len(result["candidate_rows"]), 6)
        self.assertEqual(result["expected_manifest_entry"]["rowCount"], 66)
        self.assertEqual(
            result["expected_manifest_entry"]["cutoffDate"], "2026-07-27"
        )
        for row in result["candidate_rows"]:
            self.assertEqual(
                float(row["twse_close"]), float(row["formal_price_close"])
            )
        self.assertIn(
            "2317_daily_market_activity_20260720_20260727.complete.candidate.csv",
            writes,
        )

    def test_stage1_market_candidate_uses_formal_price_and_writes_receipt_only(self) -> None:
        receipt_dir = (
            ROOT
            / "runtime"
            / "market_activity_incremental"
            / "P1008-MARKET-ACTIVITY-20260728T160944642607Z"
            / "receipts"
        )
        output_dir = (
            ROOT
            / "runtime"
            / "phase_a_test_temp"
            / f"stage1-market-{uuid.uuid4().hex}"
        )
        formal_paths = [
            ROOT / self.module.FORMAL_DAILY,
            ROOT / self.module.FORMAL_MARKET,
            ROOT / self.module.FORMAL_MACRO,
            ROOT / self.module.MANIFEST,
        ]
        before = {path: self.module.sha256_file(path) for path in formal_paths}
        original_read_formal_activity = self.module.read_formal_activity
        stage1_rows = [
            row
            for row in original_read_formal_activity(
                ROOT / "data/2317_daily_market_activity.csv"
            )
            if row["date"] not in self.module.FULL_MARKET_DATES
        ]
        self.module.read_formal_activity = lambda _path: stage1_rows
        try:
            result = self.module.build_stage1_market_activity_candidate(
                ROOT, receipt_dir, output_dir
            )
            receipt = json.loads(
                Path(result["receipt_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(len(result["candidate_rows"]), 6)
            self.assertFalse(result["promotion_eligible"])
            self.assertEqual(result["network_calls"], 0)
            self.assertTrue(result["formal_hashes_unchanged"])
            self.assertEqual(
                receipt["formal_daily_price"]["sha256"],
                self.module.DAILY_PRICE_GAPS_EXPECTED_FORMAL_SHA256,
            )
            self.assertEqual(receipt["candidate"]["sha256"], result["candidate_sha256"])
            self.assertFalse(receipt["formal_market_activity_modified"])
            self.assertFalse(receipt["formal_macro_modified"])
            self.assertTrue(
                all(row["source_month"] == "2026-07" for row in result["candidate_rows"])
            )
            self.assertEqual(
                before,
                {path: self.module.sha256_file(path) for path in formal_paths},
            )
        finally:
            self.module.read_formal_activity = original_read_formal_activity
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_macro_remediation_is_blank_not_zero(self) -> None:
        _, header, formal_rows = self.module.read_macro(
            ROOT / "data/macro_snapshot.csv"
        )
        date_index = header.index("Date")
        value_index = header.index("Hon_Hai_Rev_YoY")
        invalid_values = [
            {
                "date": row[date_index],
                "original_value": row[value_index],
            }
            for row in formal_rows
            if not self.module.is_numeric_or_blank(row[value_index])
        ]
        review = self.module.enrich_macro_review(
            ROOT,
            {
                "candidate_sha256": "EXPECTED_AFTER",
                "invalid_values": invalid_values,
            },
        )
        rows = review["row_preview"]
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row["candidate_value"] == "" for row in rows))
        self.assertTrue(
            all(
                row["original_source"] == "NOT_PRESENT_IN_MACRO_SNAPSHOT_SCHEMA"
                for row in rows
            )
        )


if __name__ == "__main__":
    unittest.main()
