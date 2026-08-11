from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TOOLS = PACKAGE_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import owner_publish_csv_v2 as publisher  # noqa: E402
import warroom_authority_freshness as freshness  # noqa: E402
import warroom_daily_price_updater as updater  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class DailyPriceIncrementalUpdaterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = PACKAGE_ROOT / "runtime/daily_price_incremental_test_scratch" / uuid.uuid4().hex
        (self.root / "data").mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(self.root) if self.root.exists() else None)
        price = self.root / updater.PRICE_REL
        with price.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(updater.PRICE_FIELDS)
            writer.writerows(
                [
                    ["2026-07-17", "234", "2026Q1", "127.12", "1.841", "OFFICIAL_TWSE_A1", "OK"],
                    ["2026-07-19", "234", "2026Q1", "127.12", "1.841", "PUBLIC_MARKET_DATA", "OK"],
                    ["2026-07-20", "234.5", "2026Q1", "127.12", "1.845", "OFFICIAL_TWSE_A1", "OK"],
                ]
            )
        activity = self.root / updater.ACTIVITY_REL
        with activity.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(publisher.MARKET_ACTIVITY_FIELDS)
            writer.writerow(["2026-07-17", "2317", "1000", "200000", "100", "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260701&stockNo=2317&response=csv", "2026-07"])
        manifest = {
            "authoritativeFiles": [
                {"path": publisher.DAILY_TARGET, "sha256": sha(price), "rowCount": 3, "columns": list(updater.PRICE_FIELDS), "dateRange": {"start": "2026-07-17", "end": "2026-07-20"}},
                {"path": publisher.MARKET_ACTIVITY_TARGET, "sha256": sha(activity), "rowCount": 1, "dateRange": {"start": "2026-07-17", "end": "2026-07-17"}},
            ]
        }
        (self.root / publisher.MANIFEST_PATH).write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        self.receipts = self.root / "fixtures"
        self._write_month()

    def _write_month(self) -> None:
        self.receipts.mkdir()
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["2026-07 2317 鴻海個股日成交資訊"])
        writer.writerow(["日期", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌價差", "成交筆數"])
        for roc, close in (("115/07/17", "234.00"), ("115/07/20", "234.50"), ("115/07/21", "246.00"), ("115/07/22", "251.50")):
            writer.writerow([roc, "1,000", "200,000", close, close, close, close, "0", "100"])
        raw = self.receipts / "2026-07.twse.raw.csv"
        raw.write_bytes(output.getvalue().encode("cp950"))
        (self.receipts / "2026-07.receipt.json").write_text(
            json.dumps({"status": "SUCCESS", "request_url": "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260701&stockNo=2317&response=csv", "raw_artifact_sha256": sha(raw)}) + "\n",
            encoding="utf-8",
        )

    def test_missing_dates_weekend_removal_and_idempotency(self) -> None:
        first = updater.run_update(self.root, as_of_date=dt.date(2026, 7, 22), offline_receipt_dir=self.receipts)
        first_hash = sha(self.root / updater.PRICE_REL)
        second = updater.run_update(self.root, as_of_date=dt.date(2026, 7, 22), offline_receipt_dir=self.receipts)
        with (self.root / updater.PRICE_REL).open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        by_date = {row["Date"]: row for row in rows}
        self.assertEqual(first["dates_added"], ["2026-07-21", "2026-07-22"])
        self.assertEqual(first["non_trading_dates_removed"], ["2026-07-19"])
        self.assertEqual(by_date["2026-07-22"]["Close"], "251.5")
        self.assertEqual(by_date["2026-07-22"]["DataSupportLevel"], "OFFICIAL_TWSE_A1")
        self.assertNotIn("2026-07-19", by_date)
        self.assertEqual(first_hash, sha(self.root / updater.PRICE_REL))
        self.assertEqual(second["status"], "NO_NEW_DAILY_PRICE")
        manifest = publisher.read_json(self.root / publisher.MANIFEST_PATH)
        entry = next(item for item in manifest["authoritativeFiles"] if item["path"] == publisher.DAILY_TARGET)
        self.assertEqual(entry["sha256"], first_hash)

    def test_conflicting_close_fails_closed_without_mutation(self) -> None:
        with (self.root / updater.PRICE_REL).open(encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        rows[-1][1] = "999"
        with (self.root / updater.PRICE_REL).open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle, lineterminator="\n").writerows(rows)
        manifest = publisher.read_json(self.root / publisher.MANIFEST_PATH)
        next(item for item in manifest["authoritativeFiles"] if item["path"] == publisher.DAILY_TARGET)["sha256"] = sha(self.root / updater.PRICE_REL)
        (self.root / publisher.MANIFEST_PATH).write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        before = sha(self.root / updater.PRICE_REL)
        with self.assertRaises(updater.PriceUpdateFailure):
            updater.run_update(self.root, as_of_date=dt.date(2026, 7, 22), offline_receipt_dir=self.receipts)
        self.assertEqual(before, sha(self.root / updater.PRICE_REL))

    def test_freshness_rejects_market_activity_lag(self) -> None:
        updater.run_update(self.root, as_of_date=dt.date(2026, 7, 22), offline_receipt_dir=self.receipts)
        with self.assertRaises(freshness.FreshnessFailure) as raised:
            freshness.validate(self.root, self.receipts)
        self.assertIn("missing_market_activity", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
