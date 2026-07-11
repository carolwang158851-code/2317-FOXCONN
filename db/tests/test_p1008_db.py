from __future__ import annotations

import importlib.util
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = PACKAGE_ROOT / "db" / "tools" / "p1008_db.py"
SPEC = importlib.util.spec_from_file_location("p1008_db", TOOL_PATH)
p1008_db = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = p1008_db
SPEC.loader.exec_module(p1008_db)


EXPECTED_TABLES = {
    "audit_logs",
    "backup_records",
    "data_conflict_candidates",
    "data_conflicts",
    "derived_metric_inputs",
    "derived_metrics",
    "metric_definitions",
    "migration_runs",
    "observations",
    "pipeline_runs",
    "raw_artifacts",
    "schema_migrations",
    "sources",
    "subjects",
    "validation_results",
}


class P1008DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        staging = PACKAGE_ROOT / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(
            prefix="p1008-db-test-",
            dir=staging,
        )
        self.root = Path(self.temp.name)
        self.db_path = self.root / "runtime" / "warroom.sqlite3"
        self.backup_dir = self.root / "backups"
        self.migrations_dir = self.root / "migrations"
        shutil.copytree(PACKAGE_ROOT / "db" / "migrations", self.migrations_dir)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def migrate(self) -> dict:
        return p1008_db.migrate_database(
            self.db_path,
            self.migrations_dir,
            self.backup_dir,
        )

    def test_initial_migration_and_idempotence(self) -> None:
        first = self.migrate()
        self.assertEqual(first["status"], "PASS")
        connection = p1008_db.connect_database(self.db_path)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            self.assertEqual(tables, EXPECTED_TABLES)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 1)
        finally:
            connection.close()

        second = self.migrate()
        self.assertEqual(second["status"], "NO_CHANGES")
        self.assertEqual(second["applied_versions"], [1])

    def test_dry_run_only_does_not_apply_schema(self) -> None:
        output = p1008_db.migrate_database(
            self.db_path,
            self.migrations_dir,
            self.backup_dir,
            dry_run_only=True,
        )
        self.assertEqual(output["status"], "PASS")
        connection = p1008_db.connect_database(self.db_path)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertFalse(p1008_db.table_exists(connection, "schema_migrations"))
        finally:
            connection.close()

    def test_checksum_change_is_blocked(self) -> None:
        self.migrate()
        migration = self.migrations_dir / "0001_initial_schema.sql"
        migration.write_text(
            migration.read_text(encoding="utf-8") + "\n-- changed\n",
            encoding="utf-8",
        )
        with self.assertRaises(p1008_db.MigrationChecksumError):
            self.migrate()

    def test_foreign_key_constraint_is_enforced(self) -> None:
        self.migrate()
        connection = p1008_db.connect_database(self.db_path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO raw_artifacts(
                        artifact_uid, source_uid, retrieved_at, source_url, local_path,
                        mime_type, sha256, http_status, parser_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        p1008_db.new_ulid(),
                        p1008_db.new_ulid(),
                        "2026-06-22T00:00:00Z",
                        "https://example.invalid",
                        "raw/test.json",
                        "application/json",
                        "0" * 64,
                        200,
                        "test",
                        "2026-06-22T00:00:00Z",
                    ),
                )
        finally:
            connection.close()

    def test_os_writer_lock_excludes_second_writer(self) -> None:
        lock_path = self.db_path.with_suffix(".sqlite3.writer.lock")
        with p1008_db.OsWriterLock(lock_path):
            with self.assertRaises(p1008_db.WriterLockError):
                with p1008_db.OsWriterLock(lock_path):
                    pass

    def test_pipeline_lease_and_expired_takeover_audit(self) -> None:
        self.migrate()
        first_uid = p1008_db.new_ulid()
        connection = p1008_db.connect_database(self.db_path)
        try:
            connection.execute(
                """
                INSERT INTO pipeline_runs(
                    pipeline_run_uid, writer_id, task_type, started_at,
                    heartbeat_at, lease_expires_at, status,
                    takeover_from_uid, message_zh
                ) VALUES (?, 'writer-a', 'TEST', '2026-06-22T00:00:00Z',
                          '2026-06-22T00:00:00Z', '2099-01-01T00:00:00Z',
                          'RUNNING', NULL, 'Writer租約有效')
                """,
                (first_uid,),
            )
        finally:
            connection.close()

        with self.assertRaises(p1008_db.ActiveLeaseError):
            with p1008_db.writer_lease(
                self.db_path,
                writer_id="writer-b",
                task_type="TEST_BLOCKED",
            ):
                pass

        connection = p1008_db.connect_database(self.db_path)
        try:
            connection.execute(
                """
                UPDATE pipeline_runs
                SET lease_expires_at='2000-01-01T00:00:00Z'
                WHERE pipeline_run_uid=?
                """,
                (first_uid,),
            )
        finally:
            connection.close()

        with p1008_db.writer_lease(
            self.db_path,
            writer_id="writer-b",
            task_type="TEST_TAKEOVER",
        ) as (_, second_uid):
            self.assertNotEqual(first_uid, second_uid)

        connection = p1008_db.connect_database(self.db_path)
        try:
            first_status = connection.execute(
                "SELECT status FROM pipeline_runs WHERE pipeline_run_uid=?",
                (first_uid,),
            ).fetchone()[0]
            audit_count = connection.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE event_type='WRITER_LEASE_TAKEOVER'"
            ).fetchone()[0]
            self.assertEqual(first_status, "ABANDONED")
            self.assertEqual(audit_count, 1)
        finally:
            connection.close()

    def test_online_backup_manifest_and_restore(self) -> None:
        self.migrate()
        with p1008_db.writer_lease(
            self.db_path,
            writer_id="backup-test",
            task_type="TEST_WRITE",
        ) as (connection, _):
            now = p1008_db.utc_now()
            connection.execute(
                """
                INSERT INTO subjects(
                    subject_uid, subject_type, canonical_key, name, ticker, market,
                    isin, cik, currency, parent_subject_uid, status, created_at, updated_at
                ) VALUES (?, 'COMPANY', 'TWSE:2317', 'Hon Hai Precision', '2317',
                          'TWSE', NULL, NULL, 'TWD', NULL, 'ACTIVE', ?, ?)
                """,
                (p1008_db.new_ulid(), now, now),
            )

        with p1008_db.OsWriterLock(
            self.db_path.with_suffix(self.db_path.suffix + ".writer.lock")
        ):
            connection = p1008_db.connect_database(self.db_path)
            try:
                manifest = p1008_db.create_backup(
                    connection,
                    source_database_path=self.db_path,
                    backup_root=self.backup_dir,
                    reason="TEST_RESTORE",
                )
            finally:
                connection.close()

        backup_path = Path(manifest["backup_path"])
        verified = p1008_db.verify_backup(backup_path)
        self.assertEqual(verified["status"], "PASS")
        self.assertEqual(
            json.loads(Path(manifest["manifest_path"]).read_text(encoding="utf-8"))[
                "database_sha256"
            ],
            p1008_db.sha256_file(backup_path),
        )

        restored = self.root / "restored" / "warroom.sqlite3"
        restore_result = p1008_db.restore_backup(backup_path, restored)
        self.assertEqual(restore_result["status"], "PASS")
        connection = p1008_db.connect_database(restored)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM subjects").fetchone()[0], 1)
            checks = p1008_db.verify_connection(connection)
            self.assertEqual(checks["integrity_check_status"], "PASS")
            self.assertEqual(checks["foreign_key_check_status"], "PASS")
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
