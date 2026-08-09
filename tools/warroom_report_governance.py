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
})
SOURCE_TYPES = frozenset({
    "OFFICIAL_WEB", "AUTHORITY_DATASET", "COMPANY_FILING", "REGULATORY_FILING",
    "LOCAL_CANONICAL_ARTIFACT", "NEWS_MEDIA", "PLUGIN_EVIDENCE", "OTHER",
})
VERIFIED_EVENT_STATUSES = frozenset({"MATERIAL_EVENT_CONFIRMED", "VERIFIED"})
VERIFICATION_STATUSES = frozenset({"VERIFIED", "OFFICIAL_VERIFIED", "VALIDATED"})
SHA256 = re.compile(r"^[A-F0-9]{64}$")
REPORT_KEY = re.compile(r"^P1008_[A-Z0-9_:-]+$")


class GovernanceValidationError(ValueError):
    """Raised whenever a governance contract cannot be proven."""


def _required(value: dict[str, Any], *names: str) -> None:
    missing = [name for name in names if value.get(name) in (None, "")]
    if missing:
        raise GovernanceValidationError(f"Missing required governance fields: {', '.join(missing)}")


def _false(value: dict[str, Any], field: str = "actionable") -> None:
    if value.get(field) is not False:
        raise GovernanceValidationError(f"{field} must be false")


def _report_identity(report_key: str, revision: int) -> None:
    if not isinstance(report_key, str) or not REPORT_KEY.fullmatch(report_key):
        raise GovernanceValidationError("Invalid stable report_key")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise GovernanceValidationError("revision must be an integer >= 1")


def validate_event_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Validate supplied evidence metadata without researching or interpreting it."""

    _required(
        evidence, "event_id", "event_type", "event_status", "occurred_at_utc",
        "published_at_utc", "received_at_utc", "data_cutoff", "source_id",
        "source_type", "source_locator", "source_tier", "source_hash",
        "evidence_ids", "claim_summary", "affected_kpis", "materiality",
        "novelty", "verification_status",
    )
    _false(evidence)
    if evidence["source_type"] not in SOURCE_TYPES:
        raise GovernanceValidationError("Unsupported source_type")
    if not isinstance(evidence["source_tier"], int) or not 1 <= evidence["source_tier"] <= 5:
        raise GovernanceValidationError("source_tier must be an integer from 1 to 5")
    if not isinstance(evidence["source_hash"], str) or not SHA256.fullmatch(evidence["source_hash"]):
        raise GovernanceValidationError("source_hash must be an uppercase SHA-256")
    if evidence["verification_status"] not in VERIFICATION_STATUSES:
        raise GovernanceValidationError("Evidence verification state is not valid")
    if not isinstance(evidence["evidence_ids"], list) or not all(isinstance(x, str) and x for x in evidence["evidence_ids"]):
        raise GovernanceValidationError("evidence_ids must contain stable identifiers")
    if evidence.get("source_url") is not None and not isinstance(evidence["source_url"], str):
        raise GovernanceValidationError("source_url is optional but must be a string when supplied")
    return dict(evidence)


def validate_materiality_threshold_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Validate policy metadata only; this function never calculates a threshold."""

    _required(policy, "threshold_policy_id", "metric", "operator", "threshold", "window", "minimum_observations", "effective_from", "version", "owner_approved", "status")
    if policy.get("owner_approved") is True:
        _required(policy, "approval_reference")
        if policy.get("status") != "APPROVED":
            raise GovernanceValidationError("Owner-approved threshold policy must be APPROVED")
    return dict(policy)


def _event_is_confirmed(evidence: dict[str, Any]) -> bool:
    return evidence["event_status"] in VERIFIED_EVENT_STATUSES and evidence["verification_status"] in VERIFICATION_STATUSES


def evaluate_report_trigger(
    *, report_key: str, revision: int, event_evidence: Iterable[dict[str, Any]], evaluated_at_utc: str,
    threshold_policies: Iterable[dict[str, Any]] = (), previous_decision_id: str | None = None,
) -> dict[str, Any]:
    """Return the governed trigger decision with no report or library side effects."""

    _report_identity(report_key, revision)
    evidence = [validate_event_evidence(item) for item in event_evidence]
    base = {
        "decision_id": "", "report_key": report_key, "revision": revision,
        "qualifying_evidence_ids": [item["event_id"] for item in evidence],
        "threshold_policy_ids": [], "authority_cutoffs": sorted({item["data_cutoff"] for item in evidence}),
        "evaluated_at_utc": evaluated_at_utc, "previous_decision_id": previous_decision_id,
        "report_generated": False, "archive_report_created": False, "library_appended": False,
        "private_library_eligible": False, "actionable": False,
    }
    if not evidence:
        return {**base, "event_type": "NONE", "decision": "NO_MATERIAL_CHANGE", "trigger_reason": "No supplied material event evidence", "material_event_confirmed": False, "report_trigger_valid": False, "status": "PASS"}
    event_types = {item["event_type"] for item in evidence}
    if len(event_types) != 1:
        return {**base, "event_type": "MULTIPLE", "decision": "FAIL_CLOSED", "trigger_reason": "A report decision requires one governed event type", "material_event_confirmed": False, "report_trigger_valid": False, "status": "FAIL"}
    event_type = next(iter(event_types))
    if event_type not in APPROVED_EVENT_TYPES:
        return {**base, "event_type": event_type, "decision": "TRIGGER_REJECTED_UNAPPROVED_EVENT_TYPE", "trigger_reason": "Event type is not Owner-approved", "material_event_confirmed": False, "report_trigger_valid": False, "status": "PASS"}
    confirmed = all(_event_is_confirmed(item) for item in evidence)
    if not confirmed:
        return {**base, "event_type": event_type, "decision": "TRIGGER_REJECTED_INSUFFICIENT_EVIDENCE", "trigger_reason": "Material evidence is not confirmed", "material_event_confirmed": False, "report_trigger_valid": False, "status": "PASS"}
    policy_ids: list[str] = []
    if event_type == "APPROVED_PRICE_VOLUME_POSITIONING_ANOMALY":
        policies = [validate_materiality_threshold_policy(item) for item in threshold_policies]
        policies = [item for item in policies if item.get("owner_approved") is True and item.get("status") == "APPROVED"]
        if not policies:
            return {**base, "event_type": event_type, "decision": "TRIGGER_REJECTED_MISSING_THRESHOLD_POLICY", "trigger_reason": "No Owner-approved threshold policy supplied", "material_event_confirmed": True, "report_trigger_valid": False, "status": "PASS"}
        policy_ids = [item["threshold_policy_id"] for item in policies]
    return {**base, "event_type": event_type, "decision": "TRIGGERED_INTERNAL_REPORT", "trigger_reason": "Approved event type with confirmed supplied evidence", "threshold_policy_ids": policy_ids, "material_event_confirmed": True, "report_trigger_valid": True, "status": "PASS"}


def evaluate_core_view_change(*, supporting_evidence_ids: Iterable[str], counter_evidence_ids: Iterable[str], official_confirmation: bool, independent_high_quality_source_count: int, financial_reflection: bool, thesis_invalidation: bool, owner_approved: bool, owner_approval_reference: str | None, prior_core_view_hash: str, proposed_core_view_hash: str) -> dict[str, Any]:
    """Determine review eligibility; Owner approval is the sole change authorization."""

    if not SHA256.fullmatch(prior_core_view_hash) or not SHA256.fullmatch(proposed_core_view_hash):
        raise GovernanceValidationError("Core-view hashes must be uppercase SHA-256")
    if not isinstance(independent_high_quality_source_count, int) or independent_high_quality_source_count < 0:
        raise GovernanceValidationError("independent_high_quality_source_count must be non-negative")
    if owner_approved and not owner_approval_reference:
        raise GovernanceValidationError("Owner approval requires a reference")
    reasons = []
    if official_confirmation: reasons.append("OFFICIAL_CONFIRMATION")
    if independent_high_quality_source_count >= 2: reasons.append("TWO_INDEPENDENT_HIGH_QUALITY_SOURCES")
    if financial_reflection: reasons.append("MATERIAL_FINANCIAL_REFLECTION")
    if thesis_invalidation: reasons.append("THESIS_INVALIDATION")
    eligible = bool(reasons)
    changed = eligible and owner_approved
    return {
        "decision_id": "", "prior_core_view_hash": prior_core_view_hash, "proposed_core_view_hash": proposed_core_view_hash,
        "supporting_evidence_ids": list(supporting_evidence_ids), "counter_evidence_ids": list(counter_evidence_ids),
        "official_confirmation": official_confirmation, "independent_high_quality_source_count": independent_high_quality_source_count,
        "financial_reflection": financial_reflection, "thesis_invalidation": thesis_invalidation,
        "eligibility": eligible, "eligibility_reasons": reasons, "owner_approval_required": True,
        "owner_approved": owner_approved, "owner_approval_reference": owner_approval_reference,
        "decision": "CORE_VIEW_CHANGED" if changed else ("CORE_VIEW_CHANGE_ELIGIBLE" if eligible else "CORE_VIEW_CHANGE_NOT_ELIGIBLE"),
        "core_view_changed": changed, "status": "PASS", "actionable": False,
    }


def evaluate_publication(*, report_key: str, revision: int, report_hash: str, audience: str, fact_check_status: str, owner_approved: bool, owner_approval_reference: str | None, approved_at_utc: str | None = None, publication_target: str | None = None) -> dict[str, Any]:
    """Represent approval readiness only; external publication cannot occur here."""

    _report_identity(report_key, revision)
    if not SHA256.fullmatch(report_hash):
        raise GovernanceValidationError("report_hash must be an uppercase SHA-256")
    if owner_approved and not owner_approval_reference:
        raise GovernanceValidationError("Owner-approved publication requires a reference")
    ready = owner_approved and fact_check_status == "PASS"
    return {
        "decision_id": "", "report_key": report_key, "revision": revision, "report_hash": report_hash,
        "audience": audience, "fact_check_status": fact_check_status,
        "publication_status": "APPROVED_NOT_EXECUTED" if ready else "DENIED_BY_DEFAULT",
        "owner_approval_required": True, "owner_approved": owner_approved,
        "owner_approval_reference": owner_approval_reference, "approved_at_utc": approved_at_utc,
        "publication_target": publication_target, "publication_ready": ready,
        "published_externally": False, "status": "PASS", "actionable": False,
    }


def validate_model_provenance(provenance: dict[str, Any]) -> dict[str, Any]:
    """Validate optional operational metadata; it never becomes investment evidence."""

    _required(provenance, "model_provenance_id", "model_surface", "model_identifier", "input_receipt_ids", "output_artifact_hash", "started_at_utc", "completed_at_utc", "status", "model_change_did_not_modify_runtime_configuration", "project_runtime_model_allowlist_unchanged")
    _false(provenance)
    if not SHA256.fullmatch(provenance["output_artifact_hash"]):
        raise GovernanceValidationError("output_artifact_hash must be an uppercase SHA-256")
    if provenance["model_change_did_not_modify_runtime_configuration"] is not True or provenance["project_runtime_model_allowlist_unchanged"] is not True:
        raise GovernanceValidationError("G1 prohibits runtime model configuration changes")
    for prohibited in ("estimated_cost", "cost_usd", "estimated_tokens"):
        if prohibited in provenance:
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
