from __future__ import annotations

import hashlib
import http.server
import io
import sys
import threading
import unittest
import urllib.request
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "tools"))

import p1008_app_server as app_server  # noqa: E402


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


class Q2OwnerReviewExportTests(unittest.TestCase):
    def test_current_q2_r1_export_contains_only_validated_existing_artifacts(self) -> None:
        body, filename = app_server.build_q2_owner_review_export(PACKAGE_ROOT)
        self.assertEqual(filename, "P1008_FY2026_Q2_EARNINGS_r1_OWNER_REVIEW.zip")
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            names = set(archive.namelist())
            self.assertEqual(
                names,
                app_server.Q2_OWNER_REVIEW_ARTIFACTS
                | app_server.Q2_OWNER_REVIEW_MANIFESTS,
            )
            for relative in names:
                self.assertEqual(archive.read(relative), (PACKAGE_ROOT / relative).read_bytes())

    def test_export_is_deterministic_and_launcher_exposes_one_action(self) -> None:
        first, _ = app_server.build_q2_owner_review_export(PACKAGE_ROOT)
        second, _ = app_server.build_q2_owner_review_export(PACKAGE_ROOT)
        self.assertEqual(sha256(first), sha256(second))
        launcher = (PACKAGE_ROOT / "launcher.html").read_text(encoding="utf-8")
        self.assertEqual(launcher.count("匯出 Q2 審查包"), 1)
        self.assertIn('href="/api/p1008/export/q2-owner-review"', launcher)

    def test_export_route_downloads_governed_zip(self) -> None:
        class Handler(app_server.P1008AppHandler):
            pass

        Handler.manager = SimpleNamespace(package_root=PACKAGE_ROOT)
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            lambda *args, **kwargs: Handler(*args, directory=str(PACKAGE_ROOT), **kwargs),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_port}{app_server.Q2_OWNER_REVIEW_EXPORT_ROUTE}",
                timeout=5,
            ) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), "application/zip")
                self.assertIn("P1008_FY2026_Q2_EARNINGS_r1_OWNER_REVIEW.zip", response.headers["Content-Disposition"])
                body = response.read()
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    app_server.Q2_OWNER_REVIEW_ARTIFACTS
                    | app_server.Q2_OWNER_REVIEW_MANIFESTS,
                )
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    def test_tampered_artifact_fails_closed(self) -> None:
        forged = mock.Mock()
        forged.hexdigest.return_value = "0" * 64
        with mock.patch.object(app_server.hashlib, "sha256", return_value=forged):
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                app_server.build_q2_owner_review_export(PACKAGE_ROOT)


if __name__ == "__main__":
    unittest.main()
