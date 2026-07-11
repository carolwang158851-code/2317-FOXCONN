"""Execute the governed mock pipeline after contract verification."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..openai.client_interface import MockOpenAIClient
from ..openai.model_registry import ModelRegistry
from ..openai.response_adapter import ResponseAdapter
from ..openai.tool_registry import ToolRegistry
from ..validation.boundary_validation import BoundaryValidator
from ..validation.prompt_validation import PromptValidator
from ..validation.schema_validation import SchemaValidator
from .artifact_writer import ArtifactWriter
from .capability_registry import CapabilityRegistry
from .prompt_builder import PromptBuilder
from .runtime_config import RuntimeConfig
from .runtime_health import RuntimeHealth
from .runtime_validator import RuntimeContractVerifier
from .typed_output import TypedResearchArtifact


class RuntimeManager:
    def __init__(self, package_root: Path, config: RuntimeConfig | None = None) -> None:
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
