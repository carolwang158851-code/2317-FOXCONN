"""Load and enforce Phase 3A lifecycle policies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CapabilityPolicyError(RuntimeError):
    """Raised when a lifecycle action is not authorized."""


class CapabilityPolicy:
    def __init__(self, config_root: Path) -> None:
        self.config_root = config_root.resolve()
        self.lifecycle = self._load("capability_lifecycle_policy.json")
        self.health = self._load("capability_health_policy.json")
        self.compatibility = self._load("capability_compatibility_policy.json")
        self.retirement = self._load("capability_retirement_policy.json")
        if self.lifecycle.get("production_state_defined") is not False:
            raise CapabilityPolicyError("Production lifecycle state is forbidden")

    def _load(self, name: str) -> dict[str, Any]:
        value = json.loads((self.config_root / name).read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict) or value.get("actionable") is not False:
            raise CapabilityPolicyError(f"Invalid capability policy: {name}")
        return value

    def transition(self, current: str, event: str, owner_reference: str | None) -> str:
        if event in self.lifecycle["forbidden_events"]:
            raise CapabilityPolicyError(f"Forbidden lifecycle event: {event}")
        matches = [
            item
            for item in self.lifecycle["transitions"]
            if item["from"] == current and item["event"] == event
        ]
        if len(matches) != 1:
            raise CapabilityPolicyError(f"Invalid transition: {current} + {event}")
        transition = matches[0]
        if transition["owner_approval_required"] and not owner_reference:
            raise CapabilityPolicyError("Owner approval reference is required")
        return transition["to"]
