from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = PACKAGE_ROOT / "db" / "tools" / "p2_03b_05_monthly_revenue_connector.py"
SPEC = importlib.util.spec_from_file_location(
    "p2_03b_05_monthly_revenue_connector", TOOL_PATH
)
connector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = connector
SPEC.loader.exec_module(connector)


FIELDS = [
    "出表日期", "資料年月", "公司代號", "公司名稱", "產業別",
    "營業收入-當月營收", "營業收入-上月營收", "營業收入-去年當月營收",
    "營業收入-上月比較增減(%)", "營業收入-去年同月增減(%)",
    "累計營業收入-當月累計營收", "累計營業收入-去年累計營收",
    "累計營業收入-前期比較增減(%)", "備註",
]


def swagger_bytes() -> bytes:
    return json.dumps(
        {
            "paths": {
                connector.ENDPOINT_PATH: {
                    "get": {
                        "summary": "上市公司每月營業收入彙總表",
                        "responses": {
                            "200": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        field: {
                                            "type": "string",
                                            "description": field,
                                        }
                                        for field in FIELDS
                                    },
                                }
                            }
                        },
                    }
                }
            }
        },
        ensure_ascii=False,
    ).encode()


def row(
    code: str = "2317",
    year_month: str = "11505",
    yoy: str = "39.572294783301125",
) -> dict:
    values = {
        "出表日期": "1150617",
        "資料年月": year_month,
        "公司代號": code,
        "公司名稱": "鴻海",
        "產業別": "其他電子業",
        "營業收入-當月營收": "859409333",
        "營業收入-上月營收": "832097956",
        "營業收入-去年當月營收": "615744933",
        "營業收入-上月比較增減(%)": "3.2822309925251156",
        "營業收入-去年同月增減(%)": yoy,
        "累計營業收入-當月累計營收": "3821097773",
        "累計營業收入-去年累計營收": "2899283743",
        "累計營業收入-前期比較增減(%)": "31.79454347045604",
        "備註": "-",
    }
    return {field: values[field] for field in FIELDS}


class FakeFetcher:
    def __init__(self, payload=None, fail_endpoint: bool = False):
        self.payload = payload if payload is not None else [row()]
        self.fail_endpoint = fail_endpoint

    def __call__(self, url: str, timeout: int):
        if url == connector.SWAGGER_URL:
            return connector.HttpResult(
                url, 200, "application/json", {}, swagger_bytes(), "FIXTURE"
            )
        if self.fail_endpoint:
            raise connector.PrimarySourceUnavailable("fixture unavailable")
        return connector.HttpResult(
            url,
            200,
            "application/json",
            {},
            json.dumps(self.payload, ensure_ascii=False).encode(),
            "FIXTURE",
        )


class P203B05MonthlyRevenueConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(
            prefix="monthly-revenue-test-", dir=PACKAGE_ROOT / "staging"
        )
        self.root = Path(self.temp.name)
        self.runtime_db = self.root / "runtime.sqlite3"
        self.runtime_db.write_bytes(b"runtime-protected")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_connector(self, fetcher: FakeFetcher, report_yoy: str = "39.57"):
        with patch.object(
            connector, "read_report_yoy", return_value=Decimal(report_yoy)
        ):
            return connector.run_connector(
                self.root / "run", self.runtime_db, fetcher
            )

    def test_happy_path_creates_three_percentage_observations(self) -> None:
        result = self.run_connector(FakeFetcher())
        candidate = result["candidate"]
        self.assertEqual(candidate["period"]["data_year_month"], "2026-05")
        self.assertEqual(candidate["observation_count"], 3)
        self.assertEqual(candidate["blocked_fact_count"], 5)
        self.assertEqual(
            candidate["report_yoy_comparison"]["status"],
            "SOURCE_MATCH_CONFIRMED",
        )

    def test_money_facts_are_blocked(self) -> None:
        result = self.run_connector(FakeFetcher())
        money = [
            fact for fact in result["candidate"]["facts"]
            if fact["unit_code"] is None
        ]
        self.assertEqual(len(money), 5)
        self.assertTrue(
            all(
                fact["promotion_status"] == "BLOCKED_UNIT_UNVERIFIED"
                for fact in money
            )
        )

    def test_percentage_formulas_are_recomputed(self) -> None:
        result = self.run_connector(FakeFetcher())
        checks = result["candidate"]["formula_checks"]
        self.assertEqual(len(checks), 3)
        self.assertTrue(all(check["status"] == "PASS" for check in checks))

    def test_bad_declared_percentage_is_blocked(self) -> None:
        with self.assertRaises(connector.DataValidationError):
            self.run_connector(FakeFetcher([row(yoy="40.00")]))

    def test_report_difference_over_tolerance_is_conflict(self) -> None:
        result = self.run_connector(FakeFetcher(), report_yoy="39.50")
        self.assertEqual(
            result["candidate"]["report_yoy_comparison"]["status"],
            "DATA_CONFLICT_PENDING",
        )

    def test_raw_bytes_are_preserved(self) -> None:
        result = self.run_connector(FakeFetcher())
        raw = Path(result["raw_artifacts"]["endpoint"]["local_path"]).read_bytes()
        self.assertEqual(
            connector.sha256_bytes(raw),
            result["raw_artifacts"]["endpoint"]["sha256"],
        )

    def test_company_name_is_not_used_for_identity(self) -> None:
        changed = row()
        changed["公司名稱"] = "任意名稱"
        result = self.run_connector(FakeFetcher([changed]))
        self.assertEqual(result["candidate"]["subject"]["ticker"], "2317")

    def test_missing_and_duplicate_2317_are_blocked(self) -> None:
        with patch.object(connector, "read_report_yoy", return_value=Decimal("39.57")):
            with self.assertRaises(connector.DataValidationError):
                connector.run_connector(
                    self.root / "missing",
                    self.runtime_db,
                    FakeFetcher([row(code="2330")]),
                )
            with self.assertRaises(connector.DataValidationError):
                connector.run_connector(
                    self.root / "duplicate",
                    self.runtime_db,
                    FakeFetcher([row(), row()]),
                )

    def test_invalid_year_month_is_blocked(self) -> None:
        with patch.object(connector, "read_report_yoy", return_value=Decimal("39.57")):
            with self.assertRaises(connector.DataValidationError):
                connector.run_connector(
                    self.root / "bad-period",
                    self.runtime_db,
                    FakeFetcher([row(year_month="11513")]),
                )

    def test_non_array_response_is_blocked(self) -> None:
        with self.assertRaises(connector.ContractError):
            self.run_connector(FakeFetcher(row()))

    def test_primary_failure_has_no_source_fallback(self) -> None:
        with self.assertRaises(connector.PrimarySourceUnavailable):
            self.run_connector(FakeFetcher(fail_endpoint=True))

    def test_runtime_file_is_unchanged(self) -> None:
        before = connector.dbcore.sha256_file(self.runtime_db)
        result = self.run_connector(FakeFetcher())
        self.assertEqual(before, connector.dbcore.sha256_file(self.runtime_db))
        self.assertTrue(result["protected_files"]["unchanged"])

    def test_chinese_notes_and_boundaries_are_explicit(self) -> None:
        result = self.run_connector(FakeFetcher())
        self.assertEqual(result["status_zh"], "通過但有警告")
        self.assertFalse(result["actionable"])
        self.assertFalse(
            result["candidate"]["cumulative_revenue_context"][
                "formal_comparison_allowed"
            ]
        )
        self.assertIn(
            "MONTH_TO_QUARTER_PROMOTION_BLOCKED",
            result["candidate"]["warnings"],
        )


if __name__ == "__main__":
    unittest.main()
