from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import p1008_app_server
import p1008_open_warroom


class _Response:
    def __init__(self, content_type: str, payload: dict | None = None) -> None:
        self.status = 200
        self.headers = {"Content-Type": content_type}
        self._body = json.dumps(payload or {}).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class OpenWarroomTests(unittest.TestCase):
    def test_launcher_expected_version_matches_app_server(self) -> None:
        self.assertEqual(
            p1008_open_warroom.EXPECTED_SERVER_VERSION,
            p1008_app_server.SERVER_VERSION,
        )

    def test_page_ok_accepts_current_server_contract(self) -> None:
        responses = [
            _Response("text/html; charset=utf-8"),
            _Response("text/markdown; charset=utf-8"),
            _Response(
                "application/json; charset=utf-8",
                {
                    "serverVersion": p1008_app_server.SERVER_VERSION,
                    "serverContext": {"codexNetworkSandbox": False},
                    "sourceManifest": {
                        "version": "P1008_NEWS_SCAN_SOURCE_MANIFEST_v2",
                        "networkSummary": {},
                    },
                },
            ),
            _Response("application/json; charset=utf-8"),
        ]
        with patch("p1008_open_warroom.urllib.request.urlopen", side_effect=responses) as mocked:
            self.assertTrue(p1008_open_warroom.page_ok(8768))
        self.assertEqual(mocked.call_count, 4)


if __name__ == "__main__":
    unittest.main()
