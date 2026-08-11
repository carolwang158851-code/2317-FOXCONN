"""Fail-closed TWSE authority freshness and continuity gate for P1008."""

from __future__ import annotations

import argparse
import csv
import json
import os
from decimal import Decimal
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


def _rows(path: Path, date_field: str) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    dates = [row.get(date_field, "") for row in rows]
    if not rows or dates != sorted(set(dates)):
        raise FreshnessFailure(f"{path.name}: dates are not unique and increasing")
    return rows, {row[date_field]: row for row in rows}


def validate(package_root: Path, receipt_dir: Path) -> dict[str, Any]:
    package_root = package_root.resolve()
    receipt_dir = receipt_dir.resolve()
    receipts = sorted(receipt_dir.glob("*.receipt.json"))
    if not receipts:
        raise FreshnessFailure(f"receipt validation failed: no receipts under {receipt_dir}")
    twse_rows: dict[str, dict[str, Any]] = {}
    receipt_paths: list[str] = []
    for receipt_path in receipts:
        month = receipt_path.name.removesuffix(".receipt.json")
        content, _ = twse.load_offline_month(receipt_dir, month)
        parsed = twse.parse_twse_month(content, month)
        if set(twse_rows) & set(parsed):
            raise FreshnessFailure(f"receipt validation failed: duplicate TWSE month rows for {month}")
        twse_rows.update(parsed)
        receipt_paths.append(str(receipt_path))
    target = max(twse_rows)
    price_rows, price = _rows(package_root / publisher.DAILY_TARGET, "Date")
    activity_rows, activity = _rows(package_root / publisher.MARKET_ACTIVITY_TARGET, "date")
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
    manifest = publisher.read_json(package_root / publisher.MANIFEST_PATH)
    entries = {entry.get("path"): entry for entry in manifest.get("authoritativeFiles", [])}
    manifest_errors: list[str] = []
    for rel in (publisher.DAILY_TARGET, publisher.MARKET_ACTIVITY_TARGET):
        entry = entries.get(rel)
        actual = publisher.sha256_file(package_root / rel)
        if entry is None or entry.get("sha256") != actual:
            manifest_errors.append(rel)
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
    return {
        "status": "PASS",
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
        "actionable": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--receipt-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = validate(args.package_root, args.receipt_dir)
    except (FreshnessFailure, twse.UpdateFailure, ValueError, OSError) as exc:
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
