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
            path.write_text(json.dumps({"status": "NO_NEW_DAILY_PRICE", "launcher_status": "NO_NEW_DATA", "last_success_date": "2026-07-17", "receipt_paths": ["receipt.json"]}), encoding="utf-8")
        if step_id == "market-activity" and exit_code == 0:
            path = self.package_root / app_server.MARKET_ACTIVITY_STATUS_REL
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"status": "NO_NEW_MARKET_ACTIVITY", "launcher_status": "NO_NEW_DATA", "last_success_date": "2026-07-17", "receipt_paths": ["receipt.json"]}), encoding="utf-8")
        if step_id == "authority-freshness":
            path = self.package_root / app_server.FRESHNESS_STATUS_REL
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"status": "PASS", "twse_latest_validated_trading_date": "2026-07-17"}), encoding="utf-8")
        return exit_code

    def _run_news_scan_step(self) -> None:
        self.calls.append("news-scan")
        self._set_step("news-scan", "News", "SUCCEEDED", exitCode=0)

    def _run_python_step(self, step_id, label, args, timeout_seconds, *, allow_after_errors=False):
        self.calls.append(step_id)
        self._set_step(step_id, label, "SUCCEEDED", exitCode=0)

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
        self.assertEqual(manager.calls, ["preflight", "daily-price-authority", "market-activity", "authority-freshness", "update-data", "news-scan", "rolling-brief", "refresh"])
        self.assertEqual(manager.state["componentStatus"]["dailyPrice"]["status"], "NO_NEW_DATA")
        self.assertEqual(manager.state["componentStatus"]["marketActivity"]["status"], "NO_NEW_DATA")
        self.assertEqual(manager.state["overallStatus"], "SUCCEEDED")
        self.assertEqual(manager.timeouts, {"daily-price-authority": 180, "market-activity": 180, "authority-freshness": 60, "update-data": 420})

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
