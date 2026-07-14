"""Execute the governed mock pipeline after contract verification."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from ..openai.model_registry import ModelRegistry
from ..openai.response_adapter import ResponseAdapter
from ..openai.tool_registry import ToolRegistry
from ..validation.boundary_validation import BoundaryValidator
from ..validation.prompt_validation import PromptValidator
from ..validation.schema_validation import SchemaValidator
from .artifact_writer import ArtifactWriter
from .capability_registry import CapabilityRegistry
from .context_builder import ContextBuilder
from .prompt_builder import PromptBuilder
from .runtime_config import RuntimeConfig
from .runtime_health import RuntimeHealth
from .runtime_validator import RuntimeContractVerifier
from .typed_output import TypedResearchArtifact


class RuntimeManager:
    def __init__(self, package_root: Path, config: RuntimeConfig | None = None) -> None:
        from ..openai.client_interface import MockOpenAIClient

        self.package_root = package_root.resolve()
        self.config = config or RuntimeConfig()
        self.config.validate()
        self.capabilities = CapabilityRegistry()
        self.models = ModelRegistry()
        self.tools = ToolRegistry()
        self.prompts = PromptBuilder()
        self.prompt_validator = PromptValidator()
        self.schema_validator = SchemaValidator()
        self.boundary_validator = BoundaryValidator()
        self.response_adapter = ResponseAdapter()
        self.contracts = RuntimeContractVerifier(self.package_root)
        self.artifacts = ArtifactWriter(self.package_root)
        self.health = RuntimeHealth(self.config)
        self.client = MockOpenAIClient(self.capabilities.execute_echo)

    def execute(self, context: Mapping[str, Any]) -> dict[str, Any]:
        contract_state = self.contracts.verify()
        capability = self.capabilities.require_enabled(str(context["capability"]))
        model = self.models.resolve(self.config.provider_id)
        if self.tools.snapshot()["enabled"]:
            raise RuntimeError("Phase 2A tools must remain empty")
        prompt = self.prompts.build(context)
        self.prompt_validator.validate(prompt, context)
        raw = self.client.generate(capability.capability_id, model.model_id, context, prompt)
        adapted = self.response_adapter.adapt(raw)
        validated = self.schema_validator.validate(adapted)
        self.boundary_validator.validate_output(validated)
        artifact = TypedResearchArtifact.from_mapping(validated)
        envelope = self.artifacts.build(artifact)
        return {
            "contracts": contract_state,
            "capability": capability.capability_id,
            "output": artifact.to_dict(),
            "artifact": envelope.metadata(),
            "health": self.health.snapshot(self.client.mock_calls),
            "ledger_changed": False,
            "governance_changed": False,
            "runtime_state_changed": False,
            "actionable": False,
        }

    def execute_plugin_shadow(
        self,
        *,
        run_type: str,
        as_of_date: str,
        packets: Iterable[Mapping[str, Any] | object],
        baseline: Mapping[str, Any] | object | None = None,
        output_root: Path | None = None,
        write_artifacts: bool = True,
    ) -> dict[str, Any]:
        """Run the opt-in manual Shadow path without changing Phase 2A defaults."""

        if self.config.phase != "PHASE_3B_PLUGIN_SHADOW":
            raise RuntimeError("Plugin Module Shadow requires an explicit Phase 3B config")

        # Imported only for the opt-in path so the frozen Phase 2A runtime remains
        # dependency-free and deterministic.
        from ..plugin_module.agent_runner import (
            AgentRunner,
            DeterministicMockClient,
            LiveAgentsSdkClient,
        )
        from ..plugin_module.baseline_reader import BaselineReader
        from ..plugin_module.contracts import BaselineSnapshot
        from ..plugin_module.packet_gateway import PacketGateway
        from ..plugin_module.router import PluginRouter
        from ..plugin_module.shadow_writer import ShadowWriter

        capability = self.capabilities.require_shadow_enabled("financial_brief_shadow")
        gateway = PacketGateway()
        parsed_packets = gateway.parse(packets)
        signals = gateway.aggregate_signals(parsed_packets)
        plan = PluginRouter().route(run_type, signals)
        validated = gateway.validate(plan, parsed_packets, as_of_date)

        reader = BaselineReader(self.package_root)
        if baseline is None:
            baseline_snapshot = reader.read(as_of_date)
        elif isinstance(baseline, BaselineSnapshot):
            baseline_snapshot = baseline
        elif isinstance(baseline, Mapping):
            baseline_snapshot = reader.from_mapping(
                as_of_date,
                baseline.get("data", {}),
                list(baseline.get("source_files", [])),
            )
        else:
            raise RuntimeError("Unsupported Phase 3B baseline input")
        if baseline_snapshot.as_of_date.isoformat() != str(as_of_date):
            raise RuntimeError("Baseline and run as_of_date must match")

        context = ContextBuilder().build_phase3b(
            run_type=plan.run_type.value,
            as_of_date=str(as_of_date),
            baseline_hash=baseline_snapshot.baseline_hash,
            evidence_ids=validated.evidence_ids,
        )
        model = self.models.resolve_phase3b(self.config)
        if self.config.live_openai:
            client = LiveAgentsSdkClient(
                config=self.config,
                model=model,
                prompt_path=(
                    Path(__file__).resolve().parents[1]
                    / "prompts"
                    / "phase3b_financial_brief.md"
                ),
                tool_registry=self.tools,
            )
        else:
            client = DeterministicMockClient(model.model_id)
        report = AgentRunner(client, model).run(
            baseline=baseline_snapshot,
            validated=validated,
            plan=plan,
        )

        artifact = {
            "persisted": False,
            "formal_state_changed": False,
            "actionable": False,
        }
        if write_artifacts:
            artifact = ShadowWriter(output_root or self.package_root).write(report)
        return {
            "context": context,
            "capability": capability.capability_id,
            "route": plan,
            "report": report,
            "artifact": artifact,
            "model": {
                "provider": model.provider,
                "model_id": model.model_id,
                "network_required": model.network_required,
            },
            "tools": self.tools.phase3b_snapshot(),
            "synthesis_calls": client.synthesis_calls,
            "scheduled": False,
            "formal_csv_changed": False,
            "runtime_sqlite_changed": False,
            "rules_changed": False,
            "hold_changed": False,
            "midr_changed": False,
            "actionable": False,
        }
