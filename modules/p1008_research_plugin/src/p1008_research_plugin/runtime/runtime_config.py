"""Immutable configuration for the local-only Phase 2A foundation."""

from __future__ import annotations

from dataclasses import dataclass


class RuntimeConfigurationError(RuntimeError):
    """Raised when configuration attempts to enable a deferred capability."""


@dataclass(frozen=True)
class RuntimeConfig:
    phase: str = "PHASE_2A"
    provider_id: str = "phase2a-mock"
    openai_enabled: bool = False
    network_enabled: bool = False
    production_enabled: bool = False
    artifact_mode: str = "MEMORY_ONLY"
    allowed_capabilities: tuple[str, ...] = ("echo_research",)
    actionable: bool = False

    def validate(self) -> None:
        if self.phase != "PHASE_2A":
            raise RuntimeConfigurationError("Only PHASE_2A is authorized")
        if self.provider_id != "phase2a-mock":
            raise RuntimeConfigurationError("Only the Phase 2A mock provider is allowed")
        if self.openai_enabled or self.network_enabled or self.production_enabled:
            raise RuntimeConfigurationError("Production and network runtime are disabled")
        if self.artifact_mode != "MEMORY_ONLY":
            raise RuntimeConfigurationError("Phase 2A artifacts must remain memory-only")
        if self.allowed_capabilities != ("echo_research",):
            raise RuntimeConfigurationError("Only EchoResearchCapability is enabled")
        if self.actionable is not False:
            raise RuntimeConfigurationError("Phase 2A is never actionable")
