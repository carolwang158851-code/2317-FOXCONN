from __future__ import annotations

import functools
import hashlib
import http.client
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "tools"))
import p1008_app_server as app  # noqa: E402
import p1008_open_warroom as launcher  # noqa: E402


class MissingStagingReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("P1008_TEST_TEMP_ROOT"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager = app.P1008JobManager(self.root)

    def assert_error(self, review, message):
        self.assertEqual(review, {
            "status": "ERROR", "error": message, "candidateDate": "",
            "stagingDate": "", "generatedFiles": [], "candidatePending": False,
            "readiness": {"allowed": False, "score": 0,
                          "threshold": app.owner_publish.MIN_PUBLISH_SCORE,
                          "blockers": [message], "candidateDiagnostics": [], "warningsZh": []},
            "formalPublishAllowed": False, "formalPublishRequired": False,
            "formalPublishBlocked": True, "actionable": False,
        })

    def empty_staging(self):
        (self.root / "staging").mkdir()

    def dated_fixture(self, content, date="2026-09-24"):
        # Test-only input, never written to production or worktree staging.
        directory = self.root / "staging" / date
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "DRY_RUN.json").write_text(content, encoding="utf-8")
        return directory

    def identities(self):
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob("*") if p.is_file()}

    def test_missing_staging_review(self):
        self.empty_staging()
        self.assert_error(self.manager.review_package(), "No staging/<date>/DRY_RUN.json was found.")

    def test_missing_staging_status(self):
        self.empty_staging()
        status = self.manager.snapshot()
        self.assertEqual(status["status"], "IDLE")
        self.assert_error(status["reviewPackage"], "No staging/<date>/DRY_RUN.json was found.")
        self.assertFalse(status["launcherGate"]["canEnterNewUi"])

    def test_no_staging_directory_preserves_existing_error(self):
        review = self.manager.review_package()
        self.assertEqual(review["status"], "ERROR")
        self.assertIn("staging", review["error"])
        self.assertFalse(review["formalPublishAllowed"])
        self.assertFalse((self.root / "staging").exists())

    def test_missing_dated_dry_run_uses_existing_contract(self):
        (self.root / "staging" / "2026-09-24").mkdir(parents=True)
        message = "DRY_RUN not found for staging date 2026-09-24."
        self.assert_error(self.manager.review_package(), message)
        self.assert_error(self.manager.review_package("2026-09-24"), message)

    def test_absent_current_dry_run_does_not_carry_forward_older_candidate(self):
        self.dated_fixture('{"candidateDate":"2026-09-23","generatedFiles":[]}', "2026-09-23")
        (self.root / "staging" / "2026-09-24").mkdir()
        with mock.patch.object(app.owner_publish, "build_publish_readiness") as readiness:
            self.assert_error(self.manager.review_package(), "DRY_RUN not found for staging date 2026-09-24.")
            readiness.assert_not_called()

    def test_valid_staging_regression(self):
        self.dated_fixture('{"candidateDate":"2026-09-24","generatedFiles":[],"noPublishRequired":true}')
        before = self.identities()
        review = self.manager.review_package()
        self.assertEqual(review["status"], "READY")
        self.assertEqual(review["stagingDate"], "2026-09-24")
        self.assertEqual(review["candidateDate"], "2026-09-24")
        self.assertEqual(review["generatedFiles"], [])
        self.assertTrue(review["readiness"]["noActionRequired"])
        self.assertFalse(review["formalPublishAllowed"])
        self.assertFalse(review["formalPublishRequired"])
        self.assertEqual(self.manager.snapshot()["reviewPackage"], review)
        self.assertEqual(self.identities(), before)

    def test_malformed_dry_run_remains_existing_error(self):
        self.dated_fixture("{not-json")
        before = self.identities()
        review = self.manager.review_package()
        self.assertEqual(review["status"], "ERROR")
        self.assertIn("Expecting property name", review["error"])
        self.assertFalse(review["readiness"]["allowed"])
        self.assertTrue(review["formalPublishBlocked"])
        self.assertNotIn("No staging", review["error"])
        self.assertEqual(self.identities(), before)

    def test_invalid_dry_run_remains_existing_error(self):
        self.dated_fixture("[]")
        review = self.manager.review_package()
        self.assertEqual(review["status"], "ERROR")
        self.assertIn("has no attribute 'get'", review["error"])
        self.assertFalse(review["formalPublishAllowed"])
        self.assertTrue(review["formalPublishBlocked"])

    def test_unrelated_systemexit_is_not_suppressed(self):
        self.empty_staging()
        for code in (7, "Authority hash mismatch", "Publisher failure"):
            with self.subTest(code=code), mock.patch.object(app.owner_publish, "latest_staging_dir", side_effect=SystemExit(code)):
                with self.assertRaises(SystemExit) as caught:
                    self.manager.review_package()
                self.assertEqual(caught.exception.code, code)

    def test_later_fatal_condition_is_not_translated(self):
        self.dated_fixture("{}")
        with mock.patch.object(app.owner_publish, "build_publish_readiness", side_effect=SystemExit("No staging/<date>/DRY_RUN.json was found.")):
            with self.assertRaises(SystemExit):
                self.manager.review_package()

    def test_repeated_reads_deterministic_and_no_writes(self):
        self.empty_staging()
        before = self.identities()
        with mock.patch.object(self.manager, "start_job") as job, \
             mock.patch.object(self.manager, "start_owner_publish") as publish, \
             mock.patch.object(self.manager, "_persist_locked") as persist, \
             mock.patch.object(app.owner_publish, "write_json") as write:
            first = self.manager.snapshot()
            for _ in range(3):
                self.assertEqual(self.manager.snapshot(), first)
                self.assertEqual(self.manager.review_package(), first["reviewPackage"])
            for operation in (job, publish, persist, write):
                operation.assert_not_called()
        self.assertEqual(self.identities(), before)
        self.assertEqual(list(self.root.rglob("DRY_RUN.json")), [])

    def test_http_smoke_missing_staging_and_launcher_health(self):
        self.empty_staging()
        source_manifest = self.root / app.SOURCE_MANIFEST_REL
        source_manifest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PACKAGE_ROOT / app.SOURCE_MANIFEST_REL, source_manifest)
        before = self.identities()
        class Handler(app.P1008AppHandler):
            pass
        Handler.manager = self.manager
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(PACKAGE_ROOT)))
        self.assertNotEqual(server.server_port, 8767)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            payloads = {}
            for _ in range(2):
                for route in ("/", "/launcher.html", "/api/p1008/status", "/api/p1008/review-package"):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
                    try:
                        connection.request("GET", route)
                        response = connection.getresponse()
                        self.assertEqual(response.status, 200)
                        content = response.read()
                        if route.startswith("/api/"):
                            payload = json.loads(content)
                            if route in payloads:
                                self.assertEqual(payload, payloads[route])
                            payloads[route] = payload
                    finally:
                        connection.close()
            self.assertEqual(payloads["/api/p1008/review-package"]["status"], "ERROR")
            self.assertFalse(payloads["/api/p1008/review-package"]["formalPublishAllowed"])
            self.assertTrue(launcher.page_ok(server.server_port, expected_package_root=self.root, expected_git_head=self.manager.git_head))
            print(f"ISOLATED_PORT={server.server_port} DASHBOARD_HTTP=200 STATUS_HTTP=200 REVIEW_HTTP=200 LAUNCHER_PAGE_OK=YES")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.identities(), before)


if __name__ == "__main__":
    unittest.main()
