from __future__ import annotations

import json
import os
import stat
import shutil
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SRC = ROOT / "modules" / "p1008_research_plugin" / "src"
for item in (str(TOOLS), str(SRC)):
    if item not in sys.path:
        sys.path.insert(0, item)

import warroom_publication_authorization_gate as publication_gate  # noqa: E402
import warroom_quarterly_report_completion as completion  # noqa: E402
from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline  # noqa: E402


def _remove_tree(path: Path) -> None:
    def clear_read_only(function, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if path.exists():
        shutil.rmtree(path, onexc=clear_read_only)


class QuarterlyReportCompletionWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence_root = (
            ROOT
            / "runtime"
            / "q2_historical_compatibility"
            / "F014BE750095543B_EDITORIAL_V1"
        )
        trigger_path = cls.evidence_root / "report_trigger" / "latest_decision.json"
        if not trigger_path.is_file():
            raise unittest.SkipTest("governed Q2 compatibility fixture unavailable")
        trigger = json.loads(trigger_path.read_text(encoding="utf-8"))
        cls.lineage = {
            "reportKey": trigger["report_key"],
            "revision": trigger["revision"],
            "eventType": trigger["event_type"],
            "canonicalEventId": trigger["canonical_event_id"],
            "triggerDecisionId": trigger["decision_id"],
            "triggerReceiptSha256": trigger["canonical_sha256"],
            "evidenceIds": trigger["qualifying_evidence_ids"],
            "authorityCutoffs": trigger["authority_cutoffs"],
            "actionable": False,
        }
        cls.base = ROOT / "runtime" / "report_production" / "test_scratch"
        cls.fixture_base = cls.base / f"quarterly-completion-source-{uuid.uuid4().hex}"
        cls.fixture_base.mkdir(parents=True)
        pipeline = PhaseB1Pipeline(ROOT, governed_evidence_root=cls.evidence_root)
        analysis = pipeline.build_analysis(
            output_base=cls.fixture_base, trigger_lineage=cls.lineage
        )
        cls.source_result = pipeline.build_report(
            run_id=analysis["run_id"], output_base=cls.fixture_base,
            trigger_lineage=cls.lineage,
            report_runtime="ENTERPRISE_VALUE_WAR_REPORT_V1",
        )
        cls.source_run_root = Path(cls.source_result["run_root"])

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "fixture_base"):
            _remove_tree(cls.fixture_base)
        try:
            cls.base.rmdir()
        except (AttributeError, OSError):
            pass

    def setUp(self) -> None:
        self.case = self.base / f"quarterly-completion-case-{uuid.uuid4().hex}"
        self.run_root = self.case / "run"
        shutil.copytree(self.source_run_root, self.run_root)
        self.state_root = self.case / "state"
        self.state_root.mkdir()
        self.result = {
            **self.source_result,
            "run_root": str(self.run_root),
            "candidate_output_root": str(self.run_root / "enterprise_value_war_report"),
        }

    def tearDown(self) -> None:
        _remove_tree(self.case)

    def complete(self):
        return completion.complete_quarterly_report(
            ROOT, self.result, persistence_root=self.state_root,
            completed_at_utc="2026-09-03T04:00:00Z",
        )

    def provenance_package(self) -> Path:
        package = self.case / "provenance-package"
        for relative in (
            completion.QUARTERLY_MASTER_REL,
            completion.AUTHORITY_MANIFEST_REL,
            completion.PROMOTION_RECEIPT_REL,
        ):
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        return package

    def test_live_manifest_evolution_keeps_promoted_quarterly_master_valid(self):
        authority = completion.validate_promoted_quarterly_authority(ROOT)
        receipt = json.loads(
            (ROOT / completion.PROMOTION_RECEIPT_REL).read_text(encoding="utf-8")
        )
        self.assertEqual(
            authority["masterSha256"],
            receipt["authority"]["master"]["afterSha256"],
        )
        self.assertNotEqual(
            authority["manifestSha256"],
            receipt["authority"]["manifest"]["afterSha256"],
        )

    def test_promoted_quarterly_authority_tamper_fails_closed(self):
        cases = (
            (completion.QUARTERLY_MASTER_REL, lambda path: path.write_bytes(path.read_bytes() + b"tamper")),
            (completion.AUTHORITY_MANIFEST_REL, lambda path: path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "E623CA082F2A080613C33F4155BA8006646E30D6A517DE926AF6108062F84D48",
                    "0" * 64,
                    1,
                ),
                encoding="utf-8",
            )),
            (completion.PROMOTION_RECEIPT_REL, lambda path: path.write_bytes(path.read_bytes() + b"tamper")),
        )
        for relative, tamper in cases:
            with self.subTest(relative=relative.as_posix()):
                package = self.provenance_package()
                tamper(package / relative)
                with self.assertRaises(completion.QuarterlyReportCompletionError):
                    completion.validate_promoted_quarterly_authority(package)
                _remove_tree(package)

    def test_q2_editorial_html_pdf_lifecycle_library_and_owner_are_persisted(self):
        result = self.complete()
        self.assertEqual(result["status"], "OWNER_REVIEW_REQUIRED")
        self.assertTrue(result["persisted"])
        self.assertEqual({item["format"] for item in result["artifacts"]}, {"HTML", "PDF"})
        editorial = json.loads(
            (self.run_root / "enterprise_value_war_report" / "editorial_validation.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(editorial["status"], "PASS")
        self.assertTrue(editorial["unsupportedNumericClaimsAbsent"])
        runtime = json.loads(
            (self.state_root / "runtime" / "warroom_report_manifest.json")
            .read_text(encoding="utf-8")
        )
        library = json.loads(
            (self.state_root / "reports" / "P1008_REPORT_MANIFEST.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(len(runtime["reports"]), 1)
        self.assertEqual(len(library["reports"]), 1)
        self.assertFalse(runtime["reports"][0]["privateLibraryOwned"])
        self.assertFalse(library["reports"][0]["lifecycleOwned"])
        owner = json.loads(
            (self.state_root / result["ownerReviewLocator"]).read_text(encoding="utf-8")
        )
        self.assertEqual(owner["status"], "OWNER_REVIEW_REQUIRED")
        self.assertEqual(owner["revision"], 1)
        self.assertFalse(owner["publishAuthorized"])
        self.assertFalse(owner["publication"])
        self.assertFalse(owner["publicationComplete"])

    def test_identical_replay_is_idempotent_and_creates_no_duplicate_revision(self):
        first = self.complete()
        replay = self.complete()
        self.assertEqual(first["status"], "OWNER_REVIEW_REQUIRED", first)
        self.assertEqual(first["revision"], 1)
        self.assertEqual(replay["status"], "IDEMPOTENT_REPLAY")
        self.assertFalse(replay["persisted"])
        self.assertFalse(replay["duplicateRevisionCreated"])
        for relative in (
            "runtime/warroom_report_manifest.json",
            "reports/P1008_REPORT_MANIFEST.json",
        ):
            manifest = json.loads((self.state_root / relative).read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["reports"]), 1)

    def test_artifact_or_provenance_tamper_fails_closed(self):
        first = self.complete()
        html_item = next(item for item in first["artifacts"] if item["format"] == "HTML")
        (self.state_root / html_item["locator"]).write_bytes(b"tampered")
        replay = self.complete()
        self.assertEqual(replay["status"], "FAIL_CLOSED")
        self.assertIn("hash mismatch", replay["reason"].lower())

    def test_publication_gate_denies_without_revision_authorization(self):
        result = self.complete()
        gate = publication_gate.validate_absent_authorization(
            self.state_root, report_key=result["report_key"], revision=result["revision"],
            event_type="QUARTERLY_EARNINGS",
        )
        self.assertEqual(gate["status"], "DENIED")
        self.assertEqual(gate["reason"], "EXPLICIT_REVISION_AUTHORIZATION_REQUIRED")
        self.assertFalse(gate["publishAuthorized"])
        self.assertFalse(gate["published"])
        self.assertFalse(gate["publicationComplete"])

    def test_daily_monthly_and_major_event_cannot_enter_quarterly_completion(self):
        for event_type in ("DAILY", "MONTHLY_REVENUE", "MAJOR_EVENT"):
            with self.subTest(event_type=event_type):
                manifest_path = self.run_root / "run_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                original = manifest["eventType"]
                manifest["eventType"] = event_type
                manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
                result = self.complete()
                self.assertEqual(result["status"], "FAIL_CLOSED")
                self.assertFalse(result["persisted"])
                manifest["eventType"] = original
                manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    def test_manifest_provenance_tamper_fails_closed(self):
        first = self.complete()
        runtime_path = self.state_root / "runtime" / "warroom_report_manifest.json"
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        runtime["reports"][0]["provenance"]["q2ResultsRawSha256"] = "0" * 64
        runtime_path.write_text(json.dumps(runtime) + "\n", encoding="utf-8")
        replay = self.complete()
        self.assertEqual(replay["status"], "FAIL_CLOSED")
        self.assertFalse(replay["persisted"])


if __name__ == "__main__":
    unittest.main()
