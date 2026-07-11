from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = PACKAGE_ROOT / "db" / "tools" / "p2_03b_07_metadata_normalizer.py"
SPEC = importlib.util.spec_from_file_location(
    "p2_03b_07_metadata_normalizer", TOOL_PATH
)
normalizer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = normalizer
SPEC.loader.exec_module(normalizer)

PRE_NORMALIZATION = (
    PACKAGE_ROOT
    / "staging"
    / "p2-03b-07"
    / "2026-06-23"
    / "run_official_item85"
    / "candidate"
    / "data"
)


class P203B07MetadataNormalizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(
            prefix="metadata-normalizer-test-", dir=PACKAGE_ROOT / "staging"
        )
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime.sqlite3"
        self.runtime.write_bytes(b"runtime-protected")
        self.source = self.root / "source"
        self.source.mkdir()
        for name in ("2317_master_v9.csv", "CSV_AUTHORITY_MANIFEST.json"):
            (self.source / name).write_bytes((PRE_NORMALIZATION / name).read_bytes())
        for name in ("2317_daily_price.csv", "macro_snapshot.csv"):
            (self.source / name).write_bytes((PACKAGE_ROOT / "data" / name).read_bytes())
        self.patchers = [
            patch.object(normalizer, "MASTER_CSV", self.source / "2317_master_v9.csv"),
            patch.object(
                normalizer,
                "AUTHORITY_MANIFEST",
                self.source / "CSV_AUTHORITY_MANIFEST.json",
            ),
            patch.object(
                normalizer, "DAILY_CSV", self.source / "2317_daily_price.csv"
            ),
            patch.object(normalizer, "MACRO_CSV", self.source / "macro_snapshot.csv"),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def run_candidate(self, name="run"):
        return normalizer.build_candidate(self.root / name, self.runtime)

    def test_only_version_comment_changes(self) -> None:
        before = normalizer.MASTER_CSV.read_bytes()
        after = normalizer.normalize_master(before)
        self.assertIn(b"## version: v9.3\n", after)
        self.assertNotIn(b"## version: v9.3-candidate\n", after)
        self.assertEqual(
            normalizer.data_region(before),
            normalizer.data_region(after),
        )

    def test_wrong_or_duplicate_version_marker_is_blocked(self) -> None:
        with self.assertRaises(normalizer.NormalizationError):
            normalizer.normalize_master(b"## version: v9.3\nA,B\n1,2\n")
        content = normalizer.MASTER_CSV.read_bytes()
        with self.assertRaises(normalizer.NormalizationError):
            normalizer.normalize_master(
                content + b"## version: v9.3-candidate\n"
            )

    def test_candidate_shape_and_data_hash_are_preserved(self) -> None:
        result = self.run_candidate()
        self.assertEqual(result["row_count"], 21)
        self.assertEqual(result["column_count"], 54)
        self.assertTrue(result["data_region_equal"])
        self.assertEqual(
            result["data_region_sha256"],
            normalizer.sha256_bytes(
                normalizer.data_region(normalizer.MASTER_CSV.read_bytes())
            ),
        )

    def test_authority_manifest_points_to_candidate_master(self) -> None:
        result = self.run_candidate()
        candidate = self.root / "run/candidate"
        formal_authority = json.loads(
            normalizer.AUTHORITY_MANIFEST.read_text(encoding="utf-8")
        )
        authority = json.loads(
            (candidate / "data/CSV_AUTHORITY_MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )
        target = next(
            item
            for item in authority["authoritativeFiles"]
            if item["path"] == "data/2317_master_v9.csv"
        )
        self.assertEqual(target["fileVersion"], "v9.3")
        self.assertEqual(
            target["sha256"],
            result["candidate_master_sha256"],
        )
        self.assertEqual(
            target["fileSizeBytes"],
            (candidate / "data/2317_master_v9.csv").stat().st_size,
        )
        formal_target = next(
            item
            for item in formal_authority["authoritativeFiles"]
            if item["path"] == "data/2317_master_v9.csv"
        )
        target_without_allowed_changes = dict(target)
        formal_without_allowed_changes = dict(formal_target)
        for field in ("sha256", "fileSizeBytes"):
            target_without_allowed_changes.pop(field)
            formal_without_allowed_changes.pop(field)
        self.assertEqual(
            target_without_allowed_changes,
            formal_without_allowed_changes,
        )
        authority_without_files = dict(authority)
        formal_without_files = dict(formal_authority)
        authority_without_files.pop("authoritativeFiles")
        formal_without_files.pop("authoritativeFiles")
        self.assertEqual(authority_without_files, formal_without_files)

    def test_manifest_is_pending_item_88_and_reproducible(self) -> None:
        first = self.run_candidate("first")
        second = self.run_candidate("second")
        self.assertEqual(first["manifest_sha256"], second["manifest_sha256"])
        manifest = json.loads(
            (self.root / "first/candidate/RELEASE_MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["owner_approval"]["approval_item"], 88)
        self.assertEqual(manifest["owner_approval"]["status"], "PENDING")
        self.assertEqual(
            normalizer.sha256_bytes(
                normalizer.canonical_json(manifest["payload"]).encode("utf-8")
            ),
            manifest["manifest_sha256"],
        )

    def test_formal_files_and_runtime_are_unchanged(self) -> None:
        before = normalizer.protected_hashes(self.runtime)
        result = self.run_candidate()
        self.assertEqual(before, normalizer.protected_hashes(self.runtime))
        self.assertTrue(result["protected_files"]["unchanged"])

    def test_chinese_status_and_non_actionable_boundary_are_explicit(self) -> None:
        result = self.run_candidate()
        self.assertEqual(result["status_zh"], "候選驗證通過")
        self.assertIn("尚未發布", result["status_note_zh"])
        self.assertFalse(result["actionable"])


if __name__ == "__main__":
    unittest.main()
