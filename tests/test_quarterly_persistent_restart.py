"""Offline, disk-backed Quarterly restart acceptance using separate processes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import threading
import unittest
import uuid
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "modules/p1008_research_plugin/src")]
import p1008_app_server as app
import warroom_report_trigger_runtime as trigger
import warroom_quarterly_report_completion as completion
from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline
from p1008_research_plugin.phaseb1_common import protected_state_hashes

EVIDENCE = ROOT / "runtime/q2_historical_compatibility/F014BE750095543B_EDITORIAL_V1"


def worker(action, base):
    """Each invocation starts with no in-memory analysis/report objects."""
    receipt = trigger.require_valid_trigger(ROOT, evidence_root=EVIDENCE)
    lineage = trigger.trigger_lineage(receipt)
    pipeline = PhaseB1Pipeline(ROOT, governed_evidence_root=EVIDENCE)
    if action == "analysis":
        result = pipeline.build_analysis(output_base=base, trigger_lineage=lineage)
        return {"status": result.get("status", "ANALYSIS_CANDIDATE_READY"), "runId": result["run_id"]}
    fixture, _ = pipeline.load_inputs("QUARTERLY_EARNINGS", lineage)
    result = pipeline.build_report(run_id=pipeline.deterministic_run_id(fixture), output_base=base,
                                   trigger_lineage=lineage, report_runtime="ENTERPRISE_VALUE_WAR_REPORT_V1")
    if action == "candidate":
        return {"status": "REPORT_CANDIDATE_READY", "runId": result["run_id"]}
    return completion.complete_quarterly_report(ROOT, result, persistence_root=base / "state")


def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


class PersistentQuarterlyRestartTests(unittest.TestCase):
    def setUp(self):
        if not EVIDENCE.is_dir():
            self.fail("Required governed Q2 compatibility evidence unavailable")
        self.base = ROOT / "runtime/report_production/test_scratch" / ("restart-" + uuid.uuid4().hex)
        self.base.mkdir(parents=True)
        self.before = protected_state_hashes(ROOT)

    def tearDown(self):
        self.assertEqual(self.before, protected_state_hashes(ROOT))
        # Only this test's exact unique scratch root; no authority/production cleanup.
        self.assertEqual(self.base.parent, ROOT / "runtime/report_production/test_scratch")
        def clear_test_readonly(function, target, _error):
            os.chmod(target, stat.S_IWRITE)
            function(target)
        shutil.rmtree(self.base, onexc=clear_test_readonly)

    def run_process(self, action):
        result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--worker", action, str(self.base)],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=90,
                                env={**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def start(self):
        result = self.run_process("analysis")
        self.assertEqual(result["status"], "ANALYSIS_CANDIDATE_READY")
        self.run_root = self.base / result["runId"]

    def test_persistent_restart_full_e2e_and_launcher_projection(self):
        self.start()
        first = self.run_process("report")
        self.assertEqual(first["status"], "OWNER_REVIEW_REQUIRED", first)
        before = hashes(self.base)
        again = self.run_process("analysis")
        self.assertEqual(again["status"], "EXISTING_VALIDATED_RUN", again)
        replay = self.run_process("report")
        self.assertEqual(replay["status"], "IDEMPOTENT_REPLAY", replay)
        self.assertEqual(hashes(self.base), before)
        self.assertEqual(replay["publicationGate"]["status"], "DENIED")
        self.assertFalse(replay["publishAuthorized"])
        self.assertFalse(replay["publication"])
        self.assertFalse(replay["publicationComplete"])
        for rel in ("runtime/warroom_report_manifest.json", "reports/P1008_REPORT_MANIFEST.json"):
            manifest = json.loads((self.base / "state" / rel).read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["reports"]), 1)
            entry = manifest["reports"][0]
            self.assertEqual(entry["revision"], 1)
            self.assertEqual({item["format"] for item in entry["renderedArtifacts"]}, {"HTML", "PDF"})
        manager = app.P1008JobManager.__new__(app.P1008JobManager)
        manager.package_root = self.base / "state"
        state = manager.latest_report_status()
        self.assertTrue(state["reportGenerated"])
        self.assertTrue(state["reportEligible"])
        self.assertEqual(state["latestQuarterly"]["report_key"], replay["report_key"])
        self.assertEqual(state["latestQuarterly"]["revision"], replay["revision"])
        owner = manager.pending_owner_review()
        self.assertTrue(owner["pending"])
        self.assertEqual(owner["pendingReviewCount"], 1)
        editorial = json.loads((self.run_root / "enterprise_value_war_report/editorial_validation.json").read_text(encoding="utf-8"))
        self.assertEqual(editorial["status"], "PASS")
        ui = (ROOT / "launcher.html").read_text(encoding="utf-8")
        self.assertIn("latest.latestQuarterly", ui)
        self.assertIn("latestQuarterly.report_key", ui)
        self.assertIn("latestQuarterly.revision", ui)
        # Execute the real renderStatus function offline with a minimal DOM.
        render = ui[ui.index("    function renderStatus() {"):ui.index("    function maybeRedirect() {")]
        script = """
const state = __TEST_APP_STATE__;
const nodes = new Map();
const $ = id => { if (!nodes.has(id)) nodes.set(id, {style:{}, value:''}); return nodes.get(id); };
const badgeClass = value => value, safe = value => String(value);
const setReportNavigationBlocked = () => {}, setBusy = () => {}, maybeRedirect = () => {};
const canPublish = () => false, displayLog = value => value;
const clientReadinessExplanation = () => ({}), renderNoteGroup = () => '';
const JOB_TYPE_ZH = {}, location = {search:'?stay=1'};
""" + render + """
renderStatus();
console.log(JSON.stringify({latest:$('latest-report').textContent, next:$('trigger-next-action').textContent}));
"""
        script = script.replace("__TEST_APP_STATE__", json.dumps({"app": {
            "latestReport": state, "pendingOwnerReview": owner,
            "reportTrigger": {"reportGenerated": True}}}))
        rendered = subprocess.run([shutil.which("node") or "node", "-"], input=script,
                                  capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        labels = json.loads(rendered.stdout)
        self.assertIn(replay["report_key"], labels["latest"])
        self.assertIn("r1", labels["latest"])
        self.assertIn("OWNER_REVIEW_REQUIRED", labels["latest"])
        self.assertIn("尚未發布", labels["next"])

    def test_report_candidate_ready_resumes_without_overwrite(self):
        self.start()
        self.assertEqual(self.run_process("candidate")["status"], "REPORT_CANDIDATE_READY")
        before = hashes(self.run_root)
        self.assertEqual(self.run_process("analysis")["status"], "EXISTING_VALIDATED_RUN")
        self.assertEqual(hashes(self.run_root), before)
        self.assertEqual(self.run_process("report")["status"], "OWNER_REVIEW_REQUIRED")

    def test_analysis_artifact_tamper_fails_closed(self):
        self.start()
        (self.run_root / "analysis_packet.json").write_bytes(b"{}")
        before = hashes(self.base)
        self.assertEqual(self.run_process("analysis")["status"], "FAIL_CLOSED")
        self.assertEqual(self.run_process("report")["status"], "FAIL_CLOSED")
        self.assertEqual(hashes(self.base), before)

    def test_provenance_tamper_fails_closed(self):
        self.start()
        path = self.run_root / "run_manifest.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["governedEvidence"]["authority_manifest_sha256"] = "0" * 64
        path.write_text(json.dumps(payload), encoding="utf-8")
        before = hashes(self.base)
        self.assertEqual(self.run_process("analysis")["status"], "FAIL_CLOSED")
        self.assertEqual(hashes(self.base), before)

    def test_report_artifact_tamper_fails_closed(self):
        self.start()
        self.assertEqual(self.run_process("report")["status"], "OWNER_REVIEW_REQUIRED")
        (self.run_root / "enterprise_value_war_report/war_report_candidate.html").write_bytes(b"changed")
        before = hashes(self.base)
        self.assertEqual(self.run_process("analysis")["status"], "FAIL_CLOSED")
        self.assertEqual(self.run_process("report")["status"], "FAIL_CLOSED")
        self.assertEqual(hashes(self.base), before)

    def test_stale_library_or_owner_never_projects_success(self):
        self.start()
        first = self.run_process("report")
        self.assertEqual(first["status"], "OWNER_REVIEW_REQUIRED")
        path = self.base / "state" / first["ownerReviewLocator"]
        owner = json.loads(path.read_text(encoding="utf-8"))
        owner["revision"] = 2
        path.write_text(json.dumps(owner), encoding="utf-8")
        state = completion.quarterly_report_status(self.base / "state")
        self.assertEqual(state["status"], "FAIL_CLOSED")
        self.assertFalse(state["reportGenerated"])
        self.assertEqual(self.run_process("report")["status"], "FAIL_CLOSED")

    def test_absent_library_is_not_generated(self):
        state = completion.quarterly_report_status(self.base)
        self.assertFalse(state["reportGenerated"])
        self.assertFalse(state["reportEligible"])

    def test_bat_captures_current_result_not_prior_success(self):
        manager = app.P1008JobManager.__new__(app.P1008JobManager)
        manager.package_root = self.base
        manager.lock = threading.Lock()
        manager.state = {"steps": []}
        manager._persist_locked = lambda: None
        manager._append_log = lambda _: None
        for status in ("OWNER_REVIEW_REQUIRED", "IDEMPOTENT_REPLAY", "FAIL_CLOSED"):
            output = subprocess.CompletedProcess([], 1 if status == "FAIL_CLOSED" else 0,
                                                 json.dumps({"status": status}), "")
            with mock.patch.object(app.subprocess, "run", return_value=output):
                manager._run_bat_step("report-candidate", "Report", self.base / "unused.bat", [], 1)
            self.assertEqual(manager.state["steps"][-1]["runtimeResult"]["status"], status)


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "--worker":
    try:
        print(json.dumps(worker(sys.argv[2], Path(sys.argv[3])), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"status": "FAIL_CLOSED", "reason": str(exc)}, ensure_ascii=False))
elif __name__ == "__main__":
    unittest.main()
