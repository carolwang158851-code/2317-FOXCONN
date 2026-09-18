from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PUBLISHER_PATH = PACKAGE_ROOT / "tools" / "owner_publish_csv_v2.py"
SPEC = importlib.util.spec_from_file_location(
    "p1008_owner_publish_csv_v2_market_activity_test", PUBLISHER_PATH
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load publisher: {PUBLISHER_PATH}")
PUBLISHER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PUBLISHER
SPEC.loader.exec_module(PUBLISHER)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class OwnerPublishCsvV2MarketActivityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = (
            PACKAGE_ROOT
            / "runtime"
            / "market_activity_owner_gate_tests"
            / uuid.uuid4().hex
        )
        (self.root / "data").mkdir(parents=True)
        (self.root / "runtime").mkdir()
        self.addCleanup(
            lambda: shutil.rmtree(self.root) if self.root.exists() else None
        )
        self.formal = self.root / PUBLISHER.MARKET_ACTIVITY_TARGET
        self.manifest = self.root / PUBLISHER.MANIFEST_PATH
        self.candidate = self.root / "runtime" / "candidate.csv"
        self._write_csv(
            self.formal,
            [
                [
                    "2026-07-17",
                    "2317",
                    "1000",
                    "200000",
                    "100",
                    self._url("2026-07"),
                    "2026-07",
                ]
            ],
        )
        self._write_csv(
            self.candidate,
            [
                [
                    "2026-07-20",
                    "2317",
                    "1200",
                    "240000",
                    "120",
                    self._url("2026-07"),
                    "2026-07",
                ]
            ],
        )
        self.manifest.write_text(
            json.dumps(
                {
                    "approvedAt": "2026-07-18",
                    "authoritativeFiles": [
                        {
                            "path": PUBLISHER.MARKET_ACTIVITY_TARGET,
                            "sha256": sha256(self.formal),
                            "currentSha256": sha256(self.formal),
                            "fileSizeBytes": self.formal.stat().st_size,
                            "size": self.formal.stat().st_size,
                            "rowCount": 1,
                            "cutoffDate": "2026-07-17",
                            "dateRange": {
                                "start": "2026-07-17",
                                "end": "2026-07-17",
                            },
                            "analysisStatus": "MARKET_LIQUIDITY_ANALYSIS_READY",
                            "lastAppend": {
                                "rowsAdded": 1,
                                "start": "2026-07-17",
                                "end": "2026-07-17",
                                "candidateSha256": "A" * 64,
                                "publishedAt": "2026-07-18T00:00:00Z",
                                "publisher": "prior-publisher.py",
                                "mode": "PRIOR_APPEND",
                                "actionable": False,
                            },
                        },
                        {
                            "path": "data/2317_master_v9.csv",
                            "sentinel": "master-unchanged",
                        },
                        {
                            "path": "data/2317_cash_flow_authority.csv",
                            "sentinel": "cash-flow-unchanged",
                        }
                    ],
                    "nonAuthoritativeFiles": [
                        {"path": "data/macro_snapshot.csv", "sentinel": "macro-unchanged"},
                        {"path": "data/fx_trend_observations.csv", "sentinel": "fx-unchanged"},
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _url(month: str) -> str:
        return (
            "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?"
            f"date={month.replace('-', '')}01&stockNo=2317&response=csv"
        )

    @staticmethod
    def _write_csv(path: Path, rows: list[list[str]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(PUBLISHER.MARKET_ACTIVITY_FIELDS)
            writer.writerows(rows)

    def test_missing_owner_phrase_refuses_formal_publish(self) -> None:
        before = (sha256(self.formal), sha256(self.manifest))
        with self.assertRaisesRegex(ValueError, "exact Owner approval phrase"):
            PUBLISHER.publish_market_activity_append(
                self.root, self.candidate, self.root / "runtime" / "publish"
            )
        self.assertEqual(before, (sha256(self.formal), sha256(self.manifest)))

    def test_exact_owner_phrase_atomically_updates_csv_and_manifest(self) -> None:
        phrase = PUBLISHER.market_activity_approval_phrase(["2026-07-20"])
        result = PUBLISHER.publish_market_activity_append(
            self.root,
            self.candidate,
            self.root / "runtime" / "publish",
            approval_phrase=phrase,
        )
        with self.formal.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        entry = json.loads(self.manifest.read_text(encoding="utf-8"))[
            "authoritativeFiles"
        ][0]
        self.assertEqual([row["date"] for row in rows], ["2026-07-17", "2026-07-20"])
        self.assertEqual(entry["rowCount"], 2)
        self.assertEqual(entry["dateRange"]["end"], "2026-07-20")
        self.assertEqual(entry["sha256"], sha256(self.formal))
        self.assertEqual(entry["fileSizeBytes"], self.formal.stat().st_size)
        self.assertEqual(entry["lastAppend"]["rowsAdded"], 1)
        self.assertEqual(entry["lastAppend"]["start"], "2026-07-20")
        self.assertEqual(entry["lastAppend"]["end"], "2026-07-20")
        self.assertEqual(entry["lastAppend"]["publisher"], "owner_publish_csv_v2.py")
        self.assertEqual(entry["lastAppend"]["mode"], "MARKET_ACTIVITY_ATOMIC_APPEND")
        self.assertEqual(result["status"], "PUBLISHED")
        self.assertFalse(result["actionable"])

    def test_market_activity_manifest_end_tracks_actual_latest_date(self) -> None:
        historical_bytes = self.formal.read_bytes()
        rows_added = PUBLISHER.append_candidate(
            self.candidate, self.formal, PUBLISHER.MARKET_ACTIVITY_TARGET
        )
        self.assertEqual(rows_added, 1)

        PUBLISHER.update_manifest(
            self.root,
            [PUBLISHER.MARKET_ACTIVITY_TARGET],
            "isolated governed update test",
        )

        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        entry = manifest["authoritativeFiles"][0]
        self.assertEqual(entry["dateRange"]["start"], "2026-07-17")
        self.assertEqual(entry["dateRange"]["end"], "2026-07-20")
        self.assertTrue(self.formal.read_bytes().startswith(historical_bytes))

    def test_market_activity_manifest_hash_size_rowcount_remain_synchronized(self) -> None:
        PUBLISHER.append_candidate(
            self.candidate, self.formal, PUBLISHER.MARKET_ACTIVITY_TARGET
        )
        PUBLISHER.update_manifest(
            self.root,
            [PUBLISHER.MARKET_ACTIVITY_TARGET],
            "isolated governed update test",
        )

        entry = json.loads(self.manifest.read_text(encoding="utf-8"))[
            "authoritativeFiles"
        ][0]
        self.assertEqual(entry["sha256"], sha256(self.formal))
        self.assertEqual(entry["currentSha256"], sha256(self.formal))
        self.assertEqual(entry["fileSizeBytes"], self.formal.stat().st_size)
        self.assertEqual(entry["size"], self.formal.stat().st_size)
        self.assertEqual(entry["rowCount"], 2)
        self.assertEqual(entry["dateRange"], {"start": "2026-07-17", "end": "2026-07-20"})
        self.assertEqual(entry["cutoffDate"], "2026-07-20")

    def test_market_activity_metadata_does_not_rewrite_history(self) -> None:
        historical_bytes = self.formal.read_bytes()
        PUBLISHER.append_candidate(
            self.candidate, self.formal, PUBLISHER.MARKET_ACTIVITY_TARGET
        )
        appended_bytes = self.formal.read_bytes()
        PUBLISHER.update_manifest(
            self.root,
            [PUBLISHER.MARKET_ACTIVITY_TARGET],
            "isolated governed update test",
        )

        self.assertEqual(self.formal.read_bytes(), appended_bytes)
        self.assertEqual(self.formal.read_bytes()[: len(historical_bytes)], historical_bytes)

    def test_market_activity_last_append_is_not_fabricated(self) -> None:
        before = json.loads(self.manifest.read_text(encoding="utf-8"))[
            "authoritativeFiles"
        ][0]["lastAppend"]
        PUBLISHER.append_candidate(
            self.candidate, self.formal, PUBLISHER.MARKET_ACTIVITY_TARGET
        )
        PUBLISHER.update_manifest(
            self.root,
            [PUBLISHER.MARKET_ACTIVITY_TARGET],
            "isolated governed update test",
        )

        after = json.loads(self.manifest.read_text(encoding="utf-8"))[
            "authoritativeFiles"
        ][0]["lastAppend"]
        self.assertEqual(after, before)

    def test_governed_append_keeps_manifest_atomic(self) -> None:
        before = (self.formal.read_bytes(), self.manifest.read_bytes())
        phrase = PUBLISHER.market_activity_approval_phrase(["2026-07-20"])
        original_atomic_write = PUBLISHER._atomic_write_bytes
        failure_injected = False

        def fail_manifest_once(path: Path, content: bytes) -> None:
            nonlocal failure_injected
            if Path(path) == self.manifest and not failure_injected:
                failure_injected = True
                raise OSError("injected manifest replacement failure")
            original_atomic_write(path, content)

        with mock.patch.object(
            PUBLISHER, "_atomic_write_bytes", side_effect=fail_manifest_once
        ):
            with self.assertRaisesRegex(RuntimeError, "CSV and manifest restored"):
                PUBLISHER.publish_market_activity_append(
                    self.root,
                    self.candidate,
                    self.root / "runtime" / "publish",
                    approval_phrase=phrase,
                )

        self.assertTrue(failure_injected)
        self.assertEqual((self.formal.read_bytes(), self.manifest.read_bytes()), before)

    def test_daily_price_manifest_behavior_unchanged(self) -> None:
        daily_path = self.root / PUBLISHER.DAILY_TARGET
        self._write_generic_csv(
            daily_path,
            ["Date", "Close"],
            [["2026-07-17", "100"], ["2026-07-20", "101"]],
        )
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest["authoritativeFiles"].append(
            {
                "path": PUBLISHER.DAILY_TARGET,
                "sha256": "OLD",
                "fileSizeBytes": 1,
                "rowCount": 1,
                "dateRange": {"start": "PRESERVE-ME", "end": "2026-07-17"},
            }
        )
        self.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        PUBLISHER.update_manifest(
            self.root, [PUBLISHER.DAILY_TARGET], "isolated daily update test"
        )

        daily_entry = json.loads(self.manifest.read_text(encoding="utf-8"))[
            "authoritativeFiles"
        ][-1]
        self.assertEqual(daily_entry["dateRange"]["start"], "2026-07-17")
        self.assertEqual(daily_entry["dateRange"]["end"], "2026-07-20")
        self.assertEqual(daily_entry["sha256"], sha256(daily_path))
        self.assertEqual(daily_entry["fileSizeBytes"], daily_path.stat().st_size)
        self.assertEqual(daily_entry["rowCount"], 2)

    def test_unrelated_manifest_entries_unchanged(self) -> None:
        before = json.loads(self.manifest.read_text(encoding="utf-8"))
        unrelated_before = {
            entry["path"]: entry
            for group in ("authoritativeFiles", "nonAuthoritativeFiles")
            for entry in before[group]
            if entry["path"] != PUBLISHER.MARKET_ACTIVITY_TARGET
        }
        PUBLISHER.append_candidate(
            self.candidate, self.formal, PUBLISHER.MARKET_ACTIVITY_TARGET
        )
        PUBLISHER.update_manifest(
            self.root,
            [PUBLISHER.MARKET_ACTIVITY_TARGET],
            "isolated governed update test",
        )

        after = json.loads(self.manifest.read_text(encoding="utf-8"))
        unrelated_after = {
            entry["path"]: entry
            for group in ("authoritativeFiles", "nonAuthoritativeFiles")
            for entry in after[group]
            if entry["path"] != PUBLISHER.MARKET_ACTIVITY_TARGET
        }
        self.assertEqual(unrelated_after, unrelated_before)

    def test_generic_publish_rolls_back_csv_and_manifest_together(self) -> None:
        candidate = self.root / "runtime" / "2317_daily_market_activity.incremental.candidate.csv"
        shutil.copy2(self.candidate, candidate)
        before = (self.formal.read_bytes(), self.manifest.read_bytes())
        with mock.patch.object(PUBLISHER, "update_manifest", side_effect=OSError("injected manifest failure")):
            with self.assertRaisesRegex(OSError, "injected manifest failure"):
                PUBLISHER.publish_generated_candidates_atomically(
                    self.root,
                    [str(candidate.relative_to(self.root))],
                    self.root / "runtime" / "backup",
                    "test append {rows}",
                )
        self.assertEqual((self.formal.read_bytes(), self.manifest.read_bytes()), before)
        self.assertTrue((self.root / "runtime" / "backup" / self.manifest.name).is_file())

    def _prepare_historical_reconciliation(
        self,
        *,
        state: str = "RECONCILIATION_REQUIRED",
        revisions: int = 1,
    ) -> tuple[Path, Path, dict[str, str], str]:
        self._write_csv(self.formal, [
            ["2026-09-13", "2317", "111", "222", "33", self._url("2026-09"), "2026-09"],
            ["2026-09-14", "2317", "22260973", "5492709017", "22321", self._url("2026-09"), "2026-09"],
        ])
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        entry = manifest["authoritativeFiles"][0]
        entry.update({
            "sha256": sha256(self.formal),
            "currentSha256": sha256(self.formal),
            "fileSizeBytes": self.formal.stat().st_size,
            "size": self.formal.stat().st_size,
            "rowCount": 2,
            "cutoffDate": "2026-09-14",
            "dateRange": {"start": "2026-09-13", "end": "2026-09-14"},
        })
        self.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        run_dir = self.root / "runtime" / "market_activity_incremental" / "TEST-RUN"
        run_dir.mkdir(parents=True)
        reconciliation = run_dir / "HISTORICAL_RECONCILIATION_REQUIRED.json"
        revision = {
            "date": "2026-09-14",
            "changed_fields": {
                "trade_volume": {"formal": "22260973", "twse": "25260973"},
                "trade_value": {"formal": "5492709017", "twse": "6232907117"},
                "transaction_count": {"formal": "22321", "twse": "22323"},
            },
            "formal_row_preserved": True,
            "twse_close_matches_price_authority": True,
        }
        reconciliation.write_text(json.dumps({
            "status": state,
            "formal_rows_preserved": True,
            "revisions": [revision for _ in range(revisions)],
            "actionable": False,
        }), encoding="utf-8")
        candidate = run_dir / "2317_daily_market_activity.incremental.candidate.csv"
        self._write_csv(candidate, [
            ["2026-09-15", "2317", "15812094", "3918516707", "17468", self._url("2026-09"), "2026-09"],
            ["2026-09-16", "2317", "19737377", "4880814131", "18480", self._url("2026-09"), "2026-09"],
        ])
        replacement = {
            "trade_volume": "25260973",
            "trade_value": "6232907117",
            "transaction_count": "22323",
        }
        phrase = PUBLISHER.market_activity_reconciliation_approval_phrase(
            "2317", "2026-09-14", ["2026-09-15", "2026-09-16"]
        )
        return reconciliation, candidate, replacement, phrase

    def test_historical_reconciliation_and_later_append_are_atomic_and_generic(self) -> None:
        reconciliation, candidate, replacement, phrase = self._prepare_historical_reconciliation()
        unrelated_line = self.formal.read_bytes().splitlines(keepends=True)[1]
        result = PUBLISHER.publish_market_activity_historical_reconciliation(
            self.root, reconciliation, self.root / "runtime" / "historical-publish",
            stock_id="2317", replacement_values=replacement,
            approval_phrase=phrase, append_candidate_path=candidate,
        )
        with self.formal.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        entry = json.loads(self.manifest.read_text(encoding="utf-8"))["authoritativeFiles"][0]
        revised = next(row for row in rows if row["date"] == "2026-09-14")
        self.assertEqual(result["status"], "PUBLISHED")
        self.assertEqual(revised["trade_volume"], "25260973")
        self.assertEqual(revised["trade_value"], "6232907117")
        self.assertEqual(revised["transaction_count"], "22323")
        self.assertEqual([row["date"] for row in rows[-2:]], ["2026-09-15", "2026-09-16"])
        self.assertEqual(self.formal.read_bytes().splitlines(keepends=True)[1], unrelated_line)
        self.assertEqual(entry["sha256"], sha256(self.formal))
        self.assertEqual(entry["currentSha256"], sha256(self.formal))
        self.assertEqual(entry["fileSizeBytes"], self.formal.stat().st_size)
        self.assertEqual(entry["size"], self.formal.stat().st_size)
        self.assertEqual(entry["rowCount"], 4)
        self.assertEqual(entry["dateRange"], {"start": "2026-09-13", "end": "2026-09-16"})
        self.assertEqual(entry["cutoffDate"], "2026-09-16")

    def test_historical_reconciliation_rejects_changed_formal_precondition(self) -> None:
        reconciliation, candidate, replacement, phrase = self._prepare_historical_reconciliation()
        rows = PUBLISHER.read_csv_header_and_rows(self.formal)[1]
        rows[1][2] = "999"
        self._write_csv(self.formal, rows)
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest["authoritativeFiles"][0]["sha256"] = sha256(self.formal)
        manifest["authoritativeFiles"][0]["rowCount"] = 2
        self.manifest.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        before = (self.formal.read_bytes(), self.manifest.read_bytes())
        with self.assertRaisesRegex(ValueError, "changed unexpectedly"):
            PUBLISHER.publish_market_activity_historical_reconciliation(
                self.root, reconciliation, self.root / "runtime" / "historical-publish",
                stock_id="2317", replacement_values=replacement,
                approval_phrase=phrase, append_candidate_path=candidate,
            )
        self.assertEqual((self.formal.read_bytes(), self.manifest.read_bytes()), before)

    def test_historical_reconciliation_rejects_replacement_evidence_mismatch(self) -> None:
        reconciliation, candidate, replacement, phrase = self._prepare_historical_reconciliation()
        replacement["trade_volume"] = "25260974"
        before = (self.formal.read_bytes(), self.manifest.read_bytes())
        with self.assertRaisesRegex(ValueError, "does not match recorded TWSE evidence"):
            PUBLISHER.publish_market_activity_historical_reconciliation(
                self.root, reconciliation, self.root / "runtime" / "historical-publish",
                stock_id="2317", replacement_values=replacement,
                approval_phrase=phrase, append_candidate_path=candidate,
            )
        self.assertEqual((self.formal.read_bytes(), self.manifest.read_bytes()), before)

    def test_historical_reconciliation_requires_state_owner_phrase_and_single_revision(self) -> None:
        for case, state, revisions, approval, expected in (
            ("state", "STALE", 1, "VALID", "RECONCILIATION_REQUIRED"),
            ("approval", "RECONCILIATION_REQUIRED", 1, None, "exact Owner approval phrase"),
            ("multiple", "RECONCILIATION_REQUIRED", 2, "VALID", "exactly one"),
        ):
            with self.subTest(case=case):
                reconciliation, candidate, replacement, phrase = self._prepare_historical_reconciliation(
                    state=state, revisions=revisions,
                )
                supplied = phrase if approval == "VALID" else approval
                before = (self.formal.read_bytes(), self.manifest.read_bytes())
                with self.assertRaisesRegex(ValueError, expected):
                    PUBLISHER.publish_market_activity_historical_reconciliation(
                        self.root, reconciliation,
                        self.root / "runtime" / f"historical-publish-{case}",
                        stock_id="2317", replacement_values=replacement,
                        approval_phrase=supplied, append_candidate_path=candidate,
                    )
                self.assertEqual((self.formal.read_bytes(), self.manifest.read_bytes()), before)
                shutil.rmtree(reconciliation.parent)

    def test_historical_reconciliation_rolls_back_csv_and_manifest(self) -> None:
        reconciliation, candidate, replacement, phrase = self._prepare_historical_reconciliation()
        before = (self.formal.read_bytes(), self.manifest.read_bytes())
        original_atomic_write = PUBLISHER._atomic_write_bytes
        failed = False

        def fail_manifest_once(path: Path, content: bytes) -> None:
            nonlocal failed
            if Path(path) == self.manifest and not failed:
                failed = True
                raise OSError("injected manifest replacement failure")
            original_atomic_write(path, content)

        with mock.patch.object(PUBLISHER, "_atomic_write_bytes", side_effect=fail_manifest_once):
            with self.assertRaisesRegex(RuntimeError, "CSV and manifest restored"):
                PUBLISHER.publish_market_activity_historical_reconciliation(
                    self.root, reconciliation, self.root / "runtime" / "historical-publish",
                    stock_id="2317", replacement_values=replacement,
                    approval_phrase=phrase, append_candidate_path=candidate,
                )
        self.assertTrue(failed)
        self.assertEqual((self.formal.read_bytes(), self.manifest.read_bytes()), before)

    def test_ordinary_append_still_rejects_historical_overlap(self) -> None:
        reconciliation, _, _, _ = self._prepare_historical_reconciliation()
        overlap = reconciliation.parent / "ordinary-overlap.csv"
        self._write_csv(overlap, [
            ["2026-09-14", "2317", "25260973", "6232907117", "22323", self._url("2026-09"), "2026-09"],
        ])
        before = (self.formal.read_bytes(), self.manifest.read_bytes())
        phrase = PUBLISHER.market_activity_approval_phrase(["2026-09-14"])
        with self.assertRaisesRegex(ValueError, "rewrite or duplicate history"):
            PUBLISHER.publish_market_activity_append(
                self.root, overlap, self.root / "runtime" / "ordinary-publish",
                approval_phrase=phrase,
            )
        self.assertEqual((self.formal.read_bytes(), self.manifest.read_bytes()), before)

    @staticmethod
    def _write_generic_csv(
        path: Path, header: list[str], rows: list[list[str]]
    ) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
