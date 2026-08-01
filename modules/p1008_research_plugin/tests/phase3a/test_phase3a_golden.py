from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
CASE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.capabilities import GovernedCapabilityFramework


class Phase3AGoldenTests(unittest.TestCase):
    def test_registry_and_replay_match_golden_contract(self) -> None:
        framework = GovernedCapabilityFramework(PACKAGE_ROOT)
        expected = json.loads(
            (CASE_ROOT / "registry_expected.json").read_text(encoding="utf-8")
        )
        registry = framework.registry.snapshot()
        compact = {
            "enabled": registry["enabled"],
            "disabled": registry["disabled"],
            "states": {
                item["capability_id"]: item["lifecycle_state"]
                for item in registry["capabilities"]
            },
            "production_enablement_allowed": registry[
                "production_enablement_allowed"
            ],
            "runtime_integration_authorized": registry[
                "runtime_integration_authorized"
            ],
            "actionable": registry["actionable"],
        }
        self.assertEqual(compact, expected)
        events = json.loads(
            (CASE_ROOT / "replay_events.json").read_text(encoding="utf-8")
        )
        replay = framework.replay.replay(events)
        self.assertEqual(replay["event_count"], 8)
        self.assertEqual(replay["states"], expected["states"])


if __name__ == "__main__":
    unittest.main()
