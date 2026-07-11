"""Typed immutable view of one capability manifest."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class CapabilityManifest:
    capability_id: str
    display_name: str
    version: str
    lifecycle_state: str
    execution_mode: str
    provider_id: str | None
    implementation_available: bool
    enabled: bool
    owner_approval_reference: str | None
    allowed_operations: tuple[str, ...]
    input_contract: str
    output_contract: str
    required_contract_roots: Mapping[str, str]
    health_policy_id: str
    compatibility_policy_id: str
    retirement_policy_id: str
    actionable: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CapabilityManifest":
        return cls(
            capability_id=value["capability_id"],
            display_name=value["display_name"],
            version=value["version"],
            lifecycle_state=value["lifecycle_state"],
            execution_mode=value["execution_mode"],
            provider_id=value["provider_id"],
            implementation_available=value["implementation_available"],
            enabled=value["enabled"],
            owner_approval_reference=value["owner_approval_reference"],
            allowed_operations=tuple(value["allowed_operations"]),
            input_contract=value["input_contract"],
            output_contract=value["output_contract"],
            required_contract_roots=MappingProxyType(dict(value["required_contract_roots"])),
            health_policy_id=value["health_policy_id"],
            compatibility_policy_id=value["compatibility_policy_id"],
            retirement_policy_id=value["retirement_policy_id"],
            actionable=value["actionable"],
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "display_name": self.display_name,
            "version": self.version,
            "lifecycle_state": self.lifecycle_state,
            "execution_mode": self.execution_mode,
            "provider_id": self.provider_id,
            "implementation_available": self.implementation_available,
            "enabled": self.enabled,
            "owner_approval_reference": self.owner_approval_reference,
            "allowed_operations": list(self.allowed_operations),
            "input_contract": self.input_contract,
            "output_contract": self.output_contract,
            "required_contract_roots": dict(self.required_contract_roots),
            "health_policy_id": self.health_policy_id,
            "compatibility_policy_id": self.compatibility_policy_id,
            "retirement_policy_id": self.retirement_policy_id,
            "actionable": False,
        }
