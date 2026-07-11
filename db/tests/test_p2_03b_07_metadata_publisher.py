from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = PACKAGE_ROOT / "db" / "tools" / "p2_03b_07_metadata_publisher.py"
CANDIDATE_DIR = (
    PACKAGE_ROOT
    / "staging"
    / "p2-03b-07"
    / "2026-06-23"
    / "metadata_normalization_item87_v2"
    / "candidate"
)
PRE_NORMALIZATION = (
    PACKAGE_ROOT
    / "staging"
    / "p2-03b-07"
    / "2026-06-23"
    / "run_official_item85"
    / "candidate"
    / "data"
)
SPEC = importlib.util.spec_from_file_location(
    "p2_03b_07_metadata_publisher", TOOL_PATH
)
publisher = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = publisher
SPEC.loader.exec_module(publisher)


class P203B07MetadataPublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(
            prefix="metadata-publisher-test-", dir=PACKAGE_ROOT / "staging"
        )
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        (self.project / "data").mkdir(parents=True)
        for name in (
            "2317_master_v9.csv",
            "CSV_AUTHORITY_MANIFEST.json",
        ):
            shutil.copy2(PRE_NORMALIZATION / name, self.project / "data" / name)
        for name in ("2317_daily_price.csv", "macro_snapshot.csv"):
            shutil.copy2(PACKAGE_ROOT / "data" / name, self.project / "data" / name)
        self.runtime = self.root / "runtime.sqlite3"
        self.runtime.write_bytes(b"runtime-protected")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def publish(self, name="publish"):
        return publisher.publish(
            CANDIDATE_DIR,
            self.project,
            self.root / name,
            release_id=publisher.EXPECTED_RELEASE_ID,
            manifest_sha=publisher.EXPECTED_MANIFEST_SHA,
            approval_item=88,
            runtime_db=self.runtime,
        )

    def test_authorized_publish_normalizes_only_metadata(self) -> None:
        before = (self.project / "data/2317_master_v9.csv").read_bytes()
        result = self.publish()
        after = (self.project / "data/2317_master_v9.csv").read_bytes()
        self.assertEqual(result["status"], "PUBLISHED")
        self.assertEqual(publisher.data_region(before), publisher.data_region(after))
        self.assertIn(b"## version: v9.3\n", after)
        self.assertNotIn(b"## version: v9.3-candidate\n", after)

    def test_wrong_approval_is_blocked(self) -> None:
        with self.assertRaises(publisher.ApprovalError):
            publisher.publish(
                CANDIDATE_DIR,
                self.project,
                self.root / "bad",
                release_id=publisher.EXPECTED_RELEASE_ID,
                manifest_sha="0" * 64,
                approval_item=88,
                runtime_db=self.runtime,
            )

    def test_changed_baseline_is_blocked(self) -> None:
        path = self.project / "data/CSV_AUTHORITY_MANIFEST.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(publisher.ApprovalError):
            self.publish()

    def test_backup_restores_pre_normalization_files(self) -> None:
        master_before = publisher.sha256_file(self.project / "data/2317_master_v9.csv")
        authority_before = publisher.sha256_file(
            self.project / "data/CSV_AUTHORITY_MANIFEST.json"
        )
        result = self.publish()
        publisher.restore(self.project, Path(result["backup_dir"]))
        self.assertEqual(
            master_before,
            publisher.sha256_file(self.project / "data/2317_master_v9.csv"),
        )
        self.assertEqual(
            authority_before,
            publisher.sha256_file(self.project / "data/CSV_AUTHORITY_MANIFEST.json"),
        )

    def test_published_manifest_records_item_88(self) -> None:
        self.publish()
        manifest = json.loads(
            (self.root / "publish/RELEASE_MANIFEST.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["owner_approval"]["approval_item"], 88)
        self.assertEqual(
            manifest["owner_approval"]["approved_manifest_sha256"],
            publisher.EXPECTED_MANIFEST_SHA,
        )
        self.assertEqual(manifest["publication"]["status"], "PUBLISHED")

    def test_unchanged_files_and_runtime_are_protected(self) -> None:
        daily = publisher.sha256_file(self.project / "data/2317_daily_price.csv")
        macro = publisher.sha256_file(self.project / "data/macro_snapshot.csv")
        runtime = publisher.sha256_file(self.runtime)
        self.publish()
        self.assertEqual(
            daily, publisher.sha256_file(self.project / "data/2317_daily_price.csv")
        )
        self.assertEqual(
            macro, publisher.sha256_file(self.project / "data/macro_snapshot.csv")
        )
        self.assertEqual(runtime, publisher.sha256_file(self.runtime))

    def test_chinese_status_and_actionable_boundary(self) -> None:
        result = self.publish()
        self.assertEqual(result["status_zh"], "已發布")
        self.assertIn("資料表頭與21列資料未變", result["status_note_zh"])
        self.assertFalse(result["actionable"])


if __name__ == "__main__":
    unittest.main()
