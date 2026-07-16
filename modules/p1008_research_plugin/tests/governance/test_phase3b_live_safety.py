from __future__ import annotations

import asyncio
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


MODULE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
FIXTURE_PATH = MODULE_ROOT / "tests" / "fixtures" / "phase3b" / "plugin_packets.json"
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.openai.model_registry import ModelDefinition
from p1008_research_plugin.openai.tool_registry import ToolRegistry
from p1008_research_plugin.plugin_module.agent_runner import (
    AGENT_RUN_MAX_TURNS,
    OPENAI_CLIENT_MAX_RETRIES,
    RESPONSES_MAX_TOOL_CALLS,
    AgentRunner,
    DeterministicMockClient,
    LiveAgentsSdkClient,
    deterministic_synthesis,
)
from p1008_research_plugin.plugin_module.baseline_reader import BaselineReader
from p1008_research_plugin.plugin_module.contracts import ExecutionStep
from p1008_research_plugin.plugin_module.packet_gateway import PacketGateway
from p1008_research_plugin.plugin_module.router import PluginRouter
from p1008_research_plugin.runtime.runtime_config import (
    PHASE3B_LIVE_MODEL_ID,
    RuntimeConfig,
    RuntimeConfigurationError,
)


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


class Phase3BLiveSafetyTests(unittest.TestCase):
    def test_live_model_is_fixed_without_reading_credentials(self) -> None:
        config = RuntimeConfig.phase3b_shadow(live=True)
        with mock.patch.object(RuntimeConfig, "api_key_available", return_value=True):
            with mock.patch.object(
                RuntimeConfig, "configured_model", return_value="unapproved-model"
            ):
                with self.assertRaises(RuntimeConfigurationError):
                    config.require_live_credentials()
            with mock.patch.object(
                RuntimeConfig, "configured_model", return_value=PHASE3B_LIVE_MODEL_ID
            ):
                self.assertEqual(
                    config.require_live_credentials(), PHASE3B_LIVE_MODEL_ID
                )

    def test_live_client_wires_zero_retry_one_turn_and_one_tool_call(self) -> None:
        baseline, validated, plan = monthly_inputs()
        capture: dict[str, object] = {}

        class FakeAsyncOpenAI:
            def __init__(self, **kwargs):
                capture["client_kwargs"] = kwargs

        class FakeRetrySettings:
            def __init__(self, **kwargs):
                self.max_retries = kwargs["max_retries"]

        class FakeModelSettings:
            def __init__(self, **kwargs):
                capture["model_settings_kwargs"] = kwargs

        class FakeProvider:
            def __init__(self, **kwargs):
                capture["provider_kwargs"] = kwargs

        class FakeRunConfig:
            def __init__(self, **kwargs):
                capture["run_config"] = self
                capture["run_config_kwargs"] = kwargs

        class FakeAgent:
            def __init__(self, **kwargs):
                capture["agent_kwargs"] = kwargs

        class FakeRunner:
            @staticmethod
            def run_sync(*args, **kwargs):
                capture["runner_args"] = args
                capture["runner_kwargs"] = kwargs
                usage = types.SimpleNamespace(input_tokens=11, output_tokens=7)
                return types.SimpleNamespace(
                    final_output=deterministic_synthesis(validated),
                    context_wrapper=types.SimpleNamespace(usage=usage),
                    last_response_id="resp_offline_trace",
                )

        agents_module = types.SimpleNamespace(
            Agent=FakeAgent,
            Runner=FakeRunner,
            ModelSettings=FakeModelSettings,
            ModelRetrySettings=FakeRetrySettings,
            OpenAIProvider=FakeProvider,
            RunConfig=FakeRunConfig,
        )
        openai_module = types.SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI)

        def module(name: str):
            return agents_module if name == "agents" else openai_module

        client = LiveAgentsSdkClient(
            config=RuntimeConfig.phase3b_shadow(live=True),
            model=ModelDefinition(
                model_id=PHASE3B_LIVE_MODEL_ID,
                provider="OPENAI_AGENTS_SDK",
                enabled=True,
                network_required=True,
            ),
            prompt_path=(
                MODULE_ROOT
                / "src"
                / "p1008_research_plugin"
                / "prompts"
                / "phase3b_financial_brief.md"
            ),
            tool_registry=mock.create_autospec(ToolRegistry, instance=True),
        )
        client.tool_registry.build_hosted_web_search.return_value = object()
        with mock.patch.object(
            RuntimeConfig,
            "require_live_credentials",
            return_value=PHASE3B_LIVE_MODEL_ID,
        ):
            with mock.patch(
                "p1008_research_plugin.plugin_module.agent_runner.importlib.import_module",
                side_effect=module,
            ):
                synthesis, usage = client.synthesize(
                    baseline=baseline,
                    validated=validated,
                    plan=plan,
                )

        self.assertEqual(
            capture["client_kwargs"], {"max_retries": OPENAI_CLIENT_MAX_RETRIES}
        )
        model_settings = capture["model_settings_kwargs"]
        self.assertFalse(model_settings["parallel_tool_calls"])
        self.assertEqual(
            model_settings["extra_args"],
            {"max_tool_calls": RESPONSES_MAX_TOOL_CALLS},
        )
        self.assertEqual(
            model_settings["retry"].max_retries,
            OPENAI_CLIENT_MAX_RETRIES,
        )
        self.assertTrue(capture["provider_kwargs"]["use_responses"])
        self.assertTrue(capture["run_config_kwargs"]["tracing_disabled"])
        self.assertEqual(capture["runner_kwargs"]["max_turns"], AGENT_RUN_MAX_TURNS)
        self.assertIs(
            capture["runner_kwargs"]["run_config"],
            capture["run_config"],
        )
        self.assertEqual(client.synthesis_calls, 1)
        self.assertEqual(client.provider_response_id, "resp_offline_trace")
        self.assertEqual(usage.total_tokens, 18)
        self.assertEqual(synthesis, deterministic_synthesis(validated))

    def test_sdk_provider_request_contains_hard_tool_call_limit(self) -> None:
        from agents import ModelSettings, WebSearchTool
        from agents.models.interface import ModelTracing
        from agents.models.openai_responses import OpenAIResponsesModel
        from openai.types.responses import Response

        captured: dict[str, object] = {}

        class Responses:
            async def create(self, **kwargs):
                captured.update(kwargs)
                return Response.model_validate(
                    {
                        "id": "resp_offline",
                        "created_at": 0.0,
                        "model": PHASE3B_LIVE_MODEL_ID,
                        "object": "response",
                        "output": [
                            {
                                "id": "msg_offline",
                                "type": "message",
                                "role": "assistant",
                                "status": "completed",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "offline",
                                        "annotations": [],
                                    }
                                ],
                            }
                        ],
                        "parallel_tool_calls": False,
                        "tool_choice": "auto",
                        "tools": [],
                        "status": "completed",
                    }
                )

        fake_client = types.SimpleNamespace(
            base_url="https://api.openai.com/v1",
            responses=Responses(),
        )

        async def request():
            model = OpenAIResponsesModel(PHASE3B_LIVE_MODEL_ID, fake_client)
            return await model.get_response(
                None,
                "offline",
                ModelSettings(
                    parallel_tool_calls=False,
                    extra_args={"max_tool_calls": RESPONSES_MAX_TOOL_CALLS},
                ),
                [WebSearchTool()],
                None,
                [],
                ModelTracing.DISABLED,
            )

        asyncio.run(request())
        self.assertEqual(captured["max_tool_calls"], RESPONSES_MAX_TOOL_CALLS)
        self.assertFalse(captured["parallel_tool_calls"])
        self.assertEqual(captured["model"], PHASE3B_LIVE_MODEL_ID)
        self.assertEqual(captured["tools"][0]["type"], "web_search")

    def test_client_error_is_not_retried(self) -> None:
        import httpx
        from openai import APIStatusError, AsyncOpenAI

        calls = 0

        def fail_once(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                500,
                json={"error": {"message": "offline failure", "type": "test_error"}},
            )

        async def request():
            transport = httpx.MockTransport(fail_once)
            async with httpx.AsyncClient(transport=transport) as http_client:
                client = AsyncOpenAI(
                    api_key="offline-test-token",
                    max_retries=OPENAI_CLIENT_MAX_RETRIES,
                    http_client=http_client,
                )
                with self.assertRaises(APIStatusError):
                    await client.responses.create(
                        model=PHASE3B_LIVE_MODEL_ID,
                        input="offline",
                        tools=[{"type": "web_search"}],
                        max_tool_calls=RESPONSES_MAX_TOOL_CALLS,
                    )

        asyncio.run(request())
        self.assertEqual(calls, 1)

    def test_runner_stops_before_second_turn(self) -> None:
        from agents import (
            Agent,
            ModelRetrySettings,
            ModelSettings,
            RunConfig,
            Runner,
            WebSearchTool,
        )
        from agents.exceptions import MaxTurnsExceeded
        from agents.models.interface import Model, ModelProvider, ModelResponse
        from agents.usage import Usage
        from openai.types.responses import ResponseFunctionWebSearch

        class OneTurnModel(Model):
            def __init__(self):
                self.calls = 0

            async def get_response(self, *args, **kwargs):
                self.calls += 1
                item = ResponseFunctionWebSearch.model_validate(
                    {
                        "id": "ws_offline",
                        "action": {"type": "search", "query": "offline"},
                        "status": "completed",
                        "type": "web_search_call",
                    }
                )
                return ModelResponse(
                    output=[item],
                    usage=Usage(requests=1),
                    response_id="resp_offline",
                )

            async def stream_response(self, *args, **kwargs):
                if False:
                    yield None

        class Provider(ModelProvider):
            def __init__(self, model):
                self.model = model

            def get_model(self, _model_name):
                return self.model

        model = OneTurnModel()
        agent = Agent(
            name="P1008 Offline Turn Limit",
            model=PHASE3B_LIVE_MODEL_ID,
            tools=[WebSearchTool()],
        )
        with self.assertRaises(MaxTurnsExceeded):
            Runner.run_sync(
                agent,
                "offline",
                max_turns=AGENT_RUN_MAX_TURNS,
                run_config=RunConfig(
                    model_provider=Provider(model),
                    model_settings=ModelSettings(
                        parallel_tool_calls=False,
                        extra_args={"max_tool_calls": RESPONSES_MAX_TOOL_CALLS},
                        retry=ModelRetrySettings(
                            max_retries=OPENAI_CLIENT_MAX_RETRIES
                        ),
                    ),
                    tracing_disabled=True,
                ),
            )
        self.assertEqual(model.calls, 1)

    def test_existing_mock_candidate_remains_non_actionable(self) -> None:
        baseline, validated, plan = monthly_inputs()
        model = ModelDefinition(
            model_id="phase3b-deterministic-mock",
            provider="LOCAL_DETERMINISTIC_MOCK",
            enabled=True,
            network_required=False,
        )
        report = AgentRunner(
            DeterministicMockClient(model.model_id),
            model,
        ).run(
            baseline=baseline,
            validated=validated,
            plan=plan,
        )
        self.assertEqual(plan.calls_for(ExecutionStep.WEB_SEARCH), 1)
        self.assertFalse(plan.actionable)
        self.assertTrue(validated.material_delta)
        self.assertEqual(report.status, "MATERIAL_CHANGE_CANDIDATE")
        self.assertFalse(report.actionable)


if __name__ == "__main__":
    unittest.main()
