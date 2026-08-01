from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = PACKAGE_ROOT / "db" / "tools" / "p2_03b_03_balance_sheet_connector.py"
SPEC = importlib.util.spec_from_file_location(
    "p2_03b_03_balance_sheet_connector", TOOL_PATH
)
connector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = connector
SPEC.loader.exec_module(connector)


FIELDS = [
    "出表日期", "年度", "季別", "公司代號", "公司名稱",
    "流動資產", "非流動資產", "資產總額", "流動負債", "非流動負債",
    "負債總額", "股本", "權益─具證券性質之虛擬通貨", "資本公積",
    "保留盈餘", "其他權益", "庫藏股票", "歸屬於母公司業主之權益合計",
    "共同控制下前手權益", "合併前非屬共同控制股權", "非控制權益",
    "權益總額", "預收股款（權益項下）之約當發行股數", "待註銷股本股數",
    "母公司暨子公司所持有之母公司庫藏股股數", "每股參考淨值",
]


def swagger_bytes() -> bytes:
    return json.dumps(
        {
            "paths": {
                connector.ENDPOINT_PATH: {
                    "get": {
                        "summary": "上市公司資產負債表(一般業)",
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
    year: str = "115",
    quarter: str = "1",
    bvps: str = "127.12",
) -> dict:
    values = {field: "0.00" for field in FIELDS}
    values.update(
        {
            "出表日期": "1150622",
            "年度": year,
            "季別": quarter,
            "公司代號": code,
            "公司名稱": "鴻海",
            "流動資產": "4052387707.00",
            "非流動資產": "1178091360.00",
            "資產總額": "5230479067.00",
            "流動負債": "2792211149.00",
            "非流動負債": "449469449.00",
            "負債總額": "3241680598.00",
            "股本": "140286486.00",
            "歸屬於母公司業主之權益合計": "1779930229.00",
            "權益總額": "1988798469.00",
            "待註銷股本股數": "0.00",
            "母公司暨子公司所持有之母公司庫藏股股數": "1483078.00",
            "每股參考淨值": bvps,
        }
    )
    return {field: values[field] for field in FIELDS}


class FakeFetcher:
    def __init__(self, payload=None, fail_endpoint: bool = False):
        self.payload = payload if payload is not None else [row()]
        self.fail_endpoint = fail_endpoint

    def __call__(self, url: str, timeout: int):
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


class P203B03BalanceSheetConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(
            prefix="balance-sheet-test-", dir=PACKAGE_ROOT / "staging"
        )
        self.root = Path(self.temp.name)
        self.runtime_db = self.root / "runtime.sqlite3"
        self.runtime_db.write_bytes(b"runtime-protected")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_connector(self, fetcher: FakeFetcher, existing_bvps: str = "127.12"):
        with patch.object(connector, "read_existing_bvps", return_value=existing_bvps):
            return connector.run_connector(
                self.root / "run", self.runtime_db, fetcher
            )

    def test_happy_path_confirms_bvps_match_without_observation(self) -> None:
        result = self.run_connector(FakeFetcher())
        comparison = result["candidate"]["bvps_comparison"]
        self.assertEqual(comparison["official_value"], "127.12")
        self.assertEqual(comparison["existing_value"], "127.12")
        self.assertEqual(comparison["difference"], "0.00")
        self.assertEqual(comparison["status"], "SOURCE_MATCH_CONFIRMED")
        self.assertFalse(comparison["promotion_allowed"])
        self.assertEqual(result["candidate"]["observation_count"], 0)

    def test_all_facts_are_blocked_by_unit_and_scope(self) -> None:
        result = self.run_connector(FakeFetcher())
        facts = result["candidate"]["facts"]
        self.assertEqual(len(facts), 12)
        self.assertTrue(
            all(
                fact["promotion_status"] == "BLOCKED_UNIT_SCOPE_UNVERIFIED"
                for fact in facts
            )
        )

    def test_difference_creates_pending_conflict(self) -> None:
        result = self.run_connector(FakeFetcher(), existing_bvps="126.00")
        comparison = result["candidate"]["bvps_comparison"]
        self.assertEqual(comparison["difference"], "1.12")
        self.assertEqual(comparison["status"], "DATA_CONFLICT_PENDING")

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

    def test_missing_or_duplicate_2317_is_blocked(self) -> None:
        with patch.object(connector, "read_existing_bvps", return_value="127.12"):
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

    def test_invalid_decimal_is_blocked(self) -> None:
        with self.assertRaises(connector.DataValidationError):
            self.run_connector(FakeFetcher([row(bvps="--")]))

    def test_invalid_period_is_blocked(self) -> None:
        with patch.object(connector, "read_existing_bvps", return_value="127.12"):
            with self.assertRaises(connector.DataValidationError):
                connector.run_connector(
                    self.root / "bad-year",
                    self.runtime_db,
                    FakeFetcher([row(year="2026")]),
                )
            with self.assertRaises(connector.DataValidationError):
                connector.run_connector(
                    self.root / "bad-quarter",
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
        self.assertIn("MONETARY_AND_SHARE_UNITS_UNVERIFIED", warnings)
        self.assertIn("REPORTING_SCOPE_UNVERIFIED", warnings)
        self.assertIn("BVPS_UNIT_UNVERIFIED", warnings)
        self.assertEqual(result["status_zh"], "通過但有警告")
        self.assertFalse(result["actionable"])


if __name__ == "__main__":
    unittest.main()
