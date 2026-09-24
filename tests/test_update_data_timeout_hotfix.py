from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TOOLS = PACKAGE_ROOT / "tools"
PLUGIN_SRC = PACKAGE_ROOT / "modules" / "p1008_research_plugin" / "src"
for import_path in (TOOLS, PLUGIN_SRC):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import p1008_app_server as app_server  # noqa: E402


class UpdateDataTimeoutHotfixTests(unittest.TestCase):
    @contextmanager
    def controlled_temp(self, prefix: str) -> Iterator[Path]:
        parent = PACKAGE_ROOT / "runtime" / "update_data_timeout_hotfix_test_scratch"
        root = parent / f"{prefix}{uuid4().hex}"
        root.mkdir(parents=True, exist_ok=False)
        try:
            yield root
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def manager(self, root: Path) -> app_server.P1008JobManager:
        manager = app_server.P1008JobManager.__new__(app_server.P1008JobManager)
        manager.package_root = root
        manager.lock = threading.Lock()
        manager.active_thread = None
        manager.state = {
            "jobId": "test-update-data",
            "jobType": "update-data",
            "status": "RUNNING",
            "overallStatus": "RUNNING",
            "startedAt": app_server.now_iso(),
            "finishedAt": "",
            "steps": [],
            "errors": [],
            "warnings": [],
            "logPath": "logs/test_update_data_timeout.log",
        }
        manager._persist_locked = lambda: None  # type: ignore[method-assign]
        return manager

    @unittest.skipUnless(os.name == "nt", "Windows process-tree semantics")
    def test_timeout_terminates_owned_cmd_and_python_descendant(self) -> None:
        with self.controlled_temp("p1008-update-timeout-") as root:
            helper = root / "slow_child.py"
            child_pid = root / "child.pid"
            helper.write_text(
                "import os, pathlib, time\n"
                f"pathlib.Path({str(child_pid)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            bat = root / "slow.cmd"
            bat.write_text(
                f'@echo off\r\nping -n 2 127.0.0.1 >nul\r\n"{sys.executable}" "{helper}"\r\n',
                encoding="utf-8",
            )
            manager = self.manager(root)

            started = time.monotonic()
            result = manager._run_bat_step(
                "update-data", "Other staging/runtime data update", bat, [], 2
            )
            duration = time.monotonic() - started

            self.assertIsNone(result)
            self.assertLess(duration, 8.0)
            step = manager.state["steps"][-1]
            self.assertEqual(step["status"], "FAILED")
            self.assertEqual(step["exitCode"], "TIMEOUT")
            self.assertTrue(step["finishedAt"])
            self.assertTrue(step["processTreeTerminated"])
            self.assertTrue(child_pid.is_file())
            pid = int(child_pid.read_text(encoding="utf-8"))
            listing = subprocess.run(
                ["tasklist.exe", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
            ).stdout
            self.assertNotIn(f'"{pid}"', listing)

    @unittest.skipUnless(os.name == "nt", "Windows BAT execution")
    def test_successful_child_and_update_data_heartbeat(self) -> None:
        with self.controlled_temp("p1008-update-success-") as root:
            helper = root / "success_child.py"
            helper.write_text(
                "import pathlib, time\n"
                "p = pathlib.Path('logs/last_update_data.log')\n"
                "p.parent.mkdir(parents=True, exist_ok=True)\n"
                "p.write_text('[00:00:00] [INFO] [PROGRESS] metric=vix "
                "provider=Yahoo transport=provider event=chosen_successful_source "
                "fallback_budget_remaining=12.00s\\n', encoding='utf-8')\n"
                "time.sleep(0.4)\n",
                encoding="utf-8",
            )
            bat = root / "success.cmd"
            bat.write_text(
                f'@echo off\r\n"{sys.executable}" "{helper}"\r\nexit /b %ERRORLEVEL%\r\n',
                encoding="utf-8",
            )
            manager = self.manager(root)

            result = manager._run_bat_step(
                "update-data", "Other staging/runtime data update", bat, [], 5
            )

            self.assertEqual(result, 0)
            step = manager.state["steps"][-1]
            self.assertEqual(step["status"], "SUCCEEDED")
            self.assertEqual(step["exitCode"], 0)
            app_log = (root / manager.state["logPath"]).read_text(encoding="utf-8")
            self.assertIn("update-data: PROGRESS", app_log)
            self.assertIn("chosen_successful_source", app_log)

    def test_unhandled_job_failure_always_sets_terminal_finished_at(self) -> None:
        with self.controlled_temp("p1008-update-finalize-") as root:
            manager = self.manager(root)
            manager._run_job_inner = (  # type: ignore[method-assign]
                lambda _job_type: (_ for _ in ()).throw(RuntimeError("boom"))
            )

            manager._run_job("update-data", "test-update-data")

            self.assertEqual(manager.state["status"], "FAILED")
            self.assertEqual(manager.state["overallStatus"], "FAILED")
            self.assertTrue(manager.state["finishedAt"])
            self.assertIn("UNHANDLED: boom", manager.state["errors"])
            self.assertEqual(
                manager.state["failureReasons"][0]["source"], "UNHANDLED"
            )


if __name__ == "__main__":
    unittest.main()
