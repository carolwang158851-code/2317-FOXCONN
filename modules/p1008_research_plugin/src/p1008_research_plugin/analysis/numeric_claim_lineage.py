"""Deterministic, evidence-bound numeric claim lineage helpers."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


WORKING_CAPITAL_METRIC_ID = "Q2_WORKING_CAPITAL_PROXY_QOQ_INCREASE"
WORKING_CAPITAL_UNIT = "新台幣百萬元"
WORKING_CAPITAL_FORMULA = (
    "(Q2_AR + Q2_INVENTORY - Q2_AP) - "
    "(Q1_AR + Q1_INVENTORY - Q1_AP)"
)
SHA256 = re.compile(r"^[A-F0-9]{64}$")
INPUT_KEYS = (
    "q1AccountsReceivableMillionTwd", "q1InventoryMillionTwd",
    "q1AccountsPayableMillionTwd", "q2AccountsReceivableMillionTwd",
    "q2InventoryMillionTwd", "q2AccountsPayableMillionTwd",
)


class NumericClaimLineageError(ValueError):
    """A derived numeric claim is not exactly reproducible from its sources."""


def _decimal(value: Any, label: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise NumericClaimLineageError(f"{label}_INVALID") from exc


def validate_working_capital_qoq_lineage(
    payload: Mapping[str, Any], *, expected_source_ids: Sequence[str] | None = None,
    expected_source_sha256: str | None = None, expected_source_page: str | None = None,
) -> dict[str, Any]:
    inputs = payload.get("inputs")
    source_ids = payload.get("sourceEvidenceIds")
    if not isinstance(inputs, Mapping) or set(inputs) != set(INPUT_KEYS):
        raise NumericClaimLineageError("WORKING_CAPITAL_INPUTS_INVALID")
    if not isinstance(source_ids, list) or not source_ids or not all(isinstance(item, str) and item for item in source_ids):
        raise NumericClaimLineageError("WORKING_CAPITAL_CITATION_REQUIRED")
    if payload.get("metricId") != WORKING_CAPITAL_METRIC_ID:
        raise NumericClaimLineageError("WORKING_CAPITAL_METRIC_INVALID")
    if payload.get("unit") != WORKING_CAPITAL_UNIT:
        raise NumericClaimLineageError("WORKING_CAPITAL_UNIT_INVALID")
    if payload.get("formula") != WORKING_CAPITAL_FORMULA:
        raise NumericClaimLineageError("WORKING_CAPITAL_FORMULA_INVALID")
    if payload.get("normalization") != "DECIMAL_EXACT_NO_ROUNDING":
        raise NumericClaimLineageError("WORKING_CAPITAL_NORMALIZATION_INVALID")
    if payload.get("classification") != "DERIVED_FROM_OFFICIAL":
        raise NumericClaimLineageError("WORKING_CAPITAL_CLASSIFICATION_INVALID")
    source_sha = payload.get("sourceDocumentSha256")
    if not isinstance(source_sha, str) or not SHA256.fullmatch(source_sha):
        raise NumericClaimLineageError("WORKING_CAPITAL_SOURCE_HASH_INVALID")
    if not isinstance(payload.get("sourcePage"), str) or not payload["sourcePage"]:
        raise NumericClaimLineageError("WORKING_CAPITAL_SOURCE_PAGE_REQUIRED")
    values = {key: _decimal(inputs[key], key) for key in INPUT_KEYS}
    q1 = values[INPUT_KEYS[0]] + values[INPUT_KEYS[1]] - values[INPUT_KEYS[2]]
    q2 = values[INPUT_KEYS[3]] + values[INPUT_KEYS[4]] - values[INPUT_KEYS[5]]
    expected_value = q2 - q1
    if not (
        _decimal(payload.get("q1NetWorkingCapitalProxyMillionTwd"), "Q1_NWC") == q1
        and _decimal(payload.get("q2NetWorkingCapitalProxyMillionTwd"), "Q2_NWC") == q2
        and _decimal(payload.get("value"), "WORKING_CAPITAL_VALUE") == expected_value
    ):
        raise NumericClaimLineageError("WORKING_CAPITAL_VALUE_MISMATCH")
    if expected_source_ids is not None and source_ids != sorted(expected_source_ids):
        raise NumericClaimLineageError("WORKING_CAPITAL_CITATION_MISMATCH")
    if expected_source_sha256 is not None and source_sha != expected_source_sha256:
        raise NumericClaimLineageError("WORKING_CAPITAL_SOURCE_HASH_MISMATCH")
    if expected_source_page is not None and payload["sourcePage"] != expected_source_page:
        raise NumericClaimLineageError("WORKING_CAPITAL_SOURCE_PAGE_MISMATCH")
    return dict(payload)


def working_capital_qoq_lineage(
    balance_sheet: Mapping[str, Any], *, source_evidence_ids: Sequence[str],
    source_document_sha256: str, source_page: str,
) -> dict[str, Any]:
    q1 = balance_sheet.get("q1")
    if not isinstance(q1, Mapping):
        raise NumericClaimLineageError("WORKING_CAPITAL_Q1_INPUTS_REQUIRED")
    inputs = {
        "q1AccountsReceivableMillionTwd": q1.get("accountsReceivableNetMillionTwd"),
        "q1InventoryMillionTwd": q1.get("inventoryMillionTwd"),
        "q1AccountsPayableMillionTwd": q1.get("accountsPayableMillionTwd"),
        "q2AccountsReceivableMillionTwd": balance_sheet.get("accountsReceivableNetMillionTwd"),
        "q2InventoryMillionTwd": balance_sheet.get("inventoryMillionTwd"),
        "q2AccountsPayableMillionTwd": balance_sheet.get("accountsPayableMillionTwd"),
    }
    values = {key: _decimal(value, key) for key, value in inputs.items()}
    q1_nwc = values[INPUT_KEYS[0]] + values[INPUT_KEYS[1]] - values[INPUT_KEYS[2]]
    q2_nwc = values[INPUT_KEYS[3]] + values[INPUT_KEYS[4]] - values[INPUT_KEYS[5]]
    payload = {
        "metricId": WORKING_CAPITAL_METRIC_ID,
        "value": str(q2_nwc - q1_nwc),
        "unit": WORKING_CAPITAL_UNIT,
        "formula": WORKING_CAPITAL_FORMULA,
        "inputs": {key: str(value) for key, value in inputs.items()},
        "q1NetWorkingCapitalProxyMillionTwd": str(q1_nwc),
        "q2NetWorkingCapitalProxyMillionTwd": str(q2_nwc),
        "normalization": "DECIMAL_EXACT_NO_ROUNDING",
        "classification": "DERIVED_FROM_OFFICIAL",
        "sourceEvidenceIds": sorted(source_evidence_ids),
        "sourceDocumentSha256": source_document_sha256,
        "sourcePage": str(source_page),
    }
    return validate_working_capital_qoq_lineage(
        payload, expected_source_ids=source_evidence_ids,
        expected_source_sha256=source_document_sha256,
        expected_source_page=str(source_page),
    )
