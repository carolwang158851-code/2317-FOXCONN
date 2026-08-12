from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PUBLISHER_PATH = PACKAGE_ROOT / "tools" / "owner_publish_csv_v2.py"
SPEC = importlib.util.spec_from_file_location(
    "p1008_owner_publish_csv_v2_remediation_test", PUBLISHER_PATH
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load publisher: {PUBLISHER_PATH}")
PUBLISHER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PUBLISHER
SPEC.loader.exec_module(PUBLISHER)
FROZEN_PHASE_A_REVISION = "ac53c1dd151e2e2645cdd3128a7dd70cfad7c582"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class OwnerPublishCsvV2RemediationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = (
            PACKAGE_ROOT
            / "runtime"
            / "daily_price_removal_tests"
            / uuid.uuid4().hex
        )
        (self.root / "data").mkdir(parents=True)
        (self.root / "runtime").mkdir()
        self.addCleanup(
            lambda: shutil.rmtree(self.root, ignore_errors=True)
            if self.root.exists()
            else None
        )
        self.formal = self.root / PUBLISHER.DAILY_TARGET
        self.manifest = self.root / PUBLISHER.MANIFEST_PATH
        frozen = subprocess.run(
            [
                "git", "-C", str(PACKAGE_ROOT), "show",
                f"{FROZEN_PHASE_A_REVISION}:{PUBLISHER.DAILY_TARGET}",
            ],
            check=True,
            capture_output=True,
        ).stdout
        self.formal.write_bytes(frozen)
        header, rows, comments = PUBLISHER.read_csv_header_and_rows(self.formal)
        rows = [
            row
            for row in rows
            if row[0] not in {"2026-07-19", "2026-07-22", "2026-07-24"}
        ]
        rows.append(
            [
                "2026-07-19",
                "234.0",
                "2026Q1",
                "127.12",
                "1.841",
                "PUBLIC_MARKET_DATA",
                "OK",
            ]
        )
        rows.sort(key=lambda row: row[0])
        self.formal.write_bytes(
            PUBLISHER._daily_price_bytes(comments, header, rows)
        )
        self.assertEqual(
            sha256(self.formal),
            "25567CE773F7270ED3B22AFBD9D2664E467A2F3D525425AFAE7F20631E56D1B4",
        )
        manifest = {
            "approvedAt": "2026-07-27",
            "approvalSource": "test",
            "authoritativeFiles": [
                {
                    "path": PUBLISHER.DAILY_TARGET,
                    "sha256": sha256(self.formal),
                    "fileSizeBytes": self.formal.stat().st_size,
                    "rowCount": len(
                        PUBLISHER.read_csv_header_and_rows(self.formal)[1]
                    ),
                    "dateRange": {"start": "2026-01-28", "end": "2026-07-27"},
                }
            ],
        }
        self.manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _write_approved_daily_gap_candidate(self, path: Path) -> None:
        header = [
            "Date",
            "Close",
            "QuarterKey",
            "BVPS_ref",
            "PB_daily",
            "DataSupportLevel",
            "Status",
        ]
        source_level = "OFFICIAL_TWSE_A1"
        self.assertIn(source_level, PUBLISHER.APPROVED_DAILY_PRICE_SOURCE_LEVELS)
        rows = [
            [
                row_date,
                expected["Close"],
                expected["QuarterKey"],
                expected["BVPS_ref"],
                expected["PB_daily"],
                source_level,
                "STAGING_CANDIDATE",
            ]
            for row_date, expected in sorted(
                PUBLISHER.DAILY_PRICE_GAPS_EXPECTED_VALUES.items()
            )
        ]
        path.write_bytes(PUBLISHER._daily_price_bytes([], header, rows))
        self.assertEqual(
            sha256(path),
            PUBLISHER.DAILY_PRICE_GAPS_CANDIDATE_SHA256,
        )

    def test_preview_removes_only_invalid_sunday_without_formal_mutation(self) -> None:
        before = (sha256(self.formal), sha256(self.manifest))
        preview = PUBLISHER.run_invalid_daily_price_removal(
            self.root, self.root / "runtime" / "preview"
        )
        self.assertEqual(preview["invalid_date"], "2026-07-19")
        self.assertEqual(
            preview["invalid_row"]["DataSupportLevel"], "PUBLIC_MARKET_DATA"
        )
        self.assertEqual(preview["candidate_rows"], preview["before_rows"] - 1)
        self.assertEqual(preview["candidate_cutoff"], "2026-07-27")
        self.assertEqual(before, (sha256(self.formal), sha256(self.manifest)))
        self.assertFalse(preview["formal_csv_modified"])

    def test_publish_without_exact_owner_phrase_is_rejected(self) -> None:
        before = (sha256(self.formal), sha256(self.manifest))
        with self.assertRaisesRegex(ValueError, "exact Owner approval phrase"):
            PUBLISHER.run_invalid_daily_price_removal(
                self.root,
                self.root / "runtime" / "no-approval",
                publish=True,
                approval_phrase="WRONG",
            )
        self.assertEqual(before, (sha256(self.formal), sha256(self.manifest)))

    def test_approved_scratch_remediation_syncs_sha_rows_and_cutoff(self) -> None:
        result = PUBLISHER.run_invalid_daily_price_removal(
            self.root,
            self.root / "runtime" / "approved",
            publish=True,
            approval_phrase=PUBLISHER.INVALID_DAILY_PRICE_APPROVAL_PHRASE,
        )
        header, rows, _ = PUBLISHER.read_csv_header_and_rows(self.formal)
        dates = [row[0] for row in rows]
        entry = json.loads(self.manifest.read_text(encoding="utf-8"))[
            "authoritativeFiles"
        ][0]
        self.assertNotIn("2026-07-19", dates)
        self.assertEqual(header[0], "Date")
        self.assertEqual(entry["sha256"], sha256(self.formal))
        self.assertEqual(entry["rowCount"], len(rows))
        self.assertEqual(entry["dateRange"]["end"], "2026-07-27")
        self.assertEqual(result["status"], "PUBLISHED")

    def test_weekend_daily_price_publish_is_refused(self) -> None:
        target = self.root / "runtime" / "target.csv"
        candidate = self.root / "runtime" / "weekend.csv"
        self._write_daily(
            target,
            [["2026-07-17", "234", "2026Q1", "127.12", "1.841", "OFFICIAL_TWSE_A1", "OK"]],
        )
        self._write_daily(
            candidate,
            [["2026-07-19", "234", "2026Q1", "127.12", "1.841", "OFFICIAL_TWSE_A1", "STAGING_CANDIDATE"]],
        )
        with self.assertRaisesRegex(ValueError, "Saturday/Sunday"):
            PUBLISHER.append_candidate(candidate, target, PUBLISHER.DAILY_TARGET)

    def test_nonapproved_source_daily_price_publish_is_refused(self) -> None:
        target = self.root / "runtime" / "target.csv"
        candidate = self.root / "runtime" / "unapproved.csv"
        self._write_daily(
            target,
            [["2026-07-17", "234", "2026Q1", "127.12", "1.841", "OFFICIAL_TWSE_A1", "OK"]],
        )
        self._write_daily(
            candidate,
            [["2026-07-20", "234.5", "2026Q1", "127.12", "1.845", "PUBLIC_MARKET_DATA", "STAGING_CANDIDATE"]],
        )
        with self.assertRaisesRegex(ValueError, "lacks approved TWSE/Owner"):
            PUBLISHER.append_candidate(candidate, target, PUBLISHER.DAILY_TARGET)

    def test_same_daily_row_is_idempotent(self) -> None:
        target = self.root / "runtime" / "target.csv"
        candidate = self.root / "runtime" / "same.csv"
        row = [
            "2026-07-20",
            "234.5",
            "2026Q1",
            "127.12",
            "1.845",
            "OFFICIAL_TWSE_A1",
            "OK",
        ]
        self._write_daily(target, [row])
        self._write_daily(candidate, [row])
        before = sha256(target)
        self.assertEqual(
            PUBLISHER.append_candidate(
                candidate, target, PUBLISHER.DAILY_TARGET
            ),
            0,
        )
        self.assertEqual(sha256(target), before)

    def test_daily_price_gaps_require_exact_owner_phrase(self) -> None:
        PUBLISHER.run_invalid_daily_price_removal(
            self.root,
            self.root / "runtime" / "remove-first",
            publish=True,
            approval_phrase=PUBLISHER.INVALID_DAILY_PRICE_APPROVAL_PHRASE,
        )
        candidate = (
            self.root
            / "runtime"
            / "2317_daily_price_20260722_20260724.candidate.csv"
        )
        self._write_approved_daily_gap_candidate(candidate)
        before = (sha256(self.formal), sha256(self.manifest))
        with self.assertRaisesRegex(ValueError, "exact Owner approval phrase"):
            PUBLISHER.run_daily_price_gaps_publish(
                self.root,
                candidate,
                self.root / "runtime" / "gaps-no-approval",
                publish=True,
                approval_phrase="WRONG",
            )
        self.assertEqual(before, (sha256(self.formal), sha256(self.manifest)))

    def test_approved_daily_price_gaps_publish_is_atomic_and_manifest_synced(self) -> None:
        PUBLISHER.run_invalid_daily_price_removal(
            self.root,
            self.root / "runtime" / "remove-first",
            publish=True,
            approval_phrase=PUBLISHER.INVALID_DAILY_PRICE_APPROVAL_PHRASE,
        )
        candidate = (
            self.root
            / "runtime"
            / "2317_daily_price_20260722_20260724.candidate.csv"
        )
        self._write_approved_daily_gap_candidate(candidate)
        result = PUBLISHER.run_daily_price_gaps_publish(
            self.root,
            candidate,
            self.root / "runtime" / "gaps-approved",
            publish=True,
            approval_phrase=PUBLISHER.DAILY_PRICE_GAPS_APPROVAL_PHRASE,
        )
        header, rows, _ = PUBLISHER.read_csv_header_and_rows(self.formal)
        by_date = {row[0]: dict(zip(header, row)) for row in rows}
        entry = json.loads(self.manifest.read_text(encoding="utf-8"))[
            "authoritativeFiles"
        ][0]
        self.assertEqual(result["status"], "PUBLISHED")
        self.assertEqual(
            sha256(self.formal),
            PUBLISHER.DAILY_PRICE_GAPS_EXPECTED_FORMAL_SHA256,
        )
        self.assertEqual(len(rows), PUBLISHER.DAILY_PRICE_GAPS_EXPECTED_ROWS)
        self.assertEqual(by_date["2026-07-22"]["Close"], "251.50")
        self.assertEqual(by_date["2026-07-22"]["PB_daily"], "1.978")
        self.assertEqual(by_date["2026-07-24"]["Close"], "252.50")
        self.assertEqual(by_date["2026-07-24"]["PB_daily"], "1.986")
        self.assertEqual(entry["sha256"], sha256(self.formal))
        self.assertEqual(entry["rowCount"], len(rows))
        self.assertEqual(entry["dateRange"]["end"], "2026-07-27")
        self.assertFalse(
            entry["lastDailyPriceGapPublish"]["runtimeSqliteModified"]
        )

    @staticmethod
    def _write_daily(path: Path, rows: list[list[str]]) -> None:
        header = [
            "Date",
            "Close",
            "QuarterKey",
            "BVPS_ref",
            "PB_daily",
            "DataSupportLevel",
            "Status",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle, lineterminator="\n").writerows([header, *rows])


if __name__ == "__main__":
    unittest.main()
