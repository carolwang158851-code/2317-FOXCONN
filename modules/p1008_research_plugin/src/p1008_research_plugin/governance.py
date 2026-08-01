"""Deterministic governance boundaries for the Phase 1B skeleton."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .contract_loader import ContractLoader


class GovernanceError(RuntimeError):
    """Raised when an operation would cross a frozen governance boundary."""


class GovernanceBoundary:
    def __init__(self, loader: ContractLoader) -> None:
        self.loader = loader
        self.policy = loader.load_json("policies/plugin_policy.json")
        self.gate_schema = loader.load_json("schemas/gate_result.schema.json")
        self.gate_types = frozenset(
            self.gate_schema["properties"]["gate_type"]["enum"]
        )
        self._assert_frozen_boundaries()

    def _assert_frozen_boundaries(self) -> None:
        expected = {
            "noAutoTrade": True,
            "noFormalCsvWrite": True,
            "noRuleEnablement": True,
            "canModifyRuntimeSqlite": False,
            "canChangeMidr": False,
            "canChangeHold": False,
            "canPublish": False,
            "actionable": False,
        }
        for key, required in expected.items():
            if self.policy.get(key) is not required:
                raise GovernanceError(f"Frozen governance boundary changed: {key}")

    def require_gate_type(self, gate_type: str) -> None:
        if gate_type not in self.gate_types:
            raise GovernanceError(f"Unregistered deterministic gate: {gate_type}")

    def gate_result(
        self,
        gate_id: str,
        gate_type: str,
        result: str,
        reason_codes: list[str] | None = None,
        violations: list[str] | None = None,
    ) -> dict[str, Any]:
        self.require_gate_type(gate_type)
        allowed_results = self.gate_schema["properties"]["result"]["enum"]
        if result not in allowed_results:
            raise GovernanceError(f"Invalid gate result: {result}")
        payload = {
            "gate_id": gate_id,
            "gate_type": gate_type,
            "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "result": result,
            "reason_codes": sorted(set(reason_codes or [])),
            "violations": list(violations or []),
            "owner_review_required": result == "OWNER_REVIEW_REQUIRED",
            "effective_change_applied": False,
            "actionable": False,
        }
        return payload

    def reject_capability(self, capability: str) -> None:
        normalized = capability.strip().upper()
        forbidden = set(self.policy.get("forbiddenCapabilities", []))
        if normalized in forbidden or normalized.startswith("OPENAI"):
            raise GovernanceError(f"Forbidden capability: {capability}")

    @staticmethod
    def assert_phase1b_status(payload: dict[str, Any]) -> None:
        if payload.get("openai_enabled") is not False:
            raise GovernanceError("OpenAI runtime must remain disabled in Phase 1B")
        if payload.get("actionable") is not False:
            raise GovernanceError("Phase 1B output cannot be actionable")
        if payload.get("implementation_status") != "SKELETON":
            raise GovernanceError("Phase 1B implementation status must be SKELETON")
