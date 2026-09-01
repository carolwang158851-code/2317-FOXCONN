"""Deterministic, side-effect-free P1008 G1 report-governance evaluator.

This module deliberately does not start jobs, write artifacts, inspect formal
authority, call a model, or contact a network service.  Runtime integration is
an explicitly later G1 stage.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys
from typing import Any, Iterable


MODULE_SRC = Path(__file__).resolve().parents[1] / "modules" / "p1008_research_plugin" / "src"
if str(MODULE_SRC) not in sys.path:
    sys.path.insert(0, str(MODULE_SRC))

from p1008_research_plugin.phaseb1_common import canonical_json_bytes, sha256_bytes


CONTRACT_VERSION = "1.0"
APPROVED_EVENT_TYPES = frozenset({
    "MONTHLY_REVENUE",
    "QUARTERLY_EARNINGS",
    "EARNINGS_CALL",
    "MATERIAL_COMPANY_DISCLOSURE",
    "APPLE_OFFICIAL_PRODUCT_EVENT",
    "APPLE_OFFICIAL_GUIDANCE_EVENT",
    "AI_SERVER_MAJOR_ORDER",
    "AI_SERVER_MATERIAL_SUPPLY_CHAIN_CHANGE",
    "MATERIAL_FX_CHANGE",
    "MATERIAL_TARIFF_OR_POLICY_CHANGE",
    "APPROVED_PRICE_VOLUME_POSITIONING_ANOMALY",
    "MAJOR_EVENT",
})
G1_EVENT_TYPES = frozenset({
    "DAILY", "MONTHLY_REVENUE", "QUARTERLY_EARNINGS", "MAJOR_EVENT",
})
MAJOR_EVENT_SOURCE_TYPES = APPROVED_EVENT_TYPES - {
    "MONTHLY_REVENUE", "QUARTERLY_EARNINGS", "MAJOR_EVENT",
}
SOURCE_TYPES = frozenset({
    "OFFICIAL_WEB", "AUTHORITY_DATASET", "COMPANY_FILING", "REGULATORY_FILING",
    "LOCAL_CANONICAL_ARTIFACT", "NEWS_MEDIA", "PLUGIN_EVIDENCE", "OTHER",
})
SOURCE_CLASSES = frozenset({"AUTHORITY", "SECONDARY", "DISCOVERY"})
SOURCE_TIERS = frozenset({"CSV_AUTHORITY", "OFFICIAL", "PUBLIC_MARKET", "MEDIA", "OWNER_NOTE", "UNVERIFIED"})
# This preserves the frozen source policy's "OFFICIAL_OR_CORROBORATED" rule:
# one media source is not enough; two independent MEDIA editorial chains are.
HIGH_QUALITY_SECONDARY_TIERS = frozenset({"MEDIA"})
VERIFIED_EVENT_STATUSES = frozenset({"MATERIAL_EVENT_CONFIRMED", "VERIFIED"})
VERIFICATION_STATUSES = frozenset({"VERIFIED", "OFFICIAL_VERIFIED", "VALIDATED"})
SHA256 = re.compile(r"^[A-F0-9]{64}$")
REPORT_KEY = re.compile(r"^P1008_[A-Z0-9_:-]+$")
OWNER_REFERENCE = re.compile(r"^OWNER_[A-Z0-9_:-]+$")
EVENT_EVIDENCE_FIELDS = frozenset({
    "event_id", "event_type", "event_status", "occurred_at_utc", "published_at_utc", "received_at_utc", "data_cutoff",
    "source_id", "source_type", "source_class", "source_locator", "source_url", "source_tier", "source_hash", "originating_chain_id",
    "evidence_ids", "claim_summary", "affected_kpis", "materiality", "novelty", "evidence_status", "validation_status",
    "confidence", "quality_metadata", "provenance", "canonical_event_id", "verification_status", "counter_evidence_ids",
    "missing_evidence", "source_conflicts", "actionable",
})


class GovernanceValidationError(ValueError):
    """Raised whenever a governance contract cannot be proven."""


def _required(value: dict[str, Any], *names: str) -> None:
    missing = [name for name in names if value.get(name) in (None, "")]
    if missing:
        raise GovernanceValidationError(f"Missing required governance fields: {', '.join(missing)}")


def _false(value: dict[str, Any], field: str = "actionable") -> None:
    if value.get(field) is not False:
        raise GovernanceValidationError(f"{field} must be false")


def _owner_reference(value: str | None) -> None:
    if not isinstance(value, str) or not OWNER_REFERENCE.fullmatch(value):
        raise GovernanceValidationError("Owner approval requires a stable OWNER_ reference")


def _decision_id(prefix: str, payload: dict[str, Any]) -> str:
    return f"{prefix}-{sha256_bytes(canonical_json_bytes(payload))[:16]}"


def _validate_decision_identity(prefix: str, decision: dict[str, Any]) -> None:
    decision_id = decision.get("decision_id")
    _required(decision, "decision_id")
    payload = {key: value for key, value in decision.items() if key != "decision_id"}
    if decision_id != _decision_id(prefix, payload):
        raise GovernanceValidationError("Referenced decision identity cannot be validated")


def _no_unknown_fields(value: dict[str, Any], allowed: frozenset[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise GovernanceValidationError(f"Unknown governed fields: {', '.join(unknown)}")


def _report_identity(report_key: str, revision: int) -> None:
    if not isinstance(report_key, str) or not REPORT_KEY.fullmatch(report_key):
        raise GovernanceValidationError("Invalid stable report_key")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise GovernanceValidationError("revision must be an integer >= 1")


def validate_event_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Validate supplied evidence metadata without researching or interpreting it."""

    _no_unknown_fields(evidence, EVENT_EVIDENCE_FIELDS)
    _required(
        evidence, "event_id", "event_type", "event_status", "occurred_at_utc",
        "published_at_utc", "received_at_utc", "data_cutoff", "source_id",
        "source_type", "source_class", "source_locator", "source_tier", "source_hash", "originating_chain_id",
        "evidence_ids", "claim_summary", "affected_kpis", "materiality",
        "novelty", "evidence_status", "validation_status", "confidence", "quality_metadata",
        "provenance", "canonical_event_id", "verification_status",
    )
    _false(evidence)
    if evidence["source_type"] not in SOURCE_TYPES:
        raise GovernanceValidationError("Unsupported source_type")
    if evidence["source_class"] not in SOURCE_CLASSES:
        raise GovernanceValidationError("Unsupported source_class")
    if evidence["source_tier"] not in SOURCE_TIERS:
        raise GovernanceValidationError("source_tier is not allowed by the frozen source policy")
    if not isinstance(evidence["source_hash"], str) or not SHA256.fullmatch(evidence["source_hash"]):
        raise GovernanceValidationError("source_hash must be an uppercase SHA-256")
    if evidence["verification_status"] not in VERIFICATION_STATUSES:
        raise GovernanceValidationError("Evidence verification state is not valid")
    if evidence["validation_status"] not in VERIFICATION_STATUSES:
        raise GovernanceValidationError("Evidence validation state is not valid")
    if evidence["source_class"] == "DISCOVERY" and evidence["evidence_status"] == "CONFIRMED":
        raise GovernanceValidationError("Discovery evidence cannot self-confirm an event")
    if not isinstance(evidence["confidence"], (int, float)) or isinstance(evidence["confidence"], bool) or not 0 <= evidence["confidence"] <= 1:
        raise GovernanceValidationError("confidence must be numeric from 0 to 1")
    if not isinstance(evidence["quality_metadata"], dict) or not isinstance(evidence["provenance"], dict):
        raise GovernanceValidationError("quality_metadata and provenance must be objects")
    if not isinstance(evidence["evidence_ids"], list) or not all(isinstance(x, str) and x for x in evidence["evidence_ids"]):
        raise GovernanceValidationError("evidence_ids must contain stable identifiers")
    if evidence.get("source_url") is not None and not isinstance(evidence["source_url"], str):
        raise GovernanceValidationError("source_url is optional but must be a string when supplied")
    return dict(evidence)


def normalize_g1_event_type(event_type: str) -> str:
    """Collapse governed source events onto the four report-routing classes."""

    if event_type in G1_EVENT_TYPES:
        return event_type
    if event_type in MAJOR_EVENT_SOURCE_TYPES:
        return "MAJOR_EVENT"
    return event_type


def build_validated_evidence_lineage_ledger(
    event_evidence: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Build a sealed, non-authoritative handoff into the G1 ledger interface.

    The returned envelope is embedded in the integration artifact.  It does not
    promote evidence, write authority, or create a second mutable evidence store.
    """

    evidence = [validate_event_evidence(item) for item in event_evidence]
    records: list[dict[str, Any]] = []
    for sequence, item in enumerate(evidence, start=1):
        if item["source_class"] == "DISCOVERY":
            channel = "GOVERNED_ANYSEARCH"
        elif item["source_class"] == "SECONDARY":
            channel = "NEWS"
        elif item["source_type"] in {
            "OFFICIAL_WEB", "COMPANY_FILING", "REGULATORY_FILING",
        }:
            channel = "OFFICIAL_IR"
        else:
            channel = "AUTHORITY"
        body = {
            "sequence": sequence,
            "event_id": item["event_id"],
            "canonical_event_id": item["canonical_event_id"],
            "source_event_type": item["event_type"],
            "g1_event_type": normalize_g1_event_type(item["event_type"]),
            "source_channel": channel,
            "source_id": item["source_id"],
            "source_class": item["source_class"],
            "source_locator": item["source_locator"],
            "source_hash": item["source_hash"],
            "originating_chain_id": item["originating_chain_id"],
            "evidence_ids": item["evidence_ids"],
            "validation_status": item["validation_status"],
            "verification_status": item["verification_status"],
            "actionable": False,
        }
        records.append({**body, "record_sha256": sha256_bytes(canonical_json_bytes(body))})
    payload = {
        "record_type": "P1008_VALIDATED_EVIDENCE_LINEAGE_LEDGER_HANDOFF_V1",
        "schema_version": "1.0",
        "record_count": len(records),
        "records": records,
        "authoritative": False,
        "publishAuthorized": False,
        "actionable": False,
    }
    return {**payload, "ledger_sha256": sha256_bytes(canonical_json_bytes(payload))}


def validate_evidence_lineage_ledger(
    ledger: dict[str, Any], event_evidence: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Rebuild and compare the ledger handoff; any lineage drift fails closed."""

    expected = build_validated_evidence_lineage_ledger(event_evidence)
    if ledger != expected:
        raise GovernanceValidationError("Validated evidence lineage ledger mismatch")
    return dict(ledger)


def canonical_event_fingerprint(*, event_type: str, canonical_event_id: str, occurred_at_utc: str) -> str:
    """Create a portable event identity; it never contacts a discovery provider."""

    _required({"event_type": event_type, "canonical_event_id": canonical_event_id, "occurred_at_utc": occurred_at_utc}, "event_type", "canonical_event_id", "occurred_at_utc")
    return sha256_bytes(canonical_json_bytes({"event_type": event_type, "canonical_event_id": canonical_event_id, "occurred_at_utc": occurred_at_utc}))


def deduplicate_event_evidence(event_evidence: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Group original and syndicated evidence under one canonical event identity."""

    evidence = [validate_event_evidence(item) for item in event_evidence]
    if not evidence:
        raise GovernanceValidationError("Deduplication requires at least one evidence record")
    keys = {(item["event_type"], item["canonical_event_id"], item["occurred_at_utc"]) for item in evidence}
    if len(keys) != 1:
        raise GovernanceValidationError("Evidence records do not identify one canonical event")
    event_type, canonical_event_id, occurred_at_utc = next(iter(keys))
    fingerprint = canonical_event_fingerprint(event_type=event_type, canonical_event_id=canonical_event_id, occurred_at_utc=occurred_at_utc)
    sources = sorted({item["source_id"] for item in evidence})
    return {
        "canonical_event_id": canonical_event_id, "event_fingerprint": fingerprint,
        "event_type": event_type, "source_ids": sources,
        "original_source_ids": sorted({item["source_id"] for item in evidence if item["source_class"] == "AUTHORITY"}),
        "syndicated_or_secondary_source_ids": sorted({item["source_id"] for item in evidence if item["source_class"] != "AUTHORITY"}),
        "duplicate_count": len(evidence) - len(sources), "actionable": False,
    }


def evaluate_cross_validation(event_evidence: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Route evidence without promoting Discovery material into authority or publication."""

    evidence = [validate_event_evidence(item) for item in event_evidence]
    if not evidence:
        return {"evidence_state": "WATCH", "validation_status": "NO_EVIDENCE", "authority_confirmation_required": False, "cross_validation_passed": False, "conflict_detected": False, "actionable": False}
    authority = [item for item in evidence if item["source_class"] == "AUTHORITY"]
    secondary = [item for item in evidence if item["source_class"] == "SECONDARY"]
    discovery = [item for item in evidence if item["source_class"] == "DISCOVERY"]
    claimed_facts = {item["claim_summary"] for item in authority}
    conflict = bool(authority and any(item["claim_summary"] not in claimed_facts for item in secondary + discovery))
    if conflict:
        return {"evidence_state": "AUTHORITY_CONFLICT", "validation_status": "AUTHORITY_NEWS_CONFLICT", "authority_confirmation_required": True, "cross_validation_passed": False, "conflict_detected": True, "actionable": False}
    if authority:
        return {"evidence_state": "AUTHORITY_CONFIRMED", "validation_status": "AUTHORITY_CONFIRMED", "authority_confirmation_required": False, "cross_validation_passed": True, "conflict_detected": False, "actionable": False}
    high_quality_secondary = [item for item in secondary if item["source_tier"] in HIGH_QUALITY_SECONDARY_TIERS]
    independent_secondary = {(item["source_id"], item["originating_chain_id"]) for item in high_quality_secondary}
    source_ids = {source_id for source_id, _ in independent_secondary}
    chain_ids = {chain_id for _, chain_id in independent_secondary}
    if len(source_ids) >= 2 and len(chain_ids) >= 2:
        return {"evidence_state": "CROSS_VALIDATED", "validation_status": "SECONDARY_CROSS_VALIDATED", "authority_confirmation_required": False, "cross_validation_passed": True, "conflict_detected": False, "actionable": False}
    if discovery:
        return {"evidence_state": "WATCH", "validation_status": "DISCOVERY_PENDING_VALIDATION", "authority_confirmation_required": True, "cross_validation_passed": False, "conflict_detected": False, "actionable": False}
    return {"evidence_state": "REVIEW_REQUIRED", "validation_status": "INSUFFICIENT_CROSS_VALIDATION", "authority_confirmation_required": True, "cross_validation_passed": False, "conflict_detected": False, "actionable": False}


def evaluate_provider_failure(*, provider_id: str, failure_class: str, retryable: bool) -> dict[str, Any]:
    """Represent provider failure without retrying, writing authority, or promoting discovery evidence."""

    _required({"provider_id": provider_id, "failure_class": failure_class}, "provider_id", "failure_class")
    allowed = {"SUCCESS_NO_RELEVANT_EVENT", "HTTP_403_POLICY_BLOCKED", "TIMEOUT_TRANSIENT", "SOURCE_FAILED"}
    if failure_class not in allowed:
        raise GovernanceValidationError("Unknown provider failure classification")
    return {
        "provider_id": provider_id, "failure_class": failure_class,
        "status": "PASS" if failure_class == "SUCCESS_NO_RELEVANT_EVENT" else "FAIL_CLOSED",
        "retry_performed": False, "retryable": bool(retryable) and failure_class == "TIMEOUT_TRANSIENT",
        "authority_write_permitted": False, "actionable": False,
    }


def validate_materiality_threshold_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Validate policy metadata only; this function never calculates a threshold."""

    _required(policy, "threshold_policy_id", "metric", "operator", "threshold", "window", "minimum_observations", "effective_from", "version", "owner_approved", "status")
    if policy.get("owner_approved") is True:
        _required(policy, "approval_reference")
        if policy.get("status") != "APPROVED":
            raise GovernanceValidationError("Owner-approved threshold policy must be APPROVED")
    return dict(policy)


def _event_is_confirmed(evidence: dict[str, Any]) -> bool:
    return evidence["source_class"] != "DISCOVERY" and evidence["event_status"] in VERIFIED_EVENT_STATUSES and evidence["verification_status"] in VERIFICATION_STATUSES and evidence["validation_status"] in VERIFICATION_STATUSES


def evaluate_report_trigger(
    *, report_key: str, revision: int, event_evidence: Iterable[dict[str, Any]], evaluated_at_utc: str,
    threshold_policies: Iterable[dict[str, Any]] = (), previous_decision_id: str | None = None,
) -> dict[str, Any]:
    """Return the governed trigger decision with no report or library side effects."""

    _report_identity(report_key, revision)
    evidence = [validate_event_evidence(item) for item in event_evidence]
    base = {
        "report_key": report_key, "revision": revision,
        "qualifying_evidence_ids": sorted({evidence_id for item in evidence for evidence_id in item["evidence_ids"]}),
        "threshold_policy_ids": [], "authority_cutoffs": sorted({item["data_cutoff"] for item in evidence}),
        "evaluated_at_utc": evaluated_at_utc, "previous_decision_id": previous_decision_id,
        "report_generated": False, "archive_report_created": False, "library_appended": False,
        "private_library_eligible": False, "actionable": False,
    }
    if not evidence:
        payload = {**base, "event_type": "NONE", "decision": "NO_MATERIAL_CHANGE", "trigger_reason": "No supplied material event evidence", "material_event_confirmed": False, "report_trigger_valid": False, "status": "PASS"}
        return {**payload, "decision_id": _decision_id("TRIGGER", payload)}
    event_types = {item["event_type"] for item in evidence}
    if len(event_types) != 1:
        payload = {**base, "event_type": "MULTIPLE", "decision": "FAIL_CLOSED", "trigger_reason": "A report decision requires one governed event type", "material_event_confirmed": False, "report_trigger_valid": False, "status": "FAIL"}
        return {**payload, "decision_id": _decision_id("TRIGGER", payload)}
    event_type = next(iter(event_types))
    if event_type not in APPROVED_EVENT_TYPES:
        payload = {**base, "event_type": event_type, "decision": "TRIGGER_REJECTED_UNAPPROVED_EVENT_TYPE", "trigger_reason": "Event type is not Owner-approved", "material_event_confirmed": False, "report_trigger_valid": False, "status": "PASS"}
        return {**payload, "decision_id": _decision_id("TRIGGER", payload)}
    confirmed = all(_event_is_confirmed(item) for item in evidence)
    if not confirmed:
        payload = {**base, "event_type": event_type, "decision": "TRIGGER_REJECTED_INSUFFICIENT_EVIDENCE", "trigger_reason": "Material evidence is not confirmed", "material_event_confirmed": False, "report_trigger_valid": False, "status": "PASS"}
        return {**payload, "decision_id": _decision_id("TRIGGER", payload)}
    cross_validation = evaluate_cross_validation(evidence)
    if cross_validation["cross_validation_passed"] is not True:
        payload = {**base, "event_type": event_type, "decision": "TRIGGER_REJECTED_INSUFFICIENT_EVIDENCE", "trigger_reason": cross_validation["validation_status"], "material_event_confirmed": True, "report_trigger_valid": False, "status": "PASS"}
        return {**payload, "decision_id": _decision_id("TRIGGER", payload)}
    policy_ids: list[str] = []
    if event_type == "APPROVED_PRICE_VOLUME_POSITIONING_ANOMALY":
        policies = [validate_materiality_threshold_policy(item) for item in threshold_policies]
        policies = [item for item in policies if item.get("owner_approved") is True and item.get("status") == "APPROVED"]
        if not policies:
            payload = {**base, "event_type": event_type, "decision": "TRIGGER_REJECTED_MISSING_THRESHOLD_POLICY", "trigger_reason": "No Owner-approved threshold policy supplied", "material_event_confirmed": True, "report_trigger_valid": False, "status": "PASS"}
            return {**payload, "decision_id": _decision_id("TRIGGER", payload)}
        policy_ids = [item["threshold_policy_id"] for item in policies]
    payload = {**base, "event_type": event_type, "decision": "TRIGGERED_INTERNAL_REPORT", "trigger_reason": "Approved event type with confirmed supplied evidence", "threshold_policy_ids": policy_ids, "material_event_confirmed": True, "report_trigger_valid": True, "status": "PASS"}
    return {**payload, "decision_id": _decision_id("TRIGGER", payload)}


def evaluate_core_view_change(*, supporting_evidence_ids: Iterable[str], counter_evidence_ids: Iterable[str], official_confirmation: bool, independent_high_quality_source_count: int, financial_reflection: bool, thesis_invalidation: bool, owner_approved: bool, owner_approval_reference: str | None, prior_core_view_hash: str, proposed_core_view_hash: str, supporting_evidence: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    """Determine review eligibility; Owner approval is the sole change authorization."""

    if not SHA256.fullmatch(prior_core_view_hash) or not SHA256.fullmatch(proposed_core_view_hash):
        raise GovernanceValidationError("Core-view hashes must be uppercase SHA-256")
    if not isinstance(independent_high_quality_source_count, int) or independent_high_quality_source_count < 0:
        raise GovernanceValidationError("independent_high_quality_source_count must be non-negative")
    if owner_approved:
        _owner_reference(owner_approval_reference)
    validated_support = [validate_event_evidence(item) for item in supporting_evidence]
    high_quality_independent_pairs = {
        (item["source_id"], item["originating_chain_id"]) for item in validated_support
        if item["source_class"] != "DISCOVERY" and item["source_tier"] in HIGH_QUALITY_SECONDARY_TIERS
    }
    high_quality_source_ids = {source_id for source_id, _ in high_quality_independent_pairs}
    high_quality_chain_ids = {chain_id for _, chain_id in high_quality_independent_pairs}
    proven_independent_count = min(len(high_quality_source_ids), len(high_quality_chain_ids))
    if independent_high_quality_source_count != proven_independent_count:
        raise GovernanceValidationError("Independent high-quality source count must match supplied evidence")
    reasons = []
    if official_confirmation: reasons.append("OFFICIAL_CONFIRMATION")
    if independent_high_quality_source_count >= 2: reasons.append("TWO_INDEPENDENT_HIGH_QUALITY_SOURCES")
    if financial_reflection: reasons.append("MATERIAL_FINANCIAL_REFLECTION")
    if thesis_invalidation: reasons.append("THESIS_INVALIDATION")
    eligible = bool(reasons)
    changed = eligible and owner_approved
    payload = {
        "prior_core_view_hash": prior_core_view_hash, "proposed_core_view_hash": proposed_core_view_hash,
        "supporting_evidence_ids": list(supporting_evidence_ids), "counter_evidence_ids": list(counter_evidence_ids),
        "official_confirmation": official_confirmation, "independent_high_quality_source_count": independent_high_quality_source_count,
        "financial_reflection": financial_reflection, "thesis_invalidation": thesis_invalidation,
        "eligibility": eligible, "eligibility_reasons": reasons, "owner_approval_required": True,
        "owner_approved": owner_approved, "owner_approval_reference": owner_approval_reference,
        "decision": "CORE_VIEW_CHANGED" if changed else ("CORE_VIEW_CHANGE_ELIGIBLE" if eligible else "CORE_VIEW_CHANGE_NOT_ELIGIBLE"),
        "core_view_changed": changed, "status": "PASS", "actionable": False,
    }
    return {**payload, "decision_id": _decision_id("CORE", payload)}


def evaluate_publication(*, report_key: str, revision: int, report_hash: str, audience: str, fact_check_status: str, owner_approved: bool, owner_approval_reference: str | None, approved_at_utc: str | None = None, publication_target: str | None = None) -> dict[str, Any]:
    """Represent approval readiness only; external publication cannot occur here."""

    _report_identity(report_key, revision)
    if not SHA256.fullmatch(report_hash):
        raise GovernanceValidationError("report_hash must be an uppercase SHA-256")
    if owner_approved:
        _owner_reference(owner_approval_reference)
    ready = owner_approved and fact_check_status == "PASS"
    payload = {
        "report_key": report_key, "revision": revision, "report_hash": report_hash,
        "audience": audience, "fact_check_status": fact_check_status,
        "publication_status": "APPROVED_NOT_EXECUTED" if ready else "DENIED_BY_DEFAULT",
        "owner_approval_required": True, "owner_approved": owner_approved,
        "owner_approval_reference": owner_approval_reference, "approved_at_utc": approved_at_utc,
        "publication_target": publication_target, "publication_ready": ready,
        "published_externally": False, "status": "PASS", "actionable": False,
    }
    return {**payload, "decision_id": _decision_id("PUBLICATION", payload)}


def validate_model_provenance(provenance: dict[str, Any]) -> dict[str, Any]:
    """Validate optional operational metadata; it never becomes investment evidence."""

    _required(provenance, "model_provenance_id", "model_surface", "model_identifier", "input_receipt_ids", "output_artifact_hash", "started_at_utc", "completed_at_utc", "status", "model_change_did_not_modify_runtime_configuration", "project_runtime_model_allowlist_unchanged")
    _false(provenance)
    if not SHA256.fullmatch(provenance["output_artifact_hash"]):
        raise GovernanceValidationError("output_artifact_hash must be an uppercase SHA-256")
    if provenance["model_change_did_not_modify_runtime_configuration"] is not True or provenance["project_runtime_model_allowlist_unchanged"] is not True:
        raise GovernanceValidationError("G1 prohibits runtime model configuration changes")
    def contains_estimate(value: Any) -> bool:
        if isinstance(value, dict):
            return any(key in {"estimated_cost", "cost_usd", "estimated_tokens"} or contains_estimate(item) for key, item in value.items())
        if isinstance(value, list):
            return any(contains_estimate(item) for item in value)
        return False
    if contains_estimate(provenance):
        raise GovernanceValidationError("Model provenance cannot estimate cost or usage")
    return dict(provenance)


def evaluate_private_library_eligibility(*, material_event_confirmed: bool, report_trigger_valid: bool, report_validation_pass: bool, actionable: bool) -> dict[str, Any]:
    eligible = material_event_confirmed and report_trigger_valid and report_validation_pass and actionable is False
    return {"private_library_eligible": eligible, "library_appended": False, "actionable": False}


def build_report_decision_receipt(*, receipt_id: str, report_key: str, revision: int, authority_cutoffs: Iterable[str], event_evidence_ids: Iterable[str], report_trigger_decision: dict[str, Any], core_view_change_decision: dict[str, Any], publication_decision: dict[str, Any], model_provenances: Iterable[dict[str, Any]], report_validation_pass: bool, report_artifact_hashes: Iterable[str], created_at_utc: str) -> dict[str, Any]:
    """Bind valid decisions into a canonical, non-writing receipt payload."""

    _report_identity(report_key, revision)
    if report_trigger_decision.get("report_key") != report_key or report_trigger_decision.get("revision") != revision:
        raise GovernanceValidationError("Report trigger identity mismatch")
    if publication_decision.get("report_key") != report_key or publication_decision.get("revision") != revision:
        raise GovernanceValidationError("Publication identity mismatch")
    _false(report_trigger_decision); _false(core_view_change_decision); _false(publication_decision)
    _validate_decision_identity("TRIGGER", report_trigger_decision)
    _validate_decision_identity("CORE", core_view_change_decision)
    _validate_decision_identity("PUBLICATION", publication_decision)
    if report_trigger_decision.get("status") != "PASS" or core_view_change_decision.get("status") != "PASS" or publication_decision.get("status") != "PASS":
        raise GovernanceValidationError("A receipt cannot bind a failed decision")
    if set(event_evidence_ids) != set(report_trigger_decision.get("qualifying_evidence_ids", [])):
        raise GovernanceValidationError("Receipt evidence references do not match trigger evidence")
    provenances = [validate_model_provenance(item) for item in model_provenances]
    hashes = list(report_artifact_hashes)
    if not all(isinstance(item, str) and SHA256.fullmatch(item) for item in hashes):
        raise GovernanceValidationError("Report artifact hashes must be uppercase SHA-256")
    private = evaluate_private_library_eligibility(
        material_event_confirmed=report_trigger_decision.get("material_event_confirmed") is True,
        report_trigger_valid=report_trigger_decision.get("report_trigger_valid") is True,
        report_validation_pass=report_validation_pass,
        actionable=False,
    )
    receipt = {
        "receipt_id": receipt_id, "report_key": report_key, "revision": revision,
        "authority_cutoffs": list(authority_cutoffs), "event_evidence_ids": list(event_evidence_ids),
        "report_trigger_decision_id": report_trigger_decision.get("decision_id"),
        "core_view_change_decision_id": core_view_change_decision.get("decision_id"),
        "publication_decision_id": publication_decision.get("decision_id"),
        "model_provenance_ids": [item["model_provenance_id"] for item in provenances],
        "report_validation_pass": report_validation_pass, "archive_eligibility": private["private_library_eligible"],
        "private_library_eligible": private["private_library_eligible"], "library_appended": False,
        "report_artifact_hashes": hashes, "created_at_utc": created_at_utc, "status": "PASS", "actionable": False,
    }
    receipt["canonical_sha256"] = sha256_bytes(canonical_json_bytes(receipt))
    return receipt


TRIGGER_ISSUANCE_SCHEMA_VERSION = "1.0"
TRIGGER_ISSUANCE_STATES = frozenset({"ISSUED", "CONSUMED"})


def _validate_issuable_trigger(trigger: dict[str, Any]) -> None:
    """Require an already validated G1 result before research can be issued."""
    _validate_decision_identity("TRIGGER", trigger)
    if not (
        trigger.get("decision") == "TRIGGERED_INTERNAL_REPORT"
        and trigger.get("material_event_confirmed") is True
        and trigger.get("report_trigger_valid") is True
        and trigger.get("status") == "PASS"
        and trigger.get("actionable") is False
    ):
        raise GovernanceValidationError("Trigger is not eligible for trusted research issuance")
    if trigger.get("authority_conflict") is True or trigger.get("conflict_detected") is True:
        raise GovernanceValidationError("Authority conflict blocks trusted research issuance")


def _validate_report_receipt(receipt: dict[str, Any]) -> None:
    _required(receipt, "receipt_id", "canonical_sha256", "report_key", "revision")
    _false(receipt)
    expected = sha256_bytes(canonical_json_bytes({
        key: value for key, value in receipt.items() if key != "canonical_sha256"
    }))
    if receipt.get("canonical_sha256") != expected:
        raise GovernanceValidationError("Report decision receipt canonical hash mismatch")


def build_trigger_issuance_receipt(*, issuance_receipt_id: str, report_key: str,
                                   revision: int, event_reference: str,
                                   event_fingerprint: str, event_type: str,
                                   report_trigger_decision: dict[str, Any],
                                   report_decision_receipt: dict[str, Any],
                                   producer_id: str, run_id: str,
                                   created_at_utc: str) -> dict[str, Any]:
    """Build the pre-research provenance record; this function does not write it."""
    _report_identity(report_key, revision)
    _validate_issuable_trigger(report_trigger_decision)
    _validate_report_receipt(report_decision_receipt)
    if report_trigger_decision.get("report_key") != report_key or report_trigger_decision.get("revision") != revision:
        raise GovernanceValidationError("Issuance trigger report identity mismatch")
    if report_trigger_decision.get("event_type") != event_type:
        raise GovernanceValidationError("Issuance trigger event type mismatch")
    if report_decision_receipt.get("report_key") != report_key or report_decision_receipt.get("revision") != revision:
        raise GovernanceValidationError("Issuance receipt report identity mismatch")
    if report_decision_receipt.get("report_trigger_decision_id") != report_trigger_decision.get("decision_id"):
        raise GovernanceValidationError("Issuance receipt trigger reference mismatch")
    if not all(isinstance(item, str) and item for item in (
        issuance_receipt_id, event_reference, event_fingerprint, event_type,
        producer_id, run_id, created_at_utc,
    )) or not SHA256.fullmatch(event_fingerprint):
        raise GovernanceValidationError("Invalid trigger issuance context")
    payload = {
        "issuance_receipt_id": issuance_receipt_id,
        "receipt_schema_version": TRIGGER_ISSUANCE_SCHEMA_VERSION,
        "report_key": report_key,
        "revision": revision,
        "event_reference": event_reference,
        "event_fingerprint": event_fingerprint,
        "event_type": event_type,
        "trigger_decision_id": report_trigger_decision["decision_id"],
        "report_decision_receipt_id": report_decision_receipt["receipt_id"],
        "report_decision_receipt_hash": report_decision_receipt["canonical_sha256"],
        "producer_id": producer_id,
        "run_id": run_id,
        "created_at": created_at_utc,
        "actionable": False,
    }
    return {**payload, "receipt_hash": sha256_bytes(canonical_json_bytes(payload))}


def validate_trigger_issuance_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    required = {
        "issuance_receipt_id", "receipt_schema_version", "report_key", "revision",
        "event_reference", "event_fingerprint", "event_type", "trigger_decision_id",
        "report_decision_receipt_id", "report_decision_receipt_hash", "producer_id",
        "run_id", "created_at", "actionable", "receipt_hash",
    }
    if set(receipt) != required:
        raise GovernanceValidationError("Trigger issuance receipt shape mismatch")
    if receipt.get("receipt_schema_version") != TRIGGER_ISSUANCE_SCHEMA_VERSION:
        raise GovernanceValidationError("Unsupported trigger issuance receipt schema")
    _report_identity(receipt.get("report_key"), receipt.get("revision"))
    _false(receipt)
    for field in ("event_reference", "event_type", "trigger_decision_id", "report_decision_receipt_id", "producer_id", "run_id", "created_at"):
        if not isinstance(receipt.get(field), str) or not receipt[field]:
            raise GovernanceValidationError("Trigger issuance receipt context is invalid")
    for field in ("event_fingerprint", "report_decision_receipt_hash", "receipt_hash"):
        if not isinstance(receipt.get(field), str) or not SHA256.fullmatch(receipt[field]):
            raise GovernanceValidationError("Trigger issuance receipt hash is invalid")
    expected = sha256_bytes(canonical_json_bytes({key: value for key, value in receipt.items() if key != "receipt_hash"}))
    if receipt["receipt_hash"] != expected:
        raise GovernanceValidationError("Trigger issuance receipt hash mismatch")
    return dict(receipt)


def build_trigger_issuance_index_entry(*, receipt: dict[str, Any], receipt_locator: str,
                                       state: str = "ISSUED") -> dict[str, Any]:
    receipt = validate_trigger_issuance_receipt(receipt)
    if state not in TRIGGER_ISSUANCE_STATES or not isinstance(receipt_locator, str) or not receipt_locator:
        raise GovernanceValidationError("Invalid trigger issuance index state")
    return {
        "issuance_receipt_id": receipt["issuance_receipt_id"],
        "issuance_receipt_hash": receipt["receipt_hash"],
        "receipt_locator": receipt_locator,
        "report_key": receipt["report_key"], "revision": receipt["revision"],
        "event_reference": receipt["event_reference"], "event_fingerprint": receipt["event_fingerprint"],
        "trigger_decision_id": receipt["trigger_decision_id"], "producer_id": receipt["producer_id"],
        "run_id": receipt["run_id"], "created_at": receipt["created_at"],
        "state": state, "actionable": False,
    }


def validate_trigger_issuance_index_entry(entry: dict[str, Any]) -> dict[str, Any]:
    required = {
        "issuance_receipt_id", "issuance_receipt_hash", "receipt_locator", "report_key", "revision",
        "event_reference", "event_fingerprint", "trigger_decision_id", "producer_id", "run_id",
        "created_at", "state", "actionable",
    }
    if set(entry) != required:
        raise GovernanceValidationError("Trigger issuance index shape mismatch")
    _report_identity(entry.get("report_key"), entry.get("revision"))
    _false(entry)
    if entry.get("state") not in TRIGGER_ISSUANCE_STATES:
        raise GovernanceValidationError("Trigger issuance index state invalid")
    for field in ("issuance_receipt_id", "receipt_locator", "event_reference", "trigger_decision_id", "producer_id", "run_id", "created_at"):
        if not isinstance(entry.get(field), str) or not entry[field]:
            raise GovernanceValidationError("Trigger issuance index context invalid")
    for field in ("issuance_receipt_hash", "event_fingerprint"):
        if not isinstance(entry.get(field), str) or not SHA256.fullmatch(entry[field]):
            raise GovernanceValidationError("Trigger issuance index hash invalid")
    return dict(entry)
