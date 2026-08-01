from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
CONFIG_ROOT = MODULE_ROOT / "config" / "phase3a"
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.capabilities.contract import (
    CapabilityContractError,
    CapabilityContractValidator,
)
from p1008_research_plugin.capabilities.registry import GovernedCapabilityRegistry


class ManifestContractTests(unittest.TestCase):
    def test_all_six_manifests_pass_strict_contract(self) -> None:
        registry = GovernedCapabilityRegistry(CONFIG_ROOT)
        self.assertEqual(len(registry.manifests), 6)
        self.assertTrue(all(item.actionable is False for item in registry.manifests.values()))

    def test_actionable_and_disabled_execution_drift_are_rejected(self) -> None:
        source = json.loads(
            (CONFIG_ROOT / "manifests" / "financial.json").read_text(encoding="utf-8")
        )
        actionable = copy.deepcopy(source)
        actionable["actionable"] = True
        with self.assertRaises(CapabilityContractError):
            CapabilityContractValidator().validate_mapping(actionable)
        enabled = copy.deepcopy(source)
        enabled["enabled"] = True
        with self.assertRaises(CapabilityContractError):
            CapabilityContractValidator().validate_mapping(enabled)

    def test_unknown_manifest_field_is_rejected(self) -> None:
        source = json.loads(
            (CONFIG_ROOT / "manifests" / "echo_research.json").read_text(
                encoding="utf-8"
            )
        )
        source["recommendation"] = None
        with self.assertRaises(CapabilityContractError):
            CapabilityContractValidator().validate_mapping(source)


if __name__ == "__main__":
    unittest.main()
