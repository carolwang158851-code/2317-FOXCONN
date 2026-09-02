#!/usr/bin/env python3
"""Fail-closed runtime bridge from governed research evidence to G1.

The bridge consumes the existing ResearchContentOrchestrator result.  It does
not collect, interpret, or promote evidence and it never creates a report.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import warroom_report_governance as governance
import warroom_major_event_baseline as major_event_baseline
import warroom_major_event_materialization as major_event_materialization
import warroom_major_event_report_persistence as major_event_report_persistence

MODULE_SRC = Path(__file__).resolve().parents[1] / "modules" / "p1008_research_plugin" / "src"
CODE_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_SRC) not in os.sys.path:
    os.sys.path.insert(0, str(MODULE_SRC))
from p1008_research_plugin.reporting import template_governance


INTEGRATION_REL = Path("runtime/research_plugin/latest_content_integration.json")
LATEST_REL = Path("runtime/report_trigger/latest_decision.json")
RECEIPTS_REL = Path("runtime/report_trigger/decision_receipts")
INTEGRATION_RECORD_TYPE = "P1008_RESEARCH_CONTENT_INTEGRATION_V1"
RECEIPT_RECORD_TYPE = "P1008_G1_RUNTIME_TRIGGER_DECISION"
PRODUCER_ID = "P1008_G1_REPORT_TRIGGER_RUNTIME_WIRING_V1"
GOVERNED_EVIDENCE_ROOT_ENV = "P1008_GOVERNED_EVIDENCE_ROOT"


class RuntimeTriggerError(RuntimeError):
    """A runtime trigger or its lineage could not be proven."""


def governed_evidence_root(package_root: Path) -> tuple[Path, dict[str, Any]]:
    """Resolve read-only evidence location; default remains this worktree runtime."""
    root = package_root.resolve()
    configured = os.environ.get(GOVERNED_EVIDENCE_ROOT_ENV, "").strip()
    if not configured:
        return root / "runtime", {"mode": "LOCAL_RUNTIME", "root": str(root / "runtime"), "actionable": False}
    evidence_root = Path(configured).expanduser().resolve()
    if not evidence_root.is_dir():
        raise RuntimeTriggerError("GOVERNED_EVIDENCE_ROOT_MISSING")
    if evidence_root == (root / "runtime").resolve():
        raise RuntimeTriggerError("GOVERNED_EVIDENCE_ROOT_MUST_BE_EXTERNAL_OR_UNSET")
    required = (evidence_root / "report_trigger" / "latest_decision.json", evidence_root / "research_plugin" / "latest_content_integration.json")
    if not all(path.is_file() for path in required):
        raise RuntimeTriggerError("GOVERNED_EVIDENCE_ROOT_INCOMPLETE")
    return evidence_root, {"mode": "EXTERNAL_GOVERNED_READ_ONLY", "root": str(evidence_root),
                           "triggerReceiptSha256": _sha256_path(required[0]),
                           "integrationSha256": _sha256_path(required[1]), "actionable": False}


def _sha256_path(path: Path) -> str:
    return governance.sha256_bytes(path.read_bytes())


def _evidence_path(package_root: Path, relative: Path) -> Path:
    evidence_root, _context = governed_evidence_root(package_root)
    if relative.parts[:1] != ("runtime",):
        raise RuntimeTriggerError("UNSAFE_EVIDENCE_RELATIVE_PATH")
    return evidence_root.joinpath(*relative.parts[1:])


def _canonical_hash(payload: dict[str, Any]) -> str:
    return governance.sha256_bytes(governance.canonical_json_bytes(payload))


def _with_hash(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "canonical_sha256": _canonical_hash(payload)}


def _validate_hash(payload: dict[str, Any], label: str) -> None:
    supplied = payload.get("canonical_sha256")
    unhashed = {key: value for key, value in payload.items() if key != "canonical_sha256"}
    if not isinstance(supplied, str) or supplied != _canonical_hash(unhashed):
        raise RuntimeTriggerError(f"{label}_HASH_INVALID")


def atomic_write_json(path: Path, payload: dict[str, Any], *, overwrite: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != payload:
            raise RuntimeTriggerError("TRIGGER_RECEIPT_COLLISION")
        return
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(body)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_integration_artifact(result: dict[str, Any]) -> dict[str, Any]:
    """Seal an existing orchestrator result for controlled runtime ingestion."""

    if result.get("record_type") != INTEGRATION_RECORD_TYPE:
        raise RuntimeTriggerError("RESEARCH_INTEGRATION_RECORD_INVALID")
    if result.get("actionable") is not False:
        raise RuntimeTriggerError("RESEARCH_INTEGRATION_ACTIONABLE_INVALID")
    payload = dict(result)
    evidence = payload.get("validated_event_evidence")
    if not isinstance(evidence, list):
        raise RuntimeTriggerError("VALIDATED_EVENT_EVIDENCE_REQUIRED")
    expected_ledger = governance.build_validated_evidence_lineage_ledger(evidence)
    supplied_ledger = payload.get("validated_evidence_lineage_ledger")
    if supplied_ledger is not None:
        governance.validate_evidence_lineage_ledger(supplied_ledger, evidence)
    payload["validated_evidence_lineage_ledger"] = expected_ledger
    return _with_hash(payload)


def persist_integration_result(package_root: Path, result: dict[str, Any]) -> dict[str, Any]:
    """Persist the existing orchestrator result at the sole runtime ingest path."""

    artifact = build_integration_artifact(result)
    atomic_write_json(package_root.resolve() / INTEGRATION_REL, artifact)
    return artifact


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeTriggerError(f"{label}_INVALID: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeTriggerError(f"{label}_INVALID")
    return payload


def _load_integration(package_root: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    path = _evidence_path(package_root, INTEGRATION_REL)
    if not path.is_file():
        return None, []
    payload = _read_json(path, "RESEARCH_INTEGRATION")
    _validate_hash(payload, "RESEARCH_INTEGRATION")
    if payload.get("record_type") != INTEGRATION_RECORD_TYPE or payload.get("actionable") is not False:
        raise RuntimeTriggerError("RESEARCH_INTEGRATION_RECORD_INVALID")
    evidence = payload.get("validated_event_evidence")
    if not isinstance(evidence, list):
        raise RuntimeTriggerError("VALIDATED_EVENT_EVIDENCE_REQUIRED")
    validated = [governance.validate_event_evidence(item) for item in evidence]
    ledger = payload.get("validated_evidence_lineage_ledger")
    if not isinstance(ledger, dict):
        raise RuntimeTriggerError("VALIDATED_EVIDENCE_LINEAGE_LEDGER_REQUIRED")
    try:
        governance.validate_evidence_lineage_ledger(ledger, validated)
    except governance.GovernanceValidationError as exc:
        raise RuntimeTriggerError(f"EVIDENCE_LINEAGE_INVALID: {exc}") from exc
    report_key = payload.get("report_key")
    revision = payload.get("revision")
    evaluated_at = payload.get("evaluated_at_utc")
    supplied_decision = payload.get("report_trigger_decision")
    if not isinstance(supplied_decision, dict):
        raise RuntimeTriggerError("RESEARCH_TRIGGER_DECISION_REQUIRED")
    try:
        expected_decision = governance.evaluate_report_trigger(
            report_key=report_key, revision=revision,
            event_evidence=validated, evaluated_at_utc=evaluated_at,
        )
    except governance.GovernanceValidationError as exc:
        raise RuntimeTriggerError(f"RESEARCH_INTEGRATION_INVALID: {exc}") from exc
    if supplied_decision != expected_decision:
        raise RuntimeTriggerError("RESEARCH_TRIGGER_DECISION_INVALID")
    return payload, validated


def _unique_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in evidence:
        key = (item["canonical_event_id"], item["source_id"], item["source_hash"])
        if key in unique and unique[key] != item:
            raise RuntimeTriggerError("DUPLICATE_EVIDENCE_IDENTITY_CONFLICT")
        unique.setdefault(key, item)
    return list(unique.values())


def _previous(package_root: Path) -> dict[str, Any] | None:
    path = _evidence_path(package_root, LATEST_REL)
    if not path.is_file():
        return None
    payload = _read_json(path, "TRIGGER_RECEIPT")
    validate_receipt(payload)
    return payload


def _report_identity(
    integration: dict[str, Any] | None,
    evidence: list[dict[str, Any]],
    previous: dict[str, Any] | None,
    evaluated_at_utc: str,
) -> tuple[str, int, str | None]:
    if not evidence:
        day = evaluated_at_utc[:10].replace("-", "")
        return f"P1008_DAILY_{day}", 1, None
    report_key = integration.get("report_key") if integration else None
    if not isinstance(report_key, str):
        raise RuntimeTriggerError("STABLE_REPORT_KEY_REQUIRED")
    # Revisions change only when the governed claims change.  Added syndicated
    # or earnings-call corroboration of the same claims remains one report.
    claim_hash = _canonical_hash({"claims": sorted({item["claim_summary"] for item in evidence})})
    if previous and previous.get("report_key") == report_key:
        if previous.get("claim_set_sha256") == claim_hash:
            return report_key, int(previous["revision"]), previous.get("previous_decision_id")
        return report_key, int(previous["revision"]) + 1, previous.get("decision_id")
    return report_key, 1, None


def _receipt(
    *, integration: dict[str, Any] | None, evidence: list[dict[str, Any]],
    decision: dict[str, Any], cross_validation: dict[str, Any],
    canonical_event: dict[str, Any] | None, baseline_binding: dict[str, Any],
) -> dict[str, Any]:
    evidence_hashes = sorted({_canonical_hash(item) for item in evidence})
    claim_hash = _canonical_hash({"claims": sorted({item["claim_summary"] for item in evidence})})
    source_event_type = decision["event_type"]
    normalized_event_type = (
        "DAILY"
        if source_event_type == "NONE" and decision["report_key"].startswith("P1008_DAILY_")
        else governance.normalize_g1_event_type(source_event_type)
    )
    # Unknown/unapproved source events remain rejected by the decision, but the
    # downstream routing vocabulary stays closed to the four governed classes.
    if normalized_event_type not in governance.G1_EVENT_TYPES:
        normalized_event_type = "MAJOR_EVENT"
    evidence_trigger_valid = decision["report_trigger_valid"] is True
    baseline_bound = (
        normalized_event_type != "MAJOR_EVENT"
        or baseline_binding.get("status") == "BOUND"
    )
    effective_trigger_valid = evidence_trigger_valid and baseline_bound
    if evidence_trigger_valid and normalized_event_type == "MAJOR_EVENT":
        if baseline_binding.get("status") == "REVIEW_REQUIRED":
            effective_decision = "REVIEW_REQUIRED_ANALYSIS_BASELINE"
            effective_reason = str(baseline_binding.get("reason"))
        elif baseline_binding.get("status") == "FAIL_CLOSED":
            effective_decision = "FAIL_CLOSED_ANALYSIS_BASELINE"
            effective_reason = str(baseline_binding.get("reason"))
        else:
            effective_decision = decision["decision"]
            effective_reason = decision["trigger_reason"]
    else:
        effective_decision = decision["decision"]
        effective_reason = decision["trigger_reason"]
    workflow = {
        "trigger": (
            "OBSERVATION_ONLY" if normalized_event_type == "DAILY"
            else "ELIGIBLE" if effective_trigger_valid
            else "BLOCKED"
        ),
        "analysis_candidate": (
            "BOUND_APPROVED_BASELINE"
            if normalized_event_type == "MAJOR_EVENT" and effective_trigger_valid
            else baseline_binding.get("status", "NOT_ELIGIBLE")
            if normalized_event_type == "MAJOR_EVENT" and evidence_trigger_valid
            else "ELIGIBLE" if effective_trigger_valid
            else "NOT_ELIGIBLE"
        ),
        "report_candidate": (
            "REQUIRES_VALIDATED_ANALYSIS_CANDIDATE"
            if effective_trigger_valid else "NOT_ELIGIBLE"
        ),
        "owner_review": (
            "REQUIRED_AFTER_REPORT_CANDIDATE"
            if effective_trigger_valid else "NOT_ELIGIBLE"
        ),
        "publication": "DENIED_BY_DEFAULT_OWNER_APPROVAL_REQUIRED",
        "actionable": False,
    }
    payload = {
        "record_type": RECEIPT_RECORD_TYPE,
        "schema_version": "1.0",
        "producer_id": PRODUCER_ID,
        "decision_id": decision["decision_id"],
        "report_key": decision["report_key"],
        "revision": decision["revision"],
        "canonical_event_id": canonical_event.get("canonical_event_id", "") if canonical_event else "",
        "event_fingerprint": canonical_event.get("event_fingerprint", "") if canonical_event else "",
        "canonical_event_occurred_at_utc": canonical_event.get("occurred_at_utc", "") if canonical_event else "",
        "event_type": normalized_event_type,
        "source_event_type": source_event_type,
        "qualifying_evidence_ids": decision["qualifying_evidence_ids"],
        "event_evidence_hashes": evidence_hashes,
        "claim_set_sha256": claim_hash,
        "authority_cutoffs": decision["authority_cutoffs"],
        "cross_validation": cross_validation,
        "decision": effective_decision,
        "trigger_reason": effective_reason,
        "evidence_trigger_decision": decision["decision"],
        "evidence_trigger_valid": evidence_trigger_valid,
        "report_trigger_valid": effective_trigger_valid,
        "material_event_confirmed": decision["material_event_confirmed"],
        "evaluated_at_utc": decision["evaluated_at_utc"],
        "previous_decision_id": decision["previous_decision_id"],
        "integration_receipt_sha256": integration.get("canonical_sha256", "") if integration else "",
        "report_generated": False,
        "analysis_candidate_valid": False,
        "report_candidate_valid": False,
        "candidate_workflow": workflow,
        "analysis_baseline_binding": baseline_binding,
        "publication": "DENIED_BY_DEFAULT_OWNER_APPROVAL_REQUIRED",
        "actionable": False,
    }
    return _with_hash(payload)


def validate_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    _validate_hash(receipt, "TRIGGER_RECEIPT")
    if receipt.get("record_type") != RECEIPT_RECORD_TYPE or receipt.get("actionable") is not False:
        raise RuntimeTriggerError("TRIGGER_RECEIPT_INVALID")
    if receipt.get("report_generated") is not False:
        raise RuntimeTriggerError("TRIGGER_RECEIPT_REPORT_STATE_INVALID")
    if receipt.get("event_type") not in governance.G1_EVENT_TYPES:
        raise RuntimeTriggerError("G1_EVENT_TYPE_NOT_NORMALIZED")
    if receipt.get("event_type") == "DAILY" and receipt.get("report_trigger_valid") is not False:
        raise RuntimeTriggerError("DAILY_FORMAL_REPORT_PROHIBITED")
    workflow = receipt.get("candidate_workflow")
    if not isinstance(workflow, dict) or workflow.get("actionable") is not False:
        raise RuntimeTriggerError("CANDIDATE_WORKFLOW_INVALID")
    if workflow.get("publication") != "DENIED_BY_DEFAULT_OWNER_APPROVAL_REQUIRED":
        raise RuntimeTriggerError("PUBLICATION_GOVERNANCE_INVALID")
    binding = receipt.get("analysis_baseline_binding")
    if not isinstance(binding, dict) or binding.get("actionable") is not False:
        raise RuntimeTriggerError("ANALYSIS_BASELINE_BINDING_INVALID")
    if receipt.get("event_type") == "MAJOR_EVENT" and receipt.get("evidence_trigger_valid") is True:
        if receipt.get("report_trigger_valid") is True and binding.get("status") != "BOUND":
            raise RuntimeTriggerError("MAJOR_EVENT_BASELINE_REQUIRED")
        if binding.get("fallback_used") is not False:
            raise RuntimeTriggerError("MAJOR_EVENT_BASELINE_FALLBACK_PROHIBITED")
    return receipt


def _baseline_binding(
    decision: dict[str, Any], canonical_event: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized = governance.normalize_g1_event_type(str(decision.get("event_type")))
    if normalized != "MAJOR_EVENT" or decision.get("report_trigger_valid") is not True:
        return {
            "status": "NOT_REQUIRED", "reason": "NON_MAJOR_OR_INELIGIBLE_EVENT",
            "selected_baseline": None, "fallback_used": False,
            "fallback_event_type": None, "authoritative": False,
            "publishAuthorized": False, "actionable": False,
        }
    if canonical_event is None:
        return {
            "status": "FAIL_CLOSED", "reason": "VALIDATED_CANONICAL_EVENT_REQUIRED",
            "selected_baseline": None, "fallback_used": False,
            "fallback_event_type": None, "authoritative": False,
            "publishAuthorized": False, "actionable": False,
        }
    return major_event_baseline.select_major_event_baseline(
        CODE_PACKAGE_ROOT, canonical_event
    )


def evaluate_and_persist(package_root: Path, *, evaluated_at_utc: str | None = None) -> dict[str, Any]:
    root = package_root.resolve()
    now = evaluated_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    previous = _previous(root)
    integration, raw_evidence = _load_integration(root)
    evidence = _unique_evidence(raw_evidence)
    canonical_event = None
    if evidence:
        canonical_event = governance.deduplicate_event_evidence(evidence)
    report_key, revision, previous_decision_id = _report_identity(
        integration, evidence, previous, now
    )
    # The integration evaluation timestamp is stable, making repeated ingestion
    # idempotent.  Ordinary-day evaluations use the current invocation time.
    evaluation_time = (
        str((integration or {}).get("evaluated_at_utc") or now)
        if evidence else now
    )
    cross_validation = governance.evaluate_cross_validation(evidence)
    decision = governance.evaluate_report_trigger(
        report_key=report_key,
        revision=revision,
        event_evidence=evidence,
        evaluated_at_utc=evaluation_time,
        previous_decision_id=previous_decision_id,
    )
    baseline_binding = _baseline_binding(decision, canonical_event)
    receipt = _receipt(
        integration=integration, evidence=evidence, decision=decision,
        cross_validation=cross_validation, canonical_event=canonical_event,
        baseline_binding=baseline_binding,
    )
    immutable = root / RECEIPTS_REL / f"{receipt['decision_id']}.json"
    atomic_write_json(immutable, receipt, overwrite=False)
    atomic_write_json(root / LATEST_REL, receipt)
    return receipt


def require_valid_trigger(package_root: Path) -> dict[str, Any]:
    root = package_root.resolve()
    persisted = _read_json(_evidence_path(root, LATEST_REL), "TRIGGER_RECEIPT")
    validate_receipt(persisted)
    integration, evidence = _load_integration(root)
    if integration is None or not evidence:
        raise RuntimeTriggerError("REPORT_TRIGGER_REQUIRED")
    # Recompute without writing and compare all governed identity inputs.
    unique = _unique_evidence(evidence)
    canonical = governance.deduplicate_event_evidence(unique)
    expected_decision = governance.evaluate_report_trigger(
        report_key=persisted["report_key"], revision=persisted["revision"],
        event_evidence=unique, evaluated_at_utc=persisted["evaluated_at_utc"],
        previous_decision_id=persisted.get("previous_decision_id"),
    )
    baseline_binding = _baseline_binding(expected_decision, canonical)
    expected = _receipt(
        integration=integration, evidence=unique, decision=expected_decision,
        cross_validation=governance.evaluate_cross_validation(unique),
        canonical_event=canonical, baseline_binding=baseline_binding,
    )
    if expected != persisted:
        raise RuntimeTriggerError("TRIGGER_RECEIPT_LINEAGE_INVALID")
    if not (
        persisted.get("decision") == "TRIGGERED_INTERNAL_REPORT"
        and persisted.get("report_trigger_valid") is True
        and persisted.get("material_event_confirmed") is True
        and persisted.get("actionable") is False
    ):
        raise RuntimeTriggerError("REPORT_TRIGGER_REQUIRED")
    return persisted


def trigger_lineage(receipt: dict[str, Any]) -> dict[str, Any]:
    validated = validate_receipt(receipt)
    lineage = {
        "reportKey": validated["report_key"],
        "revision": validated["revision"],
        "eventType": validated["event_type"],
        "canonicalEventId": validated["canonical_event_id"],
        "triggerDecisionId": validated["decision_id"],
        "triggerReceiptSha256": validated["canonical_sha256"],
        "evidenceIds": validated["qualifying_evidence_ids"],
        "authorityCutoffs": validated["authority_cutoffs"],
        "actionable": False,
    }
    if validated["event_type"] == "MAJOR_EVENT":
        binding = validated["analysis_baseline_binding"]
        if binding.get("status") != "BOUND" or not isinstance(
            binding.get("selected_baseline"), dict
        ):
            raise RuntimeTriggerError("MAJOR_EVENT_BASELINE_REQUIRED")
        lineage["analysisBaseline"] = dict(binding["selected_baseline"])
        lineage["analysisBaselineRegistry"] = {
            "registryId": binding["registry_id"],
            "registryVersion": binding["registry_version"],
            "registrySha256": binding["registry_sha256"],
        }
    return lineage


def materialize_major_event_provenance(
    _runtime_root: Path, receipt: dict[str, Any]
) -> dict[str, Any]:
    """Validate the G1 receipt, then materialize non-publishing provenance only."""

    validated = validate_receipt(receipt)
    return major_event_materialization.materialize_major_event_provenance(
        CODE_PACKAGE_ROOT, validated
    )


def persist_major_event_report_candidate(
    package_root: Path,
    receipt: dict[str, Any],
    materialized: dict[str, Any],
    *,
    revision: int,
    persisted_at_utc: str | None = None,
) -> dict[str, Any]:
    """Persist a validated provenance candidate without rendering or publishing."""

    validated = validate_receipt(receipt)
    return major_event_report_persistence.persist_major_event_report_candidate(
        package_root,
        CODE_PACKAGE_ROOT,
        validated,
        materialized,
        revision=revision,
        persisted_at_utc=persisted_at_utc,
    )


def template_governance_status(receipt: dict[str, Any] | None) -> dict[str, Any]:
    """Expose template identity to the existing Launcher without dispatching work."""
    if receipt is None:
        return {"status": "NO_TRIGGER", "templateId": template_governance.TEMPLATE_ID,
                "templateVersion": template_governance.TEMPLATE_VERSION,
                "templateHash": template_governance.template_hash(), "actionable": False}
    valid = validate_receipt(receipt)
    return {"status": "OWNER_REVIEW_REQUIRED" if valid.get("report_trigger_valid") else "TRIGGER_REQUIRED",
            "templateId": template_governance.TEMPLATE_ID,
            "templateVersion": template_governance.TEMPLATE_VERSION,
            "templateHash": template_governance.template_hash(),
            "event": valid.get("event_type"), "reportKey": valid.get("report_key"),
            "actionable": False}


def require_analysis_candidate(package_root: Path, trigger: dict[str, Any] | None = None) -> dict[str, Any]:
    root = package_root.resolve()
    receipt = trigger or require_valid_trigger(root)
    expected = trigger_lineage(receipt)
    production = root / "runtime" / "report_production"
    matches: list[tuple[str, dict[str, Any]]] = []
    if production.is_dir():
        for path in production.glob("*/run_manifest.json"):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if manifest.get("state") == "ANALYSIS_CANDIDATE_READY" and manifest.get("triggerLineage") == expected:
                matches.append((str(manifest.get("generatedAtUtc") or ""), manifest))
    if not matches:
        raise RuntimeTriggerError("ANALYSIS_CANDIDATE_REQUIRED")
    return sorted(matches, key=lambda item: item[0])[-1][1]


def launcher_status(package_root: Path) -> dict[str, Any]:
    try:
        evidence_root, evidence_context = governed_evidence_root(package_root)
        path = evidence_root / "report_trigger" / "latest_decision.json"
        if not path.is_file():
            return {"status": "NO_MATERIAL_CHANGE", "reportTriggerValid": False, "analysisEligible": False, "reportEligible": False, "templateGovernance": template_governance_status(None), "governedEvidence": evidence_context, "actionable": False}
        receipt = validate_receipt(_read_json(path, "TRIGGER_RECEIPT"))
        valid = False
        try:
            require_valid_trigger(package_root)
            valid = True
        except RuntimeTriggerError:
            valid = False
        analysis_valid = False
        if valid:
            try:
                require_analysis_candidate(package_root, receipt)
                analysis_valid = True
            except RuntimeTriggerError:
                pass
        return {
            "status": receipt["decision"],
            "event": receipt["canonical_event_id"],
            "eventType": receipt["event_type"],
            "validationState": receipt["cross_validation"]["validation_status"],
            "reportKey": receipt["report_key"],
            "revision": receipt["revision"],
            "decisionId": receipt["decision_id"],
            "reportTriggerValid": valid,
            "analysisEligible": valid,
            "reportEligible": valid and analysis_valid,
            "reportGenerated": False,
            "publication": receipt["publication"],
            "templateGovernance": template_governance_status(receipt),
            "governedEvidence": evidence_context,
            "actionable": False,
        }
    except (RuntimeTriggerError, KeyError, TypeError) as exc:
        return {"status": "FAIL_CLOSED", "error": str(exc), "reportTriggerValid": False, "analysisEligible": False, "reportEligible": False, "actionable": False}
