from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import shutil
import sys
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TOOLS = PACKAGE_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import owner_publish_csv_v2 as publisher  # noqa: E402
import warroom_market_activity_updater as updater  # noqa: E402


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class MarketActivityIncrementalUpdaterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = (
            PACKAGE_ROOT
            / "runtime"
            / "market_activity_incremental_test_scratch"
            / uuid.uuid4().hex
        )
        (self.root / "data").mkdir(parents=True)
        (self.root / "runtime").mkdir()
        self.addCleanup(self.cleanup_root)

    def cleanup_root(self) -> None:
        for _ in range(5):
            if not self.root.exists():
                return
            try:
                shutil.rmtree(self.root)
                return
            except OSError:
                time.sleep(0.05)

    def write_authority(
        self,
        activity_rows: list[dict[str, object]],
        price_rows: list[tuple[str, str]],
    ) -> None:
        activity_path = self.root / updater.FORMAL_REL
        with activity_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=updater.FORMAL_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(activity_rows)
        with (self.root / updater.PRICE_REL).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["Date", "Close"])
            writer.writerows(price_rows)
        manifest = {
            "approvedAt": "2026-07-18",
            "approvalSource": "test",
            "authoritativeFiles": [
                {
                    "path": "data/2317_daily_market_activity.csv",
                    "sha256": hash_file(activity_path),
                    "rowCount": len(activity_rows),
                    "dateRange": {
                        "start": activity_rows[0]["date"],
                        "end": activity_rows[-1]["date"],
                    },
                    "analysisStatus": updater.STATUS_READY,
                }
            ],
        }
        (self.root / publisher.MANIFEST_PATH).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    @staticmethod
    def activity(day: str, volume: int = 1000, value: int = 200000, transactions: int = 100) -> dict[str, object]:
        month = day[:7]
        return {
            "date": day,
            "stock_id": "2317",
            "trade_volume": volume,
            "trade_value": value,
            "transaction_count": transactions,
            "source_url": updater.source_url(month),
            "source_month": month,
        }

    def write_month(self, receipt_dir: Path, month: str, rows: list[tuple[str, int, int, str, int]]) -> None:
        receipt_dir.mkdir(parents=True, exist_ok=True)
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow([f"{month} 2317 鴻海個股日成交資訊"])
        writer.writerow(["日期", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌價差", "成交筆數"])
        for day, volume, value, close, transactions in rows:
            parsed = dt.date.fromisoformat(day)
            roc = f"{parsed.year - 1911:03d}/{parsed.month:02d}/{parsed.day:02d}"
            writer.writerow([roc, f"{volume:,}", f"{value:,}", close, close, close, close, "0", f"{transactions:,}"])
        content = output.getvalue().encode("cp950")
        raw_path = receipt_dir / f"{month}.twse.raw.csv"
        raw_path.write_bytes(content)
        receipt = {
            "status": "SUCCESS",
            "request_url": updater.source_url(month),
            "http_status": 200,
            "tls_version": "TLSv1.3",
            "certificate_issuer": "TWCA",
            "raw_artifact_sha256": hash_file(raw_path),
        }
        (receipt_dir / f"{month}.receipt.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )

    def test_no_new_date_is_success_and_does_not_change_authority(self) -> None:
        row = self.activity("2026-07-17")
        self.write_authority([row], [("2026-07-17", "234")])
        receipts = self.root / "fixtures"
        self.write_month(receipts, "2026-07", [("2026-07-17", 1000, 200000, "234", 100)])
        before = (hash_file(self.root / updater.FORMAL_REL), hash_file(self.root / publisher.MANIFEST_PATH))
        result = updater.run_update(
            self.root,
            as_of_date=dt.date(2026, 7, 17),
            dry_run=True,
            offline_receipt_dir=receipts,
        )
        self.assertEqual(result["status"], updater.STATUS_NO_NEW)
        self.assertEqual(result["http_calls"], 0)
        self.assertEqual(before, (hash_file(self.root / updater.FORMAL_REL), hash_file(self.root / publisher.MANIFEST_PATH)))

    def test_new_date_creates_candidate_and_repeat_keeps_formal_idempotent(self) -> None:
        self.write_authority([self.activity("2026-07-16")], [("2026-07-16", "233"), ("2026-07-17", "234")])
        receipts = self.root / "fixtures"
        self.write_month(
            receipts,
            "2026-07",
            [("2026-07-16", 1000, 200000, "233", 100), ("2026-07-17", 1200, 250000, "234", 120)],
        )
        before = (
            hash_file(self.root / updater.FORMAL_REL),
            hash_file(self.root / updater.MANIFEST_REL),
        )
        first = updater.run_update(self.root, as_of_date=dt.date(2026, 7, 17), offline_receipt_dir=receipts)
        second = updater.run_update(self.root, as_of_date=dt.date(2026, 7, 17), offline_receipt_dir=receipts)
        with (self.root / updater.FORMAL_REL).open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(first["status"], updater.STATUS_CANDIDATE_READY)
        self.assertEqual(second["status"], updater.STATUS_CANDIDATE_READY)
        self.assertEqual(first["candidate_rows"], 1)
        self.assertEqual(second["candidate_rows"], 1)
        self.assertEqual([row["date"] for row in rows], ["2026-07-16"])
        self.assertEqual(
            before,
            (
                hash_file(self.root / updater.FORMAL_REL),
                hash_file(self.root / updater.MANIFEST_REL),
            ),
        )

    def test_cross_month_uses_required_months_only(self) -> None:
        self.write_authority([self.activity("2026-06-30")], [("2026-06-30", "230"), ("2026-07-01", "231")])
        receipts = self.root / "fixtures"
        self.write_month(receipts, "2026-06", [("2026-06-30", 1000, 200000, "230", 100)])
        self.write_month(receipts, "2026-07", [("2026-07-01", 1100, 220000, "231", 110)])
        result = updater.run_update(
            self.root,
            as_of_date=dt.date(2026, 7, 1),
            dry_run=True,
            offline_receipt_dir=receipts,
        )
        self.assertEqual(result["months_checked"], ["2026-06", "2026-07"])
        self.assertEqual(result["candidate_rows"], 1)

    def test_more_than_three_months_fails_closed(self) -> None:
        with self.assertRaises(updater.UpdateFailure):
            updater.month_sequence("2026-04", "2026-08")

    def test_close_mismatch_blocks_publish(self) -> None:
        self.write_authority([self.activity("2026-07-16")], [("2026-07-16", "233"), ("2026-07-17", "235")])
        receipts = self.root / "fixtures"
        self.write_month(
            receipts,
            "2026-07",
            [("2026-07-16", 1000, 200000, "233", 100), ("2026-07-17", 1200, 250000, "234", 120)],
        )
        before = hash_file(self.root / updater.FORMAL_REL)
        with self.assertRaises(updater.UpdateFailure) as raised:
            updater.run_update(self.root, as_of_date=dt.date(2026, 7, 17), offline_receipt_dir=receipts)
        self.assertEqual(raised.exception.status, updater.STATUS_BLOCKED)
        self.assertEqual(hash_file(self.root / updater.FORMAL_REL), before)

    def test_https_failure_has_no_fallback(self) -> None:
        with mock.patch.object(updater.http.client, "HTTPSConnection", side_effect=OSError("TLS failed")):
            with self.assertRaises(updater.UpdateFailure):
                updater.fetch_twse_month("2026-07")

    def test_publisher_rolls_back_csv_and_manifest(self) -> None:
        self.write_authority([self.activity("2026-07-16")], [("2026-07-16", "233"), ("2026-07-17", "234")])
        candidate = self.root / "runtime/candidate.csv"
        updater.write_candidate(candidate, [self.activity("2026-07-17", 1200, 250000, 120)])
        formal = self.root / updater.FORMAL_REL
        manifest = self.root / publisher.MANIFEST_PATH
        before = (hash_file(formal), hash_file(manifest))
        original = publisher._atomic_write_bytes
        failed = False

        def fail_manifest_once(path: Path, content: bytes) -> None:
            nonlocal failed
            if path.resolve() == manifest.resolve() and not failed:
                failed = True
                raise OSError("simulated manifest failure")
            original(path, content)

        with mock.patch.object(publisher, "_atomic_write_bytes", side_effect=fail_manifest_once):
            with self.assertRaises(RuntimeError):
                publisher.publish_market_activity_append(
                    self.root,
                    candidate,
                    self.root / "runtime/publish",
                    approval_phrase=publisher.market_activity_approval_phrase(
                        ["2026-07-17"]
                    ),
                )
        self.assertEqual(before, (hash_file(formal), hash_file(manifest)))
        journal = json.loads((self.root / "runtime/publish/PUBLISH_JOURNAL.json").read_text(encoding="utf-8"))
        self.assertEqual(journal["status"], "ROLLED_BACK")

    def test_publisher_preserves_historical_bytes_as_exact_prefix(self) -> None:
        self.write_authority([self.activity("2026-07-16")], [("2026-07-16", "233"), ("2026-07-17", "234")])
        candidate = self.root / "runtime/candidate.csv"
        updater.write_candidate(candidate, [self.activity("2026-07-17", 1200, 250000, 120)])
        formal = self.root / updater.FORMAL_REL
        historical = formal.read_bytes()
        publisher.publish_market_activity_append(
            self.root,
            candidate,
            self.root / "runtime/publish",
            approval_phrase=publisher.market_activity_approval_phrase(["2026-07-17"]),
        )
        self.assertTrue(formal.read_bytes().startswith(historical))

    def test_publisher_requires_explicit_owner_approval_phrase(self) -> None:
        self.write_authority(
            [self.activity("2026-07-16")],
            [("2026-07-16", "233"), ("2026-07-17", "234")],
        )
        candidate = self.root / "runtime/candidate.csv"
        updater.write_candidate(
            candidate, [self.activity("2026-07-17", 1200, 250000, 120)]
        )
        before = hash_file(self.root / updater.FORMAL_REL)
        with self.assertRaisesRegex(ValueError, "exact Owner approval phrase"):
            publisher.publish_market_activity_append(
                self.root, candidate, self.root / "runtime/publish"
            )
        self.assertEqual(hash_file(self.root / updater.FORMAL_REL), before)

    def test_four_gap_dates_candidate_has_official_sources_and_no_zero_fill(self) -> None:
        price_rows = [
            ("2026-07-17", "234"),
            ("2026-07-19", "234"),
            ("2026-07-20", "234.5"),
            ("2026-07-21", "246"),
            ("2026-07-23", "257.5"),
            ("2026-07-27", "253"),
        ]
        self.write_authority([self.activity("2026-07-17")], price_rows)
        receipts = self.root / "fixtures"
        self.write_month(
            receipts,
            "2026-07",
            [
                ("2026-07-17", 1000, 200000, "234", 100),
                ("2026-07-20", 1200, 240000, "234.5", 120),
                ("2026-07-21", 1300, 260000, "246", 130),
                ("2026-07-22", 1350, 270000, "250", 135),
                ("2026-07-23", 1400, 280000, "257.5", 140),
                ("2026-07-24", 1450, 290000, "255", 145),
                ("2026-07-27", 1500, 300000, "253", 150),
            ],
        )
        result = updater.run_update(
            self.root,
            as_of_date=dt.date(2026, 7, 27),
            offline_receipt_dir=receipts,
        )
        with Path(result["candidate_path"]).open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(
            [row["date"] for row in rows],
            ["2026-07-20", "2026-07-21", "2026-07-23", "2026-07-27"],
        )
        self.assertEqual(
            result["price_authority_missing_dates"],
            ["2026-07-22", "2026-07-24"],
        )
        self.assertEqual(result["ignored_invalid_price_dates"], ["2026-07-19"])
        self.assertEqual(
            result["market_liquidity_analysis_status"], updater.STATUS_LIMITED
        )
        self.assertTrue(
            all(
                row["source_url"].startswith(
                    "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?"
                )
                for row in rows
            )
        )
        self.assertTrue(
            all(
                int(row[field]) > 0
                for row in rows
                for field in (
                    "trade_volume",
                    "trade_value",
                    "transaction_count",
                )
            )
        )

    def test_update_lock_rejects_duplicate_execution(self) -> None:
        runtime_root = self.root / updater.RUNTIME_REL
        with updater.update_lock(runtime_root):
            with self.assertRaises(updater.UpdateFailure) as raised:
                with updater.update_lock(runtime_root):
                    pass
        self.assertEqual(raised.exception.exit_code, updater.EXIT_LOCKED)

    def test_bat_has_bundled_python_only_and_no_system_fallback(self) -> None:
        wrapper = (PACKAGE_ROOT / "tools/p1008_update_market_activity.cmd").read_text(encoding="utf-8")
        self.assertIn("codex-primary-runtime\\dependencies\\python\\python.exe", wrapper)
        self.assertIn("sys.version_info[:2] == (3, 12)", wrapper)
        self.assertNotIn("where.exe", wrapper)
        self.assertNotIn("pythoncore-3.14", wrapper)

    def test_updater_has_no_formal_publish_call(self) -> None:
        source = (
            PACKAGE_ROOT / "tools/warroom_market_activity_updater.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("publish_market_activity_append(", source)
        self.assertIn('"candidate_only": True', source)
        self.assertIn('"owner_publish_required": True', source)


if __name__ == "__main__":
    unittest.main()
