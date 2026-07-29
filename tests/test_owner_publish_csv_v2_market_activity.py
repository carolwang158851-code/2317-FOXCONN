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
                            "rowCount": 1,
                            "dateRange": {
                                "start": "2026-07-17",
                                "end": "2026-07-17",
                            },
                            "analysisStatus": "MARKET_LIQUIDITY_ANALYSIS_READY",
                        }
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
        self.assertEqual(result["status"], "PUBLISHED")
        self.assertFalse(result["actionable"])


if __name__ == "__main__":
    unittest.main()
