from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import warroom_report_governance as governance  # noqa: E402


HASH = "A" * 64
OTHER_HASH = "B" * 64
NOW = "2026-08-09T00:00:00Z"


def evidence(event_type: str = "MONTHLY_REVENUE", **overrides: object) -> dict:
    value = {
        "event_id": "EV-001", "event_type": event_type,
        "event_status": "MATERIAL_EVENT_CONFIRMED", "occurred_at_utc": NOW,
        "published_at_utc": NOW, "received_at_utc": NOW, "data_cutoff": "2026-07-27",
        "source_id": "SOURCE-001", "source_type": "AUTHORITY_DATASET",
        "source_locator": "data/authority.csv#2026-07-27", "source_tier": 1,
        "source_hash": HASH, "evidence_ids": ["E-001"], "claim_summary": "Validated fact.",
        "affected_kpis": ["revenue"], "materiality": "MATERIAL", "novelty": "NEW",
        "verification_status": "VERIFIED", "counter_evidence_ids": [],
        "missing_evidence": [], "source_conflicts": [], "actionable": False,
    }
    value.update(overrides)
    return value


def approved_policy(**overrides: object) -> dict:
    value = {
        "threshold_policy_id": "POLICY-001", "metric": "price_change", "operator": ">=",
        "threshold": "OWNER_DEFINED", "window": "OWNER_DEFINED", "minimum_observations": 1,
        "effective_from": "2026-08-01", "effective_to": None, "version": "1",
        "owner_approved": True, "approval_reference": "OWNER_APPROVED_THRESHOLD_POLICY", "status": "APPROVED",
    }
    value.update(overrides)
    return value


class ReportGovernanceG1Tests(unittest.TestCase):
    def test_event_evidence_accepts_non_url_authority_locator(self) -> None:
        item = evidence()
        item.pop("source_url", None)
        self.assertEqual(governance.validate_event_evidence(item)["source_locator"], "data/authority.csv#2026-07-27")

    def test_event_evidence_missing_identity_hash_or_verification_fails_closed(self) -> None:
        for field, value in (("source_id", ""), ("source_hash", "not-a-hash"), ("verification_status", "UNVERIFIED")):
            with self.subTest(field=field), self.assertRaises(governance.GovernanceValidationError):
                governance.validate_event_evidence(evidence(**{field: value}))

    def test_no_material_change_never_generates_or_archives(self) -> None:
        decision = governance.evaluate_report_trigger(report_key="P1008_DAILY_20260809", revision=1, event_evidence=[], evaluated_at_utc=NOW)
        self.assertEqual(decision["decision"], "NO_MATERIAL_CHANGE")
        self.assertFalse(decision["report_generated"])
        self.assertFalse(decision["archive_report_created"])
        self.assertFalse(decision["library_appended"])
        self.assertFalse(decision["actionable"])

    def test_approved_event_can_trigger_but_weekly_and_unknown_cannot(self) -> None:
        good = governance.evaluate_report_trigger(report_key="P1008_MONTHLY_REVENUE_202607", revision=1, event_evidence=[evidence()], evaluated_at_utc=NOW)
        self.assertTrue(good["report_trigger_valid"])
        for event_type in ("WEEKLY_SUMMARY", "UNKNOWN_EVENT"):
            with self.subTest(event_type=event_type):
                denied = governance.evaluate_report_trigger(report_key="P1008_DAILY_20260809", revision=1, event_evidence=[evidence(event_type)], evaluated_at_utc=NOW)
                self.assertEqual(denied["decision"], "TRIGGER_REJECTED_UNAPPROVED_EVENT_TYPE")
                self.assertFalse(denied["report_trigger_valid"])

    def test_anomaly_requires_explicit_owner_approved_policy(self) -> None:
        item = evidence("APPROVED_PRICE_VOLUME_POSITIONING_ANOMALY")
        missing = governance.evaluate_report_trigger(report_key="P1008_ANOMALY_20260809", revision=1, event_evidence=[item], evaluated_at_utc=NOW)
        self.assertEqual(missing["decision"], "TRIGGER_REJECTED_MISSING_THRESHOLD_POLICY")
        unapproved = governance.evaluate_report_trigger(report_key="P1008_ANOMALY_20260809", revision=1, event_evidence=[item], evaluated_at_utc=NOW, threshold_policies=[approved_policy(owner_approved=False, approval_reference=None, status="DRAFT")])
        self.assertFalse(unapproved["report_trigger_valid"])
        approved = governance.evaluate_report_trigger(report_key="P1008_ANOMALY_20260809", revision=1, event_evidence=[item], evaluated_at_utc=NOW, threshold_policies=[approved_policy()])
        self.assertTrue(approved["report_trigger_valid"])

    def test_core_view_eligibility_never_changes_without_owner(self) -> None:
        for reason in ({"official_confirmation": True}, {"independent_high_quality_source_count": 2}, {"financial_reflection": True}, {"thesis_invalidation": True}):
            with self.subTest(reason=reason):
                kwargs = {"official_confirmation": False, "independent_high_quality_source_count": 0, "financial_reflection": False, "thesis_invalidation": False}
                kwargs.update(reason)
                decision = governance.evaluate_core_view_change(supporting_evidence_ids=["E-001"], counter_evidence_ids=[], owner_approved=False, owner_approval_reference=None, prior_core_view_hash=HASH, proposed_core_view_hash=OTHER_HASH, **kwargs)
                self.assertTrue(decision["eligibility"])
                self.assertFalse(decision["core_view_changed"])

    def test_core_view_owner_approval_is_mandatory_and_tier_five_is_not_high_quality(self) -> None:
        accepted = governance.evaluate_core_view_change(supporting_evidence_ids=["E-001"], counter_evidence_ids=[], official_confirmation=True, independent_high_quality_source_count=0, financial_reflection=False, thesis_invalidation=False, owner_approved=True, owner_approval_reference="OWNER_APPROVE_CORE_VIEW", prior_core_view_hash=HASH, proposed_core_view_hash=OTHER_HASH)
        self.assertTrue(accepted["core_view_changed"])
        tier_five_only = governance.evaluate_core_view_change(supporting_evidence_ids=["E-005"], counter_evidence_ids=[], official_confirmation=False, independent_high_quality_source_count=0, financial_reflection=False, thesis_invalidation=False, owner_approved=False, owner_approval_reference=None, prior_core_view_hash=HASH, proposed_core_view_hash=OTHER_HASH)
        self.assertFalse(tier_five_only["eligibility"])
        with self.assertRaises(governance.GovernanceValidationError):
            governance.evaluate_core_view_change(supporting_evidence_ids=[], counter_evidence_ids=[], official_confirmation=True, independent_high_quality_source_count=0, financial_reflection=False, thesis_invalidation=False, owner_approved=True, owner_approval_reference=None, prior_core_view_hash=HASH, proposed_core_view_hash=OTHER_HASH)

    def test_publication_is_default_denied_and_never_externally_published(self) -> None:
        denied = governance.evaluate_publication(report_key="P1008_MONTHLY_REVENUE_202607", revision=1, report_hash=HASH, audience="PUBLIC", fact_check_status="PASS", owner_approved=False, owner_approval_reference=None)
        self.assertEqual(denied["publication_status"], "DENIED_BY_DEFAULT")
        self.assertFalse(denied["publication_ready"])
        invalid = governance.evaluate_publication(report_key="P1008_MONTHLY_REVENUE_202607", revision=1, report_hash=HASH, audience="PUBLIC", fact_check_status="FAIL", owner_approved=True, owner_approval_reference="OWNER_APPROVE_PUBLIC")
        self.assertFalse(invalid["publication_ready"])
        ready = governance.evaluate_publication(report_key="P1008_MONTHLY_REVENUE_202607", revision=1, report_hash=HASH, audience="PUBLIC", fact_check_status="PASS", owner_approved=True, owner_approval_reference="OWNER_APPROVE_PUBLIC")
        self.assertTrue(ready["publication_ready"])
        self.assertFalse(ready["published_externally"])

    def test_model_provenance_optional_metadata_and_no_cost_estimates(self) -> None:
        provenance = {"model_provenance_id": "MP-001", "model_surface": "HOST", "model_identifier": "unchanged", "input_receipt_ids": [], "output_artifact_hash": HASH, "started_at_utc": NOW, "completed_at_utc": NOW, "status": "NOT_USED", "model_change_did_not_modify_runtime_configuration": True, "project_runtime_model_allowlist_unchanged": True, "actionable": False}
        self.assertEqual(governance.validate_model_provenance(provenance)["status"], "NOT_USED")
        with self.assertRaises(governance.GovernanceValidationError):
            governance.validate_model_provenance({**provenance, "estimated_cost": 0})

    def test_private_library_eligibility_is_represented_but_never_appended(self) -> None:
        eligible = governance.evaluate_private_library_eligibility(material_event_confirmed=True, report_trigger_valid=True, report_validation_pass=True, actionable=False)
        self.assertTrue(eligible["private_library_eligible"])
        self.assertFalse(eligible["library_appended"])
        self.assertFalse(governance.evaluate_private_library_eligibility(material_event_confirmed=True, report_trigger_valid=True, report_validation_pass=True, actionable=True)["private_library_eligible"])

    def test_receipt_binds_same_report_key_revision_and_is_canonical(self) -> None:
        trigger = governance.evaluate_report_trigger(report_key="P1008_MONTHLY_REVENUE_202607", revision=2, event_evidence=[evidence()], evaluated_at_utc=NOW)
        trigger["decision_id"] = "TRIGGER-001"
        core = governance.evaluate_core_view_change(supporting_evidence_ids=[], counter_evidence_ids=[], official_confirmation=False, independent_high_quality_source_count=0, financial_reflection=False, thesis_invalidation=False, owner_approved=False, owner_approval_reference=None, prior_core_view_hash=HASH, proposed_core_view_hash=OTHER_HASH)
        core["decision_id"] = "CORE-001"
        publication = governance.evaluate_publication(report_key="P1008_MONTHLY_REVENUE_202607", revision=2, report_hash=HASH, audience="PRIVATE", fact_check_status="PASS", owner_approved=False, owner_approval_reference=None)
        publication["decision_id"] = "PUBLICATION-001"
        receipt = governance.build_report_decision_receipt(receipt_id="RECEIPT-001", report_key="P1008_MONTHLY_REVENUE_202607", revision=2, authority_cutoffs=["2026-07-27"], event_evidence_ids=["E-001"], report_trigger_decision=trigger, core_view_change_decision=core, publication_decision=publication, model_provenances=[], report_validation_pass=True, report_artifact_hashes=[HASH], created_at_utc=NOW)
        self.assertTrue(receipt["private_library_eligible"])
        self.assertFalse(receipt["library_appended"])
        self.assertRegex(receipt["canonical_sha256"], r"^[A-F0-9]{64}$")
        with self.assertRaises(governance.GovernanceValidationError):
            governance.build_report_decision_receipt(receipt_id="RECEIPT-002", report_key="P1008_OTHER_202607", revision=2, authority_cutoffs=[], event_evidence_ids=[], report_trigger_decision=trigger, core_view_change_decision=core, publication_decision=publication, model_provenances=[], report_validation_pass=True, report_artifact_hashes=[HASH], created_at_utc=NOW)

    def test_contract_manifest_and_schemas_are_parseable(self) -> None:
        root = ROOT / "contracts/p1008_report_governance/v1.0"
        manifest = json.loads((root / "contract.manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("WEEKLY_SUMMARY", manifest["supportedEventTypes"])
        lines = []
        for artifact in manifest["artifacts"]:
            path = root / artifact["path"]
            self.assertEqual(path.stat().st_size, artifact["sizeBytes"])
            self.assertEqual(governance.sha256_bytes(path.read_bytes()), artifact["sha256"])
            lines.append(f"{artifact['path']}|{artifact['sha256']}")
        self.assertEqual(governance.sha256_bytes("\n".join(sorted(lines, key=str.casefold)).encode("utf-8")), manifest["rootHash"])
        for path in root.glob("schemas/*.json"):
            with self.subTest(path=path.name):
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["$schema"], "https://json-schema.org/draft/2020-12/schema")


if __name__ == "__main__":
    unittest.main()
