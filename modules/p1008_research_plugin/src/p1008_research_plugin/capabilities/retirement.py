"""Create non-executing retirement review candidates."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .manifest import CapabilityManifest
from .policy import CapabilityPolicy


class CapabilityRetirement:
    def __init__(self, policy: CapabilityPolicy) -> None:
        self.policy = policy.retirement

    def propose(self, manifest: CapabilityManifest, reason: str) -> dict[str, Any]:
        normalized = reason.strip()
        if not normalized:
            raise ValueError("Retirement reason is required")
        material = json.dumps(
            {"capability_id": manifest.capability_id, "reason": normalized},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return {
            "proposal_id": f"RETIRE-{hashlib.sha256(material).hexdigest().upper()[:20]}",
            "capability_id": manifest.capability_id,
            "current_state": manifest.lifecycle_state,
            "reason": normalized,
            "owner_review_required": True,
            "manifest_delete_allowed": False,
            "history_delete_allowed": False,
            "state_changed": False,
            "actionable": False,
        }
