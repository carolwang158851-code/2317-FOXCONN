"""Deterministic projections rebuilt exclusively from validated ledgers."""

from __future__ import annotations

from typing import Any

from ..events.catalog import EventCatalog
from ..ledgers.store import LedgerStore, canonical_hash


class ProjectionError(RuntimeError):
    """Raised when validated events cannot rebuild a deterministic projection."""


class ProjectionEngine:
    def __init__(self, catalog: EventCatalog) -> None:
        self.catalog = catalog

    def replay_ledger(
        self, ledger_id: str, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        aggregates: dict[str, dict[str, Any]] = {}
        for record in records:
            event = self.catalog.validate_event(record["event"])
            aggregate_id = event["aggregate_id"]
            current = aggregates.get(
                aggregate_id,
                {
                    "aggregate_type": event["aggregate_type"],
                    "state": None,
                    "event_count": 0,
                    "last_event_type": None,
                    "last_occurred_at": None,
                    "payload": {},
                },
            )
            if current["aggregate_type"] != event["aggregate_type"]:
                raise ProjectionError(f"Aggregate type changed: {aggregate_id}")
            target_state = self.catalog.target_state(event["event_type"])
            if target_state is not None:
                self.catalog.validate_transition(
                    event["aggregate_type"], current["state"], target_state, event
                )
                current["state"] = target_state
            current["event_count"] += 1
            current["last_event_type"] = event["event_type"]
            current["last_occurred_at"] = event["occurred_at"]
            current["payload"] = dict(event["payload"])
            aggregates[aggregate_id] = current
        return {
            "ledger_id": ledger_id,
            "record_count": len(records),
            "aggregates": {key: aggregates[key] for key in sorted(aggregates)},
            "actionable": False,
        }

    def replay_all(self, store: LedgerStore) -> dict[str, Any]:
        ledgers: dict[str, dict[str, Any]] = {}
        all_records = store.read_all()
        for ledger_id in sorted(all_records):
            ledgers[ledger_id] = self.replay_ledger(ledger_id, all_records[ledger_id])

        open_gap_count = 0
        overdue_debt_count = 0
        owner_review_count = 0
        legacy_reuse_violation_count = 0
        rhs: float | int | None = None
        last_successful_run: str | None = None

        for projection in ledgers.values():
            for aggregate in projection["aggregates"].values():
                aggregate_type = aggregate["aggregate_type"]
                state = aggregate["state"]
                event_type = aggregate["last_event_type"]
                if aggregate_type == "GAP" and state not in {
                    "RESOLVED",
                    "ACCEPTED_UNKNOWN",
                    "RETIRED",
                }:
                    open_gap_count += 1
                if aggregate_type == "DEBT" and state == "OVERDUE":
                    overdue_debt_count += 1
                if aggregate_type == "OWNER_REVIEW" and event_type == "OWNER_REVIEW_QUEUED":
                    owner_review_count += 1
                if aggregate_type == "LEGACY_REUSE" and event_type == "LEGACY_THESIS_REUSE_BLOCKED":
                    legacy_reuse_violation_count += 1
                if aggregate_type == "HEALTH" and isinstance(
                    aggregate["payload"].get("overall_score"), (int, float)
                ):
                    rhs = aggregate["payload"]["overall_score"]
                if aggregate_type == "RUN" and event_type == "RUN_COMPLETED":
                    occurred = aggregate["last_occurred_at"]
                    if last_successful_run is None or occurred > last_successful_run:
                        last_successful_run = occurred

        projection = {
            "contract_version": "1.0",
            "ledgers": ledgers,
            "summary": {
                "record_count": sum(item["record_count"] for item in ledgers.values()),
                "open_gap_count": open_gap_count,
                "overdue_debt_count": overdue_debt_count,
                "owner_review_count": owner_review_count,
                "legacy_reuse_violation_count": legacy_reuse_violation_count,
                "rhs": rhs,
                "last_successful_run": last_successful_run,
            },
            "actionable": False,
        }
        projection["projection_hash"] = canonical_hash(projection)
        return projection
