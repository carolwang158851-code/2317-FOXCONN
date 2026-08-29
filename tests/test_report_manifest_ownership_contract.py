from __future__ import annotations

import hashlib
import json
import shutil
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TOOLS = PACKAGE_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import warroom_periodic_report_v1 as periodic  # noqa: E402
import warroom_rolling_brief as rolling  # noqa: E402


RUNTIME_ONLY = [
    ("P1008_DAILY_20260813", "2026-08-13", 1),
    ("P1008_DAILY_20260811", "2026-08-11", 1),
    ("P1008_DAILY_20260806", "2026-08-06", 1),
    ("P1008_DAILY_20260805", "2026-08-05", 1),
    ("P1008_DAILY_20260804", "2026-08-04", 2),
    ("P1008_DAILY_20260802", "2026-08-02", 1),
    ("P1008_DAILY_20260731", "2026-07-31", 2),
    ("P1008_DAILY_20260730", "2026-07-30", 2),
    ("P1008_DAILY_20260727", "2026-07-27", 1),
    ("P1008_DAILY_20260724", "2026-07-24", 1),
    ("P1008_DAILY_20260723", "2026-07-23", 2),
    ("P1008_DAILY_20260721", "2026-07-21", 1),
    ("P1008_DAILY_20260720", "2026-07-20", 2),
]
LIBRARY_DATES = [
    "2026-07-19",
    "2026-07-17",
    "2026-07-16",
    "2026-07-10",
    "2026-07-10-plugin",
    "2026-07-09",
    "2026-07-08",
    "2026-07-07",
    "2026-07-06",
    "2026-07-05",
    "2026-07-04",
    "2026-07-03",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class ReportManifestOwnershipContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = PACKAGE_ROOT / "runtime" / "report_manifest_contract_test_scratch" / uuid.uuid4().hex
        (self.root / "data").mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        (self.root / "data/CSV_AUTHORITY_MANIFEST.json").write_text("{}\n", encoding="utf-8")
        (self.root / "data/2317_daily_price.csv").write_text(
            "Date,Close,QuarterKey,BVPS_ref,PB_daily,DataSupportLevel,Status\n"
            "2026-08-13,250.0,2026Q1,127.12,1.967,OFFICIAL_TWSE_A1,OK\n",
            encoding="utf-8",
        )
        (self.root / "data/2317_daily_market_activity.csv").write_text(
            "date,stock_id,trade_volume,trade_value,transaction_count,source_url,source_month\n"
            "2026-08-13,2317,100,25000,10,https://www.twse.com.tw/source,2026-08\n",
            encoding="utf-8",
        )

    @staticmethod
    def _runtime_record(report_id: str, report_date: str, revision: int) -> dict:
        return {
            "id": report_id,
            "report_key": report_id,
            "revision": revision,
            "period": "daily",
            "date": report_date,
            "status": "BASE_ONLY",
            "generationStatus": "GENERATED",
            "libraryEligible": False,
            "actionable": False,
        }

    @staticmethod
    def _library_record(index: int, report_date: str) -> dict:
        stamp = report_date.replace("-plugin", "").replace("-", "")
        suffix = "_PLUGIN" if report_date.endswith("-plugin") else ""
        return {
            "id": f"P1008_DAILY_REPORT_{stamp}{suffix}",
            "period": "daily",
            "date": report_date.replace("-plugin", ""),
            "status": "GENERATED",
            "actionable": False,
            "ordinal": index,
        }

    def _write_current_topology(self) -> tuple[Path, Path, set[str]]:
        library_reports = [
            self._library_record(index, report_date)
            for index, report_date in enumerate(LIBRARY_DATES, start=1)
        ]
        runtime_reports = [
            self._runtime_record(report_id, report_date, revision)
            for report_id, report_date, revision in RUNTIME_ONLY
        ] + [dict(item) for item in library_reports]
        runtime = {
            "schemaVersion": "2.0",
            "toolVersion": "P1008_REPORT_LIFECYCLE_v1",
            "generatedAt": "2026-08-13T15:34:16Z",
            "latest": {"daily": runtime_reports[0]},
            "reports": runtime_reports,
            "actionable": False,
        }
        library = {
            "schemaVersion": "1.0",
            "toolVersion": "P1008_PERIODIC_REPORT_GENERATOR_v1",
            "generatedAt": "2026-07-19T00:00:00Z",
            "latest": {"daily": library_reports[0], "weekly": None, "monthly": None},
            "reports": library_reports,
            "productionCsvModified": False,
            "actionable": False,
        }
        runtime_path = self.root / rolling.RUNTIME_MANIFEST_REL
        library_path = self.root / rolling.REPORT_MANIFEST_REL
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        library_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")
        library_path.write_text(json.dumps(library, indent=2) + "\n", encoding="utf-8")
        return runtime_path, library_path, {item["id"] for item in runtime_reports}

    def test_real_25_12_split_is_healthy_without_manifest_mutation(self) -> None:
        runtime_path, library_path, _ = self._write_current_topology()
        before = (digest(runtime_path), digest(library_path))
        bootstrap = rolling.bootstrap_report_library(self.root)
        self.assertEqual(bootstrap["status"], "REPORT_LIBRARY_EXISTING_HEALTHY")
        self.assertEqual(bootstrap["runtimeLifecycleCount"], 25)
        self.assertEqual(bootstrap["researchLibraryCount"], 12)
        self.assertEqual(bootstrap["runtimeOnlyCount"], 13)
        self.assertTrue(bootstrap["librarySubsetOfRuntime"])
        rolling.refresh_current_brief(self.root, now=datetime(2026, 8, 14, tzinfo=timezone.utc))
        health = rolling.report_library_health(self.root)
        self.assertEqual(health["status"], "PASS")
        self.assertEqual(health["runtimeLifecycleCount"], 25)
        self.assertEqual(health["researchLibraryCount"], 12)
        self.assertEqual(health["runtimeOnlyCount"], 13)
        self.assertTrue(health["librarySubsetOfRuntime"])
        self.assertEqual(before, (digest(runtime_path), digest(library_path)))

    def test_library_subset_violation_fails_closed(self) -> None:
        runtime_path, library_path, _ = self._write_current_topology()
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        removed = runtime["reports"].pop()
        self.assertEqual(removed["id"], json.loads(library_path.read_text(encoding="utf-8"))["reports"][-1]["id"])
        runtime_path.write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")
        result = rolling.bootstrap_report_library(self.root)
        self.assertEqual(result["status"], "FAIL_CLOSED")
        self.assertIn("absent from runtime lifecycle", result["message"])

    def test_periodic_eligible_upsert_preserves_all_runtime_history(self) -> None:
        runtime_path, library_path, original_ids = self._write_current_topology()
        report = {
            "id": "P1008_QUARTERLY_REPORT_2026Q2",
            "reportKey": "P1008_QUARTERLY_EARNINGS_2026Q2",
            "revision": 1,
            "period": "quarterly",
            "date": "2026-08-14",
            "status": "FULL_PLUGIN_REPORT",
            "archiveEligibility": True,
            "privateLibraryEligible": True,
            "libraryEligible": True,
            "actionable": False,
        }
        periodic.update_report_manifest(self.root, report, "2026-08-14T00:00:00Z")
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        library = json.loads(library_path.read_text(encoding="utf-8"))
        self.assertEqual(len(runtime["reports"]), 26)
        self.assertEqual(len(library["reports"]), 13)
        self.assertTrue(original_ids.issubset({item["id"] for item in runtime["reports"]}))
        self.assertEqual(runtime["schemaVersion"], "2.0")
        self.assertEqual(library["schemaVersion"], "1.0")

    def test_noneligible_record_never_pollutes_library(self) -> None:
        runtime_path, library_path, _ = self._write_current_topology()
        report = {
            "id": "P1008_DAILY_20260814",
            "report_key": "P1008_DAILY_20260814",
            "revision": 1,
            "period": "daily",
            "date": "2026-08-14",
            "status": "BASE_ONLY",
            "libraryEligible": False,
            "actionable": False,
        }
        before_library = digest(library_path)
        periodic.update_report_manifest(self.root, report, "2026-08-14T00:00:00Z")
        self.assertEqual(len(json.loads(runtime_path.read_text(encoding="utf-8"))["reports"]), 26)
        self.assertEqual(digest(library_path), before_library)

    def test_runtime_unused_latest_slots_are_optional_but_library_slots_are_required(self) -> None:
        _, library_path, _ = self._write_current_topology()
        self.assertEqual(rolling.bootstrap_report_library(self.root)["status"], "REPORT_LIBRARY_EXISTING_HEALTHY")
        library = json.loads(library_path.read_text(encoding="utf-8"))
        library["latest"].pop("weekly")
        library_path.write_text(json.dumps(library, indent=2) + "\n", encoding="utf-8")
        result = rolling.bootstrap_report_library(self.root)
        self.assertEqual(result["status"], "FAIL_CLOSED")
        self.assertIn("latest section is invalid", result["message"])

    def test_partial_loss_remains_fail_closed(self) -> None:
        runtime_path, library_path, _ = self._write_current_topology()
        library_path.unlink()
        result = rolling.bootstrap_report_library(self.root)
        self.assertEqual(result["status"], "FAIL_CLOSED")
        self.assertEqual(result["code"], "REPORT_LIBRARY_PARTIAL_MANIFEST_LOSS")
        self.assertTrue(runtime_path.is_file())

    def test_structural_and_artifact_corruption_remain_fail_closed(self) -> None:
        runtime_path, library_path, _ = self._write_current_topology()
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        runtime["actionable"] = True
        runtime_path.write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")
        self.assertEqual(rolling.bootstrap_report_library(self.root)["status"], "FAIL_CLOSED")

        self._write_current_topology()
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        runtime["reports"] = {"not": "an array"}
        runtime_path.write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")
        self.assertEqual(rolling.bootstrap_report_library(self.root)["status"], "FAIL_CLOSED")

        self._write_current_topology()
        library = json.loads(library_path.read_text(encoding="utf-8"))
        library["reports"][0]["md"] = "generated/missing.md"
        library["latest"]["daily"] = library["reports"][0]
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        matching = next(item for item in runtime["reports"] if item["id"] == library["reports"][0]["id"])
        matching["md"] = "generated/missing.md"
        runtime_path.write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")
        library_path.write_text(json.dumps(library, indent=2) + "\n", encoding="utf-8")
        result = rolling.bootstrap_report_library(self.root)
        self.assertEqual(result["status"], "FAIL_CLOSED")
        self.assertIn("artifact is missing", result["message"])


if __name__ == "__main__":
    unittest.main()
