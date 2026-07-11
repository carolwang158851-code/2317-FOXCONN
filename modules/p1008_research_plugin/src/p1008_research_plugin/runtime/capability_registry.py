"""Phase 2A capability allowlist with one deterministic Echo capability."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class CapabilityError(RuntimeError):
    """Raised when a deferred capability is requested."""


@dataclass(frozen=True)
class CapabilityDefinition:
    capability_id: str
    enabled: bool
    provider: str
    actionable: bool = False


class CapabilityRegistry:
    DEFERRED = frozenset(
        {
            "deep_research",
            "financial",
            "macro",
            "foreign_flow",
            "news",
            "ic_debate",
            "decision_engine",
        }
    )

    def __init__(self) -> None:
        self._definitions = {
            "echo_research": CapabilityDefinition(
                capability_id="echo_research",
                enabled=True,
                provider="phase2a-mock",
            )
        }

    def require_enabled(self, capability_id: str) -> CapabilityDefinition:
        definition = self._definitions.get(capability_id)
        if definition is None or not definition.enabled:
            raise CapabilityError(f"Capability is disabled: {capability_id}")
        return definition

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": sorted(self._definitions),
            "deferred": sorted(self.DEFERRED),
            "default_enabled": False,
            "actionable": False,
        }

    def execute_echo(self, context: Mapping[str, Any]) -> dict[str, Any]:
        self.require_enabled("echo_research")
        suffix = str(context["context_id"])[:12]
        source_id = f"SOURCE-{suffix}"
        evidence_id = f"EVIDENCE-{suffix}"
        return {
            "claims": [
                {
                    "claim_id": f"CLAIM-{suffix}",
                    "claim": "Echo Capability Active",
                    "evidence_ids": [evidence_id],
                    "confidence": "low",
                    "actionable": False,
                }
            ],
            "evidence": [
                {
                    "evidence_id": evidence_id,
                    "description": "Local mock echo accepted the normalized request.",
                    "source_ids": [source_id],
                    "actionable": False,
                }
            ],
            "counter_evidence": [],
            "knowledge_gaps": [],
            "sources": [
                {
                    "source_id": source_id,
                    "source_tier": "UNVERIFIED",
                    "source_name": "Phase 2A local mock request",
                    "locator": f"memory://phase2a/{context['context_id']}",
                    "evidence_level": "L1",
                }
            ],
            "confidence": "low",
            "limitations": ["Echo validates the governed pipeline only."],
            "owner_review_required": [],
            "actionable": False,
        }
