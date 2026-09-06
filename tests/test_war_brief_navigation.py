from __future__ import annotations

import hashlib
import http.server
import sys
import threading
import unittest
import urllib.request
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "tools"))

import p1008_app_server as app_server  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class WarBriefNavigationTests(unittest.TestCase):
    def test_current_brief_uses_existing_local_server_routes(self) -> None:
        brief_path = PACKAGE_ROOT / "reports/generated/latest_report.html"
        before = sha256(brief_path)
        manager = app_server.P1008JobManager(PACKAGE_ROOT)

        class Handler(app_server.P1008AppHandler):
            pass

        Handler.manager = manager
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            lambda *args, **kwargs: Handler(
                *args, directory=str(PACKAGE_ROOT), **kwargs
            ),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with urllib.request.urlopen(
                base + app_server.CURRENT_WAR_BRIEF_ROUTE + "?iab=1&fs=1",
                timeout=5,
            ) as response:
                self.assertEqual(response.status, 200)
                rendered = response.read().decode("utf-8")
            self.assertIn('id="p1008-war-brief-navigation"', rendered)
            self.assertIn(
                'href="/launcher.html?stay=1&amp;from=war_brief"', rendered
            )
            self.assertIn(
                'href="/ui/P1008_WARROOM_COMMAND_CENTER_v24.html?from=war_brief"',
                rendered,
            )
            self.assertIn("返回 Launcher", rendered)
            self.assertIn("進入新 UI", rendered)
            self.assertIn("35,223,300 股（約 3,522.33 萬股）", rendered)
            self.assertIn("8,776,917,438 元（約 87.77 億元）", rendered)
            self.assertIn("30,653 筆", rendered)
            self.assertNotIn("file://", rendered)
            for route in (
                "/launcher.html?stay=1&from=war_brief",
                "/ui/P1008_WARROOM_COMMAND_CENTER_v24.html?from=war_brief",
            ):
                with urllib.request.urlopen(base + route, timeout=5) as response:
                    self.assertEqual(response.status, 200, route)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
        self.assertEqual(sha256(brief_path), before)


if __name__ == "__main__":
    unittest.main()
