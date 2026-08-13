from __future__ import annotations

import json
import os
import subprocess
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
    def test_cmd_uses_only_bundled_python_312_with_dependency_preflight(self) -> None:
        source = (TOOLS / "p1008_open_warroom.cmd").read_text(encoding="utf-8")
        lowered = source.lower()
        self.assertIn(
            r"%userprofile%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
            lowered,
        )
        self.assertIn("sys.version_info[:2] == (3, 12)", source)
        self.assertIn("import pydantic", source)
        self.assertIn("p1008_app_server.py", source)
        self.assertNotIn("where.exe", lowered)
        self.assertNotIn("py -3", lowered)
        self.assertNotIn("pythoncore-3.14", lowered)
        self.assertNotIn("set \"python_exe=\"", lowered)
        self.assertNotIn("if not defined python_exe", lowered)

    def test_bundled_python_preflight_is_312_and_imports_pydantic(self) -> None:
        executable = (
            Path.home()
            / ".cache"
            / "codex-runtimes"
            / "codex-primary-runtime"
            / "dependencies"
            / "python"
            / "python.exe"
        )
        if os.name != "nt":
            self.assertFalse(executable.exists())
            return
        completed = subprocess.run(
            [
                str(executable),
                "-c",
                (
                    "import sys, pydantic; "
                    "assert sys.version_info[:2] == (3, 12); "
                    "print(sys.version.split()[0]); print(pydantic.__version__)"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

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
