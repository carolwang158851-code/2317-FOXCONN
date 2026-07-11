"""Frozen event catalog and transition validation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..contract_loader import ContractLoader


class EventValidationError(RuntimeError):
    """Raised when an event violates the frozen catalog or transition table."""


EVENT_TARGET_STATE = {
    "KNOWLEDGE_GAP_OPENED": "OPEN",
    "KNOWLEDGE_GAP_INVESTIGATION_STARTED": "INVESTIGATING",
    "KNOWLEDGE_GAP_PARTIALLY_RESOLVED": "PARTIALLY_RESOLVED",
    "KNOWLEDGE_GAP_RESOLVED": "RESOLVED",
    "KNOWLEDGE_GAP_ACCEPTED_UNKNOWN": "ACCEPTED_UNKNOWN",
    "KNOWLEDGE_GAP_RETIRED": "RETIRED",
    "RESEARCH_AGENDA_PROPOSED": "PROPOSED",
    "RESEARCH_AGENDA_ACTIVATED": "ACTIVE",
    "RESEARCH_AGENDA_BLOCKED": "BLOCKED",
    "RESEARCH_AGENDA_ANSWERED": "ANSWERED",
    "RESEARCH_AGENDA_RETIRED": "RETIRED",
    "RESEARCH_DEBT_OPENED": "OPEN",
    "RESEARCH_DEBT_WAITING_EVENT": "WAITING_EVENT",
    "RESEARCH_DEBT_WAITING_DATA": "WAITING_DATA",
    "RESEARCH_DEBT_OVERDUE": "OVERDUE",
    "RESEARCH_DEBT_RESOLVED": "RESOLVED",
    "RESEARCH_DEBT_ACCEPTED": "ACCEPTED_DEBT",
    "RESEARCH_DEBT_RETIRED": "RETIRED",
}

TRANSITION_AGGREGATES = {
    "GAP": "KNOWLEDGE_GAP",
    "AGENDA": "RESEARCH_AGENDA",
    "DEBT": "RESEARCH_DEBT",
}


class EventCatalog:
    REQUIRED_FIELDS = frozenset(
        {
            "event_id",
            "event_type",
            "aggregate_type",
            "aggregate_id",
            "occurred_at",
            "actor_type",
            "actor_id",
            "payload",
            "owner_review_required",
            "effective_change_applied",
            "actionable",
        }
    )
    OPTIONAL_FIELDS = frozenset({"causation_event_id", "correlation_id"})

    def __init__(self, loader: ContractLoader) -> None:
        self.loader = loader
        definitions = loader.load_json("events/event_definitions.json")
        self.transitions = loader.load_json("events/state_transitions.json")
        self.events = {item["eventType"]: item for item in definitions["events"]}
        self.forbidden_events = frozenset(definitions["forbiddenEvents"])
        if len(self.events) != len(definitions["events"]):
            raise EventValidationError("Duplicate event type in frozen catalog")

    @property
    def allowed_event_types(self) -> frozenset[str]:
        return frozenset(self.events)

    def validate_event(self, event: dict[str, Any]) -> dict[str, Any]:
        missing = sorted(self.REQUIRED_FIELDS - set(event))
        if missing:
            raise EventValidationError(f"Event is missing fields: {missing}")
        extra = sorted(set(event) - self.REQUIRED_FIELDS - self.OPTIONAL_FIELDS)
        if extra:
            raise EventValidationError(f"Event has unknown fields: {extra}")
        event_type = event["event_type"]
        if event_type in self.forbidden_events:
            raise EventValidationError(f"Forbidden event: {event_type}")
        definition = self.events.get(event_type)
        if definition is None:
            raise EventValidationError(f"Unregistered event: {event_type}")
        if event["aggregate_type"] != definition["aggregateType"]:
            raise EventValidationError(f"Wrong aggregate type for {event_type}")
        if event["actor_type"] not in definition["allowedActors"]:
            raise EventValidationError(f"Actor cannot emit {event_type}")
        if not isinstance(event["event_id"], str) or not event["event_id"]:
            raise EventValidationError("event_id is required")
        if not isinstance(event["aggregate_id"], str) or not event["aggregate_id"]:
            raise EventValidationError("aggregate_id is required")
        if not isinstance(event["actor_id"], str) or not event["actor_id"]:
            raise EventValidationError("actor_id is required")
        if not isinstance(event["payload"], dict):
            raise EventValidationError("Event payload must be an object")
        if not isinstance(event["owner_review_required"], bool):
            raise EventValidationError("owner_review_required must be boolean")
        if event["owner_review_required"] is not bool(
            definition["ownerReviewRequired"]
        ):
            raise EventValidationError(
                f"owner_review_required conflicts with catalog for {event_type}"
            )
        if event["effective_change_applied"] is not False or event["actionable"] is not False:
            raise EventValidationError("Event attempted an effective or actionable change")
        try:
            datetime.fromisoformat(str(event["occurred_at"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise EventValidationError("Event occurred_at must be date-time") from exc
        return dict(event)

    def target_state(self, event_type: str) -> str | None:
        return EVENT_TARGET_STATE.get(event_type)

    def validate_transition(
        self,
        aggregate_type: str,
        current_state: str | None,
        target_state: str,
        event: dict[str, Any],
    ) -> None:
        transition_key = TRANSITION_AGGREGATES.get(aggregate_type)
        if transition_key is None:
            raise EventValidationError(f"No state transition contract for {aggregate_type}")
        contract = self.transitions["aggregates"][transition_key]
        if event["aggregate_type"] != aggregate_type:
            raise EventValidationError("Transition event aggregate does not match")
        if self.target_state(event["event_type"]) != target_state:
            raise EventValidationError("Transition event does not produce target state")
        if current_state is None:
            if target_state != contract["initial"]:
                raise EventValidationError(
                    f"Invalid initial transition for {aggregate_type}: {target_state}"
                )
        else:
            allowed = contract["transitions"].get(current_state)
            if allowed is None or target_state not in allowed:
                raise EventValidationError(
                    f"Invalid transition for {aggregate_type}: {current_state} -> {target_state}"
                )
        if target_state in {"RESOLVED", "ANSWERED"} and contract.get(
            "resolutionRequiresEvidence", contract.get("answerRequiresEvidence", False)
        ):
            evidence_ids = event["payload"].get("evidence_ids")
            if not isinstance(evidence_ids, list) or not evidence_ids:
                raise EventValidationError(f"Evidence is required for {target_state}")
        if contract.get("modelFinalTransitionAllowed") is False and target_state in {
            "RESOLVED",
            "ANSWERED",
            "ACCEPTED_UNKNOWN",
            "ACCEPTED_DEBT",
            "RETIRED",
        }:
            if event["actor_type"] in {"OPENAI", "CODEX"}:
                raise EventValidationError("Model/Codex cannot perform a final transition")
