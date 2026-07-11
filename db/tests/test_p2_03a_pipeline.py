from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = PACKAGE_ROOT / "db" / "tools" / "p2_03a_pipeline.py"
SPEC = importlib.util.spec_from_file_location("p2_03a_pipeline", TOOL_PATH)
pipeline = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = pipeline
SPEC.loader.exec_module(pipeline)


class P203APipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        staging = PACKAGE_ROOT / "staging"
        cls.temp = tempfile.TemporaryDirectory(prefix="p2-03a-test-", dir=staging)
        cls.root = Path(cls.temp.name)
        cls.runtime_db = cls.root / "runtime.sqlite3"
        connection = pipeline.dbcore.connect_database(cls.runtime_db)
        try:
            pipeline.create_schema(connection)
        finally:
            connection.close()
        cls.runtime_hash = pipeline.dbcore.sha256_file(cls.runtime_db)
        cls.output_dir = cls.root / "suite"
        cls.summary = pipeline.run_suite(cls.output_dir, cls.runtime_db)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_same_snapshot_rebuilds_same_release(self) -> None:
        result = self.summary["reproducibility"]
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["manifest_sha256_a"], result["manifest_sha256_b"])
        for name in (
            "RELEASE_MANIFEST.json",
            "DIFF_REPORT.json",
            "VALIDATION_REPORT.md",
            "CHANGE_REPORT.md",
        ):
            self.assertTrue((self.output_dir / "rebuild_a" / name).exists())

    def test_primary_failure_does_not_fallback(self) -> None:
        result = self.summary["scenarios"]["PRIMARY_UNAVAILABLE"]
        self.assertFalse(result["release_allowed"])
        daily = next(item for item in result["datasets"] if item["dataset_code"] == "DAILY_TEST")
        self.assertFalse(daily["fallback_used"])
        self.assertIn("PRIMARY_SOURCE_UNAVAILABLE", result["blocked_codes"])

    def test_conflict_blocks_release(self) -> None:
        result = self.summary["scenarios"]["CONFLICT"]
        self.assertFalse(result["release_allowed"])
        self.assertIn("UNRESOLVED_BLOCKING", result["blocked_codes"])

    def test_stale_data_blocks_release(self) -> None:
        result = self.summary["scenarios"]["STALE"]
        self.assertFalse(result["release_allowed"])
        self.assertIn("STALE_DATA", result["blocked_codes"])

    def test_non_publisher_unapproved_and_tampered_are_blocked(self) -> None:
        tests = self.summary["authorization_tests"]
        self.assertTrue(tests["non_publisher_blocked"])
        self.assertTrue(tests["unapproved_manifest_blocked"])
        self.assertTrue(tests["tampered_candidate_blocked"])

    def test_authorized_test_publish_passes(self) -> None:
        self.assertEqual(self.summary["publish_test"]["status"], "PASS")
        published = Path(self.summary["publish_test"]["target_root"])
        self.assertTrue((published / "ACTIVE_RELEASE.json").exists())
        self.assertTrue(
            (
                published
                / "releases"
                / self.summary["publish_test"]["release_id"]
                / "RELEASE_MANIFEST.json"
            ).exists()
        )

    def test_runtime_database_is_unchanged(self) -> None:
        self.assertEqual(self.runtime_hash, pipeline.dbcore.sha256_file(self.runtime_db))
        self.assertTrue(self.summary["protected_files"]["unchanged"])

    def test_pipeline_database_integrity(self) -> None:
        self.assertEqual(
            self.summary["staging_database"]["integrity_check_status"], "PASS"
        )
        self.assertEqual(
            self.summary["staging_database"]["foreign_key_check_status"], "PASS"
        )

    def test_statuses_include_chinese_notes(self) -> None:
        self.assertTrue(self.summary["status_zh"])
        self.assertTrue(self.summary["status_note_zh"])
        for scenario in self.summary["scenarios"].values():
            for dataset in scenario["datasets"]:
                self.assertTrue(dataset["status_zh"])
                self.assertTrue(dataset["status_note_zh"])


if __name__ == "__main__":
    unittest.main()
