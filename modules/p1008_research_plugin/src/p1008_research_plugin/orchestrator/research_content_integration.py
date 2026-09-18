"""P1008 Research-to-Content v1: Discovery before governed report trigger.

This module composes existing read-only boundaries.  It does not run the news
scanner, write Authority/Core View/Evidence Ledger state, or invoke analysis,
reporting, rendering, publication, or model clients.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import re
from types import ModuleType
from typing import Any, Iterable, Mapping

from ..adapters.anysearch_runtime import execute_governed_search
from ..adapters.authority_adapter import AuthorityAdapter
from ..adapters.official_ir_evidence_adapter import (
    AUTHORIZATION_ID as OFFICIAL_IR_AUTHORIZATION_ID,
    RUNTIME_REL as OFFICIAL_IR_RUNTIME_REL,
    load_authorization as load_official_ir_authorization,
)
from ..adapters import research_skill_governance_adapter as discovery_governance
from ..contract_loader import ContractLoader
from ..phaseb1_common import canonical_json_bytes, sha256_bytes, sha256_file


class ResearchContentIntegrationError(RuntimeError):
    """The integration cannot prove a required read-only governance boundary."""


_RUN_ID = re.compile(r"^P1008-[A-Z0-9-]+$")
_REFERENCE = re.compile(r"^[A-Z0-9][A-Z0-9_:-]+$")
_PRODUCER_ID = "P1008_RESEARCH_CONTENT_ORCHESTRATOR_V1"
_DISCOVERY_QUALIFICATION_FIELDS = frozenset(
    {
        "provider_result_index",
        "event_id",
        "event_type",
        "occurred_at_utc",
        "published_at_utc",
        "received_at_utc",
        "data_cutoff",
        "originating_chain_id",
        "evidence_ids",
        "claim_summary",
        "affected_kpis",
        "materiality",
        "novelty",
        "confidence",
        "quality_metadata",
        "provenance",
        "canonical_event_id",
        "counter_evidence_ids",
        "missing_evidence",
        "source_conflicts",
    }
)


def _is_plain_json_fixture(value: object) -> bool:
    if type(value) is dict:
        return all(
            type(key) is str and _is_plain_json_fixture(item)
            for key, item in value.items()  # type: ignore[union-attr]
        )
    if type(value) is list:
        return all(_is_plain_json_fixture(item) for item in value)  # type: ignore[union-attr]
    return value is None or type(value) in {str, int, float, bool}


@dataclass(frozen=True, init=False)
class OfflineFixtureTransport:
    """Explicitly offline canned transport for deterministic integration tests."""

    _response_json: str

    def __init__(self, response: Mapping[str, Any]) -> None:
        if type(response) is not dict or not _is_plain_json_fixture(response):
            raise ResearchContentIntegrationError("OFFLINE_FIXTURE_INVALID")
        try:
            serialized = json.dumps(
                response,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise ResearchContentIntegrationError("OFFLINE_FIXTURE_INVALID") from exc
        object.__setattr__(self, "_response_json", serialized)

    def __call__(
        self, _endpoint: str, _payload: Mapping[str, Any], _headers: Mapping[str, str]
    ) -> Mapping[str, Any]:
        value = json.loads(self._response_json)
        if not isinstance(value, dict):
            raise ResearchContentIntegrationError("OFFLINE_FIXTURE_INVALID")
        return value


def _load_report_governance(package_root: Path) -> ModuleType:
    path = package_root / "tools" / "warroom_report_governance.py"
    spec = importlib.util.spec_from_file_location("p1008_existing_report_governance", path)
    if spec is None or spec.loader is None:
        raise ResearchContentIntegrationError("REPORT_GOVERNANCE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ResearchContentOrchestrator:
    """Read Authority and staging evidence, then evaluate the existing G1 gate."""

    def __init__(self, package_root: Path | str) -> None:
        self.package_root = Path(package_root).resolve()
        self.authority = AuthorityAdapter(self.package_root, ContractLoader(self.package_root))
        self.report_governance = _load_report_governance(self.package_root)
        self._issued_scans: dict[str, discovery_governance.ValidatedDiscoveryScan] = {}

    def authorize_discovery_scan(
        self,
        *,
        run_id: str,
        scan_reference: str,
        event_reference: str,
    ) -> discovery_governance.ValidatedDiscoveryScan:
        """Mint one scan from the controlled Owner authorization artifact."""

        if not _RUN_ID.fullmatch(run_id) or not all(
            isinstance(value, str) and _REFERENCE.fullmatch(value)
            for value in (scan_reference, event_reference)
        ):
            raise ResearchContentIntegrationError("DISCOVERY_SCAN_CONTEXT_INVALID")
        validated_authorization = (
            discovery_governance.load_validated_discovery_authorization(
                self.package_root
            )
        )
        verified = self.authority.verify_all()
        if verified["verified_count"] != len(self.authority.listed_paths):
            raise ResearchContentIntegrationError("AUTHORITY_VERIFICATION_FAILED")
        authority_manifest_sha256 = sha256_file(
            self.package_root / AuthorityAdapter.MANIFEST_PATH
        )
        scan_id = "DISCOVERY-SCAN-" + sha256_bytes(
            canonical_json_bytes(
                {
                    "run_id": run_id,
                    "scan_reference": scan_reference,
                    "event_reference": event_reference,
                    "authority_manifest_sha256": authority_manifest_sha256,
                    "authorization_identity": (
                        validated_authorization.authorization_identity
                    ),
                    "authorization_artifact_sha256": (
                        validated_authorization.authorization_artifact_sha256
                    ),
                }
            )
        )[:16]

        def consume_once() -> None:
            capability = self._issued_scans.get(scan_id)
            if capability is None:
                raise ResearchContentIntegrationError("DISCOVERY_SCAN_NOT_TRUSTED")
            del self._issued_scans[scan_id]

        capability = discovery_governance._mint_validated_discovery_scan(
            validated_authorization=validated_authorization,
            scan_id=scan_id,
            run_id=run_id,
            scan_reference=scan_reference,
            event_reference=event_reference,
            authority_manifest_sha256=authority_manifest_sha256,
            consume_callback=consume_once,
        )
        self._issued_scans[scan_id] = capability
        return capability

    @staticmethod
    def _news_locators(snapshot: Mapping[str, Any] | None) -> set[str]:
        if snapshot is None:
            return set()
        if (
            snapshot.get("task") != "P1008_NEWS_SCAN"
            or snapshot.get("runtimeOnly") is not True
            or snapshot.get("productionCsvModified") is not False
            or snapshot.get("actionable") is not False
        ):
            raise ResearchContentIntegrationError("NEWS_SCAN_BOUNDARY_INVALID")
        events = snapshot.get("events")
        if not isinstance(events, list):
            raise ResearchContentIntegrationError("NEWS_SCAN_BOUNDARY_INVALID")
        locators: set[str] = set()
        for event in events:
            if not isinstance(event, Mapping) or event.get("accepted") is not True:
                raise ResearchContentIntegrationError("NEWS_SCAN_BOUNDARY_INVALID")
            row = event.get("candidateRow")
            locator = row.get("SourceUrl") if isinstance(row, Mapping) else None
            if isinstance(locator, str) and locator:
                locators.add(discovery_governance.sanitize_source_locator(locator))
        return locators

    def _validate_evidence_provenance(
        self,
        evidence: Iterable[Mapping[str, Any]],
        *,
        discovery_candidates: Iterable[Mapping[str, Any]],
        news_locators: set[str],
    ) -> list[dict[str, Any]]:
        governed: list[dict[str, Any]] = []
        candidate_ids = {
            item.get("source_id")
            for item in discovery_candidates
            if isinstance(item.get("source_id"), str)
        }
        authority_paths = self.authority.listed_paths
        verified_authority = {
            entry["relative_path"]: entry["sha256"]
            for entry in self.authority.verify_all()["verified"]
        }
        for raw in evidence:
            item = self.report_governance.validate_event_evidence(dict(raw))
            source_class = item["source_class"]
            if source_class == "AUTHORITY":
                matching_path = next(
                    (
                        path
                        for path in authority_paths
                        if item["source_locator"].startswith(path)
                    ),
                    None,
                )
                if matching_path is None:
                    raise ResearchContentIntegrationError("AUTHORITY_PROVENANCE_NOT_MANIFEST_BOUND")
                if item["source_hash"] != verified_authority[matching_path]:
                    raise ResearchContentIntegrationError("AUTHORITY_PROVENANCE_HASH_MISMATCH")
            elif source_class == "DISCOVERY":
                if item["source_id"] not in candidate_ids:
                    raise ResearchContentIntegrationError("DISCOVERY_PROVENANCE_NOT_STAGED")
                if item["source_tier"] != "UNVERIFIED" or item["evidence_status"] == "CONFIRMED":
                    raise ResearchContentIntegrationError("DISCOVERY_PROMOTION_PROHIBITED")
            elif source_class == "SECONDARY":
                locator = discovery_governance.sanitize_source_locator(item["source_locator"])
                if locator not in news_locators:
                    raise ResearchContentIntegrationError("NEWS_PROVENANCE_NOT_STAGED")
            governed.append(item)
        return governed

    def _qualify_discovery(
        self,
        qualifications: Iterable[Mapping[str, Any]],
        candidates: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        by_index: dict[int, Mapping[str, Any]] = {}
        for item in candidates:
            provenance = item.get("provider_response_provenance")
            index = provenance.get("result_index") if isinstance(provenance, Mapping) else None
            if isinstance(index, int):
                by_index[index] = item
        evidence: list[dict[str, Any]] = []
        for raw in qualifications:
            if set(raw) != _DISCOVERY_QUALIFICATION_FIELDS:
                raise ResearchContentIntegrationError("DISCOVERY_QUALIFICATION_INVALID")
            candidate = by_index.get(raw.get("provider_result_index"))
            if candidate is None:
                raise ResearchContentIntegrationError("DISCOVERY_PROVENANCE_NOT_STAGED")
            item = {key: value for key, value in raw.items() if key != "provider_result_index"}
            item.update(
                {
                    "source_id": candidate["source_id"],
                    "source_type": "OTHER",
                    "source_class": "DISCOVERY",
                    "source_locator": candidate["source_locator"],
                    "source_tier": "UNVERIFIED",
                    "source_hash": candidate["source_hash"],
                    "event_status": "DISCOVERY_UNVERIFIED",
                    "evidence_status": "DISCOVERED",
                    "validation_status": "VALIDATED",
                    "verification_status": "VALIDATED",
                    "provenance": {
                        "qualification": raw["provenance"],
                        "provider_response": candidate["provider_response_provenance"],
                    },
                    "actionable": False,
                }
            )
            evidence.append(self.report_governance.validate_event_evidence(item))
        return evidence

    @staticmethod
    def _deduplicate(evidence: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
        unique: dict[tuple[str, str, str], dict[str, Any]] = {}
        count = 0
        for item in evidence:
            key = (item["canonical_event_id"], item["source_id"], item["source_hash"])
            if key in unique:
                count += 1
            else:
                unique[key] = item
        return list(unique.values()), count

    def _lineage_ledger(self, evidence: Iterable[dict[str, Any]]) -> dict[str, Any]:
        return self.report_governance.build_validated_evidence_lineage_ledger(
            list(evidence)
        )

    def integrate_official_ir(self, scan_result: Mapping[str, Any]) -> dict[str, Any]:
        """Validate hash-bound Official IR receipts and reuse the existing G1 path.

        This is deliberately not a collector.  The dedicated adapter supplies
        an integrity-valid scan; the orchestrator independently proves authorization,
        raw-byte lineage, evidence schema, deduplication and fail-closed state.
        """

        if (
            scan_result.get("record_type") != "P1008_OFFICIAL_IR_EVIDENCE_SCAN_V1"
            or scan_result.get("authorization_identity") != OFFICIAL_IR_AUTHORIZATION_ID
            or scan_result.get("scan_integrity_valid") is not True
            or scan_result.get("status") == "FAIL_CLOSED"
            or scan_result.get("actionable") is not False
            or scan_result.get("analysis_generated") is not False
            or scan_result.get("report_generated") is not False
            or scan_result.get("publication_count") != 0
        ):
            raise ResearchContentIntegrationError("OFFICIAL_IR_SCAN_FAIL_CLOSED")
        load_official_ir_authorization(self.package_root)
        supplied = scan_result.get("validated_event_evidence")
        if not isinstance(supplied, list):
            raise ResearchContentIntegrationError("OFFICIAL_IR_EVIDENCE_INVALID")
        canonical_event_id = scan_result.get("canonical_event_id")
        report_key = scan_result.get("report_key")
        supplied_ids = {
            item.get("canonical_event_id")
            for item in supplied
            if isinstance(item, Mapping)
        }
        identity = re.fullmatch(
            r"HON_HAI_FY(20\d{2})_Q([1-4])_EARNINGS",
            canonical_event_id if isinstance(canonical_event_id, str) else "",
        )
        expected_report_key = (
            f"P1008_FY{identity.group(1)}_Q{identity.group(2)}_EARNINGS"
            if identity else None
        )
        if supplied and (
            supplied_ids != {canonical_event_id}
            or expected_report_key is None
            or report_key != expected_report_key
        ):
            raise ResearchContentIntegrationError("OFFICIAL_IR_CANONICAL_EVENT_SCOPE_MISMATCH")
        if not isinstance(scan_result.get("coverage_complete"), bool):
            raise ResearchContentIntegrationError("OFFICIAL_IR_COVERAGE_INVALID")
        if not isinstance(scan_result.get("successful_sources"), list) or not isinstance(scan_result.get("failed_sources"), list):
            raise ResearchContentIntegrationError("OFFICIAL_IR_SOURCE_STATUS_INVALID")
        if scan_result["coverage_complete"] != (len(scan_result["failed_sources"]) == 0):
            raise ResearchContentIntegrationError("OFFICIAL_IR_COVERAGE_INCONSISTENT")
        governed: list[dict[str, Any]] = []
        evidence_validation_failures: list[dict[str, str]] = []
        receipt_root = (self.package_root / OFFICIAL_IR_RUNTIME_REL).resolve()
        for raw in supplied:
            try:
                item = self.report_governance.validate_event_evidence(dict(raw))
                if item["source_class"] != "AUTHORITY" or item["source_tier"] != "OFFICIAL":
                    raise ResearchContentIntegrationError("OFFICIAL_IR_AUTHORITY_CLASS_INVALID")
                receipt_path = (self.package_root / item["source_locator"]).resolve()
                if not receipt_path.is_relative_to(receipt_root) or not receipt_path.is_file():
                    raise ResearchContentIntegrationError("OFFICIAL_IR_RECEIPT_NOT_BOUND")
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                provenance = item.get("provenance") or {}
                raw_relative = provenance.get("raw_artifact_path")
                if not isinstance(raw_relative, str):
                    raise ResearchContentIntegrationError("OFFICIAL_IR_RAW_RECEIPT_REQUIRED")
                raw_path = (self.package_root / raw_relative).resolve()
                if not raw_path.is_relative_to(receipt_root) or not raw_path.is_file():
                    raise ResearchContentIntegrationError("OFFICIAL_IR_RAW_RECEIPT_REQUIRED")
                raw_hash = sha256_file(raw_path)
                if not (
                    receipt.get("authorizationIdentity") == OFFICIAL_IR_AUTHORIZATION_ID
                    and receipt.get("actionable") is False
                    and receipt.get("source_class") == "AUTHORITY"
                    and receipt.get("source_hash") == raw_hash == item["source_hash"]
                    and receipt.get("raw_sha256") == raw_hash
                    and provenance.get("raw_sha256") == raw_hash
                    and provenance.get("receipt_id") == receipt.get("receipt_id")
                ):
                    raise ResearchContentIntegrationError("OFFICIAL_IR_PROVENANCE_HASH_MISMATCH")
                governed.append(item)
            except (ResearchContentIntegrationError, ValueError, TypeError, KeyError, OSError, json.JSONDecodeError) as exc:
                source_id = raw.get("source_id", "UNKNOWN") if isinstance(raw, Mapping) else "UNKNOWN"
                evidence_validation_failures.append({"source_id": str(source_id), "error": str(exc) or type(exc).__name__})
        if supplied and not governed:
            first_error = evidence_validation_failures[0]["error"] if evidence_validation_failures else "UNKNOWN"
            raise ResearchContentIntegrationError(f"OFFICIAL_IR_EVIDENCE_VALIDATION_FAILED:{first_error}")
        evidence, duplicate_count = self._deduplicate(governed)
        revision = scan_result.get("revision")
        evaluated_at = scan_result.get("evaluated_at_utc")
        if not isinstance(report_key, str) or not isinstance(revision, int) or not isinstance(evaluated_at, str):
            raise ResearchContentIntegrationError("OFFICIAL_IR_REPORT_IDENTITY_INVALID")
        cross_validation = self.report_governance.evaluate_cross_validation(evidence)
        trigger = self.report_governance.evaluate_report_trigger(
            report_key=report_key,
            revision=revision,
            event_evidence=evidence,
            evaluated_at_utc=evaluated_at,
        )
        display_state = (
            "REPORT" if trigger["decision"] == "TRIGGERED_INTERNAL_REPORT"
            else "WATCH" if scan_result.get("schedule") or evidence
            else "OBSERVE"
        )
        return {
            "record_type": "P1008_RESEARCH_CONTENT_INTEGRATION_V1",
            "report_key": report_key,
            "revision": revision,
            "evaluated_at_utc": evaluated_at,
            "run_identity": {
                "run_id": scan_result.get("run_id"),
                "scan_id": scan_result.get("run_id"),
                "producer_id": _PRODUCER_ID,
            },
            "authority": {
                **dict(self.authority.manifest_summary()),
                "manifest_sha256": sha256_file(self.package_root / AuthorityAdapter.MANIFEST_PATH),
                "official_ir_authorization": OFFICIAL_IR_AUTHORIZATION_ID,
                "writes": 0,
            },
            "discovery": {
                "completed_before_trigger": True,
                "provider": "OFFICIAL_IR_ADAPTER",
                "provider_identity": OFFICIAL_IR_AUTHORIZATION_ID,
                "candidate_count": 0,
                "candidate_source_ids": [],
                "transport_mode": "GOVERNED_OFFICIAL_ONLY",
            },
            "official_ir": {
                "status": scan_result.get("status"),
                "scan_status": scan_result.get("scan_status"),
                "schedule": scan_result.get("schedule"),
                "receipt_paths": list(scan_result.get("receipt_paths") or []),
                "scan_integrity_valid": True,
                "coverage_complete": scan_result["coverage_complete"],
                "successful_sources": list(scan_result["successful_sources"]),
                "failed_sources": list(scan_result["failed_sources"]),
                "active_fiscal_period": scan_result.get("active_fiscal_period", ""),
                "active_canonical_event_id": canonical_event_id,
                "active_report_key": report_key,
                "detected_evidence_count": scan_result.get("detected_evidence_count", len(supplied)),
                "active_event_evidence_count": scan_result.get("active_event_evidence_count", len(supplied)),
                "historical_evidence_count": scan_result.get("historical_evidence_count", 0),
                "evidence_validation_failures": evidence_validation_failures,
            },
            "evidence": {
                "input_count": len(governed),
                "qualified_count": len(evidence),
                "duplicate_count": duplicate_count,
                "qualified_evidence_ids": trigger["qualifying_evidence_ids"],
                "conflicts": [cross_validation["validation_status"]] if cross_validation["conflict_detected"] else [],
                "cross_validation": cross_validation,
            },
            "validated_event_evidence": evidence,
            "validated_evidence_lineage_ledger": self._lineage_ledger(evidence),
            "research_state": trigger["decision"],
            "display_state": display_state,
            "report_trigger_decision": trigger,
            "handoff_eligible": trigger["decision"] == "TRIGGERED_INTERNAL_REPORT",
            "handoff_receipt": None,
            "authority_writes": 0,
            "core_view_changes": 0,
            "evidence_ledger_writes": 0,
            "formal_reports_generated": 0,
            "publication_count": 0,
            "external_live_calls": 0,
            "report_generated": False,
            "actionable": False,
        }

    def run(
        self,
        *,
        validated_scan: discovery_governance.ValidatedDiscoveryScan,
        query: str,
        report_key: str,
        revision: int,
        evaluated_at_utc: str,
        news_scan_snapshot: Mapping[str, Any] | None,
        qualified_event_evidence: Iterable[Mapping[str, Any]],
        transport: OfflineFixtureTransport | None,
        discovery_qualifications: Iterable[Mapping[str, Any]] = (),
        auth_mode: str = "NONE",
    ) -> dict[str, Any]:
        """Execute Discovery first; only then evaluate the existing report gate."""

        if transport is not None and type(transport) is not OfflineFixtureTransport:
            raise ResearchContentIntegrationError("UNAUTHORIZED_DISCOVERY_TRANSPORT")
        if self._issued_scans.get(validated_scan.scan_id) is not validated_scan:
            raise ResearchContentIntegrationError("DISCOVERY_SCAN_NOT_TRUSTED")
        skill_request = discovery_governance.build_discovery_skill_request(
            validated_scan=validated_scan,
            query=query,
            auth_mode=auth_mode,
        )
        staging = execute_governed_search(
            validated_scan,
            skill_request,
            allow_anonymous=auth_mode == "NONE",
            transport=transport,
            retrieved_at_utc=evaluated_at_utc,
        )
        news_locators = self._news_locators(news_scan_snapshot)
        discovery_evidence = self._qualify_discovery(
            discovery_qualifications, staging["candidates"]
        )
        evidence = self._validate_evidence_provenance(
            [*qualified_event_evidence, *discovery_evidence],
            discovery_candidates=staging["candidates"],
            news_locators=news_locators,
        )
        evidence, duplicate_count = self._deduplicate(evidence)
        cross_validation = self.report_governance.evaluate_cross_validation(evidence)
        trigger = self.report_governance.evaluate_report_trigger(
            report_key=report_key,
            revision=revision,
            event_evidence=evidence,
            evaluated_at_utc=evaluated_at_utc,
        )
        if trigger["decision"] == "TRIGGERED_INTERNAL_REPORT":
            display_state = "REPORT"
        elif cross_validation["evidence_state"] in {"AUTHORITY_CONFLICT", "REVIEW_REQUIRED"}:
            display_state = "REVIEW_REQUIRED"
        elif evidence:
            display_state = "WATCH"
        else:
            display_state = "OBSERVE"

        handoff: dict[str, Any] | None = None
        if trigger["decision"] == "TRIGGERED_INTERNAL_REPORT" and not cross_validation["conflict_detected"]:
            payload = {
                "record_type": "P1008_GOVERNED_RESEARCH_HANDOFF",
                "schema_version": "1.0",
                "run_id": validated_scan.run_id,
                "report_key": report_key,
                "revision": revision,
                "trigger_decision_id": trigger["decision_id"],
                "qualified_evidence_ids": trigger["qualifying_evidence_ids"],
                "authority_manifest_sha256": validated_scan.authority_manifest_sha256,
                "handoff_eligible": True,
                "report_generated": False,
                "actionable": False,
            }
            handoff = {
                **payload,
                "receipt_id": "HANDOFF-" + sha256_bytes(canonical_json_bytes(payload))[:16],
            }

        authority_summary = dict(self.authority.manifest_summary())
        return {
            "record_type": "P1008_RESEARCH_CONTENT_INTEGRATION_V1",
            "report_key": report_key,
            "revision": revision,
            "evaluated_at_utc": evaluated_at_utc,
            "run_identity": {
                "run_id": validated_scan.run_id,
                "scan_id": validated_scan.scan_id,
                "producer_id": _PRODUCER_ID,
            },
            "authority": {
                **authority_summary,
                "manifest_sha256": validated_scan.authority_manifest_sha256,
                "writes": 0,
            },
            "discovery": {
                "completed_before_trigger": True,
                "provider": staging["provider"],
                "provider_identity": staging["governed_provider_identity"],
                "skill_call_receipt": staging["receipt"],
                "candidate_count": len(staging["candidates"]),
                "candidate_source_ids": [item["source_id"] for item in staging["candidates"]],
                "transport_mode": (
                    "INJECTED_OFFLINE_FIXTURE"
                    if transport is not None
                    else "GOVERNED_RUNTIME"
                ),
            },
            "evidence": {
                "input_count": len(evidence) + duplicate_count,
                "qualified_count": len(evidence),
                "duplicate_count": duplicate_count,
                "qualified_evidence_ids": trigger["qualifying_evidence_ids"],
                "conflicts": [cross_validation["validation_status"]] if cross_validation["conflict_detected"] else [],
                "cross_validation": cross_validation,
            },
            # This is the already-validated G1 input, not a second evidence
            # ledger.  The runtime bridge seals the complete integration result
            # before Launcher may consume it.
            "validated_event_evidence": evidence,
            "validated_evidence_lineage_ledger": self._lineage_ledger(evidence),
            "research_state": trigger["decision"],
            "display_state": display_state,
            "report_trigger_decision": trigger,
            "handoff_eligible": handoff is not None,
            "handoff_receipt": handoff,
            "authority_writes": 0,
            "core_view_changes": 0,
            "evidence_ledger_writes": 0,
            "formal_reports_generated": 0,
            "publication_count": 0,
            "external_live_calls": (
                0
                if transport is not None
                else 1
            ),
            "report_generated": False,
            "actionable": False,
        }
