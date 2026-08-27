#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create P1008 staging CSV candidates and runtime snapshots.

This tool never writes formal CSV files. It only writes:
- staging/<date>/*_candidate.csv
- staging/<date>/DRY_RUN.json
- staging/<date>/DRY_RUN.md
- runtime/warroom_realtime_snapshot.json

Formal CSV append remains gated by 3_OWNER核准發布正式CSV.bat.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import json
import os
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DAILY_COLUMNS = [
    "Date",
    "Close",
    "QuarterKey",
    "BVPS_ref",
    "PB_daily",
    "DataSupportLevel",
    "Status",
]

MACRO_COLUMNS = [
    "Date",
    "TWD_USD",
    "VIX",
    "WTI_Oil",
    "US_10Y_Yield",
    "Fed_Rate",
    "Fed_Hike_Prob_YE",
    "DXY",
    "US_GDP_QoQ",
    "US_CPI_YoY",
    "TW_GDP_QoQ",
    "TAIEX_Weekly_Chg",
    "CSP_Capex_Signal",
    "Hon_Hai_Rev_YoY",
    "Foreign_Net_Buy",
    "TW_Export_YoY",
    "RiskLevel",
    "RiskNote",
]

MACRO_EVENT_COLUMNS = [
    "Date",
    "EventType",
    "EventTitle",
    "Region",
    "SourceTier",
    "SourceName",
    "SourceUrl",
    "EvidenceStatus",
    "RiskTag",
    "BlackSwanLevel",
    "RelatedMetrics",
    "SummaryZh",
    "DecisionImpactZh",
    "Actionable",
]

FX_TREND_COLUMNS = [
    "Date",
    "TWD_USD",
    "DXY",
    "JPY_USD",
    "US_10Y_Yield",
    "Fed_Rate",
    "BOJ_Rate",
    "RateSpread_US_JP",
    "FxTrend",
    "FxPressureLevel",
    "EPSImpactEstimateZh",
    "SourceTier",
    "SourceUrl",
    "SummaryZh",
    "Actionable",
]

MACRO_EVENT_TARGET = "data/macro_event_observations.csv"
FX_TREND_TARGET = "data/fx_trend_observations.csv"

REQUEST_TIMEOUT_SECONDS = 8
REQUEST_RETRIES = 1
REQUEST_RETRY_DELAY_SECONDS = 2
POWERSHELL_TIMEOUT_SECONDS = 20
HTTP_CLIENT_TIMEOUT_SECONDS = 10

MACRO_SOURCE_LABELS = {
    "stock_price": "2317 close",
    "vix": "VIX market volatility",
    "wti": "WTI crude oil",
    "twd_usd": "TWD/USD",
    "us10y": "US 10Y yield",
    "dxy": "US dollar index",
    "fed_rate": "Fed policy rate",
}

MACRO_SOURCE_CANDIDATES = {
    "stock_price": ["TWSE STOCK_DAY", "TWSE MIS", "TWSE STOCK_DAY_ALL", "Yahoo 2317.TW fallback"],
    "vix": ["FRED VIXCLS", "Stooq VIX", "Yahoo ^VIX fallback"],
    "wti": ["FRED DCOILWTICO", "Stooq CL.F", "Yahoo CL=F fallback"],
    "twd_usd": ["FRED DEXTAUS", "Stooq USDTWD", "Yahoo TWD=X fallback"],
    "us10y": ["FRED DGS10", "Yahoo ^TNX fallback"],
    "dxy": ["Stooq DXY", "Yahoo DX-Y.NYB fallback"],
    "fed_rate": ["FRED DFEDTARU/DFEDTARL midpoint", "formal CSV carry-forward"],
}

MARKET_PROXY_MANIFEST = [
    {
        "metric": "vix_proxy",
        "mapsTo": "VIX",
        "connector": "ALPACA",
        "symbol": "VIXY",
        "sourceTier": "PUBLIC_MARKET_PROXY",
        "formalDataSource": True,
        "formalReplacement": False,
        "formalUseZh": "可正式記錄為 VIXY 代理指標；不可直接填入 VIX 欄位。",
        "noteZh": "Alpaca 可作 VIXY ETF 的正式報價來源；VIXY 是波動率代理標的，不等於 FRED VIXCLS/CBOE VIX。",
    },
    {
        "metric": "wti_proxy",
        "mapsTo": "WTI_Oil",
        "connector": "ALPACA",
        "symbol": "USO",
        "sourceTier": "PUBLIC_MARKET_PROXY",
        "formalDataSource": True,
        "formalReplacement": False,
        "formalUseZh": "可正式記錄為 USO 代理指標；不可直接填入 WTI_Oil 欄位。",
        "noteZh": "Alpaca 可作 USO ETF 的正式報價來源；USO 是油價壓力代理標的，不等於 FRED DCOILWTICO/WTI 現貨序列。",
    },
    {
        "metric": "dxy_proxy",
        "mapsTo": "DXY",
        "connector": "ALPACA",
        "symbol": "UUP",
        "sourceTier": "PUBLIC_MARKET_PROXY",
        "formalDataSource": True,
        "formalReplacement": False,
        "formalUseZh": "可正式記錄為 UUP 代理指標；不可直接填入 DXY 欄位。",
        "noteZh": "Alpaca 可作 UUP ETF 的正式報價來源；UUP 是美元壓力代理標的，不等於 DXY/美元指數序列。",
    },
    {
        "metric": "us10y_proxy",
        "mapsTo": "US_10Y_Yield",
        "connector": "ALPACA",
        "symbol": "IEF/TLT",
        "sourceTier": "PUBLIC_MARKET_PROXY",
        "formalDataSource": True,
        "formalReplacement": False,
        "formalUseZh": "可正式記錄為 IEF/TLT 代理指標；不可直接填入 US_10Y_Yield 欄位。",
        "noteZh": "Alpaca 可作 IEF/TLT ETF 的正式報價來源；IEF/TLT 是長債價格代理，不等於 FRED DGS10 十年期殖利率。",
    },
]

TWSE_DAILY_ALL_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TWSE_STOCK_DAY_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
TWSE_MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
STOOQ_QUOTE_URL = "https://stooq.com/q/l/"
FRED_DFF_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF"
FRED_SERIES_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
CME_FEDWATCH_PAGE_URL = "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"


def log(message: str, level: str = "INFO") -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv_with_comments(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    content_lines: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for line in handle:
            if line.lstrip().startswith("#") or not line.strip():
                continue
            content_lines.append(line)
    reader = csv.DictReader(content_lines)
    if not reader.fieldnames:
        raise ValueError(f"CSV_HEADER_MISSING: {path}")
    return list(reader.fieldnames), list(reader)


def write_csv(path: Path, columns: list[str], row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerow({column: row.get(column, "") for column in columns})


def target_has_key(path: Path, key: str) -> bool:
    if not path.exists():
        return False
    _, rows = read_csv_with_comments(path)
    return any(row.get("Date") == key or row.get("Quarter") == key for row in rows)


WEEKDAY_ZH = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]


def stock_close_missing_note(candidate_date: str) -> str:
    parsed = datetime.strptime(candidate_date, "%Y-%m-%d").date()
    if parsed.weekday() >= 5:
        return (
            f"{candidate_date} 是{WEEKDAY_ZH[parsed.weekday()]}，台股例行休市，因此未取得 2317 收盤價；"
            "未產生 daily_price 候選檔屬正常狀況，系統不會補假資料。"
        )
    return "未取得 2317 收盤價，因此未產生 daily_price 候選檔；若非休市日，需檢查 TWSE connector 或由 Owner 補正式來源。"


def market_closed_carry_forward_price(
    candidate_date: str,
    latest_daily: dict[str, str],
) -> dict[str, Any] | None:
    if not is_weekend_date(candidate_date) or not latest_daily:
        return None
    latest_date = latest_daily.get("Date", "")
    if not is_prior_or_equal(latest_date, candidate_date):
        return None
    close = parse_float(latest_daily.get("Close"))
    if close is None:
        return None
    return source_result(
        round(close, 3),
        "FORMAL_DAILY_PRICE_CARRY_FORWARD",
        note_zh=(
            f"{candidate_date} 為休市日，沿用正式 CSV 最近交易日 {latest_date} 收盤價 {close:g}；"
            "僅供 Launcher / 新 UI 視覺與 PB 連續，不 append 週末 daily_price 正式列。"
        ),
        support_level="MARKET_CLOSED_CARRY_FORWARD",
        source_date=latest_date,
        effective_date=candidate_date,
        publish_candidate=False,
    )


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text in {"", "-", "--", "---", "N/A", "NA", "null", "None", "."}:
        return None
    text = (
        text.replace(",", "")
        .replace("%", "")
        .replace("$", "")
        .replace("−", "-")
        .strip()
    )
    try:
        return float(text)
    except ValueError:
        return None


def round_value(value: float | None, decimals: int = 3) -> float | str:
    if value is None:
        return ""
    return round(float(value), decimals)


def latest_row_by_date(rows: list[dict[str, str]], date_key: str = "Date") -> dict[str, str] | None:
    dated_rows = [row for row in rows if row.get(date_key)]
    if not dated_rows:
        return rows[-1] if rows else None
    return sorted(dated_rows, key=lambda row: row.get(date_key, ""))[-1]


def verify_master_authority(package_root: Path) -> dict[str, Any]:
    manifest_path = package_root / "data" / "CSV_AUTHORITY_MANIFEST.json"
    master_path = package_root / "data" / "2317_master_v9.csv"
    manifest = load_json(manifest_path)
    entry = next(
        (
            item
            for item in manifest.get("authoritativeFiles", [])
            if item.get("fileName") == master_path.name
        ),
        None,
    )
    if entry is None:
        raise ValueError("AUTHORITY_MANIFEST_MISSING: 找不到 2317_master_v9.csv 的正式授權紀錄")
    actual_hash = sha256_file(master_path)
    if actual_hash != entry.get("sha256"):
        raise ValueError("APPROVAL_EXPIRED: 2317_master_v9.csv SHA-256 與 manifest 不一致，需 Owner 重新核准")
    header, rows = read_csv_with_comments(master_path)
    if header != entry.get("columns"):
        raise ValueError("SCHEMA_HEADER_MISMATCH: 2317_master_v9.csv 欄位與 manifest 不一致")
    if len(rows) != entry.get("rowCount"):
        raise ValueError("ROW_COUNT_MISMATCH: 2317_master_v9.csv 筆數與 manifest 不一致")
    latest = sorted(rows, key=lambda row: row["Quarter"])[-1]
    for field in ("Quarter", "BVPS", "CashDividend"):
        if not latest.get(field):
            raise ValueError(f"DATA_MISSING: master 最新季度缺少 {field}")
    bvps = parse_float(latest["BVPS"])
    cash_dividend = parse_float(latest["CashDividend"])
    if bvps is None or cash_dividend is None:
        raise ValueError("DATA_INVALID: BVPS 或 CashDividend 不是可解析數字")
    return {
        "path": master_path,
        "sha256": actual_hash,
        "quarter": latest["Quarter"],
        "bvps": bvps,
        "cashDividend": cash_dividend,
        "validationStatus": entry.get("validationStatus"),
    }


def load_latest_macro_row(package_root: Path) -> dict[str, str] | None:
    macro_path = package_root / "data" / "macro_snapshot.csv"
    if not macro_path.exists():
        return None
    _, rows = read_csv_with_comments(macro_path)
    return latest_row_by_date(rows)


def load_latest_csv_row(package_root: Path, relative_path: str, date_key: str = "Date") -> dict[str, str] | None:
    path = package_root / relative_path
    if not path.exists():
        return None
    _, rows = read_csv_with_comments(path)
    return latest_row_by_date(rows, date_key=date_key)


def fetch_bytes(url: str, params: dict[str, str] | None = None) -> bytes | None:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (P1008 staging candidate generator)",
        "Accept": "application/json,text/csv,text/plain,*/*",
    }
    request = urllib.request.Request(url, headers=headers)
    for attempt in range(REQUEST_RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            if attempt < REQUEST_RETRIES - 1:
                time.sleep(REQUEST_RETRY_DELAY_SECONDS)
            else:
                log(f"資料來源連線失敗：{url}；{error}", "WARN")
    return None


_fetch_bytes_urllib_only = fetch_bytes


def build_url(url: str, params: dict[str, str] | None = None) -> str:
    if params:
        return f"{url}?{urllib.parse.urlencode(params)}"
    return url


def fetch_bytes_with_http_client(url: str, redirects_remaining: int = 3) -> bytes | None:
    """Use a direct verified HTTPS transport when urllib/proxy routing is unavailable."""

    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        log(f"Python HTTPS fallback rejected non-HTTPS URL: {url}", "WARN")
        return None
    target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    connection: http.client.HTTPSConnection | None = None
    try:
        connection = http.client.HTTPSConnection(
            parsed.hostname,
            port=parsed.port,
            timeout=HTTP_CLIENT_TIMEOUT_SECONDS,
            context=ssl.create_default_context(),
        )
        connection.request(
            "GET",
            target,
            headers={
                "User-Agent": "Mozilla/5.0 (P1008 staging candidate generator)",
                "Accept": "application/json,text/csv,text/plain,*/*",
            },
        )
        response = connection.getresponse()
        if response.status in {301, 302, 303, 307, 308}:
            location = response.getheader("Location")
            response.read()
            if not location or redirects_remaining <= 0:
                log(f"Python HTTPS fallback redirect rejected: {url}", "WARN")
                return None
            redirected = urllib.parse.urljoin(url, location)
            redirected_host = urllib.parse.urlsplit(redirected).hostname
            if redirected_host != parsed.hostname:
                log(f"Python HTTPS fallback cross-host redirect rejected: {url}", "WARN")
                return None
            return fetch_bytes_with_http_client(redirected, redirects_remaining - 1)
        content = response.read()
        if response.status != 200:
            log(f"Python HTTPS fallback HTTP {response.status}: {url}", "WARN")
            return None
        log(f"Python HTTPS fallback succeeded: {url}")
        return content
    except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException) as error:
        log(f"Python HTTPS fallback failed: {url} ({error})", "WARN")
        return None
    finally:
        if connection is not None:
            connection.close()


def fetch_bytes_with_powershell(url: str) -> bytes | None:
    script = (
        "$ProgressPreference='SilentlyContinue'; "
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "$Url = $env:P1008_FETCH_URL; "
        "try { "
        "$r = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 15 -MaximumRedirection 5; "
        "[Console]::Out.Write($r.Content); exit 0 "
        "} catch { "
        "[Console]::Error.Write($_.Exception.Message); exit 1 "
        "}"
    )
    env = os.environ.copy()
    env["P1008_FETCH_URL"] = url
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=POWERSHELL_TIMEOUT_SECONDS,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        log(f"PowerShell connector fallback unavailable: {url} ({error})", "WARN")
        return None
    if completed.returncode != 0 or not completed.stdout:
        error_text = (completed.stderr or "").strip()
        log(f"PowerShell connector fallback failed: {url} ({error_text or completed.returncode})", "WARN")
        return None
    log(f"PowerShell connector fallback succeeded: {url}")
    return completed.stdout.encode("utf-8")


def fetch_bytes(url: str, params: dict[str, str] | None = None) -> bytes | None:
    data = _fetch_bytes_urllib_only(url, params)
    if data is not None:
        return data
    full_url = build_url(url, params)
    data = fetch_bytes_with_http_client(full_url)
    if data is not None:
        return data
    return fetch_bytes_with_powershell(full_url)


def fetch_json(url: str, params: dict[str, str] | None = None) -> Any | None:
    data = fetch_bytes(url, params)
    if data is None:
        return None
    try:
        return json.loads(data.decode("utf-8-sig"))
    except json.JSONDecodeError as error:
        log(f"JSON 解析失敗：{url}；{error}", "WARN")
        return None


def first_number(row: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        if key in row:
            value = parse_float(row.get(key))
            if value is not None:
                return value
    return None


def parse_twse_date(raw: Any) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    try:
        if len(digits) == 7:
            year = int(digits[:3]) + 1911
            return f"{year:04d}-{int(digits[3:5]):02d}-{int(digits[5:7]):02d}"
        if len(digits) == 8:
            return f"{int(digits[:4]):04d}-{int(digits[4:6]):02d}-{int(digits[6:8]):02d}"
    except ValueError:
        return None
    return None


def source_result(
    value: float | str | None,
    source: str,
    *,
    source_url: str = "",
    note_zh: str = "",
    support_level: str = "L3",
    source_date: str = "",
    effective_date: str = "",
    publish_candidate: bool = True,
) -> dict[str, Any]:
    return {
        "value": value,
        "source": source,
        "sourceUrl": source_url,
        "noteZh": note_zh,
        "supportLevel": support_level,
        "sourceDate": source_date,
        "effectiveDate": effective_date,
        "publishCandidate": publish_candidate,
    }


def source_health_status(result: dict[str, Any], required_for_formal: bool) -> tuple[str, str, bool]:
    source = str(result.get("source") or "").upper()
    value = result.get("value")
    if source in {"", "DATA_MISSING", "MISSING", "UNAVAILABLE"} or value in (None, ""):
        return "MISSING", "本次沒有取得資料，不能支持正式發布。", False
    if source == "CONNECTOR_SOURCE_UNAVAILABLE_CARRY_FORWARD":
        return "CARRY_FORWARD", "本次 connector/source 未取得，僅沿用正式 CSV 最近值作畫面觀察。", False
    if source.endswith("CARRY_FORWARD") or "CARRY_FORWARD" in source:
        if required_for_formal:
            return "CARRY_FORWARD", "沿用正式 CSV 最近值；若此欄位要求本次來源，不能單獨支持正式發布。", False
        return "OBSERVATION_CARRY_FORWARD", "沿用正式 CSV 最近值作觀察；此欄位不要求正式發布來源。", True
    if "YAHOO" in source:
        return "FALLBACK_OK", "本次由 Yahoo fallback 取得；可作備援，但應優先補官方或公開市場主來源。", True
    if "STOOQ" in source:
        return "PUBLIC_MARKET_OK", "本次由公開市場來源取得；可支持候選資料，但建議與官方來源交叉驗證。", True
    if "FRED" in source or "TWSE" in source:
        return "OFFICIAL_OR_PUBLIC_SERIES_OK", "本次由官方/公開序列來源取得，可追溯來源。", True
    if "OWNER_INPUT" in source:
        return "OWNER_INPUT_OK", "本次由 Owner 明確輸入；需保留來源證據。", True
    return "SOURCE_OK", "本次取得可追溯來源。", True


def freshness_days(source_date: str, candidate_date: str) -> int | str:
    source = parse_iso_date(str(source_date or ""))
    candidate = parse_iso_date(candidate_date)
    if not source or not candidate:
        return ""
    return max(0, (candidate - source).days)


def build_macro_source_health(
    candidate_date: str,
    stock_result: dict[str, Any],
    macro_results: dict[str, dict[str, Any]],
    daily_row: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    ordered: list[tuple[str, dict[str, Any], bool]] = [
        ("stock_price", stock_result, bool(daily_row is not None and stock_result.get("publishCandidate", True))),
        ("vix", macro_results["vix"], True),
        ("wti", macro_results["wti"], True),
        ("twd_usd", macro_results["twd_usd"], True),
        ("us10y", macro_results["us10y"], True),
        ("dxy", macro_results["dxy"], True),
        ("fed_rate", macro_results["fed_rate"], True),
    ]
    health: list[dict[str, Any]] = []
    for field, result, required in ordered:
        status, status_zh, supports_formal = source_health_status(result, required)
        if field == "fed_rate" and result.get("source") == "FORMAL_CSV_CARRY_FORWARD":
            status = "STABLE_SERIES_CARRY_FORWARD_OK"
            status_zh = "Fed_Rate 為慢變政策利率欄位；正式 CSV 沿用可支持本次發布，但仍需定期以官方來源複核。"
            supports_formal = True
        health.append(
            {
                "field": field,
                "label": MACRO_SOURCE_LABELS.get(field, field),
                "requiredForFormal": required,
                "status": status,
                "statusZh": status_zh,
                "supportsFormal": bool(supports_formal and required),
                "value": result.get("value", ""),
                "inputSource": result.get("source", ""),
                "sourceUrl": result.get("sourceUrl", ""),
                "sourceDate": result.get("sourceDate", ""),
                "effectiveDate": result.get("effectiveDate", ""),
                "freshnessDays": freshness_days(str(result.get("sourceDate", "")), candidate_date),
                "supportLevel": result.get("supportLevel", ""),
                "candidateSources": MACRO_SOURCE_CANDIDATES.get(field, []),
                "noteZh": result.get("noteZh", ""),
            }
        )
    return health


def parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def is_weekend_date(candidate_date: str) -> bool:
    parsed = parse_iso_date(candidate_date)
    return bool(parsed and parsed.weekday() >= 5)


def previous_calendar_dates(candidate_date: str, days: int = 7) -> list[str]:
    parsed = parse_iso_date(candidate_date)
    if not parsed:
        return []
    return [(parsed - timedelta(days=offset)).isoformat() for offset in range(1, days + 1)]


def is_prior_or_equal(source_date: str | None, candidate_date: str) -> bool:
    source = parse_iso_date(str(source_date or ""))
    candidate = parse_iso_date(candidate_date)
    return bool(source and candidate and source <= candidate)


def fetch_twse_stock_day_close(candidate_date: str) -> dict[str, Any] | None:
    payload = fetch_json(
        TWSE_STOCK_DAY_URL,
        {
            "date": candidate_date.replace("-", ""),
            "stockNo": "2317",
            "response": "json",
        },
    )
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        return None
    for row in payload.get("data", []) or []:
        if not isinstance(row, list) or len(row) < 7:
            continue
        source_date = parse_twse_date(row[0])
        if source_date != candidate_date:
            continue
        close = parse_float(row[6])
        if close is None:
            return None
        return source_result(
            round(close, 3),
            "TWSE_STOCK_DAY_OFFICIAL",
            source_url=TWSE_STOCK_DAY_URL,
            note_zh="TWSE 指定日期日成交資訊；日期已核對，作為正式收盤價候選。",
            support_level="OFFICIAL_TWSE_A1",
            source_date=candidate_date,
            effective_date=candidate_date,
        )
    return None


def fetch_twse_official_close(candidate_date: str) -> dict[str, Any] | None:
    payload = fetch_json(TWSE_DAILY_ALL_URL)
    if not isinstance(payload, list):
        return None
    for item in payload:
        if not isinstance(item, dict):
            continue
        code = str(
            item.get("Code")
            or item.get("code")
            or item.get("證券代號")
            or item.get("StockNo")
            or ""
        ).strip()
        if code != "2317":
            continue
        source_date = parse_twse_date(item.get("Date") or item.get("date") or item.get("日期"))
        if source_date != candidate_date:
            log(
                f"TWSE STOCK_DAY_ALL skipped because source date {source_date or 'UNKNOWN'} != candidate date {candidate_date}",
                "WARN",
            )
            return None
        close = first_number(
            item,
            [
                "ClosingPrice",
                "closingPrice",
                "Close",
                "close",
                "收盤價",
                "Closing",
            ],
        )
        if close is None:
            return None
        return source_result(
            round(close, 3),
            "TWSE_OPENAPI_STOCK_DAY_ALL",
            source_url=TWSE_DAILY_ALL_URL,
            note_zh="TWSE OpenAPI STOCK_DAY_ALL；日期已核對後才採用。",
            support_level="OFFICIAL_TWSE_A1",
            source_date=candidate_date,
            effective_date=candidate_date,
        )
    return None


def fetch_twse_realtime_close(candidate_date: str) -> dict[str, Any] | None:
    payload = fetch_json(
        TWSE_MIS_URL,
        {"ex_ch": "tse_2317.tw", "json": "1", "delay": "0"},
    )
    try:
        item = payload["msgArray"][0]
    except (TypeError, KeyError, IndexError):
        return None
    source_date = parse_twse_date(item.get("d") or item.get("^") or item.get("key"))
    if source_date != candidate_date:
        log(
            f"TWSE MIS skipped because source date {source_date or 'UNKNOWN'} != candidate date {candidate_date}",
            "WARN",
        )
        return None
    raw_value = item.get("z")
    close = parse_float(raw_value)
    if close is None or close <= 0:
        return None
    return source_result(
        round(close, 3),
        "TWSE_MIS_REALTIME",
        source_url=TWSE_MIS_URL,
        note_zh="TWSE MIS 日期相符的最新成交價；收盤後可作交叉驗證，正式發布仍需 Owner 核准。",
        support_level="RUNTIME_OBSERVATION",
        source_date=candidate_date,
        effective_date=candidate_date,
    )


def fetch_yahoo_chart_value(ticker: str, *, source_name: str, note_zh: str = "") -> dict[str, Any] | None:
    encoded_ticker = urllib.parse.quote(ticker, safe="=.-")
    url = YAHOO_CHART_URL.format(ticker=encoded_ticker)
    payload = fetch_json(url, {"interval": "1d", "range": "5d"})
    try:
        result = payload["chart"]["result"][0]
    except (TypeError, KeyError, IndexError):
        return None
    values: list[tuple[int, float]] = []
    quote = result.get("indicators", {}).get("quote", [{}])[0]
    timestamps = result.get("timestamp", []) or []
    for index, raw in enumerate(quote.get("close", []) or []):
        value = parse_float(raw)
        if value is not None:
            values.append((index, value))
    if not values:
        value = parse_float(result.get("meta", {}).get("regularMarketPrice"))
        if value is not None:
            values.append((-1, value))
    if not values:
        return None
    value_index, latest_value = values[-1]
    source_date = ""
    if value_index >= 0 and value_index < len(timestamps):
        try:
            source_timestamp = int(timestamps[value_index])
            timezone_name = str(result.get("meta", {}).get("exchangeTimezoneName") or "UTC")
            try:
                source_timezone = ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError:
                source_timezone = timezone.utc
            source_date = datetime.fromtimestamp(source_timestamp, timezone.utc).astimezone(source_timezone).date().isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            source_date = ""
    return source_result(
        round(latest_value, 3),
        source_name,
        source_url=url,
        note_zh=note_zh or "Yahoo Finance 日資料；需標示為外部市場資料。",
        support_level="PUBLIC_MARKET_DATA",
        source_date=source_date,
    )


def fetch_stooq_quote_value(
    symbols: list[str],
    *,
    source_name: str,
    note_zh: str,
) -> dict[str, Any] | None:
    for symbol in symbols:
        payload = fetch_bytes(
            STOOQ_QUOTE_URL,
            {"s": symbol, "f": "sd2t2ohlcv", "h": "", "e": "csv"},
        )
        if payload is None:
            continue
        text = payload.decode("utf-8-sig", errors="replace")
        try:
            row = next(csv.DictReader(text.splitlines()))
        except (StopIteration, csv.Error):
            continue
        close = parse_float(row.get("Close"))
        if close is None:
            continue
        return source_result(
            round(close, 3),
            source_name,
            source_url=f"{STOOQ_QUOTE_URL}?s={urllib.parse.quote(symbol)}&f=sd2t2ohlcv&h&e=csv",
            note_zh=note_zh,
            support_level="PUBLIC_MARKET_DATA",
            source_date=row.get("Date", ""),
        )
    return None


def fetch_fred_series_latest(series_id: str) -> tuple[float, str] | None:
    url = FRED_SERIES_URL.format(series_id=urllib.parse.quote(series_id, safe=""))
    data = fetch_bytes(url)
    if data is None:
        return None
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(text.splitlines())
    latest_value: float | None = None
    latest_date = ""
    for row in reader:
        value = parse_float(row.get(series_id))
        if value is not None:
            latest_value = value
            latest_date = row.get("observation_date", "")
    if latest_value is None:
        return None
    return latest_value, latest_date


def fetch_fred_public_series_value(
    series_id: str,
    *,
    source_name: str,
    note_zh: str,
    decimals: int = 3,
) -> dict[str, Any] | None:
    latest = fetch_fred_series_latest(series_id)
    if latest is None:
        return None
    latest_value, latest_date = latest
    return source_result(
        round(latest_value, decimals),
        source_name,
        source_url=FRED_SERIES_URL.format(series_id=urllib.parse.quote(series_id, safe="")),
        note_zh=f"{note_zh}；FRED 最新觀察日 {latest_date}。",
        support_level="PUBLIC_OFFICIAL_SERIES",
        source_date=latest_date,
    )


def first_available_source(fetchers: list[tuple[str, Any]]) -> dict[str, Any] | None:
    for label, fetcher in fetchers:
        result = fetcher()
        if result is not None and result.get("value") not in (None, ""):
            return result
        log(f"{label} 未取得資料，嘗試下一來源。", "WARN")
    return None


def fetch_macro_vix() -> dict[str, Any] | None:
    return first_available_source([
        (
            "FRED VIXCLS",
            lambda: fetch_fred_public_series_value(
                "VIXCLS",
                source_name="FRED_VIXCLS_CBOE_VIX",
                note_zh="FRED VIXCLS（CBOE VIX）作為 VIX 優先來源",
                decimals=2,
            ),
        ),
        (
            "Stooq VIX",
            lambda: fetch_stooq_quote_value(
                ["^vix", "vix"],
                source_name="STOOQ_VIX_PUBLIC_MARKET",
                note_zh="Stooq 公開市場 VIX 備援；正式發布前仍需來源註記",
            ),
        ),
        ("Yahoo VIX", lambda: fetch_yahoo_chart_value("^VIX", source_name="YAHOO_FINANCE_VIX")),
    ])


def fetch_macro_wti() -> dict[str, Any] | None:
    return first_available_source([
        (
            "FRED DCOILWTICO",
            lambda: fetch_fred_public_series_value(
                "DCOILWTICO",
                source_name="FRED_DCOILWTICO_WTI",
                note_zh="FRED DCOILWTICO 作為 WTI 優先來源",
                decimals=2,
            ),
        ),
        (
            "Stooq CL.F",
            lambda: fetch_stooq_quote_value(
                ["cl.f", "cl"],
                source_name="STOOQ_WTI_PUBLIC_MARKET",
                note_zh="Stooq WTI/CL 公開市場備援；正式發布前仍需來源註記",
            ),
        ),
        ("Yahoo WTI", lambda: fetch_yahoo_chart_value("CL=F", source_name="YAHOO_FINANCE_WTI")),
    ])


def fetch_macro_twd_usd() -> dict[str, Any] | None:
    return first_available_source([
        (
            "FRED DEXTAUS",
            lambda: fetch_fred_public_series_value(
                "DEXTAUS",
                source_name="FRED_DEXTAUS_TWD_USD",
                note_zh="FRED DEXTAUS 作為新台幣兌美元優先來源",
                decimals=3,
            ),
        ),
        (
            "Stooq USDTWD",
            lambda: fetch_stooq_quote_value(
                ["usdtwd", "usdtwd.pl"],
                source_name="STOOQ_USDTWD_PUBLIC_MARKET",
                note_zh="Stooq USD/TWD 公開市場備援；正式發布前仍需來源註記",
            ),
        ),
        ("Yahoo TWD", lambda: fetch_yahoo_chart_value("TWD=X", source_name="YAHOO_FINANCE_TWD_USD")),
    ])


def fetch_macro_us10y() -> dict[str, Any] | None:
    return first_available_source([
        (
            "FRED DGS10",
            lambda: fetch_fred_public_series_value(
                "DGS10",
                source_name="FRED_DGS10_US10Y",
                note_zh="FRED DGS10 作為美國 10 年期公債殖利率優先來源",
                decimals=3,
            ),
        ),
        ("Yahoo TNX", lambda: fetch_yahoo_chart_value("^TNX", source_name="YAHOO_FINANCE_US10Y")),
    ])


def fetch_macro_dxy() -> dict[str, Any] | None:
    return first_available_source([
        (
            "Stooq DXY",
            lambda: fetch_stooq_quote_value(
                ["dx.f", "dxy", "usdidx"],
                source_name="STOOQ_DXY_PUBLIC_MARKET",
                note_zh="Stooq DXY 公開市場備援；ICE DXY 授權來源未接入前需標示來源限制",
            ),
        ),
        ("Yahoo DXY", lambda: fetch_yahoo_chart_value("DX-Y.NYB", source_name="YAHOO_FINANCE_DXY")),
    ])


def fetch_fred_dff_rate() -> dict[str, Any] | None:
    latest = fetch_fred_series_latest("DFF")
    if latest is None:
        return None
    latest_value, latest_date = latest
    return source_result(
        round(latest_value, 3),
        "FRED_DFF_EFFECTIVE_FED_FUNDS_RATE",
        source_url=FRED_DFF_URL,
        note_zh=f"FRED DFF 有效聯邦基金利率；最新觀察日 {latest_date}。",
        support_level="PUBLIC_OFFICIAL_SERIES",
    )


def fetch_fred_target_rate_midpoint() -> dict[str, Any] | None:
    upper = fetch_fred_series_latest("DFEDTARU")
    lower = fetch_fred_series_latest("DFEDTARL")
    if upper is None or lower is None:
        return None
    upper_value, upper_date = upper
    lower_value, lower_date = lower
    midpoint = (upper_value + lower_value) / 2
    source_url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU,DFEDTARL"
    return source_result(
        round(midpoint, 3),
        "FRED_FOMC_TARGET_RANGE_MIDPOINT",
        source_url=source_url,
        note_zh=(
            f"FRED FOMC 目標區間中位數；上限 DFEDTARU={upper_value:g}（{upper_date}），"
            f"下限 DFEDTARL={lower_value:g}（{lower_date}）。"
        ),
        support_level="PUBLIC_OFFICIAL_SERIES",
    )


def fetch_cme_fedwatch_year_end_hike_probability() -> dict[str, Any] | None:
    # Fed_Hike_Prob_YE is a market-implied probability, not an official Fed statistic.
    # Until a durable CME data endpoint and meeting-calendar mapping are implemented,
    # do not fabricate or silently update this field from unrelated rates.
    return source_result(
        None,
        "CME_FEDWATCH_CONNECTOR_PENDING",
        source_url=CME_FEDWATCH_PAGE_URL,
        note_zh="CME FedWatch 年底升息機率 connector 尚未實作；不得用模型或 FRED 利率代替。",
        support_level="CONNECTOR_PENDING",
    )


def choose_value(
    explicit_value: float | None,
    fetched: dict[str, Any] | None,
    *,
    carry_value: str | None = None,
    explicit_source: str = "OWNER_INPUT_CLI",
    carry_source: str = "FORMAL_CSV_CARRY_FORWARD",
    carry_note_zh: str = "沿用已核准正式 CSV 的最近值；需在 UI 標示為沿用值。",
) -> dict[str, Any]:
    if explicit_value is not None:
        return source_result(explicit_value, explicit_source, note_zh="Owner 於 BAT/CLI 明確輸入。", support_level="OWNER_INPUT")
    if fetched is not None and fetched.get("value") not in (None, ""):
        return fetched
    carry_number = parse_float(carry_value)
    if carry_number is not None:
        return source_result(round(carry_number, 3), carry_source, note_zh=carry_note_zh, support_level="CARRY_FORWARD")
    return source_result(None, "DATA_MISSING", note_zh="未取得資料。")


def fetch_stock_close(explicit_value: float | None, no_fetch: bool, candidate_date: str) -> dict[str, Any]:
    if explicit_value is not None:
        return source_result(explicit_value, "OWNER_INPUT_CLI", note_zh="Owner 手動輸入收盤價。", support_level="OWNER_INPUT")
    if no_fetch:
        return source_result(None, "DATA_MISSING", note_zh="使用 --no-fetch，未連線抓取股價。")

    for fetcher in (fetch_twse_stock_day_close, fetch_twse_realtime_close, fetch_twse_official_close):
        result = fetcher(candidate_date)
        if result is not None:
            return result
    yahoo_result = fetch_yahoo_chart_value(
        "2317.TW",
        source_name="YAHOO_FINANCE_2317TW_FALLBACK",
        note_zh="Yahoo Finance 備援股價；正式發布前需 Owner 確認。",
    )
    if yahoo_result is not None:
        return yahoo_result
    return source_result(None, "DATA_MISSING", note_zh="TWSE 官方、TWSE 即時與 Yahoo 備援均未取得股價。")


def propose_risk_level(values: dict[str, float | None]) -> dict[str, Any]:
    caution_triggers: list[str] = []
    systemic_triggers: list[str] = []

    vix = values.get("vix")
    if vix is not None and vix > 27:
        systemic_triggers.append(f"VIX={vix}")

    us10y = values.get("us10y")
    if us10y is not None:
        if us10y > 4.8:
            systemic_triggers.append(f"US_10Y={us10y}%")
        elif us10y > 4.2:
            caution_triggers.append(f"US_10Y={us10y}%")

    wti = values.get("wti")
    if wti is not None:
        if wti > 105:
            systemic_triggers.append(f"WTI={wti}")
        elif wti > 90:
            caution_triggers.append(f"WTI={wti}")

    twd_usd = values.get("twd_usd")
    if twd_usd is not None and twd_usd > 32.5:
        systemic_triggers.append(f"TWD_USD={twd_usd}")

    dxy = values.get("dxy")
    if dxy is not None and dxy > 106:
        caution_triggers.append(f"DXY={dxy}")

    fed_prob = values.get("fed_prob")
    if fed_prob is not None and fed_prob > 70:
        caution_triggers.append(f"Fed_Hike_Prob_YE={fed_prob}%")

    if len(systemic_triggers) >= 2:
        level = "SYSTEMIC"
        level_zh = "系統性風險"
    elif systemic_triggers or caution_triggers:
        level = "CAUTION"
        level_zh = "警戒"
    else:
        level = "NORMAL"
        level_zh = "正常"

    return {
        "code": "RISK_LEVEL_PROPOSED",
        "level": level,
        "levelZh": level_zh,
        "triggers": systemic_triggers + caution_triggers,
        "actionable": False,
        "noteZh": "此為風險提醒與重審提示，不啟用交易規則。",
    }


def build_risk_note(proposed_risk: dict[str, Any], source_notes: list[str], owner_note: str | None) -> str:
    trigger_text = "；".join(proposed_risk.get("triggers", [])) or "無主要觸發條件"
    parts = [f"自動建議：{proposed_risk['level']}；觸發：{trigger_text}"]
    if source_notes:
        parts.append("資料註記：" + "；".join(source_notes))
    if owner_note:
        parts.append("Owner 備註：" + owner_note)
    parts.append("僅供觀察，actionable:false")
    return "；".join(parts)


EVENT_INPUT_FIELDS = (
    "event_type",
    "event_title",
    "event_region",
    "event_source_tier",
    "event_source_name",
    "event_source_url",
    "event_evidence_status",
    "event_risk_tag",
    "black_swan_level",
    "event_related_metrics",
    "event_summary_zh",
    "event_decision_impact_zh",
)


def text_arg(value: Any) -> str:
    return str(value or "").strip()


def normalize_observation_code(value: Any, allowed: set[str], default: str) -> str:
    normalized = text_arg(value or default).upper()
    return normalized if normalized in allowed else default


def has_owner_event_input(args: argparse.Namespace) -> bool:
    return any(text_arg(getattr(args, field, "")) for field in EVENT_INPUT_FIELDS)


def build_macro_event_observation(args: argparse.Namespace, candidate_date: str) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    if not has_owner_event_input(args):
        warnings.append("macro_event_observations_candidate.csv not generated: no Owner event input supplied.")
        return None, warnings

    missing = [
        label
        for label, value in {
            "EventTitle": args.event_title,
            "SourceTier": args.event_source_tier,
            "SourceName": args.event_source_name,
            "SummaryZh": args.event_summary_zh,
        }.items()
        if not text_arg(value)
    ]
    if missing:
        warnings.append(
            "macro_event_observations_candidate.csv not generated: incomplete Owner event input "
            f"({', '.join(missing)})."
        )
        return None, warnings

    black_swan_level = normalize_observation_code(
        args.black_swan_level,
        {"OBSERVE", "WATCH", "REVIEW_REQUIRED"},
        "OBSERVE",
    )
    risk_tag = normalize_observation_code(
        args.event_risk_tag,
        {"OBSERVE", "WATCH", "REVIEW_REQUIRED"},
        "OBSERVE",
    )
    return {
        "Date": candidate_date,
        "EventType": text_arg(args.event_type) or "OWNER_NOTE",
        "EventTitle": text_arg(args.event_title),
        "Region": text_arg(args.event_region) or "GLOBAL",
        "SourceTier": text_arg(args.event_source_tier).upper(),
        "SourceName": text_arg(args.event_source_name),
        "SourceUrl": text_arg(args.event_source_url),
        "EvidenceStatus": text_arg(args.event_evidence_status) or "OWNER_REVIEW_REQUIRED",
        "RiskTag": risk_tag,
        "BlackSwanLevel": black_swan_level,
        "RelatedMetrics": text_arg(args.event_related_metrics),
        "SummaryZh": text_arg(args.event_summary_zh),
        "DecisionImpactZh": text_arg(args.event_decision_impact_zh)
        or "Observation only; review prompt only; HOLD and rules unchanged.",
        "Actionable": "false",
    }, warnings


def classify_fx_trend(twd_usd: float | None, dxy: float | None, jpy_usd: float | None) -> tuple[str, str, str]:
    if twd_usd is None and dxy is None:
        return "DATA_MISSING", "OBSERVE_DATA_GAP", "FX observation has missing TWD_USD and DXY inputs."

    trend = "NEUTRAL"
    if twd_usd is not None:
        if twd_usd >= 32.5:
            trend = "TWD_WEAKNESS_HIGH_PRESSURE"
        elif twd_usd >= 32.0:
            trend = "TWD_WEAKNESS_WATCH"
        elif twd_usd <= 30.5:
            trend = "TWD_STRENGTH_HIGH_PRESSURE"
        elif twd_usd <= 31.0:
            trend = "TWD_STRENGTH_WATCH"

    pressure = "OBSERVE"
    if (twd_usd is not None and (twd_usd >= 33.0 or twd_usd <= 30.0)) or (dxy is not None and dxy >= 110):
        pressure = "REVIEW_REQUIRED"
    elif (
        (twd_usd is not None and (twd_usd >= 32.5 or twd_usd <= 30.5))
        or (dxy is not None and dxy >= 106)
        or (jpy_usd is not None and jpy_usd >= 160)
    ):
        pressure = "WATCH"

    if trend.startswith("TWD_STRENGTH"):
        eps_note = "TWD strength may pressure translated revenue and EPS; observation only."
    elif trend.startswith("TWD_WEAKNESS"):
        eps_note = "TWD weakness may support translated revenue but can raise input-cost risk; observation only."
    else:
        eps_note = "FX trend is neutral or incomplete; observation only."
    return trend, pressure, eps_note


def source_tier_from_results(results: list[dict[str, Any]]) -> str:
    tiers = {str(result.get("supportLevel") or result.get("source") or "").upper() for result in results}
    tiers.discard("")
    if "OWNER_INPUT" in tiers:
        return "OWNER_INPUT"
    if "PUBLIC_OFFICIAL_SERIES" in tiers and "PUBLIC_MARKET_DATA" in tiers:
        return "PUBLIC_MARKET_AND_OFFICIAL_SERIES"
    if "PUBLIC_MARKET_DATA" in tiers:
        return "PUBLIC_MARKET_DATA"
    if "PUBLIC_OFFICIAL_SERIES" in tiers:
        return "PUBLIC_OFFICIAL_SERIES"
    if "CARRY_FORWARD" in tiers:
        return "CARRY_FORWARD"
    if "CONNECTOR_PENDING" in tiers:
        return "CONNECTOR_PENDING"
    return "UNVERIFIED"


def join_source_urls(results: list[dict[str, Any]]) -> str:
    urls: list[str] = []
    for result in results:
        url = text_arg(result.get("sourceUrl"))
        if url and url not in urls:
            urls.append(url)
    return " | ".join(urls)


def build_fx_trend_observation(
    candidate_date: str,
    values_for_risk: dict[str, float | None],
    macro_results: dict[str, dict[str, Any]],
    jpy_result: dict[str, Any],
    boj_result: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    twd_usd = values_for_risk.get("twd_usd")
    dxy = values_for_risk.get("dxy")
    us10y = values_for_risk.get("us10y")
    fed_rate = values_for_risk.get("fed_rate")
    jpy_usd = parse_float(jpy_result.get("value"))
    boj_rate = parse_float(boj_result.get("value"))
    if jpy_usd is None:
        warnings.append("JPY_USD missing in FX sidecar; observation row is marked with an FX data gap.")
    if boj_rate is None:
        warnings.append("BOJ_Rate missing in FX sidecar; RateSpread_US_JP cannot be computed.")

    spread = round(fed_rate - boj_rate, 3) if fed_rate is not None and boj_rate is not None else ""
    trend, pressure, eps_note = classify_fx_trend(twd_usd, dxy, jpy_usd)
    if jpy_usd is None or boj_rate is None:
        pressure = "OBSERVE_DATA_GAP" if pressure == "OBSERVE" else pressure

    source_results = [
        macro_results["twd_usd"],
        macro_results["dxy"],
        macro_results["us10y"],
        macro_results["fed_rate"],
        jpy_result,
        boj_result,
    ]
    summary_parts = [
        f"TWD_USD={round_value(twd_usd, 3)}",
        f"DXY={round_value(dxy, 3)}",
        f"JPY_USD={round_value(jpy_usd, 3)}",
        f"Fed_Rate={round_value(fed_rate, 3)}",
        f"BOJ_Rate={round_value(boj_rate, 3)}",
    ]
    return {
        "Date": candidate_date,
        "TWD_USD": round_value(twd_usd, 3),
        "DXY": round_value(dxy, 3),
        "JPY_USD": round_value(jpy_usd, 3),
        "US_10Y_Yield": round_value(us10y, 3),
        "Fed_Rate": round_value(fed_rate, 3),
        "BOJ_Rate": round_value(boj_rate, 3),
        "RateSpread_US_JP": spread,
        "FxTrend": trend,
        "FxPressureLevel": pressure,
        "EPSImpactEstimateZh": eps_note,
        "SourceTier": source_tier_from_results(source_results),
        "SourceUrl": join_source_urls(source_results),
        "SummaryZh": "; ".join(summary_parts),
        "Actionable": "false",
    }, warnings


def target_has_event_observation(path: Path, row: dict[str, Any]) -> bool:
    if not path.exists():
        return False
    _, rows = read_csv_with_comments(path)
    row_key = (
        str(row.get("Date", "")),
        str(row.get("EventTitle", "")),
        str(row.get("SourceUrl", "")),
    )
    for existing in rows:
        existing_key = (
            str(existing.get("Date", "")),
            str(existing.get("EventTitle", "")),
            str(existing.get("SourceUrl", "")),
        )
        if existing_key == row_key:
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate P1008 staging candidates without writing formal CSV files.")
    parser.add_argument("--package-root", type=Path)
    parser.add_argument("--date", dest="candidate_date")
    parser.add_argument("--stock-price", type=float)
    parser.add_argument("--vix", type=float)
    parser.add_argument("--wti", type=float)
    parser.add_argument("--twd-usd", type=float)
    parser.add_argument("--us10y", type=float)
    parser.add_argument("--dxy", type=float)
    parser.add_argument("--fed-rate", type=float)
    parser.add_argument("--fed-prob", type=float)
    parser.add_argument("--jpy-usd", type=float)
    parser.add_argument("--boj-rate", type=float)
    parser.add_argument("--event-type")
    parser.add_argument("--event-title")
    parser.add_argument("--event-region")
    parser.add_argument("--event-source-tier")
    parser.add_argument("--event-source-name")
    parser.add_argument("--event-source-url")
    parser.add_argument("--event-evidence-status")
    parser.add_argument("--event-risk-tag")
    parser.add_argument("--black-swan-level")
    parser.add_argument("--event-related-metrics")
    parser.add_argument("--event-summary-zh")
    parser.add_argument("--event-decision-impact-zh")
    parser.add_argument("--risk-note")
    parser.add_argument("--no-fetch", action="store_true", help="Do not call network sources; use explicit inputs and carry-forward only.")
    args = parser.parse_args()

    package_root = args.package_root.resolve() if args.package_root else Path(__file__).resolve().parents[1]
    candidate_date = args.candidate_date or date.today().isoformat()
    try:
        datetime.strptime(candidate_date, "%Y-%m-%d")
    except ValueError:
        log("日期格式錯誤，請使用 YYYY-MM-DD", "ERROR")
        return 2

    staging_dir = package_root / "staging" / candidate_date
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        master = verify_master_authority(package_root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        log(str(error), "ERROR")
        log("正式 CSV 未被修改；請先修復 manifest 或 master CSV 授權狀態。", "INFO")
        return 2

    latest_macro = load_latest_macro_row(package_root) or {}
    latest_fx = load_latest_csv_row(package_root, FX_TREND_TARGET) or {}
    latest_daily = load_latest_csv_row(package_root, "data/2317_daily_price.csv") or {}

    if args.no_fetch:
        fetched_macro = {
            "vix": None,
            "wti": None,
            "twd_usd": None,
            "us10y": None,
            "dxy": None,
            "fed_rate": None,
            "fed_prob": None,
            "jpy_usd": None,
        }
    else:
        fetched_macro = {
            "vix": fetch_macro_vix(),
            "wti": fetch_macro_wti(),
            "twd_usd": fetch_macro_twd_usd(),
            "us10y": fetch_macro_us10y(),
            "dxy": fetch_macro_dxy(),
            "fed_rate": fetch_fred_target_rate_midpoint(),
            "fed_prob": fetch_cme_fedwatch_year_end_hike_probability(),
            "jpy_usd": fetch_yahoo_chart_value("JPY=X", source_name="YAHOO_FINANCE_JPY_USD"),
        }

    stock_result = fetch_stock_close(args.stock_price, args.no_fetch, candidate_date)
    if parse_float(stock_result.get("value")) is None:
        carry_stock_result = market_closed_carry_forward_price(candidate_date, latest_daily)
        if carry_stock_result is not None:
            stock_result = carry_stock_result
    macro_results = {
        "vix": choose_value(
            args.vix,
            fetched_macro["vix"],
            carry_value=latest_macro.get("VIX"),
            carry_source="CONNECTOR_SOURCE_UNAVAILABLE_CARRY_FORWARD",
            carry_note_zh="VIX 官方/公開市場 connector 未取得；沿用正式 CSV 最近值作觀察，不可單獨支持正式發布。",
        ),
        "wti": choose_value(
            args.wti,
            fetched_macro["wti"],
            carry_value=latest_macro.get("WTI_Oil"),
            carry_source="CONNECTOR_SOURCE_UNAVAILABLE_CARRY_FORWARD",
            carry_note_zh="WTI 官方/公開市場 connector 未取得；沿用正式 CSV 最近值作觀察，不可單獨支持正式發布。",
        ),
        "twd_usd": choose_value(
            args.twd_usd,
            fetched_macro["twd_usd"],
            carry_value=latest_macro.get("TWD_USD"),
            carry_source="CONNECTOR_SOURCE_UNAVAILABLE_CARRY_FORWARD",
            carry_note_zh="TWD/USD 官方/公開市場 connector 未取得；沿用正式 CSV 最近值作觀察，不可單獨支持正式發布。",
        ),
        "us10y": choose_value(
            args.us10y,
            fetched_macro["us10y"],
            carry_value=latest_macro.get("US_10Y_Yield"),
            carry_source="CONNECTOR_SOURCE_UNAVAILABLE_CARRY_FORWARD",
            carry_note_zh="US10Y 官方/公開市場 connector 未取得；沿用正式 CSV 最近值作觀察，不可單獨支持正式發布。",
        ),
        "dxy": choose_value(
            args.dxy,
            fetched_macro["dxy"],
            carry_value=latest_macro.get("DXY"),
            carry_source="CONNECTOR_SOURCE_UNAVAILABLE_CARRY_FORWARD",
            carry_note_zh="DXY 公開市場 connector 未取得；沿用正式 CSV 最近值作觀察，不可單獨支持正式發布。",
        ),
        "fed_rate": choose_value(
            args.fed_rate,
            fetched_macro["fed_rate"],
            carry_value=latest_macro.get("Fed_Rate"),
            carry_note_zh="Fed Rate 應由 FRED DFEDTARU/DFEDTARL 目標區間中位數取得；本次連線失敗時沿用正式 CSV 最近值。",
        ),
        "fed_prob": choose_value(
            args.fed_prob,
            fetched_macro["fed_prob"],
            carry_value=latest_macro.get("Fed_Hike_Prob_YE"),
            carry_note_zh="Fed 年底升息機率尚無穩定 CME FedWatch connector；沿用正式 CSV 既有值，僅作風險觀察。",
        ),
    }

    jpy_result = choose_value(
        args.jpy_usd,
        fetched_macro["jpy_usd"],
        carry_value=latest_fx.get("JPY_USD"),
        carry_note_zh="JPY_USD sidecar carry-forward; observation only.",
    )
    boj_result = choose_value(
        args.boj_rate,
        None,
        carry_value=latest_fx.get("BOJ_Rate"),
        carry_note_zh="BOJ_Rate sidecar carry-forward; BOJ connector remains pending.",
    )

    generated_files: list[str] = []
    already_published_targets: list[str] = []
    validation_checks: list[dict[str, Any]] = []
    critical_missing_fields: list[str] = []
    optional_missing_fields: list[str] = []
    unavailable_candidate_fields: list[str] = []
    data_quality_warnings: list[str] = []

    for field_name, result in macro_results.items():
        if result.get("source") == "CONNECTOR_SOURCE_UNAVAILABLE_CARRY_FORWARD" and result.get("noteZh"):
            data_quality_warnings.append(f"{field_name}: {result['noteZh']}")

    daily_row: dict[str, Any] | None = None
    close = parse_float(stock_result.get("value"))
    if close is not None:
        pb_value = round(close / float(master["bvps"]), 3)
        daily_status = "STAGING_CANDIDATE"
        support_level = stock_result.get("supportLevel") or "L3"
        publish_daily_candidate = bool(stock_result.get("publishCandidate", True))
        if support_level == "RUNTIME_OBSERVATION":
            daily_status = "RUNTIME_REVIEW_REQUIRED"
            data_quality_warnings.append("股價來源為即時/備援行情，正式發布前需確認已收盤。")
        if support_level == "MARKET_CLOSED_CARRY_FORWARD":
            daily_status = "MARKET_CLOSED_CARRY_FORWARD"
            publish_daily_candidate = False
            data_quality_warnings.append(stock_result.get("noteZh") or stock_close_missing_note(candidate_date))
        daily_row = {
            "Date": candidate_date,
            "Close": round(close, 3),
            "QuarterKey": master["quarter"],
            "BVPS_ref": round(float(master["bvps"]), 3),
            "PB_daily": pb_value,
            "DataSupportLevel": support_level,
            "Status": daily_status,
        }
        daily_path = staging_dir / "2317_daily_price_candidate.csv"
        write_csv(daily_path, DAILY_COLUMNS, daily_row)
        if not publish_daily_candidate:
            data_quality_warnings.append("休市沿用列僅供 runtime/UI，不列入正式 daily_price append。")
        elif target_has_key(package_root / "data" / "2317_daily_price.csv", candidate_date):
            already_published_targets.append("data/2317_daily_price.csv")
            data_quality_warnings.append("2317_daily_price.csv 已有同日期正式資料，候選檔僅供檢視，不列入 append。")
        else:
            generated_files.append(str(daily_path.relative_to(package_root)))
        validation_checks.append(
            {
                "dataset": "daily",
                "schemaColumns": len(DAILY_COLUMNS),
                "rowColumns": len(daily_row),
                "status": "PASS_WITH_WARNINGS" if not publish_daily_candidate else "PASS",
                "statusZh": (
                    "休市日沿用最近正式收盤價供 UI/PB 連續，不列入正式 append。"
                    if not publish_daily_candidate
                    else "每日股價候選檔欄位完整；正式發布仍需 Owner 核准。"
                ),
            }
        )
    else:
        unavailable_candidate_fields.append("Close")
        data_quality_warnings.append(stock_close_missing_note(candidate_date))

    values_for_risk = {
        "vix": parse_float(macro_results["vix"].get("value")),
        "wti": parse_float(macro_results["wti"].get("value")),
        "twd_usd": parse_float(macro_results["twd_usd"].get("value")),
        "us10y": parse_float(macro_results["us10y"].get("value")),
        "dxy": parse_float(macro_results["dxy"].get("value")),
        "fed_rate": parse_float(macro_results["fed_rate"].get("value")),
        "fed_prob": parse_float(macro_results["fed_prob"].get("value")),
    }
    proposed_risk = propose_risk_level(values_for_risk)

    carry_forward_fields = {
        "CSP_Capex_Signal": latest_macro.get("CSP_Capex_Signal", ""),
        "Hon_Hai_Rev_YoY": latest_macro.get("Hon_Hai_Rev_YoY", ""),
        "Foreign_Net_Buy": latest_macro.get("Foreign_Net_Buy", ""),
        "TW_Export_YoY": latest_macro.get("TW_Export_YoY", ""),
        "US_GDP_QoQ": latest_macro.get("US_GDP_QoQ", ""),
        "US_CPI_YoY": latest_macro.get("US_CPI_YoY", ""),
        "TW_GDP_QoQ": latest_macro.get("TW_GDP_QoQ", ""),
        "TAIEX_Weekly_Chg": latest_macro.get("TAIEX_Weekly_Chg", ""),
    }
    for field, value in carry_forward_fields.items():
        if value:
            data_quality_warnings.append(f"{field} 沿用正式 CSV 最近值。")

    source_notes = [
        result["noteZh"]
        for result in [stock_result, *macro_results.values()]
        if str(result.get("source", "")).endswith("CARRY_FORWARD") and result.get("noteZh")
    ]
    macro_row = {
        "Date": candidate_date,
        "TWD_USD": round_value(values_for_risk["twd_usd"], 3),
        "VIX": round_value(values_for_risk["vix"], 2),
        "WTI_Oil": round_value(values_for_risk["wti"], 2),
        "US_10Y_Yield": round_value(values_for_risk["us10y"], 3),
        "Fed_Rate": round_value(values_for_risk["fed_rate"], 3),
        "Fed_Hike_Prob_YE": round_value(values_for_risk["fed_prob"], 1),
        "DXY": round_value(values_for_risk["dxy"], 3),
        "US_GDP_QoQ": carry_forward_fields["US_GDP_QoQ"],
        "US_CPI_YoY": carry_forward_fields["US_CPI_YoY"],
        "TW_GDP_QoQ": carry_forward_fields["TW_GDP_QoQ"],
        "TAIEX_Weekly_Chg": carry_forward_fields["TAIEX_Weekly_Chg"],
        "CSP_Capex_Signal": carry_forward_fields["CSP_Capex_Signal"],
        "Hon_Hai_Rev_YoY": carry_forward_fields["Hon_Hai_Rev_YoY"],
        "Foreign_Net_Buy": carry_forward_fields["Foreign_Net_Buy"],
        "TW_Export_YoY": carry_forward_fields["TW_Export_YoY"],
        "RiskLevel": proposed_risk["level"],
        "RiskNote": build_risk_note(proposed_risk, source_notes, args.risk_note),
    }
    macro_path = staging_dir / "macro_snapshot_candidate.csv"
    write_csv(macro_path, MACRO_COLUMNS, macro_row)
    if target_has_key(package_root / "data" / "macro_snapshot.csv", candidate_date):
        already_published_targets.append("data/macro_snapshot.csv")
        data_quality_warnings.append("macro_snapshot.csv 已有同日期正式資料，候選檔僅供檢視，不列入 append。")
    else:
        generated_files.append(str(macro_path.relative_to(package_root)))

    for field in ("TWD_USD", "VIX", "WTI_Oil", "US_10Y_Yield", "Fed_Rate", "DXY", "RiskLevel"):
        if macro_row[field] == "":
            critical_missing_fields.append(field)
    if macro_row["Fed_Hike_Prob_YE"] == "":
        optional_missing_fields.append("Fed_Hike_Prob_YE")

    macro_has_warnings = bool(optional_missing_fields or data_quality_warnings)
    validation_checks.append(
        {
            "dataset": "macro",
            "schemaColumns": len(MACRO_COLUMNS),
            "rowColumns": len(macro_row),
            "status": "PASS_WITH_WARNINGS" if macro_has_warnings and not critical_missing_fields else ("FAIL" if critical_missing_fields else "PASS"),
            "statusZh": (
                "總經候選檔欄位可發布但含沿用/觀察註記。"
                if macro_has_warnings and not critical_missing_fields
                else ("總經候選檔缺少核心欄位，不可正式發布。" if critical_missing_fields else "總經候選檔欄位完整。")
            ),
        }
    )

    fx_trend_row, fx_warnings = build_fx_trend_observation(
        candidate_date,
        values_for_risk,
        macro_results,
        jpy_result,
        boj_result,
    )
    data_quality_warnings.extend(fx_warnings)
    for field in ("JPY_USD", "BOJ_Rate", "RateSpread_US_JP"):
        if fx_trend_row.get(field) == "":
            optional_missing_fields.append(field)
    fx_path = staging_dir / "fx_trend_observations_candidate.csv"
    write_csv(fx_path, FX_TREND_COLUMNS, fx_trend_row)
    if target_has_key(package_root / FX_TREND_TARGET, candidate_date):
        already_published_targets.append(FX_TREND_TARGET)
        data_quality_warnings.append("fx_trend_observations.csv already has this Date; append is not declared.")
    else:
        generated_files.append(str(fx_path.relative_to(package_root)))
    validation_checks.append(
        {
            "dataset": "fx_trend_observations",
            "schemaColumns": len(FX_TREND_COLUMNS),
            "rowColumns": len(fx_trend_row),
            "status": "PASS_WITH_WARNINGS" if fx_warnings else "PASS",
            "statusZh": "FX sidecar observation-only candidate; Actionable=false; HOLD and rules unchanged.",
        }
    )

    macro_event_row, event_warnings = build_macro_event_observation(args, candidate_date)
    data_quality_warnings.extend(event_warnings)
    event_path = staging_dir / "macro_event_observations_candidate.csv"
    if macro_event_row:
        write_csv(event_path, MACRO_EVENT_COLUMNS, macro_event_row)
        if target_has_event_observation(package_root / MACRO_EVENT_TARGET, macro_event_row):
            already_published_targets.append(MACRO_EVENT_TARGET)
            data_quality_warnings.append("macro_event_observations.csv already has this Date/EventTitle/SourceUrl; append is not declared.")
        else:
            generated_files.append(str(event_path.relative_to(package_root)))
        validation_checks.append(
            {
                "dataset": "macro_event_observations",
                "schemaColumns": len(MACRO_EVENT_COLUMNS),
                "rowColumns": len(macro_event_row),
                "status": "PASS",
                "statusZh": "Owner-supplied event sidecar candidate; Actionable=false; review prompt only.",
            }
        )
    elif event_path.exists():
        try:
            with event_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=MACRO_EVENT_COLUMNS, lineterminator="\n")
                writer.writeheader()
            data_quality_warnings.append("macro_event_observations_candidate.csv reset to header-only because no Owner event input was supplied.")
        except OSError as error:
            data_quality_warnings.append(f"macro_event_observations_candidate.csv stale reset failed: {error}")

    input_sources = {
        "stock_price": stock_result["source"],
        "vix": macro_results["vix"]["source"],
        "wti": macro_results["wti"]["source"],
        "twd_usd": macro_results["twd_usd"]["source"],
        "us10y": macro_results["us10y"]["source"],
        "dxy": macro_results["dxy"]["source"],
        "fed_rate": macro_results["fed_rate"]["source"],
        "fed_prob": macro_results["fed_prob"]["source"],
        "jpy_usd": jpy_result["source"],
        "boj_rate": boj_result["source"],
    }
    if macro_event_row:
        input_sources["macro_event_source"] = macro_event_row["SourceTier"]
    source_meta = {
        "stock_price": {
            "requiredForFormal": bool(daily_row is not None and stock_result.get("publishCandidate", True)),
            "dataset": "daily",
            "statusZh": (
                "休市日沿用最近正式收盤價供 UI/PB 連續，不列入正式 append。"
                if daily_row is not None and not stock_result.get("publishCandidate", True)
                else "若產生每日股價候選檔，Close 必須存在。"
            ),
            "sourceUrl": stock_result.get("sourceUrl", ""),
        },
        "vix": {"requiredForFormal": True, "dataset": "macro", "sourceUrl": macro_results["vix"].get("sourceUrl", "")},
        "wti": {"requiredForFormal": True, "dataset": "macro", "sourceUrl": macro_results["wti"].get("sourceUrl", "")},
        "twd_usd": {"requiredForFormal": True, "dataset": "macro", "sourceUrl": macro_results["twd_usd"].get("sourceUrl", "")},
        "us10y": {"requiredForFormal": True, "dataset": "macro", "sourceUrl": macro_results["us10y"].get("sourceUrl", "")},
        "dxy": {"requiredForFormal": True, "dataset": "macro", "sourceUrl": macro_results["dxy"].get("sourceUrl", "")},
        "fed_rate": {
            "requiredForFormal": True,
            "dataset": "macro",
            "sourceUrl": macro_results["fed_rate"].get("sourceUrl", ""),
            "statusZh": "Fed_Rate 採 FRED DFEDTARU/DFEDTARL 目標區間中位數；若連線失敗才沿用正式 CSV 並標示中文註記。",
        },
        "fed_prob": {
            "requiredForFormal": False,
            "dataset": "macro",
            "sourceUrl": macro_results["fed_prob"].get("sourceUrl", ""),
            "statusZh": "Fed 年底升息機率為 CME FedWatch 市場隱含觀察欄位；connector 未穩定前缺失不阻斷正式發布，但 UI 必須標示中文註記。",
        },
    }
    source_meta["jpy_usd"] = {
        "requiredForFormal": False,
        "dataset": "fx_trend_observations",
        "sourceUrl": jpy_result.get("sourceUrl", ""),
        "statusZh": "JPY_USD sidecar observation only; not required for macro_snapshot formal publish.",
    }
    source_meta["boj_rate"] = {
        "requiredForFormal": False,
        "dataset": "fx_trend_observations",
        "sourceUrl": boj_result.get("sourceUrl", ""),
        "statusZh": "BOJ_Rate sidecar observation only; connector pending unless Owner supplies a value.",
    }
    if macro_event_row:
        source_meta["macro_event_source"] = {
            "requiredForFormal": False,
            "dataset": "macro_event_observations",
            "sourceUrl": macro_event_row.get("SourceUrl", ""),
            "statusZh": "Owner-supplied event observation only; not formal market data.",
        }

    macro_source_health = build_macro_source_health(candidate_date, stock_result, macro_results, daily_row)
    required_macro_sources = [
        item for item in macro_source_health
        if item.get("requiredForFormal")
    ]
    formal_ready_sources = [
        item for item in required_macro_sources
        if item.get("supportsFormal")
        and str(item.get("inputSource", "")).upper()
        not in {"CONNECTOR_SOURCE_UNAVAILABLE_CARRY_FORWARD", "DATA_MISSING"}
    ]
    missing_or_carry_forward = [
        item["field"] for item in required_macro_sources
        if not item.get("supportsFormal")
    ]
    macro_source_summary = {
        "requiredCount": len(required_macro_sources),
        "formalReadyCount": len(formal_ready_sources),
        "missingOrCarryForward": missing_or_carry_forward,
        "statusZh": (
            f"{len(formal_ready_sources)}/{len(required_macro_sources)} 個 required macro sources 目前可支持正式發布；"
            "市場/匯率沿用值只供 UI 觀察，不支持正式發布。"
        ),
    }

    generated_at = datetime.now().isoformat(timespec="seconds")
    dry_run = {
        "task": "P1008_STAGING_UPDATE",
        "toolVersion": "warroom_data_fetcher_v2",
        "generatedAt": generated_at,
        "candidateDate": candidate_date,
        "productionCsvModified": False,
        "productionCsvModifiedZh": "正式 CSV 未被修改",
        "formalPublishRuleZh": "正式 CSV 只能由 3_OWNER核准發布正式CSV.bat 在 Owner 明確核准後 append。",
        "masterAuthority": {
            "file": str(master["path"].relative_to(package_root)),
            "sha256": master["sha256"],
            "quarter": master["quarter"],
            "validationStatus": master["validationStatus"],
        },
        "inputSources": input_sources,
        "sourceMeta": source_meta,
        "macroSourceHealth": macro_source_health,
        "macroSourceSummary": macro_source_summary,
        "marketProxyManifest": MARKET_PROXY_MANIFEST,
        "criticalMissingFields": sorted(set(critical_missing_fields)),
        "missingFields": sorted(set(critical_missing_fields)),
        "optionalMissingFields": sorted(set(optional_missing_fields)),
        "unavailableCandidateFields": sorted(set(unavailable_candidate_fields)),
        "dataQualityWarningsZh": sorted(set(data_quality_warnings)),
        "alreadyPublishedTargets": sorted(set(already_published_targets)),
        "validationChecks": validation_checks,
        "proposedRiskLevel": proposed_risk,
        "dailyRow": daily_row,
        "fxTrendRow": fx_trend_row,
        "macroEventRow": macro_event_row,
        "sidecarObservationOnly": True,
        "ownerConfirmationRequired": True,
        "ownerConfirmationRequiredZh": "候選 CSV 通過檢核後仍需 Owner 在 3_OWNER 核准流程輸入明確發布指令。",
        "generatedFiles": generated_files,
        "actionable": False,
        "actionableZh": "僅供決策參考；不自動交易，不修改正式 CSV。",
    }

    json_path = staging_dir / "DRY_RUN.json"
    json_path.write_text(json.dumps(dry_run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    critical_text = ", ".join(dry_run["criticalMissingFields"]) or "無"
    optional_text = ", ".join(dry_run["optionalMissingFields"]) or "無"
    unavailable_text = ", ".join(dry_run["unavailableCandidateFields"]) or "無"
    generated_text = "\n".join(f"- {item}" for item in generated_files) or "- 無"
    already_text = "\n".join(f"- {item}" for item in dry_run["alreadyPublishedTargets"]) or "- 無"
    warnings_text = "\n".join(f"- {item}" for item in dry_run["dataQualityWarningsZh"]) or "- 無"
    markdown = [
        "# P1008 Staging Update Dry-Run",
        "",
        f"- 產生時間：{generated_at}",
        f"- 候選日期：{candidate_date}",
        "- 正式 CSV：未修改",
        f"- v9 SHA-256：`{master['sha256']}`",
        f"- ProposedRiskLevel：`{proposed_risk['level']}`（僅供 Owner 觀察）",
        f"- 核心缺欄：{critical_text}",
        f"- 觀察缺欄：{optional_text}",
        f"- 未產生候選欄位：{unavailable_text}",
        "- actionable:false",
        "",
        "## 候選檔",
        generated_text,
        "",
        "## 同日期已在正式 CSV 的檢視檔",
        already_text,
        "",
        "## 中文資料狀態與警示",
        warnings_text,
        "",
        "## 下一步",
        "1. 先檢查本資料夾的候選 CSV 與 DRY_RUN.json。",
        "2. 若 readiness 達標，執行 `3_OWNER核准發布正式CSV.bat`。",
        "3. Owner 仍需輸入明確發布指令，正式 CSV 只會 append，不會由 UI 或抓取器覆寫。",
    ]
    (staging_dir / "DRY_RUN.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")

    runtime_dir = package_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_snapshot = {
        "task": "P1008_RUNTIME_SNAPSHOT",
        "toolVersion": "warroom_data_fetcher_v2",
        "generatedAt": generated_at,
        "candidateDate": candidate_date,
        "runtimeOnly": True,
        "runtimeOnlyZh": "臨時即時快照；尚未核准發布；正式 CSV 未被修改。",
        "productionCsvModified": False,
        "productionCsvModifiedZh": "正式 CSV 未被修改",
        "ownerConfirmationRequired": True,
        "ownerConfirmationRequiredZh": dry_run["ownerConfirmationRequiredZh"],
        "actionable": False,
        "actionableZh": dry_run["actionableZh"],
        "dailyRow": daily_row,
        "macroRow": macro_row,
        "fxTrendRow": fx_trend_row,
        "macroEventRow": macro_event_row,
        "sidecarObservationOnly": True,
        "missingFields": dry_run["missingFields"],
        "optionalMissingFields": dry_run["optionalMissingFields"],
        "unavailableCandidateFields": dry_run["unavailableCandidateFields"],
        "dataQualityWarningsZh": dry_run["dataQualityWarningsZh"],
        "alreadyPublishedTargets": dry_run["alreadyPublishedTargets"],
        "inputSources": input_sources,
        "sourceMeta": source_meta,
        "macroSourceHealth": macro_source_health,
        "macroSourceSummary": macro_source_summary,
        "marketProxyManifest": MARKET_PROXY_MANIFEST,
        "proposedRiskLevel": proposed_risk,
        "dryRunPath": str(json_path.relative_to(package_root)),
        "generatedFiles": generated_files,
    }
    runtime_path = runtime_dir / "warroom_realtime_snapshot.json"
    runtime_path.write_text(json.dumps(runtime_snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    log(f"Staging candidates written: {staging_dir}", "OK")
    log(f"Runtime snapshot written: {runtime_path}", "OK")
    log("Formal CSV files were not modified.", "OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
