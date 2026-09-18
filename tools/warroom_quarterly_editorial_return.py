#!/usr/bin/env python3
"""Governed editorial-return versions inside an existing quarterly revision."""

from __future__ import annotations

import copy
import difflib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import warroom_major_event_report_persistence as persistence
import warroom_quarterly_report_completion as completion
import warroom_rolling_brief as rolling_brief

from p1008_research_plugin.analysis.analysis_contracts import AnalysisPacket
from p1008_research_plugin.reporting.report_contracts import ChartData, ReportCandidate
from p1008_research_plugin.reporting.report_renderer_formal import FormalPreviewRenderer
from p1008_research_plugin.reporting.report_validator import ReportValidator
from p1008_research_plugin.reporting.script_builder import ScriptBuilder, ShortsDurationValidator


class QuarterlyEditorialReturnError(RuntimeError):
    """Editorial return could not satisfy the existing quarterly governance."""


HISTORY_RECORD_TYPE = "P1008_QUARTERLY_EDITORIAL_HISTORY_V1"
SNAPSHOT_RECORD_TYPE = "P1008_QUARTERLY_EDITORIAL_SNAPSHOT_V1"
ALLOWED_IMPORT_KEYS = {
    "report_key", "revision", "parentEditorialVersion", "reportCandidate"
}
PUBLICATION_FLAGS = ("publication", "publishAuthorized", "publicationComplete", "actionable")


def _now(value: str | None = None) -> str:
    return value or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QuarterlyEditorialReturnError(code) from exc
    if not isinstance(value, dict):
        raise QuarterlyEditorialReturnError(code)
    return value


def _token(report_key: str) -> str:
    if not re.fullmatch(r"P1008_FY\d{4}_Q[1-4]_EARNINGS", report_key):
        raise QuarterlyEditorialReturnError("QUARTERLY_REPORT_KEY_INVALID")
    return report_key


def _base(report_key: str, revision: int) -> Path:
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise QuarterlyEditorialReturnError("QUARTERLY_REVISION_INVALID")
    return completion.LIBRARY_CANDIDATE_ROOT / _token(report_key) / f"r{revision}"


def _history_rel(report_key: str, revision: int) -> Path:
    return _base(report_key, revision) / "editorial_versions" / "history.json"


def _snapshot_rel(report_key: str, revision: int, version: str) -> Path:
    return _base(report_key, revision) / "editorial_versions" / version / "snapshot.json"


def _load_manifests(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    runtime = _read_json(root / rolling_brief.RUNTIME_MANIFEST_REL, "RUNTIME_MANIFEST_INVALID")
    library = _read_json(root / rolling_brief.REPORT_MANIFEST_REL, "REPORT_MANIFEST_INVALID")
    rolling_brief._validate_manifest_relationship(runtime, library, package_root=root)
    return runtime, library


def _entries(manifest: Mapping[str, Any], report_key: str, revision: int) -> list[dict[str, Any]]:
    return [item for item in manifest.get("reports", []) if isinstance(item, dict)
            and item.get("eventType") == completion.EVENT_TYPE
            and (item.get("report_key") or item.get("reportKey")) == report_key
            and item.get("revision") == revision]


def _governed_entry(root: Path, report_key: str, revision: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    runtime, library = _load_manifests(root)
    completion._validate_history(root, runtime, library, report_key)
    left, right = _entries(runtime, report_key, revision), _entries(library, report_key, revision)
    if len(left) != 1 or len(right) != 1:
        raise QuarterlyEditorialReturnError("QUARTERLY_REPORT_REVISION_NOT_UNIQUE")
    lifecycle, catalog = left[0], right[0]
    if not (lifecycle.get("lifecycleState") == "OWNER_REVIEW_REQUIRED"
            and catalog.get("status") == "OWNER_REVIEW_REQUIRED"
            and all(lifecycle.get(flag) is False for flag in PUBLICATION_FLAGS)
            and all(catalog.get(flag) is False for flag in PUBLICATION_FLAGS)):
        raise QuarterlyEditorialReturnError("EDITORIAL_RETURN_LIFECYCLE_INVALID")
    return runtime, library, lifecycle, catalog


def _analysis(root: Path, report: ReportCandidate, entry: Mapping[str, Any]) -> tuple[AnalysisPacket, list[ChartData], list[dict[str, str]]]:
    run_root = (root / "runtime" / "report_production" / report.run_id).resolve()
    expected = (root / "runtime" / "report_production").resolve()
    if not run_root.is_relative_to(expected):
        raise QuarterlyEditorialReturnError("EDITORIAL_ANALYSIS_LOCATOR_INVALID")
    analysis_path = run_root / "analysis_packet.json"
    if not analysis_path.is_file() or persistence._sha256(analysis_path.read_bytes()) != entry.get("analysisCandidateSha256"):
        raise QuarterlyEditorialReturnError("EDITORIAL_ANALYSIS_LINEAGE_INVALID")
    analysis = AnalysisPacket.model_validate(_read_json(analysis_path, "EDITORIAL_ANALYSIS_INVALID"))
    provenance = entry.get("provenance")
    if not (isinstance(analysis.authority_manifest_sha256, str)
            and len(analysis.authority_manifest_sha256) == 64
            and isinstance(report.authority_manifest_sha256, str)
            and len(report.authority_manifest_sha256) == 64
            and isinstance(provenance, Mapping)
            and provenance.get("canonicalEventId") == entry.get("canonicalEventId")
            and isinstance(provenance.get("authorityManifestSha256"), str)
            and len(provenance["authorityManifestSha256"]) == 64):
        raise QuarterlyEditorialReturnError("EDITORIAL_AUTHORITY_LINEAGE_INVALID")
    chart_path = run_root / "enterprise_value_war_report" / "chart_data_full_history.json"
    chart_values = json.loads(chart_path.read_text(encoding="utf-8")) if chart_path.is_file() else []
    charts = [ChartData.model_validate(item) for item in chart_values]
    formulas = list((analysis.quarterly_earnings.enterprise_value_analytics or {}).get("formulaCards", []))
    return analysis, charts, formulas


def _active_candidate(root: Path, entry: Mapping[str, Any]) -> tuple[ReportCandidate, Path]:
    path = completion._safe_path(root, entry.get("reportCandidateLocator"), completion.LIBRARY_CANDIDATE_ROOT)
    if persistence._sha256(path.read_bytes()) != entry.get("reportCandidateSha256"):
        raise QuarterlyEditorialReturnError("EDITORIAL_SOURCE_CONTENT_HASH_INVALID")
    return ReportCandidate.model_validate(_read_json(path, "EDITORIAL_SOURCE_CONTENT_INVALID")), path


def _editorial_validation(returned: ReportCandidate, analysis: AnalysisPacket, source: ReportCandidate) -> dict[str, Any]:
    """Validate editorial output, adding the governed active report as numeric lineage.

    The active report may contain later authority-backed values that are absent
    from its immutable analysis packet.  Those exact Decimal values are valid
    lineage; a newly introduced numeric value is not.
    """
    scripts = ScriptBuilder()
    longform = scripts.longform(returned)
    shorts = scripts.shorts_75s(returned)
    duration = ShortsDurationValidator.validate(shorts)
    result = ReportValidator.editorial_result(returned, analysis, longform, shorts, duration)
    payload = result.model_dump(mode="json", by_alias=True)
    returned_text = json.dumps(returned.model_dump(mode="json", by_alias=True), ensure_ascii=False)
    source_text = json.dumps(source.model_dump(mode="json", by_alias=True), ensure_ascii=False)
    analysis_text = json.dumps(analysis.model_dump(mode="json", by_alias=True), ensure_ascii=False)
    unsupported = ReportValidator._numbers(returned_text) - (
        ReportValidator._numbers(source_text) | ReportValidator._numbers(analysis_text) | {"1", "5", "20"}
    )
    errors = [item for item in payload.get("errors", []) if not item.startswith("Unsupported numeric claims:")]
    if unsupported:
        errors.append("Unsupported numeric claims: " + ", ".join(sorted(unsupported)))
    payload["unsupportedNumericClaimsAbsent"] = not unsupported
    payload["errors"] = errors
    payload["status"] = "FAIL" if errors else "PASS"
    if errors:
        raise QuarterlyEditorialReturnError("EDITORIAL_VALIDATION_FAILED: " + "; ".join(errors))
    return payload


def _validate_immutable_lineage(source: ReportCandidate, returned: ReportCandidate) -> None:
    immutable = ("record_type", "run_id", "event_type", "generated_at_utc", "report_contract_version",
                 "analysis_packet_sha256", "authority_manifest_sha256",
                 "thesis_state", "evidence_bound_facts", "evidence_references", "actionable")
    if any(getattr(source, field) != getattr(returned, field) for field in immutable):
        raise QuarterlyEditorialReturnError("EDITORIAL_GOVERNED_FACT_OR_LINEAGE_CHANGED")
    source_lineage = [(item.section_id, item.epistemic_class, item.evidence_ids) for item in source.sections]
    returned_lineage = [(item.section_id, item.epistemic_class, item.evidence_ids) for item in returned.sections]
    if source_lineage != returned_lineage:
        raise QuarterlyEditorialReturnError("EDITORIAL_SECTION_EVIDENCE_LINEAGE_CHANGED")


def _virtual_e0(root: Path, report_key: str, revision: int, entry: Mapping[str, Any]) -> dict[str, Any]:
    _, candidate_path = _active_candidate(root, entry)
    return {
        "report_key": report_key, "revision": revision,
        "editorialVersion": "e0", "parentEditorialVersion": None,
        "createdAt": None, "sourceContentSha256": entry["reportCandidateSha256"],
        "returnedContentSha256": entry["reportCandidateSha256"], "diffSha256": None,
        "authorityProvenanceBinding": copy.deepcopy(entry.get("provenance") or {}),
        "numericValidationResult": {"status": "PASS", "baseline": True},
        "ownerApplied": True,
        "resultingHtmlSha256": next(item["sha256"] for item in entry["renderedArtifacts"] if item["format"] == "HTML"),
        "resultingPdfSha256": next(item["sha256"] for item in entry["renderedArtifacts"] if item["format"] == "PDF"),
        "candidateLocator": candidate_path.relative_to(root).as_posix(),
        "status": "ORIGINAL_GOVERNED_OWNER_REVIEW",
    }


def _validate_persisted_history(root: Path, history: Mapping[str, Any], report_key: str, revision: int) -> None:
    versions = history.get("versions")
    if not (history.get("recordType") == HISTORY_RECORD_TYPE
            and history.get("report_key") == report_key and history.get("revision") == revision
            and isinstance(versions, list) and versions):
        raise QuarterlyEditorialReturnError("EDITORIAL_HISTORY_INVALID")
    expected_parent = None
    current_count = 0
    for index, item in enumerate(versions):
        version = f"e{index}"
        if not isinstance(item, dict) or item.get("editorialVersion") != version or item.get("parentEditorialVersion") != expected_parent:
            raise QuarterlyEditorialReturnError("EDITORIAL_VERSION_LINEAGE_INVALID")
        snapshot_rel = Path(str(item.get("snapshotLocator") or ""))
        if snapshot_rel != _snapshot_rel(report_key, revision, version):
            raise QuarterlyEditorialReturnError("EDITORIAL_SNAPSHOT_LOCATOR_INVALID")
        snapshot_path = (root / snapshot_rel).resolve()
        if not snapshot_path.is_relative_to((root / _base(report_key, revision)).resolve()) or not snapshot_path.is_file():
            raise QuarterlyEditorialReturnError("EDITORIAL_SNAPSHOT_LOCATOR_INVALID")
        if persistence._sha256(snapshot_path.read_bytes()) != item.get("snapshotSha256"):
            raise QuarterlyEditorialReturnError("EDITORIAL_SNAPSHOT_HASH_INVALID")
        snapshot = _read_json(snapshot_path, "EDITORIAL_SNAPSHOT_INVALID")
        if snapshot.get("editorialVersion") != version or snapshot.get("report_key") != report_key or snapshot.get("revision") != revision:
            raise QuarterlyEditorialReturnError("EDITORIAL_SNAPSHOT_IDENTITY_INVALID")
        expected_parent = version
        if item.get("ownerApplied") is True:
            current_count += int(history.get("currentEditorialVersion") == version)
    if current_count != 1:
        raise QuarterlyEditorialReturnError("CURRENT_EDITORIAL_VERSION_INVALID")


def editorial_history(package_root: Path | str, report_key: str, revision: int) -> dict[str, Any]:
    root = Path(package_root).resolve()
    _, _, entry, _ = _governed_entry(root, report_key, revision)
    path = root / _history_rel(report_key, revision)
    if not path.is_file():
        e0 = _virtual_e0(root, report_key, revision, entry)
        return {"recordType": HISTORY_RECORD_TYPE, "report_key": report_key,
                "revision": revision, "currentEditorialVersion": "e0",
                "versions": [e0], "initialized": False, "actionable": False}
    history = _read_json(path, "EDITORIAL_HISTORY_INVALID")
    _validate_persisted_history(root, history, report_key, revision)
    if entry.get("editorialHistorySha256") and persistence._sha256(path.read_bytes()) != entry["editorialHistorySha256"]:
        raise QuarterlyEditorialReturnError("EDITORIAL_HISTORY_HASH_INVALID")
    return {**history, "initialized": True}


def quarterly_editorial_catalog(package_root: Path | str) -> dict[str, Any]:
    root = Path(package_root).resolve()
    runtime, library = _load_manifests(root)
    seen: set[tuple[str, int]] = set()
    reports = []
    for item in library.get("reports", []):
        if not isinstance(item, dict) or item.get("eventType") != completion.EVENT_TYPE:
            continue
        identity = (str(item.get("report_key") or item.get("reportKey")), int(item.get("revision") or 0))
        if identity in seen:
            raise QuarterlyEditorialReturnError("DUPLICATE_QUARTERLY_REPORT_CARD")
        seen.add(identity)
        completion._validate_history(root, runtime, library, identity[0])
        history = editorial_history(root, *identity)
        reports.append({"report_key": identity[0], "revision": identity[1],
                        "canonicalEventId": item.get("canonicalEventId"),
                        "state": item.get("status"),
                        "currentEditorialVersion": history["currentEditorialVersion"],
                        "versions": history["versions"]})
    reports.sort(key=lambda item: (str(item["canonicalEventId"]), item["revision"]), reverse=True)
    return {"status": "PASS", "reports": reports, "reportCardCount": len(reports), "actionable": False}


def _e0_payloads(root: Path, report_key: str, revision: int, entry: Mapping[str, Any], stamp: str) -> tuple[dict[Path, bytes], dict[str, Any]]:
    version_root = _base(report_key, revision) / "editorial_versions" / "e0"
    sources = {
        "report_candidate.json": Path(entry["reportCandidateLocator"]),
        "editorial_validation.json": Path(entry["editorialValidationLocator"]),
        "owner_review.json": Path(entry["ownerReviewLocator"]),
    }
    for artifact in entry["renderedArtifacts"]:
        sources[f"owner_review.{artifact['format'].lower()}"] = Path(artifact["locator"])
    payloads: dict[Path, bytes] = {}
    stored = []
    for name, source_rel in sources.items():
        body = (root / source_rel).read_bytes()
        target_rel = version_root / name
        payloads[root / target_rel] = body
        stored.append({"locator": target_rel.as_posix(), "sha256": persistence._sha256(body), "sizeBytes": len(body)})
    snapshot = {**_virtual_e0(root, report_key, revision, entry),
                "recordType": SNAPSHOT_RECORD_TYPE, "createdAt": stamp,
                "candidateLocator": (version_root / "report_candidate.json").as_posix(),
                "storedArtifacts": stored}
    snapshot_body = persistence._canonical_bytes(snapshot)
    snapshot_rel = _snapshot_rel(report_key, revision, "e0")
    payloads[root / snapshot_rel] = snapshot_body
    ref = {"editorialVersion": "e0", "parentEditorialVersion": None,
           "snapshotLocator": snapshot_rel.as_posix(), "snapshotSha256": persistence._sha256(snapshot_body),
           "ownerApplied": True, "status": snapshot["status"]}
    return payloads, ref


def import_editorial_return(package_root: Path | str, envelope: Mapping[str, Any], *, created_at: str | None = None) -> dict[str, Any]:
    root = Path(package_root).resolve()
    try:
        if set(envelope) != ALLOWED_IMPORT_KEYS:
            raise QuarterlyEditorialReturnError("EDITORIAL_IMPORT_ENVELOPE_INVALID")
        report_key, revision = str(envelope["report_key"]), envelope["revision"]
        if isinstance(revision, bool) or not isinstance(revision, int):
            raise QuarterlyEditorialReturnError("EDITORIAL_IMPORT_REVISION_MISMATCH")
        _, _, entry, _ = _governed_entry(root, report_key, revision)
        history = editorial_history(root, report_key, revision)
        current = history["currentEditorialVersion"]
        if envelope.get("parentEditorialVersion") != current:
            raise QuarterlyEditorialReturnError("EDITORIAL_PARENT_VERSION_MISMATCH")
        if any(item.get("status") == "PENDING" for item in history["versions"]):
            raise QuarterlyEditorialReturnError("EDITORIAL_PENDING_VERSION_EXISTS")
        source, _ = _active_candidate(root, entry)
        returned = ReportCandidate.model_validate(envelope.get("reportCandidate"))
        _validate_immutable_lineage(source, returned)
        analysis, _, _ = _analysis(root, returned, entry)
        numeric = _editorial_validation(returned, analysis, source)
        returned_body = persistence._canonical_bytes(returned.model_dump(mode="json", by_alias=True))
        source_body = persistence._canonical_bytes(source.model_dump(mode="json", by_alias=True))
        diff_text = "".join(difflib.unified_diff(
            source_body.decode().splitlines(True), returned_body.decode().splitlines(True),
            fromfile=current, tofile=f"e{len(history['versions'])}"))
        diff_body = diff_text.encode("utf-8")
        version = f"e{len(history['versions'])}"
        stamp = _now(created_at)
        version_root = _base(report_key, revision) / "editorial_versions" / version
        candidate_rel = version_root / "returned_report_candidate.json"
        validation_rel = version_root / "editorial_validation.json"
        diff_rel = version_root / "editorial.diff"
        snapshot_rel = _snapshot_rel(report_key, revision, version)
        snapshot = {
            "recordType": SNAPSHOT_RECORD_TYPE, "report_key": report_key, "revision": revision,
            "editorialVersion": version, "parentEditorialVersion": current, "createdAt": stamp,
            "sourceContentSha256": persistence._sha256(source_body),
            "returnedContentSha256": persistence._sha256(returned_body),
            "diffSha256": persistence._sha256(diff_body),
            "authorityProvenanceBinding": copy.deepcopy(entry.get("provenance") or {}),
            "numericValidationResult": numeric, "ownerApplied": False,
            "resultingHtmlSha256": None, "resultingPdfSha256": None,
            "candidateLocator": candidate_rel.as_posix(), "validationLocator": validation_rel.as_posix(),
            "diffLocator": diff_rel.as_posix(), "status": "PENDING", "actionable": False,
        }
        snapshot_body = persistence._canonical_bytes(snapshot)
        payloads: dict[Path, bytes] = {}
        if not history["initialized"]:
            initial, e0_ref = _e0_payloads(root, report_key, revision, entry, stamp)
            payloads.update(initial)
            version_refs = [e0_ref]
        else:
            version_refs = copy.deepcopy(history["versions"])
        version_refs.append({"editorialVersion": version, "parentEditorialVersion": current,
                             "snapshotLocator": snapshot_rel.as_posix(), "snapshotSha256": persistence._sha256(snapshot_body),
                             "ownerApplied": False, "status": "PENDING"})
        next_history = {"recordType": HISTORY_RECORD_TYPE, "report_key": report_key, "revision": revision,
                        "currentEditorialVersion": current, "versions": version_refs,
                        "updatedAt": stamp, "actionable": False}
        payloads.update({root / candidate_rel: returned_body,
                         root / validation_rel: persistence._canonical_bytes(numeric),
                         root / diff_rel: diff_body, root / snapshot_rel: snapshot_body,
                         root / _history_rel(report_key, revision): persistence._canonical_bytes(next_history)})
        persistence._atomic_transaction(payloads)
        _validate_persisted_history(root, next_history, report_key, revision)
        return {"status": "PENDING", "report_key": report_key, "revision": revision,
                "editorialVersion": version, "currentEditorialVersion": current,
                "validation": "PASS", "ownerApplied": False, "actionable": False}
    except Exception as exc:
        return {"status": "FAIL_CLOSED", "reason": str(exc) or type(exc).__name__,
                "ownerApplied": False, "publication": False, "publishAuthorized": False,
                "publicationComplete": False, "actionable": False}


def apply_editorial_return(package_root: Path | str, report_key: str, revision: int, editorial_version: str, *, applied_at: str | None = None) -> dict[str, Any]:
    root = Path(package_root).resolve()
    try:
        runtime, library, entry, _ = _governed_entry(root, report_key, revision)
        history = editorial_history(root, report_key, revision)
        matches = [item for item in history["versions"] if item.get("editorialVersion") == editorial_version]
        if len(matches) != 1 or matches[0].get("status") != "PENDING":
            raise QuarterlyEditorialReturnError("EDITORIAL_PENDING_VERSION_INVALID")
        snapshot_path = root / Path(matches[0]["snapshotLocator"])
        snapshot = _read_json(snapshot_path, "EDITORIAL_SNAPSHOT_INVALID")
        if snapshot.get("parentEditorialVersion") != history["currentEditorialVersion"]:
            raise QuarterlyEditorialReturnError("EDITORIAL_PARENT_VERSION_MISMATCH")
        candidate_path = root / Path(snapshot["candidateLocator"])
        if persistence._sha256(candidate_path.read_bytes()) != snapshot.get("returnedContentSha256"):
            raise QuarterlyEditorialReturnError("EDITORIAL_RETURNED_CONTENT_TAMPERED")
        returned = ReportCandidate.model_validate(_read_json(candidate_path, "EDITORIAL_RETURNED_CONTENT_INVALID"))
        source, _ = _active_candidate(root, entry)
        _validate_immutable_lineage(source, returned)
        analysis, charts, formulas = _analysis(root, returned, entry)
        editorial = _editorial_validation(returned, analysis, source)
        report_body = persistence._canonical_bytes(returned.model_dump(mode="json", by_alias=True))
        editorial_body = persistence._canonical_bytes(editorial)
        html_body = FormalPreviewRenderer().html(returned, charts, formulas)
        pdf_body = FormalPreviewRenderer().pdf(returned, charts, formulas)
        if not pdf_body.startswith(b"%PDF-"):
            raise QuarterlyEditorialReturnError("EDITORIAL_PDF_RENDER_INVALID")
        report_sha, editorial_sha = persistence._sha256(report_body), persistence._sha256(editorial_body)
        html_sha, pdf_sha = persistence._sha256(html_body), persistence._sha256(pdf_body)
        artifacts = []
        for item in entry["renderedArtifacts"]:
            body = html_body if item["format"] == "HTML" else pdf_body
            artifacts.append({**item, "sha256": persistence._sha256(body), "sizeBytes": len(body),
                              "sourceReportCandidateSha256": report_sha})
        stamp = _now(applied_at)
        content_sha = completion._governed_content_sha(str(entry["analysisCandidateSha256"]), report_sha,
                                                       editorial_sha, html_sha, entry["provenance"])
        runtime_next, library_next = copy.deepcopy(runtime), copy.deepcopy(library)
        history_next = copy.deepcopy(history)
        history_next.pop("initialized", None)
        history_next["currentEditorialVersion"] = editorial_version
        history_next["updatedAt"] = stamp
        snapshot.update({"ownerApplied": True, "status": "OWNER_APPLIED",
                         "appliedAt": stamp, "resultingHtmlSha256": html_sha,
                         "resultingPdfSha256": pdf_sha,
                         "resultingReportCandidateSha256": report_sha,
                         "resultingEditorialValidationSha256": editorial_sha,
                         "resultingGovernedContentSha256": content_sha})
        snapshot_body = persistence._canonical_bytes(snapshot)
        for item in history_next["versions"]:
            if item["editorialVersion"] == editorial_version:
                item.update({"ownerApplied": True, "status": "OWNER_APPLIED",
                             "snapshotSha256": persistence._sha256(snapshot_body)})
        history_body = persistence._canonical_bytes(history_next)
        history_sha = persistence._sha256(history_body)
        owner_path = root / Path(entry["ownerReviewLocator"])
        owner = _read_json(owner_path, "EDITORIAL_OWNER_REVIEW_INVALID")
        owner.update({"reportCandidateSha256": report_sha, "editorialValidationSha256": editorial_sha,
                      "renderedArtifacts": artifacts, "currentEditorialVersion": editorial_version,
                      "editorialHistoryLocator": _history_rel(report_key, revision).as_posix(),
                      "editorialHistorySha256": history_sha})
        owner.pop("persistenceSha256", None)
        owner["persistenceSha256"] = persistence._sha256(persistence._canonical_bytes(owner))
        owner_body = persistence._canonical_bytes(owner)
        for manifest in (runtime_next, library_next):
            selected = _entries(manifest, report_key, revision)
            if len(selected) != 1:
                raise QuarterlyEditorialReturnError("QUARTERLY_REPORT_REVISION_NOT_UNIQUE")
            updated = selected[0]
            updated.update({"reportCandidateSha256": report_sha,
                            "editorialValidationSha256": editorial_sha,
                            "governedContentSha256": content_sha,
                            "renderedArtifacts": artifacts,
                            "currentEditorialVersion": editorial_version,
                            "editorialHistoryLocator": _history_rel(report_key, revision).as_posix(),
                            "editorialHistorySha256": history_sha})
            replacements = {
                str(entry["reportCandidateLocator"]): report_sha,
                str(entry["editorialValidationLocator"]): editorial_sha,
                str(entry["ownerReviewLocator"]): persistence._sha256(owner_body),
                **{item["locator"]: item["sha256"] for item in artifacts},
            }
            for artifact in updated.get("pluginArtifacts", []):
                if artifact.get("path") in replacements:
                    artifact["sha256"] = replacements[artifact["path"]]
            updated["pluginArtifacts"] = [artifact for artifact in updated.get("pluginArtifacts", [])
                                            if artifact.get("kind") != "EDITORIAL_VERSION_LINEAGE"]
            updated["pluginArtifacts"].append({"path": _history_rel(report_key, revision).as_posix(),
                                                "sha256": history_sha,
                                                "kind": "EDITORIAL_VERSION_LINEAGE"})
            for version_item in history_next["versions"]:
                updated["pluginArtifacts"].append({"path": version_item["snapshotLocator"],
                                                    "sha256": version_item["snapshotSha256"],
                                                    "kind": "EDITORIAL_VERSION_LINEAGE"})
            slot = completion._latest_slot(report_key)
            pointer = manifest.get("latest", {}).get(slot)
            if isinstance(pointer, dict) and pointer.get("revision") == revision:
                manifest["latest"][slot] = copy.deepcopy(updated)
            manifest["generatedAt"] = stamp
        rolling_brief._validate_manifest_relationship(runtime_next, library_next)
        active_candidate = root / Path(entry["reportCandidateLocator"])
        active_editorial = root / Path(entry["editorialValidationLocator"])
        html_path = root / Path(next(item["locator"] for item in artifacts if item["format"] == "HTML"))
        pdf_path = root / Path(next(item["locator"] for item in artifacts if item["format"] == "PDF"))
        payloads = {
            active_candidate: report_body, active_editorial: editorial_body,
            html_path: html_body, pdf_path: pdf_body, owner_path: owner_body,
            snapshot_path: snapshot_body,
            root / _history_rel(report_key, revision): history_body,
            root / rolling_brief.RUNTIME_MANIFEST_REL: rolling_brief._canonical_json_bytes(runtime_next),
            root / rolling_brief.REPORT_MANIFEST_REL: rolling_brief._canonical_json_bytes(library_next),
        }
        persistence._atomic_transaction(payloads)
        completion._validate_history(root, runtime_next, library_next, report_key)
        checked = editorial_history(root, report_key, revision)
        if checked["currentEditorialVersion"] != editorial_version:
            raise QuarterlyEditorialReturnError("CURRENT_EDITORIAL_VERSION_INVALID")
        return {"status": "OWNER_REVIEW_REQUIRED", "report_key": report_key, "revision": revision,
                "currentEditorialVersion": editorial_version, "ownerApplied": True,
                "htmlSha256": html_sha, "pdfSha256": pdf_sha,
                "publication": False, "publishAuthorized": False,
                "publicationComplete": False, "actionable": False}
    except Exception as exc:
        return {"status": "FAIL_CLOSED", "reason": str(exc) or type(exc).__name__,
                "ownerApplied": False, "publication": False, "publishAuthorized": False,
                "publicationComplete": False, "actionable": False}
