"""Deterministic manifest contract validation."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .manifest import CapabilityManifest
from .versioning import SemanticVersion


class CapabilityContractError(RuntimeError):
    """Raised when a capability weakens the Phase 3A contract."""


class CapabilityContractValidator:
    EXPECTED_KEYS = frozenset(
        {
            "capability_id",
            "display_name",
            "version",
            "lifecycle_state",
            "execution_mode",
            "provider_id",
            "implementation_available",
            "enabled",
            "owner_approval_reference",
            "allowed_operations",
            "input_contract",
            "output_contract",
            "required_contract_roots",
            "health_policy_id",
            "compatibility_policy_id",
            "retirement_policy_id",
            "actionable",
        }
    )
    ROOTS = {
        "v1": "3370C4DBD6B564E2200D051AC07C8507442C130ADE64D770621107FA09D2924D",
        "v2": "E056357A8A63A15BCF9FDC286BEE0BDB56E043AF26F4DDCD5624FDB3707BD782",
    }
    STATES = frozenset(
        {
            "DRAFT",
            "REGISTERED_DISABLED",
            "VALIDATED_DISABLED",
            "SHADOW_ENABLED",
            "RETIREMENT_PENDING",
            "RETIRED",
        }
    )

    def validate_mapping(self, value: Mapping[str, Any]) -> CapabilityManifest:
        if set(value) != self.EXPECTED_KEYS:
            raise CapabilityContractError("Manifest fields do not match contract")
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", value["capability_id"]):
            raise CapabilityContractError("Invalid capability id")
        SemanticVersion.parse(value["version"])
        if value["lifecycle_state"] not in self.STATES:
            raise CapabilityContractError("Unknown lifecycle state")
        if value["output_contract"] != "PHASE2A_TYPED_RESEARCH_OUTPUT":
            raise CapabilityContractError("Typed output contract drift")
        if value["required_contract_roots"] != self.ROOTS:
            raise CapabilityContractError("Frozen contract root drift")
        if value["actionable"] is not False:
            raise CapabilityContractError("Capability cannot be actionable")
        if value["lifecycle_state"] == "SHADOW_ENABLED":
            if value["capability_id"] != "echo_research":
                raise CapabilityContractError("Only Echo may be shadow enabled")
            if not (
                value["enabled"] is True
                and value["implementation_available"] is True
                and value["execution_mode"] == "MOCK_SHADOW"
                and value["provider_id"] == "phase2a-mock"
                and value["owner_approval_reference"]
            ):
                raise CapabilityContractError("Echo shadow boundary drift")
        elif value["lifecycle_state"] in {
            "REGISTERED_DISABLED",
            "VALIDATED_DISABLED",
            "RETIREMENT_PENDING",
            "RETIRED",
        }:
            if (
                value["enabled"] is not False
                or value["execution_mode"] != "DISABLED"
                or value["provider_id"] is not None
                or value["allowed_operations"]
            ):
                raise CapabilityContractError("Disabled capability exposes execution")
        return CapabilityManifest.from_mapping(value)
