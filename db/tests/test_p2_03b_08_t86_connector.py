from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = PACKAGE_ROOT / "db" / "tools" / "p2_03b_08_t86_connector.py"
SPEC = importlib.util.spec_from_file_location("p2_03b_08_t86_connector", TOOL_PATH)
connector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = connector
SPEC.loader.exec_module(connector)


def t86_payload(date_text: str, *, mutate=None) -> dict:
    row = [
        "2317",
        "鴻海            ",
        "20,598,050",
        "15,281,475",
        "5,316,575",
        "0",
        "0",
        "0",
        "1,712,000",
        "116,000",
        "1,596,000",
        "3,726,000",
        "5,881,000",
        "3,357,000",
        "2,524,000",
        "3,217,000",
        "2,015,000",
        "1,202,000",
        "10,638,575",
    ]
    payload = {
        "stat": "OK",
        "date": date_text,
        "title": "三大法人買賣超日報",
        "fields": list(connector.EXPECTED_FIELDS),
        "data": [row],
        "notes": ["fixture"],
        "total": 1,
    }
    if mutate is not None:
        mutate(payload)
    return payload


class FakeFetcher:
    def __init__(self, *, mutate=None, fail=False):
        self.mutate = mutate
        self.fail = fail
        self.requests = []

    def __call__(self, url: str, timeout: int):
        self.requests.append(url)
        if self.fail:
            raise connector.PrimarySourceUnavailable("fixture unavailable")
        parsed = urllib.parse.urlparse(url)
        if parsed.path == "/zh/trading/foreign/t86.html":
            body = "<html><title>三大法人買賣超日報</title></html>".encode("utf-8")
            return connector.HttpResult(url, 200, "text/html", {}, body, "FIXTURE")
        query = urllib.parse.parse_qs(parsed.query)
        date_text = query["date"][0]
        body = json.dumps(
            t86_payload(date_text, mutate=self.mutate), ensure_ascii=False
        ).encode("utf-8")
        return connector.HttpResult(url, 200, "application/json", {}, body, "FIXTURE")


class P203B08T86ConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="t86-test-", dir=PACKAGE_ROOT / "staging")
        self.root = Path(self.temp.name)
        self.runtime_db = self.root / "runtime.sqlite3"
        self.runtime_db.write_bytes(b"runtime-protected")
        self.date_value = connector.dt.date(2026, 6, 26)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_connector(self, fetcher=None):
        return connector.run_connector(
            self.root / "run",
            self.runtime_db,
            self.date_value,
            fetcher or FakeFetcher(),
        )

    def test_happy_path_writes_raw_candidate_and_observations(self) -> None:
        result = self.run_connector()
        self.assertEqual(result["status"], "PASS_WITH_WARNINGS")
        self.assertEqual(result["query"]["date"], "2026-06-26")
        self.assertEqual(len(result["observations"]), 17)
        self.assertTrue(Path(result["candidate_sqlite"]).is_file())
        self.assertTrue(Path(result["raw_artifacts"]["t86_response"]["local_path"]).is_file())
        self.assertTrue(result["formal_outputs_unchanged"])
        connection = sqlite3.connect(result["candidate_sqlite"])
        try:
            obs_count = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            evd_count = connection.execute("SELECT COUNT(*) FROM observation_evidence").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(obs_count, 17)
        self.assertEqual(evd_count, 17)

    def test_selects_by_code_not_name(self) -> None:
        def mutate(payload):
            payload["data"][0][1] = "不是鴻海"

        result = self.run_connector(FakeFetcher(mutate=mutate))
        self.assertEqual(result["candidate_facts"]["security_code"], "2317")
        self.assertEqual(result["candidate_facts"]["security_name_raw"], "不是鴻海")

    def test_field_contract_change_is_blocked(self) -> None:
        def mutate(payload):
            payload["fields"] = list(reversed(payload["fields"]))

        with self.assertRaises(connector.ContractError):
            self.run_connector(FakeFetcher(mutate=mutate))

    def test_buy_sell_net_mismatch_is_blocked(self) -> None:
        def mutate(payload):
            payload["data"][0][4] = "1"

        with self.assertRaises(connector.DataValidationError):
            self.run_connector(FakeFetcher(mutate=mutate))

    def test_total_institutional_mismatch_is_blocked(self) -> None:
        def mutate(payload):
            payload["data"][0][18] = "1"

        with self.assertRaises(connector.DataValidationError):
            self.run_connector(FakeFetcher(mutate=mutate))

    def test_no_source_fallback_on_primary_failure(self) -> None:
        with self.assertRaises(connector.PrimarySourceUnavailable):
            self.run_connector(FakeFetcher(fail=True))

    def test_units_preserve_official_shares_and_derive_lots_separately(self) -> None:
        result = self.run_connector()
        facts = result["candidate_facts"]
        self.assertEqual(facts["official_shares"]["三大法人買賣超股數"], 10638575)
        self.assertEqual(facts["derived_lots"]["三大法人買賣超股數"], "10638.575")
        self.assertEqual(result["contract"]["official_unit"], "SHARES")
        self.assertEqual(
            result["contract"]["unit_conversion"]["derived_lots_formula"],
            "lots = shares / 1000",
        )


if __name__ == "__main__":
    unittest.main()
