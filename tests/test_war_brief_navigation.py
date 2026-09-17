from __future__ import annotations

import hashlib
import http.server
import json
import sys
import threading
import unittest
import urllib.request
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "tools"))

import p1008_app_server as app_server  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class WarBriefNavigationTests(unittest.TestCase):
    def test_current_brief_uses_existing_local_server_routes(self) -> None:
        brief_path = PACKAGE_ROOT / "reports/generated/latest_report.html"
        brief_json_path = PACKAGE_ROOT / "runtime/current_warroom_brief.json"
        if not brief_path.is_file() or not brief_json_path.is_file():
            self.skipTest("governed current war-brief fixture is unavailable")
        brief = json.loads(brief_json_path.read_text(encoding="utf-8"))
        market_activity = brief["marketBaseline"]["marketActivity"]
        volume = Decimal(str(market_activity["tradeVolume"]))
        value = Decimal(str(market_activity["tradeValue"]))
        transactions = int(market_activity["transactionCount"])
        expected_volume = (
            f"{int(volume):,} 股（約 "
            f"{(volume / Decimal('10000')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f} 萬股）"
        )
        expected_value = (
            f"{int(value):,} 元（約 "
            f"{(value / Decimal('100000000')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f} 億元）"
        )
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
            self.assertIn(expected_volume, rendered)
            self.assertIn(expected_value, rendered)
            self.assertIn(f"{transactions:,} 筆", rendered)
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
