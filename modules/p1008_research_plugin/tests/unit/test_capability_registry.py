from __future__ import annotations

import sys
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.openai.model_registry import ModelRegistry, ModelRegistryError
from p1008_research_plugin.openai.tool_registry import ToolRegistry
from p1008_research_plugin.runtime.capability_registry import (
    CapabilityError,
    CapabilityRegistry,
)
from p1008_research_plugin.runtime.runtime_config import (
    RuntimeConfig,
    RuntimeConfigurationError,
)


class CapabilityRegistryTests(unittest.TestCase):
    def test_only_echo_is_enabled(self) -> None:
        registry = CapabilityRegistry()
        self.assertEqual(registry.snapshot()["enabled"], ["echo_research"])
        for capability in registry.DEFERRED:
            with self.assertRaises(CapabilityError):
                registry.require_enabled(capability)

    def test_only_mock_model_is_enabled(self) -> None:
        self.assertEqual(ModelRegistry().resolve("phase2a-mock").provider, "LOCAL_MOCK")
        with self.assertRaises(ModelRegistryError):
            ModelRegistry().resolve("production-model")

    def test_tools_and_production_configuration_are_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            ToolRegistry().register(object())
        for config in (
            RuntimeConfig(openai_enabled=True),
            RuntimeConfig(network_enabled=True),
            RuntimeConfig(production_enabled=True),
            RuntimeConfig(provider_id="production"),
        ):
            with self.assertRaises(RuntimeConfigurationError):
                config.validate()


if __name__ == "__main__":
    unittest.main()
