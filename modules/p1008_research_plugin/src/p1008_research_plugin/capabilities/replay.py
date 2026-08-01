"""Deterministically replay capability lifecycle events without persistence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from .lifecycle import CapabilityLifecycle, CapabilityLifecycleEvent


class CapabilityReplayError(RuntimeError):
    """Raised when an event stream cannot be deterministically replayed."""


class CapabilityReplay:
    def __init__(self, lifecycle: CapabilityLifecycle) -> None:
        self.lifecycle = lifecycle

    def replay(self, values: Iterable[dict[str, Any]]) -> dict[str, Any]:
        states: dict[str, str] = {}
        expected_sequence = 1
        event_count = 0
        for value in values:
            event = CapabilityLifecycleEvent.from_mapping(value)
            if event.sequence != expected_sequence:
                raise CapabilityReplayError("Lifecycle sequence is not contiguous")
            current = states.get(event.capability_id, "DRAFT")
            states[event.capability_id] = self.lifecycle.apply(current, event)
            expected_sequence += 1
            event_count += 1
        projection = {
            "event_count": event_count,
            "states": {key: states[key] for key in sorted(states)},
            "state_changed_outside_projection": False,
            "actionable": False,
        }
        material = json.dumps(
            projection,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return {
            **projection,
            "projection_hash": hashlib.sha256(material).hexdigest().upper(),
        }
