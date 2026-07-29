"""TWSE-only importer for a candidate 2317 daily market-activity CSV.

Network access is fail-closed unless an Owner explicitly supplies both the
network flag and approval token.  The importer never writes the formal CSV;
Owner publication remains a separate workflow.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import urllib.request
from pathlib import Path
from typing import Callable

from warroom_market_activity import CSV_FIELDS, MarketActivityValidationError, validate_activity_rows


ENDPOINT_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
OWNER_APPROVAL_TOKEN = "OWNER_APPROVE_TWSE_MARKET_ACTIVITY_BACKFILL"
FORMAL_FILENAME = "2317_daily_market_activity.csv"


class NetworkBackfillNotApproved(PermissionError):
    pass


def roc_date_to_iso(value: str) -> str:
    candidate = value.strip()
    if len(candidate) != 7 or not candidate.isdigit():
        raise MarketActivityValidationError("TWSE Date must be a seven-digit ROC date")
    try:
        return dt.date(int(candidate[:3]) + 1911, int(candidate[3:5]), int(candidate[5:])).isoformat()
    except ValueError as exc:
        raise MarketActivityValidationError("TWSE Date is invalid") from exc


def normalize_twse_payload(
    payload: object,
    *,
    retrieved_at_utc: str,
    as_of_date: dt.date,
) -> list[dict[str, object]]:
    if not isinstance(payload, list):
        raise MarketActivityValidationError("TWSE OpenAPI response must be an array")
    selected = [row for row in payload if isinstance(row, dict) and row.get("Code") == "2317"]
    if len(selected) != 1:
        raise MarketActivityValidationError("TWSE response must contain exactly one Code=2317 row")
    source = selected[0]
    required = {"Date", "Code", "TradeVolume", "TradeValue", "Transaction"}
    if not required.issubset(source):
        raise MarketActivityValidationError("TWSE response is missing market-activity fields")
    row = {
        "trade_date": roc_date_to_iso(str(source["Date"])),
        "ticker": str(source["Code"]),
        "volume_shares": source["TradeVolume"],
        "turnover_ntd": source["TradeValue"],
        "transaction_count": source["Transaction"],
        "source_url": ENDPOINT_URL,
        "retrieved_at_utc": retrieved_at_utc,
    }
    return validate_activity_rows([row], as_of_date=as_of_date)


def fetch_payload(
    *,
    allow_network: bool,
    owner_approval: str | None,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> tuple[object, str]:
    if not allow_network or owner_approval != OWNER_APPROVAL_TOKEN:
        raise NetworkBackfillNotApproved("TWSE network backfill requires explicit Owner approval")
    request = urllib.request.Request(
        ENDPOINT_URL,
        headers={"Accept": "application/json", "User-Agent": "P1008-Market-Activity/1.0"},
    )
    with opener(request, timeout=30) as response:
        body = response.read()
    return json.loads(body.decode("utf-8-sig")), dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def write_candidate(path: Path, rows: list[dict[str, object]]) -> None:
    if path.name == FORMAL_FILENAME or path.exists():
        raise MarketActivityValidationError("formal or existing CSV cannot be overwritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--owner-approval")
    parser.add_argument("--as-of-date", type=dt.date.fromisoformat, required=True)
    args = parser.parse_args(argv)
    payload, retrieved_at = fetch_payload(
        allow_network=args.allow_network,
        owner_approval=args.owner_approval,
    )
    rows = normalize_twse_payload(
        payload, retrieved_at_utc=retrieved_at, as_of_date=args.as_of_date
    )
    write_candidate(args.output.resolve(), rows)
    print(json.dumps({"status": "CANDIDATE_WRITTEN", "rows": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
