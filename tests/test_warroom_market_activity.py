from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TOOLS = PACKAGE_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from twse_market_activity_importer import (  # noqa: E402
    NetworkBackfillNotApproved,
    normalize_twse_payload,
    fetch_payload,
    write_candidate,
)
from warroom_market_activity import (  # noqa: E402
    CSV_FIELDS,
    FORMAL_CSV_FIELDS,
    LIMITED,
    READY,
    HistoricalRewriteError,
    MarketActivityValidationError,
    analyze_market_activity,
    analyze_optional_files,
    validate_activity_rows,
    validate_price_activity_join,
)


NOW = dt.datetime(2026, 7, 17, 12, 0, tzinfo=dt.timezone.utc)
AS_OF = dt.date(2026, 7, 17)
SOURCE = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"


def weekdays(count: int) -> list[dt.date]:
    values: list[dt.date] = []
    current = dt.date(2026, 6, 15)
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current += dt.timedelta(days=1)
    return values


def activity_row(day: dt.date, index: int = 0) -> dict[str, object]:
    return {
        "trade_date": day.isoformat(),
        "ticker": "2317",
        "volume_shares": 1_000_000 + index * 100_000,
        "turnover_ntd": 200_000_000 + index * 20_000_000,
        "transaction_count": 10_000 + index * 100,
        "source_url": SOURCE,
        "retrieved_at_utc": "2026-07-17T10:00:00Z",
    }


def price_row(day: dt.date, index: int = 0) -> dict[str, object]:
    return {"Date": day.isoformat(), "Close": str(200 + index)}


class MarketActivityTests(unittest.TestCase):
    def test_schema_declares_exact_csv_contract(self) -> None:
        schema = json.loads(
            (PACKAGE_ROOT / "contracts/2317_daily_market_activity.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(tuple(schema["x-csv-columns"]), FORMAL_CSV_FIELDS)
        self.assertEqual(schema["x-primary-key"], ["date", "stock_id"])
        self.assertEqual(schema["items"]["properties"]["trade_volume"]["minimum"], 0)

    def test_official_twse_payload_normalizes_units(self) -> None:
        payload = [{
            "Date": "1150717", "Code": "2317", "TradeVolume": "68,996,866",
            "TradeValue": "18,605,623,168", "Transaction": "53,509",
        }]
        row = normalize_twse_payload(
            payload, retrieved_at_utc="2026-07-17T10:00:00Z", as_of_date=AS_OF
        )[0]
        self.assertEqual(row["volume_shares"], 68_996_866)
        self.assertEqual(row["turnover_ntd"], 18_605_623_168)
        self.assertEqual(row["transaction_count"], 53_509)

    def test_completeness_rejects_missing_field(self) -> None:
        row = activity_row(dt.date(2026, 7, 17))
        row.pop("turnover_ntd")
        with self.assertRaises(MarketActivityValidationError):
            validate_activity_rows([row], as_of_date=AS_OF, now_utc=NOW)

    def test_unique_date_ticker_is_required(self) -> None:
        row = activity_row(dt.date(2026, 7, 17))
        with self.assertRaises(MarketActivityValidationError):
            validate_activity_rows([row, row], as_of_date=AS_OF, now_utc=NOW)

    def test_units_reject_decimal_or_negative_values(self) -> None:
        decimal = activity_row(dt.date(2026, 7, 17))
        decimal["volume_shares"] = "10.5"
        negative = activity_row(dt.date(2026, 7, 17))
        negative["turnover_ntd"] = "-1"
        for row in (decimal, negative):
            with self.assertRaises(MarketActivityValidationError):
                validate_activity_rows([row], as_of_date=AS_OF, now_utc=NOW)

    def test_weekend_and_future_dates_are_rejected(self) -> None:
        for day in (dt.date(2026, 7, 18), dt.date(2026, 7, 20)):
            with self.assertRaises(MarketActivityValidationError):
                validate_activity_rows([activity_row(day)], as_of_date=AS_OF, now_utc=NOW)

    def test_only_official_twse_https_source_is_accepted(self) -> None:
        row = activity_row(dt.date(2026, 7, 17))
        row["source_url"] = "https://example.com/volume"
        with self.assertRaises(MarketActivityValidationError):
            validate_activity_rows([row], as_of_date=AS_OF, now_utc=NOW)

    def test_historical_rewrite_is_rejected_but_idempotence_is_allowed(self) -> None:
        original = activity_row(dt.date(2026, 7, 17))
        self.assertEqual(
            len(validate_activity_rows([original], historical_rows=[original], as_of_date=AS_OF, now_utc=NOW)),
            1,
        )
        changed = dict(original)
        changed["volume_shares"] = int(original["volume_shares"]) + 1
        with self.assertRaises(HistoricalRewriteError):
            validate_activity_rows([changed], historical_rows=[original], as_of_date=AS_OF, now_utc=NOW)

    def test_date_ticker_join_reports_coverage(self) -> None:
        days = weekdays(3)
        result = validate_price_activity_join(
            [price_row(day, index) for index, day in enumerate(days)],
            [activity_row(days[1], 1), activity_row(days[2], 2)],
            as_of_date=AS_OF,
            now_utc=NOW,
        )
        self.assertEqual(result["matched_row_count"], 2)
        self.assertEqual(result["missing_activity_dates"], [days[0].isoformat()])

    def test_orphan_activity_date_fails_join(self) -> None:
        with self.assertRaises(MarketActivityValidationError):
            validate_price_activity_join(
                [price_row(dt.date(2026, 7, 16))],
                [activity_row(dt.date(2026, 7, 17))],
                as_of_date=AS_OF,
                now_utc=NOW,
            )

    def test_missing_activity_does_not_block_fundamental_report(self) -> None:
        result = analyze_market_activity([], None, as_of_date=AS_OF, now_utc=NOW)
        self.assertEqual(result["status"], LIMITED)
        self.assertIn("基本面報告可繼續", result["reason"])
        self.assertFalse(result["actionable"])

    def test_current_formal_market_activity_is_ready(self) -> None:
        result = analyze_optional_files(
            PACKAGE_ROOT / "data/2317_daily_price.csv",
            PACKAGE_ROOT / "data/2317_daily_market_activity.csv",
            as_of_date=AS_OF,
            now_utc=NOW,
        )
        self.assertEqual(result["status"], READY)
        self.assertFalse(result["actionable"])

    def test_less_than_twenty_prior_days_is_limited(self) -> None:
        days = weekdays(20)
        result = analyze_market_activity(
            [price_row(day, index) for index, day in enumerate(days)],
            [activity_row(day, index) for index, day in enumerate(days)],
            as_of_date=AS_OF,
            now_utc=NOW,
        )
        self.assertEqual(result["status"], LIMITED)

    def test_twenty_day_ratio_turnover_and_divergence_are_calculated(self) -> None:
        days = weekdays(25)
        prices = [price_row(day, index) for index, day in enumerate(days)]
        activities = [activity_row(day, index) for index, day in enumerate(days)]
        result = analyze_market_activity(
            prices, activities, as_of_date=AS_OF, now_utc=NOW
        )
        self.assertEqual(result["status"], READY)
        self.assertGreater(result["volume_ratio_20"], 1.0)
        self.assertEqual(result["turnover_trend"]["direction"], "RISING")
        self.assertEqual(
            result["price_volume_divergence"]["classification"], "PRICE_UP_VOLUME_UP"
        )

    def test_volume_never_attributes_investor_behavior(self) -> None:
        days = weekdays(21)
        result = analyze_market_activity(
            [price_row(day, index) for index, day in enumerate(days)],
            [activity_row(day, index) for index, day in enumerate(days)],
            as_of_date=AS_OF,
            now_utc=NOW,
        )
        self.assertEqual(result["investor_behavior_attribution"], "NOT_PERMITTED")
        self.assertIn("不能據此推論法人", result["guardrail"])

    def test_network_backfill_is_fail_closed_without_owner_gate(self) -> None:
        called = False

        def opener(*args, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("network must not be reached")

        with self.assertRaises(NetworkBackfillNotApproved):
            fetch_payload(allow_network=False, owner_approval=None, opener=opener)
        self.assertFalse(called)

    def test_importer_never_overwrites_formal_or_existing_csv(self) -> None:
        root = (
            PACKAGE_ROOT
            / "runtime"
            / "market_activity_importer_tests"
            / uuid.uuid4().hex
        )
        root.mkdir(parents=True)
        try:
            with self.assertRaises(MarketActivityValidationError):
                write_candidate(root / "2317_daily_market_activity.csv", [])
            existing = root / "candidate.csv"
            existing.write_text("existing", encoding="utf-8")
            with self.assertRaises(MarketActivityValidationError):
                write_candidate(existing, [])
        finally:
            if root.exists():
                shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
