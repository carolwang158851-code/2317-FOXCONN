"""Model registry for Phase 2A mock and opt-in Phase 3B Shadow execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..runtime.runtime_config import RuntimeConfig


class ModelRegistryError(RuntimeError):
    """Raised when a non-mock model is requested."""


@dataclass(frozen=True)
class ModelDefinition:
    model_id: str
    provider: str
    enabled: bool
    network_required: bool


class ModelRegistry:
    def __init__(self) -> None:
        self._models = {
            "phase2a-mock": ModelDefinition(
                model_id="phase2a-mock",
                provider="LOCAL_MOCK",
                enabled=True,
                network_required=False,
            )
        }

    def resolve(self, model_id: str) -> ModelDefinition:
        model = self._models.get(model_id)
        if model is None or not model.enabled or model.network_required:
            raise ModelRegistryError("Production model runtime is disabled")
        return model

    def resolve_phase3b(self, config: "RuntimeConfig") -> ModelDefinition:
        if config.phase != "PHASE_3B_PLUGIN_SHADOW":
            raise ModelRegistryError("Phase 3B model requested outside the Shadow runtime")
        if not config.live_openai:
            return ModelDefinition(
                model_id="phase3b-deterministic-mock",
                provider="LOCAL_DETERMINISTIC_MOCK",
                enabled=True,
                network_required=False,
            )
        model_id = config.require_live_credentials()
        return ModelDefinition(
            model_id=model_id,
            provider="OPENAI_AGENTS_SDK",
            enabled=True,
            network_required=True,
        )
