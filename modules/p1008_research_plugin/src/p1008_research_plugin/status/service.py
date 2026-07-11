"""Status projection for the isolated Phase 1B skeleton."""

from __future__ import annotations

from typing import Any

from ..adapters.authority_adapter import AuthorityAdapter
from ..adapters.runtime_snapshot_adapter import RuntimeSnapshotAdapter
from ..contract_loader import ContractLoader
from ..governance import GovernanceBoundary
from ..ledgers.store import LedgerStore
from ..projections.replay import ProjectionEngine


class StatusService:
    def __init__(
        self,
        loader: ContractLoader,
        governance: GovernanceBoundary,
        authority: AuthorityAdapter,
        runtime_snapshots: RuntimeSnapshotAdapter,
        store: LedgerStore | None = None,
        projection_engine: ProjectionEngine | None = None,
    ) -> None:
        self.loader = loader
        self.governance = governance
        self.authority = authority
        self.runtime_snapshots = runtime_snapshots
        self.store = store
        self.projection_engine = projection_engine

    def build_status(self) -> dict[str, Any]:
        self.loader.verify_manifest()
        self.authority.verify_all()
        self.authority.read_rule_manifest()
        projection: dict[str, Any] | None = None
        if self.store is not None:
            if self.projection_engine is None:
                raise RuntimeError("ProjectionEngine is required when LedgerStore is set")
            projection = self.projection_engine.replay_all(self.store)

        summary = projection["summary"] if projection else {}
        record_count = int(summary.get("record_count", 0))
        payload = {
            "contract_version": "1.0",
            "implementation_status": "SKELETON",
            "runtime_status": "AVAILABLE" if record_count else "IDLE",
            "last_successful_run": summary.get("last_successful_run"),
            "data_freshness": "NOT_EVALUATED",
            "rqs": None,
            "rhs": summary.get("rhs"),
            "evidence_gate_result": "NOT_EVALUATED",
            "legacy_reuse_violation_count": int(
                summary.get("legacy_reuse_violation_count", 0)
            ),
            "owner_review_count": int(summary.get("owner_review_count", 0)),
            "open_gap_count": int(summary.get("open_gap_count", 0)),
            "overdue_debt_count": int(summary.get("overdue_debt_count", 0)),
            "openai_enabled": False,
            "actionable": False,
        }
        self.governance.assert_phase1b_status(payload)
        return self.loader.validate_status(payload)

    def unavailable_status(self) -> dict[str, Any]:
        payload = {
            "contract_version": "1.0",
            "implementation_status": "SKELETON",
            "runtime_status": "UNAVAILABLE",
            "last_successful_run": None,
            "data_freshness": "UNKNOWN",
            "rqs": None,
            "rhs": None,
            "evidence_gate_result": "NOT_EVALUATED",
            "legacy_reuse_violation_count": 0,
            "owner_review_count": 0,
            "open_gap_count": 0,
            "overdue_debt_count": 0,
            "openai_enabled": False,
            "actionable": False,
        }
        self.governance.assert_phase1b_status(payload)
        return self.loader.validate_status(payload)
