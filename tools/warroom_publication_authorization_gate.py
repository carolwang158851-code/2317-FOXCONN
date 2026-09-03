#!/usr/bin/env python3
"""Independent, revision-specific publication authorization without publication."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

import warroom_integrated_report_completion as report_completion
import warroom_major_event_owner_workflow as owner_workflow
import warroom_major_event_report_persistence as persistence


class PublicationAuthorizationError(RuntimeError):
    """Publication authorization lineage is absent, stale, or invalid."""


AUTHORIZATION_ROOT = Path("runtime/report_production/publication_authorizations")


def _failure(status: str, reason: str) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "publishAuthorized": False,
        "published": False,
        "publicationComplete": False,
        "actionable": False,
    }


def validate_absent_authorization(
    package_root: Path | str,
    *,
    report_key: str,
    revision: int,
    event_type: str,
) -> dict[str, Any]:
    """Prove that a persisted revision has no separate publication receipt.

    This shared denial gate does not grant authorization and deliberately does
    not broaden the MAJOR_EVENT authorization API.
    """

    root = Path(package_root).resolve()
    try:
        if event_type not in {"MONTHLY_REVENUE", "QUARTERLY_EARNINGS", "MAJOR_EVENT"}:
            raise PublicationAuthorizationError("FORMAL_REPORT_EVENT_REQUIRED")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise PublicationAuthorizationError("EXPLICIT_POSITIVE_REVISION_REQUIRED")
        runtime_path = root / "runtime" / "warroom_report_manifest.json"
        library_path = root / "reports" / "P1008_REPORT_MANIFEST.json"
        runtime = persistence._read_json(runtime_path, "RUNTIME_LIFECYCLE_MANIFEST")
        library = persistence._read_json(library_path, "PRIVATE_LIBRARY_MANIFEST")
        identities = []
        for manifest in (runtime, library):
            matches = [
                item for item in manifest.get("reports", [])
                if isinstance(item, Mapping)
                and item.get("eventType") == event_type
                and (item.get("report_key") or item.get("reportKey")) == report_key
                and item.get("revision") == revision
            ]
            if len(matches) != 1:
                raise PublicationAuthorizationError("REPORT_KEY_REVISION_NOT_PERSISTED")
            entry = matches[0]
            if not (
                entry.get("publishAuthorized") is False
                and entry.get("publication") is False
                and entry.get("publicationComplete") is False
                and entry.get("actionable") is False
            ):
                raise PublicationAuthorizationError("PUBLICATION_DEFAULT_DENIAL_INVALID")
            identities.append(entry)
        common = (
            "report_key", "revision", "eventType", "canonicalEventId",
            "analysisCandidateSha256", "reportCandidateSha256",
            "renderedArtifacts", "ownerReviewLocator", "publishAuthorized",
            "publication", "publicationComplete", "actionable",
        )
        if any(identities[0].get(field) != identities[1].get(field) for field in common):
            raise PublicationAuthorizationError("PUBLICATION_GATE_LINEAGE_MISMATCH")
        receipts = list(_authorization_directory(root, report_key, revision).glob("*.json"))
        if receipts:
            raise PublicationAuthorizationError("UNVALIDATED_PUBLICATION_AUTHORIZATION_PRESENT")
        return _failure("DENIED", "EXPLICIT_REVISION_AUTHORIZATION_REQUIRED")
    except (PublicationAuthorizationError, OSError) as exc:
        return _failure("FAIL_CLOSED", str(exc) or type(exc).__name__)


def _revision_context(
    package_root: Path, code_root: Path, report_key: str, revision: int
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    _, _, runtime, library = owner_workflow._manifest_pair(package_root)
    lifecycle, private = owner_workflow._entries(
        package_root, runtime, library, report_key, revision
    )
    if lifecycle.get("eventType") != "MAJOR_EVENT":
        raise PublicationAuthorizationError("MAJOR_EVENT_REVISION_REQUIRED")
    latest = library.get("latest", {}).get(persistence._latest_slot(report_key))
    if not isinstance(latest, Mapping) or persistence._entry_identity(latest) != (
        report_key, revision
    ):
        raise PublicationAuthorizationError("STALE_REPORT_REVISION")
    owner_workflow._validate_baseline_provenance(code_root, lifecycle)
    artifacts = owner_workflow._validate_rendered(package_root, lifecycle, private)
    composition = lifecycle.get("formalComposition")
    if not isinstance(composition, Mapping) or composition != private.get(
        "formalComposition"
    ):
        raise PublicationAuthorizationError("FORMAL_COMPOSITION_LINEAGE_MISSING")
    report_completion.validate_composition(code_root, lifecycle, composition)
    _, owner, _ = owner_workflow._candidate_and_owner(
        package_root, lifecycle, private
    )
    if not (
        lifecycle.get("ownerDecisionState") == "APPROVE"
        and lifecycle.get("publicationEligibility") is True
        and lifecycle.get("publishAuthorized") is False
        and lifecycle.get("publication") is False
        and lifecycle.get("publicationComplete") is False
        and owner.get("decisionState") == "APPROVE"
        and owner.get("ownerApproved") is True
        and owner.get("publicationEligibility") is True
        and len(owner.get("decisions", [])) == 1
    ):
        raise PublicationAuthorizationError("OWNER_APPROVE_REQUIRED")
    return lifecycle, owner, artifacts, dict(composition)


def _authorization_directory(root: Path, report_key: str, revision: int) -> Path:
    token = re.sub(r"[^A-Z0-9_-]+", "_", report_key.upper())
    return root / AUTHORIZATION_ROOT / token / f"r{revision}"


def issue_publication_authorization(
    package_root: Path | str,
    code_root: Path | str,
    *,
    report_key: str,
    revision: int,
    authorization_id: str,
    authorized_by: str,
    authorized_at_utc: str,
    expected_owner_decision_sha256: str,
    expected_report_candidate_sha256: str,
    expected_rendered_artifact_hashes: list[str],
) -> dict[str, Any]:
    """Persist an explicit eligibility receipt; never publish an artifact."""

    root = Path(package_root).resolve()
    code = Path(code_root).resolve()
    try:
        if not (
            isinstance(revision, int) and not isinstance(revision, bool) and revision > 0
            and re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,127}", authorization_id)
            and str(authorized_by).strip()
            and str(authorized_at_utc).endswith("Z")
        ):
            raise PublicationAuthorizationError("PUBLICATION_AUTHORIZATION_IDENTITY_INVALID")
        lifecycle, owner, artifacts, composition = _revision_context(
            root, code, report_key, revision
        )
        decision_sha = owner["decisions"][0]["sha256"]
        if not (
            decision_sha == expected_owner_decision_sha256
            == lifecycle.get("ownerDecisionSha256")
            and lifecycle.get("reportCandidateSha256")
            == expected_report_candidate_sha256
            and [item["sha256"] for item in artifacts]
            == expected_rendered_artifact_hashes
        ):
            raise PublicationAuthorizationError("STALE_PUBLICATION_AUTHORIZATION_CONTEXT")
        directory = _authorization_directory(root, report_key, revision)
        existing = list(directory.glob("*.json")) if directory.is_dir() else []
        receipt_path = directory / f"{authorization_id}.json"
        payload = {
            "record_type": "P1008_REVISION_PUBLICATION_AUTHORIZATION_V1",
            "schema_version": "1.0",
            "authorization_id": authorization_id,
            "authorization_action": "AUTHORIZE_PUBLICATION",
            "authorized_by": authorized_by,
            "authorized_at_utc": authorized_at_utc,
            "report_key": report_key,
            "revision": revision,
            "canonical_event_id": lifecycle["canonicalEventId"],
            "event_fingerprint": lifecycle["eventFingerprint"],
            "analysis_candidate_sha256": lifecycle["analysisCandidateSha256"],
            "report_candidate_sha256": lifecycle["reportCandidateSha256"],
            "formal_composition_sha256": composition["compositionSha256"],
            "authority_binding_sha256": composition["authorityContext"]["bindingSha256"],
            "authority_manifest_sha256": composition["authorityContext"]["candidateManifestSha256"],
            "authority_owner_promotion_required": True,
            "authority_authoritative": False,
            "owner_decision_sha256": decision_sha,
            "rendered_artifacts": artifacts,
            "publicationEligibility": True,
            "publishAuthorized": True,
            "published": False,
            "publicationComplete": False,
            "actionable": False,
        }
        receipt = persistence._with_hash(payload, "authorization_sha256")
        if existing:
            if len(existing) == 1 and existing[0] == receipt_path:
                prior = persistence._read_json(receipt_path, "PUBLICATION_AUTHORIZATION")
                if prior == receipt:
                    return {
                        **receipt,
                        "status": "IDEMPOTENT_AUTHORIZATION_REPLAY",
                        "authorizationLocator": receipt_path.relative_to(root).as_posix(),
                    }
            raise PublicationAuthorizationError("DUPLICATE_PUBLICATION_AUTHORIZATION")
        persistence._atomic_transaction({
            receipt_path: persistence._canonical_bytes(receipt),
        })
        validated = validate_publication_gate(
            root, code, report_key=report_key, revision=revision
        )
        if validated.get("status") != "AUTHORIZED_NOT_PUBLISHED":
            raise PublicationAuthorizationError("PUBLICATION_GATE_POST_WRITE_INVALID")
        return validated
    except (
        PublicationAuthorizationError,
        owner_workflow.MajorEventOwnerWorkflowError,
        persistence.MajorEventPersistenceError,
        report_completion.IntegratedReportCompletionError,
        OSError,
    ) as exc:
        return _failure("FAIL_CLOSED", str(exc) or type(exc).__name__)


def validate_publication_gate(
    package_root: Path | str,
    code_root: Path | str,
    *,
    report_key: str,
    revision: int,
) -> dict[str, Any]:
    """Validate a separate receipt; Owner APPROVE alone remains denied."""

    root = Path(package_root).resolve()
    code = Path(code_root).resolve()
    try:
        lifecycle, owner, artifacts, composition = _revision_context(
            root, code, report_key, revision
        )
        directory = _authorization_directory(root, report_key, revision)
        receipts = list(directory.glob("*.json")) if directory.is_dir() else []
        if not receipts:
            return _failure("DENIED", "EXPLICIT_REVISION_AUTHORIZATION_REQUIRED")
        if len(receipts) != 1:
            raise PublicationAuthorizationError("DUPLICATE_PUBLICATION_AUTHORIZATION")
        receipt = persistence._read_json(receipts[0], "PUBLICATION_AUTHORIZATION")
        supplied = receipt.get("authorization_sha256")
        unhashed = {key: value for key, value in receipt.items() if key != "authorization_sha256"}
        if not (
            supplied == persistence._sha256(persistence._canonical_bytes(unhashed))
            and receipt.get("record_type") == "P1008_REVISION_PUBLICATION_AUTHORIZATION_V1"
            and receipt.get("authorization_action") == "AUTHORIZE_PUBLICATION"
            and receipt.get("report_key") == report_key
            and receipt.get("revision") == revision
            and receipt.get("canonical_event_id") == lifecycle.get("canonicalEventId")
            and receipt.get("event_fingerprint") == lifecycle.get("eventFingerprint")
            and receipt.get("analysis_candidate_sha256") == lifecycle.get("analysisCandidateSha256")
            and receipt.get("report_candidate_sha256") == lifecycle.get("reportCandidateSha256")
            and receipt.get("formal_composition_sha256") == composition.get("compositionSha256")
            and receipt.get("authority_binding_sha256") == composition["authorityContext"]["bindingSha256"]
            and receipt.get("authority_manifest_sha256") == composition["authorityContext"]["candidateManifestSha256"]
            and receipt.get("authority_owner_promotion_required") is True
            and receipt.get("authority_authoritative") is False
            and receipt.get("owner_decision_sha256") == owner["decisions"][0]["sha256"]
            and receipt.get("rendered_artifacts") == artifacts
            and receipt.get("publicationEligibility") is True
            and receipt.get("publishAuthorized") is True
            and receipt.get("published") is False
            and receipt.get("publicationComplete") is False
            and receipt.get("actionable") is False
        ):
            raise PublicationAuthorizationError("PUBLICATION_AUTHORIZATION_LINEAGE_INVALID")
        return {
            **receipt,
            "status": "AUTHORIZED_NOT_PUBLISHED",
            "authorizationLocator": receipts[0].relative_to(root).as_posix(),
        }
    except (
        PublicationAuthorizationError,
        owner_workflow.MajorEventOwnerWorkflowError,
        persistence.MajorEventPersistenceError,
        report_completion.IntegratedReportCompletionError,
        OSError,
    ) as exc:
        return _failure("FAIL_CLOSED", str(exc) or type(exc).__name__)
