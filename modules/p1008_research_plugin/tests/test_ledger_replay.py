from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.contract_loader import ContractLoader
from p1008_research_plugin.events.catalog import EventCatalog
from p1008_research_plugin.ledgers.store import (
    LedgerError,
    LedgerStore,
    canonical_json,
)
from p1008_research_plugin.projections.replay import ProjectionEngine


def make_event(
    catalog: EventCatalog,
    index: int,
    event_type: str,
    aggregate_id: str,
    payload: dict | None = None,
) -> dict:
    definition = catalog.events[event_type]
    actor_type = definition["allowedActors"][0]
    occurred = datetime(2026, 7, 11, tzinfo=timezone.utc) + timedelta(seconds=index)
    return {
        "event_id": f"LEDGER-{index:04d}",
        "event_type": event_type,
        "aggregate_type": definition["aggregateType"],
        "aggregate_id": aggregate_id,
        "occurred_at": occurred.isoformat(timespec="seconds"),
        "actor_type": actor_type,
        "actor_id": f"TEST-{actor_type}",
        "causation_event_id": None,
        "correlation_id": "LEDGER-REPLAY-TEST",
        "payload": dict(payload or {}),
        "owner_review_required": bool(definition["ownerReviewRequired"]),
        "effective_change_applied": False,
        "actionable": False,
    }


class LedgerReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.loader = ContractLoader(PACKAGE_ROOT)
        self.catalog = EventCatalog(self.loader)
        self.engine = ProjectionEngine(self.catalog)

    def store(self, root: Path) -> LedgerStore:
        return LedgerStore(PACKAGE_ROOT, root, self.loader, self.catalog)

    def test_repository_root_is_never_a_ledger_write_root(self) -> None:
        with self.assertRaises(LedgerError):
            self.store(PACKAGE_ROOT / "runtime" / "research_plugin")

    def test_rfc8785_compatible_number_and_key_canonicalization(self) -> None:
        value = {"z": 1e20, "b": 1.0, "a": 1e-7, "negative_zero": -0.0}
        self.assertEqual(
            canonical_json(value),
            '{"a":1e-7,"b":1,"negative_zero":0,"z":100000000000000000000}',
        )
        with self.assertRaises(LedgerError):
            canonical_json({"bad": float("nan")})

    def test_all_eight_ledgers_replay_and_restart_deterministically(self) -> None:
        events = (
            ("inference_chain", "RUN_STARTED", "RUN-1", {}),
            ("decision_memory", "DECISION_MEMORY_REVIEW_DUE", "MEMORY-1", {}),
            ("thesis_lineage", "THESIS_CHANGE_PROPOSED", "THESIS-1", {}),
            ("research_agenda", "RESEARCH_AGENDA_PROPOSED", "AGENDA-1", {}),
            ("knowledge_gap", "KNOWLEDGE_GAP_OPENED", "GAP-1", {}),
            ("research_debt", "RESEARCH_DEBT_OPENED", "DEBT-1", {}),
            ("owner_review", "OWNER_REVIEW_QUEUED", "REVIEW-1", {}),
            (
                "research_health",
                "RESEARCH_HEALTH_SNAPSHOT_COMPUTED",
                "HEALTH-1",
                {"overall_score": 82},
            ),
        )
        with tempfile.TemporaryDirectory(
            prefix=".p1008-ledger-", dir=PACKAGE_ROOT.parent
        ) as temp_dir:
            store = self.store(Path(temp_dir))
            for index, (ledger, event_type, aggregate_id, payload) in enumerate(
                events, start=1
            ):
                store.append_event(
                    ledger,
                    make_event(self.catalog, index, event_type, aggregate_id, payload),
                )
            first = self.engine.replay_all(store)
            restarted = self.engine.replay_all(self.store(Path(temp_dir)))
            self.assertEqual(len(first["ledgers"]), 8)
            self.assertEqual(first["summary"]["record_count"], 8)
            self.assertEqual(first["projection_hash"], restarted["projection_hash"])
            self.assertEqual(first["summary"]["rhs"], 82)

    def test_gap_agenda_and_debt_states_rebuild(self) -> None:
        sequences = {
            "knowledge_gap": [
                ("KNOWLEDGE_GAP_OPENED", "GAP-A", {}),
                ("KNOWLEDGE_GAP_INVESTIGATION_STARTED", "GAP-A", {}),
                ("KNOWLEDGE_GAP_PARTIALLY_RESOLVED", "GAP-A", {}),
                ("KNOWLEDGE_GAP_INVESTIGATION_STARTED", "GAP-A", {}),
                ("KNOWLEDGE_GAP_RESOLVED", "GAP-A", {"evidence_ids": ["E1"]}),
                ("KNOWLEDGE_GAP_OPENED", "GAP-B", {}),
                ("KNOWLEDGE_GAP_ACCEPTED_UNKNOWN", "GAP-B", {}),
                ("KNOWLEDGE_GAP_OPENED", "GAP-C", {}),
                ("KNOWLEDGE_GAP_RETIRED", "GAP-C", {}),
            ],
            "research_agenda": [
                ("RESEARCH_AGENDA_PROPOSED", "AGENDA-A", {}),
                ("RESEARCH_AGENDA_ACTIVATED", "AGENDA-A", {}),
                ("RESEARCH_AGENDA_BLOCKED", "AGENDA-A", {}),
                ("RESEARCH_AGENDA_ACTIVATED", "AGENDA-A", {}),
                ("RESEARCH_AGENDA_ANSWERED", "AGENDA-A", {"evidence_ids": ["E2"]}),
                ("RESEARCH_AGENDA_PROPOSED", "AGENDA-B", {}),
                ("RESEARCH_AGENDA_RETIRED", "AGENDA-B", {}),
            ],
            "research_debt": [
                ("RESEARCH_DEBT_OPENED", "DEBT-A", {}),
                ("RESEARCH_DEBT_WAITING_EVENT", "DEBT-A", {}),
                ("RESEARCH_DEBT_OVERDUE", "DEBT-A", {}),
                ("RESEARCH_DEBT_WAITING_DATA", "DEBT-A", {}),
                ("RESEARCH_DEBT_RESOLVED", "DEBT-A", {"evidence_ids": ["E3"]}),
                ("RESEARCH_DEBT_OPENED", "DEBT-B", {}),
                ("RESEARCH_DEBT_ACCEPTED", "DEBT-B", {}),
                ("RESEARCH_DEBT_OPENED", "DEBT-C", {}),
                ("RESEARCH_DEBT_RETIRED", "DEBT-C", {}),
            ],
        }
        with tempfile.TemporaryDirectory(
            prefix=".p1008-states-", dir=PACKAGE_ROOT.parent
        ) as temp_dir:
            store = self.store(Path(temp_dir))
            index = 0
            for ledger, items in sequences.items():
                for event_type, aggregate_id, payload in items:
                    index += 1
                    store.append_event(
                        ledger,
                        make_event(self.catalog, index, event_type, aggregate_id, payload),
                    )
            projection = self.engine.replay_all(store)
            self.assertEqual(
                projection["ledgers"]["knowledge_gap"]["aggregates"]["GAP-A"]["state"],
                "RESOLVED",
            )
            self.assertEqual(
                projection["ledgers"]["knowledge_gap"]["aggregates"]["GAP-B"]["state"],
                "ACCEPTED_UNKNOWN",
            )
            self.assertEqual(
                projection["ledgers"]["research_agenda"]["aggregates"]["AGENDA-A"]["state"],
                "ANSWERED",
            )
            self.assertEqual(
                projection["ledgers"]["research_debt"]["aggregates"]["DEBT-B"]["state"],
                "ACCEPTED_DEBT",
            )

    def test_invalid_transition_is_rejected_during_replay(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix=".p1008-invalid-", dir=PACKAGE_ROOT.parent
        ) as temp_dir:
            store = self.store(Path(temp_dir))
            store.append_event(
                "knowledge_gap",
                make_event(self.catalog, 1, "KNOWLEDGE_GAP_OPENED", "GAP-X"),
            )
            store.append_event(
                "knowledge_gap",
                make_event(
                    self.catalog,
                    2,
                    "KNOWLEDGE_GAP_RESOLVED",
                    "GAP-X",
                    {"evidence_ids": ["E1"]},
                ),
            )
            with self.assertRaises(Exception):
                self.engine.replay_all(store)

    def test_tamper_partial_truncation_and_known_count_suffix_loss_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix=".p1008-corrupt-", dir=PACKAGE_ROOT.parent
        ) as temp_dir:
            store = self.store(Path(temp_dir))
            store.append_event(
                "inference_chain", make_event(self.catalog, 1, "RUN_STARTED", "RUN-X")
            )
            path = store._ledger_path("inference_chain")
            record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            record["event"]["payload"]["tampered"] = True
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaises(LedgerError):
                store.read_records("inference_chain")

        with tempfile.TemporaryDirectory(
            prefix=".p1008-truncate-", dir=PACKAGE_ROOT.parent
        ) as temp_dir:
            store = self.store(Path(temp_dir))
            store.append_event(
                "inference_chain", make_event(self.catalog, 1, "RUN_STARTED", "RUN-Y")
            )
            path = store._ledger_path("inference_chain")
            data = path.read_bytes()
            path.write_bytes(data[:-7])
            with self.assertRaises(LedgerError):
                store.read_records("inference_chain")

        with tempfile.TemporaryDirectory(
            prefix=".p1008-suffix-", dir=PACKAGE_ROOT.parent
        ) as temp_dir:
            store = self.store(Path(temp_dir))
            store.append_event(
                "inference_chain", make_event(self.catalog, 1, "RUN_STARTED", "RUN-Z")
            )
            store.append_event(
                "inference_chain", make_event(self.catalog, 2, "RUN_COMPLETED", "RUN-Z")
            )
            path = store._ledger_path("inference_chain")
            first_line = path.read_text(encoding="utf-8").splitlines()[0]
            path.write_text(first_line + "\n", encoding="utf-8")
            with self.assertRaises(LedgerError):
                store.read_records("inference_chain", expected_count=2)


if __name__ == "__main__":
    unittest.main()
