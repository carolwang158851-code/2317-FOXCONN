from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SCRIPT = TOOLS / "phase_a_final_owner_review.py"
TWSE_EVIDENCE_DIR = (
    ROOT
    / "contracts"
    / "p1008_research_plugin"
    / "acceptance"
    / "v1.1"
    / "evidence"
    / "phase_a_twse_202607"
)
TWSE_RAW_PATH = TWSE_EVIDENCE_DIR / "2026-07.twse.raw.csv"
TWSE_RECEIPT_PATH = TWSE_EVIDENCE_DIR / "2026-07.receipt.json"
TWSE_RAW_SHA256 = (
    "5F796822BD279DA8843E6BAA19CC238FAD9E9801874247A98DD5045379D299B5"
)
TWSE_OFFICIAL_URL = (
    "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
    "?date=20260701&stockNo=2317&response=csv"
)
FROZEN_PHASE_A_REVISION = "ac53c1dd151e2e2645cdd3128a7dd70cfad7c582"


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
        cls.raw = TWSE_RAW_PATH.read_bytes()
        cls.source_receipt = json.loads(
            TWSE_RECEIPT_PATH.read_text(encoding="utf-8")
        )
        cls.twse = cls.module.parse_twse_month(cls.raw, "2026-07")

    def frozen_phase_a_root(self) -> Path:
        fixture = ROOT / "runtime" / "phase_a_test_temp" / uuid.uuid4().hex
        for relative in (
            "data/2317_daily_price.csv",
            "data/2317_daily_market_activity.csv",
            "data/macro_snapshot.csv",
            "data/CSV_AUTHORITY_MANIFEST.json",
        ):
            result = subprocess.run(
                ["git", "-C", str(ROOT), "show", f"{FROZEN_PHASE_A_REVISION}:{relative}"],
                check=True,
                capture_output=True,
            )
            destination = fixture / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(result.stdout)
        self.addCleanup(lambda: shutil.rmtree(fixture, ignore_errors=True))
        return fixture

    def test_review_uses_preserved_receipt_without_network(self) -> None:
        raw_sha = hashlib.sha256(self.raw).hexdigest().upper()
        self.assertEqual(raw_sha, TWSE_RAW_SHA256)
        self.assertEqual(self.source_receipt["raw_artifact_sha256"], raw_sha)
        self.assertEqual(self.source_receipt["raw_sha256"], raw_sha)
        self.assertEqual(self.source_receipt["request_url"], TWSE_OFFICIAL_URL)
        self.assertEqual(self.source_receipt["http_status"], 200)
        self.assertEqual(self.source_receipt["https_get_count"], 1)
        self.assertEqual(self.source_receipt["max_retries"], 0)
        self.assertEqual(self.source_receipt["response_encoding"], "cp950")
        self.assertTrue(str(self.source_receipt["tls_version"]).startswith("TLS"))
        self.assertIn(
            "Taiwan Stock Exchange Corporation",
            self.source_receipt["certificate_subject"],
        )
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
        fixture = self.frozen_phase_a_root()
        _, formal_rows = self.module.read_csv(fixture / "data/2317_daily_price.csv")
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
                fixture / "data/2317_daily_market_activity.csv"
            )
            if row["date"] not in self.module.FULL_MARKET_DATES
        ]
        self.module.atomic_write = (
            lambda path, value: writes.__setitem__(Path(path).name, value)
        )
        self.module.read_formal_activity = lambda _path: stage1_rows
        try:
            result = self.module.build_market_candidate(
                fixture,
                self.twse,
                expected_price,
                fixture / "runtime" / "test-review",
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
        fixture = self.frozen_phase_a_root()
        output_dir = (
            fixture
            / "runtime"
            / "phase_a_test_temp"
            / f"stage1-market-{uuid.uuid4().hex}"
        )
        formal_paths = [
            fixture / self.module.FORMAL_DAILY,
            fixture / self.module.FORMAL_MARKET,
            fixture / self.module.FORMAL_MACRO,
            fixture / self.module.MANIFEST,
        ]
        before = {path: self.module.sha256_file(path) for path in formal_paths}
        original_read_formal_activity = self.module.read_formal_activity
        stage1_rows = [
            row
            for row in original_read_formal_activity(
                fixture / "data/2317_daily_market_activity.csv"
            )
            if row["date"] not in self.module.FULL_MARKET_DATES
        ]
        self.module.read_formal_activity = lambda _path: stage1_rows
        try:
            result = self.module.build_stage1_market_activity_candidate(
                fixture, TWSE_EVIDENCE_DIR, output_dir
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
                {
                    row["date"]: row["twse_close"]
                    for row in result["candidate_rows"]
                },
                {
                    "2026-07-20": "234.50",
                    "2026-07-21": "246.00",
                    "2026-07-22": "251.50",
                    "2026-07-23": "257.50",
                    "2026-07-24": "252.50",
                    "2026-07-27": "253.00",
                },
            )
            self.assertEqual(
                before,
                {path: self.module.sha256_file(path) for path in formal_paths},
            )
        finally:
            self.module.read_formal_activity = original_read_formal_activity
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_published_macro_remediation_has_no_remaining_invalid_values(self) -> None:
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
        self.assertEqual(invalid_values, [])
        self.assertEqual(rows, [])
        self.assertEqual(
            self.module.sha256_file(ROOT / "data/macro_snapshot.csv"),
            "7C3E5F320FBD7F1558CBA670246B5A3062060769A0420A105A4CAF8499DABC63",
        )


if __name__ == "__main__":
    unittest.main()
