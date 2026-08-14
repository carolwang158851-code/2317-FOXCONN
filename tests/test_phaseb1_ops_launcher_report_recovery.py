from __future__ import annotations

import hashlib
import http.server
import json
import shutil
import sys
import threading
import urllib.request
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TOOLS = PACKAGE_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import p1008_app_server as app_server  # noqa: E402
import p1008_open_warroom as open_warroom  # noqa: E402
import warroom_periodic_report_v1 as periodic_report  # noqa: E402
import warroom_rolling_brief as rolling_brief  # noqa: E402
import warroom_report_governance as governance  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class _Response:
    def __init__(self, content_type: str, payload: dict | None = None) -> None:
        self.status = 200
        self.headers = {"Content-Type": content_type}
        self._body = json.dumps(payload or {}).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self._body


class _PipelineManager(app_server.P1008JobManager):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.calls: list[str] = []
        self.state.update(
            status="RUNNING",
            steps=[],
            errors=[],
            warnings=[],
            componentStatus={},
            logPath="logs/test.log",
        )

    def _persist_locked(self) -> None:
        return

    def _append_log(self, message: str) -> None:
        return

    def _preflight(self):
        self.calls.append("preflight")
        return app_server.formal_csv_hashes(self.package_root)

    def review_package(self, date_str=None):
        return {"generatedFiles": [], "candidateDate": "2026-07-27"}

    def _run_bat_step(self, step_id, label, bat_path, args, timeout_seconds):
        self.calls.append(step_id)
        self._set_step(step_id, label, "SUCCEEDED", exitCode=0)
        if step_id == "daily-price-authority":
            path = self.package_root / app_server.DAILY_PRICE_STATUS_REL
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "status": "NO_NEW_DAILY_PRICE",
                        "launcher_status": "NO_NEW_DATA",
                        "last_success_date": "2026-07-27",
                    }
                ),
                encoding="utf-8",
            )
        if step_id == "market-activity":
            path = self.package_root / app_server.MARKET_ACTIVITY_STATUS_REL
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "status": "NO_NEW_MARKET_ACTIVITY",
                        "launcher_status": "NO_NEW_DATA",
                        "last_success_date": "2026-07-27",
                        "receipt_paths": [str(self.package_root / "runtime/test/2026-07.receipt.json")],
                    }
                ),
                encoding="utf-8",
            )
        if step_id == "authority-freshness":
            path = self.package_root / app_server.FRESHNESS_STATUS_REL
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "freshness_scope": "FORMAL_AUTHORITY",
                        "formal_authority_current": True,
                        "owner_publish_required": False,
                        "twse_latest_validated_trading_date": "2026-07-27",
                    }
                ),
                encoding="utf-8",
            )
        return 0

    def _run_news_scan_step(self):
        self.calls.append("news-scan")
        self._set_step("news-scan", "News", "SUCCEEDED", exitCode=0)

    def _run_python_step(self, step_id, label, args, timeout_seconds, *, allow_after_errors=False):
        self.calls.append(step_id)
        if step_id == "report":
            periodic_report.update_report_manifest(
                self.package_root,
                {
                    "id": "P1008_DAILY_20260727",
                    "date": "2026-07-27",
                    "period": "daily",
                    "title": "Owner manual archive",
                    "actionable": False,
                },
                "2026-08-02T00:00:00Z",
            )
        self._set_step(step_id, label, "SUCCEEDED", exitCode=0)

    def _refresh(self, before, **_kwargs):
        self.calls.append("refresh")

    def _market_activity_last_date(self):
        return "2026-07-27"


class PhaseB1OpsLauncherReportRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = PACKAGE_ROOT / "runtime" / "phaseb1_ops_test_scratch" / uuid.uuid4().hex
        (self.root / "data").mkdir(parents=True)
        self.addCleanup(
            lambda: shutil.rmtree(self.root, ignore_errors=True)
            if self.root.exists()
            else None
        )
        (self.root / "data/CSV_AUTHORITY_MANIFEST.json").write_text("{}\n", encoding="utf-8")
        (self.root / "data/2317_daily_price.csv").write_text(
            "Date,Close,QuarterKey,BVPS_ref,PB_daily,DataSupportLevel,Status\n"
            "2026-07-27,253.0,2026Q1,127.12,1.990,OFFICIAL_TWSE_A1,OK\n",
            encoding="utf-8",
        )
        (self.root / "data/2317_daily_market_activity.csv").write_text(
            "date,stock_id,trade_volume,trade_value,transaction_count,source_url,source_month\n"
            "2026-07-27,2317,100,25300,10,https://www.twse.com.tw/source,2026-07\n",
            encoding="utf-8",
        )

    def _write_matching_manifests(self, reports=None) -> tuple[bytes, bytes]:
        records = reports or []
        runtime_payload = {
            "schemaVersion": "2.0",
            "toolVersion": "P1008_REPORT_LIFECYCLE_v1",
            "latest": {},
            "reports": records,
            "actionable": False,
        }
        report_payload = {
            "schemaVersion": "1.0",
            "latest": {"daily": None, "weekly": None, "monthly": None},
            "reports": records,
            "actionable": False,
        }
        runtime = self.root / rolling_brief.RUNTIME_MANIFEST_REL
        report = self.root / rolling_brief.REPORT_MANIFEST_REL
        runtime.parent.mkdir(parents=True, exist_ok=True)
        report.parent.mkdir(parents=True, exist_ok=True)
        runtime.write_text(json.dumps(runtime_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return runtime.read_bytes(), report.read_bytes()

    def _valid_trigger_handoff(self, *, report_date: str = "2026-07-27") -> dict:
        now = "2026-08-09T00:00:00Z"
        report_key = "P1008_MONTHLY_REVENUE_202607"
        evidence = {
            "event_id": "EV-001", "event_type": "MONTHLY_REVENUE",
            "event_status": "MATERIAL_EVENT_CONFIRMED", "occurred_at_utc": now,
            "published_at_utc": now, "received_at_utc": now, "data_cutoff": "2026-07-27",
            "source_id": "SOURCE-001", "source_type": "AUTHORITY_DATASET",
            "source_class": "AUTHORITY", "source_locator": "data/authority.csv#2026-07-27",
            "source_tier": "OFFICIAL", "source_hash": "A" * 64,
            "evidence_ids": ["E-001"], "claim_summary": "Validated fact.",
            "affected_kpis": ["revenue"], "materiality": "MATERIAL", "novelty": "NEW",
            "evidence_status": "CONFIRMED", "validation_status": "VERIFIED", "confidence": 0.95,
            "quality_metadata": {"review": "deterministic"}, "provenance": {"collector": "test"},
            "originating_chain_id": "CHAIN-001", "canonical_event_id": "MONTHLY_REVENUE_202607",
            "verification_status": "VERIFIED", "counter_evidence_ids": [], "missing_evidence": [],
            "source_conflicts": [], "actionable": False,
        }
        trigger = governance.evaluate_report_trigger(
            report_key=report_key, revision=1, event_evidence=[evidence], evaluated_at_utc=now
        )
        core = governance.evaluate_core_view_change(
            supporting_evidence_ids=[], counter_evidence_ids=[], official_confirmation=False,
            independent_high_quality_source_count=0, financial_reflection=False,
            thesis_invalidation=False, owner_approved=False, owner_approval_reference=None,
            prior_core_view_hash="B" * 64, proposed_core_view_hash="C" * 64,
        )
        publication = governance.evaluate_publication(
            report_key=report_key, revision=1, report_hash="D" * 64, audience="PRIVATE",
            fact_check_status="PASS", owner_approved=False, owner_approval_reference=None,
        )
        receipt = governance.build_report_decision_receipt(
            receipt_id="RECEIPT-001", report_key=report_key, revision=1,
            authority_cutoffs=["2026-07-27"], event_evidence_ids=["E-001"],
            report_trigger_decision=trigger, core_view_change_decision=core,
            publication_decision=publication, model_provenances=[], report_validation_pass=True,
            report_artifact_hashes=["E" * 64], created_at_utc=now,
        )
        return {
            "report_key": report_key, "revision": 1, "report_date": report_date,
            "event_type": "MONTHLY_REVENUE", "event_evidence": [evidence],
            "threshold_policies": [], "report_trigger_decision": trigger,
            "core_view_change_decision": core, "publication_decision": publication,
            "report_decision_receipt": receipt,
        }

    def _write_trigger_handoff(self, payload: dict) -> Path:
        path = self.root / "runtime/governance/report_trigger_handoff.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def _launcher_gate(self, health: dict) -> dict:
        manager = app_server.P1008JobManager(self.root)
        state = {
            "status": "IDLE",
            "errors": [],
            "formalCsvModified": False,
            "latestReport": {"health": health},
        }
        review = {
            "status": "READY",
            "candidatePending": False,
            "pendingOwnerReview": {},
            "newsScan": {},
            "eventReview": {},
            "formalPublishBlocked": False,
        }
        return manager.launcher_gate_status(review, state)

    def test_tracked_production_ui_replaces_ignored_output_dependency(self) -> None:
        tracked = "ui/P1008_WARROOM_COMMAND_CENTER_v24.html"
        legacy_ignored = "output/ui-concepts/P1008_WARROOM_COMMAND_CENTER_v24.html"
        tracked_path = PACKAGE_ROOT / tracked
        self.assertTrue(tracked_path.is_file())
        source_receipt = json.loads(
            (
                PACKAGE_ROOT
                / "contracts/p1008_report_production/acceptance/v1.1/PHASE_B1_OPS_R2_TRACKED_UI_SOURCE_RECEIPT.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(source_receipt["trackedDestinationPath"], tracked)
        self.assertEqual(source_receipt["trackedDestinationSha256"], sha256(tracked_path))
        self.assertTrue(source_receipt["byteIdentityVerified"])
        for path in (
            PACKAGE_ROOT / "launcher.html",
            PACKAGE_ROOT / "reports.html",
            PACKAGE_ROOT / "report_viewer.html",
            PACKAGE_ROOT / "SOP_v4.html",
            PACKAGE_ROOT / "src/index_p1008_v7.source.html",
            PACKAGE_ROOT / "dist/index_p1008_v7.bundle.js",
            PACKAGE_ROOT / "tools/p1008_app_server.py",
        ):
            contents = path.read_text(encoding="utf-8")
            self.assertIn(tracked, contents, path)
            self.assertNotIn(legacy_ignored, contents, path)

    def test_preflight_requires_only_clean_clone_package_files(self) -> None:
        source = (PACKAGE_ROOT / "tools/p1008_app_server.py").read_text(encoding="utf-8")
        self.assertIn('"ui/P1008_WARROOM_COMMAND_CENTER_v24.html"', source)
        self.assertNotIn('"output/ui-concepts/P1008_WARROOM_COMMAND_CENTER_v24.html"', source)
        self.assertNotIn('"index_p1008_v7.html"', source)

    def test_tracked_ui_and_report_pages_are_served_over_local_http(self) -> None:
        manager = app_server.P1008JobManager(PACKAGE_ROOT)

        class Handler(app_server.P1008AppHandler):
            pass

        Handler.manager = manager
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            lambda *args, **kwargs: Handler(*args, directory=str(PACKAGE_ROOT), **kwargs),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(lambda: server.shutdown())
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            for rel in (
                "/ui/P1008_WARROOM_COMMAND_CENTER_v24.html",
                "/reports.html",
                "/report_viewer.html",
            ):
                with urllib.request.urlopen(base + rel, timeout=5) as response:
                    self.assertEqual(response.status, 200, rel)
        finally:
            server.shutdown()
            thread.join(timeout=5)

    def test_first_run_bootstrap_is_split_empty_and_idempotent(self) -> None:
        first = rolling_brief.bootstrap_report_library(
            self.root, now=datetime(2026, 8, 3, tzinfo=timezone.utc)
        )
        runtime = self.root / rolling_brief.RUNTIME_MANIFEST_REL
        report = self.root / rolling_brief.REPORT_MANIFEST_REL
        self.assertEqual(first["status"], "REPORT_LIBRARY_BOOTSTRAPPED_EMPTY")
        self.assertTrue(first["librarySubsetOfRuntime"])
        self.assertEqual(first["runtimeLifecycleCount"], 0)
        self.assertEqual(first["researchLibraryCount"], 0)
        self.assertEqual(first["runtimeOnlyCount"], 0)
        runtime_payload = json.loads(runtime.read_text(encoding="utf-8"))
        report_payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(runtime_payload["schemaVersion"], "2.0")
        self.assertEqual(report_payload["schemaVersion"], "1.0")
        self.assertEqual(runtime_payload["reports"], [])
        self.assertEqual(report_payload["reports"], [])
        self.assertFalse(report_payload["productionCsvModified"])
        self.assertFalse(runtime_payload["actionable"])
        self.assertFalse(report_payload["actionable"])
        runtime_before = runtime.read_bytes()
        report_before = report.read_bytes()
        second = rolling_brief.bootstrap_report_library(
            self.root, now=datetime(2026, 8, 4, tzinfo=timezone.utc)
        )
        self.assertEqual(second["status"], "REPORT_LIBRARY_EXISTING_HEALTHY")
        self.assertEqual(runtime.read_bytes(), runtime_before)
        self.assertEqual(report.read_bytes(), report_before)
        self.assertEqual(second["archiveReportCount"], 0)

    def test_one_missing_manifest_fails_closed_without_recreation(self) -> None:
        rolling_brief.bootstrap_report_library(self.root)
        report = self.root / rolling_brief.REPORT_MANIFEST_REL
        report.unlink()
        result = rolling_brief.bootstrap_report_library(self.root)
        self.assertEqual(result["status"], "FAIL_CLOSED")
        self.assertEqual(result["code"], "REPORT_LIBRARY_PARTIAL_MANIFEST_LOSS")
        self.assertFalse(report.exists())

    def test_invalid_manifest_fails_closed_without_recreation(self) -> None:
        rolling_brief.bootstrap_report_library(self.root)
        runtime = self.root / rolling_brief.RUNTIME_MANIFEST_REL
        runtime.write_text("not-json\n", encoding="utf-8")
        result = rolling_brief.bootstrap_report_library(self.root)
        self.assertEqual(result["status"], "FAIL_CLOSED")
        self.assertEqual(result["code"], "REPORT_LIBRARY_MANIFEST_INVALID")
        self.assertEqual(runtime.read_text(encoding="utf-8"), "not-json\n")

    def test_stale_server_from_another_working_tree_is_rejected(self) -> None:
        responses = [
            _Response("text/html; charset=utf-8"),
            _Response("text/markdown; charset=utf-8"),
            _Response(
                "application/json; charset=utf-8",
                {
                    "serverVersion": app_server.SERVER_VERSION,
                    "resolvedPackageRoot": str(self.root / "other-checkout"),
                    "gitHead": "A" * 40,
                    "serverContext": {"codexNetworkSandbox": False},
                    "sourceManifest": {
                        "version": "P1008_NEWS_SCAN_SOURCE_MANIFEST_v2",
                        "networkSummary": {},
                    },
                },
            ),
        ]
        with mock.patch("p1008_open_warroom.urllib.request.urlopen", side_effect=responses):
            self.assertFalse(
                open_warroom.page_ok(
                    8768,
                    expected_package_root=self.root,
                    expected_git_head="B" * 40,
                )
            )

    def test_matching_server_is_reused(self) -> None:
        with mock.patch("p1008_open_warroom.page_ok", return_value=True) as page_ok:
            port, reused, _blocked = open_warroom.choose_port(
                [8768, 8769],
                expected_package_root=self.root,
                expected_git_head="C" * 40,
            )
        self.assertEqual(port, 8768)
        self.assertTrue(reused)
        self.assertEqual(page_ok.call_args.kwargs["expected_package_root"], self.root)
        self.assertEqual(page_ok.call_args.kwargs["expected_git_head"], "C" * 40)

    def test_default_update_refreshes_rolling_brief_without_archive_append(self) -> None:
        before_runtime, before_report = self._write_matching_manifests()
        protected = {
            path.name: sha256(path)
            for path in (self.root / "data").iterdir()
            if path.is_file()
        }
        manager = _PipelineManager(self.root)
        manager._run_job_inner("default")
        brief = json.loads((self.root / rolling_brief.CURRENT_BRIEF_REL).read_text(encoding="utf-8"))
        self.assertEqual(brief["authorityDate"], "2026-07-27")
        self.assertFalse(brief["archiveEligible"])
        self.assertFalse(brief["libraryAppended"])
        self.assertFalse(brief["actionable"])
        self.assertEqual((self.root / rolling_brief.RUNTIME_MANIFEST_REL).read_bytes(), before_runtime)
        self.assertEqual((self.root / rolling_brief.REPORT_MANIFEST_REL).read_bytes(), before_report)
        self.assertEqual(manager.state["componentStatus"]["rollingBrief"]["status"], "UPDATED")
        self.assertEqual(manager.state["componentStatus"]["reportLibrary"]["status"], "PASS")
        self.assertNotIn("report", manager.calls)
        self.assertEqual(
            protected,
            {
                path.name: sha256(path)
                for path in (self.root / "data").iterdir()
                if path.is_file()
            },
        )

    def test_default_update_bootstraps_before_rolling_brief(self) -> None:
        manager = _PipelineManager(self.root)
        manager._run_job_inner("default")
        runtime = self.root / rolling_brief.RUNTIME_MANIFEST_REL
        report = self.root / rolling_brief.REPORT_MANIFEST_REL
        self.assertTrue(runtime.is_file())
        runtime_manifest = json.loads(runtime.read_text(encoding="utf-8"))
        report_manifest = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(runtime_manifest["schemaVersion"], "2.0")
        self.assertEqual(runtime_manifest["latest"], {})
        self.assertEqual(report_manifest["schemaVersion"], "1.0")
        self.assertEqual(
            report_manifest["latest"],
            {"daily": None, "weekly": None, "monthly": None},
        )
        self.assertNotEqual(runtime.read_bytes(), report.read_bytes())
        self.assertTrue((self.root / rolling_brief.CURRENT_BRIEF_REL).is_file())
        self.assertTrue((self.root / rolling_brief.LATEST_REPORT_REL).is_file())
        self.assertEqual(manager.state["componentStatus"]["reportLibrary"]["status"], "PASS")
        self.assertNotIn("report", manager.calls)

    def test_explicit_report_job_without_material_event_is_suppressed(self) -> None:
        self._write_matching_manifests()
        rolling_brief.refresh_current_brief(self.root)
        before_runtime = (self.root / rolling_brief.RUNTIME_MANIFEST_REL).read_bytes()
        before_report = (self.root / rolling_brief.REPORT_MANIFEST_REL).read_bytes()
        rolling_html_before = (self.root / rolling_brief.LATEST_REPORT_REL).read_bytes()
        manager = _PipelineManager(self.root)
        manager._run_job_inner("report")
        self.assertEqual(manager.state["componentStatus"]["reportGovernance"]["status"], "NO_MATERIAL_CHANGE")
        self.assertFalse(manager.state["componentStatus"]["reportGovernance"]["reportTriggerValid"])
        self.assertEqual((self.root / rolling_brief.RUNTIME_MANIFEST_REL).read_bytes(), before_runtime)
        self.assertEqual((self.root / rolling_brief.REPORT_MANIFEST_REL).read_bytes(), before_report)
        self.assertEqual(
            (self.root / rolling_brief.LATEST_REPORT_REL).read_bytes(),
            rolling_html_before,
        )
        self.assertNotIn("report", manager.calls)

    def test_valid_material_trigger_receipt_allows_existing_archive_path(self) -> None:
        self._write_matching_manifests()
        handoff = self._write_trigger_handoff(self._valid_trigger_handoff())
        result = periodic_report.build_report(
            type("Args", (), {"package_root": str(self.root), "date": "2026-07-27", "period": "daily", "trigger_handoff": str(handoff)})()
        )
        self.assertEqual(result, 0)
        manifest = json.loads((self.root / rolling_brief.REPORT_MANIFEST_REL).read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["reports"]), 1)
        report = manifest["reports"][0]
        self.assertEqual(report["reportKey"], "P1008_MONTHLY_REVENUE_202607")
        self.assertEqual(report["revision"], 1)
        self.assertEqual(report["eventType"], "MONTHLY_REVENUE")
        self.assertFalse(report["actionable"])

    def test_archive_path_fails_closed_for_missing_or_invalid_trigger_receipt(self) -> None:
        self._write_matching_manifests()
        base_args = {"package_root": str(self.root), "date": "2026-07-27", "period": "daily"}
        with self.assertRaises(periodic_report.ReportTriggerReceiptError):
            periodic_report.build_report(type("Args", (), {**base_args, "trigger_handoff": ""})())
        cases = {}
        invalid_receipt = self._valid_trigger_handoff()
        invalid_receipt["report_decision_receipt"]["canonical_sha256"] = "F" * 64
        cases["invalid receipt"] = invalid_receipt
        identity_mismatch = self._valid_trigger_handoff()
        identity_mismatch["revision"] = 2
        cases["revision mismatch"] = identity_mismatch
        event_mismatch = self._valid_trigger_handoff()
        event_mismatch["event_type"] = "UNKNOWN_EVENT"
        cases["event mismatch"] = event_mismatch
        unsupported = self._valid_trigger_handoff()
        unsupported["event_evidence"][0]["event_type"] = "UNKNOWN_EVENT"
        unsupported["event_type"] = "UNKNOWN_EVENT"
        cases["unsupported event"] = unsupported
        anomaly_without_policy = self._valid_trigger_handoff()
        anomaly_without_policy["event_evidence"][0]["event_type"] = "APPROVED_PRICE_VOLUME_POSITIONING_ANOMALY"
        anomaly_without_policy["event_type"] = "APPROVED_PRICE_VOLUME_POSITIONING_ANOMALY"
        cases["anomaly without approved policy"] = anomaly_without_policy
        authority_conflict = self._valid_trigger_handoff()
        conflicting = json.loads(json.dumps(authority_conflict["event_evidence"][0]))
        conflicting.update({
            "source_id": "SOURCE-002", "source_class": "SECONDARY", "source_tier": "MEDIA",
            "originating_chain_id": "CHAIN-002", "claim_summary": "Contradictory fact.",
        })
        authority_conflict["event_evidence"].append(conflicting)
        cases["authority conflict"] = authority_conflict
        for label, invalid in cases.items():
            with self.subTest(label=label):
                path = self._write_trigger_handoff(invalid)
                with self.assertRaises(periodic_report.ReportTriggerReceiptError):
                    periodic_report.build_report(type("Args", (), {**base_args, "trigger_handoff": str(path)})())
        manifest = json.loads((self.root / rolling_brief.REPORT_MANIFEST_REL).read_text(encoding="utf-8"))
        self.assertEqual(manifest["reports"], [])

    def test_both_manifests_and_rolling_artifacts_agree(self) -> None:
        self._write_matching_manifests()
        rolling_brief.refresh_current_brief(
            self.root, now=datetime(2026, 8, 2, tzinfo=timezone.utc)
        )
        health = rolling_brief.report_library_health(self.root)
        self.assertEqual(health["status"], "PASS")
        self.assertTrue(health["archiveManifestAgreement"])
        self.assertEqual(health["latestRollingBriefDate"], "2026-07-27")
        self.assertEqual(health["dataAlignmentStatus"], "ALIGNED")
        self.assertEqual(health["marketActivityFreshness"]["status"], "CURRENT")
        brief = json.loads(
            (self.root / rolling_brief.CURRENT_BRIEF_REL).read_text(encoding="utf-8")
        )
        self.assertEqual(
            brief["briefContentSha256"],
            rolling_brief.brief_content_sha256(brief),
        )
        self.assertEqual(self._launcher_gate(health)["code"], "READY_TO_ENTER_NEW_UI")

    def test_library_report_absent_from_runtime_fails_closed(self) -> None:
        self._write_matching_manifests()
        rolling_brief.refresh_current_brief(self.root)
        report_path = self.root / rolling_brief.REPORT_MANIFEST_REL
        divergent = json.loads(report_path.read_text(encoding="utf-8"))
        divergent["reports"] = [{"id": "missing-from-runtime", "date": "2026-07-27"}]
        divergent["latest"]["daily"] = divergent["reports"][0]
        report_path.write_text(
            json.dumps(divergent, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        health = rolling_brief.report_library_health(self.root)
        self.assertEqual(health["status"], "FAIL_CLOSED")
        self.assertEqual(health["code"], "REPORT_LIBRARY_MANIFEST_INVALID")
        gate = self._launcher_gate(health)
        self.assertEqual(gate["code"], "REPORT_LIBRARY_FAIL_CLOSED")
        self.assertFalse(gate["canEnterNewUi"])

    def test_first_run_manifest_state_blocks_navigation_until_bootstrapped(self) -> None:
        health = rolling_brief.report_library_health(self.root)
        self.assertEqual(health["status"], "FIRST_RUN_UNINITIALIZED")
        self.assertEqual(health["code"], "REPORT_LIBRARY_FIRST_RUN_UNINITIALIZED")
        self.assertIn("P1008_APP.bat", health["recoveryInstruction"])
        gate = self._launcher_gate(health)
        self.assertEqual(gate["code"], "REPORT_LIBRARY_FAIL_CLOSED")
        self.assertFalse(gate["canEnterNewUi"])

    def test_price_and_market_activity_cutoffs_are_governed_separately(self) -> None:
        self._write_matching_manifests()
        activity_path = self.root / "data/2317_daily_market_activity.csv"
        activity_path.write_text(
            "date,stock_id,trade_volume,trade_value,transaction_count,source_url,source_month\n"
            "2026-07-24,2317,90,22000,9,https://www.twse.com.tw/source,2026-07\n",
            encoding="utf-8",
        )
        rolling_brief.refresh_current_brief(self.root)
        brief = json.loads(
            (self.root / rolling_brief.CURRENT_BRIEF_REL).read_text(encoding="utf-8")
        )
        rendered = (self.root / rolling_brief.LATEST_REPORT_REL).read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            brief["dataCutoffs"],
            {"dailyPrice": "2026-07-27", "marketActivity": "2026-07-24"},
        )
        self.assertEqual(brief["dataAlignmentStatus"], "PARTIAL")
        self.assertEqual(brief["marketActivityFreshness"]["status"], "STALE")
        self.assertEqual(brief["marketActivityFreshness"]["lagCalendarDays"], 3)
        self.assertIn("成交股數", rendered)
        self.assertIn("資料截止：2026-07-24", rendered)
        self.assertIn("市場活動資料未與價格資料同日", rendered)

    def test_html_kpi_mutation_with_unchanged_identity_fails_closed(self) -> None:
        self._write_matching_manifests()
        rolling_brief.refresh_current_brief(self.root)
        html_path = self.root / rolling_brief.LATEST_REPORT_REL
        rendered = html_path.read_text(encoding="utf-8")
        self.assertIn(">100<", rendered)
        html_path.write_text(rendered.replace(">100<", ">101<", 1), encoding="utf-8")
        health = rolling_brief.report_library_health(self.root)
        self.assertEqual(health["status"], "FAIL_CLOSED")
        self.assertEqual(health["code"], "ROLLING_BRIEF_HTML_CONTENT_MISMATCH")
        self.assertEqual(self._launcher_gate(health)["code"], "REPORT_LIBRARY_FAIL_CLOSED")

    def test_json_kpi_mutation_with_unchanged_html_fails_closed(self) -> None:
        self._write_matching_manifests()
        rolling_brief.refresh_current_brief(self.root)
        brief_path = self.root / rolling_brief.CURRENT_BRIEF_REL
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
        brief["marketBaseline"]["dailyPrice"]["close"] = "999.0"
        brief_path.write_text(
            json.dumps(brief, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        health = rolling_brief.report_library_health(self.root)
        self.assertEqual(health["status"], "FAIL_CLOSED")
        self.assertEqual(health["code"], "ROLLING_BRIEF_JSON_CONTENT_HASH_MISMATCH")
        self.assertEqual(self._launcher_gate(health)["code"], "REPORT_LIBRARY_FAIL_CLOSED")

    def test_launcher_blocks_new_ui_and_library_when_report_health_fails(self) -> None:
        launcher = (PACKAGE_ROOT / "launcher.html").read_text(encoding="utf-8")
        self.assertIn('id="new-ui-link"', launcher)
        self.assertIn('id="research-library-link"', launcher)
        self.assertIn("gate.code === 'REPORT_LIBRARY_FAIL_CLOSED'", launcher)
        self.assertIn("setReportNavigationBlocked(reportLibraryBlocked)", launcher)
        self.assertIn("link.setAttribute('aria-disabled', blocked ? 'true' : 'false')", launcher)

    def test_file_mode_pages_reject_interactive_use(self) -> None:
        reports = (PACKAGE_ROOT / "reports.html").read_text(encoding="utf-8")
        viewer = (PACKAGE_ROOT / "report_viewer.html").read_text(encoding="utf-8")
        for text in (reports, viewer):
            self.assertIn("不支援 file:// 互動模式", text)
            self.assertIn("P1008_APP.bat", text)
        self.assertIn("if (fileMode) return [];", reports)
        self.assertIn('if (location.protocol === "file:")', viewer)

    def test_status_exposes_server_identity(self) -> None:
        manager = app_server.P1008JobManager(PACKAGE_ROOT)
        with (
            mock.patch.object(manager, "pending_owner_review", return_value={}),
            mock.patch.object(manager, "source_manifest_status", return_value={}),
            mock.patch.object(manager, "latest_report_status", return_value={}),
            mock.patch.object(manager, "review_package", return_value={}),
            mock.patch.object(manager, "launcher_gate_status", return_value={}),
        ):
            payload = manager.snapshot()
        self.assertEqual(payload["resolvedPackageRoot"], str(PACKAGE_ROOT.resolve()))
        self.assertEqual(payload["gitHead"], app_server.git_head(PACKAGE_ROOT))
        self.assertEqual(len(payload["serverInstanceId"]), 32)
        self.assertEqual(
            payload["authorityManifestSha256"],
            sha256(PACKAGE_ROOT / "data/CSV_AUTHORITY_MANIFEST.json"),
        )


if __name__ == "__main__":
    unittest.main()
