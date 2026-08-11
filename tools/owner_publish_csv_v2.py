#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Owner-gated formal CSV append helper for P1008.

Default mode is review-only. Formal CSV writes require:
- staging/<date>/DRY_RUN.json exists
- readiness score >= 95
- no critical missing fields
- candidate CSV schema matches formal CSV
- no duplicate Date/Key in formal CSV
- --publish plus exact Owner approval phrase
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


DAILY_TARGET = "data/2317_daily_price.csv"
MACRO_TARGET = "data/macro_snapshot.csv"
MACRO_EVENT_TARGET = "data/macro_event_observations.csv"
FX_TREND_TARGET = "data/fx_trend_observations.csv"
MANIFEST_PATH = "data/CSV_AUTHORITY_MANIFEST.json"
MIN_PUBLISH_SCORE = 95
MISSING_SOURCE_VALUES = {"DATA_MISSING", "MISSING", "UNAVAILABLE", "N/A", "NA", "", "CONNECTOR_SOURCE_UNAVAILABLE_CARRY_FORWARD"}
FORMAL_DAILY_STATUS = "OK"
STAGING_DAILY_STATUSES = {"STAGING_CANDIDATE", "RUNTIME_SNAPSHOT", "RUNTIME_REVIEW_REQUIRED"}
OBSERVATION_ONLY_TARGETS = {MACRO_EVENT_TARGET, FX_TREND_TARGET}
ALLOWED_SOURCE_TIERS = {
    "OFFICIAL",
    "PUBLIC_MARKET",
    "PUBLIC_MARKET_DATA",
    "PUBLIC_OFFICIAL_SERIES",
    "PUBLIC_MARKET_AND_OFFICIAL_SERIES",
    "MEDIA",
    "OWNER_NOTE",
    "OWNER_INPUT",
    "UNVERIFIED",
    "CONNECTOR_PENDING",
    "CARRY_FORWARD",
}

REMEDIATION_CANDIDATE_SHA256 = (
    "E81AE954B7C621616E844B0034F7259F91FE3F6FCCFF2A5FBC84714BCE174A16"
)
REMEDIATION_FORMAL_OLD_SHA256 = (
    "CD0C42DB047CA80C25D6D8D6A652D4D258A05C9A3AE1FC1BAE96CBBCA3D12369"
)
REMEDIATION_CANDIDATE_NAME = "2317_daily_price_remediated_20260718.candidate.csv"
REMEDIATION_EXPECTED_ROWS = 110
REMEDIATION_EXPECTED_REPAIRS = {
    "2026-06-22": Decimal("268.50"),
    "2026-06-23": Decimal("259.50"),
    "2026-06-24": Decimal("256.00"),
    "2026-06-25": Decimal("257.50"),
    "2026-06-26": Decimal("248.50"),
    "2026-06-29": Decimal("246.50"),
    "2026-07-01": Decimal("248.00"),
    "2026-07-02": Decimal("239.00"),
    "2026-07-03": Decimal("240.50"),
    "2026-07-09": Decimal("237.50"),
    "2026-07-13": Decimal("236.50"),
    "2026-07-14": Decimal("235.50"),
    "2026-07-15": Decimal("239.00"),
}
REMEDIATION_REMOVED_DATES = {
    "2026-06-19",
    "2026-06-20",
    "2026-07-05",
    "2026-07-10",
}

MARKET_ACTIVITY_TARGET = "data/2317_daily_market_activity.csv"
MARKET_ACTIVITY_PRICE_SHA256 = REMEDIATION_CANDIDATE_SHA256
MARKET_ACTIVITY_FIELDS = (
    "date",
    "stock_id",
    "trade_volume",
    "trade_value",
    "transaction_count",
    "source_url",
    "source_month",
)
MARKET_ACTIVITY_EXPECTED_ROWS = 60
MARKET_ACTIVITY_EXPECTED_START = "2026-04-22"
MARKET_ACTIVITY_EXPECTED_END = "2026-07-17"
INVALID_DAILY_PRICE_DATE = "2026-07-19"
INVALID_DAILY_PRICE_APPROVAL_PHRASE = (
    "OWNER_APPROVE_REMOVE_INVALID_DAILY_PRICE_2026-07-19"
)
DAILY_PRICE_GAPS_APPROVAL_PHRASE = (
    "OWNER_APPROVE_DAILY_PRICE_GAPS_20260722_20260724"
)
DAILY_PRICE_GAPS_CANDIDATE_SHA256 = (
    "904D38BC382E21C3F90ADCDEB981423F0F8FB2E6D5ED7824D1961AD6CBD3DB2D"
)
DAILY_PRICE_GAPS_REQUIRED_FORMAL_SHA256 = (
    "0D9D55B3C1C28F0BF45EFC7B623D77D672B07EC9B2099EAD6EDB3A5D7318DEC2"
)
DAILY_PRICE_GAPS_EXPECTED_FORMAL_SHA256 = (
    "2581AF868AA0D8C4BFCEA913B156DBB515AF3929FAAE7D0FDC947EA4A8256304"
)
DAILY_PRICE_GAPS_EXPECTED_ROWS = 116
DAILY_PRICE_GAPS_EXPECTED_VALUES = {
    "2026-07-22": {
        "Close": "251.50",
        "QuarterKey": "2026Q1",
        "BVPS_ref": "127.12",
        "PB_daily": "1.978",
    },
    "2026-07-24": {
        "Close": "252.50",
        "QuarterKey": "2026Q1",
        "BVPS_ref": "127.12",
        "PB_daily": "1.986",
    },
}
APPROVED_DAILY_PRICE_SOURCE_LEVELS = {
    "OFFICIAL_TWSE_A1",
    "OFFICIAL_TWSE_STOCK_DAY",
    "OWNER_APPROVED",
}
MARKET_ACTIVITY_RECEIPTS = {
    "2026-04": {
        "receipt_sha256": "2B2D456382DDE3BCC6E39EA91BDF3248C802A14BB7F5FE6B98718B90E0BCBB74",
        "raw_sha256": "E883E7C4B76003D01BF2CDCC46A340981EC29661492D3C41E8582D01C0121507",
    },
    "2026-05": {
        "receipt_sha256": "E89FED940579DCEBCA12539C9FB9CEA5C05A9217E3346C62620B2AA9BAF01B21",
        "raw_sha256": "5134D4DE50D136AF5337D59D36A50D420336FFB0F08470DE04B61CF53CBFEC8A",
    },
    "2026-06": {
        "receipt_sha256": "1661984B856C8B6167A2F4B9E69620089F0DDC472460C7CBDA92EE175B6ED462",
        "raw_sha256": "A93C38DA69AA8AEF92602BF874A445D74CBB6D1EA358DE7C36178C19EFCD5D39",
    },
    "2026-07": {
        "receipt_sha256": "25BABF6599E49629715755C0A2F05021B9C6D696453BFDFEDD087472AFE21027",
        "raw_sha256": "907165CBFA6AA4E67701E95F1301A46252389789BBDFB6D67679813712E0CB28",
    },
}
MACRO_STAGE2B_APPROVAL_PHRASE = (
    "OWNER_APPROVE_MACRO_HON_HAI_REV_YOY_REMEDIATION"
)
MACRO_STAGE2B_REQUIRED_HEAD = (
    "76a62bbeccc3c89aea3605d6239910afe82aba5b"
)
MACRO_STAGE2B_CANONICAL_BEFORE_SHA256 = (
    "353025C29D678488F7022939C86C36CB15D3B348DC5876909D6779E56CFE213B"
)
MACRO_STAGE2B_CANDIDATE_SHA256 = (
    "30A4755E87CECD4230FA8A521DF485385A89AC2A4E1E2B5726CBFD14AB96C86F"
)
MACRO_STAGE2B_ROW_IDENTITY_RECEIPT_SHA256 = (
    "E72989762053D20665DD87DA263F8B4DB1E77D277A6A27FD6C8AABBFE4921B9D"
)
MACRO_STAGE2B_MANIFEST_BEFORE_SHA256 = (
    "7E191C8204436CAE914F7F4E930D04A542798A16F97950C03DF32C93ABAFA8B9"
)
MACRO_STAGE2B_MANIFEST_AFTER_SHA256 = (
    "966352C4DD34938240901095DE5937C69C9BE8638413C2F900977C5EDBAA9C67"
)
MACRO_STAGE2B_EXPECTED_ROWS = 39
MACRO_STAGE2B_EXPECTED_CUTOFF = "2026-07-10"
MACRO_STAGE2B_EXPECTED_IDENTITIES = (
    (1, 23, "2021-03-31", "None"),
    (26, 48, "2026-06-03", None),
    (27, 49, "2026-06-04", None),
    (28, 50, "2026-06-05", None),
    (29, 51, "2026-06-12", None),
)


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest().upper()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def latest_staging_dir(package_root: Path) -> Path:
    staging_root = package_root / "staging"
    candidates = [
        path
        for path in staging_root.iterdir()
        if path.is_dir() and (path / "DRY_RUN.json").exists()
    ]
    if not candidates:
        raise SystemExit("No staging/<date>/DRY_RUN.json was found.")
    return sorted(candidates, key=lambda path: path.name)[-1]


def read_csv_header_and_rows(path: Path) -> tuple[list[str], list[list[str]], list[str]]:
    comments: list[str] = []
    csv_lines: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not csv_lines and line.startswith("#"):
            comments.append(line)
            continue
        if line.strip():
            csv_lines.append(line)
    if not csv_lines:
        raise ValueError(f"{path} has no CSV header.")
    rows = list(csv.reader(csv_lines))
    return rows[0], rows[1:], comments


def row_count(path: Path) -> int:
    _, rows, _ = read_csv_header_and_rows(path)
    return len(rows)


def normalize_candidate_rows_for_publish(target_rel: str, header: list[str], rows: list[list[str]]) -> list[list[str]]:
    if target_rel != DAILY_TARGET or "Status" not in header:
        return rows

    status_idx = header.index("Status")
    normalized_rows: list[list[str]] = []
    for row in rows:
        normalized = list(row)
        if status_idx < len(normalized) and normalized[status_idx].upper() in STAGING_DAILY_STATUSES:
            normalized[status_idx] = FORMAL_DAILY_STATUS
        normalized_rows.append(normalized)
    return normalized_rows


def validate_daily_price_publish_rows(
    header: list[str], rows: list[list[str]]
) -> None:
    required = {
        "Date",
        "Close",
        "BVPS_ref",
        "PB_daily",
        "DataSupportLevel",
        "Status",
    }
    missing = required - set(header)
    if missing:
        raise ValueError(
            "Daily-price publish is missing required fields: "
            + ", ".join(sorted(missing))
        )
    positions = {name: header.index(name) for name in required}
    seen: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        row_date = row[positions["Date"]] if positions["Date"] < len(row) else ""
        try:
            parsed_date = date.fromisoformat(row_date)
        except ValueError as exc:
            raise ValueError(
                f"Daily-price publish has invalid Date at row {row_number}: {row_date!r}"
            ) from exc
        if parsed_date.weekday() >= 5:
            raise ValueError(
                f"Daily-price publish refused: {row_date} is Saturday/Sunday"
            )
        if row_date in seen:
            raise ValueError(f"Daily-price candidate repeats Date {row_date}")
        seen.add(row_date)
        close = _decimal(row[positions["Close"]], field="Close", row_date=row_date)
        bvps = _decimal(row[positions["BVPS_ref"]], field="BVPS_ref", row_date=row_date)
        pb = _decimal(row[positions["PB_daily"]], field="PB_daily", row_date=row_date)
        if close <= 0 or bvps <= 0:
            raise ValueError(
                f"Daily-price publish refused: {row_date} has zero/negative price evidence"
            )
        expected_pb = Decimal(str(round(float(close) / float(bvps), 3)))
        if pb != expected_pb:
            raise ValueError(
                f"Daily-price PB mismatch for {row_date}: {pb} != {expected_pb}"
            )
        source_level = row[positions["DataSupportLevel"]].strip().upper()
        if source_level not in APPROVED_DAILY_PRICE_SOURCE_LEVELS:
            raise ValueError(
                "Daily-price publish refused: "
                f"{row_date} lacks approved TWSE/Owner trading-day evidence "
                f"({source_level or 'MISSING'})"
            )
        status = row[positions["Status"]].strip().upper()
        if status != FORMAL_DAILY_STATUS:
            raise ValueError(
                f"Daily-price publish refused: {row_date} status is not {FORMAL_DAILY_STATUS}"
            )


def row_key(target_rel: str, header: list[str], row: list[str]) -> str:
    def cell(name: str, fallback_index: int = 0) -> str:
        if name in header:
            index = header.index(name)
            return row[index] if index < len(row) else ""
        return row[fallback_index] if fallback_index < len(row) else ""

    if target_rel == MACRO_EVENT_TARGET:
        return "|".join([
            cell("Date"),
            cell("EventTitle"),
            cell("SourceUrl"),
        ])
    return cell("Date")


def actionability_violations(header: list[str], rows: list[list[str]]) -> list[str]:
    if "Actionable" not in header:
        return []
    idx = header.index("Actionable")
    violations: list[str] = []
    for row_index, row in enumerate(rows, start=2):
        value = row[idx] if idx < len(row) else ""
        if str(value).strip().lower() != "false":
            violations.append(f"row {row_index}: Actionable={value!r}")
    return violations


def source_tier_violations(header: list[str], rows: list[list[str]]) -> list[str]:
    if "SourceTier" not in header:
        return []
    idx = header.index("SourceTier")
    violations: list[str] = []
    for row_index, row in enumerate(rows, start=2):
        value = (row[idx] if idx < len(row) else "").strip().upper()
        if value not in ALLOWED_SOURCE_TIERS:
            violations.append(f"row {row_index}: SourceTier={value!r}")
    return violations


def append_candidate(candidate: Path, target: Path, target_rel: str) -> int:
    candidate_header, candidate_rows, _ = read_csv_header_and_rows(candidate)
    target_header, target_rows, _ = read_csv_header_and_rows(target)
    if candidate_header != target_header:
        raise ValueError(f"Schema mismatch: {candidate} does not match {target}.")
    if not candidate_rows:
        raise ValueError(f"{candidate} contains no candidate rows.")
    candidate_rows = normalize_candidate_rows_for_publish(target_rel, candidate_header, candidate_rows)
    if target_rel == DAILY_TARGET:
        validate_daily_price_publish_rows(candidate_header, candidate_rows)
    if target_rel in OBSERVATION_ONLY_TARGETS:
        actionable_errors = actionability_violations(candidate_header, candidate_rows)
        if actionable_errors:
            raise ValueError(f"Append refused: observation-only rows must keep Actionable=false ({actionable_errors}).")
        source_tier_errors = source_tier_violations(candidate_header, candidate_rows)
        if source_tier_errors:
            raise ValueError(f"Append refused: observation-only rows must have an approved SourceTier ({source_tier_errors}).")

    existing_by_key = {
        row_key(target_rel, target_header, row): row for row in target_rows if row
    }
    rows_to_append: list[list[str]] = []
    conflicting_keys: list[str] = []
    for row in candidate_rows:
        if not row:
            continue
        key = row_key(target_rel, candidate_header, row)
        existing = existing_by_key.get(key)
        if existing is None:
            rows_to_append.append(row)
        elif existing != row:
            conflicting_keys.append(key)
    if conflicting_keys:
        raise ValueError(
            f"Append refused: target already contains conflicting Date/Key {conflicting_keys}."
        )
    if not rows_to_append:
        return 0

    needs_newline = target.stat().st_size > 0 and target.read_bytes()[-1:] not in {b"\n", b"\r"}
    with target.open("a", encoding="utf-8", newline="") as handle:
        if needs_newline:
            handle.write("\n")
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerows(rows_to_append)
    return len(rows_to_append)


def resolve_generated_file(package_root: Path, generated: str) -> tuple[Path, str, str]:
    candidate = package_root / generated.replace("\\", "/")
    name = candidate.name
    if name == "2317_daily_price_candidate.csv":
        return candidate, DAILY_TARGET, "daily"
    if name == "macro_snapshot_candidate.csv":
        return candidate, MACRO_TARGET, "macro"
    if name == "macro_event_observations_candidate.csv":
        return candidate, MACRO_EVENT_TARGET, "macro_event_observations"
    if name == "fx_trend_observations_candidate.csv":
        return candidate, FX_TREND_TARGET, "fx_trend_observations"
    raise ValueError(f"Unsupported generated candidate: {generated}")


def manifest_has_target(package_root: Path, target_rel: str) -> bool:
    manifest = read_json(package_root / MANIFEST_PATH)
    entries = manifest.get("authoritativeFiles", []) + manifest.get("nonAuthoritativeFiles", [])
    return any(entry.get("path") == target_rel for entry in entries)


def status_score(status: str) -> int:
    normalized = (status or "").upper()
    if normalized == "PASS":
        return 100
    if normalized == "PASS_WITH_WARNINGS":
        return 85
    if normalized in {"FAIL", "FAILED", "ERROR"}:
        return 0
    return 50


def generated_dataset_flags(generated_files: list[str]) -> dict[str, bool]:
    return {
        "daily": any(Path(item.replace("\\", "/")).name == "2317_daily_price_candidate.csv" for item in generated_files),
        "macro": any(Path(item.replace("\\", "/")).name == "macro_snapshot_candidate.csv" for item in generated_files),
        "macro_event_observations": any(Path(item.replace("\\", "/")).name == "macro_event_observations_candidate.csv" for item in generated_files),
        "fx_trend_observations": any(Path(item.replace("\\", "/")).name == "fx_trend_observations_candidate.csv" for item in generated_files),
    }


def source_coverage_score(dry_run: dict[str, Any]) -> tuple[int, int, int, list[str]]:
    input_sources = dry_run.get("inputSources", {}) or {}
    source_meta = dry_run.get("sourceMeta", {}) or {}
    generated_files = dry_run.get("generatedFiles", []) or []
    datasets = generated_dataset_flags(generated_files)
    required_sources: list[tuple[str, str]] = []

    for source_name, source_value in input_sources.items():
        meta = source_meta.get(source_name, {})
        if "requiredForFormal" in meta:
            required = bool(meta.get("requiredForFormal"))
        elif source_name == "fed_prob":
            required = False
        elif source_name == "stock_price":
            required = datasets["daily"]
        else:
            required = True
        if required:
            required_sources.append((source_name, str(source_value)))

    if not required_sources:
        return 100, 0, 0, []

    missing = [
        name
        for name, value in required_sources
        if value.upper() in MISSING_SOURCE_VALUES
    ]
    available = len(required_sources) - len(missing)
    return round((available / len(required_sources)) * 100), available, len(required_sources), missing


def validation_score(validation_checks: list[dict[str, Any]]) -> int:
    if not validation_checks:
        return 50
    return round(sum(status_score(str(check.get("status", ""))) for check in validation_checks) / len(validation_checks))


def inspect_candidate_files(package_root: Path, generated_files: list[str]) -> tuple[list[dict[str, Any]], list[str], int]:
    diagnostics: list[dict[str, Any]] = []
    blockers: list[str] = []
    if not generated_files:
        return diagnostics, ["No generated candidate CSV files were declared."], 0

    for generated in generated_files:
        try:
            candidate_path, target_rel, dataset = resolve_generated_file(package_root, generated)
            target_path = package_root / target_rel
            item: dict[str, Any] = {
                "candidate": str(candidate_path),
                "target": target_rel,
                "dataset": dataset,
                "exists": candidate_path.exists(),
                "targetExists": target_path.exists(),
                "rows": 0,
                "schemaMatch": False,
                "duplicateKeys": [],
                "manifestEntry": False,
                "actionableFalse": None,
                "sourceTierValid": None,
            }
            if not item["exists"]:
                blockers.append(f"Candidate file missing: {generated}")
                diagnostics.append(item)
                continue
            if not item["targetExists"]:
                blockers.append(f"Formal target missing: {target_rel}")
                diagnostics.append(item)
                continue

            candidate_header, candidate_rows, _ = read_csv_header_and_rows(candidate_path)
            target_header, target_rows, _ = read_csv_header_and_rows(target_path)
            item["rows"] = len(candidate_rows)
            item["schemaMatch"] = candidate_header == target_header
            if not item["schemaMatch"]:
                blockers.append(f"Schema mismatch: {generated} -> {target_rel}")
            if item["rows"] <= 0:
                blockers.append(f"Candidate has no data rows: {generated}")

            existing_keys = {row_key(target_rel, target_header, row) for row in target_rows if row}
            duplicate_keys = [
                row_key(target_rel, candidate_header, row)
                for row in candidate_rows
                if row and row_key(target_rel, candidate_header, row) in existing_keys
            ]
            item["duplicateKeys"] = duplicate_keys
            if duplicate_keys:
                blockers.append(f"Append would duplicate Date/Key {duplicate_keys}: {target_rel}")

            if target_rel in OBSERVATION_ONLY_TARGETS:
                actionable_errors = actionability_violations(candidate_header, candidate_rows)
                item["actionableFalse"] = not actionable_errors
                if actionable_errors:
                    blockers.append(f"Observation-only candidate must keep Actionable=false: {generated} ({'; '.join(actionable_errors)})")
                source_tier_errors = source_tier_violations(candidate_header, candidate_rows)
                item["sourceTierValid"] = not source_tier_errors
                if source_tier_errors:
                    blockers.append(f"Observation-only candidate has invalid SourceTier: {generated} ({'; '.join(source_tier_errors)})")

            item["manifestEntry"] = manifest_has_target(package_root, target_rel)
            if not item["manifestEntry"]:
                blockers.append(f"Manifest has no target entry: {target_rel}")
            diagnostics.append(item)
        except Exception as exc:
            blockers.append(f"Candidate inspection failed for {generated}: {exc}")

    return diagnostics, blockers, 100 if diagnostics and not blockers else 0


def build_publish_readiness(package_root: Path, dry_run: dict[str, Any]) -> dict[str, Any]:
    generated_files = dry_run.get("generatedFiles", []) or []
    already_published_targets = dry_run.get("alreadyPublishedTargets", []) or []
    critical_missing = dry_run.get("criticalMissingFields")
    if critical_missing is None:
        critical_missing = dry_run.get("missingFields", []) or []
    optional_missing = dry_run.get("optionalMissingFields", []) or []
    unavailable_candidate_fields = dry_run.get("unavailableCandidateFields", []) or []

    source_score, source_available, source_total, missing_sources = source_coverage_score(dry_run)
    checks_score = validation_score(dry_run.get("validationChecks", []) or [])
    no_action_required = (
        bool(dry_run.get("noPublishRequired"))
        or bool(already_published_targets)
    ) and not generated_files
    if no_action_required:
        candidate_diagnostics, candidate_blockers, candidate_score = [], [], 100
    else:
        candidate_diagnostics, candidate_blockers, candidate_score = inspect_candidate_files(package_root, generated_files)
    completeness_score = 100 if not critical_missing else max(0, 100 - len(critical_missing) * 25)
    score = round(
        source_score * 0.30
        + checks_score * 0.25
        + candidate_score * 0.25
        + completeness_score * 0.20
    )

    blockers = list(candidate_blockers)
    if critical_missing:
        blockers.append(f"Missing critical fields: {', '.join(critical_missing)}")
    if missing_sources:
        blockers.append(f"Missing required sources: {', '.join(missing_sources)}")
    if score < MIN_PUBLISH_SCORE:
        blockers.append(f"Readiness score {score}% is below required {MIN_PUBLISH_SCORE}%.")

    return {
        "score": score,
        "threshold": MIN_PUBLISH_SCORE,
        "allowed": not blockers,
        "blockers": blockers,
        "sourceCoverageScore": source_score,
        "sourceAvailable": source_available,
        "sourceTotal": source_total,
        "validationScore": checks_score,
        "candidateFileScore": candidate_score,
        "noActionRequired": no_action_required,
        "alreadyPublishedTargets": already_published_targets,
        "completenessScore": completeness_score,
        "candidateDiagnostics": candidate_diagnostics,
        "criticalMissingFields": critical_missing,
        "optionalMissingFields": optional_missing,
        "unavailableCandidateFields": unavailable_candidate_fields,
        "warningsZh": dry_run.get("dataQualityWarningsZh", []) or [],
    }


def print_readiness(readiness: dict[str, Any]) -> None:
    print(f"Readiness   : {readiness['score']}% / required {readiness['threshold']}%")
    print(f"Sources     : {readiness['sourceCoverageScore']}% ({readiness['sourceAvailable']}/{readiness['sourceTotal']} required sources available)")
    print(f"Validation  : {readiness['validationScore']}%")
    print(f"Candidates  : {readiness['candidateFileScore']}%")
    print(f"NO_ACTION_REQUIRED: {'YES' if readiness.get('noActionRequired') else 'NO'}")
    if readiness.get("alreadyPublishedTargets"):
        print(f"Already published: {', '.join(readiness['alreadyPublishedTargets'])}")
    print(f"Completeness: {readiness['completenessScore']}%")
    for item in readiness["candidateDiagnostics"]:
        duplicate_text = ", ".join(item["duplicateKeys"]) if item["duplicateKeys"] else "none"
        print(
            "Candidate   : "
            f"{Path(item['candidate']).name} -> {item['target']} | "
            f"exists={item['exists']} rows={item['rows']} "
            f"schema={item['schemaMatch']} duplicates={duplicate_text} "
            f"manifest={item['manifestEntry']} "
            f"actionableFalse={item.get('actionableFalse', 'n/a')} "
            f"sourceTierValid={item.get('sourceTierValid', 'n/a')}"
        )
    optional = readiness["optionalMissingFields"]
    unavailable = readiness["unavailableCandidateFields"]
    warnings = readiness["warningsZh"]
    print(f"Optional missing fields: {', '.join(optional) if optional else 'none'}")
    print(f"Unavailable candidate fields: {', '.join(unavailable) if unavailable else 'none'}")
    if warnings:
        print("Chinese data notes:")
        for warning in warnings:
            print(f"  - {warning}")
    if readiness["blockers"]:
        print("Blockers    :")
        for blocker in readiness["blockers"]:
            print(f"  - {blocker}")
    if readiness.get("noActionRequired"):
        print("PUBLISH_ALLOWED: NO_ACTION_REQUIRED")
    else:
        print(f"PUBLISH_ALLOWED: {'YES' if readiness['allowed'] else 'NO'}")


def update_manifest(package_root: Path, touched_targets: list[str], approval_note: str) -> None:
    manifest_path = package_root / MANIFEST_PATH
    manifest = read_json(manifest_path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest["approvedAt"] = now[:10]
    manifest["approvalSource"] = f"{manifest.get('approvalSource', '')}; {approval_note}".strip("; ")

    entries = manifest.get("authoritativeFiles", []) + manifest.get("nonAuthoritativeFiles", [])
    for target_rel in touched_targets:
        target_path = package_root / target_rel
        digest = sha256_file(target_path)
        size = target_path.stat().st_size
        rows = row_count(target_path)
        updated = False
        for entry in entries:
            if entry.get("path") != target_rel:
                continue
            entry["sha256"] = digest
            entry["fileSizeBytes"] = size
            entry["rowCount"] = rows
            entry["lastPublishedAt"] = now
            entry["publishApprovalZh"] = "Owner approved append; MARKET INTELLIGENCE sidecar remains observation only; actionable:false."
            if target_rel == DAILY_TARGET:
                _, data_rows, _ = read_csv_header_and_rows(target_path)
                if data_rows:
                    entry.setdefault("dateRange", {})["end"] = data_rows[-1][0]
            updated = True
        if not updated:
            raise ValueError(f"Manifest has no entry for {target_rel}.")
    write_json(manifest_path, manifest)


def sync_runtime_snapshot_after_publish(
    package_root: Path,
    candidate_date: str,
    touched_targets: list[str],
    published_at: str,
) -> bool:
    runtime_path = package_root / "runtime" / "warroom_realtime_snapshot.json"
    if not runtime_path.exists():
        return False

    snapshot = read_json(runtime_path)
    if str(snapshot.get("candidateDate", "")) != str(candidate_date):
        return False

    unique_targets = list(dict.fromkeys(touched_targets))
    snapshot["runtimeOnly"] = True
    snapshot["runtimeOnlyZh"] = "runtime 已同步正式 CSV；戰情室判讀以正式 CSV 為準。"
    snapshot["productionCsvModified"] = True
    snapshot["productionCsvModifiedZh"] = "Owner 已核准發布，正式 CSV 已 append。"
    snapshot["ownerConfirmationRequired"] = False
    snapshot["ownerConfirmationRequiredZh"] = "Owner 已核准發布；此 runtime snapshot 已同步正式 CSV。"
    snapshot["generatedFiles"] = []
    snapshot["alreadyPublishedTargets"] = unique_targets
    snapshot["formalSynced"] = True
    snapshot["formalSyncedZh"] = "runtime 對應日期已寫入正式 CSV；UI 應以正式 CSV 為準。"
    snapshot["formalPublishedAt"] = published_at

    daily_row = snapshot.get("dailyRow")
    if DAILY_TARGET in unique_targets and isinstance(daily_row, dict):
        status = str(daily_row.get("Status", "")).upper()
        if status in STAGING_DAILY_STATUSES:
            daily_row["Status"] = FORMAL_DAILY_STATUS

    write_json(runtime_path, snapshot)
    return True


def sync_news_scan_snapshot_after_publish(
    package_root: Path,
    candidate_date: str,
    touched_targets: list[str],
    published_at: str,
) -> bool:
    if MACRO_EVENT_TARGET not in touched_targets:
        return False

    runtime_path = package_root / "runtime" / "warroom_news_scan_snapshot.json"
    if not runtime_path.exists():
        return False

    snapshot = read_json(runtime_path)
    if str(snapshot.get("candidateDate", "")) != str(candidate_date):
        return False

    snapshot["ownerConfirmationRequired"] = False
    snapshot["ownerConfirmationRequiredZh"] = "Owner approved append for macro_event_observations.csv; news scan runtime is formal-synced."
    snapshot["ownerReviewRequired"] = False
    snapshot["ownerReviewRequiredZh"] = "Owner publish completed; event rows are formal-synced and no longer block Launcher gate."
    snapshot["holdUnderReview"] = False
    snapshot["holdUnderReviewZh"] = "Owner publish completed; HOLD_UNDER_REVIEW visual warning is cleared. HOLD main IC remains unchanged."
    snapshot["generatedFiles"] = []
    snapshot["alreadyPublishedTargets"] = list(dict.fromkeys(snapshot.get("alreadyPublishedTargets", []) + [MACRO_EVENT_TARGET]))
    snapshot["formalSynced"] = True
    snapshot["formalPublishedAt"] = published_at
    write_json(runtime_path, snapshot)
    return True


def sync_event_review_state_after_publish(
    package_root: Path,
    candidate_date: str,
    touched_targets: list[str],
    published_at: str,
) -> bool:
    if MACRO_EVENT_TARGET not in touched_targets:
        return False

    review_path = package_root / "runtime" / "warroom_event_review_state.json"
    if not review_path.exists():
        return False

    review = read_json(review_path)
    if str(review.get("candidateDate", "")) not in {"", str(candidate_date)}:
        return False

    pending_reviews = review.get("pendingReviews", []) or []
    acknowledged_reviews = []
    for item in pending_reviews:
        if not isinstance(item, dict):
            continue
        updated = dict(item)
        updated["reviewStatus"] = "OWNER_PUBLISHED"
        updated["reviewConclusionZh"] = "Owner 已正式發布事件旁路 CSV；此事件不再阻擋 Launcher gate，且不改 HOLD 主 IC。"
        updated["formalPublishedAt"] = published_at
        acknowledged_reviews.append(updated)

    review["status"] = "OWNER_PUBLISHED"
    review["ownerAckRequired"] = False
    review["pendingReviewsBeforePublish"] = pending_reviews
    review["pendingReviews"] = []
    review["acknowledgedReviews"] = acknowledged_reviews
    review["formalSynced"] = True
    review["formalPublishedAt"] = published_at
    review["reviewConclusionZh"] = "Owner 已正式發布事件旁路 CSV；新聞/事件重審提示已結案，不直接改 HOLD。"
    write_json(review_path, review)
    return True


def sync_dry_run_after_publish(dry_run_path: Path, touched_targets: list[str], published_at: str) -> bool:
    if not dry_run_path.exists():
        return False

    dry_run = read_json(dry_run_path)
    previous_generated = dry_run.get("generatedFiles", []) or []
    previous_targets = dry_run.get("alreadyPublishedTargets", []) or []
    dry_run["generatedFilesBeforePublish"] = previous_generated
    dry_run["generatedFiles"] = []
    dry_run["alreadyPublishedTargets"] = list(dict.fromkeys([*previous_targets, *touched_targets]))
    dry_run["ownerConfirmationRequired"] = False
    dry_run["ownerConfirmationRequiredZh"] = "Owner 已正式發布候選 CSV；本 DRY_RUN 已同步正式資料，不再要求發布確認。"
    dry_run["formalSynced"] = True
    dry_run["formalSyncedZh"] = "Owner 已核准發布；候選 CSV 已寫入正式 CSV，重跑發布流程應顯示 NO_ACTION_REQUIRED。"
    dry_run["formalPublishedAt"] = published_at
    write_json(dry_run_path, dry_run)
    return True


def _decimal(value: str, *, field: str, row_date: str) -> Decimal:
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid {field} for {row_date}: {value!r}") from exc
    if not parsed.is_finite():
        raise ValueError(f"Non-finite {field} for {row_date}: {value!r}")
    return parsed


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load existing module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _read_twse_month_closes(raw_path: Path) -> dict[str, Decimal]:
    rows = list(csv.reader(raw_path.read_text(encoding="cp950").splitlines()))
    if not rows or "2317" not in "".join(rows[0]):
        raise ValueError(f"TWSE receipt is not for ticker 2317: {raw_path}")
    closes: dict[str, Decimal] = {}
    for row in rows[2:]:
        if not row or len(row) < 7 or len(row[0]) != 9 or row[0][3] != "/":
            continue
        try:
            roc_year, month, day = (int(part) for part in row[0].split("/"))
        except ValueError:
            continue
        iso_date = f"{roc_year + 1911:04d}-{month:02d}-{day:02d}"
        if iso_date in closes:
            raise ValueError(f"Duplicate TWSE date: {iso_date}")
        closes[iso_date] = _decimal(
            row[6].replace(",", ""), field="TWSE Close", row_date=iso_date
        )
    return closes


def validate_remediation_candidate(
    package_root: Path,
    candidate_path: Path,
    *,
    require_old_formal_sha: bool = True,
) -> dict[str, Any]:
    package_root = package_root.resolve()
    candidate_path = candidate_path.resolve()
    formal_path = package_root / DAILY_TARGET
    expected_candidate = (
        package_root
        / "runtime"
        / "research_plugin"
        / "candidates"
        / REMEDIATION_CANDIDATE_NAME
    ).resolve()
    if candidate_path != expected_candidate:
        raise ValueError(f"Remediation candidate path is not approved: {candidate_path}")
    if candidate_path.name != REMEDIATION_CANDIDATE_NAME:
        raise ValueError("Remediation candidate filename is not approved")
    candidate_sha = sha256_file(candidate_path)
    if candidate_sha != REMEDIATION_CANDIDATE_SHA256:
        raise ValueError(f"Remediation candidate SHA mismatch: {candidate_sha}")
    formal_sha = sha256_file(formal_path)
    if require_old_formal_sha and formal_sha != REMEDIATION_FORMAL_OLD_SHA256:
        raise ValueError(f"Formal daily price SHA mismatch: {formal_sha}")

    candidate_header, candidate_rows, _ = read_csv_header_and_rows(candidate_path)
    formal_header, _, _ = read_csv_header_and_rows(formal_path)
    if candidate_header != formal_header:
        raise ValueError("Remediation candidate schema does not match formal target")
    if candidate_header != [
        "Date",
        "Close",
        "QuarterKey",
        "BVPS_ref",
        "PB_daily",
        "DataSupportLevel",
        "Status",
    ]:
        raise ValueError(f"Unexpected daily-price schema: {candidate_header}")
    if len(candidate_rows) != REMEDIATION_EXPECTED_ROWS:
        raise ValueError(
            f"Remediation candidate must have {REMEDIATION_EXPECTED_ROWS} rows; "
            f"got {len(candidate_rows)}"
        )

    dates = [row[0] for row in candidate_rows]
    if dates != sorted(dates) or len(dates) != len(set(dates)):
        raise ValueError("Remediation candidate dates must be unique and strictly increasing")
    if REMEDIATION_REMOVED_DATES & set(dates):
        raise ValueError("Remediation candidate still contains removed dates")

    rows_by_date = {row[0]: dict(zip(candidate_header, row)) for row in candidate_rows}
    for repair_date, expected_close in REMEDIATION_EXPECTED_REPAIRS.items():
        row = rows_by_date.get(repair_date)
        if row is None:
            raise ValueError(f"Missing remediation date: {repair_date}")
        close = _decimal(row["Close"], field="Close", row_date=repair_date)
        bvps = _decimal(row["BVPS_ref"], field="BVPS_ref", row_date=repair_date)
        pb = _decimal(row["PB_daily"], field="PB_daily", row_date=repair_date)
        if close != expected_close:
            raise ValueError(
                f"Candidate Close mismatch for {repair_date}: {close} != {expected_close}"
            )
        expected_pb = Decimal(str(round(float(close) / float(bvps), 3)))
        if pb != expected_pb:
            raise ValueError(
                f"Candidate PB_daily mismatch for {repair_date}: {pb} != {expected_pb}"
            )
        if row["DataSupportLevel"] != "OFFICIAL_TWSE_A1" or row["Status"] != "OK":
            raise ValueError(f"Invalid remediation provenance/status for {repair_date}")

    backfill_root = (
        package_root
        / "runtime"
        / "research_plugin"
        / "market_activity_backfill"
        / "P1008-TWSE-2317-20260414-20260717-20260718"
        / "receipts"
    )
    twse_closes: dict[str, Decimal] = {}
    twse_sources: list[dict[str, str]] = []
    for month in ("2026-06", "2026-07"):
        raw_path = backfill_root / f"{month}.twse.raw.csv"
        receipt_path = backfill_root / f"{month}.receipt.json"
        receipt = read_json(receipt_path)
        raw_sha = sha256_file(raw_path)
        if receipt.get("status") != "SUCCESS" or receipt.get("raw_artifact_sha256") != raw_sha:
            raise ValueError(f"TWSE raw receipt validation failed for {month}")
        for source_date, close in _read_twse_month_closes(raw_path).items():
            if source_date in twse_closes:
                raise ValueError(f"TWSE cross-month duplicate date: {source_date}")
            twse_closes[source_date] = close
        twse_sources.append(
            {
                "month": month,
                "raw_path": str(raw_path.resolve()),
                "raw_sha256": raw_sha,
                "receipt_path": str(receipt_path.resolve()),
                "receipt_sha256": sha256_file(receipt_path),
            }
        )
    for repair_date, expected_close in REMEDIATION_EXPECTED_REPAIRS.items():
        if twse_closes.get(repair_date) != expected_close:
            raise ValueError(f"Saved TWSE Close mismatch for {repair_date}")

    return {
        "candidate_path": str(candidate_path),
        "candidate_sha256": candidate_sha,
        "formal_path": str(formal_path.resolve()),
        "formal_sha256": formal_sha,
        "rows": len(candidate_rows),
        "date_range": {"start": dates[0], "end": dates[-1]},
        "repairs_verified": len(REMEDIATION_EXPECTED_REPAIRS),
        "removed_dates_verified": sorted(REMEDIATION_REMOVED_DATES),
        "twse_sources": twse_sources,
        "pb_formula": 'round(Close / BVPS_ref, 3)',
        "actionable": False,
    }


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    digest = hashlib.sha256(content).hexdigest()[:12]
    temporary = path.with_name(f".{path.name}.remediation-{digest}.tmp")
    if temporary.exists():
        raise FileExistsError(temporary)
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    _atomic_write_bytes(
        path,
        (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def _build_remediation_manifest_bytes(
    package_root: Path,
    candidate_path: Path,
    published_at: str,
) -> bytes:
    manifest_path = package_root / MANIFEST_PATH
    manifest = read_json(manifest_path)
    entries = manifest.get("authoritativeFiles", [])
    entry = next((item for item in entries if item.get("path") == DAILY_TARGET), None)
    if entry is None:
        raise ValueError(f"Manifest has no authoritative entry for {DAILY_TARGET}")
    candidate_header, candidate_rows, _ = read_csv_header_and_rows(candidate_path)
    if candidate_header != entry.get("columns"):
        raise ValueError("Manifest daily-price schema does not match remediation candidate")
    manifest["approvedAt"] = published_at[:10]
    note = (
        "Owner-approved 2026-07-18 price authority remediation via "
        "owner_publish_csv_v2.py replace mode"
    )
    manifest["approvalSource"] = f"{manifest.get('approvalSource', '')}; {note}".strip("; ")
    entry["sha256"] = sha256_file(candidate_path)
    entry["fileSizeBytes"] = candidate_path.stat().st_size
    entry["rowCount"] = len(candidate_rows)
    entry["lastPublishedAt"] = published_at
    entry["publishApprovalZh"] = (
        "Owner核准價格authority remediation完整替換；TWSE日期、Close與PB_daily已驗證。"
    )
    entry.setdefault("dateRange", {})["start"] = candidate_rows[0][0]
    entry.setdefault("dateRange", {})["end"] = candidate_rows[-1][0]
    entry["lastRemediation"] = {
        "candidateSha256": REMEDIATION_CANDIDATE_SHA256,
        "previousFormalSha256": REMEDIATION_FORMAL_OLD_SHA256,
        "publishedAt": published_at,
        "publisher": "owner_publish_csv_v2.py",
        "mode": "REMEDIATION_REPLACE",
        "actionable": False,
    }
    return (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _runtime_content_counts(runtime_db: Path) -> dict[str, int]:
    connection = sqlite3.connect(f"file:{runtime_db.as_posix()}?mode=ro", uri=True)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        protected_content_tables = (
            "subjects",
            "metric_definitions",
            "sources",
            "raw_artifacts",
            "observations",
            "derived_metrics",
            "derived_metric_inputs",
            "validation_results",
            "data_conflicts",
            "data_conflict_candidates",
            "audit_logs",
            "pipeline_runs",
        )
        return {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in protected_content_tables
            if table in tables
        }
    finally:
        connection.close()


def _copy_runtime_history(source_db: Path, staged_db: Path) -> dict[str, int]:
    copied: dict[str, int] = {}
    source = sqlite3.connect(f"file:{source_db.as_posix()}?mode=ro", uri=True)
    target = sqlite3.connect(staged_db)
    try:
        source_tables = {
            row[0]
            for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        target_tables = {
            row[0]
            for row in target.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in ("backup_records", "migration_runs", "audit_logs", "pipeline_runs"):
            if table not in source_tables or table not in target_tables:
                continue
            columns = [row[1] for row in source.execute(f'PRAGMA table_info("{table}")')]
            target_columns = [row[1] for row in target.execute(f'PRAGMA table_info("{table}")')]
            if columns != target_columns:
                raise ValueError(f"Runtime history schema mismatch for {table}")
            rows = source.execute(f'SELECT * FROM "{table}"').fetchall()
            if rows:
                placeholders = ",".join("?" for _ in columns)
                target.executemany(
                    f'INSERT OR IGNORE INTO "{table}" VALUES ({placeholders})', rows
                )
            copied[table] = len(rows)
        target.commit()
    finally:
        source.close()
        target.close()
    return copied


def _build_runtime_candidate(
    package_root: Path,
    candidate_path: Path,
    runtime_db: Path,
    output_dir: Path,
) -> dict[str, Any]:
    counts = _runtime_content_counts(runtime_db)
    nonempty = {name: count for name, count in counts.items() if count}
    if nonempty:
        raise ValueError(
            "Runtime SQLite contains formal analytical content that the approved rebuild "
            f"would replace: {nonempty}"
        )

    authority_input = output_dir / "authority_input"
    authority_input.mkdir(parents=True, exist_ok=False)
    shutil.copy2(package_root / "data" / "2317_master_v9.csv", authority_input / "2317_master_v9.csv")
    shutil.copy2(package_root / "data" / "macro_snapshot.csv", authority_input / "macro_snapshot.csv")
    shutil.copy2(candidate_path, authority_input / "2317_daily_price.csv")

    migrator_path = package_root / "db" / "tools" / "p2_02_legacy_migrator.py"
    migrator = _load_module("p1008_price_remediation_legacy_migrator", migrator_path)
    migrator.DATA_DIR = authority_input
    runtime_build_dir = output_dir / "runtime_rebuild"
    summary = migrator.run_migration(runtime_build_dir, runtime_db)
    staged_db = runtime_build_dir / "warroom_p2_02_dryrun.sqlite3"
    daily_summary = next(
        (item for item in summary.get("datasets", []) if item.get("dataset") == "DAILY_PRICE"),
        None,
    )
    if daily_summary is None:
        daily_summary = next(
            (item for item in summary.get("datasets", []) if item.get("dataset_code") == "DAILY_PRICE"),
            None,
        )
    if daily_summary is None or int(daily_summary.get("valid_rows", -1)) != REMEDIATION_EXPECTED_ROWS:
        raise ValueError(f"Runtime rebuild did not validate 110 daily rows: {daily_summary}")

    copied_history = _copy_runtime_history(runtime_db, staged_db)
    connection = sqlite3.connect(staged_db)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        daily_rows = connection.execute(
            "SELECT COUNT(*) FROM legacy_source_rows "
            "WHERE dataset_code='DAILY_PRICE' AND row_status='VALID'"
        ).fetchone()[0]
        if integrity != "ok" or foreign_keys or daily_rows != REMEDIATION_EXPECTED_ROWS:
            raise ValueError(
                f"Runtime candidate validation failed: integrity={integrity}, "
                f"foreign_keys={len(foreign_keys)}, daily_rows={daily_rows}"
            )
    finally:
        connection.close()
    return {
        "path": str(staged_db.resolve()),
        "sha256": sha256_file(staged_db),
        "daily_source_rows": REMEDIATION_EXPECTED_ROWS,
        "integrity_check": "PASS",
        "foreign_key_check": "PASS",
        "copied_history_rows": copied_history,
        "migration_summary": summary,
    }


def _validate_published_runtime(runtime_db: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{runtime_db.as_posix()}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        daily_rows = connection.execute(
            "SELECT COUNT(*) FROM legacy_source_rows "
            "WHERE dataset_code='DAILY_PRICE' AND row_status='VALID'"
        ).fetchone()[0]
    finally:
        connection.close()
    if integrity != "ok" or foreign_keys or daily_rows != REMEDIATION_EXPECTED_ROWS:
        raise ValueError("Published Runtime SQLite validation failed")
    return {
        "sha256": sha256_file(runtime_db),
        "integrity_check": "PASS",
        "foreign_key_check": "PASS",
        "daily_source_rows": daily_rows,
    }


def run_price_remediation(
    package_root: Path,
    candidate_path: Path,
    runtime_db: Path,
    output_dir: Path,
    *,
    publish: bool,
    dry_run_journal: Path | None = None,
) -> dict[str, Any]:
    package_root = package_root.resolve()
    candidate_path = candidate_path.resolve()
    runtime_db = runtime_db.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"Remediation output already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    journal_path = output_dir / "PUBLISH_JOURNAL.json"
    published_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    validation = validate_remediation_candidate(package_root, candidate_path)
    pre_hashes = {
        DAILY_TARGET: sha256_file(package_root / DAILY_TARGET),
        MANIFEST_PATH: sha256_file(package_root / MANIFEST_PATH),
        "runtime_sqlite": sha256_file(runtime_db),
    }
    if dry_run_journal is not None:
        approved_dry_run = read_json(dry_run_journal)
        if approved_dry_run.get("status") != "DRY_RUN_PASS":
            raise ValueError("Approved remediation dry-run journal is not PASS")
        if approved_dry_run.get("candidate_sha256") != REMEDIATION_CANDIDATE_SHA256:
            raise ValueError("Dry-run candidate SHA mismatch")
        if approved_dry_run.get("pre_hashes") != pre_hashes:
            raise ValueError("Formal inputs changed after remediation dry-run")

    staged_root = output_dir / "staged"
    staged_data = staged_root / "data"
    staged_data.mkdir(parents=True)
    staged_price = staged_data / "2317_daily_price.csv"
    shutil.copy2(candidate_path, staged_price)
    staged_manifest = staged_data / "CSV_AUTHORITY_MANIFEST.json"
    staged_manifest.write_bytes(
        _build_remediation_manifest_bytes(package_root, candidate_path, published_at)
    )
    runtime_result = _build_runtime_candidate(
        package_root, candidate_path, runtime_db, staged_root
    )
    staged_runtime = Path(runtime_result["path"])
    staged_hashes = {
        DAILY_TARGET: sha256_file(staged_price),
        MANIFEST_PATH: sha256_file(staged_manifest),
        "runtime_sqlite": sha256_file(staged_runtime),
    }
    journal: dict[str, Any] = {
        "mode": "REMEDIATION_REPLACE",
        "publish_requested": publish,
        "status": "STAGED",
        "created_at_utc": published_at,
        "candidate_sha256": REMEDIATION_CANDIDATE_SHA256,
        "pre_hashes": pre_hashes,
        "staged_hashes": staged_hashes,
        "validation": validation,
        "runtime_validation": runtime_result,
        "steps": ["VALIDATED", "STAGED"],
        "owner_accepted_environment_exception": "TemporaryDirectory PermissionError",
        "http_calls": 0,
        "openai_calls": 0,
        "actionable": False,
    }
    if not publish:
        journal["status"] = "DRY_RUN_PASS"
        journal["steps"].append("DRY_RUN_VERIFIED")
        _atomic_write_json(journal_path, journal)
        return journal

    backup_dir = output_dir / "backup"
    (backup_dir / "data").mkdir(parents=True)
    shutil.copy2(package_root / DAILY_TARGET, backup_dir / DAILY_TARGET)
    shutil.copy2(package_root / MANIFEST_PATH, backup_dir / MANIFEST_PATH)
    shutil.copy2(runtime_db, backup_dir / "warroom.sqlite3")
    backup_hashes = {
        DAILY_TARGET: sha256_file(backup_dir / DAILY_TARGET),
        MANIFEST_PATH: sha256_file(backup_dir / MANIFEST_PATH),
        "runtime_sqlite": sha256_file(backup_dir / "warroom.sqlite3"),
    }
    if backup_hashes != pre_hashes:
        raise ValueError("Remediation backup hashes do not match pre-publish hashes")
    journal["backup_dir"] = str(backup_dir)
    journal["backup_hashes"] = backup_hashes
    journal["status"] = "BACKUP_VERIFIED"
    journal["steps"].append("BACKUP_VERIFIED")
    _atomic_write_json(journal_path, journal)

    targets = {
        DAILY_TARGET: package_root / DAILY_TARGET,
        MANIFEST_PATH: package_root / MANIFEST_PATH,
        "runtime_sqlite": runtime_db,
    }
    staged = {
        DAILY_TARGET: staged_price,
        MANIFEST_PATH: staged_manifest,
        "runtime_sqlite": staged_runtime,
    }
    try:
        for key in (DAILY_TARGET, MANIFEST_PATH, "runtime_sqlite"):
            _atomic_write_bytes(targets[key], staged[key].read_bytes())
            journal["steps"].append(f"REPLACED:{key}")
            _atomic_write_json(journal_path, journal)

        published_validation = validate_remediation_candidate(
            package_root, candidate_path, require_old_formal_sha=False
        )
        if sha256_file(package_root / DAILY_TARGET) != REMEDIATION_CANDIDATE_SHA256:
            raise ValueError("Published daily-price SHA mismatch")
        manifest = read_json(package_root / MANIFEST_PATH)
        entry = next(
            item
            for item in manifest.get("authoritativeFiles", [])
            if item.get("path") == DAILY_TARGET
        )
        if (
            entry.get("sha256") != REMEDIATION_CANDIDATE_SHA256
            or entry.get("rowCount") != REMEDIATION_EXPECTED_ROWS
        ):
            raise ValueError("Published authority manifest validation failed")
        runtime_validation = _validate_published_runtime(runtime_db)
        post_hashes = {
            DAILY_TARGET: sha256_file(package_root / DAILY_TARGET),
            MANIFEST_PATH: sha256_file(package_root / MANIFEST_PATH),
            "runtime_sqlite": sha256_file(runtime_db),
        }
        journal.update(
            {
                "status": "PUBLISHED",
                "published_at_utc": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "post_hashes": post_hashes,
                "published_validation": published_validation,
                "published_runtime_validation": runtime_validation,
                "rollback_available": True,
                "rollback_performed": False,
            }
        )
        journal["steps"].append("POST_PUBLISH_VERIFIED")
        _atomic_write_json(journal_path, journal)
        return journal
    except Exception as publish_error:
        rollback_errors: list[str] = []
        for key, backup_path in (
            (DAILY_TARGET, backup_dir / DAILY_TARGET),
            (MANIFEST_PATH, backup_dir / MANIFEST_PATH),
            ("runtime_sqlite", backup_dir / "warroom.sqlite3"),
        ):
            try:
                _atomic_write_bytes(targets[key], backup_path.read_bytes())
            except Exception as rollback_error:
                rollback_errors.append(f"{key}: {rollback_error}")
        restored_hashes = {
            key: sha256_file(path) for key, path in targets.items()
        }
        rollback_ok = not rollback_errors and restored_hashes == pre_hashes
        journal.update(
            {
                "status": "ROLLED_BACK" if rollback_ok else "ROLLBACK_FAILED",
                "publish_error": str(publish_error),
                "rollback_errors": rollback_errors,
                "restored_hashes": restored_hashes,
                "rollback_performed": True,
                "rollback_verified": rollback_ok,
            }
        )
        _atomic_write_json(journal_path, journal)
        if not rollback_ok:
            raise RuntimeError(
                f"Remediation publish failed and rollback was incomplete: {journal}"
            ) from publish_error
        raise RuntimeError("Remediation publish failed; all targets restored") from publish_error


def _parse_twse_market_activity(package_root: Path) -> tuple[bytes, dict[str, Any]]:
    price_path = package_root / DAILY_TARGET
    if sha256_file(price_path) != MARKET_ACTIVITY_PRICE_SHA256:
        raise ValueError("Market-activity publish requires the approved remediated price authority")
    price_header, price_rows, _ = read_csv_header_and_rows(price_path)
    if "Date" not in price_header or "Close" not in price_header:
        raise ValueError("Price authority has no Date/Close columns")
    date_index = price_header.index("Date")
    close_index = price_header.index("Close")
    price_by_date: dict[str, Decimal] = {}
    for row in price_rows:
        row_date = row[date_index]
        if row_date in price_by_date:
            raise ValueError(f"Duplicate price authority date: {row_date}")
        price_by_date[row_date] = _decimal(
            row[close_index], field="Price Close", row_date=row_date
        )

    receipt_root = (
        package_root
        / "runtime"
        / "research_plugin"
        / "market_activity_backfill"
        / "P1008-TWSE-2317-20260414-20260717-20260718"
        / "receipts"
    )
    twse_by_date: dict[str, dict[str, Any]] = {}
    source_receipts: list[dict[str, Any]] = []
    for month, approved in MARKET_ACTIVITY_RECEIPTS.items():
        receipt_path = receipt_root / f"{month}.receipt.json"
        raw_path = receipt_root / f"{month}.twse.raw.csv"
        receipt_sha = sha256_file(receipt_path)
        raw_sha = sha256_file(raw_path)
        if receipt_sha != approved["receipt_sha256"] or raw_sha != approved["raw_sha256"]:
            raise ValueError(f"Approved TWSE artifact SHA mismatch for {month}")
        receipt = read_json(receipt_path)
        source_url = str(receipt.get("request_url", ""))
        expected_url = (
            "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?"
            f"date={month.replace('-', '')}01&stockNo=2317&response=csv"
        )
        if receipt.get("status") != "SUCCESS" or source_url != expected_url:
            raise ValueError(f"TWSE receipt status/source validation failed for {month}")
        raw_rows = list(csv.reader(raw_path.read_text(encoding="cp950").splitlines()))
        parsed_count = 0
        for raw in raw_rows[2:]:
            if not raw or len(raw) < 9 or "/" not in raw[0]:
                continue
            try:
                roc_year, raw_month, raw_day = (int(part) for part in raw[0].split("/"))
                trade_date = f"{roc_year + 1911:04d}-{raw_month:02d}-{raw_day:02d}"
            except ValueError as exc:
                raise ValueError(f"Invalid TWSE date in {month}: {raw[0]!r}") from exc
            if not trade_date.startswith(month + "-"):
                raise ValueError(f"TWSE row month mismatch: {trade_date} vs {month}")
            if trade_date in twse_by_date:
                raise ValueError(f"Duplicate TWSE trade date: {trade_date}")
            integer_values: list[int] = []
            for field_name, source_value in (
                ("trade_volume", raw[1]),
                ("trade_value", raw[2]),
                ("transaction_count", raw[8]),
            ):
                normalized = source_value.replace(",", "").strip()
                if not normalized.isdigit() or int(normalized) < 0:
                    raise ValueError(f"Invalid {field_name} for {trade_date}")
                integer_values.append(int(normalized))
            close = _decimal(
                raw[6].replace(",", ""), field="TWSE Close", row_date=trade_date
            )
            twse_by_date[trade_date] = {
                "date": trade_date,
                "stock_id": "2317",
                "trade_volume": integer_values[0],
                "trade_value": integer_values[1],
                "transaction_count": integer_values[2],
                "source_url": source_url,
                "source_month": month,
                "close": close,
            }
            parsed_count += 1
        if parsed_count != int(receipt.get("parsed_row_count", -1)):
            raise ValueError(f"TWSE parsed row count mismatch for {month}")
        source_receipts.append(
            {
                "month": month,
                "receipt_path": str(receipt_path.resolve()),
                "receipt_sha256": receipt_sha,
                "raw_path": str(raw_path.resolve()),
                "raw_sha256": raw_sha,
                "parsed_rows": parsed_count,
                "source_url": source_url,
            }
        )

    common_dates = sorted(set(price_by_date) & set(twse_by_date))
    close_mismatches = [
        {
            "date": row_date,
            "price_close": str(price_by_date[row_date]),
            "twse_close": str(twse_by_date[row_date]["close"]),
        }
        for row_date in common_dates
        if price_by_date[row_date] != twse_by_date[row_date]["close"]
    ]
    if close_mismatches:
        raise ValueError(f"Price/TWSE Close mismatch: {close_mismatches}")
    if len(common_dates) < MARKET_ACTIVITY_EXPECTED_ROWS:
        raise ValueError("Fewer than 60 price/TWSE common trade dates")
    selected_dates = common_dates[-MARKET_ACTIVITY_EXPECTED_ROWS:]
    if (
        selected_dates[0] != MARKET_ACTIVITY_EXPECTED_START
        or selected_dates[-1] != MARKET_ACTIVITY_EXPECTED_END
    ):
        raise ValueError(f"Unexpected 60-day range: {selected_dates[0]}..{selected_dates[-1]}")
    price_window = {
        value
        for value in price_by_date
        if MARKET_ACTIVITY_EXPECTED_START <= value <= MARKET_ACTIVITY_EXPECTED_END
    }
    twse_window = {
        value
        for value in twse_by_date
        if MARKET_ACTIVITY_EXPECTED_START <= value <= MARKET_ACTIVITY_EXPECTED_END
    }
    missing_dates = sorted(price_window - twse_window)
    orphan_dates = sorted(twse_window - price_window)
    if missing_dates or orphan_dates or set(selected_dates) != price_window or set(selected_dates) != twse_window:
        raise ValueError(
            f"60-day window join mismatch: missing={missing_dates}, orphan={orphan_dates}"
        )

    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=MARKET_ACTIVITY_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row_date in selected_dates:
        source = twse_by_date[row_date]
        writer.writerow({field: source[field] for field in MARKET_ACTIVITY_FIELDS})
    csv_bytes = output.getvalue().encode("utf-8")
    return csv_bytes, {
        "price_sha256": sha256_file(price_path),
        "twse_total_rows": len(twse_by_date),
        "common_dates": len(common_dates),
        "common_close_mismatches": close_mismatches,
        "rows": len(selected_dates),
        "date_range": {"start": selected_dates[0], "end": selected_dates[-1]},
        "unique_and_strictly_increasing": selected_dates == sorted(set(selected_dates)),
        "missing_dates": missing_dates,
        "orphan_dates": orphan_dates,
        "source_receipts": source_receipts,
        "csv_sha256": hashlib.sha256(csv_bytes).hexdigest().upper(),
        "actionable": False,
    }


def _build_market_activity_manifest_bytes(
    package_root: Path, csv_bytes: bytes, published_at: str
) -> bytes:
    manifest = read_json(package_root / MANIFEST_PATH)
    entries = manifest.get("authoritativeFiles", [])
    if any(item.get("path") == MARKET_ACTIVITY_TARGET for item in entries):
        raise ValueError("Market-activity authority manifest entry already exists")
    csv_rows = list(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8"))))
    csv_sha = hashlib.sha256(csv_bytes).hexdigest().upper()
    entries.append(
        {
            "path": MARKET_ACTIVITY_TARGET,
            "fileName": "2317_daily_market_activity.csv",
            "fileVersion": "market-activity-v1.0",
            "schemaVersion": "daily-market-activity-v1-7-columns",
            "sha256": csv_sha,
            "fileSizeBytes": len(csv_bytes),
            "rowCount": len(csv_rows),
            "columnCount": len(MARKET_ACTIVITY_FIELDS),
            "dateRange": {
                "start": csv_rows[0]["date"],
                "end": csv_rows[-1]["date"],
            },
            "validationStatus": "PASS",
            "fileAuthority": "CSV_AUTHORITY",
            "dataProvenance": "OFFICIAL_TWSE_STOCK_DAY_MONTHLY_CSV",
            "dataSupportLevel": "OFFICIAL_TWSE_A1",
            "requiredColumns": list(MARKET_ACTIVITY_FIELDS),
            "columns": list(MARKET_ACTIVITY_FIELDS),
            "primaryKey": ["date", "stock_id"],
            "analysisStatus": "MARKET_LIQUIDITY_ANALYSIS_READY",
            "lastPublishedAt": published_at,
            "publisher": "owner_publish_csv_v2.py",
            "publishMode": "MARKET_ACTIVITY_INITIAL_ATOMIC_PUBLISH",
            "actionable": False,
        }
    )
    manifest["approvedAt"] = published_at[:10]
    note = (
        "Owner-approved 2026-07-18 initial TWSE market-activity authority publish "
        "via owner_publish_csv_v2.py"
    )
    manifest["approvalSource"] = f"{manifest.get('approvalSource', '')}; {note}".strip("; ")
    return (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _market_activity_sqlite_schema(runtime_db: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{runtime_db.as_posix()}?mode=ro", uri=True)
    required = set(MARKET_ACTIVITY_FIELDS)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        matches = []
        for table in tables:
            columns = {
                row[1]
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            }
            if required.issubset(columns):
                matches.append(table)
    finally:
        connection.close()
    return {
        "supported": bool(matches),
        "matching_tables": matches,
        "status": "SUPPORTED" if matches else "NOT_UPDATED_SCHEMA_UNSUPPORTED",
    }


def _verify_market_activity_report_read(
    package_root: Path, formal_path: Path
) -> dict[str, Any]:
    module = _load_module(
        "p1008_market_activity_publish_reader",
        package_root / "tools" / "warroom_market_activity.py",
    )
    result = module.analyze_optional_files(
        package_root / DAILY_TARGET,
        formal_path,
        as_of_date=date.fromisoformat(MARKET_ACTIVITY_EXPECTED_END),
    )
    if result.get("status") != "MARKET_LIQUIDITY_ANALYSIS_READY":
        raise ValueError(f"Market-activity report reader is not READY: {result}")
    if result.get("as_of_date") != MARKET_ACTIVITY_EXPECTED_END:
        raise ValueError("Market-activity report reader as-of date mismatch")
    for field in ("volume_shares", "turnover_ntd", "transaction_count"):
        if not isinstance(result.get(field), int) or result[field] < 0:
            raise ValueError(f"Report reader did not load valid {field}")
    if result.get("actionable") is not False:
        raise ValueError("Market-activity report output must remain actionable=false")
    return result


def run_market_activity_publish(
    package_root: Path,
    runtime_db: Path,
    output_dir: Path,
) -> dict[str, Any]:
    package_root = package_root.resolve()
    runtime_db = runtime_db.resolve()
    output_dir = output_dir.resolve()
    formal_path = package_root / MARKET_ACTIVITY_TARGET
    manifest_path = package_root / MANIFEST_PATH
    if output_dir.exists():
        raise FileExistsError(f"Market-activity publish output already exists: {output_dir}")
    if formal_path.exists():
        raise FileExistsError("Formal market-activity CSV already exists; overwrite is not approved")
    output_dir.mkdir(parents=True)
    journal_path = output_dir / "PUBLISH_JOURNAL.json"
    published_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    csv_bytes, validation = _parse_twse_market_activity(package_root)
    manifest_bytes = _build_market_activity_manifest_bytes(
        package_root, csv_bytes, published_at
    )
    sqlite_schema = _market_activity_sqlite_schema(runtime_db)
    if sqlite_schema["supported"]:
        raise ValueError(
            "Runtime SQLite has a market-activity-shaped table, but no existing approved loader "
            "was found; publication is fail-closed"
        )
    pre_hashes = {
        MARKET_ACTIVITY_TARGET: "NOT_PRESENT",
        MANIFEST_PATH: sha256_file(manifest_path),
        "runtime_sqlite": sha256_file(runtime_db),
    }

    staged_data = output_dir / "staged" / "data"
    staged_data.mkdir(parents=True)
    staged_csv = staged_data / "2317_daily_market_activity.csv"
    staged_manifest = staged_data / "CSV_AUTHORITY_MANIFEST.json"
    staged_csv.write_bytes(csv_bytes)
    staged_manifest.write_bytes(manifest_bytes)
    backup_data = output_dir / "backup" / "data"
    backup_data.mkdir(parents=True)
    shutil.copy2(manifest_path, backup_data / manifest_path.name)
    shutil.copy2(runtime_db, output_dir / "backup" / "warroom.sqlite3")
    backup_hashes = {
        MARKET_ACTIVITY_TARGET: "NOT_PRESENT",
        MANIFEST_PATH: sha256_file(backup_data / manifest_path.name),
        "runtime_sqlite": sha256_file(output_dir / "backup" / "warroom.sqlite3"),
    }
    if backup_hashes != pre_hashes:
        raise ValueError("Market-activity backup hashes do not match pre-publish state")
    journal: dict[str, Any] = {
        "mode": "MARKET_ACTIVITY_INITIAL_ATOMIC_PUBLISH",
        "status": "BACKUP_VERIFIED",
        "created_at_utc": published_at,
        "pre_hashes": pre_hashes,
        "backup_hashes": backup_hashes,
        "staged_hashes": {
            MARKET_ACTIVITY_TARGET: sha256_file(staged_csv),
            MANIFEST_PATH: sha256_file(staged_manifest),
            "runtime_sqlite": pre_hashes["runtime_sqlite"],
        },
        "validation": validation,
        "sqlite_schema": sqlite_schema,
        "steps": ["OFFLINE_SOURCES_VERIFIED", "STAGED", "BACKUP_VERIFIED"],
        "http_calls": 0,
        "openai_calls": 0,
        "actionable": False,
    }
    _atomic_write_json(journal_path, journal)
    try:
        _atomic_write_bytes(formal_path, csv_bytes)
        journal["steps"].append(f"CREATED:{MARKET_ACTIVITY_TARGET}")
        _atomic_write_json(journal_path, journal)
        _atomic_write_bytes(manifest_path, manifest_bytes)
        journal["steps"].append(f"REPLACED:{MANIFEST_PATH}")
        _atomic_write_json(journal_path, journal)

        post_csv_bytes, post_validation = _parse_twse_market_activity(package_root)
        if formal_path.read_bytes() != post_csv_bytes:
            raise ValueError("Published market-activity CSV does not match verified source rebuild")
        manifest = read_json(manifest_path)
        entry = next(
            item
            for item in manifest.get("authoritativeFiles", [])
            if item.get("path") == MARKET_ACTIVITY_TARGET
        )
        if (
            entry.get("sha256") != sha256_file(formal_path)
            or entry.get("rowCount") != MARKET_ACTIVITY_EXPECTED_ROWS
        ):
            raise ValueError("Published market-activity manifest entry validation failed")
        runtime_hash_after = sha256_file(runtime_db)
        if runtime_hash_after != pre_hashes["runtime_sqlite"]:
            raise ValueError("Runtime SQLite changed despite unsupported market-activity schema")
        report_read = _verify_market_activity_report_read(
            package_root, formal_path
        )
        journal.update(
            {
                "status": "PUBLISHED",
                "published_at_utc": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "post_hashes": {
                    MARKET_ACTIVITY_TARGET: sha256_file(formal_path),
                    MANIFEST_PATH: sha256_file(manifest_path),
                    "runtime_sqlite": runtime_hash_after,
                },
                "post_validation": post_validation,
                "report_read_validation": report_read,
                "market_liquidity_analysis_status": "MARKET_LIQUIDITY_ANALYSIS_READY",
                "rollback_available": True,
                "rollback_performed": False,
            }
        )
        journal["steps"].append("POST_PUBLISH_VERIFIED")
        _atomic_write_json(journal_path, journal)
        return journal
    except Exception as publish_error:
        rollback_errors: list[str] = []
        try:
            if formal_path.exists():
                formal_path.unlink()
        except Exception as rollback_error:
            rollback_errors.append(f"{MARKET_ACTIVITY_TARGET}: {rollback_error}")
        for target, backup in (
            (manifest_path, backup_data / manifest_path.name),
            (runtime_db, output_dir / "backup" / "warroom.sqlite3"),
        ):
            try:
                _atomic_write_bytes(target, backup.read_bytes())
            except Exception as rollback_error:
                rollback_errors.append(f"{target}: {rollback_error}")
        restored_hashes = {
            MARKET_ACTIVITY_TARGET: (
                sha256_file(formal_path) if formal_path.exists() else "NOT_PRESENT"
            ),
            MANIFEST_PATH: sha256_file(manifest_path),
            "runtime_sqlite": sha256_file(runtime_db),
        }
        rollback_ok = not rollback_errors and restored_hashes == pre_hashes
        journal.update(
            {
                "status": "ROLLED_BACK" if rollback_ok else "ROLLBACK_FAILED",
                "publish_error": str(publish_error),
                "rollback_errors": rollback_errors,
                "restored_hashes": restored_hashes,
                "rollback_performed": True,
                "rollback_verified": rollback_ok,
            }
        )
        _atomic_write_json(journal_path, journal)
        if not rollback_ok:
            raise RuntimeError(
                "Market-activity publish failed and rollback was incomplete"
            ) from publish_error
        raise RuntimeError(
            "Market-activity publish failed; all formal state was restored"
        ) from publish_error


def build_invalid_daily_price_removal_preview(
    package_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    package_root = package_root.resolve()
    output_dir = output_dir.resolve()
    runtime_root = (package_root / "runtime").resolve()
    if not output_dir.is_relative_to(runtime_root):
        raise ValueError("Daily-price remediation preview must remain under runtime/")
    if output_dir.exists():
        raise FileExistsError(output_dir)

    formal_path = package_root / DAILY_TARGET
    manifest_path = package_root / MANIFEST_PATH
    header, rows, comments = read_csv_header_and_rows(formal_path)
    matching = [row for row in rows if row and row[0] == INVALID_DAILY_PRICE_DATE]
    if len(matching) != 1:
        raise ValueError(
            f"Expected exactly one invalid daily-price row for {INVALID_DAILY_PRICE_DATE}"
        )
    invalid_row = matching[0]
    row_map = dict(zip(header, invalid_row))
    parsed_date = date.fromisoformat(INVALID_DAILY_PRICE_DATE)
    if parsed_date.weekday() < 5:
        raise ValueError("Configured invalid daily-price date is not a weekend")
    if row_map.get("DataSupportLevel") != "PUBLIC_MARKET_DATA":
        raise ValueError("Invalid daily-price row provenance no longer matches the approved case")

    manifest = read_json(manifest_path)
    entry = next(
        (
            item
            for item in manifest.get("authoritativeFiles", [])
            if item.get("path") == DAILY_TARGET
        ),
        None,
    )
    before_sha = sha256_file(formal_path)
    if (
        entry is None
        or entry.get("sha256") != before_sha
        or entry.get("rowCount") != len(rows)
    ):
        raise ValueError("Daily-price manifest does not match formal pre-remediation CSV")

    candidate_rows = [
        row for row in rows if not row or row[0] != INVALID_DAILY_PRICE_DATE
    ]
    candidate_dates = [row[0] for row in candidate_rows if row]
    if (
        len(candidate_rows) != len(rows) - 1
        or candidate_dates != sorted(set(candidate_dates))
        or INVALID_DAILY_PRICE_DATE in candidate_dates
    ):
        raise ValueError("Daily-price remediation candidate date validation failed")

    text = io.StringIO(newline="")
    for comment in comments:
        text.write(comment + "\n")
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(candidate_rows)
    candidate_bytes = text.getvalue().encode("utf-8")

    output_dir.mkdir(parents=True)
    candidate_path = output_dir / "2317_daily_price_remove_20260719.candidate.csv"
    candidate_path.write_bytes(candidate_bytes)
    preview = {
        "mode": "OWNER_GATED_INVALID_DAILY_PRICE_REMOVAL",
        "status": "OWNER_REVIEW_REQUIRED",
        "target": DAILY_TARGET,
        "invalid_date": INVALID_DAILY_PRICE_DATE,
        "invalid_row": row_map,
        "removal_reason": (
            "2026-07-19 is Sunday and PUBLIC_MARKET_DATA is not verified TWSE "
            "trading-day evidence."
        ),
        "approval_phrase": INVALID_DAILY_PRICE_APPROVAL_PHRASE,
        "before_sha256": before_sha,
        "before_rows": len(rows),
        "candidate_path": str(candidate_path),
        "candidate_sha256": sha256_file(candidate_path),
        "candidate_rows": len(candidate_rows),
        "candidate_cutoff": candidate_dates[-1],
        "formal_csv_modified": False,
        "promotion_eligible": False,
        "actionable": False,
    }
    _atomic_write_json(output_dir / "REMEDIATION_PREVIEW.json", preview)
    return preview


def run_invalid_daily_price_removal(
    package_root: Path,
    output_dir: Path,
    *,
    publish: bool = False,
    approval_phrase: str | None = None,
) -> dict[str, Any]:
    preview = build_invalid_daily_price_removal_preview(package_root, output_dir)
    if not publish:
        return preview
    if approval_phrase != INVALID_DAILY_PRICE_APPROVAL_PHRASE:
        raise ValueError(
            "Daily-price remediation requires exact Owner approval phrase: "
            + INVALID_DAILY_PRICE_APPROVAL_PHRASE
        )

    package_root = package_root.resolve()
    output_dir = output_dir.resolve()
    formal_path = package_root / DAILY_TARGET
    manifest_path = package_root / MANIFEST_PATH
    candidate_path = Path(preview["candidate_path"])
    candidate_header, candidate_rows, _ = read_csv_header_and_rows(candidate_path)
    manifest = read_json(manifest_path)
    entry = next(
        item
        for item in manifest.get("authoritativeFiles", [])
        if item.get("path") == DAILY_TARGET
    )
    published_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry["sha256"] = sha256_file(candidate_path)
    entry["fileSizeBytes"] = candidate_path.stat().st_size
    entry["rowCount"] = len(candidate_rows)
    entry.setdefault("dateRange", {})["start"] = candidate_rows[0][0]
    entry.setdefault("dateRange", {})["end"] = candidate_rows[-1][0]
    entry["lastPublishedAt"] = published_at
    entry["lastRemediation"] = {
        "mode": "REMOVE_INVALID_DAILY_PRICE_DATE",
        "removedDate": INVALID_DAILY_PRICE_DATE,
        "candidateSha256": sha256_file(candidate_path),
        "previousFormalSha256": preview["before_sha256"],
        "approvalPhrase": INVALID_DAILY_PRICE_APPROVAL_PHRASE,
        "publishedAt": published_at,
        "publisher": "owner_publish_csv_v2.py",
        "actionable": False,
    }
    manifest["approvedAt"] = published_at[:10]
    manifest["approvalSource"] = (
        f"{manifest.get('approvalSource', '')}; Owner-approved removal of invalid "
        f"daily-price row {INVALID_DAILY_PRICE_DATE} via owner_publish_csv_v2.py"
    ).strip("; ")
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    backup_dir = output_dir / "backup"
    backup_dir.mkdir()
    shutil.copy2(formal_path, backup_dir / formal_path.name)
    shutil.copy2(manifest_path, backup_dir / manifest_path.name)
    pre_hashes = {
        DAILY_TARGET: sha256_file(formal_path),
        MANIFEST_PATH: sha256_file(manifest_path),
    }
    backup_hashes = {
        DAILY_TARGET: sha256_file(backup_dir / formal_path.name),
        MANIFEST_PATH: sha256_file(backup_dir / manifest_path.name),
    }
    if backup_hashes != pre_hashes:
        raise ValueError("Daily-price remediation backup verification failed")
    journal_path = output_dir / "PUBLISH_JOURNAL.json"
    journal: dict[str, Any] = {
        "mode": "REMOVE_INVALID_DAILY_PRICE_DATE",
        "status": "BACKUP_VERIFIED",
        "created_at_utc": published_at,
        "pre_hashes": pre_hashes,
        "backup_hashes": backup_hashes,
        "candidate_sha256": preview["candidate_sha256"],
        "actionable": False,
    }
    _atomic_write_json(journal_path, journal)
    try:
        _atomic_write_bytes(formal_path, candidate_path.read_bytes())
        _atomic_write_bytes(manifest_path, manifest_bytes)
        post_header, post_rows, _ = read_csv_header_and_rows(formal_path)
        post_manifest = read_json(manifest_path)
        post_entry = next(
            item
            for item in post_manifest.get("authoritativeFiles", [])
            if item.get("path") == DAILY_TARGET
        )
        post_dates = [row[0] for row in post_rows]
        post_hashes = {
            DAILY_TARGET: sha256_file(formal_path),
            MANIFEST_PATH: sha256_file(manifest_path),
        }
        if (
            post_header != candidate_header
            or len(post_rows) != preview["candidate_rows"]
            or INVALID_DAILY_PRICE_DATE in post_dates
            or post_dates != sorted(set(post_dates))
            or post_entry.get("sha256") != post_hashes[DAILY_TARGET]
            or post_entry.get("rowCount") != len(post_rows)
            or (post_entry.get("dateRange") or {}).get("end")
            != preview["candidate_cutoff"]
        ):
            raise ValueError("Daily-price remediation post-publish validation failed")
        journal.update(
            {
                "status": "PUBLISHED",
                "post_hashes": post_hashes,
                "rows": len(post_rows),
                "cutoff": post_dates[-1],
                "rollback_performed": False,
            }
        )
        _atomic_write_json(journal_path, journal)
        return journal
    except Exception as publish_error:
        rollback_errors: list[str] = []
        for backup, target in (
            (backup_dir / formal_path.name, formal_path),
            (backup_dir / manifest_path.name, manifest_path),
        ):
            try:
                _atomic_write_bytes(target, backup.read_bytes())
            except Exception as rollback_error:
                rollback_errors.append(f"{target}: {rollback_error}")
        restored_hashes = {
            DAILY_TARGET: sha256_file(formal_path),
            MANIFEST_PATH: sha256_file(manifest_path),
        }
        rollback_ok = not rollback_errors and restored_hashes == pre_hashes
        journal.update(
            {
                "status": "ROLLED_BACK" if rollback_ok else "ROLLBACK_FAILED",
                "publish_error": str(publish_error),
                "rollback_errors": rollback_errors,
                "restored_hashes": restored_hashes,
                "rollback_performed": True,
                "rollback_verified": rollback_ok,
            }
        )
        _atomic_write_json(journal_path, journal)
        if not rollback_ok:
            raise RuntimeError(
                "Daily-price remediation failed and rollback was incomplete"
            ) from publish_error
        raise RuntimeError(
            "Daily-price remediation failed; CSV and manifest restored"
        ) from publish_error


def _daily_price_bytes(
    comments: list[str],
    header: list[str],
    rows: list[list[str]],
) -> bytes:
    text = io.StringIO(newline="")
    for comment in comments:
        text.write(comment + "\n")
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return text.getvalue().encode("utf-8")


def build_daily_price_gaps_preview(
    package_root: Path,
    candidate_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    package_root = package_root.resolve()
    candidate_path = candidate_path.resolve()
    output_dir = output_dir.resolve()
    runtime_root = (package_root / "runtime").resolve()
    if (
        not candidate_path.is_relative_to(runtime_root)
        or not output_dir.is_relative_to(runtime_root)
    ):
        raise ValueError("Daily-price gaps candidate and journal must remain under runtime/")
    if output_dir.exists():
        raise FileExistsError(output_dir)
    if sha256_file(candidate_path) != DAILY_PRICE_GAPS_CANDIDATE_SHA256:
        raise ValueError("Daily-price gaps candidate SHA-256 is not Owner-approved")

    formal_path = package_root / DAILY_TARGET
    manifest_path = package_root / MANIFEST_PATH
    before_sha = sha256_file(formal_path)
    if before_sha != DAILY_PRICE_GAPS_REQUIRED_FORMAL_SHA256:
        raise ValueError("Daily-price formal SHA-256 is not the approved post-removal baseline")

    formal_header, formal_rows, formal_comments = read_csv_header_and_rows(formal_path)
    candidate_header, candidate_rows, _ = read_csv_header_and_rows(candidate_path)
    if candidate_header != formal_header:
        raise ValueError("Daily-price gaps candidate schema does not match formal CSV")
    candidate_rows = normalize_candidate_rows_for_publish(
        DAILY_TARGET, candidate_header, candidate_rows
    )
    validate_daily_price_publish_rows(candidate_header, candidate_rows)

    positions = {name: candidate_header.index(name) for name in candidate_header}
    candidate_by_date = {row[positions["Date"]]: row for row in candidate_rows}
    if set(candidate_by_date) != set(DAILY_PRICE_GAPS_EXPECTED_VALUES):
        raise ValueError("Daily-price gaps candidate must contain exactly 2026-07-22 and 2026-07-24")
    if len(candidate_by_date) != len(candidate_rows):
        raise ValueError("Daily-price gaps candidate contains duplicate dates")
    for row_date, expected in DAILY_PRICE_GAPS_EXPECTED_VALUES.items():
        row = candidate_by_date[row_date]
        for field, value in expected.items():
            if row[positions[field]] != value:
                raise ValueError(
                    f"Daily-price gaps candidate {row_date} {field} mismatch"
                )
        if row[positions["DataSupportLevel"]] != "OFFICIAL_TWSE_A1":
            raise ValueError(f"Daily-price gaps candidate {row_date} is not official TWSE A1")

    formal_dates = [row[formal_header.index("Date")] for row in formal_rows]
    if any(row_date in formal_dates for row_date in candidate_by_date):
        raise ValueError("Daily-price gaps candidate conflicts with an existing formal date")
    combined_rows = sorted(
        [*formal_rows, *candidate_rows],
        key=lambda row: row[formal_header.index("Date")],
    )
    combined_dates = [row[formal_header.index("Date")] for row in combined_rows]
    if combined_dates != sorted(set(combined_dates)):
        raise ValueError("Daily-price gaps combined dates are not unique and ordered")
    if any(date.fromisoformat(value).weekday() >= 5 for value in combined_dates):
        raise ValueError("Daily-price gaps combined authority contains a weekend date")
    if len(combined_rows) != DAILY_PRICE_GAPS_EXPECTED_ROWS:
        raise ValueError("Daily-price gaps combined row count is not Owner-approved")

    combined_bytes = _daily_price_bytes(
        formal_comments, formal_header, combined_rows
    )
    combined_sha = hashlib.sha256(combined_bytes).hexdigest().upper()
    if combined_sha != DAILY_PRICE_GAPS_EXPECTED_FORMAL_SHA256:
        raise ValueError("Daily-price gaps combined SHA-256 does not match Owner review")

    manifest = read_json(manifest_path)
    entry = next(
        (
            item
            for item in manifest.get("authoritativeFiles", [])
            if item.get("path") == DAILY_TARGET
        ),
        None,
    )
    if (
        entry is None
        or entry.get("sha256") != before_sha
        or entry.get("rowCount") != len(formal_rows)
        or (entry.get("dateRange") or {}).get("end") != formal_dates[-1]
    ):
        raise ValueError("Daily-price manifest does not match the post-removal formal CSV")

    output_dir.mkdir(parents=True)
    full_candidate_path = output_dir / "2317_daily_price_stage1_final.candidate.csv"
    full_candidate_path.write_bytes(combined_bytes)
    preview = {
        "mode": "OWNER_GATED_DAILY_PRICE_GAPS",
        "status": "OWNER_REVIEW_REQUIRED",
        "target": DAILY_TARGET,
        "approval_phrase": DAILY_PRICE_GAPS_APPROVAL_PHRASE,
        "source_candidate_path": str(candidate_path),
        "source_candidate_sha256": DAILY_PRICE_GAPS_CANDIDATE_SHA256,
        "before_sha256": before_sha,
        "before_rows": len(formal_rows),
        "candidate_dates": sorted(candidate_by_date),
        "final_candidate_path": str(full_candidate_path),
        "final_candidate_sha256": combined_sha,
        "final_rows": len(combined_rows),
        "final_cutoff": combined_rows[-1][positions["Date"]],
        "formal_csv_modified": False,
        "promotion_eligible": False,
        "actionable": False,
    }
    _atomic_write_json(output_dir / "GAPS_PREVIEW.json", preview)
    return preview


def run_daily_price_gaps_publish(
    package_root: Path,
    candidate_path: Path,
    output_dir: Path,
    *,
    publish: bool = False,
    approval_phrase: str | None = None,
) -> dict[str, Any]:
    preview = build_daily_price_gaps_preview(
        package_root, candidate_path, output_dir
    )
    if not publish:
        return preview
    if approval_phrase != DAILY_PRICE_GAPS_APPROVAL_PHRASE:
        raise ValueError(
            "Daily-price gaps publish requires exact Owner approval phrase: "
            + DAILY_PRICE_GAPS_APPROVAL_PHRASE
        )

    package_root = package_root.resolve()
    output_dir = output_dir.resolve()
    formal_path = package_root / DAILY_TARGET
    manifest_path = package_root / MANIFEST_PATH
    final_candidate_path = Path(preview["final_candidate_path"])
    final_header, final_rows, _ = read_csv_header_and_rows(final_candidate_path)
    published_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    manifest = read_json(manifest_path)
    entry = next(
        item
        for item in manifest.get("authoritativeFiles", [])
        if item.get("path") == DAILY_TARGET
    )
    entry["sha256"] = preview["final_candidate_sha256"]
    entry["fileSizeBytes"] = final_candidate_path.stat().st_size
    entry["rowCount"] = len(final_rows)
    entry.setdefault("dateRange", {})["start"] = final_rows[0][0]
    entry.setdefault("dateRange", {})["end"] = final_rows[-1][0]
    entry["lastPublishedAt"] = published_at
    entry["lastDailyPriceGapPublish"] = {
        "mode": "APPEND_VERIFIED_DAILY_PRICE_GAPS",
        "dates": preview["candidate_dates"],
        "candidateSha256": preview["source_candidate_sha256"],
        "previousFormalSha256": preview["before_sha256"],
        "approvalPhrase": DAILY_PRICE_GAPS_APPROVAL_PHRASE,
        "publishedAt": published_at,
        "publisher": "owner_publish_csv_v2.py",
        "runtimeSqliteModified": False,
        "actionable": False,
    }
    manifest["approvedAt"] = published_at[:10]
    manifest["approvalSource"] = (
        f"{manifest.get('approvalSource', '')}; Owner-approved official TWSE daily-price "
        "gaps 2026-07-22 and 2026-07-24 via owner_publish_csv_v2.py"
    ).strip("; ")
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    backup_dir = output_dir / "backup"
    backup_dir.mkdir()
    shutil.copy2(formal_path, backup_dir / formal_path.name)
    shutil.copy2(manifest_path, backup_dir / manifest_path.name)
    pre_hashes = {
        DAILY_TARGET: sha256_file(formal_path),
        MANIFEST_PATH: sha256_file(manifest_path),
    }
    backup_hashes = {
        DAILY_TARGET: sha256_file(backup_dir / formal_path.name),
        MANIFEST_PATH: sha256_file(backup_dir / manifest_path.name),
    }
    if backup_hashes != pre_hashes:
        raise ValueError("Daily-price gaps backup verification failed")

    journal_path = output_dir / "PUBLISH_JOURNAL.json"
    journal: dict[str, Any] = {
        "mode": "APPEND_VERIFIED_DAILY_PRICE_GAPS",
        "status": "BACKUP_VERIFIED",
        "created_at_utc": published_at,
        "pre_hashes": pre_hashes,
        "backup_hashes": backup_hashes,
        "source_candidate_sha256": preview["source_candidate_sha256"],
        "final_candidate_sha256": preview["final_candidate_sha256"],
        "actionable": False,
    }
    _atomic_write_json(journal_path, journal)
    try:
        _atomic_write_bytes(formal_path, final_candidate_path.read_bytes())
        _atomic_write_bytes(manifest_path, manifest_bytes)
        post_header, post_rows, _ = read_csv_header_and_rows(formal_path)
        post_manifest = read_json(manifest_path)
        post_entry = next(
            item
            for item in post_manifest.get("authoritativeFiles", [])
            if item.get("path") == DAILY_TARGET
        )
        post_dates = [row[post_header.index("Date")] for row in post_rows]
        post_hashes = {
            DAILY_TARGET: sha256_file(formal_path),
            MANIFEST_PATH: sha256_file(manifest_path),
        }
        if (
            post_header != final_header
            or post_hashes[DAILY_TARGET] != DAILY_PRICE_GAPS_EXPECTED_FORMAL_SHA256
            or len(post_rows) != DAILY_PRICE_GAPS_EXPECTED_ROWS
            or post_dates != sorted(set(post_dates))
            or post_entry.get("sha256") != post_hashes[DAILY_TARGET]
            or post_entry.get("rowCount") != len(post_rows)
            or (post_entry.get("dateRange") or {}).get("end") != post_dates[-1]
        ):
            raise ValueError("Daily-price gaps post-publish validation failed")
        journal.update(
            {
                "status": "PUBLISHED",
                "post_hashes": post_hashes,
                "rows": len(post_rows),
                "cutoff": post_dates[-1],
                "rollback_performed": False,
            }
        )
        _atomic_write_json(journal_path, journal)
        return journal
    except Exception as publish_error:
        rollback_errors: list[str] = []
        for backup, target in (
            (backup_dir / formal_path.name, formal_path),
            (backup_dir / manifest_path.name, manifest_path),
        ):
            try:
                _atomic_write_bytes(target, backup.read_bytes())
            except Exception as rollback_error:
                rollback_errors.append(f"{target}: {rollback_error}")
        restored_hashes = {
            DAILY_TARGET: sha256_file(formal_path),
            MANIFEST_PATH: sha256_file(manifest_path),
        }
        rollback_ok = not rollback_errors and restored_hashes == pre_hashes
        journal.update(
            {
                "status": "ROLLED_BACK" if rollback_ok else "ROLLBACK_FAILED",
                "publish_error": str(publish_error),
                "rollback_errors": rollback_errors,
                "restored_hashes": restored_hashes,
                "rollback_performed": True,
                "rollback_verified": rollback_ok,
            }
        )
        _atomic_write_json(journal_path, journal)
        if not rollback_ok:
            raise RuntimeError(
                "Daily-price gaps publish failed and rollback was incomplete"
            ) from publish_error
        raise RuntimeError(
            "Daily-price gaps publish failed; CSV and manifest restored"
        ) from publish_error


def market_activity_approval_phrase(candidate_dates: list[str]) -> str:
    if not candidate_dates:
        raise ValueError("Market-activity candidate has no dates")
    return (
        "OWNER_APPROVE_MARKET_ACTIVITY_"
        f"{candidate_dates[0].replace('-', '')}_"
        f"{candidate_dates[-1].replace('-', '')}"
    )


def publish_market_activity_append(
    package_root: Path,
    candidate_path: Path,
    output_dir: Path,
    *,
    approval_phrase: str | None = None,
) -> dict[str, Any]:
    """Atomically append a validated market-activity candidate and update its manifest entry."""

    package_root = package_root.resolve()
    candidate_path = candidate_path.resolve()
    output_dir = output_dir.resolve()
    runtime_root = (package_root / "runtime").resolve()
    if not candidate_path.is_relative_to(runtime_root) or not output_dir.is_relative_to(runtime_root):
        raise ValueError("Market-activity candidate and journal must remain under runtime/")
    formal_path = package_root / MARKET_ACTIVITY_TARGET
    manifest_path = package_root / MANIFEST_PATH
    if not formal_path.is_file():
        raise FileNotFoundError(formal_path)
    if output_dir.exists():
        raise FileExistsError(output_dir)

    formal_header, formal_rows, _ = read_csv_header_and_rows(formal_path)
    candidate_header, candidate_rows, _ = read_csv_header_and_rows(candidate_path)
    if tuple(formal_header) != MARKET_ACTIVITY_FIELDS or formal_header != candidate_header:
        raise ValueError("Market-activity append schema mismatch")
    if not candidate_rows:
        raise ValueError("Market-activity append candidate is empty")
    formal_dates = [row[0] for row in formal_rows]
    candidate_dates = [row[0] for row in candidate_rows]
    expected_approval = market_activity_approval_phrase(candidate_dates)
    if approval_phrase != expected_approval:
        raise ValueError(
            "Market-activity formal publish requires exact Owner approval phrase: "
            + expected_approval
        )
    if formal_dates != sorted(set(formal_dates)):
        raise ValueError("Formal market-activity dates are not unique and increasing")
    if candidate_dates != sorted(set(candidate_dates)):
        raise ValueError("Candidate market-activity dates are not unique and increasing")
    if set(formal_dates) & set(candidate_dates) or candidate_dates[0] <= formal_dates[-1]:
        raise ValueError("Market-activity append would rewrite or duplicate history")
    for row in candidate_rows:
        if row[1] != "2317" or not all(row[index].isdigit() for index in (2, 3, 4)):
            raise ValueError(f"Invalid market-activity candidate row: {row}")
        if not row[5].startswith("https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?"):
            raise ValueError("Market-activity candidate source is not approved TWSE STOCK_DAY")
        if row[6] != row[0][:7]:
            raise ValueError("Market-activity source_month does not match date")

    manifest = read_json(manifest_path)
    entry = next(
        (
            item
            for item in manifest.get("authoritativeFiles", [])
            if item.get("path") == MARKET_ACTIVITY_TARGET
        ),
        None,
    )
    formal_sha = sha256_file(formal_path)
    if entry is None or entry.get("sha256") != formal_sha or entry.get("rowCount") != len(formal_rows):
        raise ValueError("Market-activity manifest does not match formal pre-publish CSV")

    # Preserve every historical byte exactly.  The append publisher may add
    # rows, but it must never re-serialize or otherwise rewrite prior rows.
    formal_bytes = formal_path.read_bytes()
    if not formal_bytes.endswith((b"\n", b"\r")):
        raise ValueError("Formal market-activity CSV must end with a newline")
    append_output = io.StringIO(newline="")
    append_writer = csv.writer(append_output, lineterminator="\n")
    append_writer.writerows(candidate_rows)
    combined_bytes = formal_bytes + append_output.getvalue().encode("utf-8")
    if not combined_bytes.startswith(formal_bytes):
        raise ValueError("Market-activity append changed historical CSV bytes")
    combined_sha = hashlib.sha256(combined_bytes).hexdigest().upper()
    published_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry["sha256"] = combined_sha
    entry["fileSizeBytes"] = len(combined_bytes)
    entry["rowCount"] = len(formal_rows) + len(candidate_rows)
    entry["dateRange"]["end"] = candidate_dates[-1]
    entry["lastPublishedAt"] = published_at
    entry["analysisStatus"] = "MARKET_LIQUIDITY_ANALYSIS_READY"
    entry["lastAppend"] = {
        "rowsAdded": len(candidate_rows),
        "start": candidate_dates[0],
        "end": candidate_dates[-1],
        "candidateSha256": sha256_file(candidate_path),
        "publishedAt": published_at,
        "publisher": "owner_publish_csv_v2.py",
        "mode": "MARKET_ACTIVITY_ATOMIC_APPEND",
        "actionable": False,
    }
    manifest["approvedAt"] = published_at[:10]
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    output_dir.mkdir(parents=True)
    staged_dir = output_dir / "staged"
    backup_dir = output_dir / "backup"
    staged_dir.mkdir()
    backup_dir.mkdir()
    staged_csv = staged_dir / formal_path.name
    staged_manifest = staged_dir / manifest_path.name
    staged_csv.write_bytes(combined_bytes)
    staged_manifest.write_bytes(manifest_bytes)
    shutil.copy2(formal_path, backup_dir / formal_path.name)
    shutil.copy2(manifest_path, backup_dir / manifest_path.name)
    pre_hashes = {
        MARKET_ACTIVITY_TARGET: formal_sha,
        MANIFEST_PATH: sha256_file(manifest_path),
    }
    backup_hashes = {
        MARKET_ACTIVITY_TARGET: sha256_file(backup_dir / formal_path.name),
        MANIFEST_PATH: sha256_file(backup_dir / manifest_path.name),
    }
    if pre_hashes != backup_hashes:
        raise ValueError("Market-activity append backup verification failed")
    journal_path = output_dir / "PUBLISH_JOURNAL.json"
    journal: dict[str, Any] = {
        "mode": "MARKET_ACTIVITY_ATOMIC_APPEND",
        "status": "BACKUP_VERIFIED",
        "created_at_utc": published_at,
        "candidate_path": str(candidate_path),
        "candidate_sha256": sha256_file(candidate_path),
        "rows_added": len(candidate_rows),
        "date_range_added": {"start": candidate_dates[0], "end": candidate_dates[-1]},
        "pre_hashes": pre_hashes,
        "backup_hashes": backup_hashes,
        "staged_hashes": {
            MARKET_ACTIVITY_TARGET: combined_sha,
            MANIFEST_PATH: hashlib.sha256(manifest_bytes).hexdigest().upper(),
        },
        "actionable": False,
    }
    _atomic_write_json(journal_path, journal)
    try:
        _atomic_write_bytes(formal_path, combined_bytes)
        _atomic_write_bytes(manifest_path, manifest_bytes)
        published_header, published_rows, _ = read_csv_header_and_rows(formal_path)
        published_dates = [row[0] for row in published_rows]
        published_manifest = read_json(manifest_path)
        published_entry = next(
            item
            for item in published_manifest.get("authoritativeFiles", [])
            if item.get("path") == MARKET_ACTIVITY_TARGET
        )
        if (
            tuple(published_header) != MARKET_ACTIVITY_FIELDS
            or published_dates != sorted(set(published_dates))
            or published_dates[-len(candidate_dates):] != candidate_dates
            or sha256_file(formal_path) != combined_sha
            or published_entry.get("sha256") != combined_sha
            or published_entry.get("rowCount") != len(published_rows)
        ):
            raise ValueError("Market-activity append post-publish validation failed")
        journal.update(
            {
                "status": "PUBLISHED",
                "published_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "post_hashes": {
                    MARKET_ACTIVITY_TARGET: sha256_file(formal_path),
                    MANIFEST_PATH: sha256_file(manifest_path),
                },
                "total_rows": len(published_rows),
                "last_date": published_dates[-1],
                "rollback_available": True,
                "rollback_performed": False,
            }
        )
        _atomic_write_json(journal_path, journal)
        return journal
    except Exception as publish_error:
        rollback_errors: list[str] = []
        for target, backup in (
            (formal_path, backup_dir / formal_path.name),
            (manifest_path, backup_dir / manifest_path.name),
        ):
            try:
                _atomic_write_bytes(target, backup.read_bytes())
            except Exception as rollback_error:
                rollback_errors.append(f"{target}: {rollback_error}")
        restored = {
            MARKET_ACTIVITY_TARGET: sha256_file(formal_path),
            MANIFEST_PATH: sha256_file(manifest_path),
        }
        rollback_ok = not rollback_errors and restored == pre_hashes
        journal.update(
            {
                "status": "ROLLED_BACK" if rollback_ok else "ROLLBACK_FAILED",
                "publish_error": str(publish_error),
                "rollback_errors": rollback_errors,
                "restored_hashes": restored,
                "rollback_performed": True,
                "rollback_verified": rollback_ok,
            }
        )
        _atomic_write_json(journal_path, journal)
        if not rollback_ok:
            raise RuntimeError("Market-activity append rollback was incomplete") from publish_error
        raise RuntimeError("Market-activity append failed; CSV and manifest restored") from publish_error


def _macro_document_rows(payload: bytes) -> tuple[list[str], list[list[str]], int]:
    lines = payload.decode("utf-8-sig").splitlines()
    try:
        header_offset = next(
            index for index, line in enumerate(lines) if line.startswith("Date,")
        )
    except StopIteration as error:
        raise ValueError("Macro authority has no Date CSV header") from error
    parsed = list(csv.reader(line for line in lines[header_offset:] if line.strip()))
    if not parsed:
        raise ValueError("Macro authority has no CSV records")
    header, rows = parsed[0], parsed[1:]
    if any(len(row) != len(header) for row in rows):
        raise ValueError("Macro authority contains a row-width mismatch")
    return header, rows, header_offset + 1


def _macro_stage2b_canonical_blob(package_root: Path) -> bytes:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=package_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != MACRO_STAGE2B_REQUIRED_HEAD:
        raise ValueError(
            "Macro Stage 2B publish requires HEAD "
            f"{MACRO_STAGE2B_REQUIRED_HEAD}; found {head}"
        )
    return subprocess.run(
        ["git", "cat-file", "blob", f"HEAD:{MACRO_TARGET}"],
        cwd=package_root,
        check=True,
        capture_output=True,
    ).stdout


def _validate_macro_stage2b_inputs(
    package_root: Path,
    candidate_path: Path,
    row_identity_receipt_path: Path,
    *,
    canonical_blob_bytes: bytes | None = None,
) -> dict[str, Any]:
    formal_path = package_root / MACRO_TARGET
    manifest_path = package_root / MANIFEST_PATH
    if not formal_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError("Macro formal CSV or authority manifest is missing")
    if not candidate_path.is_file() or not row_identity_receipt_path.is_file():
        raise FileNotFoundError("Macro Stage 2B candidate or row-identity receipt is missing")

    candidate_sha = sha256_file(candidate_path)
    receipt_sha = sha256_file(row_identity_receipt_path)
    if candidate_sha != MACRO_STAGE2B_CANDIDATE_SHA256:
        raise ValueError("Macro Stage 2B candidate SHA-256 mismatch")
    if (
        canonical_blob_bytes is None
        and receipt_sha != MACRO_STAGE2B_ROW_IDENTITY_RECEIPT_SHA256
    ):
        raise ValueError("Macro Stage 2B row-identity receipt SHA-256 mismatch")
    if sha256_file(manifest_path) != MACRO_STAGE2B_MANIFEST_BEFORE_SHA256:
        raise ValueError("Macro Stage 2B pre-publish manifest SHA-256 mismatch")

    canonical = (
        canonical_blob_bytes
        if canonical_blob_bytes is not None
        else _macro_stage2b_canonical_blob(package_root)
    )
    canonical_sha = hashlib.sha256(canonical).hexdigest().upper()
    if canonical_sha != MACRO_STAGE2B_CANONICAL_BEFORE_SHA256:
        raise ValueError("Macro canonical Git blob SHA-256 mismatch")
    formal_bytes = formal_path.read_bytes()
    if formal_bytes.replace(b"\r\n", b"\n") != canonical.replace(b"\r\n", b"\n"):
        raise ValueError(
            "Macro formal worktree differs from canonical Git blob beyond line endings"
        )

    canonical_header, canonical_rows, canonical_header_line = _macro_document_rows(
        canonical
    )
    candidate_bytes = candidate_path.read_bytes()
    candidate_header, candidate_rows, candidate_header_line = _macro_document_rows(
        candidate_bytes
    )
    if canonical_header_line != 22 or candidate_header_line != 22:
        raise ValueError("Macro Stage 2B physical header identity mismatch")
    if canonical_header != candidate_header:
        raise ValueError("Macro Stage 2B candidate schema mismatch")
    if len(canonical_rows) != MACRO_STAGE2B_EXPECTED_ROWS or len(candidate_rows) != len(
        canonical_rows
    ):
        raise ValueError("Macro Stage 2B candidate must preserve exactly 39 records")
    date_index = canonical_header.index("Date")
    value_index = canonical_header.index("Hon_Hai_Rev_YoY")
    canonical_dates = [row[date_index] for row in canonical_rows]
    candidate_dates = [row[date_index] for row in candidate_rows]
    if canonical_dates != candidate_dates:
        raise ValueError("Macro Stage 2B candidate added, removed, or reordered records")
    if (
        len(set(candidate_dates)) != len(candidate_dates)
        or candidate_dates[-1] != MACRO_STAGE2B_EXPECTED_CUTOFF
        or any(value > MACRO_STAGE2B_EXPECTED_CUTOFF for value in candidate_dates)
    ):
        raise ValueError("Macro Stage 2B candidate date identity or cutoff mismatch")

    differences: list[dict[str, Any]] = []
    for ordinal, (before, after) in enumerate(
        zip(canonical_rows, candidate_rows), start=1
    ):
        for column_index, (old_value, new_value) in enumerate(zip(before, after)):
            if old_value != new_value:
                differences.append(
                    {
                        "ordinal": ordinal,
                        "date": before[date_index],
                        "column": canonical_header[column_index],
                        "before": old_value,
                        "after": new_value,
                    }
                )
    expected_ordinals = [item[0] for item in MACRO_STAGE2B_EXPECTED_IDENTITIES]
    if (
        len(differences) != 5
        or [item["ordinal"] for item in differences] != expected_ordinals
        or any(item["column"] != "Hon_Hai_Rev_YoY" for item in differences)
        or any(item["after"] != "" for item in differences)
    ):
        raise ValueError(
            "Macro Stage 2B candidate must blank exactly the five approved cells"
        )
    for difference, expected in zip(
        differences, MACRO_STAGE2B_EXPECTED_IDENTITIES
    ):
        ordinal, physical_line, expected_date, expected_first_value = expected
        if (
            difference["ordinal"] != ordinal
            or difference["date"] != expected_date
            or physical_line != canonical_header_line + ordinal
            or (
                expected_first_value is not None
                and difference["before"] != expected_first_value
            )
        ):
            raise ValueError("Macro Stage 2B canonical row identity mismatch")

    receipt = read_json(row_identity_receipt_path)
    receipt_identities = receipt.get("row_identities", [])
    receipt_pairs = [
        (
            item.get("canonical_data_record_ordinal"),
            item.get("physical_file_line_number"),
            item.get("date"),
        )
        for item in receipt_identities
    ]
    expected_pairs = [
        (ordinal, physical_line, expected_date)
        for ordinal, physical_line, expected_date, _ in MACRO_STAGE2B_EXPECTED_IDENTITIES
    ]
    if (
        receipt.get("input", {}).get("source") != "CANONICAL_GIT_BLOB_ONLY"
        or receipt.get("input", {}).get("sha256")
        != MACRO_STAGE2B_CANONICAL_BEFORE_SHA256
        or receipt.get("candidate", {}).get("sha256")
        != MACRO_STAGE2B_CANDIDATE_SHA256
        or receipt.get("canonical_statistics", {}).get("data_record_count")
        != MACRO_STAGE2B_EXPECTED_ROWS
        or receipt_pairs != expected_pairs
        or any(
            item.get("from_rejected_extra_seven_rows") is not False
            for item in receipt_identities
        )
    ):
        raise ValueError("Macro Stage 2B row-identity receipt content mismatch")

    manifest = read_json(manifest_path)
    entries = manifest.get("authoritativeFiles", []) + manifest.get(
        "nonAuthoritativeFiles", []
    )
    macro_entry = next(
        (item for item in entries if item.get("path") == MACRO_TARGET), None
    )
    if (
        macro_entry is None
        or macro_entry.get("sha256") != MACRO_STAGE2B_CANONICAL_BEFORE_SHA256
        or macro_entry.get("rowCount") != MACRO_STAGE2B_EXPECTED_ROWS
        or macro_entry.get("cutoffDate") != MACRO_STAGE2B_EXPECTED_CUTOFF
    ):
        raise ValueError("Macro manifest entry does not match canonical pre-publish state")
    macro_entry["sha256"] = candidate_sha
    macro_entry["fileSizeBytes"] = len(candidate_bytes)
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    manifest_after_sha = hashlib.sha256(manifest_bytes).hexdigest().upper()
    if manifest_after_sha != MACRO_STAGE2B_MANIFEST_AFTER_SHA256:
        raise ValueError("Macro Stage 2B projected manifest SHA-256 mismatch")

    return {
        "canonical_sha256": canonical_sha,
        "formal_worktree_sha256": sha256_file(formal_path),
        "candidate_sha256": candidate_sha,
        "row_identity_receipt_sha256": receipt_sha,
        "manifest_before_sha256": MACRO_STAGE2B_MANIFEST_BEFORE_SHA256,
        "manifest_after_sha256": manifest_after_sha,
        "candidate_bytes": candidate_bytes,
        "manifest_bytes": manifest_bytes,
        "rows": len(candidate_rows),
        "cutoff": candidate_dates[-1],
        "differences": differences,
        "added_rows": 0,
        "removed_rows": 0,
        "actionable": False,
    }


def run_macro_stage2b_publish(
    package_root: Path,
    candidate_path: Path,
    row_identity_receipt_path: Path,
    output_dir: Path,
    *,
    publish: bool = False,
    approval_phrase: str | None = None,
    dry_run_journal: Path | None = None,
    canonical_blob_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Validate or atomically publish the fixed Owner-approved Stage 2B macro repair."""

    package_root = package_root.resolve()
    candidate_path = candidate_path.resolve()
    row_identity_receipt_path = row_identity_receipt_path.resolve()
    output_dir = output_dir.resolve()
    runtime_root = (package_root / "runtime").resolve()
    if (
        not candidate_path.is_relative_to(runtime_root)
        or not row_identity_receipt_path.is_relative_to(runtime_root)
        or not output_dir.is_relative_to(runtime_root)
    ):
        raise ValueError("Macro Stage 2B evidence and journal must remain under runtime/")
    if approval_phrase != MACRO_STAGE2B_APPROVAL_PHRASE:
        raise ValueError(
            "Macro Stage 2B publish requires exact Owner approval phrase: "
            + MACRO_STAGE2B_APPROVAL_PHRASE
        )
    if output_dir.exists():
        raise FileExistsError(output_dir)

    validation = _validate_macro_stage2b_inputs(
        package_root,
        candidate_path,
        row_identity_receipt_path,
        canonical_blob_bytes=canonical_blob_bytes,
    )
    formal_path = package_root / MACRO_TARGET
    manifest_path = package_root / MANIFEST_PATH
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    journal: dict[str, Any] = {
        "mode": "MACRO_STAGE2B_ATOMIC_REMEDIATION_REPLACE",
        "status": "VALIDATED",
        "created_at_utc": created_at,
        "approval_phrase": MACRO_STAGE2B_APPROVAL_PHRASE,
        "candidate_path": str(candidate_path),
        "candidate_sha256": validation["candidate_sha256"],
        "row_identity_receipt_path": str(row_identity_receipt_path),
        "row_identity_receipt_sha256": validation[
            "row_identity_receipt_sha256"
        ],
        "pre_hashes": {
            MACRO_TARGET: validation["canonical_sha256"],
            MANIFEST_PATH: validation["manifest_before_sha256"],
        },
        "staged_hashes": {
            MACRO_TARGET: validation["candidate_sha256"],
            MANIFEST_PATH: validation["manifest_after_sha256"],
        },
        "rows": validation["rows"],
        "cutoff": validation["cutoff"],
        "differences": validation["differences"],
        "added_rows": 0,
        "removed_rows": 0,
        "rollback_performed": False,
        "openai_calls": 0,
        "web_search_calls": 0,
        "canva_calls": 0,
        "actionable": False,
    }
    output_dir.mkdir(parents=True)
    journal_path = output_dir / "PUBLISH_JOURNAL.json"
    if not publish:
        journal["status"] = "DRY_RUN_PASS"
        _atomic_write_json(journal_path, journal)
        return journal

    if dry_run_journal is None or not dry_run_journal.is_file():
        raise ValueError("Macro Stage 2B formal publish requires a dry-run journal")
    dry_run = read_json(dry_run_journal)
    if (
        dry_run.get("status") != "DRY_RUN_PASS"
        or dry_run.get("candidate_sha256") != MACRO_STAGE2B_CANDIDATE_SHA256
        or dry_run.get("row_identity_receipt_sha256")
        != validation["row_identity_receipt_sha256"]
        or dry_run.get("staged_hashes", {}).get(MANIFEST_PATH)
        != MACRO_STAGE2B_MANIFEST_AFTER_SHA256
    ):
        raise ValueError("Macro Stage 2B dry-run journal is invalid")

    staged_dir = output_dir / "staged"
    backup_dir = output_dir / "backup"
    staged_dir.mkdir()
    backup_dir.mkdir()
    (staged_dir / formal_path.name).write_bytes(validation["candidate_bytes"])
    (staged_dir / manifest_path.name).write_bytes(validation["manifest_bytes"])
    shutil.copy2(formal_path, backup_dir / formal_path.name)
    shutil.copy2(manifest_path, backup_dir / manifest_path.name)
    backup_hashes = {
        MACRO_TARGET: sha256_file(backup_dir / formal_path.name),
        MANIFEST_PATH: sha256_file(backup_dir / manifest_path.name),
    }
    if (
        backup_hashes[MACRO_TARGET] != validation["formal_worktree_sha256"]
        or backup_hashes[MANIFEST_PATH]
        != MACRO_STAGE2B_MANIFEST_BEFORE_SHA256
    ):
        raise ValueError("Macro Stage 2B backup verification failed")
    journal["status"] = "BACKUP_VERIFIED"
    journal["backup_hashes"] = backup_hashes
    _atomic_write_json(journal_path, journal)

    try:
        _atomic_write_bytes(formal_path, validation["candidate_bytes"])
        _atomic_write_bytes(manifest_path, validation["manifest_bytes"])
        published_header, published_rows, _ = _macro_document_rows(
            formal_path.read_bytes()
        )
        published_dates = [
            row[published_header.index("Date")] for row in published_rows
        ]
        published_manifest = read_json(manifest_path)
        published_entries = published_manifest.get(
            "authoritativeFiles", []
        ) + published_manifest.get("nonAuthoritativeFiles", [])
        published_entry = next(
            item for item in published_entries if item.get("path") == MACRO_TARGET
        )
        if (
            sha256_file(formal_path) != MACRO_STAGE2B_CANDIDATE_SHA256
            or sha256_file(manifest_path) != MACRO_STAGE2B_MANIFEST_AFTER_SHA256
            or len(published_rows) != MACRO_STAGE2B_EXPECTED_ROWS
            or len(set(published_dates)) != len(published_dates)
            or published_dates[-1] != MACRO_STAGE2B_EXPECTED_CUTOFF
            or published_entry.get("sha256")
            != MACRO_STAGE2B_CANDIDATE_SHA256
            or published_entry.get("rowCount") != MACRO_STAGE2B_EXPECTED_ROWS
            or published_entry.get("cutoffDate")
            != MACRO_STAGE2B_EXPECTED_CUTOFF
        ):
            raise ValueError("Macro Stage 2B post-publish validation failed")
        journal.update(
            {
                "status": "PUBLISHED",
                "published_at_utc": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "post_hashes": {
                    MACRO_TARGET: sha256_file(formal_path),
                    MANIFEST_PATH: sha256_file(manifest_path),
                },
                "transaction_status": "PUBLISHED",
                "rollback_available": True,
                "rollback_performed": False,
            }
        )
        _atomic_write_json(journal_path, journal)
        return journal
    except Exception as publish_error:
        rollback_errors: list[str] = []
        for target, backup in (
            (formal_path, backup_dir / formal_path.name),
            (manifest_path, backup_dir / manifest_path.name),
        ):
            try:
                _atomic_write_bytes(target, backup.read_bytes())
            except Exception as rollback_error:
                rollback_errors.append(f"{target}: {rollback_error}")
        restored = {
            MACRO_TARGET: sha256_file(formal_path),
            MANIFEST_PATH: sha256_file(manifest_path),
        }
        rollback_ok = (
            not rollback_errors
            and restored[MACRO_TARGET] == validation["formal_worktree_sha256"]
            and restored[MANIFEST_PATH]
            == MACRO_STAGE2B_MANIFEST_BEFORE_SHA256
        )
        journal.update(
            {
                "status": "ROLLED_BACK" if rollback_ok else "ROLLBACK_FAILED",
                "publish_error": str(publish_error),
                "rollback_errors": rollback_errors,
                "restored_hashes": restored,
                "transaction_status": "FAILED",
                "rollback_performed": True,
                "rollback_verified": rollback_ok,
            }
        )
        _atomic_write_json(journal_path, journal)
        if not rollback_ok:
            raise RuntimeError("Macro Stage 2B rollback was incomplete") from publish_error
        raise RuntimeError(
            "Macro Stage 2B publish failed; CSV and manifest restored"
        ) from publish_error


def main() -> int:
    parser = argparse.ArgumentParser(description="Review or publish P1008 staging CSV candidates.")
    parser.add_argument("--package-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--date", help="Staging date, for example 2026-06-29. Defaults to latest staging date.")
    parser.add_argument("--publish", action="store_true", help="Append candidate rows into formal CSV files.")
    parser.add_argument(
        "--remediation-replace",
        action="store_true",
        help=(
            "Explicitly opt in to the fixed P1008 price-authority remediation replacement. "
            "Without this flag the existing append workflow is unchanged."
        ),
    )
    parser.add_argument("--remediation-candidate", type=Path)
    parser.add_argument("--runtime-db", type=Path)
    parser.add_argument("--remediation-output-dir", type=Path)
    parser.add_argument("--remediation-dry-run-journal", type=Path)
    parser.add_argument(
        "--market-activity-publish",
        action="store_true",
        help="Explicitly run the fixed offline TWSE 60-day market-activity initial publish.",
    )
    parser.add_argument("--market-activity-output-dir", type=Path)
    parser.add_argument(
        "--invalid-daily-price-removal",
        action="store_true",
        help=(
            "Build the Owner-gated 2026-07-19 invalid-row removal preview. "
            "Formal mutation additionally requires --publish and the exact phrase."
        ),
    )
    parser.add_argument("--invalid-daily-price-output-dir", type=Path)
    parser.add_argument(
        "--daily-price-gaps-publish",
        action="store_true",
        help=(
            "Build or publish the fixed Owner-approved 2026-07-22/2026-07-24 "
            "daily-price gaps candidate."
        ),
    )
    parser.add_argument("--daily-price-gaps-candidate", type=Path)
    parser.add_argument("--daily-price-gaps-output-dir", type=Path)
    parser.add_argument(
        "--macro-stage2b-publish",
        action="store_true",
        help=(
            "Explicitly validate or publish the fixed Owner-approved Stage 2B "
            "Hon_Hai_Rev_YoY remediation."
        ),
    )
    parser.add_argument("--macro-stage2b-candidate", type=Path)
    parser.add_argument("--macro-stage2b-row-identity-receipt", type=Path)
    parser.add_argument("--macro-stage2b-output-dir", type=Path)
    parser.add_argument("--macro-stage2b-dry-run-journal", type=Path)
    parser.add_argument("--approval-phrase")
    args = parser.parse_args()

    package_root = args.package_root.resolve()
    if args.macro_stage2b_publish:
        if (
            args.daily_price_gaps_publish
            or args.invalid_daily_price_removal
            or args.market_activity_publish
            or args.remediation_replace
        ):
            parser.error("macro Stage 2B publish is mutually exclusive")
        required = {
            "--macro-stage2b-candidate": args.macro_stage2b_candidate,
            "--macro-stage2b-row-identity-receipt": (
                args.macro_stage2b_row_identity_receipt
            ),
            "--macro-stage2b-output-dir": args.macro_stage2b_output_dir,
        }
        missing = [flag for flag, value in required.items() if value is None]
        if missing:
            parser.error("macro Stage 2B publish requires " + ", ".join(missing))
        if args.publish and args.macro_stage2b_dry_run_journal is None:
            parser.error(
                "formal macro Stage 2B publish requires "
                "--macro-stage2b-dry-run-journal"
            )
        result = run_macro_stage2b_publish(
            package_root,
            args.macro_stage2b_candidate,
            args.macro_stage2b_row_identity_receipt,
            args.macro_stage2b_output_dir,
            publish=args.publish,
            approval_phrase=args.approval_phrase,
            dry_run_journal=args.macro_stage2b_dry_run_journal,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.daily_price_gaps_publish:
        if (
            args.invalid_daily_price_removal
            or args.market_activity_publish
            or args.remediation_replace
        ):
            parser.error("daily-price gaps publish is mutually exclusive")
        required = {
            "--daily-price-gaps-candidate": args.daily_price_gaps_candidate,
            "--daily-price-gaps-output-dir": args.daily_price_gaps_output_dir,
        }
        missing = [flag for flag, value in required.items() if value is None]
        if missing:
            parser.error(
                "daily-price gaps publish requires " + ", ".join(missing)
            )
        result = run_daily_price_gaps_publish(
            package_root,
            args.daily_price_gaps_candidate,
            args.daily_price_gaps_output_dir,
            publish=args.publish,
            approval_phrase=args.approval_phrase,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.invalid_daily_price_removal:
        if args.market_activity_publish or args.remediation_replace:
            parser.error("invalid daily-price removal is mutually exclusive")
        if args.invalid_daily_price_output_dir is None:
            parser.error(
                "invalid daily-price removal requires --invalid-daily-price-output-dir"
            )
        result = run_invalid_daily_price_removal(
            package_root,
            args.invalid_daily_price_output_dir,
            publish=args.publish,
            approval_phrase=args.approval_phrase,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.market_activity_publish:
        if args.remediation_replace:
            parser.error("market-activity and price-remediation modes are mutually exclusive")
        if not args.publish:
            parser.error("market-activity formal publish requires --publish")
        required = {
            "--runtime-db": args.runtime_db,
            "--market-activity-output-dir": args.market_activity_output_dir,
        }
        missing = [flag for flag, value in required.items() if value is None]
        if missing:
            parser.error(
                "market-activity publish requires " + ", ".join(missing)
            )
        result = run_market_activity_publish(
            package_root,
            args.runtime_db,
            args.market_activity_output_dir,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.remediation_replace:
        required = {
            "--remediation-candidate": args.remediation_candidate,
            "--runtime-db": args.runtime_db,
            "--remediation-output-dir": args.remediation_output_dir,
        }
        missing = [flag for flag, value in required.items() if value is None]
        if missing:
            parser.error(
                "remediation replace mode requires " + ", ".join(missing)
            )
        if args.publish and args.remediation_dry_run_journal is None:
            parser.error(
                "formal remediation publish requires --remediation-dry-run-journal"
            )
        result = run_price_remediation(
            package_root,
            args.remediation_candidate,
            args.runtime_db,
            args.remediation_output_dir,
            publish=args.publish,
            dry_run_journal=args.remediation_dry_run_journal,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    staging_dir = package_root / "staging" / args.date if args.date else latest_staging_dir(package_root)
    dry_run_path = staging_dir / "DRY_RUN.json"
    if not dry_run_path.exists():
        raise SystemExit(f"DRY_RUN not found: {dry_run_path}")

    dry_run = read_json(dry_run_path)
    candidate_date = dry_run.get("candidateDate", staging_dir.name)
    generated_files = dry_run.get("generatedFiles", []) or []
    readiness = build_publish_readiness(package_root, dry_run)

    print("===================================================")
    print("P1008 Owner formal CSV publish checkpoint")
    print("===================================================")
    print(f"Package root : {package_root}")
    print(f"Candidate    : {candidate_date}")
    print(f"DRY_RUN      : {dry_run_path}")
    print(f"Generated    : {', '.join(generated_files) if generated_files else 'none'}")
    print(f"Critical miss: {', '.join(readiness['criticalMissingFields']) if readiness['criticalMissingFields'] else 'none'}")
    print("Review mode modifies formal CSV: NO")
    print("---------------------------------------------------")
    print_readiness(readiness)
    print()

    if not readiness["allowed"]:
        print("[BLOCKED] Candidate does not meet formal CSV publish standard.")
        print("          Formal CSV publish is refused before Owner approval prompt.")
        print("          Use 1_一鍵更新數據.bat again after fixing source gaps, or keep runtime snapshot as observation only.")
        return 3

    if readiness.get("noActionRequired"):
        print("[NO ACTION REQUIRED] Formal CSV already contains this candidate date.")
        print("                     No generated candidate CSV is pending append.")
        print("                     Review completed without modifying formal CSV.")
        return 0

    if not args.publish:
        print("[READY FOR OWNER REVIEW] No files were changed.")
        print(f"To publish after review, rerun with --date {candidate_date} --publish")
        return 0

    approval_phrase = f"APPROVE {candidate_date}"
    typed = input(f"Type exactly '{approval_phrase}' to append formal CSV: ").strip()
    if typed != approval_phrase:
        print("[CANCELLED] Approval phrase did not match. No files were changed.")
        return 5

    backup_dir = staging_dir / "owner_publish_backup"
    backup_dir.mkdir(exist_ok=True)
    touched_targets: list[str] = []
    total_rows = 0
    for generated in generated_files:
        candidate_path, target_rel, _ = resolve_generated_file(package_root, generated)
        target_path = package_root / target_rel
        if not candidate_path.exists():
            raise FileNotFoundError(candidate_path)
        if not target_path.exists():
            raise FileNotFoundError(target_path)
        shutil.copy2(target_path, backup_dir / target_path.name)
        rows_added = append_candidate(candidate_path, target_path, target_rel)
        total_rows += rows_added
        touched_targets.append(target_rel)
        print(f"[APPENDED] {rows_added} row(s): {candidate_path} -> {target_path}")

    if total_rows == 0:
        print("[NO ACTION REQUIRED] Candidate rows are byte-equivalent to formal rows.")
        print("                     Formal CSV and manifest were not modified.")
        return 0

    approval_note = f"Owner approval {candidate_date} via owner_publish_csv_v2.py; appended {total_rows} row(s)"
    update_manifest(package_root, touched_targets, approval_note)
    published_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    runtime_snapshot_synced = sync_runtime_snapshot_after_publish(
        package_root,
        str(candidate_date),
        touched_targets,
        published_at,
    )
    news_scan_snapshot_synced = sync_news_scan_snapshot_after_publish(
        package_root,
        str(candidate_date),
        touched_targets,
        published_at,
    )
    event_review_state_synced = sync_event_review_state_after_publish(
        package_root,
        str(candidate_date),
        touched_targets,
        published_at,
    )
    dry_run_synced = sync_dry_run_after_publish(dry_run_path, touched_targets, published_at)
    report = {
        "publishedAt": published_at,
        "candidateDate": candidate_date,
        "touchedTargets": touched_targets,
        "rowsAdded": total_rows,
        "runtimeSnapshotSynced": runtime_snapshot_synced,
        "newsScanSnapshotSynced": news_scan_snapshot_synced,
        "eventReviewStateSynced": event_review_state_synced,
        "dryRunSynced": dry_run_synced,
        "actionable": False,
        "noteZh": "Owner 已核准正式 CSV append；UI 與 MARKET INTELLIGENCE 仍維持僅供決策參考，actionable:false。",
    }
    write_json(staging_dir / "OWNER_PUBLISH_REPORT.json", report)
    print("[OK] Formal CSV append completed and manifest was updated.")
    print("[NEXT] Reopen with 2_開啟戰情室網頁.bat and verify formal baseline.")
    return 0


def publish_daily_price_reconcile(
    package_root: Path,
    candidate_path: Path,
    output_dir: Path,
    *,
    immutable_through: str,
) -> dict[str, Any]:
    """Atomically replace a TWSE-validated price suffix and refresh the manifest."""

    package_root = package_root.resolve()
    candidate_path = candidate_path.resolve()
    output_dir = output_dir.resolve()
    runtime_root = (package_root / "runtime").resolve()
    if not candidate_path.is_relative_to(runtime_root) or not output_dir.is_relative_to(runtime_root):
        raise ValueError("Daily-price candidate and journal must remain under runtime/")
    formal_path = package_root / DAILY_TARGET
    manifest_path = package_root / MANIFEST_PATH
    if output_dir.exists():
        raise FileExistsError(output_dir)

    formal_header, formal_rows, _ = read_csv_header_and_rows(formal_path)
    candidate_header, candidate_rows, _ = read_csv_header_and_rows(candidate_path)
    if formal_header != candidate_header:
        raise ValueError("Daily-price reconcile schema mismatch")
    formal_prefix = [row for row in formal_rows if row[0] <= immutable_through]
    candidate_prefix = [row for row in candidate_rows if row[0] <= immutable_through]
    if formal_prefix != candidate_prefix:
        raise ValueError("Daily-price reconcile would rewrite immutable history")
    candidate_dates = [row[0] for row in candidate_rows]
    if candidate_dates != sorted(set(candidate_dates)):
        raise ValueError("Daily-price candidate dates are not unique and increasing")
    for row in (item for item in candidate_rows if item[0] > immutable_through):
        close = _decimal(row[1], field="Close", row_date=row[0])
        bvps = _decimal(row[3], field="BVPS_ref", row_date=row[0])
        pb = _decimal(row[4], field="PB_daily", row_date=row[0])
        if pb != (close / bvps).quantize(Decimal("0.001")):
            raise ValueError(f"Daily-price PB formula mismatch for {row[0]}")
        if row[5] not in {"OFFICIAL_TWSE_A1", "OFFICIAL_TWSE_STOCK_DAY"} or row[6] != "OK":
            raise ValueError(f"Daily-price reconciled row is not governed TWSE authority: {row[0]}")

    candidate_bytes = candidate_path.read_bytes()
    candidate_sha = hashlib.sha256(candidate_bytes).hexdigest().upper()
    manifest = read_json(manifest_path)
    entry = next(
        (item for item in manifest.get("authoritativeFiles", []) if item.get("path") == DAILY_TARGET),
        None,
    )
    formal_sha = sha256_file(formal_path)
    if entry is None or entry.get("sha256") != formal_sha or entry.get("rowCount") != len(formal_rows):
        raise ValueError("Daily-price manifest does not match formal pre-publish CSV")
    published_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry.update(
        {
            "sha256": candidate_sha,
            "fileSizeBytes": len(candidate_bytes),
            "rowCount": len(candidate_rows),
            "lastPublishedAt": published_at,
            "dataProvenance": "OFFICIAL_TWSE_STOCK_DAY_MONTHLY_CSV",
            "dataSupportLevel": "OFFICIAL_TWSE_A1",
            "validationStatus": "PASS",
            "lastIncrementalReconcile": {
                "immutableThrough": immutable_through,
                "start": next(row[0] for row in candidate_rows if row[0] > immutable_through),
                "end": candidate_dates[-1],
                "candidateSha256": candidate_sha,
                "publishedAt": published_at,
                "publisher": "owner_publish_csv_v2.py",
                "mode": "TWSE_DAILY_PRICE_ATOMIC_SUFFIX_RECONCILE",
                "actionable": False,
            },
        }
    )
    entry.setdefault("dateRange", {})["end"] = candidate_dates[-1]
    manifest["approvedAt"] = published_at[:10]
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    output_dir.mkdir(parents=True)
    backup_dir = output_dir / "backup"
    staged_dir = output_dir / "staged"
    backup_dir.mkdir()
    staged_dir.mkdir()
    shutil.copy2(formal_path, backup_dir / formal_path.name)
    shutil.copy2(manifest_path, backup_dir / manifest_path.name)
    (staged_dir / formal_path.name).write_bytes(candidate_bytes)
    (staged_dir / manifest_path.name).write_bytes(manifest_bytes)
    pre_hashes = {DAILY_TARGET: formal_sha, MANIFEST_PATH: sha256_file(manifest_path)}
    journal_path = output_dir / "PUBLISH_JOURNAL.json"
    journal: dict[str, Any] = {
        "mode": "TWSE_DAILY_PRICE_ATOMIC_SUFFIX_RECONCILE",
        "status": "BACKUP_VERIFIED",
        "created_at_utc": published_at,
        "immutable_through": immutable_through,
        "candidate_sha256": candidate_sha,
        "pre_hashes": pre_hashes,
        "actionable": False,
    }
    _atomic_write_json(journal_path, journal)
    try:
        _atomic_write_bytes(formal_path, candidate_bytes)
        _atomic_write_bytes(manifest_path, manifest_bytes)
        published_manifest = read_json(manifest_path)
        published_entry = next(
            item for item in published_manifest.get("authoritativeFiles", [])
            if item.get("path") == DAILY_TARGET
        )
        if sha256_file(formal_path) != candidate_sha or published_entry.get("sha256") != candidate_sha:
            raise ValueError("Daily-price reconcile post-publish validation failed")
        journal.update(
            {
                "status": "PUBLISHED",
                "post_hashes": {DAILY_TARGET: candidate_sha, MANIFEST_PATH: sha256_file(manifest_path)},
                "total_rows": len(candidate_rows),
                "last_date": candidate_dates[-1],
                "rollback_available": True,
                "rollback_performed": False,
            }
        )
        _atomic_write_json(journal_path, journal)
        return journal
    except Exception as publish_error:
        rollback_errors: list[str] = []
        for target, backup in (
            (formal_path, backup_dir / formal_path.name),
            (manifest_path, backup_dir / manifest_path.name),
        ):
            try:
                _atomic_write_bytes(target, backup.read_bytes())
            except Exception as rollback_error:
                rollback_errors.append(f"{target}: {rollback_error}")
        restored = {DAILY_TARGET: sha256_file(formal_path), MANIFEST_PATH: sha256_file(manifest_path)}
        rollback_ok = not rollback_errors and restored == pre_hashes
        journal.update(
            {
                "status": "ROLLED_BACK" if rollback_ok else "ROLLBACK_FAILED",
                "publish_error": str(publish_error),
                "rollback_errors": rollback_errors,
                "restored_hashes": restored,
                "rollback_performed": True,
                "rollback_verified": rollback_ok,
            }
        )
        _atomic_write_json(journal_path, journal)
        if not rollback_ok:
            raise RuntimeError("Daily-price reconcile rollback was incomplete") from publish_error
        raise RuntimeError("Daily-price reconcile failed; CSV and manifest restored") from publish_error


if __name__ == "__main__":
    raise SystemExit(main())
