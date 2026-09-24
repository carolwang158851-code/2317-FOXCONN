from __future__ import annotations

import csv
import http.client
import json
import socket
import shutil
import sys
import unittest
import urllib.response
import uuid
from pathlib import Path
from unittest import mock


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TOOLS = PACKAGE_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import warroom_data_fetcher_v2 as fetcher  # noqa: E402


class _Response:
    status = 200

    def __init__(self) -> None:
        self._returned = False

    @staticmethod
    def getheader(_name: str) -> None:
        return None

    def read(self, _size: int = -1) -> bytes:
        if self._returned:
            return b""
        self._returned = True
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
    def test_actual_urllib_http_response_wrapper_socket_is_deadline_bound(self) -> None:
        body = b'{"chart":{"result":[]}}'
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                client, server = socket.socketpair()
                try:
                    server.sendall(
                        b"HTTP/1.1 200 OK\r\n"
                        + f"Content-Length: {len(body)}\r\n".encode("ascii")
                        + b"Content-Type: application/json\r\n\r\n"
                        + body
                    )
                    server.shutdown(socket.SHUT_WR)
                    http_response = http.client.HTTPResponse(client)
                    http_response.begin()
                    response = (
                        urllib.response.addinfourl(
                            http_response,
                            http_response.headers,
                            "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX",
                            http_response.status,
                        )
                        if wrapped
                        else http_response
                    )
                    budget = fetcher.FallbackBudget("vix", 5.0)

                    result = fetcher.read_response_body_with_deadline(
                        response,
                        budget=budget,
                        provider="Yahoo VIX",
                        transport="urllib",
                    )

                    self.assertEqual(result, body)
                finally:
                    client.close()
                    server.close()

    def test_urllib_slow_stream_uses_one_master_deadline_for_every_read(self) -> None:
        now = [0.0]

        class Node:
            pass

        client, server = socket.socketpair()

        class SlowResponse(http.client.HTTPResponse):
            def __init__(self) -> None:
                self.fp = Node()
                self.fp.raw = Node()
                self.fp.raw._sock = client
                self.read_timeouts: list[float] = []

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def read(self, _size: int) -> bytes:
                timeout = client.gettimeout()
                self.read_timeouts.append(timeout)
                if timeout < 3.0:
                    now[0] += timeout
                    raise TimeoutError("master deadline reached")
                now[0] += 3.0
                return b"x" * fetcher.RESPONSE_READ_CHUNK_BYTES

        response = SlowResponse()
        budget = fetcher.FallbackBudget(
            "vix",
            10.0,
            clock=lambda: now[0],
            route_deadline=10.0,
        )
        try:
            with mock.patch.object(fetcher.urllib.request, "urlopen", return_value=response):
                result = fetcher.fetch_bytes_with_urllib(
                    "https://example.com/slow",
                    budget=budget,
                    provider="slow urllib",
                )
        finally:
            client.close()
            server.close()

        self.assertIsNone(result)
        self.assertLess(now[0], 10.0)
        self.assertEqual(response.read_timeouts, [8.0, 5.0, 2.0])

    def test_unsupported_urllib_wrapper_fails_closed_before_body_read(self) -> None:
        class UnsupportedResponse:
            def __init__(self) -> None:
                self.read_calls = 0

            def read(self, _size: int) -> bytes:
                self.read_calls += 1
                return b"unsafe"

        response = UnsupportedResponse()
        budget = fetcher.FallbackBudget("vix", 8.0)

        with self.assertRaisesRegex(
            TimeoutError, "response body transport cannot be deadline-bound"
        ):
            fetcher.read_response_body_with_deadline(
                response,
                budget=budget,
                provider="Yahoo VIX",
                transport="urllib",
            )

        self.assertEqual(response.read_calls, 0)

    def test_direct_https_slow_body_uses_one_master_deadline(self) -> None:
        now = [0.0]

        class SlowSocket:
            def __init__(self) -> None:
                self.timeout = 0.0
                self.read_timeouts: list[float] = []

            def settimeout(self, timeout: float) -> None:
                self.timeout = timeout
                self.read_timeouts.append(timeout)

        class SlowResponse:
            status = 200

            def __init__(self, sock: SlowSocket) -> None:
                self.sock = sock

            @staticmethod
            def getheader(_name: str) -> None:
                return None

            def read(self, _size: int) -> bytes:
                if self.sock.timeout < 3.0:
                    now[0] += self.sock.timeout
                    raise TimeoutError("master deadline reached")
                now[0] += 3.0
                return b"x" * fetcher.RESPONSE_READ_CHUNK_BYTES

        class SlowConnection:
            instance = None

            def __init__(self, *_args, **_kwargs) -> None:
                self.sock = SlowSocket()
                SlowConnection.instance = self

            @staticmethod
            def request(*_args, **_kwargs) -> None:
                return None

            def getresponse(self) -> SlowResponse:
                return SlowResponse(self.sock)

            @staticmethod
            def close() -> None:
                return None

        budget = fetcher.FallbackBudget(
            "wti",
            10.0,
            clock=lambda: now[0],
            route_deadline=10.0,
        )
        with mock.patch.object(fetcher.http.client, "HTTPSConnection", SlowConnection):
            result = fetcher.fetch_bytes_with_http_client(
                "https://example.com/slow",
                budget=budget,
                provider="slow direct https",
            )

        self.assertIsNone(result)
        self.assertLess(now[0], 10.0)
        self.assertEqual(SlowConnection.instance.sock.read_timeouts, [8.0, 5.0, 2.0])

    def test_transport_overrun_stays_inside_master_route_deadline(self) -> None:
        now = [0.0]

        class OverrunningConnection:
            def __init__(self, *_args, timeout: float, **_kwargs) -> None:
                self.timeout = timeout

            def request(self, *_args, **_kwargs) -> None:
                now[0] += self.timeout + 0.5
                raise TimeoutError("simulated scheduler and return overhead")

            @staticmethod
            def close() -> None:
                return None

        budget = fetcher.FallbackBudget(
            "fed_rate",
            60.0,
            clock=lambda: now[0],
            route_deadline=60.0,
        )
        with (
            mock.patch.object(fetcher, "HTTP_CLIENT_TIMEOUT_SECONDS", 60),
            mock.patch.object(fetcher.http.client, "HTTPSConnection", OverrunningConnection),
        ):
            result = fetcher.fetch_bytes_with_http_client(
                "https://example.com/slow",
                budget=budget,
                provider="deadline overrun simulation",
            )

        self.assertIsNone(result)
        self.assertEqual(now[0], 58.5)
        self.assertLess(now[0], 60.0)
        self.assertTrue(budget.blocking_exhausted())

    def test_master_route_deadline_prevents_stooq_after_fred_and_yahoo_expire(self) -> None:
        now = [0.0]
        calls: list[str] = []

        def fred(_budget: fetcher.FallbackBudget):
            calls.append("fred")
            now[0] += 52.0
            return None

        def yahoo(budget: fetcher.FallbackBudget):
            calls.append("yahoo")
            self.assertEqual(budget.route_remaining(), 8.0)
            now[0] += 8.0
            return None

        def stooq(_budget: fetcher.FallbackBudget):
            calls.append("stooq")
            return fetcher.source_result(14.5, "STOOQ_VIX_PUBLIC_MARKET")

        result = fetcher.first_available_source_with_yahoo_reserve(
            "vix",
            [
                ("FRED VIXCLS", "VIXCLS", fetcher.BUDGET_CLASS_NON_YAHOO, fred),
                ("Yahoo VIX", "^VIX", fetcher.BUDGET_CLASS_YAHOO_RESERVED, yahoo),
                ("Stooq VIX", "^vix", fetcher.BUDGET_CLASS_NON_YAHOO, stooq),
            ],
            clock=lambda: now[0],
        )

        self.assertIsNone(result)
        self.assertEqual(now[0], 60.0)
        self.assertEqual(calls, ["fred", "yahoo"])

    def test_powershell_timeout_cleanup_is_bounded_by_route_deadline(self) -> None:
        now = [0.0]

        class TimedOutProcess:
            def __init__(self) -> None:
                self.returncode = None
                self.alive = True
                self.killed = False
                self.communicate_timeouts: list[float] = []

            def communicate(self, timeout: float):
                self.communicate_timeouts.append(timeout)
                if len(self.communicate_timeouts) == 1:
                    now[0] += timeout
                    raise fetcher.subprocess.TimeoutExpired("powershell", timeout)
                now[0] += min(timeout, 0.25)
                self.alive = False
                self.returncode = -9
                return "", ""

            def kill(self) -> None:
                self.killed = True

        process = TimedOutProcess()
        budget = fetcher.FallbackBudget(
            "dxy",
            8.0,
            clock=lambda: now[0],
            route_deadline=8.0,
        )
        with mock.patch.object(fetcher.subprocess, "Popen", return_value=process):
            result = fetcher.fetch_bytes_with_powershell(
                "https://example.com/slow",
                budget=budget,
                provider="slow powershell",
            )

        self.assertIsNone(result)
        self.assertTrue(process.killed)
        self.assertFalse(process.alive)
        self.assertEqual(process.communicate_timeouts, [5.0, 1.0])
        self.assertLess(now[0], 8.0)

    def test_owner_approved_macro_routing_order_and_success_short_circuit(self) -> None:
        cases = [
            ("vix", fetcher.fetch_macro_vix, ["FRED:VIXCLS", "YAHOO:^VIX"]),
            ("wti", fetcher.fetch_macro_wti, ["FRED:DCOILWTICO", "YAHOO:CL=F"]),
            ("twd_usd", fetcher.fetch_macro_twd_usd, ["FRED:DEXTAUS", "YAHOO:TWD=X"]),
            ("us10y", fetcher.fetch_macro_us10y, ["FRED:DGS10", "YAHOO:^TNX"]),
            ("dxy", fetcher.fetch_macro_dxy, ["YAHOO:DX-Y.NYB"]),
        ]
        for metric, runner, expected_calls in cases:
            calls: list[str] = []

            def fred(series_id: str, **_kwargs):
                calls.append(f"FRED:{series_id}")
                return None

            def yahoo(ticker: str, **kwargs):
                calls.append(f"YAHOO:{ticker}")
                self.assertTrue(kwargs["urllib_only"])
                return fetcher.source_result(
                    1.0,
                    f"YAHOO_TEST_{metric.upper()}",
                    support_level="PUBLIC_MARKET_DATA",
                )

            def stooq(symbols: list[str], **_kwargs):
                calls.append(f"STOOQ:{'/'.join(symbols)}")
                return None

            with (
                self.subTest(metric=metric),
                mock.patch.object(fetcher, "fetch_fred_public_series_value", side_effect=fred),
                mock.patch.object(fetcher, "fetch_yahoo_chart_value", side_effect=yahoo),
                mock.patch.object(fetcher, "fetch_stooq_quote_value", side_effect=stooq),
            ):
                result = runner()
            self.assertIsNotNone(result)
            self.assertEqual(calls, expected_calls)

    def test_yahoo_failure_resumes_remaining_non_yahoo_budget(self) -> None:
        now = [0.0]
        calls: list[tuple[str, float, str]] = []

        def fred(budget: fetcher.FallbackBudget):
            calls.append(("fred", budget.total_seconds, budget.budget_class))
            now[0] += 40.0
            return None

        def yahoo(budget: fetcher.FallbackBudget):
            calls.append(("yahoo", budget.total_seconds, budget.budget_class))
            now[0] += 8.0
            return None

        def stooq(budget: fetcher.FallbackBudget):
            calls.append(("stooq", budget.total_seconds, budget.budget_class))
            return fetcher.source_result(14.5, "STOOQ_VIX_PUBLIC_MARKET")

        result = fetcher.first_available_source_with_yahoo_reserve(
            "vix",
            [
                ("FRED VIXCLS", "VIXCLS", fetcher.BUDGET_CLASS_NON_YAHOO, fred),
                ("Yahoo VIX", "^VIX", fetcher.BUDGET_CLASS_YAHOO_RESERVED, yahoo),
                ("Stooq VIX", "^vix/vix", fetcher.BUDGET_CLASS_NON_YAHOO, stooq),
            ],
            clock=lambda: now[0],
        )

        self.assertEqual(result["source"], "STOOQ_VIX_PUBLIC_MARKET")
        self.assertEqual(
            calls,
            [
                ("fred", 52.0, "NON_YAHOO"),
                ("yahoo", 8.0, "YAHOO_RESERVED"),
                ("stooq", 12.0, "NON_YAHOO"),
            ],
        )

    def test_reserved_yahoo_path_is_exactly_one_urllib_attempt(self) -> None:
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {"exchangeTimezoneName": "UTC"},
                        "timestamp": [1787788800],
                        "indicators": {"quote": [{"close": [5.125]}]},
                    }
                ]
            }
        }
        budget = fetcher.FallbackBudget(
            "us10y",
            fetcher.YAHOO_RESERVED_BUDGET_SECONDS,
            budget_class=fetcher.BUDGET_CLASS_YAHOO_RESERVED,
        )
        with (
            mock.patch.object(
                fetcher,
                "_fetch_bytes_urllib_only",
                return_value=json.dumps(payload).encode("utf-8"),
            ) as urllib_transport,
            mock.patch.object(fetcher, "fetch_bytes_with_http_client") as direct_https,
            mock.patch.object(fetcher, "fetch_bytes_with_powershell") as powershell,
        ):
            result = fetcher.fetch_yahoo_chart_value(
                "^TNX",
                source_name="YAHOO_FINANCE_US10Y",
                fallback_budget=budget,
                provider_name="Yahoo TNX",
                urllib_only=True,
            )

        self.assertEqual(result["source"], "YAHOO_FINANCE_US10Y")
        self.assertEqual(result["value"], 5.125)
        urllib_transport.assert_called_once()
        direct_https.assert_not_called()
        powershell.assert_not_called()
        self.assertEqual(fetcher.REQUEST_RETRIES, 1)
        self.assertEqual(budget.total_seconds, 8.0)

    def test_routing_metadata_and_semantic_mappings_are_unchanged(self) -> None:
        self.assertEqual(
            fetcher.MACRO_SOURCE_CANDIDATES["vix"],
            ["FRED VIXCLS", "Yahoo ^VIX fallback", "Stooq VIX"],
        )
        self.assertEqual(
            fetcher.MACRO_SOURCE_CANDIDATES["wti"],
            ["FRED DCOILWTICO", "Yahoo CL=F fallback", "Stooq CL.F"],
        )
        self.assertEqual(
            fetcher.MACRO_SOURCE_CANDIDATES["twd_usd"],
            ["FRED DEXTAUS", "Yahoo TWD=X fallback", "Stooq USDTWD"],
        )
        self.assertEqual(
            fetcher.MACRO_SOURCE_CANDIDATES["us10y"],
            ["FRED DGS10", "Yahoo ^TNX fallback"],
        )
        self.assertEqual(
            fetcher.MACRO_SOURCE_CANDIDATES["dxy"],
            ["Yahoo DX-Y.NYB fallback", "Stooq DXY"],
        )
        source = (TOOLS / "warroom_data_fetcher_v2.py").read_text(encoding="utf-8")
        self.assertIn('"CL=F",\n                source_name="YAHOO_FINANCE_WTI"', source)
        self.assertIn('"^TNX",\n                source_name="YAHOO_FINANCE_US10Y"', source)
        self.assertEqual(fetcher.NON_YAHOO_BUDGET_SECONDS, 52.0)
        self.assertEqual(fetcher.YAHOO_RESERVED_BUDGET_SECONDS, 8.0)

    def test_fed_rate_path_remains_fred_midpoint_without_yahoo(self) -> None:
        with mock.patch.object(
            fetcher,
            "fetch_fred_series_latest",
            side_effect=[(4.0, "2026-09-24"), (3.5, "2026-09-24")],
        ) as fred:
            result = fetcher.fetch_fred_target_rate_midpoint()
        self.assertEqual(result["value"], 3.75)
        self.assertEqual(result["source"], "FRED_FOMC_TARGET_RANGE_MIDPOINT")
        self.assertEqual([call.args[0] for call in fred.call_args_list], ["DFEDTARU", "DFEDTARL"])

    def test_fed_rate_final_attempt_preserves_hard_deadline_cleanup_reserve(self) -> None:
        now = [0.0]
        budget = fetcher.FallbackBudget(
            "fed_rate",
            60.0,
            clock=lambda: now[0],
            route_deadline=60.0,
        )
        requested_blocking_intervals: list[float] = []

        def fred(series_id: str, *, fallback_budget, **_kwargs):
            self.assertIs(fallback_budget, budget)
            if series_id == "DFEDTARU":
                now[0] += 45.0
                return 4.0, "2026-09-24"
            requested = fallback_budget.usable_blocking_remaining()
            requested_blocking_intervals.append(requested)
            now[0] += requested + 0.5
            return None

        with (
            mock.patch.object(fetcher, "FallbackBudget", return_value=budget),
            mock.patch.object(fetcher, "fetch_fred_series_latest", side_effect=fred),
        ):
            result = fetcher.fetch_fred_target_rate_midpoint()

        carry = fetcher.choose_value(
            result,
            None,
            carry_value="3.75",
            carry_source="CONNECTOR_SOURCE_UNAVAILABLE_CARRY_FORWARD",
            carry_note_zh="connector unavailable; observation only",
        )
        self.assertIsNone(result)
        self.assertEqual(requested_blocking_intervals, [13.0])
        self.assertEqual(now[0], 58.5)
        self.assertLess(now[0], 60.0)
        self.assertEqual(
            carry["source"], "CONNECTOR_SOURCE_UNAVAILABLE_CARRY_FORWARD"
        )

    def test_metric_fallback_chain_stops_at_explicit_budget(self) -> None:
        now = [0.0]
        calls: list[str] = []

        def timed_out(label: str, elapsed: float):
            def run(_budget: fetcher.FallbackBudget):
                calls.append(label)
                now[0] += elapsed
                return None

            return run

        result = fetcher.first_available_source(
            "vix",
            [
                ("FRED VIXCLS", timed_out("fred", 40.0)),
                ("Stooq VIX", timed_out("stooq", 25.0)),
                ("Yahoo VIX", timed_out("yahoo", 1.0)),
            ],
            fallback_budget_seconds=60.0,
            clock=lambda: now[0],
        )
        self.assertIsNone(result)
        self.assertEqual(calls, ["fred", "stooq"])

    def test_yahoo_fallback_success_preserves_source_priority(self) -> None:
        calls: list[str] = []

        def unavailable(label: str):
            def run(_budget: fetcher.FallbackBudget):
                calls.append(label)
                return None

            return run

        def yahoo(_budget: fetcher.FallbackBudget):
            calls.append("yahoo")
            return fetcher.source_result(
                14.75,
                "YAHOO_FINANCE_VIX",
                support_level="PUBLIC_MARKET_DATA",
            )

        result = fetcher.first_available_source(
            "vix",
            [
                ("FRED VIXCLS", unavailable("fred")),
                ("Stooq VIX", unavailable("stooq")),
                ("Yahoo VIX", yahoo),
            ],
            fallback_budget_seconds=60.0,
        )
        self.assertEqual(calls, ["fred", "stooq", "yahoo"])
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "YAHOO_FINANCE_VIX")
        self.assertEqual(result["supportLevel"], "PUBLIC_MARKET_DATA")

    def test_exhausted_fallback_keeps_governed_carry_forward_semantics(self) -> None:
        result = fetcher.choose_value(
            None,
            None,
            carry_value="31.732",
            carry_source="CONNECTOR_SOURCE_UNAVAILABLE_CARRY_FORWARD",
            carry_note_zh="connector unavailable; observation only",
        )
        self.assertEqual(result["value"], 31.732)
        self.assertEqual(
            result["source"], "CONNECTOR_SOURCE_UNAVAILABLE_CARRY_FORWARD"
        )
        self.assertEqual(result["supportLevel"], "CARRY_FORWARD")

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
        self.assertEqual(result["close"], 47021.0)
        self.assertEqual(result["sourceDate"], "2026-09-21")
        self.assertEqual(result["change5dPct"], round((47021 / 47014 - 1) * 100, 4))
        self.assertEqual(result["sourceName"], "TWSE")
        self.assertEqual(result["sourceTier"], "OFFICIAL_EXCHANGE")
        self.assertEqual(result["status"], "OBSERVATION_ONLY")
        self.assertFalse(result["actionable"])
        self.assertIn("MI_5MINS_HIST", result["sourceUrl"])

    def test_generated_runtime_snapshot_contains_fail_closed_taiex(self) -> None:
        package_root = (
            PACKAGE_ROOT
            / "runtime"
            / "taiex_runtime_wiring_test_scratch"
            / uuid.uuid4().hex
        )
        try:
            shutil.copytree(PACKAGE_ROOT / "data", package_root / "data")
            contract = Path(
                "contracts/p1008_quarterly_authority/v1.0/"
                "P1008_QUARTERLY_FIELD_AVAILABILITY_CONTRACT_V1.json"
            )
            (package_root / contract).parent.mkdir(parents=True)
            shutil.copy2(PACKAGE_ROOT / contract, package_root / contract)
            with mock.patch.object(
                sys,
                "argv",
                [
                    "warroom_data_fetcher_v2.py",
                    "--package-root",
                    str(package_root),
                    "--date",
                    "2026-09-22",
                    "--no-fetch",
                ],
            ):
                self.assertEqual(fetcher.main(), 0)

            runtime_snapshot = json.loads(
                (package_root / "runtime/warroom_realtime_snapshot.json").read_text(
                    encoding="utf-8"
                )
            )
            dry_run = json.loads(
                (package_root / "staging/2026-09-22/DRY_RUN.json").read_text(
                    encoding="utf-8"
                )
            )
        finally:
            shutil.rmtree(package_root, ignore_errors=True)
        self.assertIn("taiex", runtime_snapshot)
        self.assertEqual(runtime_snapshot["taiex"], dry_run["taiex"])
        self.assertIsNone(runtime_snapshot["taiex"]["close"])
        self.assertIsNone(runtime_snapshot["taiex"]["change5dPct"])
        self.assertEqual(runtime_snapshot["taiex"]["status"], "SOURCE_UNAVAILABLE")
        self.assertEqual(runtime_snapshot["taiex"]["sourceTier"], "OFFICIAL_EXCHANGE")
        self.assertFalse(runtime_snapshot["taiex"]["actionable"])

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
