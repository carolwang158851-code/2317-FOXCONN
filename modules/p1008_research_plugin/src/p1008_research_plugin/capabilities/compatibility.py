"""Evaluate manifest compatibility with the frozen framework policies."""

from __future__ import annotations

from typing import Any

from .manifest import CapabilityManifest
from .policy import CapabilityPolicy
from .versioning import SemanticVersion


class CapabilityCompatibility:
    def __init__(self, policy: CapabilityPolicy) -> None:
        self.policy = policy.compatibility

    def evaluate(self, manifest: CapabilityManifest) -> dict[str, Any]:
        version = SemanticVersion.parse(manifest.version)
        checks = {
            "framework_major": version.compatible_with_framework(
                self.policy["framework_major"]
            ),
            "v1_root": manifest.required_contract_roots["v1"]
            == self.policy["compatible_contract_roots"]["v1"],
            "v2_root": manifest.required_contract_roots["v2"]
            == self.policy["compatible_contract_roots"]["v2"],
            "typed_output": manifest.output_contract == "PHASE2A_TYPED_RESEARCH_OUTPUT",
            "actionable_false": manifest.actionable is False,
        }
        return {
            "capability_id": manifest.capability_id,
            "compatible": all(checks.values()),
            "checks": checks,
            "actionable": False,
        }
