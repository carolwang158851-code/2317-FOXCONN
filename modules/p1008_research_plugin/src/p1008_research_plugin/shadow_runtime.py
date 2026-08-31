"""Manual Phase 1B contract/replay smoke entrypoint; never scheduled or integrated."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from p1008_research_plugin.adapters.authority_adapter import AuthorityAdapter
from p1008_research_plugin.adapters.runtime_snapshot_adapter import RuntimeSnapshotAdapter
from p1008_research_plugin.contract_loader import ContractLoader
from p1008_research_plugin.events.catalog import EventCatalog
from p1008_research_plugin.governance import GovernanceBoundary
from p1008_research_plugin.ledgers.store import LedgerStore
from p1008_research_plugin.projections.replay import ProjectionEngine
from p1008_research_plugin.status.service import StatusService


SMOKE_EVENTS = (
    ("inference_chain", "RUN_STARTED", "RUN", "RUN-SMOKE"),
    (
        "decision_memory",
        "DECISION_MEMORY_REVIEW_DUE",
        "DECISION_MEMORY",
        "MEMORY-SMOKE",
    ),
    ("thesis_lineage", "THESIS_CHANGE_PROPOSED", "THESIS", "THESIS-SMOKE"),
    ("research_agenda", "RESEARCH_AGENDA_PROPOSED", "AGENDA", "AGENDA-SMOKE"),
    ("knowledge_gap", "KNOWLEDGE_GAP_OPENED", "GAP", "GAP-SMOKE"),
    ("research_debt", "RESEARCH_DEBT_OPENED", "DEBT", "DEBT-SMOKE"),
    ("owner_review", "OWNER_REVIEW_QUEUED", "OWNER_REVIEW", "REVIEW-SMOKE"),
    (
        "research_health",
        "RESEARCH_HEALTH_SNAPSHOT_COMPUTED",
        "HEALTH",
        "HEALTH-SMOKE",
    ),
)


def event_for(
    catalog: EventCatalog,
    index: int,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
) -> dict[str, Any]:
    definition = catalog.events[event_type]
    actor_type = definition["allowedActors"][0]
    timestamp = datetime(2026, 7, 11, 0, 0, tzinfo=timezone.utc) + timedelta(
        seconds=index
    )
    payload: dict[str, Any] = {}
    if aggregate_type == "HEALTH":
        payload["overall_score"] = 80
    return {
        "event_id": f"SMOKE-{index:03d}",
        "event_type": event_type,
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "occurred_at": timestamp.isoformat(timespec="seconds"),
        "actor_type": actor_type,
        "actor_id": f"PHASE1B-{actor_type}",
        "causation_event_id": None,
        "correlation_id": "PHASE1B-SMOKE",
        "payload": payload,
        "owner_review_required": bool(definition["ownerReviewRequired"]),
        "effective_change_applied": False,
        "actionable": False,
    }


def build_components(package_root: Path, sandbox_root: Path | None = None) -> dict[str, Any]:
    loader = ContractLoader(package_root)
    governance = GovernanceBoundary(loader)
    authority = AuthorityAdapter(package_root, loader)
    runtime = RuntimeSnapshotAdapter(package_root)
    catalog = EventCatalog(loader)
    engine = ProjectionEngine(catalog)
    store = (
        LedgerStore(package_root, sandbox_root, loader, catalog)
        if sandbox_root is not None
        else None
    )
    service = StatusService(loader, governance, authority, runtime, store, engine)
    return {
        "loader": loader,
        "governance": governance,
        "authority": authority,
        "runtime": runtime,
        "catalog": catalog,
        "engine": engine,
        "store": store,
        "service": service,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="P1008 Phase 1B deterministic smoke")
    parser.add_argument("--check", action="store_true", help="Verify contract and read-only status")
    parser.add_argument(
        "--replay-smoke", action="store_true", help="Replay all eight ledgers in a temp root"
    )
    args = parser.parse_args()
    if not args.check and not args.replay_smoke:
        parser.error("Select --check or --replay-smoke")

    package_root = ContractLoader.discover_package_root(Path(__file__))
    if args.check:
        components = build_components(package_root)
        output = {
            "contract": components["loader"].verify_manifest(),
            "references": components["loader"].resolve_references(),
            "authority": dict(components["authority"].manifest_summary()),
            "status": components["service"].build_status(),
            "openai_calls": 0,
            "actionable": False,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    governance = GovernanceBoundary(ContractLoader(package_root))
    ledger_temp_root = governance.authorize_write(
        "RESEARCH_PLUGIN_LEDGER",
        package_root / "runtime" / "research_plugin" / "ledgers",
    )
    ledger_temp_root.mkdir(parents=True, exist_ok=True)
    temp_name = f".p1008-phase1b-{uuid4().hex}"
    temp_dir = governance.authorize_write(
        "RESEARCH_PLUGIN_LEDGER", ledger_temp_root / temp_name
    )
    temp_dir.mkdir()
    try:
        components = build_components(package_root, temp_dir)
        store: LedgerStore = components["store"]
        catalog: EventCatalog = components["catalog"]
        for index, (ledger_id, event_type, aggregate_type, aggregate_id) in enumerate(
            SMOKE_EVENTS, start=1
        ):
            store.append_event(
                ledger_id,
                event_for(catalog, index, event_type, aggregate_type, aggregate_id),
            )
        projection = components["engine"].replay_all(store)
        output = {
            "status": components["service"].build_status(),
            "projection_hash": projection["projection_hash"],
            "ledger_count": len(projection["ledgers"]),
            "record_count": projection["summary"]["record_count"],
            "sandbox_deleted_on_exit": True,
            "openai_calls": 0,
            "actionable": False,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    finally:
        disposable = governance.authorize_tree_delete(
            "RESEARCH_PLUGIN_LEDGER",
            temp_dir,
            owned_parent=ledger_temp_root,
            expected_name=temp_name,
        )
        shutil.rmtree(disposable, ignore_errors=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
