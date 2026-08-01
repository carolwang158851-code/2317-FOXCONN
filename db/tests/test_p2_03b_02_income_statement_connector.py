from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = (
    PACKAGE_ROOT / "db" / "tools" / "p2_03b_02_income_statement_connector.py"
)
SPEC = importlib.util.spec_from_file_location(
    "p2_03b_02_income_statement_connector", TOOL_PATH
)
connector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = connector
SPEC.loader.exec_module(connector)


FIELDS = [
    "出表日期",
    "年度",
    "季別",
    "公司代號",
    "公司名稱",
    "營業收入",
    "營業成本",
    "原始認列生物資產及農產品之利益（損失）",
    "生物資產當期公允價值減出售成本之變動利益（損失）",
    "營業毛利（毛損）",
    "未實現銷貨（損）益",
    "已實現銷貨（損）益",
    "營業毛利（毛損）淨額",
    "營業費用",
    "其他收益及費損淨額",
    "營業利益（損失）",
    "營業外收入及支出",
    "稅前淨利（淨損）",
    "所得稅費用（利益）",
    "繼續營業單位本期淨利（淨損）",
    "停業單位損益",
    "合併前非屬共同控制股權損益",
    "本期淨利（淨損）",
    "其他綜合損益（淨額）",
    "合併前非屬共同控制股權綜合損益淨額",
    "本期綜合損益總額",
    "淨利（淨損）歸屬於母公司業主",
    "淨利（淨損）歸屬於共同控制下前手權益",
    "淨利（淨損）歸屬於非控制權益",
    "綜合損益總額歸屬於母公司業主",
    "綜合損益總額歸屬於共同控制下前手權益",
    "綜合損益總額歸屬於非控制權益",
    "基本每股盈餘（元）",
]


def swagger_bytes() -> bytes:
    return json.dumps(
        {
            "paths": {
                connector.ENDPOINT_PATH: {
                    "get": {
                        "summary": "上市公司綜合損益表(一般業)",
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
    year: str = "114",
    quarter: str = "4",
    eps: str = "13.61",
) -> dict:
    values = {field: "0" for field in FIELDS}
    values.update(
        {
            "出表日期": "1150331",
            "年度": year,
            "季別": quarter,
            "公司代號": code,
            "公司名稱": "鴻海精密",
            "營業收入": "7212789000",
            "營業成本": "6760000000",
            "營業毛利（毛損）淨額": "452789000",
            "營業利益（損失）": "250000000",
            "稅前淨利（淨損）": "245000000",
            "所得稅費用（利益）": "55000000",
            "淨利（淨損）歸屬於母公司業主": "188000000",
            "基本每股盈餘（元）": eps,
        }
    )
    return {field: values[field] for field in FIELDS}


class FakeFetcher:
    def __init__(self, payload=None, fail_endpoint: bool = False):
        self.payload = payload if payload is not None else [row()]
        self.fail_endpoint = fail_endpoint
        self.calls = []

    def __call__(self, url: str, timeout: int):
        self.calls.append(url)
        if url == connector.SWAGGER_URL:
            return connector.HttpResult(
                url, 200, "application/json", {}, swagger_bytes()
            )
        if self.fail_endpoint:
            raise connector.PrimarySourceUnavailable("fixture unavailable")
        return connector.HttpResult(
            url,
            200,
            "application/json",
            {},
            json.dumps(self.payload, ensure_ascii=False).encode(),
        )


class P203B02IncomeStatementConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        staging = PACKAGE_ROOT / "staging"
        self.temp = tempfile.TemporaryDirectory(
            prefix="income-statement-test-", dir=staging
        )
        self.root = Path(self.temp.name)
        self.runtime_db = self.root / "runtime.sqlite3"
        self.runtime_db.write_bytes(b"runtime-protected")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_connector(self, fetcher: FakeFetcher):
        return connector.run_connector(
            self.root / "run", self.runtime_db, fetcher
        )

    def test_happy_path_creates_only_cumulative_eps_observation(self) -> None:
        result = self.run_connector(FakeFetcher())
        candidate = result["candidate"]
        self.assertEqual(candidate["period"]["period_label"], "2025Q4")
        self.assertEqual(candidate["period"]["period_basis"], "CUMULATIVE_YTD")
        self.assertEqual(candidate["observation_count"], 1)
        self.assertEqual(candidate["blocked_fact_count"], 7)
        eps = next(
            fact for fact in candidate["facts"]
            if fact["metric_code"] == "MOPS_CUM_BASIC_EPS"
        )
        self.assertEqual(eps["normalized_value"], "13.61")
        self.assertEqual(eps["promotion_status"], "OBSERVATION_ONLY")

    def test_monetary_facts_are_blocked_when_unit_is_unknown(self) -> None:
        result = self.run_connector(FakeFetcher())
        money = [
            fact for fact in result["candidate"]["facts"]
            if fact["metric_code"] != "MOPS_CUM_BASIC_EPS"
        ]
        self.assertTrue(all(fact["unit_status"] == "UNVERIFIED" for fact in money))
        self.assertTrue(
            all(
                fact["promotion_status"] == "BLOCKED_UNIT_UNVERIFIED"
                for fact in money
            )
        )
        self.assertTrue(all(fact["observation_uid"] is None for fact in money))

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

    def test_missing_2317_is_blocked(self) -> None:
        with self.assertRaises(connector.DataValidationError):
            self.run_connector(FakeFetcher([row(code="2330")]))

    def test_duplicate_2317_is_blocked(self) -> None:
        with self.assertRaises(connector.DataValidationError):
            self.run_connector(FakeFetcher([row(), row()]))

    def test_invalid_decimal_is_blocked(self) -> None:
        with self.assertRaises(connector.DataValidationError):
            self.run_connector(FakeFetcher([row(eps="--")]))

    def test_invalid_year_or_quarter_is_blocked(self) -> None:
        with self.assertRaises(connector.DataValidationError):
            connector.run_connector(
                self.root / "run-invalid-year",
                self.runtime_db,
                FakeFetcher([row(year="2025")]),
            )
        with self.assertRaises(connector.DataValidationError):
            connector.run_connector(
                self.root / "run-invalid-quarter",
                self.runtime_db,
                FakeFetcher([row(quarter="5")]),
            )

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

    def test_warnings_and_chinese_notes_are_explicit(self) -> None:
        result = self.run_connector(FakeFetcher())
        warnings = result["candidate"]["warnings"]
        self.assertIn("SWAGGER_RESPONSE_SHAPE_MISMATCH", warnings)
        self.assertIn("CUMULATIVE_PERIOD_NOT_SINGLE_QUARTER", warnings)
        self.assertIn("MONETARY_UNIT_UNVERIFIED", warnings)
        self.assertIn("REPORTING_SCOPE_UNVERIFIED", warnings)
        self.assertEqual(result["status_zh"], "通過但有警告")
        self.assertFalse(result["actionable"])


if __name__ == "__main__":
    unittest.main()
