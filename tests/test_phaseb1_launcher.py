from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TOOLS = PACKAGE_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import p1008_build_report  # noqa: E402


class PhaseB1LauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = (PACKAGE_ROOT / "tools" / "p1008_app_server.py").read_text(encoding="utf-8")
        cls.launcher = (PACKAGE_ROOT / "launcher.html").read_text(encoding="utf-8")

    def test_manual_analysis_and_report_routes_exist(self) -> None:
        self.assertIn('/api/p1008/run/analysis-candidate', self.server)
        self.assertIn('/api/p1008/run/report-candidate', self.server)
        self.assertIn('id="run-analysis-candidate"', self.launcher)
        self.assertIn('id="run-report-candidate"', self.launcher)

    def test_default_flow_does_not_invoke_phaseb1_builders(self) -> None:
        match = re.search(
            r'def _run_job_inner\(self, job_type: str\).*?if job_type in \{"default", "update-data"\}:',
            self.server,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        first_default_block = self.server[
            self.server.index('if job_type in {"default", "update-data"}:') :
            self.server.index(
                'if job_type in {"default", "news-scan"} and not component_failures:'
            )
        ]
        self.assertIn("and not component_failures", self.server)
        self.assertNotIn("P1008_BUILD_ANALYSIS.bat", first_default_block)
        self.assertNotIn("P1008_BUILD_REPORT.bat", first_default_block)

    def test_bat_wrappers_are_business_rule_free_and_bundled_python_only(self) -> None:
        for name in ("P1008_BUILD_ANALYSIS.bat", "P1008_BUILD_REPORT.bat"):
            text = (PACKAGE_ROOT / name).read_text(encoding="utf-8")
            self.assertIn("codex-primary-runtime", text)
            self.assertIn("Python 3.12", text)
            self.assertNotIn("System Python", text)
            self.assertNotIn("OPENAI_API_KEY", text)

    def test_launcher_displays_run_id_and_output_path(self) -> None:
        self.assertIn('id="phaseb1-run-id"', self.launcher)
        self.assertIn('id="phaseb1-output"', self.launcher)
        self.assertIn("不會自動產生日報", self.launcher)

    def test_quarterly_report_candidate_routes_to_enterprise_value_runtime(self) -> None:
        self.assertEqual(
            p1008_build_report._report_runtime("QUARTERLY_EARNINGS"),
            "ENTERPRISE_VALUE_WAR_REPORT_V1",
        )
        self.assertEqual(
            p1008_build_report._report_runtime("MONTHLY_REVENUE"),
            "PHASE_B1_LEGACY",
        )
        pipeline = (
            PACKAGE_ROOT
            / "modules"
            / "p1008_research_plugin"
            / "src"
            / "p1008_research_plugin"
            / "phaseb1_pipeline.py"
        ).read_text(encoding="utf-8")
        self.assertIn("compile_existing_phaseb1_result", pipeline)
        self.assertIn('"reportChapterCount": 11', pipeline)


if __name__ == "__main__":
    unittest.main()
