from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import warroom_q2_historical_compatibility as compat
import warroom_report_governance as governance
import warroom_report_trigger_runtime as runtime


class Q2HistoricalWorkflowCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        controlled = Path(os.environ.get("P1008_TEST_TEMP_ROOT", Path(os.environ["LOCALAPPDATA"]) / "P1008" / "pytest-temp"))
        controlled.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=controlled, prefix="p1008-q2-compat-")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.package = base / "package"
        self.historical = base / "historical-runtime"
        self.output = base / "materialized-runtime"
        self.raw_bytes = b"%PDF-1.7\ncontract-designated historical Q2 results\n"
        self.raw_sha = governance.sha256_bytes(self.raw_bytes)
        self.receipt_id = "IR-RECEIPT-TESTQ2"
        self.event_id = "IR-EVIDENCE-TESTQ2"
        raw_rel = Path(f"runtime/official_ir_evidence/q2/raw/{self.receipt_id}.bin")
        receipt_rel = Path(f"runtime/official_ir_evidence/q2/receipts/{self.receipt_id}.json")
        raw_path = self.historical.joinpath(*raw_rel.parts[1:])
        receipt_path = self.historical.joinpath(*receipt_rel.parts[1:])
        raw_path.parent.mkdir(parents=True)
        raw_path.write_bytes(self.raw_bytes)
        receipt = {
            "recordType": "P1008_OFFICIAL_IR_RAW_RECEIPT_V1", "receipt_id": self.receipt_id,
            "raw_sha256": self.raw_sha, "source_hash": self.raw_sha,
            "document_type": "RESULTS_DOCUMENT_CONFIRMED", "fiscal_period": "FY2026 Q2",
            "actionable": False,
        }
        runtime.atomic_write_json(receipt_path, receipt)
        self.receipt_sha = runtime._sha256_path(receipt_path)
        occurred = "2026-08-12T16:15:37Z"
        event = {
            "actionable": False, "affected_kpis": [], "canonical_event_id": "HON_HAI_FY2026_Q2_EARNINGS",
            "claim_summary": "Hon Hai published FY2026 Q2 financial results.", "confidence": 1.0,
            "counter_evidence_ids": [], "data_cutoff": "2026-08-12", "event_id": self.event_id,
            "event_status": "MATERIAL_EVENT_CONFIRMED", "event_type": "QUARTERLY_EARNINGS",
            "evidence_ids": [self.event_id], "evidence_status": "CONFIRMED",
            "materiality": "MATERIAL_RESULTS_PUBLICATION", "missing_evidence": [],
            "novelty": "NEW_OFFICIAL_DOCUMENT", "occurred_at_utc": occurred,
            "originating_chain_id": "OFFICIAL-IR-TEST", "published_at_utc": occurred,
            "quality_metadata": {"document_type": "RESULTS_DOCUMENT_CONFIRMED", "raw_byte_hash_bound": True},
            "provenance": {"raw_artifact_path": raw_rel.as_posix(), "receipt_path": receipt_rel.as_posix(),
                           "raw_sha256": self.raw_sha, "receipt_id": self.receipt_id},
            "received_at_utc": occurred, "source_class": "AUTHORITY", "source_conflicts": [],
            "source_hash": self.raw_sha, "source_id": "HON_HAI_INVESTOR_CONFERENCE",
            "source_locator": receipt_rel.as_posix(), "source_tier": "OFFICIAL",
            "source_type": "OFFICIAL_WEB", "source_url": "https://image.honhai.com/test.pdf",
            "validation_status": "OFFICIAL_VERIFIED", "verification_status": "OFFICIAL_VERIFIED",
        }
        self.event = event
        decision = governance.evaluate_report_trigger(
            report_key="P1008_FY2026_Q2_EARNINGS", revision=1,
            event_evidence=[event], evaluated_at_utc=occurred,
        )
        integration = runtime._with_hash({
            "record_type": runtime.INTEGRATION_RECORD_TYPE, "report_key": "P1008_FY2026_Q2_EARNINGS",
            "revision": 1, "evaluated_at_utc": occurred, "validated_event_evidence": [event],
            "report_trigger_decision": decision, "actionable": False,
        })
        integration_path = self.historical / compat.INTEGRATION_REL
        runtime.atomic_write_json(integration_path, integration)
        canonical = governance.deduplicate_event_evidence([event])
        current_trigger = runtime._receipt(
            integration=integration, evidence=[event], decision=decision,
            cross_validation=governance.evaluate_cross_validation([event]), canonical_event=canonical,
            baseline_binding=runtime._baseline_binding(decision, canonical),
        )
        legacy = {key: value for key, value in current_trigger.items()
                  if key not in {"canonical_sha256", "candidate_workflow", "analysis_baseline_binding"}}
        legacy["candidate_workflow"] = None
        legacy["analysis_baseline_binding"] = None
        legacy = runtime._with_hash(legacy)
        trigger_path = self.historical / compat.TRIGGER_REL
        runtime.atomic_write_json(trigger_path, legacy)
        analysis = self.package / compat.ANALYSIS_CONTRACT_REL
        q2_packet = self.package / compat.Q2_PACKET_REL
        analysis.parent.mkdir(parents=True)
        q2_packet.parent.mkdir(parents=True)
        analysis.write_text('{"version":"1.0"}\n', encoding="utf-8")
        q2_packet.write_text('{"rawSha256":"' + self.raw_sha + '"}\n', encoding="utf-8")
        authority = {
            "manifestVersion": "1.6.0", "approvedBy": "Owner", "authoritative": True,
            "ownerPromotionRequired": False, "actionable": False, "publishAuthorized": False,
            "phase3aOwnerPromotion": {
                "promotionId": "TEST-PROMOTION", "sourceManifestSha256": "A" * 64,
                "q2Lineage": {"quarter": "2026Q2", "closeoutReceiptPath": "closeout.json",
                              "closeoutReceiptSha256": "B" * 64},
            },
        }
        authority_path = self.package / compat.AUTHORITY_MANIFEST_REL
        runtime.atomic_write_json(authority_path, authority)
        self.policy = compat.CompatibilityPolicy(
            raw_sha256=self.raw_sha, rejected_revised_sha256="F" * 64,
            receipt_file_sha256=self.receipt_sha,
            integration_file_sha256=runtime._sha256_path(integration_path),
            integration_canonical_sha256=integration["canonical_sha256"],
            trigger_file_sha256=runtime._sha256_path(trigger_path),
            trigger_canonical_sha256=legacy["canonical_sha256"],
            authority_manifest_sha256=runtime._sha256_path(authority_path),
            authority_manifest_version="1.6.0", phase3a_source_manifest_sha256="A" * 64,
            q2_closeout_receipt_sha256="B" * 64, event_id=self.event_id,
            receipt_id=self.receipt_id, decision_id=decision["decision_id"],
        )

    def materialize(self):
        with mock.patch.object(runtime, "Q2_CONTRACT_RAW_SHA256", self.policy.raw_sha256), \
             mock.patch.object(runtime, "Q2_AUTHORITY_MANIFEST_SHA256", self.policy.authority_manifest_sha256):
            return compat._materialize(self.package, self.historical, self.output, self.policy)

    def test_valid_materialization_and_current_candidate_workflow_validation(self):
        result = self.materialize()
        self.assertEqual(result["status"], "PASS")
        previous = os.environ.get(runtime.GOVERNED_EVIDENCE_ROOT_ENV)
        try:
            os.environ[runtime.GOVERNED_EVIDENCE_ROOT_ENV] = str(self.output)
            with mock.patch.object(runtime, "Q2_CONTRACT_RAW_SHA256", self.policy.raw_sha256), \
                 mock.patch.object(runtime, "Q2_AUTHORITY_MANIFEST_SHA256", self.policy.authority_manifest_sha256):
                trigger = runtime.require_valid_trigger(self.package)
            self.assertEqual(trigger["candidate_workflow"]["historical_compatibility"]["factsAdded"], 0)
        finally:
            if previous is None:
                os.environ.pop(runtime.GOVERNED_EVIDENCE_ROOT_ENV, None)
            else:
                os.environ[runtime.GOVERNED_EVIDENCE_ROOT_ENV] = previous

    def test_raw_tamper_rejected(self):
        raw = self.historical / "official_ir_evidence/q2/raw" / f"{self.receipt_id}.bin"
        raw.write_bytes(self.raw_bytes + b"tamper")
        with self.assertRaisesRegex(compat.Q2CompatibilityError, "HISTORICAL_RAW_HASH_INVALID"):
            self.materialize()

    def test_receipt_tamper_rejected(self):
        receipt = self.historical / "official_ir_evidence/q2/receipts" / f"{self.receipt_id}.json"
        receipt.write_bytes(receipt.read_bytes() + b" ")
        with self.assertRaisesRegex(compat.Q2CompatibilityError, "HISTORICAL_RECEIPT_HASH_INVALID"):
            self.materialize()

    def test_revised_pdf_is_explicitly_rejected(self):
        raw = self.historical / "official_ir_evidence/q2/raw" / f"{self.receipt_id}.bin"
        revised = b"revised-live-results"
        raw.write_bytes(revised)
        self.policy = replace(self.policy, rejected_revised_sha256=governance.sha256_bytes(revised))
        with self.assertRaisesRegex(compat.Q2CompatibilityError, "REVISED_Q2_RESULTS_NOT_CONTRACT_AUTHORITY"):
            self.materialize()

    def test_ambiguous_lineage_rejected(self):
        path = self.historical / compat.INTEGRATION_REL
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["validated_event_evidence"].append(dict(self.event))
        payload = runtime._with_hash({key: value for key, value in payload.items() if key != "canonical_sha256"})
        runtime.atomic_write_json(path, payload)
        self.policy = replace(self.policy, integration_file_sha256=runtime._sha256_path(path),
                              integration_canonical_sha256=payload["canonical_sha256"])
        with self.assertRaisesRegex(compat.Q2CompatibilityError, "HISTORICAL_LINEAGE_AMBIGUOUS"):
            self.materialize()

    def test_exact_q2_analysis_authority_binding(self):
        self.materialize()
        trigger = json.loads((self.output / compat.TRIGGER_REL).read_text(encoding="utf-8"))
        lineage = trigger["candidate_workflow"]["historical_compatibility"]
        self.assertEqual(lineage["originalRawSha256"], self.raw_sha)
        self.assertEqual(lineage["currentAuthority"]["phase3aSourceManifestSha256"], "A" * 64)
        self.assertEqual(lineage["q2CloseoutLineage"]["receiptSha256"], "B" * 64)
        self.assertRegex(lineage["analysisContractLineage"]["contractSha256"], r"^[A-F0-9]{64}$")


if __name__ == "__main__":
    unittest.main()
