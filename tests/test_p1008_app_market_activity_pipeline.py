from __future__ import annotations

import json
import shutil
import sys
import threading
import unittest
import uuid
from pathlib import Path
from unittest import mock


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TOOLS = PACKAGE_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import p1008_app_server as app_server  # noqa: E402


BASE_HASHES = {
    "data/2317_master_v9.csv": "A",
    "data/2317_daily_price.csv": "B",
    "data/2317_daily_market_activity.csv": "C",
    "data/macro_snapshot.csv": "D",
    "data/macro_event_observations.csv": "E",
    "data/fx_trend_observations.csv": "F",
    "data/CSV_AUTHORITY_MANIFEST.json": "G",
}


class FakeManager(app_server.P1008JobManager):
    def __init__(self, root: Path, *, daily_exit: int = 0, market_exit: int = 0) -> None:
        self.package_root = root
        self.lock = threading.Lock()
        self.active_thread = None
        self.daily_exit = daily_exit
        self.market_exit = market_exit
        self.calls: list[str] = []
        self.timeouts: dict[str, int] = {}
        self.step_args: dict[str, list[str]] = {}
        self.python_step_args: dict[str, list[str]] = {}
        self.daily_payload: dict[str, object] = {
            "status": "NO_NEW_DAILY_PRICE", "launcher_status": "NO_NEW_DATA",
            "last_success_date": "2026-07-17", "receipt_paths": ["receipt.json"],
        }
        self.market_payload: dict[str, object] = {
            "status": "NO_NEW_MARKET_ACTIVITY", "launcher_status": "NO_NEW_DATA",
            "last_success_date": "2026-07-17", "receipt_paths": ["receipt.json"],
        }
        self.state = self._initial_state()
        self.state.update({"status": "RUNNING", "steps": [], "errors": [], "warnings": [], "componentStatus": {}, "logPath": "logs/test.log"})

    def _persist_locked(self) -> None:
        return

    def _append_log(self, message: str) -> None:
        return

    def _preflight(self) -> dict[str, str]:
        self.calls.append("preflight")
        return dict(BASE_HASHES)

    def review_package(self, date_str=None):
        return {"generatedFiles": [], "candidateDate": "2026-07-19"}

    def _run_bat_step(self, step_id, label, bat_path, args, timeout_seconds):
        self.calls.append(step_id)
        self.timeouts[step_id] = timeout_seconds
        self.step_args[step_id] = list(args)
        exit_code = (
            self.daily_exit
            if step_id == "daily-price-authority"
            else self.market_exit
            if step_id == "market-activity"
            else 0
        )
        self._set_step(step_id, label, "SUCCEEDED" if exit_code == 0 else "FAILED", exitCode=exit_code)
        if step_id == "daily-price-authority":
            path = self.package_root / app_server.DAILY_PRICE_STATUS_REL
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.daily_payload), encoding="utf-8")
        if step_id == "market-activity" and exit_code == 0:
            path = self.package_root / app_server.MARKET_ACTIVITY_STATUS_REL
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.market_payload), encoding="utf-8")
        if step_id == "authority-freshness":
            path = self.package_root / app_server.FRESHNESS_STATUS_REL
            path.parent.mkdir(parents=True, exist_ok=True)
            overlay = "--daily-price-run-dir" in args
            path.write_text(json.dumps({
                "status": "PASS_CANDIDATE_OVERLAY" if overlay else "PASS",
                "freshness_scope": "CANDIDATE_OVERLAY" if overlay else "FORMAL_AUTHORITY",
                "formal_authority_current": not overlay,
                "owner_publish_required": overlay,
                "twse_latest_validated_trading_date": "2026-07-22" if overlay else "2026-07-17",
            }), encoding="utf-8")
        return exit_code

    def _run_news_scan_step(self) -> None:
        self.calls.append("news-scan")
        self._set_step("news-scan", "News", "SUCCEEDED", exitCode=0)

    def _run_python_step(self, step_id, label, args, timeout_seconds, *, allow_after_errors=False):
        self.calls.append(step_id)
        self.python_step_args[step_id] = list(args)
        self._set_step(step_id, label, "SUCCEEDED", exitCode=0)
        if step_id == "official-ir-scan":
            path = self.package_root / app_server.OFFICIAL_IR_STATUS_REL
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "status": "SCHEDULE_CONFIRMED",
                "canonical_event_id": "HON_HAI_FY2026_Q2_EARNINGS",
                "schedule": {"fiscal_period": "FY2026 Q2", "source_id": "HON_HAI_EVENT_CALENDAR"},
                "detected_evidence": [],
                "evaluated_at_utc": "2026-08-12T12:00:00Z",
                "source_scan_complete": True,
                "actionable": False,
            }), encoding="utf-8")

    def _refresh(self, before, *, allow_authority_change=False):
        self.calls.append("refresh")

    def _refresh_rolling_brief_step(self):
        self.calls.append("rolling-brief")
        self._set_component_status("rollingBrief", "UPDATED", archiveAppended=False)
        self._set_component_status("reportLibrary", "PASS")
        return ""

    def _market_activity_last_date(self) -> str:
        return "2026-07-17"


class LauncherMarketActivityPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = PACKAGE_ROOT / "runtime/app_pipeline_test_scratch" / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))

    def test_default_pipeline_no_material_change_skips_report(self) -> None:
        manager = FakeManager(self.root)
        with mock.patch.object(app_server, "formal_csv_hashes", return_value=dict(BASE_HASHES)):
            manager._run_job_inner("default")
        self.assertEqual(manager.calls, ["preflight", "daily-price-authority", "market-activity", "authority-freshness", "update-data", "news-scan", "official-ir-scan", "rolling-brief", "refresh"])
        self.assertEqual(manager.state["componentStatus"]["dailyPrice"]["status"], "NO_NEW_DATA")
        self.assertEqual(manager.state["componentStatus"]["marketActivity"]["status"], "NO_NEW_DATA")
        self.assertEqual(manager.state["overallStatus"], "SUCCEEDED")
        self.assertEqual(manager.timeouts, {"daily-price-authority": 180, "market-activity": 180, "authority-freshness": 60, "update-data": 420})
        self.assertEqual(manager.step_args["daily-price-authority"], ["--dry-run"])
        self.assertEqual(manager.step_args["market-activity"], ["--dry-run"])

    def test_official_ir_propagates_existing_canonical_period_across_quarters(self) -> None:
        manager = FakeManager(self.root)
        path = self.root / app_server.RESEARCH_INTEGRATION_STATUS_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        for period in (
            "FY2025 Q4",
            "FY2026 Q1",
            "FY2026 Q2",
            "FY2026 Q3",
            "FY2026 Q4",
            "FY2027 Q1",
        ):
            with self.subTest(period=period):
                path.write_text(
                    json.dumps({"official_ir": {"active_fiscal_period": period}}),
                    encoding="utf-8",
                )
                manager._run_official_ir_step()
                self.assertEqual(
                    manager.python_step_args["official-ir-scan"][-2:],
                    ["--period", period],
                )

    def test_official_ir_missing_canonical_period_does_not_guess(self) -> None:
        manager = FakeManager(self.root)
        manager._run_official_ir_step()
        self.assertNotIn("--period", manager.python_step_args["official-ir-scan"])

    def test_launcher_binds_market_activity_to_same_run_daily_price_staging(self) -> None:
        manager = FakeManager(self.root)
        manager.daily_payload = {
            "status": "DRY_RUN_READY", "launcher_status": "UPDATED",
            "run_id": "P1008-DAILY-PRICE-TEST", "run_dir": "C:/runtime/P1008-DAILY-PRICE-TEST",
            "last_success_date": "2026-07-17", "receipt_paths": ["receipt.json"], "dry_run": True,
        }
        manager.market_payload = {
            "status": "DRY_RUN_READY", "launcher_status": "UPDATED",
            "run_id": "P1008-MARKET-ACTIVITY-TEST",
            "run_dir": "C:/runtime/P1008-MARKET-ACTIVITY-TEST",
            "last_success_date": "2026-07-17", "receipt_paths": ["receipt.json"],
            "dry_run": True,
        }
        with mock.patch.object(app_server, "formal_csv_hashes", return_value=dict(BASE_HASHES)):
            manager._run_job_inner("default")
        self.assertEqual(manager.step_args["daily-price-authority"], ["--dry-run"])
        self.assertEqual(
            manager.step_args["market-activity"],
            ["--dry-run", "--daily-price-run-dir", "C:/runtime/P1008-DAILY-PRICE-TEST", "--daily-price-run-id", "P1008-DAILY-PRICE-TEST"],
        )
        self.assertEqual(
            manager.step_args["authority-freshness"],
            [
                "--daily-price-run-dir", "C:/runtime/P1008-DAILY-PRICE-TEST",
                "--daily-price-run-id", "P1008-DAILY-PRICE-TEST",
                "--market-activity-run-dir", "C:/runtime/P1008-MARKET-ACTIVITY-TEST",
                "--market-activity-run-id", "P1008-MARKET-ACTIVITY-TEST",
            ],
        )
        self.assertIn("news-scan", manager.calls)
        self.assertIn("rolling-brief", manager.calls)
        freshness_state = manager.state["componentStatus"]["freshness"]
        self.assertEqual(freshness_state["status"], "PASS_CANDIDATE_OVERLAY")
        self.assertTrue(freshness_state["ownerPublishRequired"])

    def test_default_job_never_runs_report(self) -> None:
        manager = FakeManager(self.root)
        with mock.patch.object(
            app_server, "formal_csv_hashes", return_value=dict(BASE_HASHES)
        ):
            manager._run_job_inner("default")
        self.assertNotIn("report", manager.calls)

    def test_daily_failure_blocks_market_and_downstream(self) -> None:
        manager = FakeManager(self.root, daily_exit=5)
        with mock.patch.object(app_server, "formal_csv_hashes", return_value=dict(BASE_HASHES)):
            manager._run_job_inner("default")
        self.assertNotIn("market-activity", manager.calls)
        self.assertNotIn("news-scan", manager.calls)
        self.assertNotIn("rolling-brief", manager.calls)
        self.assertEqual(manager.state["componentStatus"]["marketActivity"]["status"], "BLOCKED")
        self.assertEqual(manager.state["overallStatus"], "PARTIAL_FAILURE")

    def test_market_failure_stops_downstream(self) -> None:
        manager = FakeManager(self.root, market_exit=30)
        with mock.patch.object(app_server, "formal_csv_hashes", return_value=dict(BASE_HASHES)):
            manager._run_job_inner("default")
        self.assertNotIn("news-scan", manager.calls)
        self.assertNotIn("rolling-brief", manager.calls)
        self.assertEqual(manager.state["componentStatus"]["marketActivity"]["status"], "STALE")
        self.assertEqual(manager.state["overallStatus"], "PARTIAL_FAILURE")

    def test_current_run_failed_child_cannot_be_masked_by_refresh_success(self) -> None:
        manager = FakeManager(self.root)
        manager.state["overallStatus"] = "SUCCEEDED"
        def failed_then_refreshed(_job_type: str) -> None:
            manager._set_step(
                "analysis-candidate", "Analysis", "FAILED",
                message="OFFICIAL_IR_Q2_AUTHORITY_MISMATCH",
            )
            manager._set_step("app-state-refresh", "Refresh", "SUCCEEDED")

        manager._run_job_inner = failed_then_refreshed  # type: ignore[method-assign]
        manager._run_job("analysis-candidate", "CURRENT-RUN")
        self.assertEqual(manager.state["status"], "FAILED")
        self.assertEqual(manager.state["overallStatus"], "FAILED")
        self.assertEqual(
            manager.state["failureReasons"][0]["reason"],
            "OFFICIAL_IR_Q2_AUTHORITY_MISMATCH",
        )

    def test_current_run_blocked_child_is_explicit(self) -> None:
        manager = FakeManager(self.root)
        manager.state["steps"] = [
            {"id": "report-candidate", "status": "BLOCKED", "code": "ANALYSIS_CANDIDATE_REQUIRED"}
        ]
        status, reasons = manager._aggregate_current_run_status()
        self.assertEqual(status, "BLOCKED")
        self.assertEqual(reasons[0]["reason"], "ANALYSIS_CANDIDATE_REQUIRED")

    def test_official_ir_partial_authority_propagates_to_top_level(self) -> None:
        manager = FakeManager(self.root)
        manager.state["componentStatus"] = {
            "officialIR": {
                "status": "PARTIAL_FAILURE_WITH_AUTHORITY",
                "failedSources": [{"source_id": "MOPS", "error": "OFFICIAL_ENDPOINT_ERROR"}],
            }
        }
        status, reasons = manager._aggregate_current_run_status()
        self.assertEqual(status, "PARTIAL_FAILURE")
        self.assertIn("OFFICIAL_ENDPOINT_ERROR", reasons[0]["reason"])

    def test_structured_current_run_failure_is_exposed(self) -> None:
        output = 'diagnostic\n{"status":"FAIL_CLOSED","error":"OFFICIAL_IR_Q2_AUTHORITY_MISMATCH"}\n'
        self.assertEqual(
            app_server.command_failure_reason(output, "exit=1"),
            "OFFICIAL_IR_Q2_AUTHORITY_MISMATCH",
        )
        self.assertEqual(
            app_server.command_failure_reason("plain failure", "exit=7"), "exit=7"
        )

    def test_active_launcher_job_returns_conflict(self) -> None:
        manager = FakeManager(self.root)

        class ActiveThread:
            @staticmethod
            def is_alive() -> bool:
                return True

        manager.active_thread = ActiveThread()
        status, payload = manager.start_job("default")
        self.assertEqual(status, 409)
        self.assertIn("already running", payload["message"])

    def test_existing_daily_price_and_news_bat_chains_remain_present(self) -> None:
        daily = (PACKAGE_ROOT / "P1008_1_UPDATE_DATA.bat").read_text(encoding="utf-8")
        authority = (PACKAGE_ROOT / "P1008_1A_UPDATE_DAILY_PRICE.bat").read_text(encoding="utf-8")
        news = (PACKAGE_ROOT / "P1008_4_NEWS_SCAN.bat").read_text(encoding="utf-8")
        self.assertIn("tools\\p1008_update_data.cmd", daily)
        self.assertIn("tools\\p1008_update_daily_price.cmd", authority)
        self.assertIn("tools\\p1008_news_scan.cmd", news)

    def test_all_data_wrappers_use_bundled_python_without_system_fallback(self) -> None:
        for rel in (
            "tools/p1008_update_data.cmd",
            "tools/p1008_update_daily_price.cmd",
            "tools/p1008_update_market_activity.cmd",
            "tools/p1008_validate_authority_freshness.cmd",
        ):
            wrapper = (PACKAGE_ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("codex-primary-runtime\\dependencies\\python\\python.exe", wrapper)
            self.assertNotIn("where.exe", wrapper)
            self.assertNotIn("pythoncore-3.14", wrapper)

    def test_launcher_exposes_three_component_and_overall_statuses(self) -> None:
        launcher = (PACKAGE_ROOT / "launcher.html").read_text(encoding="utf-8")
        for element_id in (
            "daily-price-status",
            "market-activity-status",
            "news-component-status",
            "overall-component-status",
            "market-activity-date",
            "market-activity-log",
            "served-package-root",
            "served-git-head",
            "latest-rolling-brief-date",
            "latest-archived-report-date",
            "report-library-health",
        ):
            self.assertIn(f'id="{element_id}"', launcher)
        self.assertIn("HTTP_403_POLICY_BLOCKED|TIMEOUT_TRANSIENT", launcher)
        self.assertIn("SUCCESS_NO_RELEVANT_EVENT", launcher)


if __name__ == "__main__":
    unittest.main()
