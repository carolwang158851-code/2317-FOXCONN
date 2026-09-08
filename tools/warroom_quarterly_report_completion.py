#!/usr/bin/env python3
"""Governed completion for an already validated Quarterly EV report candidate."""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import warroom_major_event_report_persistence as persistence
import warroom_publication_authorization_gate as publication_gate
import warroom_rolling_brief as rolling_brief

from p1008_research_plugin.analysis.analysis_contracts import AnalysisPacket
from p1008_research_plugin.analysis.numeric_claim_lineage import (
    validate_working_capital_qoq_lineage,
)
from p1008_research_plugin.phaseb1_common import canonical_json_bytes, sha256_bytes
from p1008_research_plugin.reporting.report_contracts import ChartData, ReportCandidate
from p1008_research_plugin.reporting.report_renderer_formal import FormalPreviewRenderer
from p1008_research_plugin.reporting.report_validator import ReportValidator
from p1008_research_plugin.reporting.script_builder import ScriptBuilder, ShortsDurationValidator


class QuarterlyReportCompletionError(RuntimeError):
    """Quarterly completion input or persisted lineage is invalid."""


EVENT_TYPE = "QUARTERLY_EARNINGS"
REPORT_RUNTIME = "ENTERPRISE_VALUE_WAR_REPORT_V1"
EXPECTED_Q2_RAW_SHA256 = (
    "F014BE750095543B35ED2D482C0CF7A40B4A448167796F8AC4560AB928E609C5"
)
EXPECTED_AUTHORITY_MANIFEST_VERSION = "1.6.0"
EXPECTED_PROMOTION_RECEIPT_SHA256 = (
    "A2656A441102231405989E45BEFAAFD7AAF7DBAF91E6A2351EDF022620ED6A25"
)
PROMOTION_REVIEW_ID = "P1008-2026Q2-QUARTERLY-FIELD-AVAILABILITY-OWNER-REVIEW"
PROMOTION_APPROVAL_TOKEN = "OWNER_APPROVE_P1008_2026Q2_QUARTERLY_FIELD_AVAILABILITY"
PROMOTION_RECEIPT_REL = Path(
    "runtime/quarterly_authority_promotion/"
    f"{PROMOTION_REVIEW_ID}/promotion_receipt.json"
)
AUTHORITY_MANIFEST_REL = Path("data/CSV_AUTHORITY_MANIFEST.json")
QUARTERLY_MASTER_REL = Path("data/2317_master_v9.csv")
OWNER_REVIEW_ROOT = Path("runtime/report_production/quarterly_owner_reviews")
LIBRARY_CANDIDATE_ROOT = Path("reports/private_candidates/quarterly")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QuarterlyReportCompletionError(f"{label}_INVALID") from exc
    if not isinstance(value, dict):
        raise QuarterlyReportCompletionError(f"{label}_INVALID")
    return value


def _safe_path(root: Path, locator: Any, prefix: Path) -> Path:
    relative = Path(str(locator or ""))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise QuarterlyReportCompletionError("QUARTERLY_ARTIFACT_LOCATOR_INVALID")
    expected = (root / prefix).resolve()
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(expected):
        raise QuarterlyReportCompletionError("QUARTERLY_ARTIFACT_LOCATOR_INVALID")
    return resolved


def _file_record(root: Path, path: Path, kind: str) -> dict[str, Any]:
    return {
        "format": kind,
        "locator": path.relative_to(root).as_posix(),
        "sha256": persistence._sha256(path.read_bytes()),
        "sizeBytes": path.stat().st_size,
    }


def _candidate_sha(report: ReportCandidate) -> str:
    return sha256_bytes(canonical_json_bytes(report.model_dump(mode="json", by_alias=True)))


def validate_promoted_quarterly_authority(package_root: Path | str) -> dict[str, str]:
    """Bind Q2 production to its immutable promotion receipt and live Master entry.

    The global authority manifest can legitimately evolve after the quarterly
    promotion.  Its whole-file hash is therefore not the stable Q2 identity;
    the promoted Master bytes and the manifest's unique authoritative Master
    entry are.
    """

    root = Path(package_root).resolve()
    receipt_path = root / PROMOTION_RECEIPT_REL
    master_path = root / QUARTERLY_MASTER_REL
    manifest_path = root / AUTHORITY_MANIFEST_REL
    if not all(path.is_file() for path in (receipt_path, master_path, manifest_path)):
        raise QuarterlyReportCompletionError("Q2_PROMOTED_AUTHORITY_ARTIFACT_MISSING")
    receipt_bytes = receipt_path.read_bytes()
    receipt_sha = persistence._sha256(receipt_bytes)
    if receipt_sha != EXPECTED_PROMOTION_RECEIPT_SHA256:
        raise QuarterlyReportCompletionError("Q2_PROMOTION_RECEIPT_HASH_MISMATCH")
    receipt = _read_json(receipt_path, "Q2_PROMOTION_RECEIPT")
    receipt_authority = receipt.get("authority")
    receipt_master = (
        receipt_authority.get("master")
        if isinstance(receipt_authority, Mapping)
        else None
    )
    receipt_manifest = (
        receipt_authority.get("manifest")
        if isinstance(receipt_authority, Mapping)
        else None
    )
    if not (
        receipt.get("schemaVersion") == "P1008_QUARTERLY_OWNER_PROMOTION_RECEIPT_V1"
        and receipt.get("reviewId") == PROMOTION_REVIEW_ID
        and receipt.get("status") == "PROMOTED"
        and receipt.get("ownerApproval") is True
        and receipt.get("approvalTokenRequired") == PROMOTION_APPROVAL_TOKEN
        and receipt.get("ownerApprovalToken") == PROMOTION_APPROVAL_TOKEN
        and receipt.get("actionable") is False
        and receipt.get("publishAuthorized") is False
        and isinstance(receipt_master, Mapping)
        and receipt_master.get("path") == QUARTERLY_MASTER_REL.as_posix()
        and receipt_master.get("candidateSha256") == receipt_master.get("afterSha256")
        and isinstance(receipt_manifest, Mapping)
        and receipt_manifest.get("path") == AUTHORITY_MANIFEST_REL.as_posix()
        and receipt_manifest.get("candidateSha256") == receipt_manifest.get("afterSha256")
    ):
        raise QuarterlyReportCompletionError("Q2_PROMOTION_RECEIPT_GOVERNANCE_INVALID")

    master_sha = persistence._sha256(master_path.read_bytes())
    if receipt_master.get("afterSha256") != master_sha:
        raise QuarterlyReportCompletionError("Q2_PROMOTED_MASTER_HASH_MISMATCH")
    manifest = _read_json(manifest_path, "Q2_LIVE_AUTHORITY_MANIFEST")
    entries = [
        item for item in manifest.get("authoritativeFiles", [])
        if isinstance(item, Mapping)
        and item.get("path") == QUARTERLY_MASTER_REL.as_posix()
    ]
    if len(entries) != 1:
        raise QuarterlyReportCompletionError("Q2_MASTER_AUTHORITY_ENTRY_INVALID")
    entry = entries[0]
    field_overrides = entry.get("fieldOverrides")
    receipt_lineage = receipt.get("fieldLineage")
    availability = receipt.get("availability")
    if not all(isinstance(item, Mapping) for item in (
        field_overrides, receipt_lineage, availability,
    )):
        raise QuarterlyReportCompletionError("Q2_QUARTERLY_LINEAGE_INVALID")
    roe = field_overrides.get("ROE_TTM_Pct")
    roic = field_overrides.get("ROIC_Status")
    receipt_roe = receipt_lineage.get("2026Q2.ROE_TTM_Pct")
    receipt_roic = receipt_lineage.get("2026Q2.ROIC")
    if not (
        manifest.get("manifestVersion") == EXPECTED_AUTHORITY_MANIFEST_VERSION
        and manifest.get("approvedBy") == "Owner"
        and manifest.get("authoritative") is True
        and manifest.get("actionable") is False
        and manifest.get("publishAuthorized") is False
        and entry.get("fileName") == QUARTERLY_MASTER_REL.name
        and entry.get("fileAuthority") == "CSV_AUTHORITY"
        and entry.get("sha256") == master_sha
        and entry.get("fieldAvailabilityContract")
        == "contracts/p1008_quarterly_authority/v1.0/"
        "P1008_QUARTERLY_FIELD_AVAILABILITY_CONTRACT_V1.json"
        and isinstance(roe, Mapping)
        and roe.get("latestValidQuarter") == availability.get("latestValidRoeQuarter")
        == "2026Q2"
        and str(roe.get("2026Q2Value")) == str(receipt_roe.get("value")) == "12.61"
        and isinstance(roic, Mapping)
        and roic.get("latestValidQuarter") == availability.get("latestValidRoicQuarter")
        == "2026Q1"
        and roic.get("2026Q2Value") == receipt_roic.get("availability")
        == "INSUFFICIENT_DATA"
        and availability.get("unavailableRoicQuarters") == ["2026Q2"]
    ):
        raise QuarterlyReportCompletionError("Q2_QUARTERLY_LINEAGE_INVALID")
    return {
        "manifestVersion": str(manifest["manifestVersion"]),
        "manifestSha256": persistence._sha256(manifest_path.read_bytes()),
        "masterSha256": master_sha,
        "promotionReceiptSha256": receipt_sha,
    }


def stable_report_key(trigger_lineage: Mapping[str, Any]) -> str:
    raw = str(trigger_lineage.get("reportKey") or "")
    token = re.sub(r"[^A-Z0-9_-]+", "_", raw.upper()).strip("_")
    if not token:
        raise QuarterlyReportCompletionError("QUARTERLY_REPORT_KEY_INVALID")
    return token


def _latest_slot(report_key: str) -> str:
    return f"quarterly:{report_key}"


def _validate_q2_inputs(
    code_root: Path,
    run_root: Path,
    result: Mapping[str, Any],
) -> tuple[AnalysisPacket, ReportCandidate, dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    manifest = _read_json(run_root / "run_manifest.json", "Q2_RUN_MANIFEST")
    evidence_manifest = _read_json(run_root / "evidence_manifest.json", "Q2_EVIDENCE_MANIFEST")
    validation = _read_json(run_root / "analysis_validation.json", "Q2_ANALYSIS_VALIDATION")
    output_root = Path(str(result.get("candidate_output_root") or "")).resolve()
    if not output_root.is_relative_to(run_root.resolve()):
        raise QuarterlyReportCompletionError("Q2_REPORT_OUTPUT_ROOT_INVALID")
    runtime_receipt = _read_json(
        output_root / "war_report_runtime_receipt.json", "Q2_REPORT_RUNTIME_RECEIPT"
    )
    html_path = output_root / "war_report_candidate.html"
    analysis_path = run_root / "analysis_packet.json"
    if not html_path.is_file() or not analysis_path.is_file():
        raise QuarterlyReportCompletionError("Q2_REPORT_ARTIFACT_MISSING")
    try:
        analysis = AnalysisPacket.model_validate_json(analysis_path.read_text(encoding="utf-8"))
        report_value = result.get("report")
        report = (
            report_value
            if isinstance(report_value, ReportCandidate)
            else ReportCandidate.model_validate(report_value)
        )
    except Exception as exc:  # pydantic errors are normalized to one fail-closed reason.
        raise QuarterlyReportCompletionError("Q2_CANDIDATE_SCHEMA_INVALID") from exc
    report = ReportValidator().validate(report, analysis)
    analysis_sha = persistence._sha256(analysis_path.read_bytes())
    trigger = manifest.get("triggerLineage")
    governed = manifest.get("governedEvidence")
    evidence_governed = evidence_manifest.get("governedEvidence")
    if not all(isinstance(item, Mapping) for item in (trigger, governed, evidence_governed)):
        raise QuarterlyReportCompletionError("Q2_GOVERNED_LINEAGE_MISSING")
    authority = validate_promoted_quarterly_authority(code_root)
    authority_sha = authority["manifestSha256"]
    if not (
        manifest.get("eventType") == EVENT_TYPE
        and manifest.get("reportRuntime") == REPORT_RUNTIME
        and manifest.get("state") in {
            "REPORT_CANDIDATE_READY", "OWNER_REVIEW_REQUIRED",
        }
        and analysis.event_type == EVENT_TYPE
        and report.event_type == EVENT_TYPE
        and validation.get("status") == "PASS"
        and validation.get("analysisPacketSha256") == analysis_sha
        and runtime_receipt.get("state") == "REPORT_CANDIDATE_READY"
        and runtime_receipt.get("trigger") == EVENT_TYPE
        and runtime_receipt.get("report_key") == trigger.get("reportKey")
        and runtime_receipt.get("revision") == trigger.get("revision")
        and runtime_receipt.get("output_html_sha256")
        == persistence._sha256(html_path.read_bytes())
        and governed == evidence_governed
        and governed.get("raw_artifact_sha256") == EXPECTED_Q2_RAW_SHA256
        and evidence_manifest.get("sourceHash") == EXPECTED_Q2_RAW_SHA256
        and analysis.quarterly_earnings is not None
        and analysis.quarterly_earnings.source_hash == EXPECTED_Q2_RAW_SHA256
        and analysis.authority_manifest_sha256 == authority_sha
        and governed.get("authority_manifest_version")
        == authority["manifestVersion"]
        and governed.get("authority_manifest_sha256")
        == authority_sha
        and trigger.get("eventType") == EVENT_TYPE
        and trigger.get("canonicalEventId") == "HON_HAI_FY2026_Q2_EARNINGS"
        and trigger.get("actionable") is False
        and isinstance(trigger.get("triggerReceiptSha256"), str)
        and len(trigger["triggerReceiptSha256"]) == 64
        and isinstance(governed.get("trigger_receipt_sha256"), str)
        and len(governed["trigger_receipt_sha256"]) == 64
        and isinstance(governed.get("authority_source_manifest_sha256"), str)
        and len(governed["authority_source_manifest_sha256"]) == 64
        and isinstance(governed.get("authority_q2_closeout_sha256"), str)
        and len(governed["authority_q2_closeout_sha256"]) == 64
        and runtime_receipt.get("historical_kpi_source_hashes", {}).get(
            "q2_official_filing"
        ) == EXPECTED_Q2_RAW_SHA256
        and runtime_receipt.get("publication") is False
        and runtime_receipt.get("actionable") is False
    ):
        raise QuarterlyReportCompletionError("Q2_PROVENANCE_OR_AUTHORITY_MISMATCH")
    return (
        analysis,
        report,
        dict(trigger),
        dict(governed),
        runtime_receipt,
        html_path,
    )


def _editorial_validation(report: ReportCandidate, analysis: AnalysisPacket) -> dict[str, Any]:
    scripts = ScriptBuilder()
    longform = scripts.longform(report)
    shorts = scripts.shorts_75s(report)
    duration = ShortsDurationValidator.validate(shorts)
    editorial = ReportValidator.editorial_result(
        report, analysis, longform, shorts, duration
    )
    payload = editorial.model_dump(mode="json", by_alias=True)
    if payload.get("status") != "PASS":
        raise QuarterlyReportCompletionError(
            "EDITORIAL_VALIDATION_FAILED: " + "; ".join(payload.get("errors") or [])
        )
    return payload


def _provenance(
    analysis: AnalysisPacket,
    trigger: Mapping[str, Any],
    governed: Mapping[str, Any],
    runtime_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    analytics = analysis.quarterly_earnings.enterprise_value_analytics or {}
    numeric_lineage = validate_working_capital_qoq_lineage(
        analytics.get("workingCapitalQoqIncrease"),
        expected_source_ids=[str(governed["event_id"])],
        expected_source_sha256=EXPECTED_Q2_RAW_SHA256,
        expected_source_page="8",
    )
    return {
        "canonicalEventId": trigger["canonicalEventId"],
        "triggerDecisionId": trigger["triggerDecisionId"],
        "currentCandidateWorkflowSha256": trigger["triggerReceiptSha256"],
        "historicalTriggerReceiptSha256": governed["trigger_receipt_sha256"],
        "officialIrEvidenceId": governed["event_id"],
        "officialIrReceiptId": governed["official_receipt_id"],
        "officialIrReceiptSha256": governed["official_receipt_sha256"],
        "q2ResultsRawSha256": governed["raw_artifact_sha256"],
        "compatibilityIntegrationSha256": governed["integration_sha256"],
        "authorityManifestVersion": governed["authority_manifest_version"],
        "authorityManifestSha256": governed["authority_manifest_sha256"],
        "phase3aSourceManifestSha256": governed["authority_source_manifest_sha256"],
        "q2CloseoutSha256": governed["authority_q2_closeout_sha256"],
        "analysisContractVersion": analysis.analysis_contract_version,
        "q2ConfigSha256": runtime_receipt["historical_kpi_source_hashes"]["q2_config"],
        "historicalKpiBaselineSha256": runtime_receipt["historical_kpi_baseline_sha256"],
        "forwardAnalyticsSha256": runtime_receipt["forward_analytics_sha256"],
        "decisionRulesSha256": runtime_receipt["decision_rules_sha256"],
        "numericClaimLineage": numeric_lineage,
    }


def _governed_content_sha(
    analysis_sha: str,
    report_sha: str,
    editorial_sha: str,
    html_sha: str,
    provenance: Mapping[str, Any],
) -> str:
    return persistence._sha256(persistence._canonical_bytes({
        "analysisCandidateSha256": analysis_sha,
        "reportCandidateSha256": report_sha,
        "editorialValidationSha256": editorial_sha,
        "htmlSha256": html_sha,
        "provenance": dict(provenance),
    }))


def _quarterly_entries(manifest: Mapping[str, Any], report_key: str) -> list[dict[str, Any]]:
    reports = manifest.get("reports")
    if not isinstance(reports, list):
        raise QuarterlyReportCompletionError("REPORT_MANIFEST_REPORTS_INVALID")
    return [
        dict(item) for item in reports
        if isinstance(item, Mapping)
        and item.get("eventType") == EVENT_TYPE
        and (item.get("report_key") or item.get("reportKey")) == report_key
    ]


def _validate_history(
    root: Path,
    runtime: Mapping[str, Any],
    library: Mapping[str, Any],
    report_key: str,
) -> list[dict[str, Any]]:
    left = _quarterly_entries(runtime, report_key)
    right = _quarterly_entries(library, report_key)
    left_by = {int(item.get("revision", 0)): item for item in left}
    right_by = {int(item.get("revision", 0)): item for item in right}
    if (
        0 in left_by or 0 in right_by
        or len(left_by) != len(left) or len(right_by) != len(right)
        or set(left_by) != set(right_by)
    ):
        raise QuarterlyReportCompletionError("QUARTERLY_REVISION_LINEAGE_INVALID")
    shared_fields = (
        "report_key", "revision", "eventType", "canonicalEventId",
        "analysisCandidateSha256", "reportCandidateSha256",
        "editorialValidationSha256", "governedContentSha256",
        "previousRevision", "previousGovernedContentSha256", "provenance",
        "renderedArtifacts", "ownerReviewLocator", "ownerReviewStatus",
        "publishAuthorized", "publication", "publicationComplete", "actionable",
    )
    for revision in sorted(left_by):
        lifecycle, private = left_by[revision], right_by[revision]
        if not (
            lifecycle.get("lifecycleState") == "OWNER_REVIEW_REQUIRED"
            and lifecycle.get("privateLibraryOwned") is False
            and private.get("status") == "OWNER_REVIEW_REQUIRED"
            and private.get("lifecycleOwned") is False
            and private.get("privateLibraryEligible") is True
            and len(lifecycle.get("renderedArtifacts") or []) == 2
            and {item.get("format") for item in lifecycle.get("renderedArtifacts", [])} == {"HTML", "PDF"}
        ):
            raise QuarterlyReportCompletionError("QUARTERLY_OWNERSHIP_OR_ARTIFACT_SET_INVALID")
        if any(lifecycle.get(field) != private.get(field) for field in shared_fields):
            raise QuarterlyReportCompletionError("QUARTERLY_LIFECYCLE_LIBRARY_DIVERGED")
        if revision == 1:
            if lifecycle.get("previousRevision") is not None:
                raise QuarterlyReportCompletionError("QUARTERLY_PREVIOUS_REVISION_INVALID")
        else:
            previous = left_by.get(revision - 1)
            if not previous or not (
                lifecycle.get("previousRevision") == revision - 1
                and lifecycle.get("previousGovernedContentSha256")
                == previous.get("governedContentSha256")
            ):
                raise QuarterlyReportCompletionError("QUARTERLY_PREVIOUS_REVISION_INVALID")
        for item in lifecycle.get("renderedArtifacts") or []:
            path = _safe_path(root, item.get("locator"), LIBRARY_CANDIDATE_ROOT)
            if not path.is_file() or not (
                persistence._sha256(path.read_bytes()) == item.get("sha256")
                and path.stat().st_size == item.get("sizeBytes")
            ):
                raise QuarterlyReportCompletionError("QUARTERLY_ARTIFACT_HASH_MISMATCH")
        candidate_path = _safe_path(
            root, lifecycle.get("reportCandidateLocator"), LIBRARY_CANDIDATE_ROOT
        )
        editorial_path = _safe_path(
            root, lifecycle.get("editorialValidationLocator"), LIBRARY_CANDIDATE_ROOT
        )
        candidate = _read_json(candidate_path, "QUARTERLY_REPORT_CANDIDATE")
        editorial = _read_json(editorial_path, "QUARTERLY_EDITORIAL_VALIDATION")
        if not (
            persistence._sha256(candidate_path.read_bytes())
            == lifecycle.get("reportCandidateSha256")
            and persistence._sha256(editorial_path.read_bytes())
            == lifecycle.get("editorialValidationSha256")
            and editorial.get("status") == "PASS"
            and editorial.get("reportCandidateSha256")
            == lifecycle.get("reportCandidateSha256")
        ):
            raise QuarterlyReportCompletionError("QUARTERLY_CANDIDATE_EDITORIAL_HASH_MISMATCH")
        html_items = [
            item for item in lifecycle.get("renderedArtifacts") or []
            if item.get("format") == "HTML"
        ]
        if len(html_items) != 1 or lifecycle.get("governedContentSha256") != _governed_content_sha(
            str(lifecycle.get("analysisCandidateSha256") or ""),
            str(lifecycle.get("reportCandidateSha256") or ""),
            str(lifecycle.get("editorialValidationSha256") or ""),
            str(html_items[0].get("sha256") or ""),
            lifecycle.get("provenance") or {},
        ):
            raise QuarterlyReportCompletionError("QUARTERLY_GOVERNED_CONTENT_HASH_MISMATCH")
        owner_path = _safe_path(root, lifecycle.get("ownerReviewLocator"), OWNER_REVIEW_ROOT)
        owner = _read_json(owner_path, "QUARTERLY_OWNER_REVIEW")
        unhashed = {key: value for key, value in owner.items() if key != "persistenceSha256"}
        if not (
            owner.get("persistenceSha256")
            == persistence._sha256(persistence._canonical_bytes(unhashed))
            and owner.get("report_key") == report_key
            and owner.get("revision") == revision
            and owner.get("analysisCandidateSha256")
            == lifecycle.get("analysisCandidateSha256")
            and owner.get("reportCandidateSha256")
            == lifecycle.get("reportCandidateSha256")
            and owner.get("editorialValidationSha256")
            == lifecycle.get("editorialValidationSha256")
            and owner.get("renderedArtifacts") == lifecycle.get("renderedArtifacts")
            and owner.get("provenance") == lifecycle.get("provenance")
            and owner.get("status") == "OWNER_REVIEW_REQUIRED"
            and owner.get("actionable") is False
            and owner.get("publishAuthorized") is False
            and owner.get("publication") is False
            and owner.get("publicationComplete") is False
        ):
            raise QuarterlyReportCompletionError("QUARTERLY_OWNER_REVIEW_INVALID")
    if left:
        latest_revision = max(left_by)
        slot = _latest_slot(report_key)
        for manifest in (runtime, library):
            pointer = (manifest.get("latest") or {}).get(slot)
            expected_pointer = left_by[latest_revision] if manifest is runtime else right_by[latest_revision]
            if not isinstance(pointer, Mapping) or pointer != expected_pointer:
                raise QuarterlyReportCompletionError("QUARTERLY_LATEST_STATE_STALE")
    return [left_by[key] for key in sorted(left_by)]


def quarterly_report_status(package_root: Path | str) -> dict[str, Any]:
    """Read-only API projection; persisted labels alone never establish success."""
    root = Path(package_root).resolve()
    empty = {"reportGenerated": False, "reportEligible": False, "latestQuarterly": None,
             "pendingOwnerReviews": [], "publication": False, "publishAuthorized": False}
    runtime_path = root / rolling_brief.RUNTIME_MANIFEST_REL
    library_path = root / rolling_brief.REPORT_MANIFEST_REL
    if not runtime_path.exists() and not library_path.exists():
        return {**empty, "status": "NO_QUARTERLY_REPORT"}
    try:
        runtime = _read_json(runtime_path, "RUNTIME_LIFECYCLE_MANIFEST")
        library = _read_json(library_path, "PRIVATE_LIBRARY_MANIFEST")
        rolling_brief._validate_manifest_relationship(runtime, library)
        keys = {str(item.get("report_key") or item.get("reportKey") or "")
                for manifest in (runtime, library) for item in manifest.get("reports", [])
                if item.get("eventType") == EVENT_TYPE}
        reports = []
        for key in sorted(keys):
            history = _validate_history(root, runtime, library, key)
            reports.append(history[-1])
        for item in reports:
            if (item.get("lifecycleState") != "OWNER_REVIEW_REQUIRED"
                    or any(item.get(flag) is not False for flag in ("actionable", "publishAuthorized", "publication", "publicationComplete"))):
                raise QuarterlyReportCompletionError("QUARTERLY_STATE_INVALID")
        latest = sorted(reports, key=lambda item: (str(item.get("canonicalEventId")), item["revision"]))[-1] if reports else None
        return {**empty, "status": "OWNER_REVIEW_REQUIRED" if latest else "NO_QUARTERLY_REPORT",
                "reportGenerated": bool(latest), "reportEligible": bool(latest),
                "latestQuarterly": latest, "pendingOwnerReviews": reports}
    except Exception as exc:  # Read-only status boundary must never expose unvalidated success.
        return {**empty, "status": "FAIL_CLOSED", "reason": str(exc)}


def complete_quarterly_report(
    package_root: Path | str,
    result: Mapping[str, Any],
    *,
    persistence_root: Path | str | None = None,
    completed_at_utc: str | None = None,
) -> dict[str, Any]:
    """Complete one Quarterly EV revision without publishing it."""

    code = Path(package_root).resolve()
    state = Path(persistence_root).resolve() if persistence_root else code
    run_root = Path(str(result.get("run_root") or "")).resolve()
    try:
        if not run_root.is_relative_to(code / "runtime" / "report_production"):
            raise QuarterlyReportCompletionError("Q2_RUN_ROOT_OUTSIDE_GOVERNED_RUNTIME")
        analysis, report, trigger, governed, runtime_receipt, html_source = _validate_q2_inputs(
            code, run_root, result
        )
        editorial = _editorial_validation(report, analysis)
        editorial_bytes = persistence._canonical_bytes(editorial)
        editorial_sha = persistence._sha256(editorial_bytes)
        report_payload = report.model_dump(mode="json", by_alias=True)
        report_bytes = canonical_json_bytes(report_payload)
        report_sha = _candidate_sha(report)
        analysis_sha = persistence._sha256((run_root / "analysis_packet.json").read_bytes())
        html_bytes = html_source.read_bytes()
        html_sha = persistence._sha256(html_bytes)
        chart_values = json.loads(
            (Path(str(result["candidate_output_root"])) / "chart_data_full_history.json")
            .read_text(encoding="utf-8")
        )
        charts = [ChartData.model_validate(item) for item in chart_values]
        formula_cards = list(
            (analysis.quarterly_earnings.enterprise_value_analytics or {}).get(
                "formulaCards", []
            )
        )
        pdf_bytes = FormalPreviewRenderer().pdf(report, charts, formula_cards)
        if not pdf_bytes.startswith(b"%PDF-"):
            raise QuarterlyReportCompletionError("QUARTERLY_PDF_RENDER_INVALID")
        provenance = _provenance(analysis, trigger, governed, runtime_receipt)
        report_text = "\n".join(item.body_zh for item in report.sections)
        if "174,738百萬元" not in report_text:
            raise QuarterlyReportCompletionError("Q2_NUMERIC_CLAIM_LINEAGE_MISSING")
        report_key = stable_report_key(trigger)
        requested_revision = int(trigger.get("revision") or 0)
        if requested_revision < 1:
            raise QuarterlyReportCompletionError("EXPLICIT_POSITIVE_REVISION_REQUIRED")

        health = rolling_brief.bootstrap_report_library(state)
        if health.get("status") not in {
            "REPORT_LIBRARY_BOOTSTRAPPED_EMPTY", "REPORT_LIBRARY_EXISTING_HEALTHY",
        }:
            raise QuarterlyReportCompletionError(
                str(
                    health.get("message")
                    or health.get("code")
                    or "REPORT_LIBRARY_MANIFEST_INVALID"
                )
            )
        runtime_path = state / rolling_brief.RUNTIME_MANIFEST_REL
        library_path = state / rolling_brief.REPORT_MANIFEST_REL
        runtime = _read_json(runtime_path, "RUNTIME_LIFECYCLE_MANIFEST")
        library = _read_json(library_path, "PRIVATE_LIBRARY_MANIFEST")
        history = _validate_history(state, runtime, library, report_key)
        content_sha = _governed_content_sha(
            analysis_sha, report_sha, editorial_sha, html_sha, provenance
        )
        same = [item for item in history if item.get("governedContentSha256") == content_sha]
        if same:
            existing = same[0]
            checkpoint = _read_json(run_root / "run_manifest.json", "Q2_RUN_MANIFEST")
            expected_completion = {
                "reportKey": report_key, "revision": existing["revision"],
                "editorialValidationSha256": editorial_sha,
                "renderedArtifacts": existing["renderedArtifacts"],
                "runtimeManifestPath": rolling_brief.RUNTIME_MANIFEST_REL,
                "privateLibraryManifestPath": rolling_brief.REPORT_MANIFEST_REL,
                "ownerReviewLocator": existing["ownerReviewLocator"],
                "publishAuthorized": False, "publication": False,
                "publicationComplete": False, "actionable": False,
            }
            if checkpoint.get("state") != "OWNER_REVIEW_REQUIRED" or checkpoint.get("reportCompletion") != expected_completion:
                raise QuarterlyReportCompletionError("QUARTERLY_COMPLETION_CHECKPOINT_MISMATCH")
            gate = publication_gate.validate_absent_authorization(
                state, report_key=report_key, revision=existing["revision"],
                event_type=EVENT_TYPE,
            )
            return {
                "status": "IDEMPOTENT_REPLAY", "report_key": report_key,
                "revision": existing["revision"], "persisted": False,
                "analysisCandidateSha256": analysis_sha,
                "reportCandidateSha256": report_sha,
                "editorialValidationSha256": editorial_sha,
                "duplicateRevisionCreated": False, "publicationGate": gate,
                "publishAuthorized": False, "publication": False,
                "publicationComplete": False, "actionable": False,
            }
        expected_revision = len(history) + 1
        if _read_json(run_root / "run_manifest.json", "Q2_RUN_MANIFEST").get("state") == "OWNER_REVIEW_REQUIRED":
            raise QuarterlyReportCompletionError("QUARTERLY_PERSISTED_HISTORY_MISSING")
        if requested_revision != expected_revision:
            return {
                "status": "REVIEW_REQUIRED",
                "reason": "EXPLICIT_REVISION_SEQUENCE_MISMATCH",
                "persisted": False, "publishAuthorized": False,
                "publication": False, "publicationComplete": False,
                "actionable": False,
            }
        previous = history[-1] if history else None
        token = re.sub(r"[^A-Z0-9_-]+", "_", report_key)
        base = LIBRARY_CANDIDATE_ROOT / token / f"r{requested_revision}"
        candidate_rel = base / "report_candidate.json"
        editorial_rel = base / "editorial_validation.json"
        html_rel = base / "rendered" / "owner_review.html"
        pdf_rel = base / "rendered" / "owner_review.pdf"
        owner_rel = OWNER_REVIEW_ROOT / token / f"r{requested_revision}" / "owner_review.json"
        paths = {rel: state / rel for rel in (candidate_rel, editorial_rel, html_rel, pdf_rel, owner_rel)}
        if any(path.exists() for path in paths.values()):
            raise QuarterlyReportCompletionError("QUARTERLY_REVISION_ARTIFACT_COLLISION")
        artifacts = [
            {"format": "HTML", "locator": html_rel.as_posix(), "sha256": html_sha, "sizeBytes": len(html_bytes), "sourceReportCandidateSha256": report_sha},
            {"format": "PDF", "locator": pdf_rel.as_posix(), "sha256": persistence._sha256(pdf_bytes), "sizeBytes": len(pdf_bytes), "sourceReportCandidateSha256": report_sha},
        ]
        owner_payload = {
            "recordType": "P1008_QUARTERLY_OWNER_REVIEW_PERSISTENCE_V1",
            "schemaVersion": "1.0", "report_key": report_key,
            "revision": requested_revision, "eventType": EVENT_TYPE,
            "canonicalEventId": trigger["canonicalEventId"],
            "analysisCandidateSha256": analysis_sha,
            "reportCandidateSha256": report_sha,
            "editorialValidationSha256": editorial_sha,
            "renderedArtifacts": artifacts, "provenance": provenance,
            "status": "OWNER_REVIEW_REQUIRED", "decisionState": "PENDING",
            "ownerApproved": False, "publicationEligibility": False,
            "publishAuthorized": False, "publication": False,
            "publicationComplete": False, "actionable": False,
        }
        owner = {
            **owner_payload,
            "persistenceSha256": persistence._sha256(
                persistence._canonical_bytes(owner_payload)
            ),
        }
        shared = {
            "id": f"{token}_R{requested_revision}", "report_key": report_key,
            "revision": requested_revision, "eventType": EVENT_TYPE,
            "canonicalEventId": trigger["canonicalEventId"],
            "analysisCandidateSha256": analysis_sha,
            "reportCandidateSha256": report_sha,
            "editorialValidationSha256": editorial_sha,
            "governedContentSha256": content_sha,
            "previousRevision": previous.get("revision") if previous else None,
            "previousGovernedContentSha256": previous.get("governedContentSha256") if previous else None,
            "provenance": provenance, "renderedArtifacts": artifacts,
            "reportCandidateLocator": candidate_rel.as_posix(),
            "editorialValidationLocator": editorial_rel.as_posix(),
            "ownerReviewLocator": owner_rel.as_posix(),
            "ownerReviewStatus": "OWNER_REVIEW_REQUIRED",
            "pluginArtifacts": [
                {"path": candidate_rel.as_posix(), "sha256": report_sha},
                {"path": editorial_rel.as_posix(), "sha256": editorial_sha},
                *[{"path": item["locator"], "sha256": item["sha256"]} for item in artifacts],
                {"path": owner_rel.as_posix(), "sha256": persistence._sha256(persistence._canonical_bytes(owner))},
            ],
            "publishAuthorized": False, "publication": False,
            "publicationComplete": False, "actionable": False,
        }
        lifecycle = {
            **shared,
            "recordType": "P1008_QUARTERLY_REPORT_LIFECYCLE_ENTRY_V1",
            "lifecycleState": "OWNER_REVIEW_REQUIRED", "privateLibraryOwned": False,
        }
        private = {
            **shared,
            "recordType": "P1008_QUARTERLY_PRIVATE_LIBRARY_ENTRY_V1",
            "status": "OWNER_REVIEW_REQUIRED", "privateLibraryEligible": True,
            "libraryEligible": True, "lifecycleOwned": False,
        }
        stamp = completed_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        runtime_next, library_next = copy.deepcopy(runtime), copy.deepcopy(library)
        runtime_next["generatedAt"] = stamp
        library_next["generatedAt"] = stamp
        runtime_next["reports"].append(lifecycle)
        library_next["reports"].append(private)
        runtime_next["latest"][_latest_slot(report_key)] = lifecycle
        library_next["latest"][_latest_slot(report_key)] = private
        rolling_brief._validate_manifest_relationship(runtime_next, library_next)
        run_manifest = _read_json(run_root / "run_manifest.json", "Q2_RUN_MANIFEST")
        run_manifest.update({
            "state": "OWNER_REVIEW_REQUIRED",
            "reportCompletion": {
                "reportKey": report_key, "revision": requested_revision,
                "editorialValidationSha256": editorial_sha,
                "renderedArtifacts": artifacts,
                "runtimeManifestPath": rolling_brief.RUNTIME_MANIFEST_REL,
                "privateLibraryManifestPath": rolling_brief.REPORT_MANIFEST_REL,
                "ownerReviewLocator": owner_rel.as_posix(),
                "publishAuthorized": False, "publication": False,
                "publicationComplete": False, "actionable": False,
            },
        })
        output_editorial = Path(str(result["candidate_output_root"])) / "editorial_validation.json"
        run_manifest.setdefault("artifacts", {})[
            "enterprise_value_war_report/editorial_validation.json"
        ] = editorial_sha
        persistence._atomic_transaction({
            paths[candidate_rel]: report_bytes,
            paths[editorial_rel]: editorial_bytes,
            paths[html_rel]: html_bytes,
            paths[pdf_rel]: pdf_bytes,
            paths[owner_rel]: persistence._canonical_bytes(owner),
            output_editorial: editorial_bytes,
            runtime_path: rolling_brief._canonical_json_bytes(runtime_next),
            library_path: rolling_brief._canonical_json_bytes(library_next),
            run_root / "run_manifest.json": persistence._canonical_bytes(run_manifest),
        })
        _validate_history(state, runtime_next, library_next, report_key)
        gate = publication_gate.validate_absent_authorization(
            state, report_key=report_key, revision=requested_revision,
            event_type=EVENT_TYPE,
        )
        if gate.get("status") != "DENIED":
            raise QuarterlyReportCompletionError("PUBLICATION_GATE_NOT_DENIED")
        return {
            "status": "OWNER_REVIEW_REQUIRED", "report_key": report_key,
            "revision": requested_revision, "editorialValidationSha256": editorial_sha,
            "analysisCandidateSha256": analysis_sha,
            "reportCandidateSha256": report_sha,
            "artifacts": artifacts, "ownerReviewLocator": owner_rel.as_posix(),
            "runtimeManifestPath": rolling_brief.RUNTIME_MANIFEST_REL,
            "privateLibraryManifestPath": rolling_brief.REPORT_MANIFEST_REL,
            "persisted": True, "duplicateRevisionCreated": False,
            "publicationGate": gate, "publishAuthorized": False,
            "publication": False, "publicationComplete": False, "actionable": False,
        }
    except Exception as exc:  # noqa: BLE001 - this boundary is deliberately fail-closed.
        return {
            "status": "FAIL_CLOSED", "reason": str(exc) or type(exc).__name__,
            "persisted": False, "publishAuthorized": False,
            "publication": False, "publicationComplete": False,
            "actionable": False,
        }
