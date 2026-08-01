from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = PACKAGE_ROOT / "db" / "tools" / "p2_02_legacy_migrator.py"
SPEC = importlib.util.spec_from_file_location("p2_02_legacy_migrator", TOOL_PATH)
migrator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = migrator
SPEC.loader.exec_module(migrator)


class P202LegacyMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        staging = PACKAGE_ROOT / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="p2-02-test-", dir=staging)
        cls.root = Path(cls.temp.name)
        cls.runtime_db = cls.root / "runtime.sqlite3"
        connection = migrator.dbcore.connect_database(cls.runtime_db)
        try:
            migrator.create_staging_schema(connection)
        finally:
            connection.close()
        cls.runtime_hash_before = migrator.dbcore.sha256_file(cls.runtime_db)
        cls.output_dir = cls.root / "run"
        cls.summary = migrator.run_migration(cls.output_dir, cls.runtime_db)
        cls.db_path = Path(cls.summary["staging_database"]["path"])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def test_all_headers_are_explicitly_mapped(self) -> None:
        mapping = json.loads((self.output_dir / "FIELD_MAPPING.json").read_text(encoding="utf-8"))
        self.assertEqual(len(mapping["mappings"]), 79)
        self.assertEqual(self.summary["totals"]["field_mappings"], 79)

    def test_macro_invalid_rows_are_excluded(self) -> None:
        macro = next(item for item in self.summary["datasets"] if item["dataset_code"] == "MACRO_SNAPSHOT")
        self.assertEqual(macro["source_rows"], 32)
        self.assertEqual(macro["valid_rows"], 25)
        self.assertEqual(macro["excluded_invalid_rows"], 7)
        self.assertEqual(
            [item["source_line"] for item in macro["invalid_details"]],
            [42, 43, 44, 45, 46, 47, 51],
        )

    def test_evidence_has_no_orphans(self) -> None:
        self.assertEqual(self.summary["totals"]["evidence_row_orphans"], 0)
        self.assertEqual(self.summary["totals"]["evidence_target_orphans"], 0)
        connection = self.connect()
        try:
            count = connection.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0]
            self.assertEqual(count, self.summary["totals"]["evidence_records"])
        finally:
            connection.close()

    def test_decimal_values_round_trip_exactly(self) -> None:
        connection = self.connect()
        try:
            rows = connection.execute(
                """
                SELECT e.raw_value, e.normalized_value
                FROM evidence_records e
                JOIN legacy_field_mappings m
                  ON m.legacy_run_uid=e.legacy_run_uid
                 AND m.dataset_code=(
                    SELECT dataset_code FROM legacy_source_rows
                    WHERE legacy_row_uid=e.legacy_row_uid
                 )
                 AND m.source_column=e.source_column
                WHERE m.value_type='DECIMAL'
                """
            ).fetchall()
            self.assertEqual(len(rows), self.summary["totals"]["decimal_values"])
            for row in rows:
                raw = row["raw_value"].replace("%", "").replace("+", "").replace(",", "")
                self.assertEqual(Decimal(raw), Decimal(row["normalized_value"]))
        finally:
            connection.close()

    def test_legacy_derived_values_are_not_promoted(self) -> None:
        connection = self.connect()
        try:
            wrong = connection.execute(
                """
                SELECT COUNT(*)
                FROM legacy_field_mappings
                WHERE classification IN ('LEGACY_DERIVED','LEGACY_INFERENCE')
                  AND (
                    formula_id <> 'LEGACY_UNVERIFIED'
                    OR validation_status <> 'PASS_WITH_WARNINGS'
                    OR model_usage <> 'OBSERVATION_ONLY'
                  )
                """
            ).fetchone()[0]
            self.assertEqual(wrong, 0)
        finally:
            connection.close()

    def test_subject_hierarchy_is_explicit(self) -> None:
        connection = self.connect()
        try:
            keys = {
                row[0]
                for row in connection.execute("SELECT canonical_key FROM subjects")
            }
            self.assertTrue(
                {
                    "LEGAL_ENTITY:HON_HAI_PRECISION_INDUSTRY",
                    "INSTRUMENT:HON_HAI_COMMON_EQUITY",
                    "LISTING:TWSE:2317",
                    "MACRO:GLOBAL_TW_US",
                }.issubset(keys)
            )
        finally:
            connection.close()

    def test_runtime_database_is_unchanged(self) -> None:
        self.assertEqual(self.runtime_hash_before, migrator.dbcore.sha256_file(self.runtime_db))
        self.assertTrue(self.summary["runtime_database"]["unchanged"])

    def test_evidence_ids_are_stable_for_same_sources(self) -> None:
        second_output = self.root / "run_second"
        second = migrator.run_migration(second_output, self.runtime_db)
        first_connection = self.connect()
        second_connection = sqlite3.connect(second["staging_database"]["path"])
        try:
            first_ids = [
                row[0]
                for row in first_connection.execute(
                    "SELECT evidence_id FROM evidence_records ORDER BY evidence_id"
                )
            ]
            second_ids = [
                row[0]
                for row in second_connection.execute(
                    "SELECT evidence_id FROM evidence_records ORDER BY evidence_id"
                )
            ]
            self.assertEqual(first_ids, second_ids)
        finally:
            first_connection.close()
            second_connection.close()


if __name__ == "__main__":
    unittest.main()

