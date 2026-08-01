from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
CASE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.capabilities import GovernedCapabilityFramework
from p1008_research_plugin.capabilities.replay import CapabilityReplayError


class LifecycleReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.framework = GovernedCapabilityFramework(PACKAGE_ROOT)
        self.events = json.loads(
            (CASE_ROOT / "replay_events.json").read_text(encoding="utf-8")
        )

    def test_replay_is_deterministic_and_non_persistent(self) -> None:
        first = self.framework.replay.replay(self.events)
        second = self.framework.replay.replay(self.events)
        self.assertEqual(first, second)
        self.assertEqual(first["states"]["echo_research"], "SHADOW_ENABLED")
        self.assertFalse(first["state_changed_outside_projection"])
        self.assertFalse(first["actionable"])

    def test_sequence_gap_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.events)
        invalid[2]["sequence"] = 9
        with self.assertRaises(CapabilityReplayError):
            self.framework.replay.replay(invalid)


if __name__ == "__main__":
    unittest.main()
