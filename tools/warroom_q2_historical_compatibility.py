#!/usr/bin/env python3
"""Fail-closed Q2 historical evidence compatibility materialization.

This module translates one sealed 2026-08-12 G1 receipt into the current
candidate-workflow envelope.  It neither adds evidence nor changes the source
receipt/raw artifact.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import warroom_report_governance as governance
import warroom_report_trigger_runtime as runtime


class Q2CompatibilityError(RuntimeError):
    """Historical Q2 lineage cannot be translated deterministically."""


@dataclass(frozen=True)
class CompatibilityPolicy:
    raw_sha256: str
    rejected_revised_sha256: str
    receipt_file_sha256: str
    integration_file_sha256: str
    integration_canonical_sha256: str
    trigger_file_sha256: str
    trigger_canonical_sha256: str
    authority_manifest_sha256: str
    authority_manifest_version: str
    phase3a_source_manifest_sha256: str
    q2_closeout_receipt_sha256: str
    event_id: str
    receipt_id: str
    decision_id: str
    canonical_event_id: str = "HON_HAI_FY2026_Q2_EARNINGS"
    report_key: str = "P1008_FY2026_Q2_EARNINGS"
    revision: int = 1


PRODUCTION_POLICY = CompatibilityPolicy(
    raw_sha256="F014BE750095543B35ED2D482C0CF7A40B4A448167796F8AC4560AB928E609C5",
    rejected_revised_sha256="24E61BEFB2F87FC3582B0C7A1187DF35F5976EA49C11421DE324151180B7F7E8",
    receipt_file_sha256="03412B8DA34ABE06E7037EDC16E2963E68F0C5CD8B62AC5E902702FDAA6D66B5",
    integration_file_sha256="D0F1C63216106B2D703C9183B7C65E996F02D1D1249C80693D98FBC692DC2227",
    integration_canonical_sha256="CD251FC75650CE700648FEC29C9C52E2F09DE3A36AFB72C961334E306EE87EA5",
    trigger_file_sha256="4CCEC0C56540DF9E8F3720714419835A2339E5225DFA04F2B4FDB9291231D7DD",
    trigger_canonical_sha256="8DD15B103350D26AEDFB87D789FFB1535AD1FC18999F9D7D0502BCA460E78116",
    authority_manifest_sha256="FB00A640007F34803A01BBE9C8E11DC4AFF61A8C7B52996B35099B86CA092622",
    authority_manifest_version="1.6.0",
    phase3a_source_manifest_sha256="AACF739D02261CFD70C82B2E97D47C01340FCE344B6D49CAA1F135CDF6285DEF",
    q2_closeout_receipt_sha256="B1D431C6380E2914E40203DA6A077B3414029F100FA14FB0108E63F5D4069050",
    event_id="IR-EVIDENCE-EE53AFE9517E1D666F0A",
    receipt_id="IR-RECEIPT-6D5D0281AD7B2C179220",
    decision_id="TRIGGER-89A339965F6CED47",
)

INTEGRATION_REL = Path("research_plugin/latest_content_integration.json")
TRIGGER_REL = Path("report_trigger/latest_decision.json")
AUTHORITY_MANIFEST_REL = Path("data/CSV_AUTHORITY_MANIFEST.json")
ANALYSIS_CONTRACT_REL = Path("contracts/p1008_analysis/v1.0/contract.manifest.json")
Q2_PACKET_REL = Path("modules/p1008_research_plugin/config/quarterly_earnings/FY2026_Q2.json")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Q2CompatibilityError(f"{label}_INVALID: {exc}") from exc
    if not isinstance(result, dict):
        raise Q2CompatibilityError(f"{label}_INVALID")
    return result


def _require_file_sha(path: Path, expected: str, label: str) -> None:
    if not path.is_file() or runtime._sha256_path(path) != expected:
        raise Q2CompatibilityError(f"{label}_HASH_INVALID")


def _safe_historical_path(root: Path, relative: str, label: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or rel.parts[:1] != ("runtime",) or ".." in rel.parts:
        raise Q2CompatibilityError(f"{label}_PATH_INVALID")
    target = root.joinpath(*rel.parts[1:]).resolve()
    if root.resolve() not in target.parents:
        raise Q2CompatibilityError(f"{label}_PATH_INVALID")
    return target


def _validate_authority(package_root: Path, policy: CompatibilityPolicy) -> dict[str, Any]:
    path = package_root / AUTHORITY_MANIFEST_REL
    _require_file_sha(path, policy.authority_manifest_sha256, "CURRENT_AUTHORITY_MANIFEST")
    manifest = _read_json(path, "CURRENT_AUTHORITY_MANIFEST")
    promotion = manifest.get("phase3aOwnerPromotion")
    if not (
        manifest.get("manifestVersion") == policy.authority_manifest_version
        and manifest.get("approvedBy") == "Owner"
        and manifest.get("authoritative") is True
        and manifest.get("ownerPromotionRequired") is False
        and isinstance(promotion, dict)
        and promotion.get("sourceManifestSha256") == policy.phase3a_source_manifest_sha256
        and promotion.get("q2Lineage", {}).get("closeoutReceiptSha256") == policy.q2_closeout_receipt_sha256
        and manifest.get("actionable") is False
        and manifest.get("publishAuthorized") is False
    ):
        raise Q2CompatibilityError("CURRENT_AUTHORITY_LINEAGE_INVALID")
    return manifest


def _validate_historical(
    historical_root: Path, policy: CompatibilityPolicy,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], Path, Path]:
    integration_path = historical_root / INTEGRATION_REL
    trigger_path = historical_root / TRIGGER_REL
    _require_file_sha(integration_path, policy.integration_file_sha256, "HISTORICAL_INTEGRATION_FILE")
    _require_file_sha(trigger_path, policy.trigger_file_sha256, "HISTORICAL_TRIGGER_FILE")
    integration = _read_json(integration_path, "HISTORICAL_INTEGRATION")
    trigger = _read_json(trigger_path, "HISTORICAL_TRIGGER")
    runtime._validate_hash(integration, "HISTORICAL_INTEGRATION")
    runtime._validate_hash(trigger, "HISTORICAL_TRIGGER")
    if integration.get("canonical_sha256") != policy.integration_canonical_sha256 or trigger.get("canonical_sha256") != policy.trigger_canonical_sha256:
        raise Q2CompatibilityError("HISTORICAL_CANONICAL_HASH_INVALID")
    if trigger.get("candidate_workflow") is not None or trigger.get("analysis_baseline_binding") is not None:
        raise Q2CompatibilityError("HISTORICAL_WORKFLOW_NOT_LEGACY_SCHEMA")
    evidence_list = integration.get("validated_event_evidence")
    if not isinstance(evidence_list, list):
        raise Q2CompatibilityError("HISTORICAL_EVIDENCE_INVALID")
    matches = [item for item in evidence_list if isinstance(item, dict) and item.get("canonical_event_id") == policy.canonical_event_id]
    if len(matches) != 1 or len(evidence_list) != 1:
        raise Q2CompatibilityError("HISTORICAL_LINEAGE_AMBIGUOUS")
    try:
        evidence = governance.validate_event_evidence(matches[0])
        canonical_event = governance.deduplicate_event_evidence([evidence])
    except governance.GovernanceValidationError as exc:
        raise Q2CompatibilityError(f"HISTORICAL_EVIDENCE_INVALID: {exc}") from exc
    provenance = evidence["provenance"]
    if not isinstance(provenance, dict):
        raise Q2CompatibilityError("HISTORICAL_PROVENANCE_INVALID")
    raw_path = _safe_historical_path(historical_root, str(provenance.get("raw_artifact_path", "")), "HISTORICAL_RAW")
    receipt_path = _safe_historical_path(historical_root, str(provenance.get("receipt_path", "")), "HISTORICAL_RECEIPT")
    if raw_path.is_file() and runtime._sha256_path(raw_path) == policy.rejected_revised_sha256:
        raise Q2CompatibilityError("REVISED_Q2_RESULTS_NOT_CONTRACT_AUTHORITY")
    _require_file_sha(raw_path, policy.raw_sha256, "HISTORICAL_RAW")
    _require_file_sha(receipt_path, policy.receipt_file_sha256, "HISTORICAL_RECEIPT")
    receipt = _read_json(receipt_path, "HISTORICAL_RECEIPT")
    decision = integration.get("report_trigger_decision")
    expected_decision = governance.evaluate_report_trigger(
        report_key=integration.get("report_key"), revision=integration.get("revision"),
        event_evidence=[evidence], evaluated_at_utc=integration.get("evaluated_at_utc"),
    )
    if decision != expected_decision:
        raise Q2CompatibilityError("HISTORICAL_TRIGGER_DECISION_INVALID")
    expected = {
        "event_id": policy.event_id, "receipt_id": policy.receipt_id,
        "decision_id": policy.decision_id, "report_key": policy.report_key,
        "revision": policy.revision, "canonical_event_id": policy.canonical_event_id,
    }
    if not (
        evidence.get("event_id") == expected["event_id"]
        and evidence.get("source_hash") == policy.raw_sha256
        and provenance.get("raw_sha256") == policy.raw_sha256
        and provenance.get("receipt_id") == expected["receipt_id"]
        and evidence.get("quality_metadata", {}).get("document_type") == "RESULTS_DOCUMENT_CONFIRMED"
        and evidence.get("quality_metadata", {}).get("raw_byte_hash_bound") is True
        and evidence.get("validation_status") == "OFFICIAL_VERIFIED"
        and receipt.get("receipt_id") == expected["receipt_id"]
        and receipt.get("raw_sha256") == policy.raw_sha256
        and receipt.get("source_hash") == policy.raw_sha256
        and receipt.get("document_type") == "RESULTS_DOCUMENT_CONFIRMED"
        and receipt.get("fiscal_period") == "FY2026 Q2"
        and receipt.get("actionable") is False
        and decision.get("decision_id") == expected["decision_id"]
        and decision.get("report_key") == expected["report_key"]
        and decision.get("revision") == expected["revision"]
        and decision.get("qualifying_evidence_ids") == [policy.event_id]
        and trigger.get("decision_id") == expected["decision_id"]
        and trigger.get("qualifying_evidence_ids") == [policy.event_id]
        and trigger.get("report_key") == expected["report_key"]
        and trigger.get("revision") == expected["revision"]
        and trigger.get("report_trigger_valid") is True
        and trigger.get("decision") == "TRIGGERED_INTERNAL_REPORT"
        and trigger.get("actionable") is False
        and canonical_event.get("canonical_event_id") == policy.canonical_event_id
    ):
        raise Q2CompatibilityError("HISTORICAL_LINEAGE_INVALID")
    return integration, trigger, evidence, canonical_event, raw_path, receipt_path


def _copy_exact(source: Path, target: Path, expected_sha256: str) -> None:
    body = source.read_bytes()
    if governance.sha256_bytes(body) != expected_sha256:
        raise Q2CompatibilityError("SOURCE_CHANGED_DURING_MATERIALIZATION")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if governance.sha256_bytes(target.read_bytes()) != expected_sha256:
            raise Q2CompatibilityError("MATERIALIZATION_COLLISION")
        return
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(body)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _materialize(
    package_root: Path, historical_root: Path, output_root: Path,
    policy: CompatibilityPolicy,
) -> dict[str, Any]:
    package_root = package_root.resolve()
    historical_root = historical_root.resolve()
    output_root = output_root.resolve()
    if output_root == historical_root or historical_root in output_root.parents:
        raise Q2CompatibilityError("OUTPUT_MUST_NOT_MODIFY_HISTORICAL_ROOT")
    authority = _validate_authority(package_root, policy)
    integration, trigger, evidence, canonical_event, raw_path, receipt_path = _validate_historical(historical_root, policy)
    analysis_contract = package_root / ANALYSIS_CONTRACT_REL
    q2_packet = package_root / Q2_PACKET_REL
    if not analysis_contract.is_file() or not q2_packet.is_file():
        raise Q2CompatibilityError("Q2_ANALYSIS_CONTRACT_LINEAGE_MISSING")
    promotion = authority["phase3aOwnerPromotion"]
    compat_base = {
        "recordType": runtime.Q2_COMPATIBILITY_RECORD_TYPE,
        "compatibilitySchema": "candidate_workflow/1.0",
        "compatibilityVersion": runtime.Q2_COMPATIBILITY_VERSION,
        "historicalEvidenceIdentity": {
            "eventId": evidence["event_id"], "canonicalEventId": evidence["canonical_event_id"],
            "documentType": evidence["quality_metadata"]["document_type"],
            "sourceId": evidence["source_id"], "rawSha256": policy.raw_sha256,
        },
        "originalRawSha256": policy.raw_sha256,
        "originalReceipt": {
            "receiptId": policy.receipt_id, "receiptSha256": policy.receipt_file_sha256,
            "relativePath": evidence["provenance"]["receipt_path"], "rawSha256": policy.raw_sha256,
        },
        "originalEventIdentity": {
            "eventId": evidence["event_id"], "canonicalEventId": canonical_event["canonical_event_id"],
            "eventFingerprint": canonical_event["event_fingerprint"],
            "eventCanonicalSha256": runtime._canonical_hash(evidence),
        },
        "originalTriggerLineage": {
            "decisionId": trigger["decision_id"], "reportKey": trigger["report_key"],
            "revision": trigger["revision"], "triggerCanonicalSha256": policy.trigger_canonical_sha256,
            "triggerFileSha256": policy.trigger_file_sha256,
            "integrationCanonicalSha256": policy.integration_canonical_sha256,
            "integrationFileSha256": policy.integration_file_sha256,
        },
        "currentAuthority": {
            "manifestVersion": policy.authority_manifest_version,
            "manifestSha256": policy.authority_manifest_sha256,
            "phase3aSourceManifestSha256": policy.phase3a_source_manifest_sha256,
            "promotionId": promotion["promotionId"],
        },
        "q2CloseoutLineage": {
            "receiptPath": promotion["q2Lineage"]["closeoutReceiptPath"],
            "receiptSha256": policy.q2_closeout_receipt_sha256,
            "quarter": promotion["q2Lineage"]["quarter"],
        },
        "analysisContractLineage": {
            "contractPath": ANALYSIS_CONTRACT_REL.as_posix(),
            "contractSha256": runtime._sha256_path(analysis_contract),
            "q2PacketPath": Q2_PACKET_REL.as_posix(),
            "q2PacketSha256": runtime._sha256_path(q2_packet),
        },
        "factsAdded": 0, "historicalRawModified": False,
        "historicalReceiptModified": False, "authoritative": False,
        "publishAuthorized": False, "actionable": False,
    }
    compatibility = {**compat_base, "materializedWorkflowSha256": runtime._canonical_hash(compat_base)}
    runtime.validate_historical_workflow_compatibility(compatibility)
    current_integration = {key: value for key, value in integration.items() if key != "canonical_sha256"}
    current_integration["historical_workflow_compatibility"] = compatibility
    current_integration = runtime.build_integration_artifact(current_integration)
    decision = governance.evaluate_report_trigger(
        report_key=policy.report_key, revision=policy.revision, event_evidence=[evidence],
        evaluated_at_utc=integration["evaluated_at_utc"],
    )
    current_trigger = runtime._receipt(
        integration=current_integration, evidence=[evidence], decision=decision,
        cross_validation=governance.evaluate_cross_validation([evidence]),
        canonical_event=canonical_event,
        baseline_binding=runtime._baseline_binding(decision, canonical_event),
    )
    runtime.validate_receipt(current_trigger)
    if current_trigger["candidate_workflow"].get("historical_compatibility") != compatibility:
        raise Q2CompatibilityError("CURRENT_WORKFLOW_COMPATIBILITY_MISSING")
    for source, relative, expected_sha in (
        (raw_path, evidence["provenance"]["raw_artifact_path"], policy.raw_sha256),
        (receipt_path, evidence["provenance"]["receipt_path"], policy.receipt_file_sha256),
    ):
        rel = Path(relative)
        _copy_exact(source, output_root.joinpath(*rel.parts[1:]), expected_sha)
    runtime.atomic_write_json(output_root / INTEGRATION_REL, current_integration, overwrite=False)
    runtime.atomic_write_json(output_root / "report_trigger/decision_receipts" / f"{policy.decision_id}.json", current_trigger, overwrite=False)
    runtime.atomic_write_json(output_root / TRIGGER_REL, current_trigger, overwrite=False)
    result = {
        "status": "PASS", "evidenceRoot": str(output_root),
        "materializedWorkflowSha256": compatibility["materializedWorkflowSha256"],
        "integrationCanonicalSha256": current_integration["canonical_sha256"],
        "triggerCanonicalSha256": current_trigger["canonical_sha256"],
        "rawSha256": policy.raw_sha256, "receiptSha256": policy.receipt_file_sha256,
        "factsAdded": 0, "actionable": False, "publishAuthorized": False,
    }
    runtime.atomic_write_json(output_root / "q2_historical_compatibility_manifest.json", result, overwrite=False)
    return result


def materialize(package_root: Path, historical_root: Path, output_root: Path) -> dict[str, Any]:
    """Production entry point; all accepted historical identities are frozen."""

    return _materialize(package_root, historical_root, output_root, PRODUCTION_POLICY)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--historical-evidence-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = materialize(args.package_root, args.historical_evidence_root, args.output_root)
    except (Q2CompatibilityError, runtime.RuntimeTriggerError, governance.GovernanceValidationError) as exc:
        print(json.dumps({"status": "FAIL_CLOSED", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
