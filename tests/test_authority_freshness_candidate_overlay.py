from __future__ import annotations

import csv
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
import warroom_market_activity_updater as updater  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class CandidateOverlayFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = PACKAGE_ROOT / "runtime/authority_freshness_test_scratch" / uuid.uuid4().hex
        (self.root / "data").mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.daily_id = "P1008-DAILY-PRICE-TEST"
        self.market_id = "P1008-MARKET-ACTIVITY-TEST"
        self.daily_dir = self.root / "runtime/daily_price_incremental" / self.daily_id
        self.market_dir = self.root / "runtime/market_activity_incremental" / self.market_id
        (self.daily_dir / "receipts").mkdir(parents=True)
        (self.market_dir / "receipts").mkdir(parents=True)
        self._write_formal()
        self._write_run(self.daily_dir, daily=True)
        self._write_run(self.market_dir, daily=False)

    def _csv(self, path: Path, fields: tuple[str, ...], rows: list[list[str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(fields)
            writer.writerows(rows)

    def _write_formal(self) -> None:
        price = self.root / publisher.DAILY_TARGET
        activity = self.root / publisher.MARKET_ACTIVITY_TARGET
        self._csv(
            price,
            updater.PRICE_CANDIDATE_FIELDS,
            [["2026-07-20", "234.5", "2026Q1", "127.12", "1.845", "OFFICIAL_TWSE_A1", "OK"]],
        )
        self._csv(
            activity,
            updater.FORMAL_FIELDS,
            [["2026-07-20", "2317", "1000", "234500", "100", updater.source_url("2026-07"), "2026-07"]],
        )
        manifest = {
            "authoritativeFiles": [
                {"path": publisher.DAILY_TARGET, "sha256": sha(price)},
                {"path": publisher.MARKET_ACTIVITY_TARGET, "sha256": sha(activity)},
            ]
        }
        (self.root / publisher.MANIFEST_PATH).write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    @staticmethod
    def _raw(days: tuple[str, ...] = ("115/07/20", "115/07/21", "115/07/22")) -> bytes:
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["2026-07 2317 test"])
        writer.writerow(["date", "volume", "value", "open", "high", "low", "close", "change", "count"])
        values = {
            "115/07/20": ("1,000", "234,500", "234.50", "100"),
            "115/07/21": ("2,000", "492,000", "246.00", "200"),
            "115/07/22": ("3,000", "754,500", "251.50", "300"),
        }
        for day in days:
            volume, value, close, count = values[day]
            writer.writerow([day, volume, value, close, close, close, close, "0", count])
        return output.getvalue().encode("cp950")

    def _write_receipt(self, receipts: Path, days: tuple[str, ...] = ("115/07/20", "115/07/21", "115/07/22")) -> Path:
        raw = receipts / "2026-07.twse.raw.csv"
        raw.write_bytes(self._raw(days))
        receipt = receipts / "2026-07.receipt.json"
        receipt.write_text(
            json.dumps(
                {
                    "month": "2026-07",
                    "status": "SUCCESS",
                    "http_status": 200,
                    "request_url": updater.source_url("2026-07"),
                    "raw_artifact_sha256": sha(raw),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return receipt

    def _write_run(self, run_dir: Path, *, daily: bool, days: tuple[str, ...] = ("115/07/20", "115/07/21", "115/07/22")) -> None:
        receipt = self._write_receipt(run_dir / "receipts", days)
        if daily:
            candidate = run_dir / "2317_daily_price.incremental.candidate.csv"
            self._csv(
                candidate,
                updater.PRICE_CANDIDATE_FIELDS,
                [
                    ["2026-07-20", "234.5", "2026Q1", "127.12", "1.845", "OFFICIAL_TWSE_A1", "OK"],
                    ["2026-07-21", "246.0", "2026Q1", "127.12", "1.935", "OFFICIAL_TWSE_A1", "OK"],
                    ["2026-07-22", "251.5", "2026Q1", "127.12", "1.978", "OFFICIAL_TWSE_A1", "OK"],
                ],
            )
            result = {
                "run_id": self.daily_id,
                "run_dir": str(run_dir.resolve()),
                "status": "DRY_RUN_READY",
                "launcher_status": "UPDATED",
                "dry_run": True,
                "exit_code": 0,
                "actionable": False,
                "candidate_path": str(candidate.resolve()),
                "candidate_sha256": sha(candidate),
                "receipt_paths": [str(receipt.resolve())],
                "twse_latest_validated_trading_date": "2026-07-22",
            }
        else:
            candidate = run_dir / "2317_daily_market_activity.incremental.candidate.csv"
            self._csv(
                candidate,
                updater.FORMAL_FIELDS,
                [
                    ["2026-07-21", "2317", "2000", "492000", "200", updater.source_url("2026-07"), "2026-07"],
                    ["2026-07-22", "2317", "3000", "754500", "300", updater.source_url("2026-07"), "2026-07"],
                ],
            )
            daily_result = json.loads((self.daily_dir / "RESULT.json").read_text(encoding="utf-8"))
            result = {
                "run_id": self.market_id,
                "run_dir": str(run_dir.resolve()),
                "status": "DRY_RUN_READY",
                "launcher_status": "UPDATED",
                "dry_run": True,
                "exit_code": 0,
                "actionable": False,
                "candidate_path": str(candidate.resolve()),
                "candidate_sha256": sha(candidate),
                "receipt_paths": [str(receipt.resolve())],
                "candidate_last_date": "2026-07-22",
                "price_validation_provenance": {
                    "source": "SAME_RUN_DAILY_PRICE_STAGING",
                    "daily_price_run_id": self.daily_id,
                    "daily_price_run_dir": str(self.daily_dir.resolve()),
                    "daily_price_candidate_sha256": daily_result["candidate_sha256"],
                    "daily_price_receipt_paths": daily_result["receipt_paths"],
                },
            }
        (run_dir / "RESULT.json").write_text(json.dumps(result) + "\n", encoding="utf-8")

    def validate(self) -> dict[str, object]:
        return freshness.validate_candidate_overlay(
            self.root,
            daily_price_run_dir=self.daily_dir,
            daily_price_run_id=self.daily_id,
            market_activity_run_dir=self.market_dir,
            market_activity_run_id=self.market_id,
        )

    def test_formal_stale_same_run_candidates_pass_without_mutation(self) -> None:
        before = {
            rel: sha(self.root / rel)
            for rel in (publisher.DAILY_TARGET, publisher.MARKET_ACTIVITY_TARGET, publisher.MANIFEST_PATH)
        }
        with self.assertRaises(freshness.FreshnessFailure):
            freshness.validate(self.root, self.market_dir / "receipts")
        result = self.validate()
        self.assertEqual(result["status"], "PASS_CANDIDATE_OVERLAY")
        self.assertTrue(result["owner_publish_required"])
        self.assertFalse(result["formal_authority_current"])
        self.assertEqual(result["candidate_validated_through"], "2026-07-22")
        self.assertEqual(
            freshness.main(
                [
                    "--package-root", str(self.root),
                    "--daily-price-run-dir", str(self.daily_dir),
                    "--daily-price-run-id", self.daily_id,
                    "--market-activity-run-dir", str(self.market_dir),
                    "--market-activity-run-id", self.market_id,
                ]
            ),
            freshness.EXIT_OK,
        )
        self.assertEqual(
            before,
            {
                rel: sha(self.root / rel)
                for rel in (publisher.DAILY_TARGET, publisher.MARKET_ACTIVITY_TARGET, publisher.MANIFEST_PATH)
            },
        )

    def test_candidate_sha_tamper_fails_closed(self) -> None:
        with (self.daily_dir / "2317_daily_price.incremental.candidate.csv").open("a", encoding="utf-8") as handle:
            handle.write("\n")
        with self.assertRaisesRegex(freshness.FreshnessFailure, "candidate path or SHA"):
            self.validate()
        self.assertEqual(
            freshness.main(
                [
                    "--package-root", str(self.root),
                    "--daily-price-run-dir", str(self.daily_dir),
                    "--daily-price-run-id", self.daily_id,
                    "--market-activity-run-dir", str(self.market_dir),
                    "--market-activity-run-id", self.market_id,
                ]
            ),
            freshness.EXIT_STALE,
        )

    def test_bad_run_id_fails_closed(self) -> None:
        with self.assertRaises(freshness.FreshnessFailure):
            freshness.validate_candidate_overlay(
                self.root,
                daily_price_run_dir=self.daily_dir,
                daily_price_run_id="P1008-DAILY-PRICE-STALE",
                market_activity_run_dir=self.market_dir,
                market_activity_run_id=self.market_id,
            )

    def test_candidate_outside_run_fails_closed(self) -> None:
        result_path = self.daily_dir / "RESULT.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["candidate_path"] = str((self.root / publisher.DAILY_TARGET).resolve())
        result["candidate_sha256"] = sha(self.root / publisher.DAILY_TARGET)
        result_path.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaises(freshness.FreshnessFailure):
            self.validate()

    def test_missing_result_fails_closed(self) -> None:
        (self.market_dir / "RESULT.json").unlink()
        with self.assertRaises(freshness.FreshnessFailure):
            self.validate()

    def test_stale_previous_run_provenance_fails_closed(self) -> None:
        result_path = self.market_dir / "RESULT.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["price_validation_provenance"]["daily_price_run_id"] = "P1008-DAILY-PRICE-PREVIOUS"
        result_path.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(freshness.FreshnessFailure, "same-run"):
            self.validate()

    def test_candidate_targets_disagree_fails_closed(self) -> None:
        shutil.rmtree(self.market_dir)
        (self.market_dir / "receipts").mkdir(parents=True)
        self._write_run(self.market_dir, daily=False, days=("115/07/20", "115/07/21"))
        result_path = self.market_dir / "RESULT.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["candidate_last_date"] = "2026-07-21"
        candidate = self.market_dir / "2317_daily_market_activity.incremental.candidate.csv"
        with candidate.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))[:-1]
        with candidate.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle, lineterminator="\n").writerows(rows)
        result["candidate_sha256"] = sha(candidate)
        result_path.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(freshness.FreshnessFailure, "target disagreement"):
            self.validate()

    def test_market_activity_value_mismatch_fails_closed(self) -> None:
        candidate = self.market_dir / "2317_daily_market_activity.incremental.candidate.csv"
        with candidate.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        rows[-1][3] = "999"
        with candidate.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle, lineterminator="\n").writerows(rows)
        result_path = self.market_dir / "RESULT.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["candidate_sha256"] = sha(candidate)
        result_path.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(freshness.FreshnessFailure, "market_activity_mismatches"):
            self.validate()

    def test_formal_manifest_corruption_fails_closed(self) -> None:
        with (self.root / publisher.DAILY_TARGET).open("a", encoding="utf-8") as handle:
            handle.write("\n")
        with self.assertRaisesRegex(freshness.FreshnessFailure, "manifest_errors"):
            self.validate()

    def test_formal_no_new_data_path_remains_strict(self) -> None:
        price_candidate = self.daily_dir / "2317_daily_price.incremental.candidate.csv"
        shutil.copyfile(price_candidate, self.root / publisher.DAILY_TARGET)
        activity_candidate = self.market_dir / "2317_daily_market_activity.incremental.candidate.csv"
        with activity_candidate.open(encoding="utf-8", newline="") as handle:
            candidate_rows = list(csv.DictReader(handle))
        with (self.root / publisher.MARKET_ACTIVITY_TARGET).open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=updater.FORMAL_FIELDS, lineterminator="\n")
            writer.writerows(candidate_rows)
        manifest = publisher.read_json(self.root / publisher.MANIFEST_PATH)
        for entry in manifest["authoritativeFiles"]:
            entry["sha256"] = sha(self.root / entry["path"])
        (self.root / publisher.MANIFEST_PATH).write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        self.assertEqual(
            freshness.validate(self.root, self.market_dir / "receipts")["freshness_scope"],
            "FORMAL_AUTHORITY",
        )
        rows = (self.root / publisher.MARKET_ACTIVITY_TARGET).read_text(encoding="utf-8").splitlines()
        (self.root / publisher.MARKET_ACTIVITY_TARGET).write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")
        manifest = publisher.read_json(self.root / publisher.MANIFEST_PATH)
        next(entry for entry in manifest["authoritativeFiles"] if entry["path"] == publisher.MARKET_ACTIVITY_TARGET)["sha256"] = sha(self.root / publisher.MARKET_ACTIVITY_TARGET)
        (self.root / publisher.MANIFEST_PATH).write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        with self.assertRaises(freshness.FreshnessFailure):
            freshness.validate(self.root, self.market_dir / "receipts")


if __name__ == "__main__":
    unittest.main()
