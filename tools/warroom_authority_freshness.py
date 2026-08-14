"""Fail-closed TWSE authority freshness and continuity gate for P1008."""

from __future__ import annotations

import argparse
import csv
import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import owner_publish_csv_v2 as publisher
import warroom_market_activity_updater as twse


STATUS_REL = Path("runtime/authority_freshness/latest_status.json")
EXIT_OK = 0
EXIT_STALE = 20


class FreshnessFailure(RuntimeError):
    pass


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _rows(
    path: Path,
    date_field: str,
    expected_fields: tuple[str, ...] | None = None,
) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if expected_fields is not None and tuple(reader.fieldnames or ()) != expected_fields:
            raise FreshnessFailure(f"{path.name}: candidate schema is invalid")
        rows = list(reader)
    dates = [row.get(date_field, "") for row in rows]
    if not rows or dates != sorted(set(dates)):
        raise FreshnessFailure(f"{path.name}: dates are not unique and increasing")
    return rows, {row[date_field]: row for row in rows}


def _within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _formal_manifest_errors(package_root: Path) -> list[str]:
    manifest = publisher.read_json(package_root / publisher.MANIFEST_PATH)
    entries = {entry.get("path"): entry for entry in manifest.get("authoritativeFiles", [])}
    errors: list[str] = []
    for rel in (publisher.DAILY_TARGET, publisher.MARKET_ACTIVITY_TARGET):
        entry = entries.get(rel)
        actual = publisher.sha256_file(package_root / rel)
        if entry is None or entry.get("sha256") != actual:
            errors.append(rel)
    return errors


def _load_twse_receipts(receipt_dir: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    receipts = sorted(receipt_dir.glob("*.receipt.json"))
    if not receipts:
        raise FreshnessFailure(f"receipt validation failed: no receipts under {receipt_dir}")
    rows: dict[str, dict[str, Any]] = {}
    paths: list[str] = []
    for receipt_path in receipts:
        month = receipt_path.name.removesuffix(".receipt.json")
        content, _ = twse.load_offline_month(receipt_dir, month)
        parsed = twse.parse_twse_month(content, month)
        if set(rows) & set(parsed):
            raise FreshnessFailure(f"receipt validation failed: duplicate TWSE month rows for {month}")
        rows.update(parsed)
        paths.append(str(receipt_path))
    return rows, paths


def _governed_result(
    package_root: Path,
    *,
    kind: str,
    run_dir: Path,
    run_id: str,
    candidate_name: str,
) -> tuple[dict[str, Any], Path, Path]:
    allowed_root = (package_root / "runtime" / kind).resolve()
    resolved = run_dir.resolve()
    if resolved.parent != allowed_root or resolved.name != run_id:
        raise FreshnessFailure(f"{kind}: run lineage is outside the governed runtime root")
    result_path = resolved / "RESULT.json"
    if not result_path.is_file():
        raise FreshnessFailure(f"{kind}: RESULT.json is missing")
    result = publisher.read_json(result_path)
    if (
        result.get("run_id") != run_id
        or result.get("run_dir") is None
        or Path(str(result["run_dir"])).resolve() != resolved
        or result.get("status") != "DRY_RUN_READY"
        or result.get("launcher_status") != "UPDATED"
        or result.get("dry_run") is not True
        or result.get("exit_code") != EXIT_OK
        or result.get("actionable") is not False
    ):
        raise FreshnessFailure(f"{kind}: RESULT.json is not a trusted dry-run result")
    candidate_value = result.get("candidate_path")
    expected_sha = result.get("candidate_sha256")
    if not isinstance(candidate_value, str) or not isinstance(expected_sha, str):
        raise FreshnessFailure(f"{kind}: candidate provenance is incomplete")
    candidate = Path(candidate_value).resolve()
    if (
        candidate.parent != resolved
        or candidate.name != candidate_name
        or not candidate.is_file()
        or publisher.sha256_file(candidate) != expected_sha
    ):
        raise FreshnessFailure(f"{kind}: candidate path or SHA is invalid")
    receipts_dir = resolved / "receipts"
    receipt_values = result.get("receipt_paths")
    if not isinstance(receipt_values, list) or not receipt_values:
        raise FreshnessFailure(f"{kind}: TWSE receipt lineage is missing")
    declared = {Path(str(value)).resolve() for value in receipt_values}
    actual = set(receipts_dir.glob("*.receipt.json"))
    if declared != actual:
        raise FreshnessFailure(f"{kind}: TWSE receipt paths do not match the governed run")
    for receipt_path in declared:
        if not _within(receipt_path, receipts_dir):
            raise FreshnessFailure(f"{kind}: TWSE receipt is outside the governed run")
        receipt = publisher.read_json(receipt_path)
        month = receipt_path.name.removesuffix(".receipt.json")
        raw_path = receipts_dir / f"{month}.twse.raw.csv"
        if (
            receipt.get("status") != "SUCCESS"
            or receipt.get("http_status") != 200
            or receipt.get("request_url") != twse.source_url(month)
            or not raw_path.is_file()
            or receipt.get("raw_artifact_sha256") != publisher.sha256_file(raw_path)
        ):
            raise FreshnessFailure(f"{kind}: TWSE receipt/raw provenance is invalid for {month}")
    return result, candidate, receipts_dir


def _validate_effective(
    *,
    twse_rows: dict[str, dict[str, Any]],
    price_rows: list[dict[str, str]],
    price: dict[str, dict[str, str]],
    activity_rows: list[dict[str, str]],
    activity: dict[str, dict[str, str]],
    manifest_errors: list[str],
    receipt_dir: Path,
) -> tuple[str, str, str]:
    target = max(twse_rows)
    missing_price = sorted(day for day in twse_rows if day not in price)
    missing_activity = sorted(day for day in twse_rows if day not in activity)
    close_mismatches = sorted(
        day for day in twse_rows
        if day in price and Decimal(price[day]["Close"]) != twse_rows[day]["close"]
    )
    activity_mismatches = sorted(
        day for day in twse_rows
        if day in activity and any(
            int(activity[day][field]) != int(twse_rows[day][field])
            for field in ("trade_volume", "trade_value", "transaction_count")
        )
    )
    checked_months = {day[:7] for day in twse_rows}
    synthetic_price = sorted(
        row["Date"] for row in price_rows
        if row["Date"][:7] in checked_months and row["Date"] not in twse_rows
    )
    price_last = price_rows[-1]["Date"]
    activity_last = activity_rows[-1]["date"]
    if missing_price or missing_activity or close_mismatches or activity_mismatches or synthetic_price or manifest_errors:
        raise FreshnessFailure(
            "dataset=TWSE_AUTHORITY; "
            f"local_price_max={price_last}; local_market_activity_max={activity_last}; "
            f"twse_target={target}; missing_price={missing_price}; "
            f"missing_market_activity={missing_activity}; close_mismatches={close_mismatches}; "
            f"market_activity_mismatches={activity_mismatches}; synthetic_price_dates={synthetic_price}; "
            f"manifest_errors={manifest_errors}; receipt_dir={receipt_dir}; "
            "recommended_remediation=run governed TWSE price and market-activity incremental updaters"
        )
    if price_last != target or activity_last != target:
        raise FreshnessFailure(
            "dataset=TWSE_AUTHORITY; "
            f"local_price_max={price_last}; local_market_activity_max={activity_last}; twse_target={target}; "
            f"missing_dates=[]; receipt_dir={receipt_dir}; recommended_remediation=complete authority continuity"
        )
    return target, price_last, activity_last


def validate(package_root: Path, receipt_dir: Path) -> dict[str, Any]:
    package_root = package_root.resolve()
    receipt_dir = receipt_dir.resolve()
    twse_rows, receipt_paths = _load_twse_receipts(receipt_dir)
    price_rows, price = _rows(package_root / publisher.DAILY_TARGET, "Date")
    activity_rows, activity = _rows(package_root / publisher.MARKET_ACTIVITY_TARGET, "date")
    target, price_last, activity_last = _validate_effective(
        twse_rows=twse_rows,
        price_rows=price_rows,
        price=price,
        activity_rows=activity_rows,
        activity=activity,
        manifest_errors=_formal_manifest_errors(package_root),
        receipt_dir=receipt_dir,
    )
    return {
        "status": "PASS",
        "freshness_scope": "FORMAL_AUTHORITY",
        "formal_authority_current": True,
        "price": "PASS",
        "market_activity": "PASS",
        "manifest": "PASS",
        "freshness": "PASS",
        "twse_latest_validated_trading_date": target,
        "price_formal_last_date": price_last,
        "market_activity_formal_last_date": activity_last,
        "receipt_paths": receipt_paths,
        "missing_price_dates": [],
        "missing_market_activity_dates": [],
        "synthetic_price_dates": [],
        "exit_code": EXIT_OK,
        "research_input_ready": True,
        "owner_publish_required": False,
        "actionable": False,
    }


def validate_candidate_overlay(
    package_root: Path,
    *,
    daily_price_run_dir: Path,
    daily_price_run_id: str,
    market_activity_run_dir: Path,
    market_activity_run_id: str,
) -> dict[str, Any]:
    package_root = package_root.resolve()
    manifest_errors = _formal_manifest_errors(package_root)
    formal_price_rows, _ = _rows(package_root / publisher.DAILY_TARGET, "Date")
    formal_activity_rows, _ = _rows(package_root / publisher.MARKET_ACTIVITY_TARGET, "date")
    daily_result, daily_candidate, daily_receipts = _governed_result(
        package_root,
        kind="daily_price_incremental",
        run_dir=daily_price_run_dir,
        run_id=daily_price_run_id,
        candidate_name="2317_daily_price.incremental.candidate.csv",
    )
    market_result, market_candidate, market_receipts = _governed_result(
        package_root,
        kind="market_activity_incremental",
        run_dir=market_activity_run_dir,
        run_id=market_activity_run_id,
        candidate_name="2317_daily_market_activity.incremental.candidate.csv",
    )
    provenance = market_result.get("price_validation_provenance")
    if not isinstance(provenance, dict) or (
        provenance.get("source") != "SAME_RUN_DAILY_PRICE_STAGING"
        or provenance.get("daily_price_run_id") != daily_price_run_id
        or Path(str(provenance.get("daily_price_run_dir", ""))).resolve() != daily_price_run_dir.resolve()
        or provenance.get("daily_price_candidate_sha256") != daily_result.get("candidate_sha256")
        or {Path(str(value)).resolve() for value in provenance.get("daily_price_receipt_paths", [])}
        != {Path(str(value)).resolve() for value in daily_result.get("receipt_paths", [])}
    ):
        raise FreshnessFailure("market_activity_incremental: same-run Daily Price validation provenance is invalid")

    price_rows, price = _rows(daily_candidate, "Date", twse.PRICE_CANDIDATE_FIELDS)
    incremental_rows, incremental = _rows(market_candidate, "date", twse.FORMAL_FIELDS)
    formal_activity = {row["date"]: row for row in formal_activity_rows}
    overlap = set(formal_activity) & set(incremental)
    if overlap:
        raise FreshnessFailure(f"market_activity_incremental: candidate rewrites formal dates {sorted(overlap)}")
    effective_activity_rows = sorted(formal_activity_rows + incremental_rows, key=lambda row: row["date"])
    effective_activity = {row["date"]: row for row in effective_activity_rows}

    daily_twse, daily_receipt_paths = _load_twse_receipts(daily_receipts)
    market_twse, market_receipt_paths = _load_twse_receipts(market_receipts)
    daily_target = max(daily_twse)
    market_target = max(market_twse)
    if daily_target != market_target:
        raise FreshnessFailure(
            f"candidate target disagreement: daily_price={daily_target}; market_activity={market_target}"
        )
    if (
        daily_result.get("twse_latest_validated_trading_date") != daily_target
        or market_result.get("candidate_last_date") != market_target
        or price_rows[-1]["Date"] != daily_target
        or incremental_rows[-1]["date"] != market_target
    ):
        raise FreshnessFailure("candidate target does not equal the latest validated TWSE target")
    if set(daily_twse) != set(market_twse) or any(
        daily_twse[day] != market_twse[day] for day in daily_twse
    ):
        raise FreshnessFailure("Daily Price and Market Activity TWSE receipt evidence disagrees")

    target, _, _ = _validate_effective(
        twse_rows=market_twse,
        price_rows=price_rows,
        price=price,
        activity_rows=effective_activity_rows,
        activity=effective_activity,
        manifest_errors=manifest_errors,
        receipt_dir=market_receipts,
    )
    return {
        "status": "PASS_CANDIDATE_OVERLAY",
        "freshness_scope": "CANDIDATE_OVERLAY",
        "formal_authority_current": False,
        "candidate_validated_through": target,
        "twse_latest_validated_trading_date": target,
        "formal_price_through": formal_price_rows[-1]["Date"],
        "formal_market_activity_through": formal_activity_rows[-1]["date"],
        "daily_price_run_id": daily_price_run_id,
        "market_activity_run_id": market_activity_run_id,
        "receipt_paths": sorted(set(daily_receipt_paths + market_receipt_paths)),
        "manifest": "PASS",
        "freshness": "PASS",
        "exit_code": EXIT_OK,
        "owner_publish_required": True,
        "research_input_ready": True,
        "actionable": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--receipt-dir", type=Path)
    parser.add_argument("--daily-price-run-dir", type=Path)
    parser.add_argument("--daily-price-run-id")
    parser.add_argument("--market-activity-run-dir", type=Path)
    parser.add_argument("--market-activity-run-id")
    args = parser.parse_args(argv)
    try:
        overlay_values = (
            args.daily_price_run_dir,
            args.daily_price_run_id,
            args.market_activity_run_dir,
            args.market_activity_run_id,
        )
        if any(overlay_values):
            if not all(overlay_values):
                raise FreshnessFailure("candidate-overlay mode requires both governed run IDs and run directories")
            result = validate_candidate_overlay(
                args.package_root,
                daily_price_run_dir=args.daily_price_run_dir,
                daily_price_run_id=args.daily_price_run_id,
                market_activity_run_dir=args.market_activity_run_dir,
                market_activity_run_id=args.market_activity_run_id,
            )
        elif args.receipt_dir is not None:
            result = validate(args.package_root, args.receipt_dir)
        else:
            raise FreshnessFailure("formal mode requires --receipt-dir")
    except (
        FreshnessFailure,
        twse.UpdateFailure,
        InvalidOperation,
        KeyError,
        ValueError,
        OSError,
    ) as exc:
        result = {
            "status": "FAIL_CLOSED",
            "error": str(exc),
            "exit_code": EXIT_STALE,
            "research_input_ready": False,
            "actionable": False,
        }
        atomic_json(args.package_root / STATUS_REL, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return EXIT_STALE
    atomic_json(args.package_root / STATUS_REL, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
