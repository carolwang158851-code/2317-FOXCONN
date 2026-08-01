from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = PACKAGE_ROOT / "db" / "tools" / "p2_03b_07_publisher.py"
CANDIDATE_DIR = (
    PACKAGE_ROOT
    / "staging"
    / "p2-03b-07"
    / "2026-06-23"
    / "run_official_item85"
    / "candidate"
)
PRE_PUBLISH_BACKUP = (
    PACKAGE_ROOT
    / "staging"
    / "p2-03b-07"
    / "2026-06-23"
    / "publish_item86_retry1"
    / "backup"
    / "data"
)
SPEC = importlib.util.spec_from_file_location("p2_03b_07_publisher", TOOL_PATH)
publisher = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = publisher
SPEC.loader.exec_module(publisher)


class P203B07PublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(
            prefix="foreign-holding-publisher-test-", dir=PACKAGE_ROOT / "staging"
        )
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        (self.project / "data").mkdir(parents=True)
        for name in (
            "2317_master_v9.csv",
            "2317_daily_price.csv",
            "macro_snapshot.csv",
            "CSV_AUTHORITY_MANIFEST.json",
        ):
            source = (
                PRE_PUBLISH_BACKUP / name
                if name in {"2317_master_v9.csv", "CSV_AUTHORITY_MANIFEST.json"}
                else PACKAGE_ROOT / "data" / name
            )
            shutil.copy2(source, self.project / "data" / name)
        self.runtime = self.root / "runtime.sqlite3"
        self.runtime.write_bytes(b"runtime-protected")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def publish(self, output_name="publish"):
        return publisher.publish_release(
            CANDIDATE_DIR,
            self.project,
            self.root / output_name,
            approved_release_id=publisher.EXPECTED_RELEASE_ID,
            approved_manifest_sha=publisher.EXPECTED_MANIFEST_SHA,
            approval_item=86,
            runtime_db=self.runtime,
        )

    def test_authorized_publish_updates_only_two_files(self) -> None:
        daily_before = publisher.sha256_file(self.project / "data/2317_daily_price.csv")
        macro_before = publisher.sha256_file(self.project / "data/macro_snapshot.csv")
        result = self.publish()
        self.assertEqual(result["status"], "PUBLISHED_WITH_METADATA_WARNING")
        self.assertEqual(
            publisher.sha256_file(self.project / "data/2317_master_v9.csv"),
            "113F1B2A5E24BEB5009EA6AA6A94C2190E44363C825A729AF48F6A28CA503508",
        )
        self.assertEqual(
            publisher.sha256_file(self.project / "data/CSV_AUTHORITY_MANIFEST.json"),
            "3EE40DB1C2D6F0CE5A3B19D5C10676A9A6056A9674F81F3CC6EF64070828B2C1",
        )
        self.assertEqual(
            daily_before,
            publisher.sha256_file(self.project / "data/2317_daily_price.csv"),
        )
        self.assertEqual(
            macro_before,
            publisher.sha256_file(self.project / "data/macro_snapshot.csv"),
        )

    def test_wrong_approval_is_blocked(self) -> None:
        with self.assertRaises(publisher.ApprovalError):
            publisher.publish_release(
                CANDIDATE_DIR,
                self.project,
                self.root / "bad",
                approved_release_id=publisher.EXPECTED_RELEASE_ID,
                approved_manifest_sha="0" * 64,
                approval_item=86,
                runtime_db=self.runtime,
            )

    def test_changed_formal_baseline_is_blocked(self) -> None:
        path = self.project / "data/2317_master_v9.csv"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(publisher.ApprovalError):
            self.publish()

    def test_backup_can_restore_original_files(self) -> None:
        master_before = publisher.sha256_file(self.project / "data/2317_master_v9.csv")
        authority_before = publisher.sha256_file(
            self.project / "data/CSV_AUTHORITY_MANIFEST.json"
        )
        result = self.publish()
        publisher.restore_from_backup(self.project, Path(result["backup_dir"]))
        self.assertEqual(
            master_before,
            publisher.sha256_file(self.project / "data/2317_master_v9.csv"),
        )
        self.assertEqual(
            authority_before,
            publisher.sha256_file(self.project / "data/CSV_AUTHORITY_MANIFEST.json"),
        )

    def test_published_manifest_records_exact_owner_approval(self) -> None:
        self.publish()
        manifest = json.loads(
            (self.root / "publish/RELEASE_MANIFEST.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["owner_approval"]["approval_item"], 86)
        self.assertEqual(
            manifest["owner_approval"]["approved_manifest_sha256"],
            publisher.EXPECTED_MANIFEST_SHA,
        )
        self.assertTrue(manifest["publication"]["post_publish_verified"])

    def test_chinese_warning_and_non_actionable_status_are_explicit(self) -> None:
        result = self.publish()
        self.assertEqual(result["status_zh"], "已發布但有中繼資料警告")
        self.assertIn("版本註解", result["status_note_zh"])
        self.assertFalse(result["actionable"])


if __name__ == "__main__":
    unittest.main()
