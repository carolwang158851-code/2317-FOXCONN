"""Reconcile P1008 daily-price authority from verified TWSE monthly receipts."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import owner_publish_csv_v2 as publisher
import warroom_market_activity_updater as twse


PRICE_REL = Path("data/2317_daily_price.csv")
ACTIVITY_REL = Path("data/2317_daily_market_activity.csv")
RUNTIME_REL = Path("runtime/daily_price_incremental")
STATUS_REL = RUNTIME_REL / "latest_status.json"
PRICE_FIELDS = ("Date", "Close", "QuarterKey", "BVPS_ref", "PB_daily", "DataSupportLevel", "Status")
EXIT_OK = 0
EXIT_FAIL_CLOSED = 30


class PriceUpdateFailure(RuntimeError):
    pass


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != PRICE_FIELDS:
            raise PriceUpdateFailure("Formal daily-price CSV schema is invalid")
        rows = [dict(row) for row in reader]
    dates = [row["Date"] for row in rows]
    if not rows or dates != sorted(set(dates)):
        raise PriceUpdateFailure("Formal daily-price dates are not unique and increasing")
    return rows


def activity_last_date(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise PriceUpdateFailure("Formal market-activity authority is empty")
    dates = [row.get("date", "") for row in rows]
    if dates != sorted(set(dates)):
        raise PriceUpdateFailure("Formal market-activity dates are not unique and increasing")
    return dates[-1]


def decimal_text(value: Decimal, places: str) -> str:
    rendered = format(value.quantize(Decimal(places), rounding=ROUND_HALF_UP), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def write_candidate(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PRICE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def run_update(
    package_root: Path,
    *,
    as_of_date: dt.date,
    dry_run: bool = False,
    offline_receipt_dir: Path | None = None,
) -> dict[str, Any]:
    package_root = package_root.resolve()
    price_path = package_root / PRICE_REL
    activity_path = package_root / ACTIVITY_REL
    formal_rows = read_rows(price_path)
    anchor = activity_last_date(activity_path)
    months = twse.month_sequence(anchor[:7], as_of_date.strftime("%Y-%m"))
    run_id = f"P1008-DAILY-PRICE-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    run_dir = package_root / RUNTIME_REL / run_id
    receipts_dir = run_dir / "receipts"
    receipts_dir.mkdir(parents=True)
    receipt_paths: list[str] = []
    http_calls = 0
    twse_rows: dict[str, dict[str, Any]] = {}

    try:
        for month in months:
            if offline_receipt_dir is None:
                content, metadata = twse.fetch_twse_month(month)
                http_calls += 1
            else:
                content, metadata = twse.load_offline_month(offline_receipt_dir, month)
            parsed = twse.parse_twse_month(content, month)
            overlap = set(twse_rows) & set(parsed)
            if overlap:
                raise PriceUpdateFailure(f"Duplicate TWSE dates across months: {sorted(overlap)}")
            twse_rows.update(parsed)
            raw_path = receipts_dir / f"{month}.twse.raw.csv"
            receipt_path = receipts_dir / f"{month}.receipt.json"
            raw_path.write_bytes(content)
            metadata.update(
                {
                    "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                    "parsed_row_count": len(parsed),
                    "raw_artifact_path": str(raw_path.resolve()),
                    "raw_artifact_sha256": twse.sha256_file(raw_path),
                }
            )
            atomic_json(receipt_path, metadata)
            receipt_paths.append(str(receipt_path.resolve()))

        target_dates = sorted(
            day for day in twse_rows if anchor < day <= as_of_date.isoformat()
        )
        if not target_dates:
            formal_by_date = {row["Date"]: row for row in formal_rows}
            if anchor not in twse_rows or anchor not in formal_by_date:
                raise PriceUpdateFailure(f"TWSE month file does not contain eligible price date {anchor}")
            if Decimal(formal_by_date[anchor]["Close"]) != twse_rows[anchor]["close"]:
                raise PriceUpdateFailure(f"TWSE Close does not match price authority for {anchor}")
            result = {
                "run_id": run_id,
                "status": "NO_NEW_DAILY_PRICE",
                "launcher_status": "NO_NEW_DATA",
                "anchor_date": anchor,
                "last_success_date": anchor,
                "twse_latest_validated_trading_date": max(
                    day for day in twse_rows if day <= as_of_date.isoformat()
                ),
                "months_checked": months,
                "missing_dates_detected": [],
                "dates_added": [],
                "non_trading_dates_removed": [],
                "metadata_normalized_dates": [],
                "rows_added": 0,
                "http_calls": http_calls,
                "receipt_paths": receipt_paths,
                "run_dir": str(run_dir.resolve()),
                "dry_run": dry_run,
                "exit_code": EXIT_OK,
                "actionable": False,
            }
            atomic_json(run_dir / "RESULT.json", result)
            atomic_json(package_root / STATUS_REL, result)
            return result
        formal_by_date = {row["Date"]: row for row in formal_rows}
        existing_target_dates = sorted(day for day in formal_by_date if day > anchor)
        conflicting: list[str] = []
        for day in set(existing_target_dates) & set(target_dates):
            if Decimal(formal_by_date[day]["Close"]) != twse_rows[day]["close"]:
                conflicting.append(day)
        if conflicting:
            raise PriceUpdateFailure(f"TWSE Close does not match price authority for {conflicting[0]}")

        base = formal_by_date[anchor]
        bvps = Decimal(base["BVPS_ref"])
        reconciled = [dict(row) for row in formal_rows if row["Date"] <= anchor]
        for day in target_dates:
            close = twse_rows[day]["close"]
            reconciled.append(
                {
                    "Date": day,
                    "Close": format(close.quantize(Decimal("0.0"), rounding=ROUND_HALF_UP), "f"),
                    "QuarterKey": base["QuarterKey"],
                    "BVPS_ref": base["BVPS_ref"],
                    "PB_daily": decimal_text(close / bvps, "0.001"),
                    "DataSupportLevel": "OFFICIAL_TWSE_A1",
                    "Status": "OK",
                }
            )
        removed_dates = sorted(set(existing_target_dates) - set(target_dates))
        added_dates = sorted(set(target_dates) - set(existing_target_dates))
        normalized_dates = sorted(
            day for day in set(existing_target_dates) & set(target_dates)
            if formal_by_date[day] != next(row for row in reconciled if row["Date"] == day)
        )
        candidate_path = run_dir / "2317_daily_price.incremental.candidate.csv"
        write_candidate(candidate_path, reconciled)
        before_hash = twse.sha256_file(price_path)
        candidate_hash = twse.sha256_file(candidate_path)
        if dry_run:
            status = "DRY_RUN_READY"
            last_date = formal_rows[-1]["Date"]
            rows_added = 0
        elif candidate_hash == before_hash:
            status = "NO_NEW_DAILY_PRICE"
            last_date = formal_rows[-1]["Date"]
            rows_added = 0
        else:
            publish = publisher.publish_daily_price_reconcile(
                package_root,
                candidate_path,
                run_dir / "publish",
                immutable_through=anchor,
            )
            status = "UPDATED" if twse.sha256_file(price_path) != before_hash else "NO_NEW_DAILY_PRICE"
            last_date = publish["last_date"]
            rows_added = len(added_dates)
        result = {
            "run_id": run_id,
            "status": status,
            "launcher_status": "UPDATED" if status in {"UPDATED", "DRY_RUN_READY"} else "NO_NEW_DATA",
            "anchor_date": anchor,
            "last_success_date": last_date,
            "twse_latest_validated_trading_date": target_dates[-1],
            "months_checked": months,
            "missing_dates_detected": added_dates,
            "dates_added": added_dates,
            "non_trading_dates_removed": removed_dates,
            "metadata_normalized_dates": normalized_dates,
            "rows_added": rows_added,
            "http_calls": http_calls,
            "receipt_paths": receipt_paths,
            "candidate_path": str(candidate_path.resolve()),
            "candidate_sha256": candidate_hash,
            "run_dir": str(run_dir.resolve()),
            "dry_run": dry_run,
            "exit_code": EXIT_OK,
            "actionable": False,
        }
        atomic_json(run_dir / "RESULT.json", result)
        atomic_json(package_root / STATUS_REL, result)
        return result
    except (PriceUpdateFailure, twse.UpdateFailure, ValueError, OSError) as exc:
        result = {
            "run_id": run_id,
            "status": "DAILY_PRICE_FAIL_CLOSED",
            "launcher_status": "BLOCKED",
            "anchor_date": anchor,
            "months_checked": months,
            "http_calls": http_calls,
            "receipt_paths": receipt_paths,
            "run_dir": str(run_dir.resolve()),
            "dry_run": dry_run,
            "exit_code": EXIT_FAIL_CLOSED,
            "error": str(exc),
            "actionable": False,
        }
        atomic_json(run_dir / "RESULT.json", result)
        atomic_json(package_root / STATUS_REL, result)
        raise PriceUpdateFailure(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--as-of-date", type=dt.date.fromisoformat, default=dt.date.today())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--offline-receipt-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run_update(
            args.package_root,
            as_of_date=args.as_of_date,
            dry_run=args.dry_run,
            offline_receipt_dir=args.offline_receipt_dir,
        )
    except PriceUpdateFailure as exc:
        print(json.dumps({"status": "DAILY_PRICE_FAIL_CLOSED", "error": str(exc), "exit_code": EXIT_FAIL_CLOSED}, ensure_ascii=False))
        return EXIT_FAIL_CLOSED
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
