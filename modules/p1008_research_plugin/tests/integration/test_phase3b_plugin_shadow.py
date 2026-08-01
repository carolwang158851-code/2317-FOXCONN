from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
FIXTURE_PATH = MODULE_ROOT / "tests" / "fixtures" / "phase3b" / "plugin_packets.json"
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.plugin_module.contracts import ExecutionStep
from p1008_research_plugin.plugin_module.baseline_reader import BaselineReader
from p1008_research_plugin.runtime.runtime_config import RuntimeConfig
from p1008_research_plugin.runtime.runtime_manager import RuntimeManager


def load_fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def load_periodic_report_module():
    path = PACKAGE_ROOT / "tools" / "warroom_periodic_report_v1.py"
    spec = importlib.util.spec_from_file_location("phase3b_periodic_report", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load periodic report module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Phase3BPluginShadowIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = load_fixture()
        self.as_of_date = str(self.fixture["as_of_date"])
        self.baseline = self.fixture["baseline"]

    def run_case(
        self, case_name: str, output_root: Path, *, write_artifacts: bool = True
    ) -> dict[str, object]:
        case = self.fixture["cases"][case_name]
        manager = RuntimeManager(PACKAGE_ROOT, RuntimeConfig.phase3b_shadow())
        return manager.execute_plugin_shadow(
            run_type=case["run_type"],
            as_of_date=self.as_of_date,
            packets=case["packets"],
            baseline=self.baseline,
            output_root=output_root,
            write_artifacts=write_artifacts,
        )

    def test_no_material_change_writes_candidate_without_synthesis(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p1008-p3b-no-delta-") as temp_dir:
            result = self.run_case("no_material_daily", Path(temp_dir))
            report = result["report"]
            self.assertTrue(report.no_material_change)
            self.assertEqual(report.status, "NO_MATERIAL_CHANGE")
            self.assertEqual(report.synthesis_count, 0)
            self.assertEqual(result["synthesis_calls"], 0)
            self.assertEqual(report.changed_fields, [])
            self.assertEqual(report.evidence_ids, [])
            self.assertFalse(report.actionable)
            latest = Path(temp_dir) / result["artifact"]["latest"]
            self.assertTrue(latest.is_file())

    def test_formal_war_room_baseline_is_read_only_and_hash_stable(self) -> None:
        first = BaselineReader(PACKAGE_ROOT).read(self.as_of_date)
        second = BaselineReader(PACKAGE_ROOT).read(self.as_of_date)
        self.assertEqual(first, second)
        self.assertEqual(len(first.baseline_hash), 64)
        self.assertEqual(
            set(first.data),
            {"revenue", "EPS", "margins", "valuation", "fx_impact", "baseline_dates"},
        )

    def test_all_deterministic_fixtures_pass_as_a_mock_smoke(self) -> None:
        expected_synthesis = {
            "no_material_daily": 0,
            "daily_numeric_anomaly": 1,
            "monthly_revenue": 1,
            "quarterly_earnings": 1,
            "major_event_financial": 1,
        }
        with tempfile.TemporaryDirectory(prefix="p1008-p3b-smoke-") as temp_dir:
            for case_name, expected_calls in expected_synthesis.items():
                with self.subTest(case=case_name):
                    result = self.run_case(
                        case_name,
                        Path(temp_dir) / case_name,
                    )
                    report = result["report"]
                    self.assertEqual(result["synthesis_calls"], expected_calls)
                    self.assertEqual(report.synthesis_count, expected_calls)
                    self.assertLessEqual(report.synthesis_count, 1)
                    self.assertFalse(report.actionable)
                    self.assertTrue(report.manual_shadow)
                    self.assertFalse(result["scheduled"])
                    self.assertFalse(result["formal_csv_changed"])
                    self.assertEqual(
                        next(
                            item.call_count
                            for item in report.tool_usage
                            if item.tool is ExecutionStep.CANVA
                        ),
                        0,
                    )

    def test_material_fixture_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p1008-p3b-replay-") as temp_dir:
            first = self.run_case("monthly_revenue", Path(temp_dir) / "first")["report"]
            second = self.run_case("monthly_revenue", Path(temp_dir) / "second")["report"]
            first_json = json.dumps(
                first.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            second_json = json.dumps(
                second.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            self.assertEqual(first_json, second_json)
            self.assertEqual(first.synthesis_count, 1)
            self.assertEqual(set(first.changed_fields), {"revenue"})

    def test_periodic_report_reads_and_separates_shadow_candidate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p1008-p3b-periodic-") as temp_dir:
            result = self.run_case("monthly_revenue", Path(temp_dir))
            periodic = load_periodic_report_module()
            candidate = periodic.read_shadow_candidate(Path(temp_dir), self.as_of_date)
            self.assertIsNotNone(candidate)
            markdown = periodic.append_shadow_candidate("# Existing periodic report\n", candidate)
            self.assertIn("### 戰情室基線", markdown)
            self.assertIn("### 本次新增證據", markdown)
            self.assertIn("### 對投資判讀的影響", markdown)
            self.assertIn(result["report"].run_id, markdown)


if __name__ == "__main__":
    unittest.main()
