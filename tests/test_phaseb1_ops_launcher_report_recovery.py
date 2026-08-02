from __future__ import annotations

import hashlib
import json
import shutil
import sys
import threading
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
        if step_id == "market-activity":
            path = self.package_root / app_server.MARKET_ACTIVITY_STATUS_REL
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "status": "NO_NEW_MARKET_ACTIVITY",
                        "launcher_status": "NO_NEW_DATA",
                        "last_success_date": "2026-07-27",
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

    def _refresh(self, before):
        self.calls.append("refresh")

    def _market_activity_last_date(self):
        return "2026-07-27"


class PhaseB1OpsLauncherReportRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = PACKAGE_ROOT / "runtime" / "phaseb1_ops_test_scratch" / uuid.uuid4().hex
        (self.root / "data").mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(self.root) if self.root.exists() else None)
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
        payload = {
            "schemaVersion": "1.0",
            "latest": {"daily": None, "weekly": None, "monthly": None},
            "reports": reports or [],
            "actionable": False,
        }
        body = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        runtime = self.root / rolling_brief.RUNTIME_MANIFEST_REL
        report = self.root / rolling_brief.REPORT_MANIFEST_REL
        runtime.parent.mkdir(parents=True, exist_ok=True)
        report.parent.mkdir(parents=True, exist_ok=True)
        runtime.write_bytes(body)
        report.write_bytes(body)
        return runtime.read_bytes(), report.read_bytes()

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

    def test_explicit_report_job_appends_archive(self) -> None:
        self._write_matching_manifests()
        rolling_brief.refresh_current_brief(self.root)
        rolling_html_before = (self.root / rolling_brief.LATEST_REPORT_REL).read_bytes()
        manager = _PipelineManager(self.root)
        manager._run_job_inner("report")
        manifest = json.loads((self.root / rolling_brief.REPORT_MANIFEST_REL).read_text(encoding="utf-8"))
        self.assertEqual([item["id"] for item in manifest["reports"]], ["P1008_DAILY_20260727"])
        self.assertEqual(
            (self.root / rolling_brief.REPORT_MANIFEST_REL).read_bytes(),
            (self.root / rolling_brief.RUNTIME_MANIFEST_REL).read_bytes(),
        )
        self.assertEqual(
            (self.root / rolling_brief.LATEST_REPORT_REL).read_bytes(),
            rolling_html_before,
        )

    def test_both_manifests_and_rolling_artifacts_agree(self) -> None:
        self._write_matching_manifests()
        rolling_brief.refresh_current_brief(
            self.root, now=datetime(2026, 8, 2, tzinfo=timezone.utc)
        )
        health = rolling_brief.report_library_health(self.root)
        self.assertEqual(health["status"], "PASS")
        self.assertTrue(health["archiveManifestAgreement"])
        self.assertEqual(health["latestRollingBriefDate"], "2026-07-27")

    def test_manifest_mismatch_fails_closed(self) -> None:
        self._write_matching_manifests()
        rolling_brief.refresh_current_brief(self.root)
        (self.root / rolling_brief.RUNTIME_MANIFEST_REL).write_text(
            '{"reports":[{"id":"unexpected"}]}\n', encoding="utf-8"
        )
        health = rolling_brief.report_library_health(self.root)
        self.assertEqual(health["status"], "FAIL_CLOSED")
        self.assertEqual(health["code"], "REPORT_LIBRARY_MANIFEST_MISMATCH")

    def test_missing_manifest_has_actionable_recovery(self) -> None:
        health = rolling_brief.report_library_health(self.root)
        self.assertEqual(health["status"], "FAIL_CLOSED")
        self.assertEqual(health["code"], "REPORT_LIBRARY_MANIFEST_MISSING")
        self.assertIn("P1008_APP.bat", health["recoveryInstruction"])

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
