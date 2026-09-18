#!/usr/bin/env python3
"""Non-publishing rendering and revision-specific Owner decisions for MAJOR_EVENT."""

from __future__ import annotations

import copy
import html
import io
import json
import re
from pathlib import Path
from typing import Any, Mapping

import warroom_major_event_baseline as baseline_registry
import warroom_major_event_report_persistence as persistence
import warroom_integrated_report_completion as report_completion
import warroom_rolling_brief as rolling_brief


class MajorEventOwnerWorkflowError(RuntimeError):
    """Rendered artifact or Owner decision lineage is invalid."""


DECISIONS = {"APPROVE", "REJECT", "REVISION_REQUIRED"}


def _failure(status: str, reason: str) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "rendered": False,
        "decisionPersisted": False,
        "published": False,
        "publicationComplete": False,
        "publishAuthorized": False,
        "actionable": False,
    }


def _manifest_pair(root: Path) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    runtime_path = root / rolling_brief.RUNTIME_MANIFEST_REL
    library_path = root / rolling_brief.REPORT_MANIFEST_REL
    health = rolling_brief.bootstrap_report_library(root)
    if health.get("status") != "REPORT_LIBRARY_EXISTING_HEALTHY":
        raise MajorEventOwnerWorkflowError(
            str(health.get("code") or "PERSISTED_REPORT_LIFECYCLE_REQUIRED")
        )
    return (
        runtime_path,
        library_path,
        persistence._read_json(runtime_path, "RUNTIME_LIFECYCLE_MANIFEST"),
        persistence._read_json(library_path, "PRIVATE_LIBRARY_MANIFEST"),
    )


def _entries(
    root: Path, runtime: Mapping[str, Any], library: Mapping[str, Any],
    report_key: str, revision: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    history = persistence._validate_existing_lineage(root, runtime, library, report_key)
    lifecycle = next((item for item in history if item.get("revision") == revision), None)
    private = next(
        (
            dict(item) for item in library["reports"]
            if isinstance(item, Mapping)
            and (item.get("report_key") or item.get("reportKey")) == report_key
            and item.get("revision") == revision
        ),
        None,
    )
    if lifecycle is None or private is None:
        raise MajorEventOwnerWorkflowError("REPORT_KEY_REVISION_NOT_PERSISTED")
    workflow_fields = (
        "renderingState", "renderedArtifacts", "ownerDecisionState",
        "ownerDecisionSha256", "publicationEligibility", "publication",
        "publicationComplete", "publishAuthorized", "actionable",
        "formalComposition", "formalCompositionSha256",
    )
    if any(lifecycle.get(field) != private.get(field) for field in workflow_fields):
        raise MajorEventOwnerWorkflowError("OWNER_WORKFLOW_MANIFEST_LINEAGE_MISMATCH")
    return dict(lifecycle), private


def _replace_entry(manifest: dict[str, Any], replacement: dict[str, Any]) -> None:
    identity = persistence._entry_identity(replacement)
    matches = [
        index for index, item in enumerate(manifest["reports"])
        if isinstance(item, Mapping) and persistence._entry_identity(item) == identity
    ]
    if len(matches) != 1:
        raise MajorEventOwnerWorkflowError("MANIFEST_ENTRY_IDENTITY_INVALID")
    manifest["reports"][matches[0]] = replacement
    slot = persistence._latest_slot(identity[0])
    latest = manifest.get("latest")
    if not isinstance(latest, dict) or not isinstance(latest.get(slot), Mapping):
        raise MajorEventOwnerWorkflowError("MAJOR_EVENT_LATEST_STATE_INVALID")
    if persistence._entry_identity(latest[slot]) == identity:
        latest[slot] = replacement


def _validate_baseline_provenance(code_root: Path, entry: Mapping[str, Any]) -> None:
    provenance = entry.get("baselineProvenance")
    if not isinstance(provenance, Mapping):
        raise MajorEventOwnerWorkflowError("BASELINE_PROVENANCE_MISSING")
    registry = baseline_registry.load_registry(code_root)
    if not (
        provenance.get("baseline_registry_id") == registry.get("recordType")
        and provenance.get("baseline_registry_version") == registry.get("registryVersion")
        and provenance.get("baseline_registry_sha256")
        == baseline_registry.APPROVED_REGISTRY_SHA256
        and provenance.get("canonical_event_id") == entry.get("canonicalEventId")
        and provenance.get("event_fingerprint") == entry.get("eventFingerprint")
    ):
        raise MajorEventOwnerWorkflowError("BASELINE_REGISTRY_EVENT_PROVENANCE_MISMATCH")
    source = baseline_registry._safe_reference(
        code_root,
        provenance.get("governed_source_reference"),
        baseline_registry.ALLOWED_SOURCE_PREFIX,
    )
    baseline_registry._verified_content(
        source.read_bytes(), str(provenance.get("baseline_content_sha256") or "")
    )
    contract = baseline_registry._safe_reference(
        code_root,
        provenance.get("analysis_contract_reference"),
        baseline_registry.ALLOWED_CONTRACT_PREFIX,
    )
    baseline_registry._verified_content(
        contract.read_bytes(), str(provenance.get("analysis_contract_sha256") or "")
    )


def _candidate_and_owner(
    root: Path, lifecycle: Mapping[str, Any], private: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    candidate_path = persistence._safe_persisted_locator(
        root, private.get("reportCandidateLocator"), persistence.LIBRARY_CANDIDATE_ROOT
    )
    owner_path = persistence._safe_persisted_locator(
        root, lifecycle.get("ownerReviewLocator"), persistence.OWNER_REVIEW_ROOT
    )
    candidate = persistence._read_json(candidate_path, "PERSISTED_REPORT_CANDIDATE")
    owner = persistence._read_json(owner_path, "PERSISTED_OWNER_REVIEW")
    if not (
        candidate.get("report_candidate_sha256") == lifecycle.get("reportCandidateSha256")
        and owner.get("persistence_sha256")
        == persistence._sha256(persistence._canonical_bytes({
            key: value for key, value in owner.items() if key != "persistence_sha256"
        }))
        and owner.get("report_key") == lifecycle.get("report_key")
        and owner.get("revision") == lifecycle.get("revision")
        and owner.get("canonical_event_id") == lifecycle.get("canonicalEventId")
        and owner.get("event_fingerprint") == lifecycle.get("eventFingerprint")
        and owner.get("report_candidate_sha256") == lifecycle.get("reportCandidateSha256")
        and owner.get("rendered_artifacts") == lifecycle.get("renderedArtifacts")
        and owner.get("formal_composition_sha256")
        == lifecycle.get("formalCompositionSha256")
    ):
        raise MajorEventOwnerWorkflowError("OWNER_CANDIDATE_LINEAGE_MISMATCH")
    decisions = owner.get("decisions", [])
    state = owner.get("decisionState", "PENDING")
    if state == "PENDING":
        if decisions != []:
            raise MajorEventOwnerWorkflowError("OWNER_DECISION_LINEAGE_INVALID")
    else:
        if state not in DECISIONS or not isinstance(decisions, list) or len(decisions) != 1:
            raise MajorEventOwnerWorkflowError("OWNER_DECISION_LINEAGE_INVALID")
        index = decisions[0]
        if not isinstance(index, Mapping):
            raise MajorEventOwnerWorkflowError("OWNER_DECISION_LINEAGE_INVALID")
        decision_path = persistence._safe_persisted_locator(
            root, index.get("locator"), persistence.OWNER_REVIEW_ROOT
        )
        decision = persistence._read_json(decision_path, "OWNER_DECISION")
        unhashed = {
            key: value for key, value in decision.items() if key != "decision_sha256"
        }
        if not (
            decision.get("decision_sha256") == persistence._sha256(
                persistence._canonical_bytes(unhashed)
            )
            and decision.get("decision_sha256") == index.get("sha256")
            and decision.get("decision_id") == index.get("decision_id")
            and decision.get("decision") == state == index.get("decision")
            and decision.get("report_key") == lifecycle.get("report_key")
            and decision.get("revision") == lifecycle.get("revision")
            and decision.get("canonical_event_id") == lifecycle.get("canonicalEventId")
            and decision.get("event_fingerprint") == lifecycle.get("eventFingerprint")
            and decision.get("analysis_candidate_sha256") == lifecycle.get("analysisCandidateSha256")
            and decision.get("report_candidate_sha256") == lifecycle.get("reportCandidateSha256")
            and decision.get("baseline_provenance") == lifecycle.get("baselineProvenance")
            and decision.get("formal_composition_sha256")
            == lifecycle.get("formalCompositionSha256")
            and decision.get("rendered_artifacts") == lifecycle.get("renderedArtifacts")
            and decision.get("publication") is False
            and decision.get("publicationComplete") is False
            and decision.get("publishAuthorized") is False
            and decision.get("actionable") is False
        ):
            raise MajorEventOwnerWorkflowError("OWNER_DECISION_LINEAGE_INVALID")
    return candidate, owner, owner_path


def _artifact_root(root: Path, report_key: str, revision: int) -> tuple[Path, Path]:
    token = re.sub(r"[^A-Z0-9_-]+", "_", report_key.upper())
    base = root / persistence.LIBRARY_CANDIDATE_ROOT / token / f"r{revision}" / "rendered"
    return base / "owner_review.html", base / "owner_review.pdf"


def _html_bytes(entry: Mapping[str, Any], composition: Mapping[str, Any]) -> bytes:
    provenance = entry["baselineProvenance"]
    rows = [
        ("Report key", entry["report_key"]),
        ("Revision", entry["revision"]),
        ("Canonical event", entry["canonicalEventId"]),
        ("Event fingerprint", entry["eventFingerprint"]),
        ("Analysis candidate SHA-256", entry["analysisCandidateSha256"]),
        ("Report candidate SHA-256", entry["reportCandidateSha256"]),
        ("Baseline", f"{provenance['baseline_id']} v{provenance['baseline_version']}"),
        ("Baseline content SHA-256", provenance["baseline_content_sha256"]),
        ("Registry", f"{provenance['baseline_registry_id']} v{provenance['baseline_registry_version']}"),
        ("Registry SHA-256", provenance["baseline_registry_sha256"]),
        ("Analysis contract", provenance["analysis_contract_reference"]),
        ("Contract SHA-256", provenance["analysis_contract_sha256"]),
        ("Authority candidate", composition["authorityContext"]["candidateId"]),
        ("Authority manifest SHA-256", composition["authorityContext"]["candidateManifestSha256"]),
        ("Authority context SHA-256", composition["authorityContext"]["contextSha256"]),
        ("Formal composition SHA-256", composition["compositionSha256"]),
    ]
    table = "".join(
        f"<tr><th>{html.escape(str(label))}</th><td>{html.escape(str(value))}</td></tr>"
        for label, value in rows
    )
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>P1008 MAJOR_EVENT Owner Review</title>
<style>body{{font-family:Arial,sans-serif;background:#07111f;color:#e8f3ff;margin:0}}
main{{max-width:980px;margin:32px auto;padding:28px;background:#0f1b2c;border:1px solid #274761;border-radius:12px}}
h1{{color:#67e8f9}} .badge{{display:inline-block;padding:6px 10px;background:#713f12;color:#fef3c7;border-radius:999px}}
table{{width:100%;border-collapse:collapse;margin-top:20px}}th,td{{padding:10px;border-bottom:1px solid #274761;text-align:left;vertical-align:top}}
th{{width:230px;color:#bae6fd}}td{{word-break:break-all}}footer{{margin-top:24px;color:#94a3b8}}</style></head>
<body><main><div class="badge">OWNER_REVIEW_REQUIRED - NON-PUBLISHED</div>
<h1>P1008 MAJOR_EVENT Report Candidate</h1><p>This governed rendering composes the validated authority, evidence, analysis baseline, and report lineage. It is private review material, not publication.</p>
<table>{table}</table><footer>actionable=false | publishAuthorized=false | publicationComplete=false</footer>
</main></body></html>\n"""
    return body.encode("utf-8")


def _pdf_bytes(entry: Mapping[str, Any], composition: Mapping[str, Any]) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:
        raise MajorEventOwnerWorkflowError("PDF_RENDER_DEPENDENCY_MISSING") from exc
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm, title="P1008 MAJOR_EVENT Owner Review",
        author="P1008 Integrated War Room", invariant=1,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("P1008Title", parent=styles["Title"], textColor=colors.HexColor("#075985"), fontSize=18, leading=22)
    body = ParagraphStyle("P1008Body", parent=styles["BodyText"], fontSize=8.5, leading=11)
    label = ParagraphStyle("P1008Label", parent=body, textColor=colors.HexColor("#0c4a6e"))
    provenance = entry["baselineProvenance"]
    data = [
        [Paragraph("Governed field", label), Paragraph("Bound value", label)],
        [Paragraph("Report key / revision", label), Paragraph(f"{entry['report_key']} / {entry['revision']}", body)],
        [Paragraph("Canonical event", label), Paragraph(str(entry["canonicalEventId"]), body)],
        [Paragraph("Event fingerprint", label), Paragraph(str(entry["eventFingerprint"]), body)],
        [Paragraph("Analysis candidate SHA-256", label), Paragraph(str(entry["analysisCandidateSha256"]), body)],
        [Paragraph("Report candidate SHA-256", label), Paragraph(str(entry["reportCandidateSha256"]), body)],
        [Paragraph("Baseline identity / version", label), Paragraph(f"{provenance['baseline_id']} / {provenance['baseline_version']}", body)],
        [Paragraph("Baseline content SHA-256", label), Paragraph(str(provenance["baseline_content_sha256"]), body)],
        [Paragraph("Registry identity / version", label), Paragraph(f"{provenance['baseline_registry_id']} / {provenance['baseline_registry_version']}", body)],
        [Paragraph("Registry SHA-256", label), Paragraph(str(provenance["baseline_registry_sha256"]), body)],
        [Paragraph("Analysis contract", label), Paragraph(str(provenance["analysis_contract_reference"]), body)],
        [Paragraph("Contract SHA-256", label), Paragraph(str(provenance["analysis_contract_sha256"]), body)],
        [Paragraph("Authority candidate", label), Paragraph(str(composition["authorityContext"]["candidateId"]), body)],
        [Paragraph("Authority manifest SHA-256", label), Paragraph(str(composition["authorityContext"]["candidateManifestSha256"]), body)],
        [Paragraph("Authority context SHA-256", label), Paragraph(str(composition["authorityContext"]["contextSha256"]), body)],
        [Paragraph("Formal composition SHA-256", label), Paragraph(str(composition["compositionSha256"]), body)],
    ]
    table = Table(data, colWidths=[52 * mm, 118 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0f2fe")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#7dd3fc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story = [
        Paragraph("P1008 MAJOR_EVENT Owner Review", title), Spacer(1, 5 * mm),
        Paragraph("OWNER_REVIEW_REQUIRED - PRIVATE - NON-PUBLISHED", styles["Heading3"]),
        Paragraph("This rendering preserves the validated authority, evidence, event, analysis baseline, registry, contract, and candidate hashes. Rendering does not authorize or complete publication.", styles["BodyText"]),
        Spacer(1, 5 * mm), table, Spacer(1, 5 * mm),
        Paragraph("actionable=false | publishAuthorized=false | publicationComplete=false", styles["BodyText"]),
    ]
    document.build(story)
    payload = buffer.getvalue()
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(payload))
        if len(reader.pages) < 1:
            raise MajorEventOwnerWorkflowError("PDF_RENDER_EMPTY")
    except (ImportError, Exception) as exc:
        if isinstance(exc, MajorEventOwnerWorkflowError):
            raise
        raise MajorEventOwnerWorkflowError("PDF_RENDER_INVALID") from exc
    return payload


def _artifacts(root: Path, html_path: Path, pdf_path: Path) -> list[dict[str, Any]]:
    values = []
    for kind, path in (("HTML", html_path), ("PDF", pdf_path)):
        if not path.is_file():
            raise MajorEventOwnerWorkflowError(f"RENDERED_{kind}_MISSING")
        relative = path.relative_to(root).as_posix()
        values.append({
            "format": kind, "locator": relative,
            "sha256": persistence._sha256(path.read_bytes()),
            "sizeBytes": path.stat().st_size,
        })
    return values


def _validate_rendered(
    root: Path, lifecycle: Mapping[str, Any], private: Mapping[str, Any]
) -> list[dict[str, Any]]:
    left = lifecycle.get("renderedArtifacts")
    right = private.get("renderedArtifacts")
    if not isinstance(left, list) or left != right or {item.get("format") for item in left if isinstance(item, Mapping)} != {"HTML", "PDF"}:
        raise MajorEventOwnerWorkflowError("RENDERED_ARTIFACT_LINEAGE_INVALID")
    for item in left:
        path = persistence._safe_persisted_locator(
            root, item.get("locator"), persistence.LIBRARY_CANDIDATE_ROOT
        )
        if not path.is_file() or not (
            persistence._sha256(path.read_bytes()) == item.get("sha256")
            and path.stat().st_size == item.get("sizeBytes")
        ):
            raise MajorEventOwnerWorkflowError("RENDERED_ARTIFACT_HASH_MISMATCH")
    return [dict(item) for item in left]


def render_major_event_revision(
    package_root: Path | str, code_root: Path | str, *, report_key: str, revision: int
) -> dict[str, Any]:
    root = Path(package_root).resolve()
    code = Path(code_root).resolve()
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        return _failure("FAIL_CLOSED", "EXPLICIT_POSITIVE_REVISION_REQUIRED")
    try:
        runtime_path, library_path, runtime, library = _manifest_pair(root)
        lifecycle, private = _entries(root, runtime, library, report_key, revision)
        if lifecycle.get("eventType") != "MAJOR_EVENT":
            raise MajorEventOwnerWorkflowError("MAJOR_EVENT_REVISION_REQUIRED")
        _validate_baseline_provenance(code, lifecycle)
        _, owner, owner_path = _candidate_and_owner(root, lifecycle, private)
        if lifecycle.get("renderedArtifacts") is not None or private.get("renderedArtifacts") is not None:
            composition = lifecycle.get("formalComposition")
            if not isinstance(composition, Mapping) or not (
                composition == private.get("formalComposition")
                and composition.get("compositionSha256")
                == lifecycle.get("formalCompositionSha256")
            ):
                raise MajorEventOwnerWorkflowError("FORMAL_COMPOSITION_LINEAGE_MISSING")
            report_completion.validate_composition(code, lifecycle, composition)
            artifacts = _validate_rendered(root, lifecycle, private)
            return {
                "status": "IDEMPOTENT_RENDER_REPLAY", "report_key": report_key,
                "revision": revision, "artifacts": artifacts,
                "ownerReviewPersistenceSha256": owner["persistence_sha256"],
                "rendered": False, "published": False, "publicationComplete": False,
                "publishAuthorized": False, "actionable": False,
            }
        if owner.get("decisionState", "PENDING") != "PENDING":
            raise MajorEventOwnerWorkflowError("OWNER_DECISION_PRECEDES_RENDERING")
        composition = report_completion.build_major_event_composition(code, lifecycle)
        html_path, pdf_path = _artifact_root(root, report_key, revision)
        if html_path.exists() or pdf_path.exists():
            raise MajorEventOwnerWorkflowError("UNREGISTERED_RENDERED_ARTIFACT_COLLISION")
        html_payload = _html_bytes(lifecycle, composition)
        pdf_payload = _pdf_bytes(lifecycle, composition)
        artifact_values = [
            {"format": "HTML", "locator": html_path.relative_to(root).as_posix(), "sha256": persistence._sha256(html_payload), "sizeBytes": len(html_payload)},
            {"format": "PDF", "locator": pdf_path.relative_to(root).as_posix(), "sha256": persistence._sha256(pdf_payload), "sizeBytes": len(pdf_payload)},
        ]
        lifecycle_next = {
            **lifecycle, "renderingState": "OWNER_REVIEW_REQUIRED",
            "renderedArtifacts": artifact_values, "formalComposition": composition,
            "formalCompositionSha256": composition["compositionSha256"],
        }
        private_next = {
            **private, "renderingState": "OWNER_REVIEW_REQUIRED",
            "renderedArtifacts": artifact_values, "formalComposition": composition,
            "formalCompositionSha256": composition["compositionSha256"],
        }
        owner_unhashed = {
            **{key: value for key, value in owner.items() if key != "persistence_sha256"},
            "analysis_candidate_sha256": lifecycle["analysisCandidateSha256"],
            "baseline_provenance": lifecycle["baselineProvenance"],
            "rendered_artifacts": artifact_values,
            "formal_composition_sha256": composition["compositionSha256"],
            "decisionState": "PENDING",
            "decisions": [],
            "publicationEligibility": False,
            "publicationComplete": False,
            "publication": False,
            "publishAuthorized": False,
            "actionable": False,
        }
        owner_next = persistence._with_hash(owner_unhashed, "persistence_sha256")
        runtime_next, library_next = copy.deepcopy(runtime), copy.deepcopy(library)
        _replace_entry(runtime_next, lifecycle_next)
        _replace_entry(library_next, private_next)
        rolling_brief._validate_manifest_relationship(runtime_next, library_next)
        persistence._atomic_transaction({
            html_path: html_payload, pdf_path: pdf_payload,
            owner_path: persistence._canonical_bytes(owner_next),
            runtime_path: rolling_brief._canonical_json_bytes(runtime_next),
            library_path: rolling_brief._canonical_json_bytes(library_next),
        })
        _validate_rendered(root, lifecycle_next, private_next)
        return {
            "status": "OWNER_REVIEW_REQUIRED", "report_key": report_key,
            "revision": revision, "canonicalEventId": lifecycle["canonicalEventId"],
            "eventFingerprint": lifecycle["eventFingerprint"],
            "analysisCandidateSha256": lifecycle["analysisCandidateSha256"],
            "reportCandidateSha256": lifecycle["reportCandidateSha256"],
            "baselineProvenance": lifecycle["baselineProvenance"],
            "formalCompositionSha256": composition["compositionSha256"],
            "artifacts": artifact_values,
            "ownerReviewPersistenceSha256": owner_next["persistence_sha256"],
            "rendered": True, "published": False, "publicationComplete": False,
            "publishAuthorized": False, "actionable": False,
        }
    except (
        MajorEventOwnerWorkflowError, persistence.MajorEventPersistenceError,
        baseline_registry.MajorEventBaselineError,
        report_completion.IntegratedReportCompletionError, OSError, ValueError,
    ) as exc:
        return _failure("FAIL_CLOSED", str(exc) or type(exc).__name__)


def record_owner_decision(
    package_root: Path | str,
    code_root: Path | str,
    *,
    report_key: str,
    revision: int,
    decision: str,
    decision_id: str,
    decided_by: str,
    decided_at_utc: str,
    expected_report_candidate_sha256: str,
    expected_owner_review_persistence_sha256: str,
    expected_rendered_artifact_hashes: list[str],
) -> dict[str, Any]:
    root = Path(package_root).resolve()
    code = Path(code_root).resolve()
    normalized = str(decision).upper()
    if normalized not in DECISIONS:
        return _failure("FAIL_CLOSED", "OWNER_DECISION_INVALID")
    try:
        runtime_path, library_path, runtime, library = _manifest_pair(root)
        lifecycle, private = _entries(root, runtime, library, report_key, revision)
        _validate_baseline_provenance(code, lifecycle)
        artifacts = _validate_rendered(root, lifecycle, private)
        composition = lifecycle.get("formalComposition")
        if not isinstance(composition, Mapping) or not (
            composition == private.get("formalComposition")
            and composition.get("compositionSha256")
            == lifecycle.get("formalCompositionSha256")
        ):
            raise MajorEventOwnerWorkflowError("FORMAL_COMPOSITION_LINEAGE_MISSING")
        report_completion.validate_composition(code, lifecycle, composition)
        _, owner, owner_path = _candidate_and_owner(root, lifecycle, private)
        if not (
            lifecycle.get("reportCandidateSha256") == expected_report_candidate_sha256
            and owner.get("persistence_sha256") == expected_owner_review_persistence_sha256
            and [item["sha256"] for item in artifacts] == expected_rendered_artifact_hashes
        ):
            raise MajorEventOwnerWorkflowError("STALE_OWNER_DECISION_CONTEXT")
        if owner.get("decisionState") != "PENDING" or owner.get("decisions") != []:
            return _failure("REVIEW_REQUIRED", "OWNER_DECISION_ALREADY_RECORDED")
        if not (
            re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,127}", decision_id)
            and str(decided_by).strip()
            and str(decided_at_utc).endswith("Z")
        ):
            raise MajorEventOwnerWorkflowError("OWNER_DECISION_IDENTITY_INCOMPLETE")
        decision_rel = Path(str(lifecycle["ownerReviewLocator"])).parent / "decisions" / f"{decision_id}.json"
        decision_path = persistence._safe_persisted_locator(
            root, decision_rel.as_posix(), persistence.OWNER_REVIEW_ROOT
        )
        if decision_path.exists():
            raise MajorEventOwnerWorkflowError("OWNER_DECISION_ID_COLLISION")
        eligible = normalized == "APPROVE"
        decision_record = persistence._with_hash({
            "record_type": "P1008_MAJOR_EVENT_OWNER_DECISION_V1",
            "schema_version": "1.0", "decision_id": decision_id,
            "decision": normalized, "decided_by": decided_by,
            "decided_at_utc": decided_at_utc, "report_key": report_key,
            "revision": revision, "canonical_event_id": lifecycle["canonicalEventId"],
            "event_fingerprint": lifecycle["eventFingerprint"],
            "analysis_candidate_sha256": lifecycle["analysisCandidateSha256"],
            "report_candidate_sha256": lifecycle["reportCandidateSha256"],
            "baseline_provenance": lifecycle["baselineProvenance"],
            "formal_composition_sha256": lifecycle["formalCompositionSha256"],
            "rendered_artifacts": artifacts,
            "publicationEligibility": eligible, "publication": False,
            "publicationComplete": False, "publishAuthorized": False,
            "actionable": False,
        }, "decision_sha256")
        status = "APPROVED" if eligible else normalized
        owner_unhashed = {
            **{key: value for key, value in owner.items() if key != "persistence_sha256"},
            "status": status, "decisionState": normalized,
            "decisions": [{
                "decision_id": decision_id, "decision": normalized,
                "locator": decision_rel.as_posix(),
                "sha256": decision_record["decision_sha256"],
            }],
            "ownerApproved": eligible, "publicationEligibility": eligible,
            "publication": False, "publicationComplete": False,
            "publishAuthorized": False, "actionable": False,
        }
        owner_next = persistence._with_hash(owner_unhashed, "persistence_sha256")
        lifecycle_next = {
            **lifecycle, "ownerDecisionState": normalized,
            "ownerDecisionSha256": decision_record["decision_sha256"],
            "publicationEligibility": eligible, "publication": False,
            "publicationComplete": False, "publishAuthorized": False,
            "actionable": False,
        }
        private_next = {
            **private, "ownerDecisionState": normalized,
            "ownerDecisionSha256": decision_record["decision_sha256"],
            "publicationEligibility": eligible, "publication": False,
            "publicationComplete": False, "publishAuthorized": False,
            "actionable": False,
        }
        runtime_next, library_next = copy.deepcopy(runtime), copy.deepcopy(library)
        _replace_entry(runtime_next, lifecycle_next)
        _replace_entry(library_next, private_next)
        persistence._atomic_transaction({
            decision_path: persistence._canonical_bytes(decision_record),
            owner_path: persistence._canonical_bytes(owner_next),
            runtime_path: rolling_brief._canonical_json_bytes(runtime_next),
            library_path: rolling_brief._canonical_json_bytes(library_next),
        })
        return {
            "status": status, "decision": normalized, "decision_id": decision_id,
            "decisionSha256": decision_record["decision_sha256"],
            "report_key": report_key, "revision": revision,
            "publicationEligibility": eligible, "decisionPersisted": True,
            "published": False, "publicationComplete": False,
            "publishAuthorized": False, "actionable": False,
        }
    except (
        MajorEventOwnerWorkflowError, persistence.MajorEventPersistenceError,
        baseline_registry.MajorEventBaselineError,
        report_completion.IntegratedReportCompletionError, OSError, ValueError,
    ) as exc:
        return _failure("FAIL_CLOSED", str(exc) or type(exc).__name__)
