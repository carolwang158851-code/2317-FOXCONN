from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PUBLISHER_PATH = PACKAGE_ROOT / "tools" / "owner_publish_csv_v2.py"
SPEC = importlib.util.spec_from_file_location(
    "p1008_owner_publish_csv_v2_macro_stage2b_test", PUBLISHER_PATH
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load publisher: {PUBLISHER_PATH}")
PUBLISHER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PUBLISHER
SPEC.loader.exec_module(PUBLISHER)
REMEDIATION_PATH = PACKAGE_ROOT / "tools" / "warroom_macro_remediation.py"
REMEDIATION_SPEC = importlib.util.spec_from_file_location(
    "p1008_warroom_macro_remediation_stage2b_test", REMEDIATION_PATH
)
if REMEDIATION_SPEC is None or REMEDIATION_SPEC.loader is None:
    raise RuntimeError(f"Unable to load remediation builder: {REMEDIATION_PATH}")
REMEDIATION = importlib.util.module_from_spec(REMEDIATION_SPEC)
sys.modules[REMEDIATION_SPEC.name] = REMEDIATION
REMEDIATION_SPEC.loader.exec_module(REMEDIATION)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def controlled_test_temp_root() -> Path:
    configured = os.environ.get("P1008_TEST_TEMP_ROOT", "").strip()
    if configured:
        root = Path(configured)
    else:
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if not local_app_data:
            raise RuntimeError("P1008_TEST_TEMP_ROOT_REQUIRED")
        root = Path(local_app_data) / "P1008" / "pytest-temp"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


class OwnerPublishCsvV2MacroStage2BTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = (
            controlled_test_temp_root()
            / "macro_stage2b_owner_gate_tests"
            / uuid.uuid4().hex
        )
        (self.root / "data").mkdir(parents=True)
        self.evidence = self.root / "runtime" / "evidence"
        self.evidence.mkdir(parents=True)
        self.formal = self.root / PUBLISHER.MACRO_TARGET
        self.manifest = self.root / PUBLISHER.MANIFEST_PATH
        self.canonical = subprocess.run(
            [
                "git",
                "cat-file",
                "blob",
                f"{PUBLISHER.MACRO_STAGE2B_REQUIRED_HEAD}:{PUBLISHER.MACRO_TARGET}",
            ],
            cwd=PACKAGE_ROOT,
            check=True,
            capture_output=True,
        ).stdout
        self.formal.write_bytes(self.canonical)
        self.manifest.write_bytes(
            subprocess.run(
                [
                    "git",
                    "cat-file",
                    "blob",
                    (
                        f"{PUBLISHER.MACRO_STAGE2B_REQUIRED_HEAD}:"
                        f"{PUBLISHER.MANIFEST_PATH}"
                    ),
                ],
                cwd=PACKAGE_ROOT,
                check=True,
                capture_output=True,
            ).stdout
        )
        candidate_result = REMEDIATION.build_candidate(
            self.root, self.evidence / "candidate-build"
        )
        self.candidate = Path(candidate_result["candidate_path"])
        self.receipt = self.evidence / "ROW_IDENTITY_RECEIPT.json"
        self.receipt.write_text(
            json.dumps(
                {
                    "input": {
                        "source": "CANONICAL_GIT_BLOB_ONLY",
                        "sha256": PUBLISHER.MACRO_STAGE2B_CANONICAL_BEFORE_SHA256,
                    },
                    "canonical_statistics": {"data_record_count": 39},
                    "row_identities": [
                        {
                            "canonical_data_record_ordinal": ordinal,
                            "physical_file_line_number": physical_line,
                            "date": date,
                            "from_rejected_extra_seven_rows": False,
                        }
                        for ordinal, physical_line, date, _ in (
                            PUBLISHER.MACRO_STAGE2B_EXPECTED_IDENTITIES
                        )
                    ],
                    "candidate": {
                        "sha256": PUBLISHER.MACRO_STAGE2B_CANDIDATE_SHA256
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.before = (sha256(self.formal), sha256(self.manifest))
        self.addCleanup(
            lambda: shutil.rmtree(self.root) if self.root.exists() else None
        )

    def run_publish(
        self,
        output_name: str,
        *,
        publish: bool = False,
        phrase: str | None = PUBLISHER.MACRO_STAGE2B_APPROVAL_PHRASE,
        dry_run_journal: Path | None = None,
    ) -> dict:
        return PUBLISHER.run_macro_stage2b_publish(
            self.root,
            self.candidate,
            self.receipt,
            self.root / "runtime" / output_name,
            publish=publish,
            approval_phrase=phrase,
            dry_run_journal=dry_run_journal,
            canonical_blob_bytes=self.canonical,
        )

    def test_exact_candidate_dry_run_preserves_formal_authority(self) -> None:
        result = self.run_publish("dry-run")
        self.assertEqual(result["status"], "DRY_RUN_PASS")
        self.assertEqual(result["candidate_sha256"], PUBLISHER.MACRO_STAGE2B_CANDIDATE_SHA256)
        self.assertEqual(result["rows"], 39)
        self.assertEqual(result["cutoff"], "2026-07-10")
        self.assertEqual(len(result["differences"]), 5)
        self.assertEqual(self.before, (sha256(self.formal), sha256(self.manifest)))
        self.assertFalse(result["actionable"])

    def test_missing_or_wrong_owner_phrase_fails_closed(self) -> None:
        for index, phrase in enumerate((None, "OWNER_APPROVE_WRONG")):
            with self.subTest(phrase=phrase):
                with self.assertRaisesRegex(ValueError, "exact Owner approval phrase"):
                    self.run_publish(f"wrong-phrase-{index}", phrase=phrase)
        self.assertEqual(self.before, (sha256(self.formal), sha256(self.manifest)))

    def test_candidate_sha_mismatch_fails_closed(self) -> None:
        self.candidate.write_bytes(self.candidate.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "candidate SHA-256 mismatch"):
            self.run_publish("bad-candidate")
        self.assertEqual(self.before, (sha256(self.formal), sha256(self.manifest)))

    def test_row_identity_receipt_content_mismatch_fails_closed(self) -> None:
        payload = json.loads(self.receipt.read_text(encoding="utf-8"))
        payload["row_identities"][0]["date"] = "2021-03-30"
        self.receipt.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "receipt content mismatch"):
            self.run_publish("bad-receipt")
        self.assertEqual(self.before, (sha256(self.formal), sha256(self.manifest)))

    def test_formal_content_drift_beyond_line_endings_fails_closed(self) -> None:
        self.formal.write_bytes(self.formal.read_bytes().replace(b"2021-03-31", b"2021-03-30", 1))
        with self.assertRaisesRegex(ValueError, "beyond line endings"):
            self.run_publish("bad-formal")
        self.assertEqual(sha256(self.manifest), self.before[1])

    def test_exact_publish_atomically_replaces_macro_and_manifest(self) -> None:
        dry = self.run_publish("dry-run")
        result = self.run_publish(
            "publish",
            publish=True,
            dry_run_journal=self.root / "runtime" / "dry-run" / "PUBLISH_JOURNAL.json",
        )
        self.assertEqual(dry["status"], "DRY_RUN_PASS")
        self.assertEqual(result["status"], "PUBLISHED")
        self.assertEqual(sha256(self.formal), PUBLISHER.MACRO_STAGE2B_CANDIDATE_SHA256)
        self.assertEqual(sha256(self.manifest), PUBLISHER.MACRO_STAGE2B_MANIFEST_AFTER_SHA256)
        self.assertFalse(result["rollback_performed"])
        self.assertFalse(result["actionable"])

    def test_manifest_write_failure_rolls_back_both_files(self) -> None:
        self.run_publish("dry-run")
        original_atomic_write = PUBLISHER._atomic_write_bytes
        failure_sent = False

        def fail_manifest_once(path: Path, content: bytes) -> None:
            nonlocal failure_sent
            if path.name == "CSV_AUTHORITY_MANIFEST.json" and not failure_sent:
                failure_sent = True
                raise OSError("injected manifest failure")
            original_atomic_write(path, content)

        with mock.patch.object(
            PUBLISHER, "_atomic_write_bytes", side_effect=fail_manifest_once
        ):
            with self.assertRaisesRegex(RuntimeError, "CSV and manifest restored"):
                self.run_publish(
                    "publish",
                    publish=True,
                    dry_run_journal=(
                        self.root
                        / "runtime"
                        / "dry-run"
                        / "PUBLISH_JOURNAL.json"
                    ),
                )
        self.assertEqual(self.before, (sha256(self.formal), sha256(self.manifest)))
        journal = json.loads(
            (
                self.root / "runtime" / "publish" / "PUBLISH_JOURNAL.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(journal["status"], "ROLLED_BACK")
        self.assertTrue(journal["rollback_performed"])
        self.assertTrue(journal["rollback_verified"])


if __name__ == "__main__":
    unittest.main()
