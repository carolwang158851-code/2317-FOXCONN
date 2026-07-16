from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID


MODULE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
FIXTURE_PATH = MODULE_ROOT / "tests" / "fixtures" / "phase3b" / "plugin_packets.json"
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.openai.model_registry import ModelDefinition
from p1008_research_plugin.plugin_module.agent_runner import (
    AgentRunner,
    DeterministicMockClient,
    deterministic_synthesis,
)
from p1008_research_plugin.plugin_module.baseline_reader import BaselineReader
from p1008_research_plugin.plugin_module.contracts import TokenUsage
from p1008_research_plugin.plugin_module.packet_gateway import PacketGateway
from p1008_research_plugin.plugin_module.router import PluginRouter
from p1008_research_plugin.plugin_module.shadow_writer import ShadowWriteError, ShadowWriter


def monthly_inputs():
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    case = payload["cases"]["monthly_revenue"]
    gateway = PacketGateway()
    packets = gateway.parse(case["packets"])
    plan = PluginRouter().route(case["run_type"], gateway.aggregate_signals(packets))
    validated = gateway.validate(plan, packets, payload["as_of_date"])
    baseline = BaselineReader.from_mapping(
        payload["as_of_date"],
        payload["baseline"]["data"],
        payload["baseline"]["source_files"],
    )
    return baseline, validated, plan


def load_periodic_report_module():
    path = PACKAGE_ROOT / "tools" / "warroom_periodic_report_v1.py"
    spec = importlib.util.spec_from_file_location("phase3b_identity_periodic", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load periodic report module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OfflineLiveClient:
    mode = "AGENTS_SDK"

    def __init__(self, response_id: str) -> None:
        self.synthesis_calls = 0
        self.provider_response_id = response_id

    def synthesize(self, *, baseline, validated, plan):
        self.synthesis_calls += 1
        synthesis = deterministic_synthesis(validated)
        return synthesis, TokenUsage(
            source="AGENTS_SDK",
            model_id="gpt-5.6-sol",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )


class Phase3BRunIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline, self.validated, self.plan = monthly_inputs()
        self.mock_model = ModelDefinition(
            model_id="phase3b-deterministic-mock",
            provider="LOCAL_DETERMINISTIC_MOCK",
            enabled=True,
            network_required=False,
        )
        self.live_model = ModelDefinition(
            model_id="gpt-5.6-sol",
            provider="OPENAI_AGENTS_SDK",
            enabled=True,
            network_required=True,
        )

    def mock_report(self):
        return AgentRunner(
            DeterministicMockClient(self.mock_model.model_id), self.mock_model
        ).run(baseline=self.baseline, validated=self.validated, plan=self.plan)

    def live_report(self, uuid_hex: str):
        return AgentRunner(
            OfflineLiveClient("resp_offline_trace"),
            self.live_model,
            utc_now=lambda: datetime(2026, 7, 15, 13, 31, 31, 750216, tzinfo=timezone.utc),
            uuid_factory=lambda: UUID(hex=uuid_hex),
        ).run(baseline=self.baseline, validated=self.validated, plan=self.plan)

    def test_same_mock_inputs_produce_same_mode_qualified_run_id(self) -> None:
        first = self.mock_report()
        second = self.mock_report()
        self.assertEqual(first.run_id, second.run_id)
        self.assertIn("-MOCK-", first.run_id)
        self.assertEqual(first.execution_mode, "MOCK")
        self.assertIsNone(first.executed_at_utc)
        self.assertIsNone(first.provider_response_id)

    def test_mock_and_live_ids_cannot_collide(self) -> None:
        mock_report = self.mock_report()
        live_report = self.live_report("11111111111111111111111111111111")
        self.assertNotEqual(mock_report.run_id, live_report.run_id)
        self.assertIn("-MOCK-", mock_report.run_id)
        self.assertIn("-LIVE-", live_report.run_id)

    def test_consecutive_live_ids_are_unique_without_external_service(self) -> None:
        first = self.live_report("11111111111111111111111111111111")
        second = self.live_report("22222222222222222222222222222222")
        self.assertNotEqual(first.run_id, second.run_id)
        self.assertTrue(first.run_id.endswith("-11111111"))
        self.assertTrue(second.run_id.endswith("-22222222"))
        self.assertEqual(first.provider_response_id, "resp_offline_trace")
        self.assertEqual(first.executed_at_utc.tzinfo, timezone.utc)

    def test_existing_run_artifact_is_never_overwritten(self) -> None:
        report = self.mock_report()
        with tempfile.TemporaryDirectory(prefix="p1008-p3b-identity-") as temp_dir:
            writer = ShadowWriter(Path(temp_dir))
            artifact = writer.write(report)
            run_path = Path(temp_dir) / artifact["run"]
            original = run_path.read_bytes()
            with self.assertRaises(ShadowWriteError):
                writer.write(report)
            self.assertEqual(run_path.read_bytes(), original)

    def test_periodic_reader_accepts_mode_qualified_candidate(self) -> None:
        report = self.mock_report()
        with tempfile.TemporaryDirectory(prefix="p1008-p3b-periodic-") as temp_dir:
            writer = ShadowWriter(Path(temp_dir))
            writer.write(report)
            periodic = load_periodic_report_module()
            candidate = periodic.read_shadow_candidate(
                Path(temp_dir), self.baseline.as_of_date.isoformat()
            )
            self.assertIsNotNone(candidate)
            markdown = periodic.append_shadow_candidate("# Existing\n", candidate)
            self.assertIn(report.run_id, markdown)
            self.assertIn("`MOCK`", markdown)

    def test_mock_and_live_candidates_remain_non_actionable(self) -> None:
        mock_report = self.mock_report()
        live_report = self.live_report("33333333333333333333333333333333")
        self.assertFalse(mock_report.actionable)
        self.assertFalse(live_report.actionable)
        self.assertTrue(mock_report.manual_shadow)
        self.assertTrue(live_report.manual_shadow)


if __name__ == "__main__":
    unittest.main()
