"""Phase 2A model registry with production entries intentionally absent."""

from __future__ import annotations

from dataclasses import dataclass


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
