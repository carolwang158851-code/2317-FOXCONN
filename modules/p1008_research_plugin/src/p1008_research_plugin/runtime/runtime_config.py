"""Immutable configuration for the local-only Phase 2A foundation."""

from __future__ import annotations

import os
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
    live_openai: bool = False
    manual_shadow: bool = False
    actionable: bool = False

    @classmethod
    def phase3b_shadow(cls, *, live: bool = False) -> "RuntimeConfig":
        return cls(
            phase="PHASE_3B_PLUGIN_SHADOW",
            provider_id="phase3b-agents-sdk" if live else "phase3b-deterministic-mock",
            openai_enabled=live,
            network_enabled=live,
            production_enabled=False,
            artifact_mode="SHADOW_JSON",
            allowed_capabilities=("financial_brief_shadow",),
            live_openai=live,
            manual_shadow=True,
            actionable=False,
        )

    @staticmethod
    def _api_key_env_name() -> str:
        return "_".join(("OPENAI", "API", "KEY"))

    def configured_model(self) -> str:
        return str(os.getenv("P1008_OPENAI_MODEL", "")).strip()

    def api_key_available(self) -> bool:
        return bool(str(os.getenv(self._api_key_env_name(), "")).strip())

    def require_live_credentials(self) -> str:
        if not self.live_openai:
            raise RuntimeConfigurationError("Live credentials requested for a mock Shadow run")
        if not self.api_key_available():
            raise RuntimeConfigurationError("Live Shadow is closed: OpenAI API key is unavailable")
        model_id = self.configured_model()
        if not model_id:
            raise RuntimeConfigurationError("Live Shadow is closed: P1008_OPENAI_MODEL is unavailable")
        return model_id

    def validate(self) -> None:
        if self.phase == "PHASE_2A":
            if self.provider_id != "phase2a-mock":
                raise RuntimeConfigurationError("Only the Phase 2A mock provider is allowed")
            if self.openai_enabled or self.network_enabled or self.production_enabled:
                raise RuntimeConfigurationError("Production and network runtime are disabled")
            if self.artifact_mode != "MEMORY_ONLY":
                raise RuntimeConfigurationError("Phase 2A artifacts must remain memory-only")
            if self.allowed_capabilities != ("echo_research",):
                raise RuntimeConfigurationError("Only EchoResearchCapability is enabled")
            if self.live_openai or self.manual_shadow:
                raise RuntimeConfigurationError("Phase 2A cannot enable the Shadow runtime")
        elif self.phase == "PHASE_3B_PLUGIN_SHADOW":
            expected_provider = (
                "phase3b-agents-sdk" if self.live_openai else "phase3b-deterministic-mock"
            )
            if self.provider_id != expected_provider:
                raise RuntimeConfigurationError("Phase 3B provider does not match execution mode")
            if self.openai_enabled is not self.live_openai:
                raise RuntimeConfigurationError("OpenAI enablement does not match execution mode")
            if self.network_enabled is not self.live_openai:
                raise RuntimeConfigurationError("Network enablement does not match execution mode")
            if self.production_enabled:
                raise RuntimeConfigurationError("Phase 3B Shadow cannot enable production")
            if self.artifact_mode != "SHADOW_JSON" or not self.manual_shadow:
                raise RuntimeConfigurationError("Phase 3B must remain manual Shadow JSON")
            if self.allowed_capabilities != ("financial_brief_shadow",):
                raise RuntimeConfigurationError("Only Financial Brief Shadow is allowed")
        else:
            raise RuntimeConfigurationError("Unknown governed runtime phase")
        if self.actionable is not False:
            raise RuntimeConfigurationError("Governed research output is never actionable")
