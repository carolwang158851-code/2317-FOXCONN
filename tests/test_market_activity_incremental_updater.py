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
            "month": month,
            "request_url": updater.source_url(month),
            "http_status": 200,
            "tls_version": "TLSv1.3",
            "certificate_issuer": "TWCA",
            "raw_artifact_sha256": hash_file(raw_path),
        }
        (receipt_dir / f"{month}.receipt.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )

    def write_valid_daily_price_staging(
        self,
        *,
        rows: list[tuple[str, str]],
        anchor_date: str,
        receipts: Path,
        run_id: str = "P1008-DAILY-PRICE-TEST-RUN",
    ) -> tuple[Path, str]:
        run_dir = self.root / "runtime" / "daily_price_incremental" / run_id
        receipts_dir = run_dir / "receipts"
        receipts_dir.mkdir(parents=True)
        for path in receipts.glob("*"):
            shutil.copy2(path, receipts_dir / path.name)
        candidate = run_dir / "2317_daily_price.incremental.candidate.csv"
        with candidate.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=updater.PRICE_CANDIDATE_FIELDS, lineterminator="\n")
            writer.writeheader()
            for day, close in rows:
                writer.writerow({
                    "Date": day, "Close": close, "QuarterKey": "2026Q1",
                    "BVPS_ref": "127.12", "PB_daily": "1.978",
                    "DataSupportLevel": "OFFICIAL_TWSE_A1", "Status": "OK",
                })
        receipt_paths = [str(path.resolve()) for path in sorted(receipts_dir.glob("*.receipt.json"))]
        result = {
            "run_id": run_id,
            "status": "DRY_RUN_READY",
            "launcher_status": "UPDATED",
            "anchor_date": anchor_date,
            "candidate_path": str(candidate.resolve()),
            "candidate_sha256": hash_file(candidate),
            "receipt_paths": receipt_paths,
            "dry_run": True,
            "exit_code": 0,
            "actionable": False,
        }
        (run_dir / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return run_dir, run_id

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

    def test_new_date_appends_once_and_repeat_is_idempotent(self) -> None:
        self.write_authority([self.activity("2026-07-16")], [("2026-07-16", "233"), ("2026-07-17", "234")])
        receipts = self.root / "fixtures"
        self.write_month(
            receipts,
            "2026-07",
            [("2026-07-16", 1000, 200000, "233", 100), ("2026-07-17", 1200, 250000, "234", 120)],
        )
        first = updater.run_update(self.root, as_of_date=dt.date(2026, 7, 17), offline_receipt_dir=receipts)
        second = updater.run_update(self.root, as_of_date=dt.date(2026, 7, 17), offline_receipt_dir=receipts)
        with (self.root / updater.FORMAL_REL).open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(first["status"], updater.STATUS_UPDATED)
        self.assertEqual(first["rows_added"], 1)
        self.assertEqual(second["status"], updater.STATUS_NO_NEW)
        self.assertEqual([row["date"] for row in rows], ["2026-07-16", "2026-07-17"])

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

    def test_exit_20_when_price_authority_lacks_twse_date(self) -> None:
        self.write_authority(
            [self.activity("2026-07-21")],
            [("2026-07-21", "246")],
        )
        receipts = self.root / "fixtures"
        self.write_month(
            receipts,
            "2026-07",
            [
                ("2026-07-21", 1000, 200000, "246", 100),
                ("2026-07-22", 1200, 250000, "251.5", 120),
            ],
        )
        before = hash_file(self.root / updater.FORMAL_REL)
        with self.assertRaisesRegex(
            updater.UpdateFailure,
            "Price authority does not contain TWSE date 2026-07-22",
        ) as raised:
            updater.run_update(
                self.root,
                as_of_date=dt.date(2026, 7, 22),
                offline_receipt_dir=receipts,
            )
        self.assertEqual(raised.exception.exit_code, updater.EXIT_BLOCKED)
        self.assertEqual(hash_file(self.root / updater.FORMAL_REL), before)

    def test_valid_same_run_staging_allows_missing_formal_price_date(self) -> None:
        self.write_authority([self.activity("2026-07-21")], [("2026-07-21", "246")])
        receipts = self.root / "fixtures"
        self.write_month(receipts, "2026-07", [
            ("2026-07-21", 1000, 200000, "246", 100),
            ("2026-07-22", 1200, 250000, "251.5", 120),
        ])
        run_dir, run_id = self.write_valid_daily_price_staging(
            rows=[("2026-07-21", "246"), ("2026-07-22", "251.5")],
            anchor_date="2026-07-21", receipts=receipts,
        )
        result = updater.run_update(
            self.root, as_of_date=dt.date(2026, 7, 22), dry_run=True,
            offline_receipt_dir=receipts, daily_price_run_dir=run_dir,
            daily_price_run_id=run_id,
        )
        self.assertEqual(result["status"], "DRY_RUN_READY")
        self.assertEqual(result["candidate_rows"], 1)
        self.assertEqual(result["price_validation_provenance"]["source"], "SAME_RUN_DAILY_PRICE_STAGING")

    def test_same_run_staging_close_mismatch_fails_closed(self) -> None:
        self.write_authority([self.activity("2026-07-21")], [("2026-07-21", "246")])
        receipts = self.root / "fixtures"
        self.write_month(receipts, "2026-07", [
            ("2026-07-21", 1000, 200000, "246", 100),
            ("2026-07-22", 1200, 250000, "251.5", 120),
        ])
        run_dir, run_id = self.write_valid_daily_price_staging(
            rows=[("2026-07-21", "246"), ("2026-07-22", "252")],
            anchor_date="2026-07-21", receipts=receipts,
        )
        with self.assertRaisesRegex(updater.UpdateFailure, "Close does not match") as raised:
            updater.run_update(
                self.root, as_of_date=dt.date(2026, 7, 22), dry_run=True,
                offline_receipt_dir=receipts, daily_price_run_dir=run_dir,
                daily_price_run_id=run_id,
            )
        self.assertEqual(raised.exception.exit_code, updater.EXIT_BLOCKED)

    def test_same_run_staging_hash_or_lineage_failure_fails_closed(self) -> None:
        self.write_authority([self.activity("2026-07-21")], [("2026-07-21", "246")])
        receipts = self.root / "fixtures"
        self.write_month(receipts, "2026-07", [
            ("2026-07-21", 1000, 200000, "246", 100),
            ("2026-07-22", 1200, 250000, "251.5", 120),
        ])
        run_dir, run_id = self.write_valid_daily_price_staging(
            rows=[("2026-07-21", "246"), ("2026-07-22", "251.5")],
            anchor_date="2026-07-21", receipts=receipts,
        )
        result_path = run_dir / "RESULT.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["candidate_sha256"] = "0" * 64
        result_path.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(updater.UpdateFailure, "SHA") as raised:
            updater.run_update(
                self.root, as_of_date=dt.date(2026, 7, 22), dry_run=True,
                offline_receipt_dir=receipts, daily_price_run_dir=run_dir,
                daily_price_run_id=run_id,
            )
        self.assertEqual(raised.exception.exit_code, updater.EXIT_BLOCKED)

    def test_formal_price_remains_valid_without_same_run_staging(self) -> None:
        self.write_authority([self.activity("2026-07-21")], [("2026-07-21", "246"), ("2026-07-22", "251.5")])
        receipts = self.root / "fixtures"
        self.write_month(receipts, "2026-07", [
            ("2026-07-21", 1000, 200000, "246", 100),
            ("2026-07-22", 1200, 250000, "251.5", 120),
        ])
        result = updater.run_update(self.root, as_of_date=dt.date(2026, 7, 22), dry_run=True, offline_receipt_dir=receipts)
        self.assertEqual(result["status"], "DRY_RUN_READY")
        self.assertIsNone(result["price_validation_provenance"])

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
                    approval_phrase=publisher.market_activity_approval_phrase(["2026-07-17"]),
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

    def test_updater_delegates_atomic_publish_with_scoped_phrase(self) -> None:
        source = (
            PACKAGE_ROOT / "tools/warroom_market_activity_updater.py"
        ).read_text(encoding="utf-8")
        self.assertIn("publish_market_activity_append(", source)
        self.assertIn("market_activity_approval_phrase(", source)
        self.assertNotIn('"candidate_only": True', source)

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


if __name__ == "__main__":
    unittest.main()
