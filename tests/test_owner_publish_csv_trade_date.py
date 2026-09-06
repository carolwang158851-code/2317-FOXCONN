from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PUBLISHER_PATH = PACKAGE_ROOT / "tools" / "owner_publish_csv_v2.py"
SPEC = importlib.util.spec_from_file_location("p1008_trade_date_publisher", PUBLISHER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load publisher: {PUBLISHER_PATH}")
PUBLISHER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PUBLISHER
SPEC.loader.exec_module(PUBLISHER)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class OwnerPublishTradeDateTests(unittest.TestCase):
    DAILY_HEADER = [
        "Date", "Close", "QuarterKey", "BVPS_ref", "PB_daily",
        "DataSupportLevel", "Status",
    ]
    MARKET_HEADER = [
        "date", "stock_id", "trade_volume", "trade_value",
        "transaction_count", "source_url", "source_month",
    ]

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir()
        (self.root / "staging" / "2026-09-06").mkdir(parents=True)
        self._write_csv(
            self.root / PUBLISHER.DAILY_TARGET,
            self.DAILY_HEADER,
            [["2026-08-31", "200", "2026Q2", "100", "2.000", "OFFICIAL_TWSE_A1", "OK"]],
        )
        self._write_csv(
            self.root / PUBLISHER.MARKET_ACTIVITY_TARGET,
            self.MARKET_HEADER,
            [["2026-08-31", "2317", "1", "200", "1", "https://twse.example", "2026-08"]],
        )
        (self.root / PUBLISHER.MANIFEST_PATH).write_text(
            json.dumps({
                "authoritativeFiles": [
                    {"path": PUBLISHER.DAILY_TARGET},
                    {"path": PUBLISHER.MARKET_ACTIVITY_TARGET},
                ]
            }),
            encoding="utf-8",
        )

    @staticmethod
    def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(rows)

    def _stage_trade_pair(self, daily_date: str, market_date: str | None = None) -> dict:
        market_date = market_date or daily_date
        daily_run = "P1008-DAILY-PRICE-TEST"
        market_run = "P1008-MARKET-ACTIVITY-TEST"
        daily_dir = self.root / "runtime" / "daily_price_incremental" / daily_run
        market_dir = self.root / "runtime" / "market_activity_incremental" / market_run
        receipts = market_dir / "receipts"
        receipts.mkdir(parents=True)
        daily_candidate = daily_dir / "2317_daily_price.incremental.candidate.csv"
        market_candidate = market_dir / "2317_daily_market_activity.incremental.candidate.csv"
        self._write_csv(
            daily_candidate,
            self.DAILY_HEADER,
            [
                ["2026-08-31", "200", "2026Q2", "100", "2.000", "OFFICIAL_TWSE_A1", "OK"],
                [daily_date, "201", "2026Q2", "100", "2.010", "OFFICIAL_TWSE_A1", "STAGING_CANDIDATE"],
            ],
        )
        self._write_csv(
            market_candidate,
            self.MARKET_HEADER,
            [[market_date, "2317", "2", "402", "2", "https://twse.example", market_date[:7]]],
        )
        raw_path = receipts / "month.twse.raw.csv"
        parsed = market_date.split("-")
        roc = int(parsed[0]) - 1911
        raw_path.write_bytes(f'"{roc:03d}/{parsed[1]}/{parsed[2]}","2"\n'.encode("cp950"))
        receipt_path = receipts / "month.receipt.json"
        receipt_path.write_text(json.dumps({
            "response_encoding": "cp950",
            "raw_artifact_path": str(raw_path),
            "raw_artifact_sha256": sha256(raw_path),
        }), encoding="utf-8")
        daily_status = {
            "run_id": daily_run,
            "status": "DRY_RUN_READY",
            "candidate_path": str(daily_candidate),
            "candidate_sha256": sha256(daily_candidate),
            "twse_latest_validated_trading_date": daily_date,
        }
        market_status = {
            "run_id": market_run,
            "status": "DRY_RUN_READY",
            "candidate_path": str(market_candidate),
            "candidate_sha256": sha256(market_candidate),
            "candidate_last_date": market_date,
            "receipt_paths": [str(receipt_path)],
            "price_validation_provenance": {
                "source": "SAME_RUN_DAILY_PRICE_STAGING",
                "daily_price_run_id": daily_run,
                "daily_price_candidate_sha256": sha256(daily_candidate),
            },
        }
        for rel, payload in (
            (PUBLISHER.DAILY_PRICE_STATUS_PATH, daily_status),
            (PUBLISHER.MARKET_ACTIVITY_STATUS_PATH, market_status),
        ):
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
        staging_daily = self.root / "staging" / "2026-09-06" / "2317_daily_price_candidate.csv"
        self._write_csv(
            staging_daily,
            self.DAILY_HEADER,
            [["2026-09-06", "201", "2026Q2", "100", "2.010", "PUBLIC_MARKET_DATA", "STAGING_CANDIDATE"]],
        )
        return {
            "candidateDate": "2026-09-06",
            "generatedFiles": [str(staging_daily.relative_to(self.root))],
            "validationChecks": [{"status": "PASS"}],
            "criticalMissingFields": [],
        }

    def test_weekend_execution_uses_prior_validated_trading_date(self) -> None:
        readiness = PUBLISHER.build_publish_readiness(
            self.root, self._stage_trade_pair("2026-09-04")
        )
        self.assertTrue(readiness["allowed"], readiness["blockers"])
        self.assertEqual(readiness["executionDate"], "2026-09-06")
        self.assertEqual(readiness["candidateTradingDate"], "2026-09-04")
        self.assertEqual(readiness["formalTargetDate"], "2026-09-04")

    def test_weekend_candidate_row_fails_closed(self) -> None:
        readiness = PUBLISHER.build_publish_readiness(
            self.root, self._stage_trade_pair("2026-09-06")
        )
        self.assertFalse(readiness["allowed"])
        self.assertIn("Saturday/Sunday", " ".join(readiness["blockers"]))

    def test_price_market_date_mismatch_fails_closed(self) -> None:
        readiness = PUBLISHER.build_publish_readiness(
            self.root, self._stage_trade_pair("2026-09-04", "2026-09-03")
        )
        self.assertFalse(readiness["allowed"])
        self.assertIn("date mismatch", " ".join(readiness["blockers"]))

    def test_weekday_without_twse_receipt_fails_closed_as_non_trading_day(self) -> None:
        dry_run = self._stage_trade_pair("2026-09-04")
        status_path = self.root / PUBLISHER.MARKET_ACTIVITY_STATUS_PATH
        status = json.loads(status_path.read_text(encoding="utf-8"))
        raw_path = Path(json.loads(Path(status["receipt_paths"][0]).read_text(encoding="utf-8"))["raw_artifact_path"])
        raw_path.write_bytes('"115/09/03","2"\n'.encode("cp950"))
        receipt_path = Path(status["receipt_paths"][0])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["raw_artifact_sha256"] = sha256(raw_path)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        readiness = PUBLISHER.build_publish_readiness(self.root, dry_run)
        self.assertFalse(readiness["allowed"])
        self.assertIn("non-receipt trading dates", " ".join(readiness["blockers"]))

    def test_duplicate_formal_date_fails_closed(self) -> None:
        candidate = self.root / "staging" / "duplicate" / "2317_daily_price_candidate.csv"
        self._write_csv(
            candidate,
            self.DAILY_HEADER,
            [["2026-08-31", "200", "2026Q2", "100", "2.000", "OFFICIAL_TWSE_A1", "OK"]],
        )
        _, blockers, _ = PUBLISHER.inspect_candidate_files(self.root, [str(candidate)])
        self.assertIn("duplicate Date/Key", " ".join(blockers))

    def test_valid_weekday_candidate_passes(self) -> None:
        plan = PUBLISHER.resolve_trade_date_publish_plan(
            self.root,
            self._stage_trade_pair("2026-09-04")["generatedFiles"],
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan["formalTargetDate"], "2026-09-04")
        self.assertEqual(plan["sameRunLineage"], "PASS")

    def test_review_without_explicit_owner_gate_changes_no_formal_csv(self) -> None:
        dry_run = self._stage_trade_pair("2026-09-04")
        dry_run_path = self.root / "staging" / "2026-09-06" / "DRY_RUN.json"
        dry_run_path.write_text(json.dumps(dry_run), encoding="utf-8")
        before = (sha256(self.root / PUBLISHER.DAILY_TARGET), sha256(self.root / PUBLISHER.MARKET_ACTIVITY_TARGET))
        completed = subprocess.run(
            [sys.executable, str(PUBLISHER_PATH), "--package-root", str(self.root), "--date", "2026-09-06"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("READY FOR OWNER REVIEW", completed.stdout)
        self.assertEqual(before, (sha256(self.root / PUBLISHER.DAILY_TARGET), sha256(self.root / PUBLISHER.MARKET_ACTIVITY_TARGET)))

    def test_isolated_byte_copy_full_publish_and_duplicate_guard(self) -> None:
        """Exercise the real --publish path without touching production authority."""
        authority_paths = [
            PUBLISHER.DAILY_TARGET,
            PUBLISHER.MARKET_ACTIVITY_TARGET,
            PUBLISHER.MACRO_TARGET,
            PUBLISHER.FX_TREND_TARGET,
            PUBLISHER.MACRO_EVENT_TARGET,
            PUBLISHER.MANIFEST_PATH,
        ]
        source_hashes = {rel: sha256(PACKAGE_ROOT / rel) for rel in authority_paths}
        for rel in authority_paths:
            destination = self.root / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PACKAGE_ROOT / rel, destination)
            self.assertEqual(sha256(destination), source_hashes[rel])

        source_staging = PACKAGE_ROOT / "staging" / "2026-09-06"
        isolated_staging = self.root / "staging" / "2026-09-06"
        source_dry_run = json.loads((source_staging / "DRY_RUN.json").read_text(encoding="utf-8"))
        for generated in source_dry_run["generatedFiles"]:
            relative = Path(generated.replace("\\", "/"))
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PACKAGE_ROOT / relative, destination)
        isolated_dry_run_path = isolated_staging / "DRY_RUN.json"
        shutil.copy2(source_staging / "DRY_RUN.json", isolated_dry_run_path)
        original_isolated_dry_run = isolated_dry_run_path.read_bytes()

        for status_rel, runtime_rel in (
            (PUBLISHER.DAILY_PRICE_STATUS_PATH, "runtime/daily_price_incremental"),
            (PUBLISHER.MARKET_ACTIVITY_STATUS_PATH, "runtime/market_activity_incremental"),
        ):
            status = json.loads((PACKAGE_ROOT / status_rel).read_text(encoding="utf-8"))
            source_candidate = Path(status["candidate_path"])
            source_run = source_candidate.parent
            isolated_run = self.root / runtime_rel / status["run_id"]
            shutil.copytree(source_run, isolated_run)
            status["candidate_path"] = str(isolated_run / source_candidate.name)
            isolated_receipts: list[str] = []
            for receipt_value in status.get("receipt_paths", []):
                source_receipt = Path(receipt_value)
                isolated_receipt = isolated_run / source_receipt.relative_to(source_run)
                receipt = json.loads(isolated_receipt.read_text(encoding="utf-8"))
                source_raw = Path(receipt["raw_artifact_path"])
                receipt["raw_artifact_path"] = str(
                    isolated_run / source_raw.relative_to(source_run)
                )
                isolated_receipt.write_text(json.dumps(receipt), encoding="utf-8")
                isolated_receipts.append(str(isolated_receipt))
            status["receipt_paths"] = isolated_receipts
            isolated_status = self.root / status_rel
            isolated_status.parent.mkdir(parents=True, exist_ok=True)
            isolated_status.write_text(json.dumps(status), encoding="utf-8")

        before_counts = {
            rel: PUBLISHER.row_count(self.root / rel)
            for rel in (PUBLISHER.DAILY_TARGET, PUBLISHER.MARKET_ACTIVITY_TARGET)
        }
        environment = dict(
            os.environ,
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONIOENCODING="utf-8",
        )
        command = [
            sys.executable,
            str(PUBLISHER_PATH),
            "--package-root",
            str(self.root),
            "--date",
            "2026-09-06",
            "--publish",
        ]
        published = subprocess.run(
            command,
            input="APPROVE 2026-09-04\n",
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            env=environment,
        )
        self.assertEqual(published.returncode, 0, published.stdout + published.stderr)
        self.assertIn("Formal CSV append completed", published.stdout)
        for rel in (PUBLISHER.DAILY_TARGET, PUBLISHER.MARKET_ACTIVITY_TARGET):
            header, rows, _ = PUBLISHER.read_csv_header_and_rows(self.root / rel)
            date_field = "Date" if rel == PUBLISHER.DAILY_TARGET else "date"
            dates = [row[header.index(date_field)] for row in rows]
            self.assertEqual(dates.count("2026-09-04"), 1)
            self.assertEqual(len(rows), before_counts[rel] + 4)

        manifest = json.loads((self.root / PUBLISHER.MANIFEST_PATH).read_text(encoding="utf-8"))
        entries = manifest["authoritativeFiles"] + manifest.get("nonAuthoritativeFiles", [])
        by_path = {entry["path"]: entry for entry in entries}
        for rel in authority_paths[:-1]:
            self.assertEqual(by_path[rel]["sha256"], sha256(self.root / rel))

        # A second publish request for the identical candidate must not append
        # another formal row. Restoring only the request envelope exercises the
        # full gate against the already-updated isolated authority.
        isolated_dry_run_path.write_bytes(original_isolated_dry_run)
        duplicate = subprocess.run(
            command,
            input="APPROVE 2026-09-04\n",
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            env=environment,
        )
        self.assertEqual(duplicate.returncode, 3, duplicate.stdout + duplicate.stderr)
        self.assertIn("contains no reconciled new trading rows", duplicate.stdout)
        for rel, expected in source_hashes.items():
            self.assertEqual(sha256(PACKAGE_ROOT / rel), expected)


if __name__ == "__main__":
    unittest.main()
