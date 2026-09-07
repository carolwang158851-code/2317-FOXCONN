"""Incrementally update P1008 formal market activity from official TWSE monthly CSVs.

The updater is fail-closed, uses at most three monthly requests, never retries,
and delegates formal CSV/manifest mutation to owner_publish_csv_v2.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import http.client
import json
import os
import ssl
import sys
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

import owner_publish_csv_v2 as publisher


TWSE_HOST = "www.twse.com.tw"
TWSE_PATH = "/rwd/zh/afterTrading/STOCK_DAY"
FORMAL_REL = Path("data/2317_daily_market_activity.csv")
PRICE_REL = Path("data/2317_daily_price.csv")
STATUS_REL = Path("runtime/market_activity_incremental/latest_status.json")
RUNTIME_REL = Path("runtime/market_activity_incremental")
FORMAL_FIELDS = publisher.MARKET_ACTIVITY_FIELDS
PRICE_CANDIDATE_FIELDS = (
    "Date", "Close", "QuarterKey", "BVPS_ref", "PB_daily", "DataSupportLevel", "Status"
)

STATUS_UPDATED = "UPDATED"
STATUS_NO_NEW = "NO_NEW_MARKET_ACTIVITY"
STATUS_STALE = "MARKET_ACTIVITY_STALE"
STATUS_BLOCKED = "MARKET_ACTIVITY_BLOCKED_BY_DAILY_PRICE"
STATUS_LIMITED = "MARKET_LIQUIDITY_ANALYSIS_LIMITED"
STATUS_READY = "MARKET_LIQUIDITY_ANALYSIS_READY"

EXIT_OK = 0
EXIT_BLOCKED = 20
EXIT_FAIL_CLOSED = 30
EXIT_LOCKED = 31


class UpdateFailure(RuntimeError):
    def __init__(self, message: str, *, status: str = STATUS_STALE, exit_code: int = EXIT_FAIL_CLOSED):
        super().__init__(message)
        self.status = status
        self.exit_code = exit_code


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest().upper()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def month_sequence(start_month: str, end_month: str) -> list[str]:
    try:
        start = dt.date.fromisoformat(start_month + "-01")
        end = dt.date.fromisoformat(end_month + "-01")
    except ValueError as exc:
        raise UpdateFailure("Invalid month boundary") from exc
    if end < start:
        raise UpdateFailure("as-of month is earlier than formal market-activity month")
    months: list[str] = []
    current = start
    while current <= end:
        months.append(current.strftime("%Y-%m"))
        current = dt.date(current.year + (current.month == 12), 1 if current.month == 12 else current.month + 1, 1)
    if len(months) > 3:
        raise UpdateFailure("More than three TWSE months are required; historical backfill approval is required")
    return months


def source_url(month: str) -> str:
    query = urlencode(
        {
            "date": month.replace("-", "") + "01",
            "stockNo": "2317",
            "response": "csv",
        }
    )
    return f"https://{TWSE_HOST}{TWSE_PATH}?{query}"


def approved_redirect_url(location: str, request_url: str) -> str:
    """Allow one redirect only when it preserves the governed TWSE request."""
    if not location:
        raise UpdateFailure("TWSE redirect has no Location header")
    target = urlsplit(urljoin(request_url, location))
    requested = urlsplit(request_url)
    if (
        target.scheme != "https"
        or target.hostname != TWSE_HOST
        or target.port not in (None, 443)
        or target.username is not None
        or target.password is not None
        or target.fragment
        or target.path != TWSE_PATH
        or parse_qsl(target.query, keep_blank_values=True)
        != parse_qsl(requested.query, keep_blank_values=True)
    ):
        raise UpdateFailure(f"TWSE redirect target is not approved: {location}")
    return target.geturl()


def parse_twse_month(content: bytes, month: str) -> dict[str, dict[str, Any]]:
    try:
        text = content.decode("cp950", errors="strict")
    except UnicodeDecodeError as exc:
        raise UpdateFailure(f"TWSE {month} response is not valid CP950") from exc
    rows = list(csv.reader(text.splitlines()))
    if not rows or "2317" not in "".join(rows[0]):
        raise UpdateFailure(f"TWSE {month} response is not the 2317 STOCK_DAY CSV")
    parsed: dict[str, dict[str, Any]] = {}
    for row in rows[2:]:
        if not row or len(row) < 9 or "/" not in row[0]:
            continue
        try:
            roc_year, row_month, row_day = (int(part) for part in row[0].split("/"))
            trade_date = dt.date(roc_year + 1911, row_month, row_day).isoformat()
        except ValueError as exc:
            raise UpdateFailure(f"Invalid TWSE date in {month}: {row[0]!r}") from exc
        if trade_date[:7] != month or trade_date in parsed:
            raise UpdateFailure(f"TWSE date month/uniqueness violation: {trade_date}")
        integers: list[int] = []
        for name, raw in (("trade_volume", row[1]), ("trade_value", row[2]), ("transaction_count", row[8])):
            normalized = raw.replace(",", "").strip()
            if not normalized.isdigit():
                raise UpdateFailure(f"Invalid {name} for {trade_date}")
            integers.append(int(normalized))
        try:
            close = Decimal(row[6].replace(",", "").strip())
        except InvalidOperation as exc:
            raise UpdateFailure(f"Invalid TWSE Close for {trade_date}") from exc
        if not close.is_finite() or close <= 0:
            raise UpdateFailure(f"Invalid TWSE Close for {trade_date}")
        parsed[trade_date] = {
            "date": trade_date,
            "stock_id": "2317",
            "trade_volume": integers[0],
            "trade_value": integers[1],
            "transaction_count": integers[2],
            "source_url": source_url(month),
            "source_month": month,
            "close": close,
        }
    if not parsed:
        raise UpdateFailure(f"TWSE {month} response has no data rows")
    return parsed


def fetch_twse_month(month: str, timeout_seconds: int = 30) -> tuple[bytes, dict[str, Any]]:
    """Perform a verified HTTPS GET with at most one governed redirect."""

    context = ssl.create_default_context()
    path = f"{TWSE_PATH}?{urlencode({'date': month.replace('-', '') + '01', 'stockNo': '2317', 'response': 'csv'})}"
    request_url = source_url(month)
    connection: http.client.HTTPSConnection | None = None
    try:
        def request_once(request_path: str) -> tuple[Any, bytes, str, dict[str, Any]]:
            nonlocal connection
            connection = http.client.HTTPSConnection(
                TWSE_HOST, timeout=timeout_seconds, context=context
            )
            connection.request(
                "GET",
                request_path,
                headers={"Accept": "text/csv", "User-Agent": "P1008-Market-Activity/1.0"},
            )
            response = connection.getresponse()
            sock = connection.sock
            tls = sock.version() if sock else "NOT_AVAILABLE"
            cert = sock.getpeercert() if sock else {}
            return response, response.read(), tls, cert

        response, content, tls_version, certificate = request_once(path)
        final_url = request_url
        redirect_status: int | None = None
        redirect_location: str | None = None
        if response.status == 307:
            redirect_status = response.status
            redirect_location = response.getheader("Location")
            final_url = approved_redirect_url(str(redirect_location or ""), request_url)
            connection.close()
            connection = None
            target = urlsplit(final_url)
            redirected_path = target.path + (f"?{target.query}" if target.query else "")
            response, content, tls_version, certificate = request_once(redirected_path)
        if response.status != 200:
            raise UpdateFailure(f"TWSE {month} HTTP status {response.status}")
        issuer = ", ".join("=".join(item) for group in certificate.get("issuer", ()) for item in group)
        subject = ", ".join("=".join(item) for group in certificate.get("subject", ()) for item in group)
        metadata = {
            "month": month,
            "request_url": request_url,
            "final_url": final_url,
            "http_status": response.status,
            "https_get_count": 2 if redirect_status is not None else 1,
            "redirect_status": redirect_status,
            "redirect_location": redirect_location,
            "max_retries": 0,
            "tls_version": tls_version,
            "certificate_issuer": issuer,
            "certificate_subject": subject,
            "certificate_not_before": certificate.get("notBefore", "NOT_AVAILABLE"),
            "certificate_not_after": certificate.get("notAfter", "NOT_AVAILABLE"),
            "response_encoding": "cp950",
            "response_bytes": len(content),
            "raw_sha256": sha256_bytes(content),
            "status": "SUCCESS",
        }
        return content, metadata
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise UpdateFailure(f"TWSE {month} HTTPS/TLS failure: {type(exc).__name__}: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()


def load_offline_month(receipt_dir: Path, month: str) -> tuple[bytes, dict[str, Any]]:
    raw_path = receipt_dir / f"{month}.twse.raw.csv"
    receipt_path = receipt_dir / f"{month}.receipt.json"
    if not raw_path.is_file() or not receipt_path.is_file():
        raise UpdateFailure(f"Offline TWSE fixture is missing for {month}")
    content = raw_path.read_bytes()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    raw_sha = sha256_bytes(content)
    if receipt.get("status") not in {"SUCCESS", "SUCCESS_OFFLINE_RECEIPT"} or receipt.get("request_url") != source_url(month):
        raise UpdateFailure(f"Offline TWSE receipt validation failed for {month}")
    expected_sha = receipt.get("raw_artifact_sha256") or receipt.get("raw_sha256")
    if expected_sha != raw_sha:
        raise UpdateFailure(f"Offline TWSE raw SHA mismatch for {month}")
    return content, {
        "month": month,
        "request_url": source_url(month),
        "http_status": receipt.get("http_status", 200),
        "https_get_count": 0,
        "max_retries": 0,
        "tls_version": receipt.get("tls_version", "OFFLINE_RECEIPT"),
        "certificate_issuer": receipt.get("certificate_issuer", "OFFLINE_RECEIPT"),
        "certificate_subject": receipt.get("certificate_subject", "OFFLINE_RECEIPT"),
        "certificate_not_before": receipt.get("certificate_not_before", "OFFLINE_RECEIPT"),
        "certificate_not_after": receipt.get("certificate_not_after", "OFFLINE_RECEIPT"),
        "response_encoding": "cp950",
        "response_bytes": len(content),
        "raw_sha256": raw_sha,
        "status": "SUCCESS_OFFLINE_RECEIPT",
    }


def read_formal_activity(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != FORMAL_FIELDS:
            raise UpdateFailure("Formal market-activity CSV schema is invalid")
        rows = [dict(row) for row in reader]
    dates = [row["date"] for row in rows]
    if not rows or dates != sorted(set(dates)):
        raise UpdateFailure("Formal market-activity dates are not unique and increasing")
    return rows


def read_price(path: Path) -> dict[str, Decimal]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    output: dict[str, Decimal] = {}
    for row in rows:
        row_date = row.get("Date", "")
        if row_date in output:
            raise UpdateFailure(f"Duplicate price authority date: {row_date}")
        try:
            output[row_date] = Decimal(row.get("Close", ""))
        except InvalidOperation as exc:
            raise UpdateFailure(f"Invalid price Close for {row_date}") from exc
    return output


def _resolved_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def load_same_run_price_staging(
    package_root: Path,
    *,
    daily_price_run_dir: Path,
    daily_price_run_id: str,
    as_of_date: dt.date,
    activity_anchor_date: str,
) -> tuple[dict[str, Decimal], dict[str, Any]]:
    """Load only the validated Daily Price candidate from this Launcher run."""

    allowed_root = package_root / "runtime" / "daily_price_incremental"
    run_dir = daily_price_run_dir.resolve()
    if not _resolved_within(run_dir, allowed_root) or run_dir.parent != allowed_root.resolve():
        raise UpdateFailure("Daily Price staging lineage is outside the governed runtime root", status=STATUS_BLOCKED, exit_code=EXIT_BLOCKED)
    result_path = run_dir / "RESULT.json"
    if not result_path.is_file():
        raise UpdateFailure("Daily Price staging RESULT.json is missing", status=STATUS_BLOCKED, exit_code=EXIT_BLOCKED)
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateFailure("Daily Price staging RESULT.json is invalid", status=STATUS_BLOCKED, exit_code=EXIT_BLOCKED) from exc
    if (
        result.get("run_id") != daily_price_run_id
        or run_dir.name != daily_price_run_id
        or result.get("status") != "DRY_RUN_READY"
        or result.get("dry_run") is not True
        or result.get("exit_code") != EXIT_OK
        or result.get("actionable") is not False
        or result.get("anchor_date") != activity_anchor_date
    ):
        raise UpdateFailure("Daily Price staging lineage or validation status is not trusted", status=STATUS_BLOCKED, exit_code=EXIT_BLOCKED)
    candidate_value = result.get("candidate_path")
    candidate_sha = result.get("candidate_sha256")
    if not isinstance(candidate_value, str) or not isinstance(candidate_sha, str):
        raise UpdateFailure("Daily Price staging candidate provenance is incomplete", status=STATUS_BLOCKED, exit_code=EXIT_BLOCKED)
    candidate_path = Path(candidate_value)
    if not candidate_path.is_file() or not _resolved_within(candidate_path, run_dir):
        raise UpdateFailure("Daily Price staging candidate is missing or outside its run", status=STATUS_BLOCKED, exit_code=EXIT_BLOCKED)
    if candidate_path.name != "2317_daily_price.incremental.candidate.csv" or sha256_file(candidate_path) != candidate_sha:
        raise UpdateFailure("Daily Price staging candidate SHA does not match its receipt", status=STATUS_BLOCKED, exit_code=EXIT_BLOCKED)
    with candidate_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != PRICE_CANDIDATE_FIELDS:
            raise UpdateFailure("Daily Price staging candidate schema is invalid", status=STATUS_BLOCKED, exit_code=EXIT_BLOCKED)
        candidate_rows = [dict(row) for row in reader]
    candidate_dates = [row["Date"] for row in candidate_rows]
    if not candidate_rows or candidate_dates != sorted(set(candidate_dates)):
        raise UpdateFailure("Daily Price staging candidate dates are not unique and increasing", status=STATUS_BLOCKED, exit_code=EXIT_BLOCKED)
    try:
        candidate_price = {row["Date"]: Decimal(row["Close"]) for row in candidate_rows}
    except (InvalidOperation, KeyError) as exc:
        raise UpdateFailure("Daily Price staging candidate has an invalid Close", status=STATUS_BLOCKED, exit_code=EXIT_BLOCKED) from exc
    receipt_paths = result.get("receipt_paths")
    if not isinstance(receipt_paths, list) or not receipt_paths:
        raise UpdateFailure("Daily Price staging has no verified TWSE receipts", status=STATUS_BLOCKED, exit_code=EXIT_BLOCKED)
    staged_twse: dict[str, Decimal] = {}
    for receipt_value in receipt_paths:
        receipt_path = Path(receipt_value)
        if not receipt_path.is_file() or not _resolved_within(receipt_path, run_dir / "receipts"):
            raise UpdateFailure("Daily Price staging receipt path is invalid", status=STATUS_BLOCKED, exit_code=EXIT_BLOCKED)
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            month = str(receipt["month"])
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise UpdateFailure("Daily Price staging receipt is invalid", status=STATUS_BLOCKED, exit_code=EXIT_BLOCKED) from exc
        raw_path = run_dir / "receipts" / f"{month}.twse.raw.csv"
        if (
            receipt.get("status") != "SUCCESS"
            or receipt.get("http_status") != 200
            or receipt.get("request_url") != source_url(month)
            or not raw_path.is_file()
            or receipt.get("raw_artifact_sha256") != sha256_file(raw_path)
        ):
            raise UpdateFailure("Daily Price staging TWSE receipt provenance is invalid", status=STATUS_BLOCKED, exit_code=EXIT_BLOCKED)
        for row_date, row in parse_twse_month(raw_path.read_bytes(), month).items():
            if row_date in staged_twse:
                raise UpdateFailure("Daily Price staging contains duplicate TWSE dates", status=STATUS_BLOCKED, exit_code=EXIT_BLOCKED)
            staged_twse[row_date] = row["close"]
    target_dates = [day for day in candidate_price if activity_anchor_date < day <= as_of_date.isoformat()]
    if not target_dates:
        raise UpdateFailure("Daily Price staging is stale for the current Launcher run", status=STATUS_BLOCKED, exit_code=EXIT_BLOCKED)
    for day in target_dates:
        if day not in staged_twse or candidate_price[day] != staged_twse[day]:
            raise UpdateFailure("Daily Price staging Close does not match its verified TWSE receipt", status=STATUS_BLOCKED, exit_code=EXIT_BLOCKED)
    return candidate_price, {
        "source": "SAME_RUN_DAILY_PRICE_STAGING",
        "daily_price_run_id": daily_price_run_id,
        "daily_price_run_dir": str(run_dir),
        "daily_price_candidate_sha256": candidate_sha,
        "daily_price_receipt_paths": receipt_paths,
    }


def write_candidate(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FORMAL_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows([{field: row[field] for field in FORMAL_FIELDS} for row in rows])
    os.replace(temporary, path)


@contextmanager
def update_lock(runtime_root: Path, stale_seconds: int = 1800) -> Iterator[Path]:
    runtime_root.mkdir(parents=True, exist_ok=True)
    lock_path = runtime_root / "run.lock"
    if lock_path.exists():
        age = dt.datetime.now().timestamp() - lock_path.stat().st_mtime
        if age <= stale_seconds:
            raise UpdateFailure("Market-activity update is already running", exit_code=EXIT_LOCKED)
        stale_path = runtime_root / f"run.lock.stale.{int(dt.datetime.now().timestamp())}.json"
        os.replace(lock_path, stale_path)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(descriptor, json.dumps({"pid": os.getpid(), "started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}).encode("utf-8"))
        os.close(descriptor)
        yield lock_path
    finally:
        try:
            if lock_path.exists():
                lock_path.unlink()
        except OSError:
            pass


def run_update(
    package_root: Path,
    *,
    as_of_date: dt.date,
    dry_run: bool = False,
    offline_receipt_dir: Path | None = None,
    daily_price_run_dir: Path | None = None,
    daily_price_run_id: str | None = None,
) -> dict[str, Any]:
    package_root = package_root.resolve()
    formal_path = package_root / FORMAL_REL
    price_path = package_root / PRICE_REL
    if not formal_path.is_file() or not price_path.is_file():
        raise UpdateFailure("Formal market-activity or price authority is missing", status=STATUS_LIMITED)
    formal_hash_before = sha256_file(formal_path)
    manifest_path = package_root / publisher.MANIFEST_PATH
    manifest_hash_before = sha256_file(manifest_path)
    formal_rows = read_formal_activity(formal_path)
    price = read_price(price_path)
    last_formal_date = formal_rows[-1]["date"]
    if (daily_price_run_dir is None) != (daily_price_run_id is None):
        raise UpdateFailure("Daily Price staging requires both run directory and run id", status=STATUS_BLOCKED, exit_code=EXIT_BLOCKED)
    staging_price: dict[str, Decimal] = {}
    staging_provenance: dict[str, Any] | None = None
    if daily_price_run_dir is not None and daily_price_run_id is not None:
        staging_price, staging_provenance = load_same_run_price_staging(
            package_root,
            daily_price_run_dir=daily_price_run_dir,
            daily_price_run_id=daily_price_run_id,
            as_of_date=as_of_date,
            activity_anchor_date=last_formal_date,
        )
    months = month_sequence(last_formal_date[:7], as_of_date.strftime("%Y-%m"))
    run_id = f"P1008-MARKET-ACTIVITY-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    runtime_root = package_root / RUNTIME_REL
    run_dir = runtime_root / run_id
    if run_dir.exists():
        raise UpdateFailure(f"Run directory collision: {run_dir}")
    run_dir.mkdir(parents=True)
    receipts_dir = run_dir / "receipts"
    receipts_dir.mkdir()
    status_path = package_root / STATUS_REL
    http_calls = 0
    receipt_paths: list[str] = []

    with update_lock(runtime_root):
        try:
            twse_rows: dict[str, dict[str, Any]] = {}
            for month in months:
                if offline_receipt_dir is None:
                    content, metadata = fetch_twse_month(month)
                    http_calls += 1
                else:
                    content, metadata = load_offline_month(offline_receipt_dir, month)
                parsed = parse_twse_month(content, month)
                for row_date, row in parsed.items():
                    if row_date in twse_rows:
                        raise UpdateFailure(f"Duplicate TWSE date across months: {row_date}")
                    twse_rows[row_date] = row
                raw_path = receipts_dir / f"{month}.twse.raw.csv"
                receipt_path = receipts_dir / f"{month}.receipt.json"
                raw_path.write_bytes(content)
                metadata.update(
                    {
                        "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                        "parsed_row_count": len(parsed),
                        "raw_artifact_path": str(raw_path.resolve()),
                        "raw_artifact_sha256": sha256_file(raw_path),
                    }
                )
                atomic_json(receipt_path, metadata)
                receipt_paths.append(str(receipt_path.resolve()))

            formal_by_date = {row["date"]: row for row in formal_rows}
            for row_date, formal in formal_by_date.items():
                if row_date[:7] not in months:
                    continue
                source = twse_rows.get(row_date)
                if source is None:
                    raise UpdateFailure(f"TWSE month file no longer contains formal date {row_date}")
                for formal_field, source_field in (
                    ("trade_volume", "trade_volume"),
                    ("trade_value", "trade_value"),
                    ("transaction_count", "transaction_count"),
                ):
                    if int(formal[formal_field]) != int(source[source_field]):
                        raise UpdateFailure(f"Historical market-activity rewrite detected for {row_date}")

            new_rows: list[dict[str, Any]] = []
            for row_date in sorted(twse_rows):
                if row_date > as_of_date.isoformat() or row_date in formal_by_date:
                    continue
                if row_date <= last_formal_date:
                    raise UpdateFailure(f"Historical gap requires separate backfill approval: {row_date}")
                comparison_price = staging_price.get(row_date, price.get(row_date))
                if comparison_price is None:
                    raise UpdateFailure(
                        f"Price authority does not contain TWSE date {row_date}",
                        status=STATUS_BLOCKED,
                        exit_code=EXIT_BLOCKED,
                    )
                if comparison_price != twse_rows[row_date]["close"]:
                    raise UpdateFailure(
                        f"TWSE Close does not match price authority for {row_date}",
                        status=STATUS_BLOCKED,
                        exit_code=EXIT_BLOCKED,
                    )
                row = dict(twse_rows[row_date])
                row["price_validation_source"] = (
                    "SAME_RUN_DAILY_PRICE_STAGING"
                    if row_date in staging_price
                    else "FORMAL_DAILY_PRICE_AUTHORITY"
                )
                new_rows.append(row)

            if not new_rows:
                result = {
                    "run_id": run_id,
                    "status": STATUS_NO_NEW,
                    "launcher_status": "NO_NEW_DATA",
                    "market_liquidity_analysis_status": STATUS_READY,
                    "last_success_date": last_formal_date,
                    "months_checked": months,
                    "rows_added": 0,
                    "http_calls": http_calls,
                    "receipt_paths": receipt_paths,
                    "run_dir": str(run_dir.resolve()),
                    "dry_run": dry_run,
                    "exit_code": EXIT_OK,
                    "actionable": False,
                    "price_validation_provenance": staging_provenance,
                }
            else:
                candidate_path = run_dir / "2317_daily_market_activity.incremental.candidate.csv"
                write_candidate(candidate_path, new_rows)
                if dry_run:
                    result = {
                        "run_id": run_id,
                        "status": "DRY_RUN_READY",
                        "launcher_status": "UPDATED",
                        "market_liquidity_analysis_status": STATUS_READY,
                        "last_success_date": last_formal_date,
                        "candidate_last_date": new_rows[-1]["date"],
                        "months_checked": months,
                        "rows_added": 0,
                        "candidate_rows": len(new_rows),
                        "candidate_path": str(candidate_path.resolve()),
                        "candidate_sha256": sha256_file(candidate_path),
                        "http_calls": http_calls,
                        "receipt_paths": receipt_paths,
                        "run_dir": str(run_dir.resolve()),
                        "dry_run": True,
                        "exit_code": EXIT_OK,
                        "actionable": False,
                        "price_validation_provenance": staging_provenance,
                    }
                else:
                    publish_result = publisher.publish_market_activity_append(
                        package_root,
                        candidate_path,
                        run_dir / "publish",
                        approval_phrase=publisher.market_activity_approval_phrase(
                            [row["date"] for row in new_rows]
                        ),
                    )
                    result = {
                        "run_id": run_id,
                        "status": STATUS_UPDATED,
                        "launcher_status": "UPDATED",
                        "market_liquidity_analysis_status": STATUS_READY,
                        "last_success_date": publish_result["last_date"],
                        "months_checked": months,
                        "rows_added": len(new_rows),
                        "candidate_path": str(candidate_path.resolve()),
                        "candidate_sha256": sha256_file(candidate_path),
                        "publish_journal": str((run_dir / "publish" / "PUBLISH_JOURNAL.json").resolve()),
                        "formal_sha256": publish_result["post_hashes"][str(FORMAL_REL).replace('\\', '/')],
                        "manifest_sha256": publish_result["post_hashes"][publisher.MANIFEST_PATH],
                        "http_calls": http_calls,
                        "receipt_paths": receipt_paths,
                        "run_dir": str(run_dir.resolve()),
                        "dry_run": False,
                        "exit_code": EXIT_OK,
                        "actionable": False,
                        "price_validation_provenance": staging_provenance,
                    }
            if dry_run and (
                sha256_file(formal_path) != formal_hash_before
                or sha256_file(manifest_path) != manifest_hash_before
            ):
                raise UpdateFailure("Dry-run changed formal CSV or manifest")
            atomic_json(run_dir / "RESULT.json", result)
            atomic_json(status_path, result)
            return result
        except UpdateFailure as exc:
            result = {
                "run_id": run_id,
                "status": exc.status,
                "launcher_status": "BLOCKED" if exc.status == STATUS_BLOCKED else "STALE",
                "market_liquidity_analysis_status": STATUS_LIMITED,
                "last_success_date": last_formal_date,
                "months_checked": months,
                "rows_added": 0,
                "http_calls": http_calls,
                "receipt_paths": receipt_paths,
                "run_dir": str(run_dir.resolve()),
                "dry_run": dry_run,
                "exit_code": exc.exit_code,
                "error": str(exc),
                "actionable": False,
                "price_validation_provenance": staging_provenance,
            }
            atomic_json(run_dir / "RESULT.json", result)
            atomic_json(status_path, result)
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--as-of-date", type=dt.date.fromisoformat, default=dt.date.today())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--offline-receipt-dir", type=Path)
    parser.add_argument("--daily-price-run-dir", type=Path)
    parser.add_argument("--daily-price-run-id")
    args = parser.parse_args(argv)
    try:
        result = run_update(
            args.package_root,
            as_of_date=args.as_of_date,
            dry_run=args.dry_run,
            offline_receipt_dir=args.offline_receipt_dir,
            daily_price_run_dir=args.daily_price_run_dir,
            daily_price_run_id=args.daily_price_run_id,
        )
    except UpdateFailure as exc:
        print(json.dumps({"status": exc.status, "error": str(exc), "exit_code": exc.exit_code}, ensure_ascii=False))
        return exc.exit_code
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
