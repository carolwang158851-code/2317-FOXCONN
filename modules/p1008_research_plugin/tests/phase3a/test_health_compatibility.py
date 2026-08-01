from __future__ import annotations

import sys
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.capabilities import GovernedCapabilityFramework
from p1008_research_plugin.capabilities.health import CapabilityHealthError


class HealthCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.framework = GovernedCapabilityFramework(PACKAGE_ROOT)

    def test_all_manifests_are_framework_compatible(self) -> None:
        for manifest in self.framework.registry.manifests.values():
            with self.subTest(capability=manifest.capability_id):
                report = self.framework.compatibility.evaluate(manifest)
                self.assertTrue(report["compatible"])
                self.assertFalse(report["actionable"])

    def test_health_requires_complete_boolean_evidence(self) -> None:
        checks = {key: True for key in self.framework.health.required}
        report = self.framework.health.evaluate("echo_research", checks)
        self.assertEqual(report["state"], "HEALTHY")
        self.assertEqual(report["score"], 100)
        with self.assertRaises(CapabilityHealthError):
            self.framework.health.evaluate("echo_research", {"manifest": True})

    def test_retirement_is_review_candidate_without_state_change(self) -> None:
        manifest = self.framework.registry.get("financial")
        proposal = self.framework.retirement.propose(manifest, "superseded contract")
        self.assertTrue(proposal["owner_review_required"])
        self.assertFalse(proposal["manifest_delete_allowed"])
        self.assertFalse(proposal["history_delete_allowed"])
        self.assertFalse(proposal["state_changed"])
        self.assertFalse(proposal["actionable"])


if __name__ == "__main__":
    unittest.main()
