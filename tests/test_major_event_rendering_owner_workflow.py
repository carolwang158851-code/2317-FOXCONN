from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import warroom_report_trigger_runtime as runtime  # noqa: E402
import warroom_rolling_brief as rolling  # noqa: E402
from tests.test_major_event_report_lifecycle_persistence import (  # noqa: E402
    NOW,
    evidence,
    integration,
)


class MajorEventRenderingOwnerWorkflowTests(unittest.TestCase):
    def setUp(self):
        self._evidence_env = patch.dict(
            os.environ, {"P1008_GOVERNED_EVIDENCE_ROOT": ""}
        )
        self._evidence_env.start()
        self.base = ROOT / "runtime" / "major_event_rendering_test_scratch"
        self.base.mkdir(parents=True, exist_ok=True)
        self.root = self.base / uuid.uuid4().hex
        self.root.mkdir()
        self.addCleanup(self.cleanup_scratch)
        self.addCleanup(self._evidence_env.stop)

    def cleanup_scratch(self):
        for _attempt in range(3):
            shutil.rmtree(self.root, ignore_errors=True)
            if not self.root.exists():
                break
        try:
            self.base.rmdir()
        except OSError:
            pass

    def materialize(self, items=None):
        payload = integration(items or [evidence()])
        runtime.persist_integration_result(
            self.root,
            {key: value for key, value in payload.items() if key != "canonical_sha256"},
        )
        receipt = runtime.evaluate_and_persist(self.root, evaluated_at_utc=NOW)
        materialized = runtime.materialize_major_event_provenance(self.root, receipt)
        self.assertEqual(materialized["status"], "OWNER_REVIEW_REQUIRED")
        return receipt, materialized

    def persist(self, receipt, materialized, revision):
        result = runtime.persist_major_event_report_candidate(
            self.root,
            receipt,
            materialized,
            revision=revision,
            persisted_at_utc=f"2026-08-12T09:0{revision}:00Z",
        )
        self.assertEqual(result["status"], "OWNER_REVIEW_REQUIRED")
        return result

    def first_revision(self):
        receipt, materialized = self.materialize()
        persisted = self.persist(receipt, materialized, 1)
        rendered = runtime.render_major_event_revision(
            self.root, report_key=persisted["report_key"], revision=1
        )
        self.assertEqual(rendered["status"], "OWNER_REVIEW_REQUIRED")
        return receipt, materialized, persisted, rendered

    def decision(self, rendered, value, *, revision=None, token=None, hashes=None, suffix="1"):
        return runtime.record_major_event_owner_decision(
            self.root,
            report_key=rendered["report_key"],
            revision=revision or rendered["revision"],
            decision=value,
            decision_id=f"OWNER-MAJOR-EVENT-{value}-{suffix}",
            decided_by="P1008_OWNER",
            decided_at_utc="2026-08-12T10:00:00Z",
            expected_report_candidate_sha256=rendered["reportCandidateSha256"],
            expected_owner_review_persistence_sha256=(
                token or rendered["ownerReviewPersistenceSha256"]
            ),
            expected_rendered_artifact_hashes=(
                hashes or [item["sha256"] for item in rendered["artifacts"]]
            ),
        )

    def test_governed_html_and_pdf_rendering_records_verified_hashes(self):
        _, _, _, rendered = self.first_revision()
        self.assertTrue(rendered["rendered"])
        self.assertFalse(rendered["published"])
        formats = {item["format"]: item for item in rendered["artifacts"]}
        self.assertEqual(set(formats), {"HTML", "PDF"})
        html_path = self.root / formats["HTML"]["locator"]
        pdf_path = self.root / formats["PDF"]["locator"]
        self.assertIn("NON-PUBLISHED", html_path.read_text(encoding="utf-8"))
        self.assertEqual(len(PdfReader(str(pdf_path)).pages), 1)
        for item in formats.values():
            path = self.root / item["locator"]
            self.assertEqual(runtime.major_event_report_persistence._sha256(path.read_bytes()), item["sha256"])
            self.assertEqual(path.stat().st_size, item["sizeBytes"])
        lifecycle = json.loads(
            (self.root / rolling.RUNTIME_MANIFEST_REL).read_text(encoding="utf-8")
        )["reports"][0]
        library = json.loads(
            (self.root / rolling.REPORT_MANIFEST_REL).read_text(encoding="utf-8")
        )["reports"][0]
        self.assertEqual(lifecycle["report_key"], rendered["report_key"])
        self.assertEqual(lifecycle["revision"], rendered["revision"])
        self.assertEqual(lifecycle["renderedArtifacts"], rendered["artifacts"])
        self.assertEqual(library["renderedArtifacts"], rendered["artifacts"])
        owner_path = self.root / lifecycle["ownerReviewLocator"]
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        self.assertEqual(owner["report_key"], rendered["report_key"])
        self.assertEqual(owner["revision"], rendered["revision"])
        self.assertEqual(owner["baseline_provenance"], rendered["baselineProvenance"])
        self.assertEqual(owner["rendered_artifacts"], rendered["artifacts"])
        replay = runtime.render_major_event_revision(
            self.root, report_key=rendered["report_key"], revision=1
        )
        self.assertEqual(replay["status"], "IDEMPOTENT_RENDER_REPLAY")

    def test_approve_sets_eligibility_without_publication(self):
        _, _, _, rendered = self.first_revision()
        result = self.decision(rendered, "APPROVE")
        self.assertEqual(result["status"], "APPROVED")
        self.assertTrue(result["publicationEligibility"])
        self.assertFalse(result["published"])
        self.assertFalse(result["publicationComplete"])
        self.assertFalse(result["publishAuthorized"])
        self.assertFalse(result["actionable"])

    def test_reject_and_revision_required_are_revision_specific_terminal_decisions(self):
        for decision in ("REJECT", "REVISION_REQUIRED"):
            with self.subTest(decision=decision):
                _, _, _, rendered = self.first_revision()
                result = self.decision(rendered, decision)
                self.assertEqual(result["status"], decision)
                self.assertFalse(result["publicationEligibility"])
                repeated = self.decision(rendered, "APPROVE", suffix="2")
                self.assertIn(repeated["status"], {"FAIL_CLOSED", "REVIEW_REQUIRED"})
                shutil.rmtree(self.root)
                self.root.mkdir()

    def test_cross_revision_and_stale_owner_context_are_rejected(self):
        _, _, _, first_rendered = self.first_revision()
        supplemental = evidence(
            source_id="HON_HAI_IR_MATERIAL_UPDATE",
            source_hash="B" * 64,
            originating_chain_id="HON_HAI_IR_UPDATE",
            evidence_ids=["E-MATERIAL-002"],
            claim_summary="Validated material disclosure with new outlook",
        )
        receipt, materialized = self.materialize([evidence(), supplemental])
        second_persisted = self.persist(receipt, materialized, 2)
        second_rendered = runtime.render_major_event_revision(
            self.root, report_key=second_persisted["report_key"], revision=2
        )
        self.assertEqual(second_rendered["status"], "OWNER_REVIEW_REQUIRED")
        cross = self.decision(
            second_rendered,
            "APPROVE",
            token=first_rendered["ownerReviewPersistenceSha256"],
            hashes=[item["sha256"] for item in first_rendered["artifacts"]],
        )
        self.assertEqual(cross["status"], "FAIL_CLOSED")
        approved = self.decision(second_rendered, "APPROVE", suffix="2")
        self.assertEqual(approved["status"], "APPROVED")
        stale = self.decision(second_rendered, "REJECT", suffix="3")
        self.assertEqual(stale["status"], "FAIL_CLOSED")

    def test_tampered_artifact_fails_closed(self):
        _, _, _, rendered = self.first_revision()
        html_item = next(item for item in rendered["artifacts"] if item["format"] == "HTML")
        (self.root / html_item["locator"]).write_text("tampered", encoding="utf-8")
        result = self.decision(rendered, "APPROVE")
        self.assertEqual(result["status"], "FAIL_CLOSED")
        self.assertIn("ARTIFACT_HASH_MISMATCH", result["reason"])

    def test_previous_revision_render_and_decision_lineage_is_preserved(self):
        _, _, _, first_rendered = self.first_revision()
        rejected = self.decision(first_rendered, "REJECT")
        first_paths = [self.root / item["locator"] for item in first_rendered["artifacts"]]
        supplemental = evidence(
            source_id="HON_HAI_IR_MATERIAL_UPDATE",
            source_hash="C" * 64,
            originating_chain_id="HON_HAI_IR_UPDATE",
            evidence_ids=["E-MATERIAL-003"],
            claim_summary="Validated material disclosure requiring revision",
        )
        receipt, materialized = self.materialize([evidence(), supplemental])
        persisted = self.persist(receipt, materialized, 2)
        second = runtime.render_major_event_revision(
            self.root, report_key=persisted["report_key"], revision=2
        )
        self.assertEqual(self.decision(second, "REVISION_REQUIRED", suffix="2")["status"], "REVISION_REQUIRED")
        self.assertTrue(all(path.is_file() for path in first_paths))
        lifecycle = json.loads(
            (self.root / rolling.RUNTIME_MANIFEST_REL).read_text(encoding="utf-8")
        )
        history = sorted(
            (item for item in lifecycle["reports"] if item.get("eventType") == "MAJOR_EVENT"),
            key=lambda item: item["revision"],
        )
        self.assertEqual([item["revision"] for item in history], [1, 2])
        self.assertEqual(history[0]["ownerDecisionState"], "REJECT")
        self.assertEqual(history[0]["ownerDecisionSha256"], rejected["decisionSha256"])

    def test_daily_monthly_and_quarterly_cannot_enter_rendering_or_decision_api(self):
        for event_type, key in (
            ("DAILY", "P1008_DAILY_20260812"),
            ("MONTHLY_REVENUE", "P1008_MONTHLY_REVENUE_202607"),
            ("QUARTERLY_EARNINGS", "P1008_FY2026_Q2_EARNINGS"),
        ):
            with self.subTest(event_type=event_type):
                rendered = runtime.render_major_event_revision(
                    self.root, report_key=key, revision=1
                )
                self.assertEqual(rendered["status"], "FAIL_CLOSED")
                self.assertFalse(rendered["rendered"])
                self.assertFalse(rendered["published"])


if __name__ == "__main__":
    unittest.main()
