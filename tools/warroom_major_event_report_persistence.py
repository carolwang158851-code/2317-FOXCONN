#!/usr/bin/env python3
"""Governed persistence for validated MAJOR_EVENT provenance candidates only."""

from __future__ import annotations

import copy
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import warroom_major_event_materialization as materialization
import warroom_rolling_brief as rolling_brief


class MajorEventPersistenceError(RuntimeError):
    """Persistence lineage is stale, inconsistent, or tampered."""


OWNER_REVIEW_ROOT = Path("runtime/report_production/major_event_owner_reviews")
LIBRARY_CANDIDATE_ROOT = Path("reports/private_candidates/major_event")


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return materialization._sha256(value)


def _with_hash(payload: dict[str, Any], field: str) -> dict[str, Any]:
    return {**payload, field: _sha256(_canonical_bytes(payload))}


def stable_report_key(canonical_event_id: str) -> str:
    token = re.sub(r"[^A-Z0-9_-]+", "_", canonical_event_id.upper()).strip("_")
    if not token:
        raise MajorEventPersistenceError("CANONICAL_EVENT_ID_INVALID")
    return f"P1008_MAJOR_EVENT__{token}"


def _latest_slot(report_key: str) -> str:
    return f"major_event:{report_key}"


def _failure(status: str, reason: str) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "persisted": False,
        "published": False,
        "publishAuthorized": False,
        "actionable": False,
    }


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MajorEventPersistenceError(f"{label}_INVALID") from exc
    if not isinstance(value, dict):
        raise MajorEventPersistenceError(f"{label}_INVALID")
    return value


def _validate_materialized(
    code_root: Path,
    receipt: Mapping[str, Any],
    result: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not (
        receipt.get("event_type") == "MAJOR_EVENT"
        and receipt.get("report_trigger_valid") is True
        and receipt.get("actionable") is False
        and result.get("status") == "OWNER_REVIEW_REQUIRED"
        and result.get("formal_report_generated") is False
        and result.get("publication") is False
        and result.get("publishAuthorized") is False
        and result.get("actionable") is False
    ):
        raise MajorEventPersistenceError("VALIDATED_BOUND_MAJOR_EVENT_REQUIRED")
    binding = receipt.get("analysis_baseline_binding")
    analysis = result.get("analysis_candidate")
    report = result.get("report_candidate")
    owner = result.get("owner_review")
    if not all(isinstance(value, Mapping) for value in (binding, analysis, report, owner)):
        raise MajorEventPersistenceError("MATERIALIZATION_ENVELOPES_REQUIRED")
    validated_analysis = materialization.validate_analysis_candidate(
        code_root, analysis, binding, receipt
    )
    validated_report = materialization.validate_report_candidate(
        code_root, report, validated_analysis, binding, receipt
    )
    validated_owner = materialization.validate_owner_review(
        code_root, owner, validated_report, validated_analysis, binding, receipt
    )
    if not (
        validated_analysis.get("trigger_receipt_sha256") == receipt.get("canonical_sha256")
        and validated_analysis.get("evidence_trigger_decision_id") == receipt.get("decision_id")
        and validated_report.get("analysis_candidate_sha256")
        == validated_analysis.get("analysis_candidate_sha256")
        and validated_owner.get("report_candidate_sha256")
        == validated_report.get("report_candidate_sha256")
    ):
        raise MajorEventPersistenceError("MATERIALIZATION_TRIGGER_LINEAGE_MISMATCH")
    provenance = dict(validated_analysis["baseline_provenance"])
    if not (
        provenance == validated_report.get("baseline_provenance")
        and provenance == validated_owner.get("baseline_provenance")
        and provenance.get("canonical_event_id") == receipt.get("canonical_event_id")
        and provenance.get("event_fingerprint") == receipt.get("event_fingerprint")
    ):
        raise MajorEventPersistenceError("MATERIALIZATION_PROVENANCE_MISMATCH")
    return validated_analysis, validated_report, validated_owner, provenance


def _major_entries(manifest: Mapping[str, Any], report_key: str) -> list[dict[str, Any]]:
    reports = manifest.get("reports")
    if not isinstance(reports, list):
        raise MajorEventPersistenceError("REPORT_MANIFEST_REPORTS_INVALID")
    return [
        dict(item) for item in reports
        if isinstance(item, Mapping)
        and item.get("eventType") == "MAJOR_EVENT"
        and (item.get("report_key") or item.get("reportKey")) == report_key
    ]


def _entry_identity(entry: Mapping[str, Any]) -> tuple[str, int]:
    try:
        revision = int(entry.get("revision"))
    except (TypeError, ValueError) as exc:
        raise MajorEventPersistenceError("MAJOR_EVENT_REVISION_INVALID") from exc
    if revision < 1:
        raise MajorEventPersistenceError("MAJOR_EVENT_REVISION_INVALID")
    return str(entry.get("report_key") or entry.get("reportKey") or ""), revision


def _safe_persisted_locator(root: Path, locator: Any, prefix: Path) -> Path:
    relative = Path(str(locator or ""))
    if relative.is_absolute() or not relative.parts:
        raise MajorEventPersistenceError("PERSISTED_ARTIFACT_LOCATOR_INVALID")
    expected_root = (root / prefix).resolve()
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(expected_root):
        raise MajorEventPersistenceError("PERSISTED_ARTIFACT_LOCATOR_INVALID")
    return resolved


def _validate_existing_lineage(
    root: Path,
    runtime: Mapping[str, Any],
    library: Mapping[str, Any],
    report_key: str,
) -> list[dict[str, Any]]:
    runtime_entries = _major_entries(runtime, report_key)
    library_entries = _major_entries(library, report_key)
    runtime_by_revision = {_entry_identity(item)[1]: item for item in runtime_entries}
    library_by_revision = {_entry_identity(item)[1]: item for item in library_entries}
    if len(runtime_by_revision) != len(runtime_entries) or len(library_by_revision) != len(library_entries):
        raise MajorEventPersistenceError("MAJOR_EVENT_DUPLICATE_REVISION")
    if set(runtime_by_revision) != set(library_by_revision):
        raise MajorEventPersistenceError("MAJOR_EVENT_LIFECYCLE_LIBRARY_DIVERGED")
    lineage_fields = (
        "report_key", "revision", "canonicalEventId", "eventFingerprint",
        "analysisCandidateSha256", "reportCandidateSha256", "ownerReviewSha256",
        "governedContentSha256", "previousRevision",
        "previousGovernedContentSha256", "baselineProvenance",
    )
    for revision in sorted(runtime_by_revision):
        lifecycle = runtime_by_revision[revision]
        private = library_by_revision[revision]
        if any(lifecycle.get(field) != private.get(field) for field in lineage_fields):
            raise MajorEventPersistenceError("MAJOR_EVENT_LIFECYCLE_LIBRARY_LINEAGE_MISMATCH")
        expected_content_sha = _sha256(_canonical_bytes({
            "analysisCandidateSha256": lifecycle.get("analysisCandidateSha256"),
            "reportCandidateSha256": lifecycle.get("reportCandidateSha256"),
            "ownerReviewSha256": lifecycle.get("ownerReviewSha256"),
            "baselineProvenance": lifecycle.get("baselineProvenance"),
        }))
        if lifecycle.get("governedContentSha256") != expected_content_sha:
            raise MajorEventPersistenceError("GOVERNED_CONTENT_HASH_INVALID")
        if revision == 1:
            if lifecycle.get("previousRevision") is not None or lifecycle.get(
                "previousGovernedContentSha256"
            ) is not None:
                raise MajorEventPersistenceError("MAJOR_EVENT_PREVIOUS_LINEAGE_INVALID")
        else:
            previous = runtime_by_revision.get(revision - 1)
            if previous is None or not (
                lifecycle.get("previousRevision") == revision - 1
                and lifecycle.get("previousGovernedContentSha256")
                == previous.get("governedContentSha256")
            ):
                raise MajorEventPersistenceError("MAJOR_EVENT_PREVIOUS_LINEAGE_INVALID")
        candidate_path = _safe_persisted_locator(
            root, private.get("reportCandidateLocator"), LIBRARY_CANDIDATE_ROOT
        )
        owner_path = _safe_persisted_locator(
            root, lifecycle.get("ownerReviewLocator"), OWNER_REVIEW_ROOT
        )
        candidate = _read_json(candidate_path, "PERSISTED_REPORT_CANDIDATE")
        owner = _read_json(owner_path, "PERSISTED_OWNER_REVIEW")
        try:
            materialization._validate_hash(
                candidate, "report_candidate_sha256", "PERSISTED_REPORT_CANDIDATE"
            )
        except materialization.MajorEventMaterializationError as exc:
            raise MajorEventPersistenceError(str(exc)) from exc
        if candidate.get("report_candidate_sha256") != lifecycle.get("reportCandidateSha256"):
            raise MajorEventPersistenceError("PERSISTED_REPORT_CANDIDATE_HASH_MISMATCH")
        supplied_owner_hash = owner.get("persistence_sha256")
        owner_unhashed = {
            key: value for key, value in owner.items() if key != "persistence_sha256"
        }
        if not (
            supplied_owner_hash == _sha256(_canonical_bytes(owner_unhashed))
            and owner.get("owner_review_sha256") == lifecycle.get("ownerReviewSha256")
            and isinstance(owner.get("owner_review_envelope"), Mapping)
            and owner["owner_review_envelope"].get("owner_review_sha256")
            == owner.get("owner_review_sha256")
            and owner.get("status") == "OWNER_REVIEW_REQUIRED"
            and owner.get("actionable") is False
            and owner.get("publishAuthorized") is False
            and owner.get("ownerApproved") is False
        ):
            raise MajorEventPersistenceError("PERSISTED_OWNER_REVIEW_LINEAGE_INVALID")
    if runtime_entries:
        latest_revision = max(runtime_by_revision)
        for manifest, label in ((runtime, "LIFECYCLE"), (library, "LIBRARY")):
            latest = manifest.get("latest")
            if not isinstance(latest, Mapping):
                raise MajorEventPersistenceError(f"MAJOR_EVENT_{label}_LATEST_INVALID")
            pointer = latest.get(_latest_slot(report_key))
            if not isinstance(pointer, Mapping) or _entry_identity(pointer) != (
                report_key, latest_revision
            ):
                raise MajorEventPersistenceError(f"MAJOR_EVENT_{label}_LATEST_STALE")
    return [runtime_by_revision[key] for key in sorted(runtime_by_revision)]


def _governed_content_sha(
    analysis: Mapping[str, Any], report: Mapping[str, Any], owner: Mapping[str, Any]
) -> str:
    return _sha256(_canonical_bytes({
        "analysisCandidateSha256": analysis["analysis_candidate_sha256"],
        "reportCandidateSha256": report["report_candidate_sha256"],
        "ownerReviewSha256": owner["owner_review_sha256"],
        "baselineProvenance": analysis["baseline_provenance"],
    }))


def _atomic_transaction(payloads: Mapping[Path, bytes]) -> None:
    originals = {path: path.read_bytes() if path.exists() else None for path in payloads}
    temporary: dict[Path, Path] = {}
    try:
        for path, payload in payloads.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            with temp.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            temporary[path] = temp
        for path, temp in temporary.items():
            os.replace(temp, path)
    except OSError as exc:
        for path, original in originals.items():
            try:
                if original is None:
                    if path.exists():
                        path.unlink()
                else:
                    path.write_bytes(original)
            except OSError:
                pass
        raise MajorEventPersistenceError("PERSISTENCE_TRANSACTION_FAILED") from exc
    finally:
        for temp in temporary.values():
            if temp.exists():
                temp.unlink()


def persist_major_event_report_candidate(
    package_root: Path | str,
    code_root: Path | str,
    receipt: Mapping[str, Any],
    materialized: Mapping[str, Any],
    *,
    revision: int,
    persisted_at_utc: str | None = None,
) -> dict[str, Any]:
    """Persist one validated candidate without rendering or publication."""

    root = Path(package_root).resolve()
    code = Path(code_root).resolve()
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        return _failure("FAIL_CLOSED", "EXPLICIT_POSITIVE_REVISION_REQUIRED")
    try:
        analysis, report, owner, provenance = _validate_materialized(
            code, receipt, materialized
        )
        report_key = stable_report_key(str(receipt.get("canonical_event_id") or ""))
        health = rolling_brief.bootstrap_report_library(root)
        if health.get("status") not in {
            "REPORT_LIBRARY_BOOTSTRAPPED_EMPTY", "REPORT_LIBRARY_EXISTING_HEALTHY",
        }:
            return _failure("FAIL_CLOSED", str(health.get("code") or health.get("status")))
        runtime_path = root / rolling_brief.RUNTIME_MANIFEST_REL
        library_path = root / rolling_brief.REPORT_MANIFEST_REL
        runtime = _read_json(runtime_path, "RUNTIME_LIFECYCLE_MANIFEST")
        library = _read_json(library_path, "PRIVATE_LIBRARY_MANIFEST")
        history = _validate_existing_lineage(root, runtime, library, report_key)
        content_sha = _governed_content_sha(analysis, report, owner)
        same = [item for item in history if item.get("governedContentSha256") == content_sha]
        if same:
            existing = same[0]
            return {
                "status": "IDEMPOTENT_REPLAY",
                "reason": "GOVERNED_CONTENT_ALREADY_PERSISTED",
                "report_key": report_key,
                "revision": existing["revision"],
                "governedContentSha256": content_sha,
                "persisted": False,
                "duplicateRevisionCreated": False,
                "published": False,
                "publishAuthorized": False,
                "actionable": False,
            }
        expected_revision = len(history) + 1
        if revision != expected_revision:
            return _failure("REVIEW_REQUIRED", "EXPLICIT_REVISION_SEQUENCE_MISMATCH")
        previous = history[-1] if history else None
        stamp = persisted_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        file_key = re.sub(r"[^A-Z0-9_-]+", "_", report_key)
        candidate_rel = LIBRARY_CANDIDATE_ROOT / file_key / f"r{revision}" / "report_candidate.json"
        owner_rel = OWNER_REVIEW_ROOT / file_key / f"r{revision}" / "owner_review.json"
        candidate_path = root / candidate_rel
        owner_path = root / owner_rel
        if candidate_path.exists() or owner_path.exists():
            raise MajorEventPersistenceError("REVISION_ARTIFACT_COLLISION")
        owner_record = _with_hash({
            "record_type": "P1008_MAJOR_EVENT_OWNER_REVIEW_PERSISTENCE_V1",
            "schema_version": "1.0",
            "report_key": report_key,
            "revision": revision,
            "canonical_event_id": receipt["canonical_event_id"],
            "event_fingerprint": receipt["event_fingerprint"],
            "report_candidate_sha256": report["report_candidate_sha256"],
            "owner_review_sha256": owner["owner_review_sha256"],
            "owner_review_envelope": owner,
            "status": "OWNER_REVIEW_REQUIRED",
            "ownerApproved": False,
            "publication": False,
            "publishAuthorized": False,
            "actionable": False,
        }, "persistence_sha256")
        shared = {
            "id": f"{file_key}_R{revision}",
            "report_key": report_key,
            "revision": revision,
            "eventType": "MAJOR_EVENT",
            "canonicalEventId": receipt["canonical_event_id"],
            "eventFingerprint": receipt["event_fingerprint"],
            "analysisCandidateSha256": analysis["analysis_candidate_sha256"],
            "reportCandidateSha256": report["report_candidate_sha256"],
            "ownerReviewSha256": owner["owner_review_sha256"],
            "governedContentSha256": content_sha,
            "previousRevision": previous.get("revision") if previous else None,
            "previousGovernedContentSha256": previous.get("governedContentSha256") if previous else None,
            "baselineProvenance": provenance,
            "reportCandidateLocator": candidate_rel.as_posix(),
            "ownerReviewLocator": owner_rel.as_posix(),
            "ownerReviewStatus": "OWNER_REVIEW_REQUIRED",
            "formalReportGenerated": False,
            "publication": False,
            "publishAuthorized": False,
            "actionable": False,
        }
        lifecycle_entry = {
            **shared,
            "recordType": "P1008_MAJOR_EVENT_REPORT_LIFECYCLE_ENTRY_V1",
            "lifecycleState": "OWNER_REVIEW_REQUIRED",
            "privateLibraryOwned": False,
        }
        library_entry = {
            **shared,
            "recordType": "P1008_MAJOR_EVENT_PRIVATE_LIBRARY_ENTRY_V1",
            "status": "OWNER_REVIEW_REQUIRED",
            "archiveEligibility": True,
            "privateLibraryEligible": True,
            "libraryEligible": True,
            "lifecycleOwned": False,
        }
        runtime_next = copy.deepcopy(runtime)
        library_next = copy.deepcopy(library)
        runtime_next["generatedAt"] = stamp
        library_next["generatedAt"] = stamp
        runtime_next["reports"].append(lifecycle_entry)
        library_next["reports"].append(library_entry)
        runtime_next["latest"][_latest_slot(report_key)] = lifecycle_entry
        library_next["latest"][_latest_slot(report_key)] = library_entry
        rolling_brief._validate_manifest_relationship(runtime_next, library_next)
        _atomic_transaction({
            candidate_path: _canonical_bytes(dict(report)),
            owner_path: _canonical_bytes(owner_record),
            runtime_path: rolling_brief._canonical_json_bytes(runtime_next),
            library_path: rolling_brief._canonical_json_bytes(library_next),
        })
        _validate_existing_lineage(root, runtime_next, library_next, report_key)
        return {
            "status": "OWNER_REVIEW_REQUIRED",
            "reason": "MAJOR_EVENT_CANDIDATE_PERSISTED",
            "report_key": report_key,
            "revision": revision,
            "governedContentSha256": content_sha,
            "previousRevision": shared["previousRevision"],
            "reportCandidateLocator": candidate_rel.as_posix(),
            "ownerReviewLocator": owner_rel.as_posix(),
            "runtimeManifestPath": rolling_brief.RUNTIME_MANIFEST_REL,
            "privateLibraryManifestPath": rolling_brief.REPORT_MANIFEST_REL,
            "persisted": True,
            "duplicateRevisionCreated": False,
            "published": False,
            "publishAuthorized": False,
            "actionable": False,
        }
    except (MajorEventPersistenceError, materialization.MajorEventMaterializationError) as exc:
        return _failure("FAIL_CLOSED", str(exc) or type(exc).__name__)
