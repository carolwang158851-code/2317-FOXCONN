"""Facade for the contract-only Phase 3A capability framework."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .compatibility import CapabilityCompatibility
from .conformance import CapabilityConformance
from .health import CapabilityHealthEvaluator
from .lifecycle import CapabilityLifecycle
from .policy import CapabilityPolicy
from .registry import GovernedCapabilityRegistry
from .replay import CapabilityReplay
from .retirement import CapabilityRetirement


class GovernedCapabilityFramework:
    CONFIG_RELATIVE = Path("modules/p1008_research_plugin/config/phase3a")

    def __init__(self, package_root: Path) -> None:
        self.package_root = package_root.resolve()
        self.config_root = (self.package_root / self.CONFIG_RELATIVE).resolve()
        self.registry = GovernedCapabilityRegistry(self.config_root)
        self.policy = CapabilityPolicy(self.config_root)
        self.lifecycle = CapabilityLifecycle(self.policy)
        self.replay = CapabilityReplay(self.lifecycle)
        self.health = CapabilityHealthEvaluator(self.policy)
        self.compatibility = CapabilityCompatibility(self.policy)
        self.retirement = CapabilityRetirement(self.policy)
        self.conformance = CapabilityConformance(
            self.registry, self.compatibility, self.health
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "phase": "PHASE_3A",
            "framework": "GOVERNED_CAPABILITY_FRAMEWORK",
            "registry": self.registry.snapshot(),
            "conformance": self.conformance.evaluate(),
            "runtime_integrated": False,
            "openai_production_enabled": False,
            "state_persisted": False,
            "actionable": False,
        }
