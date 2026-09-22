from __future__ import annotations

import csv
import sys
import unittest
from pathlib import Path
from unittest import mock


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TOOLS = PACKAGE_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import warroom_data_fetcher_v2 as fetcher  # noqa: E402


class _Response:
    status = 200

    @staticmethod
    def getheader(_name: str) -> None:
        return None

    @staticmethod
    def read() -> bytes:
        return b"payload"


class _Connection:
    def __init__(self, *args, **kwargs) -> None:
        self.request_args = None

    def request(self, *args, **kwargs) -> None:
        self.request_args = (args, kwargs)

    @staticmethod
    def getresponse() -> _Response:
        return _Response()

    @staticmethod
    def close() -> None:
        return None


class _CrossHostRedirectResponse(_Response):
    status = 302

    @staticmethod
    def getheader(name: str) -> str | None:
        return "https://unapproved.example/data" if name == "Location" else None


class _CrossHostRedirectConnection(_Connection):
    @staticmethod
    def getresponse() -> _CrossHostRedirectResponse:
        return _CrossHostRedirectResponse()


class DataFreshnessRemediationTests(unittest.TestCase):
    def test_daily_price_wrapper_creates_log_directory_before_redirect(self) -> None:
        wrapper = (TOOLS / "p1008_update_daily_price.cmd").read_text(encoding="utf-8")
        mkdir_at = wrapper.index('if not exist "%LOG_DIR%" mkdir')
        updater_at = wrapper.index('"%PYTHON_EXE%" "%UPDATER%"')
        self.assertLess(mkdir_at, updater_at)

    def test_direct_https_transport_accepts_only_verified_https(self) -> None:
        with mock.patch.object(fetcher.http.client, "HTTPSConnection", _Connection):
            self.assertEqual(
                fetcher.fetch_bytes_with_http_client("https://example.com/data?q=1"),
                b"payload",
            )
        self.assertIsNone(fetcher.fetch_bytes_with_http_client("http://example.com/data"))

    def test_direct_https_transport_rejects_cross_host_redirect(self) -> None:
        with mock.patch.object(
            fetcher.http.client, "HTTPSConnection", _CrossHostRedirectConnection
        ):
            self.assertIsNone(fetcher.fetch_bytes_with_http_client("https://example.com/data"))

    def test_fetch_bytes_uses_direct_https_before_powershell(self) -> None:
        with (
            mock.patch.object(fetcher, "_fetch_bytes_urllib_only", return_value=None),
            mock.patch.object(fetcher, "fetch_bytes_with_http_client", return_value=b"direct") as direct,
            mock.patch.object(fetcher, "fetch_bytes_with_powershell") as powershell,
        ):
            self.assertEqual(fetcher.fetch_bytes("https://example.com/data", {"q": "1"}), b"direct")
        direct.assert_called_once_with("https://example.com/data?q=1")
        powershell.assert_not_called()

    def test_yahoo_value_keeps_latest_non_null_value_and_source_date(self) -> None:
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {"exchangeTimezoneName": "UTC"},
                        "timestamp": [1787702400, 1787788800],
                        "indicators": {"quote": [{"close": [31.5, 31.723]}]},
                    }
                ]
            }
        }
        with mock.patch.object(fetcher, "fetch_json", return_value=payload):
            result = fetcher.fetch_yahoo_chart_value(
                "TWD=X", source_name="YAHOO_FINANCE_TWD_USD"
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["value"], 31.723)
        self.assertEqual(result["sourceDate"], "2026-08-27")
        self.assertEqual(result["supportLevel"], "PUBLIC_MARKET_DATA")

    def test_twse_daily_close_keeps_verified_candidate_date(self) -> None:
        payload = {
            "stat": "OK",
            "data": [["115/08/27", "1", "2", "3", "4", "5", "252.00"]],
        }
        with mock.patch.object(fetcher, "fetch_json", return_value=payload):
            result = fetcher.fetch_twse_stock_day_close("2026-08-27")
        self.assertIsNotNone(result)
        self.assertEqual(result["sourceDate"], "2026-08-27")
        self.assertEqual(result["effectiveDate"], "2026-08-27")
        self.assertEqual(result["supportLevel"], "OFFICIAL_TWSE_A1")

    def test_twse_taiex_parser_returns_latest_closing_index(self) -> None:
        payload = {
            "stat": "OK",
            "fields": ["日期", "開盤指數", "最高指數", "最低指數", "收盤指數"],
            "data": [
                ["115/09/18", "47,000", "47,200", "46,900", "47,150.25"],
                ["115/09/21", "47,200", "47,400", "47,100", "47,333.50"],
            ],
        }
        observations = fetcher.parse_twse_taiex_history(payload)
        self.assertEqual(observations[-1], {"date": "2026-09-21", "close": 47333.5})

    def test_taiex_change_uses_five_trading_observations_not_calendar_days(self) -> None:
        observations = [
            {"date": "2026-09-11", "close": 100.0},
            {"date": "2026-09-14", "close": 101.0},
            {"date": "2026-09-15", "close": 102.0},
            {"date": "2026-09-16", "close": 103.0},
            {"date": "2026-09-17", "close": 104.0},
            {"date": "2026-09-18", "close": 110.0},
        ]
        self.assertEqual(fetcher.calculate_taiex_5d_change(observations), 10.0)

    def test_taiex_cross_month_fetch_supplies_five_prior_sessions(self) -> None:
        current = {"stat": "OK", "data": [["115/09/01", "0", "0", "0", "25,000"]]}
        prior = {
            "stat": "OK",
            "data": [
                ["115/08/25", "0", "0", "0", "24,000"],
                ["115/08/26", "0", "0", "0", "24,100"],
                ["115/08/27", "0", "0", "0", "24,200"],
                ["115/08/28", "0", "0", "0", "24,300"],
                ["115/08/31", "0", "0", "0", "24,400"],
            ],
        }
        with mock.patch.object(fetcher, "fetch_json", side_effect=[current, prior]) as mocked:
            result = fetcher.fetch_twse_taiex_observation("2026-09-01")
        self.assertEqual(result["close"], 25000.0)
        self.assertEqual(result["change5dPct"], round((25000 / 24000 - 1) * 100, 4))
        self.assertEqual(mocked.call_args_list[1].args[1]["date"], "20260801")

    def test_taiex_insufficient_or_unavailable_is_null_never_zero(self) -> None:
        self.assertIsNone(
            fetcher.calculate_taiex_5d_change(
                [{"date": "2026-09-21", "close": 47333.5}]
            )
        )
        with mock.patch.object(fetcher, "fetch_json", return_value=None):
            result = fetcher.fetch_twse_taiex_observation("2026-09-21")
        self.assertIsNone(result["close"])
        self.assertIsNone(result["change5dPct"])
        self.assertEqual(result["status"], "SOURCE_UNAVAILABLE")

    def test_taiex_runtime_observation_includes_official_provenance(self) -> None:
        payload = {
            "stat": "OK",
            "data": [
                [f"115/09/{day:02d}", "0", "0", "0", str(47000 + day)]
                for day in (14, 15, 16, 17, 18, 21)
            ],
        }
        with mock.patch.object(fetcher, "fetch_json", return_value=payload):
            result = fetcher.fetch_twse_taiex_observation("2026-09-21")
        self.assertEqual(result["sourceName"], "TWSE")
        self.assertEqual(result["sourceTier"], "OFFICIAL_EXCHANGE")
        self.assertEqual(result["status"], "OBSERVATION_ONLY")
        self.assertFalse(result["actionable"])
        self.assertIn("MI_5MINS_HIST", result["sourceUrl"])

    def test_fetcher_keeps_macro_fx_source_ownership(self) -> None:
        source = (TOOLS / "warroom_data_fetcher_v2.py").read_text(encoding="utf-8")
        self.assertIn('"twd_usd": fetch_macro_twd_usd()', source)
        self.assertIn('"vix": fetch_macro_vix()', source)
        self.assertNotIn("VIX = fx", source)
        self.assertNotIn("TWD_USD = macro", source)

    def test_freshness_matrix_uses_cadence_aware_statuses(self) -> None:
        path = (
            PACKAGE_ROOT
            / "engineering/audit/p1008_data_freshness_remediation_v1/FRESHNESS_MATRIX.csv"
        )
        with path.open(encoding="utf-8", newline="") as handle:
            rows = {row["DATASET"]: row for row in csv.DictReader(handle)}
        self.assertEqual(rows["daily_price"]["SOURCE_LAST_AVAILABLE"], "2026-08-27")
        self.assertEqual(rows["quarterly_financials"]["FRESHNESS_STATUS"], "EXPECTED_CURRENT")
        self.assertEqual(rows["macro_events"]["FRESHNESS_STATUS"], "OBSERVATION_ONLY")
        self.assertEqual(rows["AI_industry_evidence"]["FRESHNESS_STATUS"], "OWNER_REVIEW_ONLY")

    def test_root_cause_keeps_reports_downstream(self) -> None:
        path = (
            PACKAGE_ROOT
            / "engineering/audit/p1008_data_freshness_remediation_v1/FRESHNESS_ROOT_CAUSE_REPORT.md"
        )
        report = path.read_text(encoding="utf-8")
        expected = (
            "The principal score collision was caused by overlapping UI-derived scoring and "
            "legacy fallback/hardcoded values. Report generation is downstream and was not the "
            "source of War Room KPI truth."
        )
        self.assertIn(expected, report)

    def test_validation_summary_records_no_formal_mutation(self) -> None:
        path = (
            PACKAGE_ROOT
            / "engineering/audit/p1008_data_freshness_remediation_v1/FRESHNESS_VALIDATION_SUMMARY.md"
        )
        summary = path.read_text(encoding="utf-8")
        self.assertIn("formalCsvModified=false", summary)
        self.assertIn("introduced_regression: `0`", summary)


if __name__ == "__main__":
    unittest.main()
