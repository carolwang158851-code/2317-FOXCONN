"""Pure in-memory lifecycle events and transition application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .policy import CapabilityPolicy


@dataclass(frozen=True)
class CapabilityLifecycleEvent:
    sequence: int
    capability_id: str
    event_type: str
    owner_approval_reference: str | None = None
    actionable: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "CapabilityLifecycleEvent":
        allowed = {
            "sequence",
            "capability_id",
            "event_type",
            "owner_approval_reference",
            "actionable",
        }
        if set(value) != allowed or value.get("actionable") is not False:
            raise ValueError("Lifecycle event shape is invalid")
        return cls(**value)


class CapabilityLifecycle:
    def __init__(self, policy: CapabilityPolicy) -> None:
        self.policy = policy

    def apply(self, current: str, event: CapabilityLifecycleEvent) -> str:
        if event.sequence < 1 or event.actionable is not False:
            raise ValueError("Lifecycle event boundary is invalid")
        return self.policy.transition(
            current,
            event.event_type,
            event.owner_approval_reference,
        )
