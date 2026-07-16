from __future__ import annotations

import copy
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError


MODULE_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = MODULE_ROOT / "tests" / "fixtures" / "phase3b" / "plugin_packets.json"
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.openai.model_registry import ModelDefinition
from p1008_research_plugin.plugin_module.agent_runner import (
    AgentRunner,
    DeterministicMockClient,
    deterministic_synthesis,
)
from p1008_research_plugin.plugin_module.baseline_reader import BaselineReader
from p1008_research_plugin.plugin_module.contracts import (
    HostedWebSearchTrace,
    ProviderCitation,
    TokenUsage,
)
from p1008_research_plugin.plugin_module.packet_gateway import (
    PacketGateway,
    PacketValidationError,
)
from p1008_research_plugin.plugin_module.router import PluginRouter


OFFICIAL_HON_HAI_URL = "https://www.honhai.com/en-us/investor-relations/monthly-revenues"
OFFICIAL_MOPS_URL = "https://mops.twse.com.tw/mops/web/t05st10_ifrs"


def fixture_payload() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def official_monthly_packets() -> list[dict[str, object]]:
    payload = fixture_payload()
    packets = copy.deepcopy(payload["cases"]["monthly_revenue"]["packets"])
    for packet in packets:
        for item in packet["evidence"]:
            item["data_quality_notes"] = ["Validated against a cited official release."]
            for locator in item["source_locators"]:
                locator["source_tier"] = "OFFICIAL_REGULATORY_OR_COMPANY_RELEASE"
                locator["locator"] = (
                    OFFICIAL_HON_HAI_URL
                    if packet["plugin"] == "WEB_SEARCH"
                    else OFFICIAL_MOPS_URL
                )
    return packets


def monthly_inputs(packets: list[dict[str, object]]):
    payload = fixture_payload()
    gateway = PacketGateway()
    parsed = gateway.parse(packets)
    plan = PluginRouter().route(
        payload["cases"]["monthly_revenue"]["run_type"],
        gateway.aggregate_signals(parsed),
    )
    validated = gateway.validate(plan, parsed, payload["as_of_date"])
    baseline = BaselineReader.from_mapping(
        payload["as_of_date"],
        payload["baseline"]["data"],
        payload["baseline"]["source_files"],
    )
    return baseline, validated, plan


class OfflineLiveClient:
    mode = "AGENTS_SDK"

    def __init__(self, *, include_citation: bool = True) -> None:
        self.synthesis_calls = 0
        self.provider_response_id = "resp_offline_real_evidence"
        self.provider_request_ids = ["req_offline_real_evidence"]
        self.hosted_web_search_trace = [
            HostedWebSearchTrace(
                call_id="ws_offline_real_evidence",
                status="completed",
                action_type="search",
                queries=["Hon Hai monthly revenue"],
                source_urls=[OFFICIAL_HON_HAI_URL],
            )
        ]
        self.provider_citations = (
            [ProviderCitation(url=OFFICIAL_HON_HAI_URL, title="Hon Hai monthly revenue")]
            if include_citation
            else []
        )

    def synthesize(self, *, baseline, validated, plan):
        self.synthesis_calls += 1
        return deterministic_synthesis(validated), TokenUsage(
            source="AGENTS_SDK",
            model_id="gpt-5.6-sol",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )


class Phase3BRealEvidenceGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = fixture_payload()
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

    def test_fixture_evidence_fails_closed_before_live_synthesis(self) -> None:
        packets = copy.deepcopy(self.payload["cases"]["monthly_revenue"]["packets"])
        baseline, validated, plan = monthly_inputs(packets)
        client = OfflineLiveClient()
        with self.assertRaises(PacketValidationError):
            AgentRunner(client, self.live_model).run(
                baseline=baseline, validated=validated, plan=plan
            )
        self.assertEqual(client.synthesis_calls, 0)

    def test_example_invalid_fails_closed_in_live_mode(self) -> None:
        packets = official_monthly_packets()
        packets[0]["evidence"][0]["source_locators"][0]["locator"] = (
            "https://example.invalid/monthly-revenue"
        )
        _baseline, validated, plan = monthly_inputs(packets)
        with self.assertRaises(PacketValidationError):
            PacketGateway.validate_live_evidence(plan, validated)

    def test_mock_mode_still_accepts_deterministic_fixtures(self) -> None:
        packets = copy.deepcopy(self.payload["cases"]["monthly_revenue"]["packets"])
        baseline, validated, plan = monthly_inputs(packets)
        report = AgentRunner(
            DeterministicMockClient(self.mock_model.model_id), self.mock_model
        ).run(baseline=baseline, validated=validated, plan=plan)
        self.assertEqual(report.execution_mode, "MOCK")
        self.assertFalse(report.actionable)

    def test_official_https_monthly_revenue_locators_pass(self) -> None:
        _baseline, validated, plan = monthly_inputs(official_monthly_packets())
        PacketGateway.validate_live_evidence(plan, validated)

    def test_supplemental_https_source_cannot_replace_monthly_official_source(self) -> None:
        packets = official_monthly_packets()
        packets[1]["evidence"][0]["source_locators"][0]["locator"] = (
            "https://www.reuters.com/technology/contract-manufacturing-background"
        )
        _baseline, validated, plan = monthly_inputs(packets)
        with self.assertRaises(PacketValidationError):
            PacketGateway.validate_live_evidence(plan, validated)

    def test_missing_source_locator_or_provider_citation_fails_closed(self) -> None:
        missing_locator = official_monthly_packets()
        missing_locator[0]["evidence"][0]["source_locators"] = []
        with self.assertRaises(PacketValidationError):
            monthly_inputs(missing_locator)

        baseline, validated, plan = monthly_inputs(official_monthly_packets())
        with self.assertRaises(ValidationError):
            AgentRunner(
                OfflineLiveClient(include_citation=False),
                self.live_model,
                utc_now=lambda: datetime(2026, 7, 16, tzinfo=timezone.utc),
                uuid_factory=lambda: UUID("11111111-1111-1111-1111-111111111111"),
            ).run(baseline=baseline, validated=validated, plan=plan)

    def test_live_candidate_keeps_provider_trace_and_is_non_actionable(self) -> None:
        baseline, validated, plan = monthly_inputs(official_monthly_packets())
        report = AgentRunner(
            OfflineLiveClient(),
            self.live_model,
            utc_now=lambda: datetime(2026, 7, 16, tzinfo=timezone.utc),
            uuid_factory=lambda: UUID("22222222-2222-2222-2222-222222222222"),
        ).run(baseline=baseline, validated=validated, plan=plan)
        self.assertEqual(report.execution_mode, "LIVE")
        self.assertEqual(report.provider_response_id, "resp_offline_real_evidence")
        self.assertEqual(report.hosted_web_search_call_count, 1)
        self.assertEqual(len(report.hosted_web_search_trace), 1)
        self.assertEqual(len(report.provider_citations), 1)
        self.assertFalse(report.actionable)


if __name__ == "__main__":
    unittest.main()
