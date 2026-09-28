"""Governed, observation-only KPI supplement store and deterministic resolver.

This module is a consumption adapter. It never writes formal authority files,
never enables scoring, and never turns a supplement into an official fact.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from p1008_t1_derived_kpi_bridge_v1 import (
    canonical_json_bytes,
    sha256_bytes,
    validate_t1_eligibility,
)
from p1008_t2_annotated_use_v1 import (
    T2AnnotatedUseError,
    validate_owner_approval,
    validate_t2_research_candidate,
)


SCHEMA_VERSION = "P1008_KPI_SUPPLEMENT_RECORD_V1"
RESOLVER_VERSION = "P1008_KPI_SUPPLEMENT_RESOLVER_V1"
T0 = "T0_DIRECT_OFFICIAL"
T1 = "T1_EXACT_DERIVED"
T2 = "T2_ESTIMATED_DERIVED"
T3 = "T3_EXTERNAL_CROSSCHECK"
T4 = "T4_MODEL_SCENARIO"
DATA_MISSING = "DATA_MISSING"
STORE_RELATIVE_ROOT = Path("runtime/kpi_supplements/v1/records")
UI_PROJECTION_SCHEMA_VERSION = "P1008_KPI_SUPPLEMENT_UI_PROJECTION_V1"
ALLOWED_DISPLAY_SCOPES = frozenset({"REPORT_MAIN_TEXT", "REPORT_KPI_TABLE", "RESEARCH_APPENDIX"})
HASH_RE = re.compile(r"^[A-F0-9]{64}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")

FORBIDDEN_SUBSTITUTIONS = frozenset(
    {
        ("CLOUD_NETWORKING_SHARE", "FOXCONN_AI_REVENUE_SHARE"),
        ("NEWS_EVENT_COUNT", "FOXCONN_AI_DEMAND"),
        ("ETF_PROXY", "VIX"),
        ("ETF_PROXY", "US10Y"),
        ("ETF_PROXY", "DXY"),
        ("ETF_PROXY", "WTI"),
        ("MARKET_SENTIMENT", "FOREIGN_HOLDING_RATIO"),
        ("PARTIAL_OPERATING_INVESTED_CAPITAL_ROIC", "PRECISE_ROIC"),
        ("QUALITATIVE_MANAGEMENT_STATEMENT", "NUMERIC_REVENUE_SHARE"),
    }
)


class SupplementError(ValueError):
    """A supplement or request violated the consumption contract."""


class ImmutableStoreError(SupplementError):
    """An immutable record identity was reused with different bytes."""


@dataclass(frozen=True)
class KPIRequest:
    metric_id: str
    semantic_name: str
    period: str
    as_of_date: str
    unit: str
    display_scope: str = "REPORT_KPI_TABLE"


@dataclass(frozen=True)
class Resolution:
    metric_id: str
    period: str
    value: str | None
    unit: str
    resolved_tier: str
    display_status: str
    annotation_zh: str | None
    confidence: str | None
    range_lower: str | None
    range_upper: str | None
    provenance: tuple[dict[str, Any], ...]
    eligible_lineage: tuple[dict[str, Any], ...]
    block_reasons: tuple[str, ...]
    actionable: bool = False
    formal_scoring_eligible: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "resolver_version": RESOLVER_VERSION,
            "metric_id": self.metric_id,
            "period": self.period,
            "value": self.value,
            "unit": self.unit,
            "resolved_tier": self.resolved_tier,
            "display_status": self.display_status,
            "annotation_zh": self.annotation_zh,
            "confidence": self.confidence,
            "range": (
                {"lower": self.range_lower, "upper": self.range_upper}
                if self.range_lower is not None or self.range_upper is not None
                else None
            ),
            "provenance": list(self.provenance),
            "eligible_lineage": list(self.eligible_lineage),
            "block_reasons": list(self.block_reasons),
            "actionable": False,
            "formal_scoring_eligible": False,
        }


def _decimal_string(value: Any, field: str) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SupplementError(f"{field} must be a finite decimal") from exc
    if not number.is_finite():
        raise SupplementError(f"{field} must be a finite decimal")
    return format(number, "f")


def _parse_date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise SupplementError(f"{field} must be YYYY-MM-DD") from exc


def _validate_timestamp(value: Any, field: str) -> None:
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        raise SupplementError(f"{field} must be a whole-second UTC timestamp ending in Z")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise SupplementError(f"{field} is invalid") from exc


def _same_semantic(source: Any, target: Any) -> bool:
    left = str(source or "").strip().upper()
    right = str(target or "").strip().upper()
    return bool(left) and left == right and (left, right) not in FORBIDDEN_SUBSTITUTIONS


def _hash_object(value: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(dict(value)))


def _lineage(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "data_tier": record.get("data_tier"),
        "candidate_id": record.get("candidate_id"),
        "candidate_hash": record.get("candidate_hash"),
        "formula_id": record.get("formula_id"),
        "formula_version": record.get("formula_version"),
        "source_ids": list(record.get("source_ids", [])),
        "source_hashes": list(record.get("source_hashes", [])),
        "owner_approval_identity": record.get("owner_approval_identity"),
        "formal_authority": False,
        "formal_scoring_eligible": False,
        "actionable": False,
    }


def validate_request(request: KPIRequest) -> None:
    for field in ("metric_id", "semantic_name", "period", "unit"):
        if not str(getattr(request, field)).strip():
            raise SupplementError(f"request {field} is required")
    _parse_date(request.as_of_date, "request.as_of_date")
    if request.display_scope not in ALLOWED_DISPLAY_SCOPES:
        raise SupplementError("display scope is not supplement eligible")


def validate_t0(candidate: Mapping[str, Any], request: KPIRequest) -> dict[str, Any]:
    value = dict(candidate)
    if value.get("data_tier") != T0:
        raise SupplementError("direct candidate is not T0_DIRECT_OFFICIAL")
    if value.get("validation_status") != "PASS" or value.get("formal_authority") is not True:
        raise SupplementError("T0 is not valid formal authority")
    if value.get("metric_id") != request.metric_id:
        raise SupplementError("T0 metric_id mismatch")
    if not _same_semantic(value.get("semantic_name"), request.semantic_name):
        raise SupplementError("T0 semantic mismatch")
    if value.get("period") != request.period:
        raise SupplementError("T0 wrong period; carry-forward is forbidden")
    if value.get("unit") != request.unit:
        raise SupplementError("T0 unit mismatch")
    request_date = _parse_date(request.as_of_date, "request.as_of_date")
    if _parse_date(value.get("as_of_date"), "T0.as_of_date") > request_date:
        raise SupplementError("T0 is future-dated")
    if _parse_date(value.get("source_effective_date"), "T0.source_effective_date") > request_date:
        raise SupplementError("T0 source is future-dated")
    _decimal_string(value.get("value"), "T0.value")
    if not value.get("source_ids") or not value.get("source_hashes"):
        raise SupplementError("T0 source lineage is required")
    if any(not HASH_RE.fullmatch(str(item)) for item in value["source_hashes"]):
        raise SupplementError("T0 source hash is invalid")
    return value


def validate_supplement(record: Mapping[str, Any], request: KPIRequest) -> dict[str, Any]:
    value = dict(record)
    if value.get("schema_version") != SCHEMA_VERSION:
        raise SupplementError("supplement schema version is invalid")
    tier = value.get("data_tier")
    if tier not in {T1, T2}:
        if tier in {T3, T4}:
            raise SupplementError(f"{tier} is cross-check/scenario only")
        raise SupplementError("only T1 or T2 may enter the supplement resolver")
    for field in (
        "candidate_id", "candidate_hash", "metric_id", "semantic_name", "period",
        "as_of_date", "source_effective_date", "value", "unit", "formula_id",
        "formula_version", "created_at",
    ):
        if value.get(field) in (None, ""):
            raise SupplementError(f"supplement {field} is required")
    if not HASH_RE.fullmatch(str(value["candidate_hash"])):
        raise SupplementError("candidate_hash must be uppercase SHA-256")
    _validate_timestamp(value["created_at"], "created_at")
    if value.get("status") != "ACTIVE" or value.get("validation_status") != "PASS":
        raise SupplementError("supplement validation/status did not pass")
    if value.get("formal_authority") is not False:
        raise SupplementError("supplement cannot be formal authority")
    if value.get("formal_scoring_eligible") is not False:
        raise SupplementError("supplement cannot be score eligible")
    if value.get("actionable") is not False:
        raise SupplementError("supplement cannot be actionable")
    if value.get("metric_id") != request.metric_id:
        raise SupplementError("supplement metric_id mismatch")
    if not _same_semantic(value.get("semantic_name"), request.semantic_name):
        raise SupplementError("semantic substitution is forbidden")
    if value.get("period") != request.period:
        raise SupplementError("wrong/stale period; carry-forward is forbidden")
    if value.get("unit") != request.unit:
        raise SupplementError("supplement unit mismatch")
    request_date = _parse_date(request.as_of_date, "request.as_of_date")
    as_of = _parse_date(value.get("as_of_date"), "supplement.as_of_date")
    effective = _parse_date(value.get("source_effective_date"), "supplement.source_effective_date")
    if as_of > request_date or effective > request_date:
        raise SupplementError("future-dated supplement is forbidden")
    if effective > as_of:
        raise SupplementError("source effective date cannot follow candidate as-of date")
    _decimal_string(value["value"], "supplement.value")
    source_ids = value.get("source_ids")
    source_hashes = value.get("source_hashes")
    if not isinstance(source_ids, list) or not source_ids:
        raise SupplementError("source IDs are required")
    if not isinstance(source_hashes, list) or not source_hashes:
        raise SupplementError("source hashes are required")
    if len(source_ids) != len(source_hashes) or any(not HASH_RE.fullmatch(str(item)) for item in source_hashes):
        raise SupplementError("source ID/hash lineage is invalid")

    source_candidate = value.get("source_candidate")
    if not isinstance(source_candidate, dict):
        raise SupplementError("immutable source_candidate is required")
    if _hash_object(source_candidate) != value["candidate_hash"]:
        raise SupplementError("candidate-hash mismatch")
    if source_candidate.get("metric_id") != value["metric_id"]:
        raise SupplementError("source candidate metric binding mismatch")
    if source_candidate.get("period") != value["period"]:
        raise SupplementError("source candidate period binding mismatch")

    if tier == T1:
        eligibility = validate_t1_eligibility(source_candidate)
        if eligibility.status != "PASS":
            raise SupplementError("T1 validation failed: " + "; ".join(eligibility.errors))
        if str(source_candidate.get("value")) != str(value["value"]):
            raise SupplementError("T1 value binding mismatch")
        if value.get("assumptions") not in ([], None) or source_candidate.get("assumption_count") != 0:
            raise SupplementError("T1 assumptions must be zero")
        value["annotation_zh"] = "精確推導"
    else:
        try:
            validate_t2_research_candidate(source_candidate)
        except T2AnnotatedUseError as exc:
            raise SupplementError(f"T2 validation failed: {exc}") from exc
        approval = value.get("owner_approval")
        if not isinstance(approval, dict):
            raise SupplementError("T2 exact Owner approval is required")
        try:
            validate_owner_approval(source_candidate, approval, required_scope=request.display_scope)
        except T2AnnotatedUseError as exc:
            raise SupplementError(f"T2 approval invalid: {exc}") from exc
        if value.get("owner_approved_for_annotated_use") is not True:
            raise SupplementError("T2 is not Owner-approved for annotated use")
        if value.get("owner_approval_identity") != approval.get("approval_id"):
            raise SupplementError("T2 approval identity mismatch")
        if str(source_candidate.get("point_estimate")) != str(value["value"]):
            raise SupplementError("T2 point-estimate binding mismatch")
        if not value.get("assumptions") or not value.get("limitations") or not value.get("confidence"):
            raise SupplementError("T2 assumptions, limitations, and confidence are required")
        value["annotation_zh"] = "推估"
    return value


def resolve_kpi(
    request: KPIRequest,
    *,
    t0_candidates: Sequence[Mapping[str, Any]] = (),
    supplement_records: Sequence[Mapping[str, Any]] = (),
) -> Resolution:
    """Resolve T0 > valid T1 > exact-Owner-approved T2 > DATA_MISSING."""

    validate_request(request)
    reasons: list[str] = []
    valid_t0: list[dict[str, Any]] = []
    valid_t1: list[dict[str, Any]] = []
    valid_t2: list[dict[str, Any]] = []
    lineage: list[dict[str, Any]] = []
    for candidate in t0_candidates:
        try:
            valid_t0.append(validate_t0(candidate, request))
        except (SupplementError, KeyError, TypeError) as exc:
            reasons.append(f"T0_REJECTED:{exc}")
    for record in supplement_records:
        try:
            accepted = validate_supplement(record, request)
        except (SupplementError, KeyError, TypeError) as exc:
            reasons.append(f"SUPPLEMENT_REJECTED:{exc}")
            continue
        lineage.append(_lineage(accepted))
        (valid_t1 if accepted["data_tier"] == T1 else valid_t2).append(accepted)

    def newest(values: list[dict[str, Any]]) -> dict[str, Any]:
        return sorted(values, key=lambda item: (item.get("source_effective_date", ""), item.get("created_at", ""), item.get("candidate_hash", "")))[-1]

    if valid_t0:
        chosen = newest(valid_t0)
        provenance = ({
            "data_tier": T0,
            "source_ids": list(chosen["source_ids"]),
            "source_hashes": list(chosen["source_hashes"]),
            "formal_authority": True,
        },)
        return Resolution(request.metric_id, request.period, str(chosen["value"]), request.unit, T0, "官方直接值", None, None, None, None, provenance, tuple(lineage), tuple(reasons))
    if valid_t1:
        chosen = newest(valid_t1)
        return Resolution(request.metric_id, request.period, str(chosen["value"]), request.unit, T1, "精確推導", "精確推導", chosen.get("confidence"), None, None, (_lineage(chosen),), tuple(lineage), tuple(reasons))
    if valid_t2:
        chosen = newest(valid_t2)
        bounds = chosen.get("range") or {}
        return Resolution(request.metric_id, request.period, str(chosen["value"]), request.unit, T2, "推估", "推估", chosen.get("confidence"), bounds.get("lower"), bounds.get("upper"), (_lineage(chosen),), tuple(lineage), tuple(reasons))
    return Resolution(request.metric_id, request.period, None, request.unit, DATA_MISSING, "DATA_MISSING", None, None, None, None, (), tuple(lineage), tuple(reasons or ["NO_ELIGIBLE_VALUE"]))


class SupplementStore:
    """Filesystem store with create-once identities and fail-open reads."""

    def __init__(self, package_root: str | Path):
        self.package_root = Path(package_root).resolve()
        self.root = (self.package_root / STORE_RELATIVE_ROOT).resolve()
        runtime_root = (self.package_root / "runtime").resolve()
        if runtime_root != self.root and runtime_root not in self.root.parents:
            raise ImmutableStoreError("supplement store must remain under runtime")

    @staticmethod
    def _safe(value: Any, field: str) -> str:
        text = str(value or "")
        if not SAFE_ID_RE.fullmatch(text):
            raise ImmutableStoreError(f"unsafe {field}")
        return text

    def record_path(self, record: Mapping[str, Any]) -> Path:
        metric = self._safe(record.get("metric_id"), "metric_id")
        period = self._safe(record.get("period"), "period")
        candidate = self._safe(record.get("candidate_id"), "candidate_id")
        digest = self._safe(record.get("candidate_hash"), "candidate_hash")
        return self.root / metric / period / f"{candidate}--{digest}.json"

    def put(self, record: Mapping[str, Any]) -> Path:
        approval = record.get("owner_approval")
        approved_scopes = approval.get("approved_use_scope", []) if isinstance(approval, dict) else []
        scope = next(
            (item for item in approved_scopes if item in ALLOWED_DISPLAY_SCOPES),
            "REPORT_KPI_TABLE",
        )
        validate_supplement(
            record,
            KPIRequest(
                metric_id=str(record.get("metric_id", "")),
                semantic_name=str(record.get("semantic_name", "")),
                period=str(record.get("period", "")),
                as_of_date=str(record.get("as_of_date", "")),
                unit=str(record.get("unit", "")),
                display_scope=scope,
            ),
        )
        payload = canonical_json_bytes(dict(record))
        path = self.record_path(record)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != payload:
                raise ImmutableStoreError("immutable candidate identity already exists with different bytes")
            return path
        try:
            with path.open("xb") as handle:
                handle.write(payload)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise ImmutableStoreError("concurrent immutable identity collision")
        return path

    def load_all(self) -> tuple[list[dict[str, Any]], list[str]]:
        records: list[dict[str, Any]] = []
        errors: list[str] = []
        if not self.root.is_dir():
            return records, errors
        for path in sorted(self.root.rglob("*.json")):
            try:
                item = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
                if not isinstance(item, dict):
                    raise ValueError("record is not an object")
                if self.record_path(item).resolve() != path.resolve():
                    raise ValueError("record path/identity mismatch")
                records.append(item)
            except (OSError, ValueError, json.JSONDecodeError, ImmutableStoreError) as exc:
                errors.append(f"{path.name}:{exc}")
        return records, errors


def resolve_from_store(
    package_root: str | Path,
    request: KPIRequest,
    *,
    t0_candidates: Sequence[Mapping[str, Any]] = (),
) -> Resolution:
    """Non-blocking store adapter: Plugin/store failure falls open to T0 or NULL."""

    try:
        records, load_errors = SupplementStore(package_root).load_all()
    except Exception as exc:
        records, load_errors = [], [f"STORE_UNAVAILABLE:{exc}"]
    relevant = [item for item in records if item.get("metric_id") == request.metric_id]
    result = resolve_kpi(request, t0_candidates=t0_candidates, supplement_records=relevant)
    if not load_errors:
        return result
    return Resolution(
        metric_id=result.metric_id,
        period=result.period,
        value=result.value,
        unit=result.unit,
        resolved_tier=result.resolved_tier,
        display_status=result.display_status,
        annotation_zh=result.annotation_zh,
        confidence=result.confidence,
        range_lower=result.range_lower,
        range_upper=result.range_upper,
        provenance=result.provenance,
        eligible_lineage=result.eligible_lineage,
        block_reasons=tuple(list(result.block_reasons) + load_errors),
    )


def _read_formal_rows(path: Path) -> list[dict[str, str]]:
    """Read the governed CSV shape without mutating or normalizing its bytes."""

    lines = path.read_text(encoding="utf-8-sig").splitlines()
    content = [line for line in lines if line.strip() and not line.lstrip().startswith("##")]
    return list(csv.DictReader(content)) if content else []


def build_formal_t0_candidate(
    record: Mapping[str, Any],
    *,
    package_root: str | Path,
    data: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Bind only an exact-period governed formal field for resolver precedence."""

    metric_map = {
        "PRECISE_ROIC": ("masterRows", "Quarter", "ROIC_Precise_Pct", "data/2317_master_v9.csv"),
        "PRECISE_ROIC_PCT": ("masterRows", "Quarter", "ROIC_Precise_Pct", "data/2317_master_v9.csv"),
        "FOREIGN_HOLDING_RATIO": ("masterRows", "Quarter", "ForeignHoldRatio_Pct", "data/2317_master_v9.csv"),
        "FOREIGN_HOLDING_RATIO_PCT": ("masterRows", "Quarter", "ForeignHoldRatio_Pct", "data/2317_master_v9.csv"),
        "FOREIGN_HOLDING_CHANGE": ("masterRows", "Quarter", "ForeignHoldChange_Pct", "data/2317_master_v9.csv"),
        "FOREIGN_HOLDING_CHANGE_PCT": ("masterRows", "Quarter", "ForeignHoldChange_Pct", "data/2317_master_v9.csv"),
        "FOXCONN_AI_REVENUE_SHARE": ("masterRows", "Quarter", "AI_Revenue_Pct", "data/2317_master_v9.csv"),
        "US10Y": ("macroRows", "Date", "US_10Y_Yield", "data/macro_snapshot.csv"),
        "US_10Y": ("macroRows", "Date", "US_10Y_Yield", "data/macro_snapshot.csv"),
        "VIX": ("macroRows", "Date", "VIX", "data/macro_snapshot.csv"),
        "FED_RATE": ("macroRows", "Date", "Fed_Rate", "data/macro_snapshot.csv"),
        "FED_RATE_PATH": ("macroRows", "Date", "Fed_Hike_Prob_YE", "data/macro_snapshot.csv"),
        "DXY": ("macroRows", "Date", "DXY", "data/macro_snapshot.csv"),
        "TWD_USD": ("macroRows", "Date", "TWD_USD", "data/macro_snapshot.csv"),
        "WTI": ("macroRows", "Date", "WTI_Oil", "data/macro_snapshot.csv"),
    }
    binding = metric_map.get(str(record.get("metric_id", "")).upper())
    if binding is None:
        return None
    rows_key, period_key, value_key, source_rel = binding
    matching = [
        row for row in data.get(rows_key, [])
        if str(row.get(period_key, "")) == str(record.get("period", ""))
    ]
    if not matching:
        return None
    raw_value = matching[-1].get(value_key)
    if raw_value in (None, "", "N/A", "NA", "null"):
        return None
    metric_id = str(record.get("metric_id", "")).upper()
    if metric_id in {"FED_RATE", "FED_RATE_PATH"}:
        if "沿用正式 CSV 最近值" in str(matching[-1].get("RiskNote", "")):
            return None
    source_path = Path(package_root).resolve() / source_rel
    return {
        "metric_id": record["metric_id"],
        "semantic_name": record["semantic_name"],
        "period": record["period"],
        "as_of_date": record["as_of_date"],
        "source_effective_date": record["source_effective_date"],
        "value": str(raw_value),
        "unit": record["unit"],
        "data_tier": T0,
        "validation_status": "PASS",
        "formal_authority": True,
        "source_ids": [source_rel],
        "source_hashes": [sha256_bytes(source_path.read_bytes())],
    }


def resolution_to_ui_contract(
    resolution: Resolution,
    *,
    as_of_date: str,
    display_name: str,
) -> dict[str, Any]:
    """Expose the minimal, display-only resolver result consumed by the UI."""

    labels = {
        T0: "正式來源",
        T1: "精確推導",
        T2: "Owner 核准推估",
        DATA_MISSING: "資料不足",
    }
    return {
        "metric_id": resolution.metric_id,
        "display_name": display_name,
        "period": resolution.period,
        "resolved_value": resolution.value,
        "unit": resolution.unit,
        "resolved_tier": resolution.resolved_tier,
        "display_status": resolution.display_status,
        "provenance_label": labels.get(resolution.resolved_tier, "資料不足"),
        "confidence": resolution.confidence,
        "estimate_lower_bound": resolution.range_lower,
        "estimate_upper_bound": resolution.range_upper,
        "owner_approved_for_annotated_use": resolution.resolved_tier == T2,
        "as_of_date": as_of_date,
        "actionable": False,
        "formal_scoring_eligible": False,
    }


def build_ui_projection(package_root: str | Path) -> dict[str, Any]:
    """Build one optional server projection; any failure returns an empty projection."""

    root = Path(package_root).resolve()
    try:
        records, load_errors = SupplementStore(root).load_all()
        data = {
            "masterRows": _read_formal_rows(root / "data/2317_master_v9.csv"),
            "macroRows": _read_formal_rows(root / "data/macro_snapshot.csv"),
        }
        requests: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        for record in records:
            key = (
                str(record.get("metric_id", "")),
                str(record.get("semantic_name", "")),
                str(record.get("period", "")),
                str(record.get("as_of_date", "")),
                str(record.get("unit", "")),
            )
            requests[key] = record
        metrics: list[dict[str, Any]] = []
        for record in requests.values():
            request = KPIRequest(
                metric_id=record["metric_id"],
                semantic_name=record["semantic_name"],
                period=record["period"],
                as_of_date=record["as_of_date"],
                unit=record["unit"],
                display_scope="REPORT_KPI_TABLE",
            )
            direct = build_formal_t0_candidate(record, package_root=root, data=data)
            resolution = resolve_from_store(
                root,
                request,
                t0_candidates=([direct] if direct is not None else []),
            )
            metrics.append(
                resolution_to_ui_contract(
                    resolution,
                    as_of_date=request.as_of_date,
                    display_name=str(record.get("display_name") or request.semantic_name),
                )
            )
        metrics.sort(key=lambda item: (item["metric_id"], item["period"]))
        return {
            "schema_version": UI_PROJECTION_SCHEMA_VERSION,
            "status": "DEGRADED" if load_errors else "READY",
            "metrics": metrics,
        }
    except Exception:
        return {
            "schema_version": UI_PROJECTION_SCHEMA_VERSION,
            "status": "UNAVAILABLE",
            "metrics": [],
        }


def render_report_rows(resolutions: Iterable[Resolution]) -> str:
    """Render existing-report compatible Markdown with required annotations."""

    rows = list(resolutions)
    if not rows:
        return ""
    lines = [
        "## KPI Supplement（僅供研報顯示；不納入正式評分）",
        "",
        "| KPI | Period | Value | Tier / annotation | Confidence / range |",
        "|---|---|---:|---|---|",
    ]
    for item in rows:
        shown = "DATA_MISSING" if item.value is None else f"{item.value} {item.unit}".strip()
        tier = item.resolved_tier if not item.annotation_zh else f"{item.resolved_tier}／{item.annotation_zh}"
        range_text = ""
        if item.range_lower is not None or item.range_upper is not None:
            range_text = f"; range {item.range_lower or 'N/A'}–{item.range_upper or 'N/A'}"
        confidence = f"{item.confidence or 'N/A'}{range_text}"
        lines.append(f"| {item.metric_id} | {item.period} | {shown} | {tier} | {confidence} |")
    lines.extend(["", "- Provenance remains available in each resolver result; actionable:false; formal_scoring_eligible:false.", ""])
    return "\n".join(lines)
