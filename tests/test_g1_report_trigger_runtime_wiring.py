from __future__ import annotations

import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import p1008_app_server as app_server  # noqa: E402
import warroom_report_governance as governance  # noqa: E402
import warroom_report_trigger_runtime as runtime  # noqa: E402


NOW = "2026-08-12T08:00:00Z"
HASH = "A" * 64


def evidence(**changes):
    item = {
        "event_id": "FY26-Q2-RESULTS",
        "event_type": "QUARTERLY_EARNINGS",
        "event_status": "MATERIAL_EVENT_CONFIRMED",
        "occurred_at_utc": "2026-08-12T06:00:00Z",
        "published_at_utc": "2026-08-12T06:00:00Z",
        "received_at_utc": "2026-08-12T06:05:00Z",
        "data_cutoff": "2026-06-30",
        "source_id": "HON_HAI_IR_Q2",
        "source_type": "COMPANY_FILING",
        "source_class": "AUTHORITY",
        "source_locator": "official-ir/FY2026-Q2.pdf",
        "source_url": "https://www.honhai.com/en-us/investor-relations",
        "source_tier": "OFFICIAL",
        "source_hash": HASH,
        "originating_chain_id": "HON_HAI_IR",
        "evidence_ids": ["E-FY26-Q2-OFFICIAL"],
        "claim_summary": "Hon Hai FY2026 Q2 financial results",
        "affected_kpis": ["revenue", "margin", "eps"],
        "materiality": "HIGH",
        "novelty": "NEW",
        "evidence_status": "CONFIRMED",
        "validation_status": "OFFICIAL_VERIFIED",
        "confidence": 1.0,
        "quality_metadata": {"official": True},
        "provenance": {"adapter": "ResearchContentOrchestrator"},
        "canonical_event_id": "P1008_FY2026_Q2_EARNINGS",
        "verification_status": "OFFICIAL_VERIFIED",
        "counter_evidence_ids": [],
        "missing_evidence": [],
        "source_conflicts": [],
        "actionable": False,
    }
    item.update(changes)
    return item


def integration(items, *, report_key="P1008_FY2026_Q2_EARNINGS", revision=1):
    decision = governance.evaluate_report_trigger(
        report_key=report_key, revision=revision, event_evidence=items,
        evaluated_at_utc=NOW,
    )
    return runtime.build_integration_artifact({
        "record_type": runtime.INTEGRATION_RECORD_TYPE,
        "report_key": report_key,
        "revision": revision,
        "evaluated_at_utc": NOW,
        "validated_event_evidence": items,
        "report_trigger_decision": decision,
        "report_generated": False,
        "actionable": False,
    })


class RuntimeRootMixin:
    def setUp(self):
        scratch = ROOT / "runtime" / "g1_trigger_test_scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        self.root = scratch / uuid.uuid4().hex
        self.root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write_integration(self, items, **kwargs):
        payload = integration(items, **kwargs)
        runtime.persist_integration_result(
            self.root, {key: value for key, value in payload.items() if key != "canonical_sha256"}
        )
        return payload


class RuntimeTriggerTests(RuntimeRootMixin, unittest.TestCase):

    def test_no_evidence_is_no_material_change_and_analysis_disabled(self):
        receipt = runtime.evaluate_and_persist(self.root, evaluated_at_utc=NOW)
        self.assertEqual(receipt["decision"], "NO_MATERIAL_CHANGE")
        self.assertFalse(runtime.launcher_status(self.root)["analysisEligible"])
        with self.assertRaisesRegex(runtime.RuntimeTriggerError, "REPORT_TRIGGER_REQUIRED"):
            runtime.require_valid_trigger(self.root)

    def test_discovery_and_one_media_do_not_trigger(self):
        discovery = evidence(
            source_id="ANYSEARCH-1", source_class="DISCOVERY", source_type="OTHER",
            source_tier="UNVERIFIED", event_status="DISCOVERY_UNVERIFIED",
            evidence_status="DISCOVERED", source_hash="B" * 64,
            originating_chain_id="ANYSEARCH", evidence_ids=["D-1"],
        )
        self.write_integration([discovery])
        receipt = runtime.evaluate_and_persist(self.root)
        self.assertFalse(receipt["report_trigger_valid"])
        self.assertEqual(receipt["cross_validation"]["evidence_state"], "WATCH")

        media = evidence(
            source_id="MEDIA-1", source_class="SECONDARY", source_type="NEWS_MEDIA",
            source_tier="MEDIA", source_hash="C" * 64,
            originating_chain_id="CHAIN-1", evidence_ids=["M-1"],
        )
        self.write_integration([media])
        receipt = runtime.evaluate_and_persist(self.root)
        self.assertFalse(receipt["report_trigger_valid"])
        self.assertEqual(receipt["cross_validation"]["evidence_state"], "REVIEW_REQUIRED")

    def test_official_q2_triggers_but_does_not_generate(self):
        self.write_integration([evidence()])
        receipt = runtime.evaluate_and_persist(self.root)
        self.assertEqual(receipt["decision"], "TRIGGERED_INTERNAL_REPORT")
        self.assertEqual(receipt["canonical_event_id"], "P1008_FY2026_Q2_EARNINGS")
        self.assertTrue(runtime.launcher_status(self.root)["analysisEligible"])
        self.assertFalse(runtime.launcher_status(self.root)["reportEligible"])
        self.assertFalse(receipt["report_generated"])
        self.assertEqual(receipt["publication"], "DENIED_BY_DEFAULT_OWNER_APPROVAL_REQUIRED")

    def test_two_independent_media_match_frozen_policy(self):
        first = evidence(
            source_id="MEDIA-1", source_class="SECONDARY", source_type="NEWS_MEDIA",
            source_tier="MEDIA", source_hash="C" * 64,
            originating_chain_id="CHAIN-1", evidence_ids=["M-1"],
        )
        second = evidence(
            source_id="MEDIA-2", source_class="SECONDARY", source_type="NEWS_MEDIA",
            source_tier="MEDIA", source_hash="D" * 64,
            originating_chain_id="CHAIN-2", evidence_ids=["M-2"],
        )
        self.write_integration([first, second])
        receipt = runtime.evaluate_and_persist(self.root)
        self.assertEqual(receipt["cross_validation"]["evidence_state"], "CROSS_VALIDATED")
        self.assertTrue(receipt["report_trigger_valid"])

    def test_conflict_unsupported_multiple_malformed_and_actionable_fail_closed(self):
        conflict = evidence(
            source_id="MEDIA-1", source_class="SECONDARY", source_type="NEWS_MEDIA",
            source_tier="MEDIA", source_hash="C" * 64,
            originating_chain_id="CHAIN-1", evidence_ids=["M-1"],
            claim_summary="Conflicting account",
        )
        self.write_integration([evidence(), conflict])
        receipt = runtime.evaluate_and_persist(self.root)
        self.assertFalse(receipt["report_trigger_valid"])
        self.assertTrue(receipt["cross_validation"]["conflict_detected"])

        unsupported = evidence(event_type="UNAPPROVED_EVENT")
        self.write_integration([unsupported])
        self.assertEqual(runtime.evaluate_and_persist(self.root)["decision"], "TRIGGER_REJECTED_UNAPPROVED_EVENT_TYPE")

        self.write_integration([
            evidence(),
            evidence(event_type="EARNINGS_CALL", source_id="CALL", source_hash="B" * 64),
        ])
        with self.assertRaises(governance.GovernanceValidationError):
            runtime.evaluate_and_persist(self.root)
        with self.assertRaises(governance.GovernanceValidationError):
            integration([evidence(source_hash="bad")])
        with self.assertRaises(governance.GovernanceValidationError):
            integration([evidence(actionable=True)])

    def test_dedupe_and_material_revision_semantics(self):
        first = evidence()
        self.write_integration([first, dict(first)])
        one = runtime.evaluate_and_persist(self.root)
        self.assertEqual(one["revision"], 1)
        self.assertEqual(len(one["event_evidence_hashes"]), 1)

        supplemental = evidence(
            source_id="CALL-TRANSCRIPT", source_hash="E" * 64,
            originating_chain_id="HON_HAI_IR", evidence_ids=["E-CALL"],
        )
        self.write_integration([first, supplemental])
        same = runtime.evaluate_and_persist(self.root)
        self.assertEqual(same["revision"], 1)
        self.assertEqual(same["report_key"], one["report_key"])

        material = evidence(
            source_id="CALL-UPDATE", source_hash="F" * 64,
            originating_chain_id="HON_HAI_IR", evidence_ids=["E-CALL-MATERIAL"],
            claim_summary="Hon Hai FY2026 Q2 results plus material new outlook",
        )
        self.write_integration([first, material])
        revised = runtime.evaluate_and_persist(self.root)
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(revised["previous_decision_id"], same["decision_id"])

    def test_tampered_integration_and_receipt_are_rejected(self):
        payload = self.write_integration([evidence()])
        runtime.evaluate_and_persist(self.root)
        payload["report_key"] = "P1008_TAMPERED"
        runtime.atomic_write_json(self.root / runtime.INTEGRATION_REL, payload)
        with self.assertRaisesRegex(runtime.RuntimeTriggerError, "HASH_INVALID"):
            runtime.require_valid_trigger(self.root)


class ServerGateTests(RuntimeRootMixin, unittest.TestCase):
    def manager(self):
        manager = app_server.P1008JobManager(self.root)
        manager.state = manager._initial_state()
        manager.state["logPath"] = "logs/test.log"
        manager._preflight = lambda: {}  # type: ignore[method-assign]
        manager._bootstrap_report_library_step = lambda: ""  # type: ignore[method-assign]
        manager._refresh = lambda *args, **kwargs: None  # type: ignore[method-assign]
        manager._latest_phaseb1_status = lambda: {"runId": "RUN-1", "outputPath": "runtime/report_production/RUN-1"}  # type: ignore[method-assign]
        return manager

    def test_analysis_without_or_with_invalid_trigger_is_blocked(self):
        manager = self.manager()
        manager._run_bat_step = lambda *args, **kwargs: self.fail("BAT must not run")  # type: ignore[method-assign]
        manager._run_job_inner("analysis-candidate")
        self.assertEqual(manager.state["componentStatus"]["phaseB1"]["code"], "REPORT_TRIGGER_REQUIRED")

        payload = self.write_integration([evidence()])
        runtime.evaluate_and_persist(self.root)
        payload["canonical_sha256"] = "0" * 64
        runtime.atomic_write_json(self.root / runtime.INTEGRATION_REL, payload)
        manager = self.manager()
        manager._run_bat_step = lambda *args, **kwargs: self.fail("BAT must not run")  # type: ignore[method-assign]
        manager._run_job_inner("analysis-candidate")
        self.assertEqual(manager.state["componentStatus"]["phaseB1"]["code"], "REPORT_TRIGGER_REQUIRED")

    def test_valid_analysis_allowed_and_report_requires_same_lineage(self):
        self.write_integration([evidence()])
        trigger = runtime.evaluate_and_persist(self.root)
        calls = []
        manager = self.manager()
        manager._run_bat_step = lambda *args, **kwargs: calls.append(args[0]) or 0  # type: ignore[method-assign]
        manager._run_job_inner("analysis-candidate")
        self.assertEqual(calls, ["analysis-candidate"])

        manager = self.manager()
        manager._run_bat_step = lambda *args, **kwargs: self.fail("BAT must not run")  # type: ignore[method-assign]
        manager._run_job_inner("report-candidate")
        self.assertEqual(manager.state["componentStatus"]["phaseB1"]["code"], "ANALYSIS_CANDIDATE_REQUIRED")

        run = self.root / "runtime/report_production/RUN-1"
        run.mkdir(parents=True)
        (run / "run_manifest.json").write_text(json.dumps({
            "runId": "RUN-1", "state": "ANALYSIS_CANDIDATE_READY",
            "generatedAtUtc": NOW, "triggerLineage": {**runtime.trigger_lineage(trigger), "revision": 99},
        }), encoding="utf-8")
        manager = self.manager()
        manager._run_bat_step = lambda *args, **kwargs: self.fail("BAT must not run")  # type: ignore[method-assign]
        manager._run_job_inner("report-candidate")
        self.assertEqual(manager.state["componentStatus"]["phaseB1"]["code"], "ANALYSIS_CANDIDATE_REQUIRED")

        (run / "run_manifest.json").write_text(json.dumps({
            "runId": "RUN-1", "state": "ANALYSIS_CANDIDATE_READY",
            "generatedAtUtc": NOW, "triggerLineage": runtime.trigger_lineage(trigger),
        }), encoding="utf-8")
        calls = []
        manager = self.manager()
        manager._run_bat_step = lambda *args, **kwargs: calls.append(args[0]) or 0  # type: ignore[method-assign]
        manager._run_job_inner("report-candidate")
        self.assertEqual(calls, ["report-candidate"])


class LauncherWiringTests(unittest.TestCase):
    def test_ui_uses_server_trigger_state_for_both_candidate_buttons(self):
        launcher = (ROOT / "launcher.html").read_text(encoding="utf-8-sig")
        self.assertIn('id="report-trigger-panel"', launcher)
        self.assertIn("trigger.analysisEligible !== true", launcher)
        self.assertIn("trigger.reportEligible !== true", launcher)
        self.assertIn("評估戰報 Trigger", launcher)

    def test_server_exposes_trigger_state_and_never_auto_runs_candidates(self):
        server = (ROOT / "tools/p1008_app_server.py").read_text(encoding="utf-8")
        self.assertIn('state["reportTrigger"] = report_trigger_runtime.launcher_status', server)
        default_block = server.split('if job_type == "default" and not component_failures:', 1)[0]
        self.assertNotIn("P1008_BUILD_ANALYSIS.bat", default_block)
        self.assertNotIn("P1008_BUILD_REPORT.bat", default_block)


if __name__ == "__main__":
    unittest.main()
