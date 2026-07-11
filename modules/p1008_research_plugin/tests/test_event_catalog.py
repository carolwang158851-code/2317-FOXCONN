from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.contract_loader import ContractLoader
from p1008_research_plugin.events.catalog import (
    EVENT_TARGET_STATE,
    TRANSITION_AGGREGATES,
    EventCatalog,
    EventValidationError,
)


def event_for(catalog: EventCatalog, event_type: str, actor: str | None = None) -> dict:
    definition = catalog.events[event_type]
    actor_type = actor or definition["allowedActors"][0]
    return {
        "event_id": f"TEST-{event_type}",
        "event_type": event_type,
        "aggregate_type": definition["aggregateType"],
        "aggregate_id": f"AGG-{event_type}",
        "occurred_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "actor_type": actor_type,
        "actor_id": f"TEST-{actor_type}",
        "causation_event_id": None,
        "correlation_id": "CATALOG-TEST",
        "payload": {},
        "owner_review_required": bool(definition["ownerReviewRequired"]),
        "effective_change_applied": False,
        "actionable": False,
    }


class EventCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = EventCatalog(ContractLoader(PACKAGE_ROOT))

    def test_all_allowed_and_forbidden_events(self) -> None:
        self.assertEqual(len(self.catalog.allowed_event_types), 34)
        self.assertEqual(len(self.catalog.forbidden_events), 8)
        for event_type in self.catalog.allowed_event_types:
            self.assertEqual(
                self.catalog.validate_event(event_for(self.catalog, event_type))["event_type"],
                event_type,
            )
        for event_type in self.catalog.forbidden_events:
            event = event_for(self.catalog, "RUN_STARTED")
            event["event_type"] = event_type
            with self.assertRaises(EventValidationError):
                self.catalog.validate_event(event)

    def test_wrong_actor_and_effective_change_are_rejected(self) -> None:
        event = event_for(self.catalog, "RESEARCH_HEALTH_SNAPSHOT_COMPUTED")
        event["actor_type"] = "OPENAI"
        with self.assertRaises(EventValidationError):
            self.catalog.validate_event(event)
        event = event_for(self.catalog, "RUN_STARTED")
        event["effective_change_applied"] = True
        with self.assertRaises(EventValidationError):
            self.catalog.validate_event(event)

    def test_every_frozen_transition_edge_is_accepted(self) -> None:
        state_to_event = {
            (self.catalog.events[event]["aggregateType"], state): event
            for event, state in EVENT_TARGET_STATE.items()
        }
        for aggregate_type, contract_key in TRANSITION_AGGREGATES.items():
            contract = self.catalog.transitions["aggregates"][contract_key]
            initial_event = event_for(
                self.catalog, state_to_event[(aggregate_type, contract["initial"])]
            )
            self.catalog.validate_transition(
                aggregate_type, None, contract["initial"], initial_event
            )
            for current, targets in contract["transitions"].items():
                for target in targets:
                    event = event_for(
                        self.catalog, state_to_event[(aggregate_type, target)]
                    )
                    if target in {"RESOLVED", "ANSWERED"}:
                        event["payload"]["evidence_ids"] = ["EVD-TEST"]
                    self.catalog.validate_transition(
                        aggregate_type, current, target, event
                    )

    def test_invalid_transition_and_missing_evidence_are_rejected(self) -> None:
        resolved = event_for(self.catalog, "KNOWLEDGE_GAP_RESOLVED")
        with self.assertRaises(EventValidationError):
            self.catalog.validate_transition("GAP", "OPEN", "RESOLVED", resolved)
        answered = event_for(self.catalog, "RESEARCH_AGENDA_ANSWERED")
        with self.assertRaises(EventValidationError):
            self.catalog.validate_transition("AGENDA", "ACTIVE", "ANSWERED", answered)


if __name__ == "__main__":
    unittest.main()
