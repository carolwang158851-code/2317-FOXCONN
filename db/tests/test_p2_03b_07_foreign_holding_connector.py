from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
import urllib.parse
from decimal import Decimal
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = (
    PACKAGE_ROOT / "db" / "tools" / "p2_03b_07_foreign_holding_connector.py"
)
SPEC = importlib.util.spec_from_file_location(
    "p2_03b_07_foreign_holding_connector", TOOL_PATH
)
connector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = connector
SPEC.loader.exec_module(connector)


def quarter_ratios() -> dict[str, Decimal]:
    ratios = {}
    for index, item in enumerate(connector.required_quarters()):
        ratios[item["quarter"]] = Decimal("30.00") + Decimal(index) * Decimal("0.25")
    ratios["2025Q4"] = Decimal("38.32")
    ratios["2026Q1"] = Decimal("36.28")
    return ratios


def payload(date_value, ratio: Decimal, *, code: str = "2317", isin=None) -> dict:
    issued = Decimal("10000000")
    holding = issued * ratio / Decimal("100")
    row = [
        code,
        "鴻海",
        isin or ("TW0002317005" if code == "2317" else "TW0002330008"),
        str(int(issued)),
        "5000000",
        str(int(holding)),
        "50.00",
        f"{ratio:.2f}",
        "100.00",
        "30.00",
        "",
        date_value.strftime("%Y%m%d"),
    ]
    return {
        "stat": "OK",
        "date": date_value.strftime("%Y%m%d"),
        "title": "外資及陸資投資持股統計",
        "fields": connector.EXPECTED_FIELDS,
        "data": [row],
        "notes": ["fixture"],
        "total": 1,
    }


class FakeFetcher:
    def __init__(
        self,
        *,
        prior_available_quarter: str | None = None,
        payload_mutator=None,
        fail: bool = False,
    ):
        self.ratios = quarter_ratios()
        self.prior_available_quarter = prior_available_quarter
        self.payload_mutator = payload_mutator
        self.fail = fail
        self.requests = []
        self.valid_dates = {}
        for item in connector.required_quarters():
            valid_date = item["quarter_end"]
            if item["quarter"] == prior_available_quarter:
                valid_date = valid_date - connector.dt.timedelta(days=2)
            self.valid_dates[valid_date] = item["quarter"]

    def __call__(self, url: str, timeout: int):
        self.requests.append(url)
        if self.fail:
            raise connector.PrimarySourceUnavailable("fixture unavailable")
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        date_value = connector.dt.datetime.strptime(
            query["date"][0], "%Y%m%d"
        ).date()
        quarter = self.valid_dates.get(date_value)
        if quarter is None:
            body = {
                "stat": "很抱歉，沒有符合條件的資料!",
                "date": date_value.strftime("%Y%m%d"),
            }
        else:
            body = payload(date_value, self.ratios[quarter])
            if self.payload_mutator is not None:
                body = self.payload_mutator(body, quarter)
        return connector.HttpResult(
            url,
            200,
            "application/json",
            {},
            json.dumps(body, ensure_ascii=False).encode("utf-8"),
            "FIXTURE",
        )


class P203B07ForeignHoldingConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(
            prefix="foreign-holding-test-", dir=PACKAGE_ROOT / "staging"
        )
        self.root = Path(self.temp.name)
        self.runtime_db = self.root / "runtime.sqlite3"
        self.runtime_db.write_bytes(b"runtime-protected")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_connector(self, fetcher=None, name: str = "run"):
        return connector.run_connector(
            self.root / name,
            self.runtime_db,
            fetcher or FakeFetcher(),
            sleep_seconds=0,
        )

    def test_required_quarters_include_baseline_and_21_candidate_rows(self) -> None:
        quarters = connector.required_quarters()
        self.assertEqual(len(quarters), 22)
        self.assertEqual(quarters[0]["quarter"], "2020Q4")
        self.assertFalse(quarters[0]["is_candidate_row"])
        self.assertEqual(quarters[-1]["quarter"], "2026Q1")
        self.assertEqual(sum(item["is_candidate_row"] for item in quarters), 21)

    def test_happy_path_builds_pending_release_and_candidate(self) -> None:
        result = self.run_connector()
        self.assertEqual(result["connector"]["snapshot_count"], 22)
        self.assertEqual(result["changes"]["compared"], 63)
        self.assertEqual(result["release"]["status"], "READY_FOR_OWNER_REVIEW")
        self.assertFalse(result["release"]["published"])
        self.assertEqual(result["owner_acceptance"], "PENDING_MANIFEST_APPROVAL")
        self.assertTrue(
            Path(result["release"]["candidate_dir"], "data", "2317_master_v9.csv").is_file()
        )

    def test_prior_available_date_is_recorded(self) -> None:
        result = self.run_connector(
            FakeFetcher(prior_available_quarter="2024Q2")
        )
        row = next(item for item in result["series"] if item["quarter"] == "2024Q2")
        self.assertEqual(row["date_alignment_status"], "PRIOR_AVAILABLE_DATE")
        attempts = next(
            item for item in result["attempt_log"] if item["quarter"] == "2024Q2"
        )
        self.assertEqual(len(attempts["attempts"]), 3)

    def test_2026q1_change_and_trend_use_official_series(self) -> None:
        result = self.run_connector()
        row = next(item for item in result["series"] if item["quarter"] == "2026Q1")
        self.assertEqual(row["ratio_pct"], "36.28")
        self.assertEqual(row["change_pct_point"], "-2.04")
        self.assertEqual(row["trend"], "DECLINING")
        self.assertEqual(result["candidate_2026Q1"]["ForeignHoldRatio_Pct"], "36.28")
        self.assertEqual(result["candidate_2026Q1"]["ForeignHoldTrend"], "DECLINING")

    def test_only_three_approved_fields_change(self) -> None:
        result = self.run_connector()
        manifest_path = Path(result["release"]["candidate_dir"]) / "RELEASE_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        fields = {item["field"] for item in manifest["payload"]["changes"]}
        self.assertEqual(
            fields,
            {
                "ForeignHoldRatio_Pct",
                "ForeignHoldChange_Pct",
                "ForeignHoldTrend",
            },
        )
        self.assertIn("DataSource", manifest["payload"]["excluded_changes"])
        self.assertIn("DataSupportLevel", manifest["payload"]["excluded_changes"])

    def test_candidate_authority_manifest_has_field_level_evidence(self) -> None:
        result = self.run_connector()
        path = (
            Path(result["release"]["candidate_dir"])
            / "data"
            / "CSV_AUTHORITY_MANIFEST.json"
        )
        authority = json.loads(path.read_text(encoding="utf-8"))
        master = next(
            item
            for item in authority["authoritativeFiles"]
            if item["path"] == "data/2317_master_v9.csv"
        )
        overrides = master["fieldOverrides"]
        self.assertEqual(
            overrides["ForeignHoldRatio_Pct"]["sourceMetricZh"],
            "全體外資及陸資持股比率",
        )
        self.assertEqual(overrides["ForeignHoldRatio_Pct"]["ruleUsage"], "OBSERVATION_ONLY")

    def test_field_contract_change_is_blocked(self) -> None:
        def mutate(body, quarter):
            if quarter == "2020Q4":
                body["fields"] = list(reversed(body["fields"]))
            return body

        with self.assertRaises(connector.ContractError):
            self.run_connector(FakeFetcher(payload_mutator=mutate))

    def test_wrong_isin_is_blocked(self) -> None:
        def mutate(body, quarter):
            if quarter == "2020Q4":
                body["data"][0][2] = "TW0002330008"
            return body

        with self.assertRaises(connector.DataValidationError):
            self.run_connector(FakeFetcher(payload_mutator=mutate))

    def test_ratio_recompute_mismatch_is_blocked(self) -> None:
        def mutate(body, quarter):
            if quarter == "2020Q4":
                body["data"][0][7] = "99.99"
            return body

        with self.assertRaises(connector.DataValidationError):
            self.run_connector(FakeFetcher(payload_mutator=mutate))

    def test_missing_and_duplicate_2317_are_blocked(self) -> None:
        date_value = connector.dt.date(2026, 3, 31)
        missing = payload(date_value, Decimal("36.28"), code="2330")
        self.assertIsNone(connector.parse_snapshot(missing, date_value))
        duplicate = payload(date_value, Decimal("36.28"))
        duplicate["data"].append(list(duplicate["data"][0]))
        with self.assertRaises(connector.DataValidationError):
            connector.parse_snapshot(duplicate, date_value)

    def test_primary_failure_has_no_source_fallback(self) -> None:
        with self.assertRaises(connector.PrimarySourceUnavailable):
            self.run_connector(FakeFetcher(fail=True))

    def test_manifest_payload_hash_is_reproducible(self) -> None:
        first = self.run_connector(name="run-1")
        second = self.run_connector(name="run-2")
        self.assertEqual(
            first["release"]["manifest_sha256"],
            second["release"]["manifest_sha256"],
        )
        manifest_path = Path(first["release"]["candidate_dir"]) / "RELEASE_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            connector.sha256_json(manifest["payload"]),
            manifest["manifest_sha256"],
        )

    def test_staging_database_counts_and_integrity(self) -> None:
        result = self.run_connector()
        self.assertEqual(result["staging_database"]["integrity_check_status"], "PASS")
        self.assertEqual(result["staging_database"]["foreign_key_check_status"], "PASS")
        connection = sqlite3.connect(result["staging_database"]["path"])
        try:
            counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "foreign_holding_snapshots",
                    "foreign_holding_series",
                    "candidate_changes",
                    "candidate_releases",
                )
            }
        finally:
            connection.close()
        self.assertEqual(
            counts,
            {
                "foreign_holding_snapshots": 22,
                "foreign_holding_series": 21,
                "candidate_changes": 63,
                "candidate_releases": 1,
            },
        )

    def test_formal_files_runtime_and_t86_are_untouched(self) -> None:
        before = connector.protected_hashes(self.runtime_db)
        result = self.run_connector()
        self.assertEqual(before, connector.protected_hashes(self.runtime_db))
        self.assertTrue(result["protected_files"]["unchanged"])
        self.assertFalse(result["connector"]["t86_used"])
        self.assertEqual(result["connector"]["fallback_policy"], "NO_SOURCE_FALLBACK")

    def test_chinese_status_and_non_actionable_boundary_are_explicit(self) -> None:
        result = self.run_connector()
        self.assertEqual(result["status_zh"], "通過但有警告")
        self.assertIn("尚未發布", result["status_note_zh"])
        self.assertFalse(result["actionable"])


if __name__ == "__main__":
    unittest.main()
