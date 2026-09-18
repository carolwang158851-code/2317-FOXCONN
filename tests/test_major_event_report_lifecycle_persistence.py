from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import warroom_report_governance as governance  # noqa: E402
import warroom_report_trigger_runtime as runtime  # noqa: E402
import warroom_rolling_brief as rolling  # noqa: E402


NOW = "2026-08-12T08:00:00Z"
HASH = "A" * 64


def evidence(**changes):
    item = {
        "event_id": "MATERIAL-DISCLOSURE-001",
        "event_type": "MATERIAL_COMPANY_DISCLOSURE",
        "event_status": "MATERIAL_EVENT_CONFIRMED",
        "occurred_at_utc": "2026-08-12T06:00:00Z",
        "published_at_utc": "2026-08-12T06:00:00Z",
        "received_at_utc": "2026-08-12T06:05:00Z",
        "data_cutoff": "2026-06-30",
        "source_id": "HON_HAI_IR_MATERIAL",
        "source_type": "COMPANY_FILING",
        "source_class": "AUTHORITY",
        "source_locator": "official-ir/material-disclosure.pdf",
        "source_url": "https://www.honhai.com/en-us/investor-relations",
        "source_tier": "OFFICIAL",
        "source_hash": HASH,
        "originating_chain_id": "HON_HAI_IR",
        "evidence_ids": ["E-MATERIAL-001"],
        "claim_summary": "Validated material company disclosure",
        "affected_kpis": ["revenue", "margin"],
        "materiality": "HIGH",
        "novelty": "NEW",
        "evidence_status": "CONFIRMED",
        "validation_status": "OFFICIAL_VERIFIED",
        "confidence": 1.0,
        "quality_metadata": {"official": True},
        "provenance": {"adapter": "ResearchContentOrchestrator"},
        "canonical_event_id": "P1008_MATERIAL_DISCLOSURE_20260812",
        "verification_status": "OFFICIAL_VERIFIED",
        "counter_evidence_ids": [],
        "missing_evidence": [],
        "source_conflicts": [],
        "actionable": False,
    }
    item.update(changes)
    return item


def integration(items, *, event_type="MAJOR_EVENT"):
    decision = governance.evaluate_report_trigger(
        report_key="P1008_MAJOR_EVENT_20260812",
        revision=1,
        event_evidence=items,
        evaluated_at_utc=NOW,
    )
    return runtime.build_integration_artifact({
        "record_type": runtime.INTEGRATION_RECORD_TYPE,
        "report_key": "P1008_MAJOR_EVENT_20260812",
        "revision": 1,
        "evaluated_at_utc": NOW,
        "validated_event_evidence": items,
        "report_trigger_decision": decision,
        "report_generated": False,
        "actionable": False,
    })


class MajorEventReportLifecyclePersistenceTests(unittest.TestCase):
    def setUp(self):
        self._evidence_env = patch.dict(
            os.environ, {"P1008_GOVERNED_EVIDENCE_ROOT": ""}
        )
        self._evidence_env.start()
        self.base = ROOT / "runtime" / "major_event_persistence_test_scratch"
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

    def receipt_and_materialized(self, items=None):
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
        return runtime.persist_major_event_report_candidate(
            self.root,
            receipt,
            materialized,
            revision=revision,
            persisted_at_utc="2026-08-12T09:00:00Z",
        )

    def read_manifests(self):
        lifecycle = json.loads(
            (self.root / rolling.RUNTIME_MANIFEST_REL).read_text(encoding="utf-8")
        )
        library = json.loads(
            (self.root / rolling.REPORT_MANIFEST_REL).read_text(encoding="utf-8")
        )
        return lifecycle, library

    def test_first_persistence_separates_lifecycle_library_and_owner_review(self):
        receipt, materialized = self.receipt_and_materialized()
        result = self.persist(receipt, materialized, 1)
        self.assertEqual(result["status"], "OWNER_REVIEW_REQUIRED")
        self.assertTrue(result["persisted"])
        self.assertEqual(result["revision"], 1)
        lifecycle, library = self.read_manifests()
        self.assertEqual(len(lifecycle["reports"]), 1)
        self.assertEqual(len(library["reports"]), 1)
        self.assertEqual(
            lifecycle["reports"][0]["recordType"],
            "P1008_MAJOR_EVENT_REPORT_LIFECYCLE_ENTRY_V1",
        )
        self.assertEqual(
            library["reports"][0]["recordType"],
            "P1008_MAJOR_EVENT_PRIVATE_LIBRARY_ENTRY_V1",
        )
        self.assertFalse(lifecycle["reports"][0]["privateLibraryOwned"])
        self.assertFalse(library["reports"][0]["lifecycleOwned"])
        owner = json.loads(
            (self.root / result["ownerReviewLocator"]).read_text(encoding="utf-8")
        )
        self.assertEqual(owner["status"], "OWNER_REVIEW_REQUIRED")
        self.assertFalse(owner["ownerApproved"])
        self.assertFalse(owner["publishAuthorized"])
        self.assertFalse(owner["actionable"])

    def test_replay_is_idempotent_and_never_creates_duplicate_revision(self):
        receipt, materialized = self.receipt_and_materialized()
        first = self.persist(receipt, materialized, 1)
        replay = self.persist(receipt, materialized, 1)
        higher_replay = self.persist(receipt, materialized, 2)
        self.assertTrue(first["persisted"])
        for result in (replay, higher_replay):
            self.assertEqual(result["status"], "IDEMPOTENT_REPLAY")
            self.assertEqual(result["revision"], 1)
            self.assertFalse(result["persisted"])
            self.assertFalse(result["duplicateRevisionCreated"])
        lifecycle, library = self.read_manifests()
        self.assertEqual(len(lifecycle["reports"]), 1)
        self.assertEqual(len(library["reports"]), 1)

    def test_changed_governed_content_requires_next_explicit_revision(self):
        first_receipt, first_materialized = self.receipt_and_materialized()
        first = self.persist(first_receipt, first_materialized, 1)
        supplemental = evidence(
            source_id="HON_HAI_IR_MATERIAL_UPDATE",
            source_hash="B" * 64,
            originating_chain_id="HON_HAI_IR_UPDATE",
            evidence_ids=["E-MATERIAL-002"],
            claim_summary="Validated material disclosure with new outlook",
        )
        second_receipt, second_materialized = self.receipt_and_materialized(
            [evidence(), supplemental]
        )
        rejected = self.persist(second_receipt, second_materialized, 3)
        self.assertEqual(rejected["status"], "REVIEW_REQUIRED")
        second = self.persist(second_receipt, second_materialized, 2)
        self.assertEqual(second["status"], "OWNER_REVIEW_REQUIRED")
        self.assertEqual(second["previousRevision"], 1)
        lifecycle, library = self.read_manifests()
        for manifest in (lifecycle, library):
            history = sorted(manifest["reports"], key=lambda item: item["revision"])
            self.assertEqual([item["revision"] for item in history], [1, 2])
            self.assertEqual(
                history[1]["previousGovernedContentSha256"],
                first["governedContentSha256"],
            )

    def test_tampered_lifecycle_or_library_lineage_fails_closed(self):
        for target in (rolling.RUNTIME_MANIFEST_REL, rolling.REPORT_MANIFEST_REL):
            with self.subTest(target=target):
                receipt, materialized = self.receipt_and_materialized()
                self.persist(receipt, materialized, 1)
                path = self.root / target
                manifest = json.loads(path.read_text(encoding="utf-8"))
                manifest["reports"][0]["eventFingerprint"] = "0" * 64
                path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
                result = self.persist(receipt, materialized, 1)
                self.assertEqual(result["status"], "FAIL_CLOSED")
                shutil.rmtree(self.root)
                self.root.mkdir()

    def test_stale_latest_and_tampered_owner_state_fail_closed(self):
        receipt, materialized = self.receipt_and_materialized()
        persisted = self.persist(receipt, materialized, 1)
        lifecycle, _ = self.read_manifests()
        slot = next(key for key in lifecycle["latest"] if key.startswith("major_event:"))
        lifecycle["latest"][slot]["revision"] = 99
        (self.root / rolling.RUNTIME_MANIFEST_REL).write_text(
            json.dumps(lifecycle) + "\n", encoding="utf-8"
        )
        self.assertEqual(self.persist(receipt, materialized, 1)["status"], "FAIL_CLOSED")

        shutil.rmtree(self.root)
        self.root.mkdir()
        receipt, materialized = self.receipt_and_materialized()
        persisted = self.persist(receipt, materialized, 1)
        owner_path = self.root / persisted["ownerReviewLocator"]
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        owner["ownerApproved"] = True
        owner_path.write_text(json.dumps(owner) + "\n", encoding="utf-8")
        self.assertEqual(self.persist(receipt, materialized, 1)["status"], "FAIL_CLOSED")

    def test_daily_monthly_and_quarterly_cannot_enter_major_event_persistence(self):
        for event_type, canonical_id in (
            ("DAILY", "P1008_DAILY_20260812"),
            ("MONTHLY_REVENUE", "P1008_MONTHLY_REVENUE_202607"),
            ("QUARTERLY_EARNINGS", "P1008_FY2026_Q2_EARNINGS"),
        ):
            with self.subTest(event_type=event_type):
                item = evidence(event_type=event_type, canonical_event_id=canonical_id)
                payload = integration([item])
                runtime.persist_integration_result(
                    self.root,
                    {key: value for key, value in payload.items() if key != "canonical_sha256"},
                )
                receipt = runtime.evaluate_and_persist(self.root, evaluated_at_utc=NOW)
                materialized = runtime.materialize_major_event_provenance(self.root, receipt)
                result = self.persist(receipt, materialized, 1)
                self.assertEqual(result["status"], "FAIL_CLOSED")
                self.assertFalse(result["persisted"])
                if (self.root / rolling.REPORT_MANIFEST_REL).exists():
                    self.assertEqual(
                        json.loads(
                            (self.root / rolling.REPORT_MANIFEST_REL).read_text(
                                encoding="utf-8"
                            )
                        )["reports"],
                        [],
                    )
                shutil.rmtree(self.root)
                self.root.mkdir()


if __name__ == "__main__":
    unittest.main()
