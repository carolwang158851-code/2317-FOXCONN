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
import json
import shutil
from datetime import datetime, timezone
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
    if target_rel in OBSERVATION_ONLY_TARGETS:
        actionable_errors = actionability_violations(candidate_header, candidate_rows)
        if actionable_errors:
            raise ValueError(f"Append refused: observation-only rows must keep Actionable=false ({actionable_errors}).")
        source_tier_errors = source_tier_violations(candidate_header, candidate_rows)
        if source_tier_errors:
            raise ValueError(f"Append refused: observation-only rows must have an approved SourceTier ({source_tier_errors}).")

    existing_keys = {row_key(target_rel, target_header, row) for row in target_rows if row}
    duplicate_keys = [row_key(target_rel, candidate_header, row) for row in candidate_rows if row and row_key(target_rel, candidate_header, row) in existing_keys]
    if duplicate_keys:
        raise ValueError(f"Append refused: target already contains Date/Key {duplicate_keys}.")

    needs_newline = target.stat().st_size > 0 and target.read_bytes()[-1:] not in {b"\n", b"\r"}
    with target.open("a", encoding="utf-8", newline="") as handle:
        if needs_newline:
            handle.write("\n")
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerows(candidate_rows)
    return len(candidate_rows)


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Review or publish P1008 staging CSV candidates.")
    parser.add_argument("--package-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--date", help="Staging date, for example 2026-06-29. Defaults to latest staging date.")
    parser.add_argument("--publish", action="store_true", help="Append candidate rows into formal CSV files.")
    args = parser.parse_args()

    package_root = args.package_root.resolve()
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


if __name__ == "__main__":
    raise SystemExit(main())
