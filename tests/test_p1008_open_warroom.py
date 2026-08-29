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
    @staticmethod
    def _page_ok_responses(
        *,
        server_version: str = p1008_app_server.SERVER_VERSION,
        git_head: str = "A" * 40,
        package_root: Path = ROOT,
        sandboxed: bool = False,
        source_manifest_version: str = "P1008_NEWS_SCAN_SOURCE_MANIFEST_v2",
    ) -> list[_Response]:
        return [
            _Response("text/html; charset=utf-8"),
            _Response("text/markdown; charset=utf-8"),
            _Response(
                "application/json; charset=utf-8",
                {
                    "serverVersion": server_version,
                    "gitHead": git_head,
                    "resolvedPackageRoot": str(package_root),
                    "serverContext": {"codexNetworkSandbox": sandboxed},
                    "sourceManifest": {
                        "version": source_manifest_version,
                        "networkSummary": {},
                    },
                },
            ),
            _Response("application/json; charset=utf-8"),
        ]

    def test_cmd_uses_only_bundled_python_312_with_dependency_preflight(self) -> None:
        source = (TOOLS / "p1008_open_warroom.cmd").read_text(encoding="utf-8")
        lowered = source.lower()
        self.assertIn(
            r"%userprofile%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
            lowered,
        )
        self.assertIn("sys.version_info[:2] == (3, 12)", source)
        self.assertIn("pydantic", source)
        self.assertIn(r"sys.path.insert(0, r'%ROOT%\tools')", source)
        self.assertIn("import p1008_app_server", source)
        self.assertNotIn("runpy.run_path", source)
        self.assertNotIn("where.exe", lowered)
        self.assertNotIn("py -3", lowered)
        self.assertNotIn("pythoncore-3.14", lowered)
        self.assertNotIn("set \"python_exe=\"", lowered)
        self.assertNotIn("if not defined python_exe", lowered)

    def test_dependency_preflight_uses_supported_tools_import_context(self) -> None:
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys, pydantic; "
                    f"sys.path.insert(0, {str(TOOLS)!r}); "
                    "import p1008_app_server"
                ),
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_previous_runpy_root_context_is_not_the_supported_import_context(self) -> None:
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import runpy; "
                    f"runpy.run_path({str(TOOLS / 'p1008_app_server.py')!r}, "
                    "run_name='p1008_launcher_preflight')"
                ),
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("owner_publish_csv_v2", completed.stderr)

    def test_launcher_expected_version_matches_app_server(self) -> None:
        self.assertEqual(
            p1008_open_warroom.EXPECTED_SERVER_VERSION,
            p1008_app_server.SERVER_VERSION,
        )

    def test_page_ok_accepts_current_server_contract(self) -> None:
        responses = self._page_ok_responses()
        with patch("p1008_open_warroom.urllib.request.urlopen", side_effect=responses) as mocked:
            self.assertTrue(p1008_open_warroom.page_ok(8768))
        self.assertEqual(mocked.call_count, 4)

    def test_page_ok_default_timeout_covers_measured_healthy_local_api_latency(self) -> None:
        responses = iter(self._page_ok_responses())
        required_latency = {
            "/api/p1008/status": 0.86,
            "/api/p1008/review-package": 0.79,
        }
        observed_timeouts: list[float] = []

        def latency_aware_urlopen(url: str, *, timeout: float) -> _Response:
            observed_timeouts.append(timeout)
            required = next(
                (latency for suffix, latency in required_latency.items() if url.endswith(suffix)),
                0.0,
            )
            if timeout < required:
                raise TimeoutError(f"probe budget {timeout} is below required latency {required}")
            return next(responses)

        with patch(
            "p1008_open_warroom.urllib.request.urlopen",
            side_effect=latency_aware_urlopen,
        ):
            self.assertTrue(p1008_open_warroom.page_ok(8768))
        self.assertEqual(p1008_open_warroom.DEFAULT_PAGE_PROBE_TIMEOUT, 2.0)
        self.assertEqual(observed_timeouts, [2.0, 2.0, 2.0, 2.0])

    def test_page_ok_preserves_strict_server_contract_rejections(self) -> None:
        valid_head = "A" * 40
        cases = {
            "wrong_server_version": {
                "responses": self._page_ok_responses(server_version="WRONG"),
                "kwargs": {},
            },
            "wrong_git_head": {
                "responses": self._page_ok_responses(git_head="B" * 40),
                "kwargs": {"expected_git_head": valid_head},
            },
            "wrong_package_root": {
                "responses": self._page_ok_responses(package_root=ROOT / "wrong"),
                "kwargs": {"expected_package_root": ROOT},
            },
            "wrong_source_manifest": {
                "responses": self._page_ok_responses(source_manifest_version="WRONG"),
                "kwargs": {},
            },
            "codex_sandbox": {
                "responses": self._page_ok_responses(sandboxed=True),
                "kwargs": {"reject_codex_network_sandbox": True},
            },
        }
        for name, case in cases.items():
            with self.subTest(name=name):
                with patch(
                    "p1008_open_warroom.urllib.request.urlopen",
                    side_effect=case["responses"],
                ):
                    self.assertFalse(p1008_open_warroom.page_ok(8768, **case["kwargs"]))

        missing_review = [
            *self._page_ok_responses()[:3],
            TimeoutError("review package unavailable"),
        ]
        with patch(
            "p1008_open_warroom.urllib.request.urlopen",
            side_effect=missing_review,
        ):
            self.assertFalse(p1008_open_warroom.page_ok(8768))

    def test_page_ok_still_fails_closed_beyond_governed_timeout(self) -> None:
        observed_timeout: list[float] = []

        def unresponsive_urlopen(_url: str, *, timeout: float) -> _Response:
            observed_timeout.append(timeout)
            raise TimeoutError("endpoint exceeded governed timeout")

        with patch(
            "p1008_open_warroom.urllib.request.urlopen",
            side_effect=unresponsive_urlopen,
        ):
            self.assertFalse(p1008_open_warroom.page_ok(8768))
        self.assertEqual(observed_timeout, [2.0])


if __name__ == "__main__":
    unittest.main()
