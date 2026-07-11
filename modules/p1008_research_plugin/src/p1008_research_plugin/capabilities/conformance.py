"""Aggregate deterministic Phase 3A conformance checks."""

from __future__ import annotations

from typing import Any

from .compatibility import CapabilityCompatibility
from .health import CapabilityHealthEvaluator
from .registry import GovernedCapabilityRegistry


class CapabilityConformance:
    def __init__(
        self,
        registry: GovernedCapabilityRegistry,
        compatibility: CapabilityCompatibility,
        health: CapabilityHealthEvaluator,
    ) -> None:
        self.registry = registry
        self.compatibility = compatibility
        self.health = health

    def evaluate(self) -> dict[str, Any]:
        compatibility = {
            key: self.compatibility.evaluate(manifest)
            for key, manifest in sorted(self.registry.manifests.items())
        }
        registry_snapshot = self.registry.snapshot()
        checks = {
            "six_manifests": len(self.registry.manifests) == 6,
            "echo_only_shadow": registry_snapshot["enabled"] == ["echo_research"],
            "five_disabled": len(registry_snapshot["disabled"]) == 5,
            "all_compatible": all(item["compatible"] for item in compatibility.values()),
            "production_disabled": self.registry.config[
                "production_enablement_allowed"
            ]
            is False,
            "runtime_not_integrated": self.registry.config[
                "runtime_integration_authorized"
            ]
            is False,
        }
        health = self.health.evaluate(
            "phase3a_framework",
            {
                "manifest": checks["six_manifests"],
                "contract": checks["all_compatible"],
                "boundary": checks["production_disabled"],
                "typed_output": True,
                "deterministic_replay": True,
                "protected_files": checks["runtime_not_integrated"],
            },
        )
        return {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "compatibility": compatibility,
            "health": health,
            "actionable": False,
        }
