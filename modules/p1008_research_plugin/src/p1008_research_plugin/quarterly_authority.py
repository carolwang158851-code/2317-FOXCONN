"""Field-level availability rules for the governed quarterly CSV authority."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping


CONTRACT_RELATIVE_PATH = Path(
    "contracts/p1008_quarterly_authority/v1.0/"
    "P1008_QUARTERLY_FIELD_AVAILABILITY_CONTRACT_V1.json"
)
ROIC_STATUS_FIELD = "ROIC_Status"
ROIC_UNAVAILABLE = "INSUFFICIENT_DATA"
ROIC_VALUE_FIELDS = (
    "ROIC_Precise_Pct",
    "NOPAT_Annual_100M",
    "InvestedCapital_100M",
    "InterestBearingDebt_100M",
)
UNAVAILABLE_TOKENS = {"N/A", "NA", "UNAVAILABLE", "INSUFFICIENT_DATA"}


class QuarterlyAuthorityError(ValueError):
    """Raised when quarterly field availability is internally inconsistent."""


def load_quarterly_authority_contract(package_root: Path) -> dict[str, Any]:
    path = package_root.resolve() / CONTRACT_RELATIVE_PATH
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schemaVersion") != "P1008_QUARTERLY_FIELD_AVAILABILITY_V1":
        raise QuarterlyAuthorityError("QUARTERLY_AUTHORITY_CONTRACT_VERSION_INVALID")
    if tuple(value.get("conditionallyBlankFields", ())) != ROIC_VALUE_FIELDS:
        raise QuarterlyAuthorityError("QUARTERLY_AUTHORITY_CONTRACT_FIELDS_INVALID")
    if value.get("unavailableStatus") != ROIC_UNAVAILABLE:
        raise QuarterlyAuthorityError("QUARTERLY_AUTHORITY_CONTRACT_STATUS_INVALID")
    return value


def _is_numeric(value: object) -> bool:
    text = str(value or "").strip()
    if not text or text.upper() in UNAVAILABLE_TOKENS:
        return False
    try:
        Decimal(text.replace("%", "").replace("+", ""))
    except InvalidOperation:
        return False
    return True


def validate_quarterly_authority_row(
    row: Mapping[str, object], *, allowed_statuses: Iterable[str] | None = None
) -> None:
    status = str(row.get(ROIC_STATUS_FIELD, "")).strip()
    allowed = set(
        allowed_statuses
        or {
            "LOW_CAPITAL_EFFICIENCY",
            "ACCEPTABLE_CAPITAL_EFFICIENCY",
            "HIGH_CAPITAL_EFFICIENCY",
            ROIC_UNAVAILABLE,
        }
    )
    if status not in allowed:
        raise QuarterlyAuthorityError("ROIC_STATUS_INVALID_OR_MISSING")

    values = {field: str(row.get(field, "") or "").strip() for field in ROIC_VALUE_FIELDS}
    if any(value.upper() in UNAVAILABLE_TOKENS for value in values.values()):
        raise QuarterlyAuthorityError("ROIC_BARE_UNAVAILABLE_TOKEN_INVALID")
    if status == ROIC_UNAVAILABLE:
        if any(values.values()):
            raise QuarterlyAuthorityError("ROIC_UNAVAILABLE_STATUS_REQUIRES_BLANK_FIELDS")
    elif not all(_is_numeric(value) for value in values.values()):
        raise QuarterlyAuthorityError("ROIC_AVAILABLE_STATUS_REQUIRES_NUMERIC_FIELDS")

    required_verified = (
        "Quarter",
        "QuarterEndDate",
        "EstimatedEffectiveDate",
        "EPS_Q",
        "EPS_TTM",
        "BVPS",
        "ROE_TTM_Pct",
        "DataSource",
        "DataSupportLevel",
    )
    missing = [field for field in required_verified if not str(row.get(field, "") or "").strip()]
    if missing:
        raise QuarterlyAuthorityError("QUARTERLY_VERIFIED_FIELDS_MISSING:" + ",".join(missing))
    for field in ("EPS_Q", "EPS_TTM", "BVPS", "ROE_TTM_Pct"):
        if not _is_numeric(row[field]):
            raise QuarterlyAuthorityError(f"QUARTERLY_VERIFIED_FIELD_NOT_NUMERIC:{field}")


def roic_is_available(row: Mapping[str, object]) -> bool:
    validate_quarterly_authority_row(row)
    return str(row[ROIC_STATUS_FIELD]).strip() != ROIC_UNAVAILABLE


def latest_available_roic_row(rows: Iterable[Mapping[str, object]]) -> Mapping[str, object]:
    candidates = []
    for row in rows:
        validate_quarterly_authority_row(row)
        if str(row[ROIC_STATUS_FIELD]).strip() != ROIC_UNAVAILABLE:
            candidates.append(row)
    if not candidates:
        raise QuarterlyAuthorityError("NO_AVAILABLE_ROIC_QUARTER")
    return candidates[-1]


def quarterly_metric_availability(rows: Iterable[Mapping[str, object]]) -> dict[str, Any]:
    normalized = list(rows)
    if not normalized:
        raise QuarterlyAuthorityError("QUARTERLY_AUTHORITY_EMPTY")
    for row in normalized:
        validate_quarterly_authority_row(row)
    roe_rows = [row for row in normalized if _is_numeric(row.get("ROE_TTM_Pct"))]
    roic_rows = [row for row in normalized if roic_is_available(row)]
    if not roe_rows or not roic_rows:
        raise QuarterlyAuthorityError("QUARTERLY_METRIC_HISTORY_INCOMPLETE")
    return {
        "latestValidRoeQuarter": str(roe_rows[-1]["Quarter"]),
        "latestValidRoicQuarter": str(roic_rows[-1]["Quarter"]),
        "roe": {
            "labels": [str(row["Quarter"]) for row in roe_rows],
            "values": [str(row["ROE_TTM_Pct"]) for row in roe_rows],
        },
        "roic": {
            "labels": [str(row["Quarter"]) for row in roic_rows],
            "values": [str(row["ROIC_Precise_Pct"]) for row in roic_rows],
        },
        "unavailableRoicQuarters": [
            str(row["Quarter"])
            for row in normalized
            if str(row[ROIC_STATUS_FIELD]).strip() == ROIC_UNAVAILABLE
        ],
    }
