"""Validate and analyze P1008 daily market activity without mutating authority data.

The module treats ``data/2317_daily_price.csv`` as the price authority and a
separate TWSE-only CSV as market-activity authority.  Missing activity data is a
documented analytical limitation, not a reason to block a fundamental report.
"""

from __future__ import annotations

import csv
import datetime as dt
import math
import statistics
import urllib.parse
from pathlib import Path
from typing import Iterable, Mapping


CSV_FIELDS = (
    "trade_date",
    "ticker",
    "volume_shares",
    "turnover_ntd",
    "transaction_count",
    "source_url",
    "retrieved_at_utc",
)
FORMAL_CSV_FIELDS = (
    "date",
    "stock_id",
    "trade_volume",
    "trade_value",
    "transaction_count",
    "source_url",
    "source_month",
)
PRICE_TICKER = "2317"
OFFICIAL_HOSTS = {"openapi.twse.com.tw", "www.twse.com.tw", "twse.com.tw"}
READY = "MARKET_LIQUIDITY_ANALYSIS_READY"
LIMITED = "MARKET_LIQUIDITY_ANALYSIS_LIMITED"
NO_INVESTOR_ATTRIBUTION = (
    "成交量與成交金額只能描述市場活動，不能據此推論法人、主力或特定投資人行為。"
)


class MarketActivityValidationError(ValueError):
    """Raised when market-activity authority fails a deterministic gate."""


class HistoricalRewriteError(MarketActivityValidationError):
    """Raised when an existing date+ticker row would be changed."""


def _parse_utc(value: str) -> dt.datetime:
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise MarketActivityValidationError("retrieved_at_utc must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
        raise MarketActivityValidationError("retrieved_at_utc must use UTC")
    return parsed


def _nonnegative_integer(value: object, field: str) -> int:
    candidate = str(value).strip().replace(",", "")
    if not candidate.isdigit():
        raise MarketActivityValidationError(f"{field} must be an integer in its declared unit")
    number = int(candidate)
    if number < 0:
        raise MarketActivityValidationError(f"{field} must be nonnegative")
    return number


def validate_activity_row(
    row: Mapping[str, object],
    *,
    as_of_date: dt.date,
    now_utc: dt.datetime | None = None,
) -> dict[str, object]:
    """Validate and normalize one TWSE market-activity row."""

    row_fields = set(row)
    is_formal = row_fields == set(FORMAL_CSV_FIELDS)
    if not is_formal and row_fields != set(CSV_FIELDS):
        expected = set(FORMAL_CSV_FIELDS) if "date" in row_fields else set(CSV_FIELDS)
        missing = sorted(expected - row_fields)
        extra = sorted(row_fields - expected)
        raise MarketActivityValidationError(f"CSV columns mismatch; missing={missing}, extra={extra}")
    required_fields = FORMAL_CSV_FIELDS if is_formal else CSV_FIELDS
    if any(str(row[field]).strip() == "" for field in required_fields):
        raise MarketActivityValidationError("all market-activity fields are required")
    trade_date_field = "date" if is_formal else "trade_date"
    ticker_field = "stock_id" if is_formal else "ticker"
    volume_field = "trade_volume" if is_formal else "volume_shares"
    turnover_field = "trade_value" if is_formal else "turnover_ntd"
    try:
        trade_date = dt.date.fromisoformat(str(row[trade_date_field]).strip())
    except ValueError as exc:
        raise MarketActivityValidationError("trade_date must be YYYY-MM-DD") from exc
    if trade_date > as_of_date:
        raise MarketActivityValidationError("future trade_date is forbidden")
    if trade_date.weekday() >= 5:
        raise MarketActivityValidationError("trade_date must be a weekday trading-date candidate")
    ticker = str(row[ticker_field]).strip()
    if ticker != PRICE_TICKER:
        raise MarketActivityValidationError("ticker must be 2317")
    source_url = str(row["source_url"]).strip()
    parsed_url = urllib.parse.urlparse(source_url)
    if parsed_url.scheme != "https" or parsed_url.hostname not in OFFICIAL_HOSTS:
        raise MarketActivityValidationError("source_url must be an official TWSE HTTPS URL")
    normalized = {
        "trade_date": trade_date.isoformat(),
        "ticker": ticker,
        "volume_shares": _nonnegative_integer(row[volume_field], "volume_shares"),
        "turnover_ntd": _nonnegative_integer(row[turnover_field], "turnover_ntd"),
        "transaction_count": _nonnegative_integer(row["transaction_count"], "transaction_count"),
        "source_url": source_url,
    }
    if is_formal:
        source_month = str(row["source_month"]).strip()
        if source_month != trade_date.strftime("%Y-%m"):
            raise MarketActivityValidationError("source_month must match trade_date month")
        normalized["source_month"] = source_month
    else:
        retrieved = _parse_utc(str(row["retrieved_at_utc"]))
        current = now_utc or dt.datetime.now(dt.timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=dt.timezone.utc)
        if retrieved > current.astimezone(dt.timezone.utc) + dt.timedelta(minutes=5):
            raise MarketActivityValidationError("future retrieved_at_utc is forbidden")
        normalized["retrieved_at_utc"] = retrieved.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    return normalized


def validate_activity_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    as_of_date: dt.date,
    historical_rows: Iterable[Mapping[str, object]] = (),
    now_utc: dt.datetime | None = None,
) -> list[dict[str, object]]:
    """Validate completeness, uniqueness, units, dates, and historical immutability."""

    normalized = [
        validate_activity_row(row, as_of_date=as_of_date, now_utc=now_utc) for row in rows
    ]
    keys = [(row["trade_date"], row["ticker"]) for row in normalized]
    if len(keys) != len(set(keys)):
        raise MarketActivityValidationError("duplicate trade_date+ticker rows are forbidden")
    historical = {
        (str(row["trade_date"]), str(row["ticker"])): validate_activity_row(
            row, as_of_date=as_of_date, now_utc=now_utc
        )
        for row in historical_rows
    }
    for row in normalized:
        key = (row["trade_date"], row["ticker"])
        if key in historical and historical[key] != row:
            raise HistoricalRewriteError(f"historical rewrite forbidden for {key[0]}+{key[1]}")
    return sorted(normalized, key=lambda item: (str(item["trade_date"]), str(item["ticker"])))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) not in (CSV_FIELDS, FORMAL_CSV_FIELDS):
            raise MarketActivityValidationError("market-activity CSV header is invalid")
        return [dict(row) for row in reader]


def read_price_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream) if row.get("Date")]


def validate_price_activity_join(
    price_rows: Iterable[Mapping[str, object]],
    activity_rows: Iterable[Mapping[str, object]],
    *,
    as_of_date: dt.date,
    now_utc: dt.datetime | None = None,
) -> dict[str, object]:
    """Validate the date+ticker join without requiring full activity coverage."""

    activities = validate_activity_rows(
        activity_rows, as_of_date=as_of_date, now_utc=now_utc
    )
    prices: dict[tuple[str, str], dict[str, object]] = {}
    for raw in price_rows:
        raw_date = str(raw.get("Date", "")).strip()
        try:
            parsed_date = dt.date.fromisoformat(raw_date)
        except ValueError as exc:
            raise MarketActivityValidationError(f"invalid price Date: {raw_date}") from exc
        if parsed_date > as_of_date or parsed_date.weekday() >= 5:
            continue
        key = (raw_date, PRICE_TICKER)
        if key in prices:
            raise MarketActivityValidationError(f"duplicate price key: {key}")
        try:
            close = float(str(raw.get("Close", "")).replace(",", ""))
        except ValueError as exc:
            raise MarketActivityValidationError(f"invalid Close for {raw_date}") from exc
        if not math.isfinite(close) or close <= 0:
            raise MarketActivityValidationError(f"invalid Close for {raw_date}")
        prices[key] = {"trade_date": raw_date, "ticker": PRICE_TICKER, "close": close}
    activity_map = {(str(row["trade_date"]), str(row["ticker"])): row for row in activities}
    orphan = sorted(set(activity_map) - set(prices))
    if orphan:
        raise MarketActivityValidationError(f"activity rows do not join to price authority: {orphan}")
    matched = [
        {**prices[key], **activity_map[key]} for key in sorted(set(prices) & set(activity_map))
    ]
    missing = [key[0] for key in sorted(set(prices) - set(activity_map))]
    return {
        "join_key": ["trade_date", "ticker"],
        "price_row_count": len(prices),
        "activity_row_count": len(activities),
        "matched_row_count": len(matched),
        "coverage_ratio": len(matched) / len(prices) if prices else 0.0,
        "missing_activity_dates": missing,
        "matched_rows": matched,
    }


def _pct(current: float, prior: float) -> float | None:
    return None if prior == 0 else (current / prior - 1.0) * 100.0


def analyze_market_activity(
    price_rows: Iterable[Mapping[str, object]],
    activity_rows: Iterable[Mapping[str, object]] | None,
    *,
    as_of_date: dt.date,
    now_utc: dt.datetime | None = None,
) -> dict[str, object]:
    """Calculate liquidity diagnostics while preserving the no-attribution boundary."""

    if activity_rows is None:
        return {
            "status": LIMITED,
            "reason": "2317_daily_market_activity.csv 尚未提供；基本面報告可繼續。",
            "volume_ratio_20": None,
            "turnover_trend": None,
            "price_volume_divergence": None,
            "investor_behavior_attribution": "NOT_PERMITTED",
            "guardrail": NO_INVESTOR_ATTRIBUTION,
            "actionable": False,
        }
    joined = validate_price_activity_join(
        price_rows, activity_rows, as_of_date=as_of_date, now_utc=now_utc
    )
    rows = list(joined["matched_rows"])
    if len(rows) < 21:
        return {
            "status": LIMITED,
            "reason": f"20 日量比至少需要 21 筆可連結交易日，目前只有 {len(rows)} 筆。",
            "join": {key: value for key, value in joined.items() if key != "matched_rows"},
            "volume_ratio_20": None,
            "turnover_trend": None,
            "price_volume_divergence": None,
            "investor_behavior_attribution": "NOT_PERMITTED",
            "guardrail": NO_INVESTOR_ATTRIBUTION,
            "actionable": False,
        }
    latest = rows[-1]
    prior_20 = rows[-21:-1]
    average_volume_20 = statistics.fmean(float(row["volume_shares"]) for row in prior_20)
    ratio = float(latest["volume_shares"]) / average_volume_20 if average_volume_20 else None
    turnover_5 = statistics.fmean(float(row["turnover_ntd"]) for row in rows[-5:])
    turnover_20 = statistics.fmean(float(row["turnover_ntd"]) for row in rows[-20:])
    turnover_vs_20 = _pct(turnover_5, turnover_20)
    price_return_5 = _pct(float(latest["close"]), float(rows[-6]["close"]))
    volume_change_5 = _pct(
        float(latest["volume_shares"]),
        statistics.fmean(float(row["volume_shares"]) for row in rows[-6:-1]),
    )
    if price_return_5 is not None and volume_change_5 is not None:
        if price_return_5 > 0 and volume_change_5 < 0:
            divergence = "PRICE_UP_VOLUME_DOWN"
        elif price_return_5 < 0 and volume_change_5 > 0:
            divergence = "PRICE_DOWN_VOLUME_UP"
        elif price_return_5 > 0 and volume_change_5 > 0:
            divergence = "PRICE_UP_VOLUME_UP"
        elif price_return_5 < 0 and volume_change_5 < 0:
            divergence = "PRICE_DOWN_VOLUME_DOWN"
        else:
            divergence = "NO_CLEAR_DIVERGENCE"
    else:
        divergence = "INSUFFICIENT_EVIDENCE"
    return {
        "status": READY,
        "as_of_date": str(latest["trade_date"]),
        "volume_shares": int(latest["volume_shares"]),
        "average_volume_shares_prior_20": average_volume_20,
        "volume_ratio_20": ratio,
        "turnover_ntd": int(latest["turnover_ntd"]),
        "transaction_count": int(latest["transaction_count"]),
        "turnover_trend": {
            "average_5_ntd": turnover_5,
            "average_20_ntd": turnover_20,
            "five_vs_twenty_pct": turnover_vs_20,
            "direction": "RISING" if (turnover_vs_20 or 0) > 0 else "FALLING_OR_FLAT",
        },
        "price_volume_divergence": {
            "classification": divergence,
            "price_return_5_pct": price_return_5,
            "latest_volume_vs_prior_5_pct": volume_change_5,
        },
        "join": {key: value for key, value in joined.items() if key != "matched_rows"},
        "investor_behavior_attribution": "NOT_PERMITTED",
        "guardrail": NO_INVESTOR_ATTRIBUTION,
        "actionable": False,
    }


def analyze_optional_files(
    price_path: Path,
    activity_path: Path,
    *,
    as_of_date: dt.date,
    now_utc: dt.datetime | None = None,
) -> dict[str, object]:
    price_rows = read_price_rows(price_path)
    if not activity_path.is_file():
        return analyze_market_activity(price_rows, None, as_of_date=as_of_date, now_utc=now_utc)
    return analyze_market_activity(
        price_rows,
        read_csv_rows(activity_path),
        as_of_date=as_of_date,
        now_utc=now_utc,
    )
