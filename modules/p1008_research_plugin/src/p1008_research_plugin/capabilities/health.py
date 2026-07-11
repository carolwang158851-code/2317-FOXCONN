"""Deterministic capability health evaluation."""

from __future__ import annotations

from typing import Any, Mapping

from .policy import CapabilityPolicy


class CapabilityHealthError(RuntimeError):
    """Raised when health evidence is incomplete."""


class CapabilityHealthEvaluator:
    def __init__(self, policy: CapabilityPolicy) -> None:
        self.required = tuple(policy.health["required_checks"])

    def evaluate(self, capability_id: str, checks: Mapping[str, bool]) -> dict[str, Any]:
        if set(checks) != set(self.required) or not all(
            isinstance(value, bool) for value in checks.values()
        ):
            raise CapabilityHealthError("Health checks do not match policy")
        score = round(sum(1 for value in checks.values() if value) * 100 / len(checks))
        state = "HEALTHY" if score == 100 else "DEGRADED" if score >= 80 else "BLOCKED"
        return {
            "capability_id": capability_id,
            "checks": {key: checks[key] for key in sorted(checks)},
            "score": score,
            "state": state,
            "production_health_claim": False,
            "actionable": False,
        }
