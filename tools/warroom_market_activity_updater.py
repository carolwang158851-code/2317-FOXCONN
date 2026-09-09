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
import io
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
CONFIRMED_REVISION_DATE = "2026-09-08"
CONFIRMED_REVISION_OLD = ("39921647", "10039328945", "36632")
CONFIRMED_REVISION_NEW = ("40240647", "10119470867", "36634")

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
    """Fetch one TWSE CSV, allowing one governed redirect or direct-path recovery."""

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
        canonical_direct_fallback = False
        if 300 <= response.status < 400:
            redirect_status = response.status
            redirect_location = response.getheader("Location")
            connection.close()
            connection = None
            if isinstance(redirect_location, str) and redirect_location.strip():
                final_url = approved_redirect_url(redirect_location.strip(), request_url)
                target = urlsplit(final_url)
                next_path = target.path + (f"?{target.query}" if target.query else "")
            else:
                # TWSE occasionally emits a redirect-like response without a usable
                # Location.  Reissue only the already-governed direct STOCK_DAY URL;
                # do not accept the 3xx body or broaden the approved destination set.
                canonical_direct_fallback = True
                next_path = path
            response, content, tls_version, certificate = request_once(next_path)
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
            "canonical_direct_fallback": canonical_direct_fallback,
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


def _render_market_row(row: dict[str, str], line_ending: str) -> bytes:
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator=line_ending).writerow(
        [row[field] for field in FORMAL_FIELDS]
    )
    return output.getvalue().encode("utf-8")


def publish_confirmed_official_revision(
    package_root: Path,
    *,
    candidate_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Atomically apply only the confirmed 2026-09-08 TWSE correction plus 2026-09-09."""

    package_root = package_root.resolve()
    candidate_path = candidate_path.resolve()
    output_dir = output_dir.resolve()
    runtime_root = (package_root / "runtime").resolve()
    if not candidate_path.is_relative_to(runtime_root) or not output_dir.is_relative_to(runtime_root):
        raise UpdateFailure("Confirmed revision evidence must remain under runtime/")
    if output_dir.exists():
        raise UpdateFailure(f"Confirmed revision output already exists: {output_dir}")

    formal_path = package_root / FORMAL_REL
    manifest_path = package_root / publisher.MANIFEST_PATH
    formal_header, formal_rows, _ = publisher.read_csv_header_and_rows(formal_path)
    candidate_header, candidate_rows, _ = publisher.read_csv_header_and_rows(candidate_path)
    if tuple(formal_header) != FORMAL_FIELDS or formal_header != candidate_header:
        raise UpdateFailure("Confirmed revision CSV schema mismatch")
    formal_dates = [row[0] for row in formal_rows]
    candidate_dates = [row[0] for row in candidate_rows]
    if formal_dates != sorted(set(formal_dates)) or candidate_dates != sorted(set(candidate_dates)):
        raise UpdateFailure("Confirmed revision dates are not unique and increasing")
    if candidate_dates != formal_dates + ["2026-09-09"]:
        raise UpdateFailure("Confirmed revision candidate has an unexpected date sequence")
    formal_by_date = {row[0]: row for row in formal_rows}
    candidate_by_date = {row[0]: row for row in candidate_rows}
    changed_dates = [row_date for row_date in formal_dates if candidate_by_date[row_date] != formal_by_date[row_date]]
    if changed_dates != [CONFIRMED_REVISION_DATE]:
        raise UpdateFailure("Confirmed revision candidate changes an unauthorized historical row")
    old_row = formal_by_date[CONFIRMED_REVISION_DATE]
    revised_row = candidate_by_date[CONFIRMED_REVISION_DATE]
    appended_row = candidate_by_date["2026-09-09"]
    if tuple(old_row[2:5]) != CONFIRMED_REVISION_OLD or tuple(revised_row[2:5]) != CONFIRMED_REVISION_NEW:
        raise UpdateFailure("Confirmed revision values do not match the approved TWSE evidence")
    for row in (revised_row, appended_row):
        if row[1] != "2317" or not all(row[index].isdigit() for index in (2, 3, 4)) or not row[5].startswith(f"https://{TWSE_HOST}{TWSE_PATH}?") or row[6] != row[0][:7]:
            raise UpdateFailure("Confirmed revision candidate is not approved TWSE market activity")

    manifest = publisher.read_json(manifest_path)
    target_path = str(FORMAL_REL).replace("\\", "/")
    entry = next((item for item in manifest.get("authoritativeFiles", []) if item.get("path") == target_path), None)
    formal_bytes = formal_path.read_bytes()
    formal_sha = sha256_bytes(formal_bytes)
    if entry is None or entry.get("sha256") != formal_sha or entry.get("rowCount") != len(formal_rows):
        raise UpdateFailure("Market-activity manifest does not match the formal pre-reconciliation CSV")
    lines = formal_bytes.splitlines(keepends=True)
    old_line = next((line for line in lines if line.startswith(b"2026-09-08,")), None)
    if old_line is None or sum(line.startswith(b"2026-09-08,") for line in lines) != 1:
        raise UpdateFailure("Confirmed revision target row is not uniquely present")
    line_ending = "\r\n" if old_line.endswith(b"\r\n") else "\n"
    expected_old_line = _render_market_row(dict(zip(FORMAL_FIELDS, old_row, strict=True)), line_ending)
    if old_line != expected_old_line:
        raise UpdateFailure("Confirmed revision target row bytes do not match the parsed formal row")
    replacement_line = _render_market_row(dict(zip(FORMAL_FIELDS, revised_row, strict=True)), line_ending)
    appended_line = _render_market_row(dict(zip(FORMAL_FIELDS, appended_row, strict=True)), line_ending)
    combined_bytes = formal_bytes.replace(old_line, replacement_line, 1) + appended_line
    if combined_bytes.count(replacement_line) != 1 or not combined_bytes.endswith(appended_line):
        raise UpdateFailure("Confirmed revision byte construction failed")
    combined_sha = sha256_bytes(combined_bytes)

    unrelated_entries = [item for item in manifest.get("authoritativeFiles", []) if item.get("path") != target_path]
    published_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry["sha256"] = combined_sha
    entry["fileSizeBytes"] = len(combined_bytes)
    entry["rowCount"] = len(candidate_rows)
    entry["dateRange"]["end"] = "2026-09-09"
    entry["lastPublishedAt"] = published_at
    entry["lastAppend"] = {"rowsAdded": 1, "start": "2026-09-09", "end": "2026-09-09", "candidateSha256": sha256_file(candidate_path), "publishedAt": published_at, "publisher": "warroom_market_activity_updater.py", "mode": "TWSE_CONFIRMED_OFFICIAL_REVISION_AND_APPEND", "actionable": False}
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    output_dir.mkdir(parents=True)
    staged_dir = output_dir / "staged"
    backup_dir = output_dir / "backup"
    staged_dir.mkdir()
    backup_dir.mkdir()
    (staged_dir / formal_path.name).write_bytes(combined_bytes)
    (staged_dir / manifest_path.name).write_bytes(manifest_bytes)
    (backup_dir / formal_path.name).write_bytes(formal_bytes)
    manifest_before = manifest_path.read_bytes()
    (backup_dir / manifest_path.name).write_bytes(manifest_before)
    journal_path = output_dir / "PUBLISH_JOURNAL.json"
    journal: dict[str, Any] = {"mode": "TWSE_CONFIRMED_OFFICIAL_REVISION_AND_APPEND", "status": "BACKUP_VERIFIED", "pre_hashes": {target_path: formal_sha, publisher.MANIFEST_PATH: sha256_bytes(manifest_before)}, "pre_sizes": {target_path: len(formal_bytes), publisher.MANIFEST_PATH: len(manifest_before)}, "pre_row_count": len(formal_rows), "row_diff": {"replaced": {"date": CONFIRMED_REVISION_DATE, "before": old_row, "after": revised_row}, "appended": appended_row}, "staged_hashes": {target_path: combined_sha, publisher.MANIFEST_PATH: sha256_bytes(manifest_bytes)}, "actionable": False}
    atomic_json(journal_path, journal)
    try:
        publisher._atomic_write_bytes(formal_path, combined_bytes)
        publisher._atomic_write_bytes(manifest_path, manifest_bytes)
        published_header, published_rows, _ = publisher.read_csv_header_and_rows(formal_path)
        published_manifest = publisher.read_json(manifest_path)
        published_entry = next(item for item in published_manifest["authoritativeFiles"] if item.get("path") == target_path)
        published_unrelated = [item for item in published_manifest["authoritativeFiles"] if item.get("path") != target_path]
        if tuple(published_header) != FORMAL_FIELDS or published_rows != candidate_rows or published_unrelated != unrelated_entries or sha256_file(formal_path) != combined_sha or published_entry.get("sha256") != combined_sha or published_entry.get("fileSizeBytes") != len(combined_bytes) or published_entry.get("rowCount") != len(candidate_rows):
            raise UpdateFailure("Confirmed revision post-publish validation failed")
        journal.update({"status": "PUBLISHED", "post_hashes": {target_path: sha256_file(formal_path), publisher.MANIFEST_PATH: sha256_file(manifest_path)}, "post_sizes": {target_path: formal_path.stat().st_size, publisher.MANIFEST_PATH: manifest_path.stat().st_size}, "post_row_count": len(published_rows), "last_date": published_rows[-1][0], "duplicate_dates": len(published_rows) - len({row[0] for row in published_rows}), "unrelated_manifest_entries_unchanged": True, "rollback_available": True})
        atomic_json(journal_path, journal)
        return journal
    except Exception as exc:
        publisher._atomic_write_bytes(formal_path, formal_bytes)
        publisher._atomic_write_bytes(manifest_path, manifest_before)
        journal.update({"status": "ROLLED_BACK", "error": str(exc), "rollback_verified": sha256_file(formal_path) == formal_sha and sha256_file(manifest_path) == sha256_bytes(manifest_before)})
        atomic_json(journal_path, journal)
        raise


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
    apply_confirmed_official_revision_20260908: bool = False,
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
            confirmed_revision_dates: list[str] = []
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
                        if (
                            apply_confirmed_official_revision_20260908
                            and row_date == CONFIRMED_REVISION_DATE
                            and tuple(formal[field] for field in ("trade_volume", "trade_value", "transaction_count")) == CONFIRMED_REVISION_OLD
                            and tuple(str(source[field]) for field in ("trade_volume", "trade_value", "transaction_count")) == CONFIRMED_REVISION_NEW
                            and price.get(row_date) == source["close"]
                        ):
                            confirmed_revision_dates.append(row_date)
                            break
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

            if confirmed_revision_dates:
                reconciled_rows = []
                for row in formal_rows:
                    row_date = row["date"]
                    if row_date in confirmed_revision_dates:
                        source = twse_rows[row_date]
                        reconciled_rows.append({field: str(source[field]) for field in FORMAL_FIELDS})
                    else:
                        reconciled_rows.append(dict(row))
                reconciled_rows.extend({field: str(row[field]) for field in FORMAL_FIELDS} for row in new_rows)
                candidate_path = run_dir / "2317_daily_market_activity.confirmed_revision.candidate.csv"
                write_candidate(candidate_path, reconciled_rows)
                if dry_run:
                    result = {
                        "run_id": run_id, "status": "DRY_RUN_READY", "launcher_status": "UPDATED",
                        "market_liquidity_analysis_status": STATUS_READY, "last_success_date": last_formal_date,
                        "candidate_last_date": reconciled_rows[-1]["date"], "months_checked": months,
                        "rows_added": 0, "rows_revised": len(confirmed_revision_dates),
                        "candidate_rows": len(reconciled_rows), "candidate_path": str(candidate_path.resolve()),
                        "candidate_sha256": sha256_file(candidate_path), "http_calls": http_calls,
                        "receipt_paths": receipt_paths, "run_dir": str(run_dir.resolve()), "dry_run": True,
                        "exit_code": EXIT_OK, "actionable": False, "price_validation_provenance": staging_provenance,
                    }
                else:
                    publish_result = publish_confirmed_official_revision(
                        package_root, candidate_path=candidate_path, output_dir=run_dir / "publish"
                    )
                    result = {
                        "run_id": run_id, "status": STATUS_UPDATED, "launcher_status": "UPDATED",
                        "market_liquidity_analysis_status": STATUS_READY, "last_success_date": publish_result["last_date"],
                        "months_checked": months, "rows_added": len(new_rows), "rows_revised": len(confirmed_revision_dates),
                        "candidate_path": str(candidate_path.resolve()), "candidate_sha256": sha256_file(candidate_path),
                        "publish_journal": str((run_dir / "publish" / "PUBLISH_JOURNAL.json").resolve()),
                        "formal_sha256": publish_result["post_hashes"][str(FORMAL_REL).replace("\\", "/")],
                        "manifest_sha256": publish_result["post_hashes"][publisher.MANIFEST_PATH],
                        "http_calls": http_calls, "receipt_paths": receipt_paths, "run_dir": str(run_dir.resolve()),
                        "dry_run": False, "exit_code": EXIT_OK, "actionable": False, "price_validation_provenance": staging_provenance,
                    }
            elif not new_rows:
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
    parser.add_argument("--apply-confirmed-official-revision-20260908", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_update(
            args.package_root,
            as_of_date=args.as_of_date,
            dry_run=args.dry_run,
            offline_receipt_dir=args.offline_receipt_dir,
            daily_price_run_dir=args.daily_price_run_dir,
            daily_price_run_id=args.daily_price_run_id,
            apply_confirmed_official_revision_20260908=args.apply_confirmed_official_revision_20260908,
        )
    except UpdateFailure as exc:
        print(json.dumps({"status": exc.status, "error": str(exc), "exit_code": exc.exit_code}, ensure_ascii=False))
        return exc.exit_code
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
