#!/usr/bin/env python3
"""Deterministic formal composition over governed authority and evidence interfaces."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import warroom_integrated_authority as integrated_authority
import warroom_major_event_baseline as baseline_registry


class IntegratedReportCompletionError(RuntimeError):
    """Integrated authority, evidence, or report composition is invalid."""


CAPABILITY_REFERENCES = {
    "TRIGGER_REPORT_MATRIX": (
        "contracts/p1008_report_production/v1.1/"
        "P1008_REPORT_TRIGGER_SECTION_MATRIX_V1.json"
    ),
    "REPORT_PRODUCTION_CONTRACT": (
        "contracts/p1008_report_production/v1.1/"
        "P1008_WAR_REPORT_PRODUCTION_CONTRACT_V1.json"
    ),
    "MONTHLY_QUARTERLY_PIPELINE": (
        "modules/p1008_research_plugin/src/p1008_research_plugin/phaseb1_pipeline.py"
    ),
    "FORMAL_RENDERER": (
        "modules/p1008_research_plugin/src/p1008_research_plugin/reporting/"
        "report_renderer_formal.py"
    ),
    "ROIC_FCF_EV_ANALYTICS": (
        "modules/p1008_research_plugin/src/p1008_research_plugin/reporting/"
        "forward_enterprise_value_analytics.py"
    ),
    "EV_RULE_ENGINE": (
        "modules/p1008_research_plugin/src/p1008_research_plugin/reporting/"
        "enterprise_value_rule_engine.py"
    ),
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _safe_file(root: Path, relative: Any) -> Path:
    raw = Path(str(relative or ""))
    if raw.is_absolute() or not raw.parts or ".." in raw.parts:
        raise IntegratedReportCompletionError("GOVERNED_REFERENCE_INVALID")
    path = (root / raw).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise IntegratedReportCompletionError("GOVERNED_REFERENCE_INVALID")
    return path


def capability_matrix(code_root: Path | str) -> dict[str, Any]:
    root = Path(code_root).resolve()
    references = {
        name: {
            "path": relative,
            "sha256": _sha256(
                _safe_file(root, relative).read_bytes().replace(b"\r\n", b"\n")
            ),
            "hashMode": "LF_CANONICAL_TEXT",
        }
        for name, relative in CAPABILITY_REFERENCES.items()
    }
    try:
        production_contract = json.loads(
            _safe_file(root, CAPABILITY_REFERENCES["REPORT_PRODUCTION_CONTRACT"])
            .read_text(encoding="utf-8-sig")
        )
        trigger_matrix = json.loads(
            _safe_file(root, CAPABILITY_REFERENCES["TRIGGER_REPORT_MATRIX"])
            .read_text(encoding="utf-8-sig")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegratedReportCompletionError("REPORT_CAPABILITY_CONTRACT_INVALID") from exc
    if not (
        set(production_contract.get("valid_triggers", []))
        == {"MONTHLY_REVENUE", "QUARTERLY_EARNINGS", "MAJOR_EVENT"}
        and "DAILY" in production_contract.get("invalid_formal_triggers", [])
        and set((trigger_matrix.get("triggers") or {}).keys())
        >= {"MONTHLY_REVENUE", "QUARTERLY_EARNINGS", "MAJOR_EVENT"}
    ):
        raise IntegratedReportCompletionError("REPORT_CAPABILITY_CONTRACT_MISMATCH")
    return {
        "DAILY": {
            "behavior": "OBSERVATION_ONLY",
            "formalReportEligible": False,
            "privateLibraryEligible": False,
        },
        "MONTHLY_REVENUE": {
            "behavior": "GOVERNED_FORMAL_REPORT",
            "formalReportEligible": True,
            "wiring": ["TRIGGER_REPORT_MATRIX", "MONTHLY_QUARTERLY_PIPELINE", "FORMAL_RENDERER"],
        },
        "QUARTERLY_EARNINGS": {
            "behavior": "GOVERNED_FORMAL_REPORT_WITH_ROIC_FCF_EV",
            "formalReportEligible": True,
            "wiring": [
                "TRIGGER_REPORT_MATRIX", "MONTHLY_QUARTERLY_PIPELINE",
                "ROIC_FCF_EV_ANALYTICS", "EV_RULE_ENGINE", "FORMAL_RENDERER",
            ],
        },
        "MAJOR_EVENT": {
            "behavior": "BOUND_GOVERNED_FORMAL_REPORT",
            "formalReportEligible": True,
            "wiring": [
                "TRIGGER_REPORT_MATRIX", "REPORT_PRODUCTION_CONTRACT",
                "ROIC_FCF_EV_ANALYTICS", "EV_RULE_ENGINE", "FORMAL_RENDERER",
            ],
        },
        "references": references,
        "actionable": False,
        "publishAuthorized": False,
    }


def build_major_event_composition(
    code_root: Path | str, lifecycle: Mapping[str, Any]
) -> dict[str, Any]:
    """Build a hash-bound private formal report composition for one revision."""

    root = Path(code_root).resolve()
    if not (
        lifecycle.get("eventType") == "MAJOR_EVENT"
        and isinstance(lifecycle.get("revision"), int)
        and lifecycle.get("revision", 0) > 0
        and lifecycle.get("actionable") is False
        and lifecycle.get("publication") is False
        and lifecycle.get("publishAuthorized") is False
    ):
        raise IntegratedReportCompletionError("PERSISTED_MAJOR_EVENT_REQUIRED")
    provenance = lifecycle.get("baselineProvenance")
    if not isinstance(provenance, Mapping):
        raise IntegratedReportCompletionError("BASELINE_PROVENANCE_REQUIRED")
    baseline_path = baseline_registry._safe_reference(
        root,
        provenance.get("governed_source_reference"),
        baseline_registry.ALLOWED_SOURCE_PREFIX,
    )
    verified = baseline_registry._verified_content(
        baseline_path.read_bytes(), str(provenance.get("baseline_content_sha256") or "")
    )
    try:
        baseline_content = json.loads(verified.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegratedReportCompletionError("ANALYSIS_BASELINE_INVALID") from exc
    if not isinstance(baseline_content, dict):
        raise IntegratedReportCompletionError("ANALYSIS_BASELINE_INVALID")
    authority = integrated_authority.report_authority_context(root)
    evidence = {
        "triggerDecisionId": lifecycle.get("triggerDecisionId"),
        "triggerReceiptSha256": lifecycle.get("triggerReceiptSha256"),
        "evidenceIds": lifecycle.get("evidenceIds"),
        "authorityCutoffs": lifecycle.get("authorityCutoffs"),
        "canonicalEventId": lifecycle.get("canonicalEventId"),
        "eventFingerprint": lifecycle.get("eventFingerprint"),
    }
    if not (
        isinstance(evidence["triggerDecisionId"], str)
        and isinstance(evidence["triggerReceiptSha256"], str)
        and len(evidence["triggerReceiptSha256"]) == 64
        and isinstance(evidence["evidenceIds"], list)
        and evidence["evidenceIds"]
        and isinstance(evidence["authorityCutoffs"], list)
    ):
        raise IntegratedReportCompletionError("EVIDENCE_LINEAGE_INCOMPLETE")
    content = {
        "recordType": "P1008_INTEGRATED_MAJOR_EVENT_FORMAL_COMPOSITION_V1",
        "schemaVersion": "1.0",
        "state": "OWNER_REVIEW_REQUIRED",
        "report_key": lifecycle["report_key"],
        "revision": lifecycle["revision"],
        "eventType": "MAJOR_EVENT",
        "authorityContext": authority,
        "evidenceLineage": evidence,
        "analysisCandidateSha256": lifecycle["analysisCandidateSha256"],
        "reportCandidateSha256": lifecycle["reportCandidateSha256"],
        "analysisBaselineProvenance": dict(provenance),
        "governedAnalysis": baseline_content,
        "capabilityMatrix": capability_matrix(root),
        "formalReportLibraryEligible": True,
        "ownerReviewRequired": True,
        "publicationGateRequired": True,
        "publication": False,
        "publicationComplete": False,
        "publishAuthorized": False,
        "actionable": False,
    }
    return {**content, "compositionSha256": _sha256(_canonical_bytes(content))}


def validate_composition(
    code_root: Path | str,
    lifecycle: Mapping[str, Any],
    composition: Mapping[str, Any],
) -> dict[str, Any]:
    rebuilt = build_major_event_composition(code_root, lifecycle)
    if dict(composition) != rebuilt:
        raise IntegratedReportCompletionError("FORMAL_COMPOSITION_LINEAGE_MISMATCH")
    return rebuilt
