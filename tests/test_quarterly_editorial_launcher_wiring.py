from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class QuarterlyEditorialLauncherWiringTests(unittest.TestCase):
    def test_launcher_exposes_one_generic_import_apply_and_history_surface(self):
        body = (ROOT / "launcher.html").read_text(encoding="utf-8")
        panel = body.split('id="quarterly-editorial-panel"', 1)[1].split('</section>', 1)[0]
        self.assertEqual(body.count('id="import-editorial"'), 1)
        self.assertEqual(body.count('id="apply-editorial"'), 1)
        self.assertIn("匯入潤稿版", panel)
        self.assertIn("套用潤稿版", panel)
        self.assertIn("版本歷史", panel)
        self.assertNotIn("P1008_FY2026_Q2_EARNINGS", panel)
        self.assertIn("/api/p1008/quarterly-editorial/import", body)
        self.assertIn("/api/p1008/quarterly-editorial/apply", body)

    def test_server_routes_are_whitelisted_and_report_cards_embed_versions(self):
        server = (ROOT / "tools" / "p1008_app_server.py").read_text(encoding="utf-8")
        reports = (ROOT / "reports.html").read_text(encoding="utf-8")
        for route in ("catalog", "history", "import", "apply"):
            self.assertIn(f'/api/p1008/quarterly-editorial/{route}', server)
        self.assertIn("EDITORIAL_SELECTED_REPORT_IDENTITY_MISMATCH", server)
        self.assertIn("selectedReportKey", server)
        self.assertIn("currentEditorialVersion", reports)
        self.assertIn("editorialHistoryLocator", reports)
        self.assertIn("版本歷史｜", reports)


if __name__ == "__main__":
    unittest.main()
