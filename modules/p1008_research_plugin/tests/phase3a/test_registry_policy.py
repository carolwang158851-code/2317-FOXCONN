from __future__ import annotations

import sys
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = MODULE_ROOT / "config" / "phase3a"
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.capabilities.policy import (
    CapabilityPolicy,
    CapabilityPolicyError,
)
from p1008_research_plugin.capabilities.registry import (
    CapabilityRegistryError,
    GovernedCapabilityRegistry,
)


class RegistryPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = GovernedCapabilityRegistry(CONFIG_ROOT)
        self.policy = CapabilityPolicy(CONFIG_ROOT)

    def test_registry_is_deny_by_default(self) -> None:
        self.assertEqual(self.registry.snapshot()["enabled"], ["echo_research"])
        self.assertEqual(self.registry.require_shadow_enabled("echo_research").provider_id, "phase2a-mock")
        for capability in ("financial", "macro", "news", "deep_research", "foreign_flow"):
            with self.assertRaises(CapabilityRegistryError):
                self.registry.require_shadow_enabled(capability)
        with self.assertRaises(CapabilityRegistryError):
            self.registry.get("unknown")

    def test_shadow_enable_requires_owner_reference(self) -> None:
        with self.assertRaises(CapabilityPolicyError):
            self.policy.transition(
                "VALIDATED_DISABLED", "CAPABILITY_SHADOW_ENABLED", None
            )
        self.assertEqual(
            self.policy.transition(
                "VALIDATED_DISABLED", "CAPABILITY_SHADOW_ENABLED", "OWNER-REF"
            ),
            "SHADOW_ENABLED",
        )

    def test_production_event_is_forbidden(self) -> None:
        with self.assertRaises(CapabilityPolicyError):
            self.policy.transition(
                "SHADOW_ENABLED", "CAPABILITY_PRODUCTION_ENABLED", "OWNER-REF"
            )


if __name__ == "__main__":
    unittest.main()
