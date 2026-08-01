from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = PACKAGE_ROOT / "db" / "tools" / "p2_03b_01_twse_connector.py"
SPEC = importlib.util.spec_from_file_location("p2_03b_01_twse_connector", TOOL_PATH)
connector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = connector
SPEC.loader.exec_module(connector)


FIELDS = [
    "Date", "Code", "Name", "TradeVolume", "TradeValue", "OpeningPrice",
    "HighestPrice", "LowestPrice", "ClosingPrice", "Change", "Transaction"
]


def swagger_bytes() -> bytes:
    return json.dumps(
        {
            "paths": {
                connector.ENDPOINT_PATH: {
                    "get": {
                        "summary": "上市個股日成交資訊",
                        "responses": {
                            "200": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        field: {"type": "string", "description": field}
                                        for field in FIELDS
                                    },
                                }
                            }
                        },
                    }
                }
            }
        }
    ).encode()


def row(code: str = "2317", closing: str = "268.50") -> dict:
    values = {
        "Date": "1150618",
        "Code": code,
        "Name": "鴻海",
        "TradeVolume": "68996866",
        "TradeValue": "18605623168",
        "OpeningPrice": "270.50",
        "HighestPrice": "271.50",
        "LowestPrice": "268.50",
        "ClosingPrice": closing,
        "Change": "-3.5000",
        "Transaction": "53509",
    }
    return {field: values[field] for field in FIELDS}


class FakeFetcher:
    def __init__(self, payload=None, fail_endpoint: bool = False):
        self.payload = payload if payload is not None else [row()]
        self.fail_endpoint = fail_endpoint
        self.calls = []

    def __call__(self, url: str, timeout: int):
        self.calls.append(url)
        if url == connector.SWAGGER_URL:
            return connector.HttpResult(url, 200, "application/json", {}, swagger_bytes())
        if self.fail_endpoint:
            raise connector.PrimarySourceUnavailable("fixture unavailable")
        return connector.HttpResult(
            url,
            200,
            "application/json",
            {},
            json.dumps(self.payload, ensure_ascii=False).encode(),
        )


class P203B01TwseConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        staging = PACKAGE_ROOT / "staging"
        self.temp = tempfile.TemporaryDirectory(prefix="twse-connector-test-", dir=staging)
        self.root = Path(self.temp.name)
        self.runtime_db = self.root / "runtime.sqlite3"
        self.runtime_db.write_bytes(b"runtime-protected")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_connector(self, fetcher: FakeFetcher):
        return connector.run_connector(self.root / "run", self.runtime_db, fetcher)

    def test_happy_path_builds_a1_l1_candidate(self) -> None:
        result = self.run_connector(FakeFetcher())
        candidate = result["candidate"]
        self.assertEqual(candidate["subject"]["canonical_key"], "LISTING:TWSE:2317")
        self.assertEqual(candidate["subject"]["currency"], "TWD")
        self.assertEqual(candidate["source_authority"], "A1")
        self.assertEqual(candidate["evidence_level"], "L1")
        self.assertEqual(candidate["value_decimal"], "268.5")
        self.assertEqual(candidate["period_end"], "2026-06-18")
        self.assertEqual(candidate["model_usage"], "OBSERVATION_ONLY")

    def test_raw_bytes_are_preserved(self) -> None:
        fetcher = FakeFetcher()
        result = self.run_connector(fetcher)
        raw = Path(result["raw_artifacts"]["endpoint"]["local_path"]).read_bytes()
        self.assertEqual(
            connector.sha256_bytes(raw),
            result["raw_artifacts"]["endpoint"]["sha256"],
        )

    def test_name_is_not_used_for_identity(self) -> None:
        changed = row()
        changed["Name"] = "任意名稱"
        result = self.run_connector(FakeFetcher([changed]))
        self.assertEqual(result["candidate"]["subject"]["ticker"], "2317")

    def test_missing_2317_is_blocked(self) -> None:
        with self.assertRaises(connector.DataValidationError):
            self.run_connector(FakeFetcher([row("2330")]))

    def test_duplicate_2317_is_blocked(self) -> None:
        with self.assertRaises(connector.DataValidationError):
            self.run_connector(FakeFetcher([row(), row()]))

    def test_invalid_decimal_is_blocked(self) -> None:
        with self.assertRaises(connector.DataValidationError):
            self.run_connector(FakeFetcher([row(closing="--")]))

    def test_non_array_response_is_blocked(self) -> None:
        with self.assertRaises(connector.ContractError):
            self.run_connector(FakeFetcher(row()))

    def test_primary_failure_has_no_fallback(self) -> None:
        with self.assertRaises(connector.PrimarySourceUnavailable):
            self.run_connector(FakeFetcher(fail_endpoint=True))

    def test_runtime_file_is_unchanged(self) -> None:
        before = connector.dbcore.sha256_file(self.runtime_db)
        result = self.run_connector(FakeFetcher())
        self.assertEqual(before, connector.dbcore.sha256_file(self.runtime_db))
        self.assertTrue(result["protected_files"]["unchanged"])

    def test_warning_contract_is_explicit(self) -> None:
        result = self.run_connector(FakeFetcher())
        warnings = result["candidate"]["warnings"]
        self.assertIn("SWAGGER_RESPONSE_SHAPE_MISMATCH", warnings)
        self.assertIn("PUBLICATION_TIME_MISSING", warnings)
        self.assertIn("SESSION_CALENDAR_NOT_INTEGRATED", warnings)
        self.assertEqual(result["status"], "PASS_WITH_WARNINGS")


if __name__ == "__main__":
    unittest.main()

