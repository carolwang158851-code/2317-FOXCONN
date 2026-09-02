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

import warroom_integrated_authority as authority  # noqa: E402
import warroom_integrated_report_completion as completion  # noqa: E402
import warroom_report_trigger_runtime as runtime  # noqa: E402
from tests.test_major_event_report_lifecycle_persistence import (  # noqa: E402
    NOW,
    evidence,
    integration,
)


class Phase4CIntegratedAuthorityReportCompletionTests(unittest.TestCase):
    def setUp(self):
        self._evidence_env = patch.dict(
            os.environ, {"P1008_GOVERNED_EVIDENCE_ROOT": ""}
        )
        self._evidence_env.start()
        self.base = ROOT / "runtime" / "phase4c_completion_test_scratch"
        self.base.mkdir(parents=True, exist_ok=True)
        self.root = self.base / uuid.uuid4().hex
        self.root.mkdir()
        self.addCleanup(self.cleanup_scratch)
        self.addCleanup(self._evidence_env.stop)

    def cleanup_scratch(self):
        shutil.rmtree(self.root, ignore_errors=True)
        try:
            self.base.rmdir()
        except OSError:
            pass

    def first_revision(self):
        payload = integration([evidence()])
        runtime.persist_integration_result(
            self.root,
            {key: value for key, value in payload.items() if key != "canonical_sha256"},
        )
        receipt = runtime.evaluate_and_persist(self.root, evaluated_at_utc=NOW)
        materialized = runtime.materialize_major_event_provenance(self.root, receipt)
        persisted = runtime.persist_major_event_report_candidate(
            self.root,
            receipt,
            materialized,
            revision=1,
            persisted_at_utc="2026-08-12T09:00:00Z",
        )
        rendered = runtime.render_major_event_revision(
            self.root, report_key=persisted["report_key"], revision=1
        )
        self.assertEqual(rendered["status"], "OWNER_REVIEW_REQUIRED")
        return receipt, materialized, persisted, rendered

    def approve(self, rendered):
        return runtime.record_major_event_owner_decision(
            self.root,
            report_key=rendered["report_key"],
            revision=rendered["revision"],
            decision="APPROVE",
            decision_id="OWNER-PHASE4C-E2E-APPROVE",
            decided_by="P1008_OWNER",
            decided_at_utc="2026-09-02T01:00:00Z",
            expected_report_candidate_sha256=rendered["reportCandidateSha256"],
            expected_owner_review_persistence_sha256=rendered[
                "ownerReviewPersistenceSha256"
            ],
            expected_rendered_artifact_hashes=[
                item["sha256"] for item in rendered["artifacts"]
            ],
        )

    def authorize(self, rendered, decision, *, authorization_id="OWNER-PHASE4C-PUBLISH-AUTH"):
        return runtime.authorize_major_event_publication(
            self.root,
            report_key=rendered["report_key"],
            revision=rendered["revision"],
            authorization_id=authorization_id,
            authorized_by="P1008_OWNER_PUBLICATION_AUTHORIZER",
            authorized_at_utc="2026-09-02T01:05:00Z",
            expected_owner_decision_sha256=decision["decisionSha256"],
            expected_report_candidate_sha256=rendered["reportCandidateSha256"],
            expected_rendered_artifact_hashes=[
                item["sha256"] for item in rendered["artifacts"]
            ],
        )

    def test_phase3a_candidate_is_byte_bound_and_non_authoritative(self):
        view = runtime.integrated_authority_status()
        self.assertEqual(view["candidateManifestVersion"], "1.5.0-candidate.1")
        self.assertEqual(len(view["files"]), 5)
        self.assertFalse(view["authoritative"])
        self.assertFalse(view["actionable"])
        self.assertFalse(view["publishAuthorized"])
        self.assertTrue(view["ownerPromotionRequired"])
        self.assertEqual(view["promotionStatus"], "OWNER_PROMOTION_REQUIRED")
        self.assertEqual(
            view["candidateManifestSha256"], authority.EXPECTED_MANIFEST_SHA256
        )

    def test_candidate_hash_or_governance_drift_fails_closed(self):
        fake = self.root / "fake_code"
        shutil.copytree(ROOT / "authority_candidates", fake / "authority_candidates")
        shutil.copytree(
            ROOT / "contracts" / "p1008_authority_integration",
            fake / "contracts" / "p1008_authority_integration",
        )
        target = fake / "authority_candidates/phase3a_canonical_v1/data/2317_daily_price.csv"
        target.write_bytes(target.read_bytes() + b"tampered")
        with self.assertRaises(authority.IntegratedAuthorityError):
            authority.load_candidate(fake)

    def test_capability_matrix_keeps_daily_out_of_formal_library(self):
        matrix = completion.capability_matrix(ROOT)
        self.assertFalse(matrix["DAILY"]["formalReportEligible"])
        self.assertFalse(matrix["DAILY"]["privateLibraryEligible"])
        for event_type in ("MONTHLY_REVENUE", "QUARTERLY_EARNINGS", "MAJOR_EVENT"):
            self.assertTrue(matrix[event_type]["formalReportEligible"])
        self.assertIn("ROIC_FCF_EV_ANALYTICS", matrix["QUARTERLY_EARNINGS"]["wiring"])
        self.assertIn("ROIC_FCF_EV_ANALYTICS", matrix["MAJOR_EVENT"]["wiring"])

    def test_offline_e2e_composes_renders_reviews_and_authorizes_without_publish(self):
        receipt, materialized, persisted, rendered = self.first_revision()
        self.assertEqual(receipt["event_type"], "MAJOR_EVENT")
        self.assertEqual(materialized["status"], "OWNER_REVIEW_REQUIRED")
        self.assertEqual(persisted["status"], "OWNER_REVIEW_REQUIRED")
        html_item = next(item for item in rendered["artifacts"] if item["format"] == "HTML")
        pdf_item = next(item for item in rendered["artifacts"] if item["format"] == "PDF")
        html = (self.root / html_item["locator"]).read_text(encoding="utf-8")
        self.assertIn("P1008-PHASE3A-CANONICAL-AUTHORITY-CANDIDATE-20260901", html)
        self.assertEqual(len(PdfReader(str(self.root / pdf_item["locator"])).pages), 1)
        decision = self.approve(rendered)
        self.assertEqual(decision["status"], "APPROVED")
        denied = runtime.validate_major_event_publication_gate(
            self.root, report_key=rendered["report_key"], revision=1
        )
        self.assertEqual(denied["status"], "DENIED")
        self.assertFalse(denied["publishAuthorized"])
        authorized = self.authorize(rendered, decision)
        self.assertEqual(authorized["status"], "AUTHORIZED_NOT_PUBLISHED")
        self.assertTrue(authorized["publishAuthorized"])
        self.assertFalse(authorized["published"])
        self.assertFalse(authorized["publicationComplete"])
        self.assertTrue(authorized["authority_owner_promotion_required"])
        self.assertFalse(authorized["authority_authoritative"])

    def test_owner_approve_alone_never_authorizes_or_publishes(self):
        _, _, _, rendered = self.first_revision()
        decision = self.approve(rendered)
        self.assertFalse(decision["publishAuthorized"])
        gate = runtime.validate_major_event_publication_gate(
            self.root, report_key=rendered["report_key"], revision=1
        )
        self.assertEqual(gate["reason"], "EXPLICIT_REVISION_AUTHORIZATION_REQUIRED")
        self.assertFalse(gate["published"])

    def test_publication_authorization_replay_is_idempotent_and_duplicate_is_rejected(self):
        _, _, _, rendered = self.first_revision()
        decision = self.approve(rendered)
        first = self.authorize(rendered, decision)
        replay = self.authorize(rendered, decision)
        duplicate = self.authorize(
            rendered, decision, authorization_id="OWNER-PHASE4C-PUBLISH-AUTH-OTHER"
        )
        self.assertEqual(first["status"], "AUTHORIZED_NOT_PUBLISHED")
        self.assertEqual(replay["status"], "IDEMPOTENT_AUTHORIZATION_REPLAY")
        self.assertEqual(duplicate["status"], "FAIL_CLOSED")
        self.assertIn("DUPLICATE", duplicate["reason"])

    def test_tampered_authorization_and_artifact_fail_closed(self):
        _, _, _, rendered = self.first_revision()
        decision = self.approve(rendered)
        authorized = self.authorize(rendered, decision)
        auth_path = self.root / authorized["authorizationLocator"]
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
        payload["revision"] = 2
        auth_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        invalid = runtime.validate_major_event_publication_gate(
            self.root, report_key=rendered["report_key"], revision=1
        )
        self.assertEqual(invalid["status"], "FAIL_CLOSED")

    def test_stale_context_and_non_approve_decision_are_rejected(self):
        _, _, _, rendered = self.first_revision()
        decision = self.approve(rendered)
        stale = runtime.authorize_major_event_publication(
            self.root,
            report_key=rendered["report_key"], revision=1,
            authorization_id="OWNER-PHASE4C-STALE",
            authorized_by="P1008_OWNER_PUBLICATION_AUTHORIZER",
            authorized_at_utc="2026-09-02T01:05:00Z",
            expected_owner_decision_sha256="0" * 64,
            expected_report_candidate_sha256=rendered["reportCandidateSha256"],
            expected_rendered_artifact_hashes=[item["sha256"] for item in rendered["artifacts"]],
        )
        self.assertEqual(stale["status"], "FAIL_CLOSED")
        self.assertIn("STALE", stale["reason"])
        self.assertEqual(decision["status"], "APPROVED")


if __name__ == "__main__":
    unittest.main()
