#!/usr/bin/env python3
"""Owner-gated CSV publish helper for P1008.

Default mode is review-only. Formal CSV writes require --publish and an exact
typed approval phrase. The helper refuses publication when the DRY_RUN report
contains missing required fields.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


DAILY_TARGET = "data/2317_daily_price.csv"
MACRO_TARGET = "data/macro_snapshot.csv"
MANIFEST_PATH = "data/CSV_AUTHORITY_MANIFEST.json"
MIN_PUBLISH_SCORE = 95
MISSING_SOURCE_VALUES = {"DATA_MISSING", "MISSING", "UNAVAILABLE", "N/A", "NA", "", "CONNECTOR_SOURCE_UNAVAILABLE_CARRY_FORWARD"}


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest().upper()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def latest_staging_dir(package_root: Path) -> Path:
    staging_root = package_root / "staging"
    candidates = [
        path for path in staging_root.iterdir()
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


def append_candidate(candidate: Path, target: Path) -> int:
    candidate_header, candidate_rows, _ = read_csv_header_and_rows(candidate)
    target_header, target_rows, _ = read_csv_header_and_rows(target)
    if candidate_header != target_header:
        raise ValueError(f"Schema mismatch: {candidate} does not match {target}.")
    if not candidate_rows:
        raise ValueError(f"{candidate} contains no candidate rows.")

    key_index = 0
    existing_keys = {row[key_index] for row in target_rows if row}
    duplicate_keys = [row[key_index] for row in candidate_rows if row and row[key_index] in existing_keys]
    if duplicate_keys:
        raise ValueError(f"Append refused: target already contains Date/Key {duplicate_keys}.")

    with target.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        for row in candidate_rows:
            writer.writerow(row)
    return len(candidate_rows)


def row_count(path: Path) -> int:
    _, rows, _ = read_csv_header_and_rows(path)
    return len(rows)


def update_manifest(package_root: Path, touched_targets: list[str], approval_note: str) -> None:
    manifest_path = package_root / MANIFEST_PATH
    manifest = read_json(manifest_path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest["approvedAt"] = now[:10]
    manifest["approvalSource"] = f"{manifest.get('approvalSource', '')}; {approval_note}".strip("; ")

    authoritative = manifest.get("authoritativeFiles", [])
    non_authoritative = manifest.get("nonAuthoritativeFiles", [])
    for target_rel in touched_targets:
        target_path = package_root / target_rel
        digest = sha256_file(target_path)
        size = target_path.stat().st_size
        rows = row_count(target_path)
        updated = False
        for entry in authoritative:
            if entry.get("path") == target_rel:
                entry["sha256"] = digest
                entry["fileSizeBytes"] = size
                entry["rowCount"] = rows
                if target_rel == DAILY_TARGET:
                    _, data_rows, _ = read_csv_header_and_rows(target_path)
                    if data_rows:
                        entry.setdefault("dateRange", {})["end"] = data_rows[-1][0]
                updated = True
        for entry in non_authoritative:
            if entry.get("path") == target_rel:
                entry["sha256"] = digest
                entry["fileSizeBytes"] = size
                entry["rowCount"] = rows
                entry["lastPublishedAt"] = now
                entry["publishApprovalZh"] = "Owner 已核准 append 正式 CSV；本檔仍僅供 MARKET INTELLIGENCE 觀察，不啟用交易規則。"
                updated = True
        if not updated:
            raise ValueError(f"Manifest has no entry for {target_rel}.")
    write_json(manifest_path, manifest)


def resolve_generated_file(package_root: Path, generated: str) -> tuple[Path, str]:
    candidate = package_root / generated.replace("\\", "/")
    name = candidate.name
    if name == "2317_daily_price_candidate.csv":
        return candidate, DAILY_TARGET
    if name == "macro_snapshot_candidate.csv":
        return candidate, MACRO_TARGET
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


def source_coverage_score(input_sources: dict) -> tuple[int, int, int]:
    if not input_sources:
        return 100, 0, 0
    total = len(input_sources)
    available = sum(1 for value in input_sources.values() if str(value).upper() not in MISSING_SOURCE_VALUES)
    return round((available / total) * 100), available, total


def validation_score(validation_checks: list[dict]) -> int:
    if not validation_checks:
        return 50
    return round(sum(status_score(check.get("status", "")) for check in validation_checks) / len(validation_checks))


def inspect_candidate_files(package_root: Path, generated_files: list[str]) -> tuple[list[dict], list[str], int]:
    diagnostics: list[dict] = []
    blockers: list[str] = []
    if not generated_files:
        return diagnostics, ["No generated candidate CSV files were declared."], 0

    for generated in generated_files:
        try:
            candidate_path, target_rel = resolve_generated_file(package_root, generated)
            target_path = package_root / target_rel
            item = {
                "candidate": str(candidate_path),
                "target": target_rel,
                "exists": candidate_path.exists(),
                "targetExists": target_path.exists(),
                "rows": 0,
                "schemaMatch": False,
                "duplicateKeys": [],
                "manifestEntry": False,
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

            existing_keys = {row[0] for row in target_rows if row}
            duplicate_keys = [row[0] for row in candidate_rows if row and row[0] in existing_keys]
            item["duplicateKeys"] = duplicate_keys
            if duplicate_keys:
                blockers.append(f"Append would duplicate Date/Key {duplicate_keys}: {target_rel}")

            item["manifestEntry"] = manifest_has_target(package_root, target_rel)
            if not item["manifestEntry"]:
                blockers.append(f"Manifest has no target entry: {target_rel}")
            diagnostics.append(item)
        except Exception as exc:
            blockers.append(f"Candidate inspection failed for {generated}: {exc}")

    passed = bool(diagnostics) and not blockers
    return diagnostics, blockers, 100 if passed else 0


def build_publish_readiness(package_root: Path, dry_run: dict) -> dict:
    missing_fields = dry_run.get("missingFields", [])
    generated_files = dry_run.get("generatedFiles", [])
    source_score, source_available, source_total = source_coverage_score(dry_run.get("inputSources", {}))
    checks_score = validation_score(dry_run.get("validationChecks", []))
    candidate_diagnostics, candidate_blockers, candidate_score = inspect_candidate_files(package_root, generated_files)
    missing_score = 100 if not missing_fields else max(0, 100 - len(missing_fields) * 20)
    score = round(
        source_score * 0.35
        + checks_score * 0.25
        + candidate_score * 0.25
        + missing_score * 0.15
    )
    blockers = list(candidate_blockers)
    if missing_fields:
        blockers.append(f"Missing critical fields: {', '.join(missing_fields)}")
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
        "missingFieldScore": missing_score,
        "candidateDiagnostics": candidate_diagnostics,
    }


def print_readiness(readiness: dict) -> None:
    print(f"Readiness   : {readiness['score']}% / required {readiness['threshold']}%")
    print(f"Sources     : {readiness['sourceCoverageScore']}% ({readiness['sourceAvailable']}/{readiness['sourceTotal']} available)")
    print(f"Validation  : {readiness['validationScore']}%")
    print(f"Candidates  : {readiness['candidateFileScore']}%")
    print(f"Completeness: {readiness['missingFieldScore']}%")
    for item in readiness["candidateDiagnostics"]:
        duplicate_text = ", ".join(item["duplicateKeys"]) if item["duplicateKeys"] else "none"
        print(
            "Candidate   : "
            f"{Path(item['candidate']).name} -> {item['target']} | "
            f"exists={item['exists']} rows={item['rows']} "
            f"schema={item['schemaMatch']} duplicates={duplicate_text} "
            f"manifest={item['manifestEntry']}"
        )
    if readiness["blockers"]:
        print("Blockers    :")
        for blocker in readiness["blockers"]:
            print(f"  - {blocker}")
    print(f"PUBLISH_ALLOWED: {'YES' if readiness['allowed'] else 'NO'}")


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
    missing_fields = dry_run.get("missingFields", [])
    generated_files = dry_run.get("generatedFiles", [])
    readiness = build_publish_readiness(package_root, dry_run)

    print("===================================================")
    print("P1008 Owner CSV publish checkpoint")
    print("===================================================")
    print(f"Package root : {package_root}")
    print(f"Candidate    : {candidate_date}")
    print(f"DRY_RUN      : {dry_run_path}")
    print(f"Generated    : {', '.join(generated_files) if generated_files else 'none'}")
    print(f"Missing      : {', '.join(missing_fields) if missing_fields else 'none'}")
    print("Formal CSV modified by review mode: NO")
    print("---------------------------------------------------")
    print_readiness(readiness)
    print()

    if not readiness["allowed"]:
        print("[BLOCKED] Candidate does not meet formal CSV publish standard.")
        print("          Formal CSV publish is refused before Owner approval prompt.")
        print("          Keep this candidate as runtime /盤中觀察 until blockers are fixed.")
        return 3
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
        candidate_path, target_rel = resolve_generated_file(package_root, generated)
        target_path = package_root / target_rel
        if not candidate_path.exists():
            raise FileNotFoundError(candidate_path)
        if not target_path.exists():
            raise FileNotFoundError(target_path)
        shutil.copy2(target_path, backup_dir / target_path.name)
        rows_added = append_candidate(candidate_path, target_path)
        total_rows += rows_added
        touched_targets.append(target_rel)
        print(f"[APPENDED] {rows_added} row(s): {candidate_path} -> {target_path}")

    approval_note = f"Owner approval {candidate_date} via tools/owner_publish_csv.py; appended {total_rows} row(s)"
    update_manifest(package_root, touched_targets, approval_note)
    report = {
        "publishedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "candidateDate": candidate_date,
        "touchedTargets": touched_targets,
        "rowsAdded": total_rows,
        "actionable": False,
        "noteZh": "Owner 已核准正式 CSV append；交易規則仍維持 actionable:false。",
    }
    write_json(staging_dir / "OWNER_PUBLISH_REPORT.json", report)
    print("[OK] Formal CSV append completed and manifest was updated.")
    print("[NEXT] Reopen with 2_開啟戰情室網頁.bat and verify formal baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
