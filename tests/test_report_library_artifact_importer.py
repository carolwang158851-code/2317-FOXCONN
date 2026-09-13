from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import p1008_app_server as app_server  # noqa: E402


class ReportLibraryArtifactImporterTests(unittest.TestCase):
    report_key = "P1008_FY2026_AUGUST_REVENUE"
    revision = 1

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog = {
            "reports": [{"report_key": self.report_key, "revision": self.revision}]
        }
        self.catalog_patch = patch.object(
            app_server.quarterly_editorial,
            "quarterly_editorial_catalog",
            return_value=self.catalog,
        )
        self.catalog_patch.start()

    def tearDown(self) -> None:
        self.catalog_patch.stop()
        self.temp.cleanup()

    def attach(self, name: str, content: bytes) -> dict[str, object]:
        return app_server.import_report_library_artifact(
            self.root,
            selected_report_key=self.report_key,
            selected_revision=self.revision,
            file_name=name,
            content_base64=base64.b64encode(content).decode("ascii"),
        )

    def test_valid_html_artifact_is_attached_for_owner_review_only(self) -> None:
        content = b"<html><body>Owner review</body></html>"
        result = self.attach(f"{self.report_key}.html", content)
        target = self.root / "runtime/report_library_artifacts" / self.report_key / "r1" / f"{self.report_key}.html"
        self.assertEqual(result["status"], "ATTACHED_OWNER_REVIEW_ONLY")
        self.assertEqual(target.read_bytes(), content)
        self.assertFalse(result["publication"])
        self.assertFalse(result["actionable"])
        self.assertFalse(result["coreViewChanged"])
        self.assertFalse(result["authorityModified"])
        self.assertFalse(result["reportTriggerChanged"])
        self.assertFalse((self.root / "data/CSV_AUTHORITY_MANIFEST.json").exists())
        self.assertFalse((self.root / "runtime/warroom_report_manifest.json").exists())

    def test_pdf_artifact_is_accepted(self) -> None:
        result = self.attach(f"{self.report_key}.pdf", b"%PDF-1.7\nowner-review")
        self.assertEqual(result["format"], "PDF")

    def test_actual_v3_report_filename_is_accepted(self) -> None:
        name = "P1008_FY2026_AUGUST_REVENUE_ENTERPRISE_VALUE_WAR_REPORT_OWNER_REVIEW_V3.html"
        result = self.attach(name, b"<html><body>V3</body></html>")
        self.assertEqual(result["fileName"], name)
        self.assertTrue((self.root / "runtime/report_library_artifacts" / self.report_key / "r1" / name).is_file())

    def test_report_key_mismatch_fails_closed_without_attachment(self) -> None:
        with self.assertRaisesRegex(ValueError, "REPORT_ARTIFACT_REPORT_KEY_MISMATCH"):
            self.attach("P1008_FY2026_Q2_EARNINGS.html", b"<html></html>")
        with self.assertRaisesRegex(ValueError, "REPORT_ARTIFACT_REPORT_KEY_MISMATCH"):
            self.attach("P1008_FY2026_AUGUST.html", b"<html></html>")
        self.assertFalse((self.root / "runtime/report_library_artifacts").exists())

    def test_path_traversal_and_malformed_basenames_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "REPORT_ARTIFACT_FILENAME_INVALID"):
            self.attach(f"../{self.report_key}.html", b"<html></html>")
        with self.assertRaisesRegex(ValueError, "REPORT_ARTIFACT_BASENAME_INVALID"):
            self.attach(f"{self.report_key}__V3.html", b"<html></html>")


if __name__ == "__main__":
    unittest.main()
