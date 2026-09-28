"""Deterministic, fail-closed T1 derived-KPI bridge for P1008.

The module accepts only P1008_DERIVED_KPI_CANDIDATE_V1 objects whose tier is
T1_EXACT_DERIVED.  It validates and recomputes the Plugin-owned object, then
creates immutable serialized bytes for a War Room staging envelope, validation
receipt, and manifest.  It has no formal CSV, authority-manifest, publisher,
scoring, UI, or Launcher integration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from p1008_derived_kpi_candidate_v1 import (
    CandidateValidationError,
    REQUIRED_FIELDS,
    T0,
    T1,
    load_json,
    recompute,
    validate_candidate,
)


ADAPTER_VERSION = "P1008_T1_DERIVED_KPI_ADAPTER_V1"
ENVELOPE_SCHEMA_VERSION = "P1008_T1_WAR_ROOM_CANDIDATE_V1"
RECEIPT_SCHEMA_VERSION = "P1008_T1_VALIDATION_RECEIPT_V1"
MANIFEST_SCHEMA_VERSION = "P1008_T1_BRIDGE_MANIFEST_V1"
STAGING_RELATIVE_ROOT = Path("staging/t1_derived_kpi_candidates")
ALLOWED_ANCESTRY = frozenset({T0, T1})
REJECTED_TIERS = frozenset(
    {"T2_ESTIMATED_DERIVED", "T3_EXTERNAL_CROSSCHECK", "T4_MODEL_SCENARIO"}
)
FORBIDDEN_LINEAGE_MARKERS = (
    "PREVIOUS_PERIOD_CARRY",
    "CARRY_FORWARD",
    "CARRY-FORWARD",
    "FORWARD_FILL",
    "BACKFILL",
    "DEFAULT_FILL",
    "SILENT_FILL",
    "IMPUTED",
    "IMPUTATION",
)
UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

ROIC_FORMULA_AUTHORITY = "HISTORICAL_MASTER_PRECISE_ROIC_LINEAGE"
ROIC_REQUIRED_INPUTS = (
    "OperatingIncome_Q_100M",
    "StandardizedAnnualTaxRate",
    "InterestBearingDebt_100M",
    "ParentEquity_100M",
    "Cash_100M",
    "ApprovedSameBasisInvestedCapitalBridge",
)
ROIC_AVAILABLE_INPUTS = (
    "OperatingIncome_Q_100M",
    "Cash_100M",
    "ReportedPretaxIncome_100M",
    "ReportedTaxExpense_100M",
    "TotalEquity_100M",
)
ROIC_MISSING_INPUTS = (
    "InterestBearingDebt_100M",
    "SameDefinitionInvestedCapital_100M",
    "StandardizedAnnualTaxRate",
    "ApprovedSameBasisEquityInvestedCapitalBridge",
)


class T1BridgeError(ValueError):
    """Raised when a source candidate or bridge operation fails closed."""


@dataclass(frozen=True)
class EligibilityResult:
    status: str
    errors: tuple[str, ...]
    recomputed_value: str | None


@dataclass(frozen=True)
class BridgeBundle:
    """Immutable canonical JSON byte payloads for the bridge crossing."""

    candidate_id: str
    envelope_bytes: bytes
    receipt_bytes: bytes
    manifest_bytes: bytes

    def envelope(self) -> dict[str, Any]:
        return json.loads(self.envelope_bytes)

    def receipt(self) -> dict[str, Any]:
        return json.loads(self.receipt_bytes)

    def manifest(self) -> dict[str, Any]:
        return json.loads(self.manifest_bytes)


def canonical_json_bytes(value: Any) -> bytes:
    """Return the bridge's only hash/serialization representation."""

    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _validate_created_at(created_at: str) -> None:
    if not isinstance(created_at, str) or not UTC_TIMESTAMP_RE.fullmatch(created_at):
        raise T1BridgeError("created_at must be a whole-second UTC timestamp ending in Z")
    try:
        datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise T1BridgeError("created_at is not a valid UTC timestamp") from exc


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {_flatten_text(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    return str(value)


def validate_t1_eligibility(candidate: dict[str, Any]) -> EligibilityResult:
    """Apply the bridge-only T1 gate on top of the completed input contract."""

    errors: list[str] = []
    tier = candidate.get("data_tier")
    if tier != T1:
        if tier in REJECTED_TIERS:
            errors.append(f"data_tier {tier} is not bridge-eligible")
        else:
            errors.append(f"unknown or missing data_tier is not bridge-eligible: {tier!r}")
        return EligibilityResult("FAIL", tuple(errors), None)

    contract_errors = validate_candidate(candidate)
    errors.extend(f"input contract: {error}" for error in contract_errors)
    unexpected_fields = sorted(set(candidate) - set(REQUIRED_FIELDS))
    if unexpected_fields:
        errors.append(
            "input contract contains unsupported fields: " + ", ".join(unexpected_fields)
        )

    # The completed input contract intentionally uses VALIDATED_CANDIDATE.  The
    # bridge emits PASS only after this independent gate and recomputation pass.
    if candidate.get("validation_status") != "VALIDATED_CANDIDATE":
        errors.append("source validation_status is not VALIDATED_CANDIDATE")
    if candidate.get("actionable") is not False:
        errors.append("actionable must be false")
    if candidate.get("publication") is not False:
        errors.append("publication must be false")
    if candidate.get("production_scoring_enabled") is not False:
        errors.append("production scoring must remain disabled")
    for field in ("formula_id", "formula_version", "formula_expression"):
        value = candidate.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field} is required")

    source_ids = candidate.get("input_source_ids")
    source_locators = candidate.get("input_source_locators")
    input_hashes = candidate.get("input_hashes")
    if not isinstance(source_ids, list) or not source_ids or any(not str(v).strip() for v in source_ids):
        errors.append("all input source IDs are required")
    if not isinstance(source_locators, list) or not source_locators or any(
        not str(v).strip() for v in source_locators
    ):
        errors.append("all input source locators are required")
    if not isinstance(input_hashes, list) or not input_hashes or any(
        not isinstance(v, str) or not re.fullmatch(r"[A-F0-9]{64}", v)
        for v in input_hashes
    ):
        errors.append("all input hashes must be present uppercase SHA-256 digests")

    ancestry = candidate.get("input_source_tiers")
    if not isinstance(ancestry, list) or not ancestry:
        errors.append("input source ancestry is required")
    else:
        for index, ancestor in enumerate(ancestry):
            if ancestor not in ALLOWED_ANCESTRY:
                errors.append(f"input_source_tiers[{index}] is forbidden T1 ancestry: {ancestor}")

    if candidate.get("assumptions") != [] or candidate.get("assumption_count") != 0:
        errors.append("T1 assumptions must be empty and zero")
    if candidate.get("semantic_match_status") != "EXACT_MATCH":
        errors.append("semantic match did not pass")
    if candidate.get("proxy_metric_used") is not False or candidate.get(
        "proxy_relabelled_as_direct"
    ) is not False:
        errors.append("proxy substitution is forbidden")

    flattened = _flatten_text(candidate).upper()
    for marker in FORBIDDEN_LINEAGE_MARKERS:
        if marker in flattened:
            errors.append(f"forbidden carry/imputation lineage marker: {marker}")

    recomputed_value: str | None = None
    if not contract_errors:
        try:
            recomputed_value = format(recompute(candidate), "f")
        except (CandidateValidationError, KeyError, ArithmeticError) as exc:
            errors.append(f"deterministic recomputation failed: {exc}")
        else:
            if recomputed_value != str(candidate.get("value")):
                errors.append(
                    f"deterministic recomputation mismatch: {recomputed_value} != {candidate.get('value')}"
                )

    return EligibilityResult(
        "PASS" if not errors else "FAIL", tuple(dict.fromkeys(errors)), recomputed_value
    )


def _adapter_hash(adapter_path: str | Path | None = None) -> str:
    return sha256_file(Path(adapter_path) if adapter_path else Path(__file__))


def adapt_t1_candidate(
    candidate: dict[str, Any],
    *,
    created_at: str,
    adapter_path: str | Path | None = None,
) -> BridgeBundle:
    """Validate and cross one Plugin-owned T1 candidate into War Room staging."""

    _validate_created_at(created_at)
    eligibility = validate_t1_eligibility(candidate)
    if eligibility.status != "PASS":
        raise T1BridgeError("; ".join(eligibility.errors))

    source_bytes = canonical_json_bytes(candidate)
    source_hash = sha256_bytes(source_bytes)
    adapter_hash = _adapter_hash(adapter_path)
    candidate_id = f"WR-T1-{source_hash[:16]}-{adapter_hash[:12]}"
    receipt_id = f"T1VR-{source_hash[:16]}-{adapter_hash[:12]}"

    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "validation_receipt_id": receipt_id,
        "source_candidate_id": candidate["candidate_id"],
        "source_candidate_hash": source_hash,
        "adapter_version": ADAPTER_VERSION,
        "adapter_hash": adapter_hash,
        "created_at": created_at,
        "validation_status": "PASS",
        "eligibility_gate": "T1_EXACT_DERIVED_ONLY",
        "recomputed_value": eligibility.recomputed_value,
        "governed_rounding_rule": candidate["rounding_rule"],
        "checks": [
            "INPUT_CONTRACT_PASS",
            "T1_ONLY_PASS",
            "LINEAGE_ANCESTRY_PASS",
            "PERIOD_UNIT_DENOMINATOR_PASS",
            "NO_ASSUMPTION_PROXY_CARRY_OR_IMPUTATION_PASS",
            "DETERMINISTIC_RECOMPUTATION_PASS",
            "NON_ACTIONABLE_NON_PUBLICATION_PASS",
        ],
        "formal_authority": False,
        "actionable": False,
        "publication": False,
    }
    receipt_bytes = canonical_json_bytes(receipt)
    receipt_hash = sha256_bytes(receipt_bytes)

    envelope = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "source_candidate_id": candidate["candidate_id"],
        "synthetic_fixture": candidate["synthetic_fixture"],
        "metric_id": candidate["metric_id"],
        "dimension": candidate["dimension"],
        "period": candidate["period"],
        "as_of_date": candidate["as_of_date"],
        "value": candidate["value"],
        "unit": candidate["unit"],
        "data_tier": T1,
        "formula_id": candidate["formula_id"],
        "formula_version": candidate["formula_version"],
        "formula_expression": candidate["formula_expression"],
        "input_source_ids": list(candidate["input_source_ids"]),
        "input_source_locators": list(candidate["input_source_locators"]),
        "input_hashes": list(candidate["input_hashes"]),
        "source_candidate_hash": source_hash,
        "adapter_version": ADAPTER_VERSION,
        "adapter_hash": adapter_hash,
        "validation_receipt_id": receipt_id,
        "validation_receipt_hash": receipt_hash,
        "created_at": created_at,
        "candidate_owner": "WAR_ROOM",
        "origin": "PLUGIN_DERIVED_T1",
        "owner_review_required": True,
        "formal_authority": False,
        "actionable": False,
        "publication": False,
        "production_scoring_enabled": False,
    }
    envelope_bytes = canonical_json_bytes(envelope)
    envelope_hash = sha256_bytes(envelope_bytes)

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_id": f"T1BM-{envelope_hash[:16]}",
        "candidate_id": candidate_id,
        "candidate_sha256": envelope_hash,
        "candidate_schema_version": ENVELOPE_SCHEMA_VERSION,
        "validation_receipt_id": receipt_id,
        "validation_receipt_sha256": receipt_hash,
        "validation_receipt_schema_version": RECEIPT_SCHEMA_VERSION,
        "source_candidate_id": candidate["candidate_id"],
        "synthetic_fixture": candidate["synthetic_fixture"],
        "source_candidate_sha256": source_hash,
        "source_contract": "P1008_DERIVED_KPI_CANDIDATE_V1",
        "adapter_version": ADAPTER_VERSION,
        "adapter_sha256": adapter_hash,
        "created_at": created_at,
        "candidate_owner": "WAR_ROOM",
        "formal_authority": False,
        "owner_review_required": True,
        "actionable": False,
        "publication": False,
        "production_scoring_enabled": False,
    }
    manifest_bytes = canonical_json_bytes(manifest)
    return BridgeBundle(
        candidate_id=candidate_id,
        envelope_bytes=envelope_bytes,
        receipt_bytes=receipt_bytes,
        manifest_bytes=manifest_bytes,
    )


def _assert_staging_destination(output_root: Path, repository_root: Path) -> None:
    allowed = (repository_root.resolve() / STAGING_RELATIVE_ROOT).resolve()
    resolved = output_root.resolve()
    if resolved != allowed and allowed not in resolved.parents:
        raise T1BridgeError(
            f"output must remain under isolated staging root: {allowed}"
        )


def write_bundle(
    bundle: BridgeBundle, *, output_root: str | Path, repository_root: str | Path
) -> tuple[Path, Path, Path]:
    """Write a once-only staging bundle; existing identities cannot be replaced."""

    root = Path(output_root)
    repo = Path(repository_root)
    _assert_staging_destination(root, repo)
    destination = root / bundle.candidate_id
    destination.mkdir(parents=True, exist_ok=False)
    paths = (
        destination / "WAR_ROOM_CANDIDATE.json",
        destination / "VALIDATION_RECEIPT.json",
        destination / "CANDIDATE_MANIFEST.json",
    )
    for path, payload in zip(
        paths, (bundle.envelope_bytes, bundle.receipt_bytes, bundle.manifest_bytes)
    ):
        with path.open("xb") as handle:
            handle.write(payload)
    return paths


def roic_bridge_status(available_inputs: list[str] | tuple[str, ...]) -> dict[str, Any]:
    """Return the fixed current ROIC gap without manufacturing a candidate."""

    available = tuple(dict.fromkeys(available_inputs))
    return {
        "ROIC_REQUIRED_INPUTS": list(ROIC_REQUIRED_INPUTS),
        "ROIC_AVAILABLE_INPUTS": list(available),
        "ROIC_MISSING_INPUTS": list(ROIC_MISSING_INPUTS),
        "ROIC_FORMULA_AUTHORITY": ROIC_FORMULA_AUTHORITY,
        "ROIC_CURRENT_STATUS": "DATA_GAP",
        "candidate_allowed": False,
    }


def domain_route(metric_family: str, *, direct_observation_exists: bool = False) -> str:
    """Guard known domains from inappropriate derived-T1 substitution."""

    normalized = metric_family.strip().upper()
    if normalized == "POSITIONING":
        return "RAW_SOURCE_REMEDIATION_REQUIRED"
    if normalized == "MACRO" and direct_observation_exists:
        return "DIRECT_OBSERVATION_USE_REQUIRED"
    if normalized in {"INDUSTRY", "INDUSTRY_AI", "AI"}:
        return "NO_ELIGIBLE_CURRENT_NUMERIC_KPI"
    return "T1_ELIGIBILITY_REVIEW_REQUIRED"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        source = load_json(args.candidate)
        bundle = adapt_t1_candidate(source, created_at=args.created_at)
        paths = write_bundle(
            bundle,
            output_root=args.output_root,
            repository_root=args.repository_root,
        )
    except (CandidateValidationError, T1BridgeError, FileExistsError) as exc:
        print(f"T1_DERIVED_KPI_BRIDGE=FAIL_CLOSED\nERROR={exc}")
        return 1
    print("T1_DERIVED_KPI_BRIDGE=PASS")
    print(f"candidate_id={bundle.candidate_id}")
    for path in paths:
        print(path)
    print("formal_authority=false")
    print("actionable=false")
    print("publication=false")
    print("production_scoring_enabled=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
