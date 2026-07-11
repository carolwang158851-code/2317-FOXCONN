from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence


RUNNER_VERSION = "p2-01.1"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MIGRATIONS_DIR = PROJECT_ROOT / "db" / "migrations"
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "backups" / "sqlite"
DEFAULT_DB_PATH = (
    Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
    / "P1008"
    / "data"
    / "warroom.sqlite3"
)
CROCKFORD32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class DatabaseError(RuntimeError):
    pass


class WriterLockError(DatabaseError):
    pass


class MigrationChecksumError(DatabaseError):
    pass


class ActiveLeaseError(DatabaseError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def new_ulid() -> str:
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    chars = []
    for _ in range(26):
        chars.append(CROCKFORD32[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def canonical_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def result(status: str, note_zh: str, **extra: object) -> dict:
    labels = {
        "PASS": "通過",
        "PASS_WITH_WARNINGS": "通過但有警告",
        "FAIL": "失敗",
        "NO_CHANGES": "無變更",
    }
    return {
        "status": status,
        "status_zh": labels.get(status, status),
        "status_note_zh": note_zh,
        "actionable": False,
        **extra,
    }


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    checksum: str


def discover_migrations(directory: Path) -> list[Migration]:
    migrations = []
    for path in sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        prefix, name = path.stem.split("_", 1)
        migrations.append(
            Migration(
                version=int(prefix),
                name=name,
                path=path,
                checksum=sha256_file(path),
            )
        )
    versions = [item.version for item in migrations]
    if not migrations:
        raise DatabaseError(f"找不到Migration：{directory}")
    if versions != sorted(set(versions)):
        raise DatabaseError("Migration版本重複或排序異常")
    return migrations


class OsWriterLock:
    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.handle = None

    def __enter__(self) -> "OsWriterLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.lock_path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise WriterLockError("已有另一個P1008 Writer持有作業系統鎖") from exc
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if not self.handle:
            return
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
        self.handle = None


def connect_database(path: Path, *, wal: bool = True) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA synchronous = FULL")
    if wal:
        mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            connection.close()
            raise DatabaseError(f"無法啟用WAL，實際模式：{mode}")
    return connection


def table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def applied_migrations(connection: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    if not table_exists(connection, "schema_migrations"):
        return {}
    rows = connection.execute(
        "SELECT version, name, checksum_sha256 FROM schema_migrations ORDER BY version"
    ).fetchall()
    return {int(row["version"]): row for row in rows}


def validate_migration_history(
    connection: sqlite3.Connection, migrations: Sequence[Migration]
) -> None:
    known = {item.version: item for item in migrations}
    for version, row in applied_migrations(connection).items():
        migration = known.get(version)
        if migration is None:
            raise MigrationChecksumError(f"資料庫包含未知Migration版本：{version}")
        if row["checksum_sha256"] != migration.checksum:
            raise MigrationChecksumError(
                f"Migration {version:04d} checksum不一致，禁止繼續"
            )


def split_sql_statements(script: str) -> list[str]:
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                statements.append(statement)
            buffer = ""
    if buffer.strip():
        raise DatabaseError("Migration SQL最後一個陳述式不完整")
    return statements


def verify_connection(connection: sqlite3.Connection) -> dict:
    integrity_rows = [row[0] for row in connection.execute("PRAGMA integrity_check")]
    foreign_key_rows = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
    integrity_ok = integrity_rows == ["ok"]
    foreign_keys_ok = not foreign_key_rows
    return {
        "integrity_check_status": "PASS" if integrity_ok else "FAIL",
        "foreign_key_check_status": "PASS" if foreign_keys_ok else "FAIL",
        "integrity_details": integrity_rows,
        "foreign_key_details": foreign_key_rows,
        "schema_version": int(connection.execute("PRAGMA user_version").fetchone()[0]),
        "journal_mode": str(connection.execute("PRAGMA journal_mode").fetchone()[0]).upper(),
        "foreign_keys_enabled": bool(connection.execute("PRAGMA foreign_keys").fetchone()[0]),
    }


def apply_one_migration(
    connection: sqlite3.Connection,
    migration: Migration,
    *,
    mode: str,
    backup_id: str | None,
) -> None:
    started = time.perf_counter()
    run_uid = new_ulid()
    started_at = utc_now()
    existed_before = table_exists(connection, "migration_runs")
    try:
        connection.execute("BEGIN IMMEDIATE")
        for statement in split_sql_statements(migration.path.read_text(encoding="utf-8")):
            connection.execute(statement)
        elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
        connection.execute(
            """
            INSERT INTO schema_migrations(
                version, name, checksum_sha256, applied_at, execution_ms, runner_version
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                migration.version,
                migration.name,
                migration.checksum,
                utc_now(),
                elapsed_ms,
                RUNNER_VERSION,
            ),
        )
        connection.execute(
            """
            INSERT INTO migration_runs(
                run_uid, migration_version, migration_name, checksum_sha256,
                mode, status, started_at, finished_at, backup_id, message_zh
            ) VALUES (?, ?, ?, ?, ?, 'PASS', ?, ?, ?, ?)
            """,
            (
                run_uid,
                migration.version,
                migration.name,
                migration.checksum,
                mode,
                started_at,
                utc_now(),
                backup_id,
                "Migration執行與完整性驗證通過",
            ),
        )
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        if existed_before and table_exists(connection, "migration_runs"):
            connection.execute(
                """
                INSERT INTO migration_runs(
                    run_uid, migration_version, migration_name, checksum_sha256,
                    mode, status, started_at, finished_at, backup_id, message_zh
                ) VALUES (?, ?, ?, ?, ?, 'FAIL', ?, ?, ?, ?)
                """,
                (
                    run_uid,
                    migration.version,
                    migration.name,
                    migration.checksum,
                    mode,
                    started_at,
                    utc_now(),
                    backup_id,
                    "Migration失敗並已回復交易",
                ),
            )
        raise


def latest_observation_at(connection: sqlite3.Connection) -> str | None:
    if not table_exists(connection, "observations"):
        return None
    return connection.execute("SELECT MAX(retrieved_at) FROM observations").fetchone()[0]


def create_backup(
    connection: sqlite3.Connection,
    *,
    source_database_path: Path,
    backup_root: Path,
    reason: str,
) -> dict:
    created_at = utc_now()
    stamp = created_at.replace("-", "").replace(":", "")
    year, month = created_at[:4], created_at[5:7]
    target_dir = backup_root / year / month
    target_dir.mkdir(parents=True, exist_ok=True)

    temporary_path = target_dir / f".p1008-backup-{new_ulid()}.tmp.sqlite3"
    target = sqlite3.connect(temporary_path)
    try:
        connection.backup(target)
        target.execute("PRAGMA foreign_keys = ON")
        checks = verify_connection(target)
    finally:
        target.close()

    if checks["integrity_check_status"] != "PASS" or checks["foreign_key_check_status"] != "PASS":
        temporary_path.unlink(missing_ok=True)
        raise DatabaseError("備份完整性檢查失敗")

    database_sha256 = sha256_file(temporary_path)
    filename = f"P1008_DB_{stamp}_{database_sha256[:8]}.sqlite3"
    backup_path = target_dir / filename
    manifest_path = backup_path.with_suffix(".manifest.json")
    if backup_path.exists() or manifest_path.exists():
        temporary_path.unlink(missing_ok=True)
        raise DatabaseError(f"備份檔名已存在，禁止覆寫：{filename}")
    temporary_path.replace(backup_path)

    backup_id = f"BKP-P1008-{stamp}-{database_sha256[:8]}"
    manifest = result(
        "PASS",
        "SQLite Online Backup、SHA-256及完整性檢查均通過",
        backup_id=backup_id,
        database_sha256=database_sha256,
        schema_version=checks["schema_version"],
        latest_observation_at=latest_observation_at(connection),
        latest_release_id=None,
        backup_reason=reason,
        created_at=created_at,
        integrity_check_status=checks["integrity_check_status"],
        foreign_key_check_status=checks["foreign_key_check_status"],
        source_database_path=str(source_database_path.resolve()),
        backup_path=str(backup_path.resolve()),
        manifest_path=str(manifest_path.resolve()),
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if table_exists(connection, "backup_records"):
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                INSERT INTO backup_records(
                    backup_id, database_sha256, schema_version, latest_observation_at,
                    latest_release_id, backup_reason, created_at,
                    integrity_check_status, foreign_key_check_status,
                    source_database_path, backup_path, manifest_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    backup_id,
                    database_sha256,
                    checks["schema_version"],
                    manifest["latest_observation_at"],
                    None,
                    reason,
                    created_at,
                    checks["integrity_check_status"],
                    checks["foreign_key_check_status"],
                    manifest["source_database_path"],
                    manifest["backup_path"],
                    manifest["manifest_path"],
                ),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    return manifest


def verify_backup(backup_path: Path) -> dict:
    manifest_path = backup_path.with_suffix(".manifest.json")
    if not manifest_path.exists():
        raise DatabaseError(f"找不到Backup Manifest：{manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_sha = sha256_file(backup_path)
    if actual_sha != manifest.get("database_sha256"):
        raise DatabaseError("備份SHA-256與Manifest不一致")
    connection = connect_database(backup_path, wal=False)
    try:
        checks = verify_connection(connection)
    finally:
        connection.close()
    if checks["integrity_check_status"] != "PASS" or checks["foreign_key_check_status"] != "PASS":
        raise DatabaseError("備份SQLite完整性檢查失敗")
    return result(
        "PASS",
        "備份雜湊、SQLite完整性及外鍵檢查均通過",
        backup_path=str(backup_path.resolve()),
        database_sha256=actual_sha,
        checks=checks,
    )


def restore_backup(backup_path: Path, target_path: Path) -> dict:
    verify_backup(backup_path)
    if target_path.exists():
        raise DatabaseError(f"回復目標已存在，禁止覆寫：{target_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_target = target_path.with_suffix(target_path.suffix + ".restore.tmp")
    source = connect_database(backup_path, wal=False)
    destination = sqlite3.connect(temporary_target)
    try:
        source.backup(destination)
        destination.execute("PRAGMA foreign_keys = ON")
        checks = verify_connection(destination)
    finally:
        source.close()
        destination.close()
    if checks["integrity_check_status"] != "PASS" or checks["foreign_key_check_status"] != "PASS":
        temporary_target.unlink(missing_ok=True)
        raise DatabaseError("回復後完整性檢查失敗")
    temporary_target.replace(target_path)
    return result(
        "PASS",
        "備份已回復至新路徑，且完整性檢查通過",
        restored_path=str(target_path.resolve()),
        database_sha256=sha256_file(target_path),
        checks=checks,
    )


def clone_database(source_path: Path, target_path: Path) -> None:
    source = connect_database(source_path, wal=False)
    target = sqlite3.connect(target_path)
    try:
        source.backup(target)
    finally:
        source.close()
        target.close()


def migrate_database(
    db_path: Path,
    migrations_dir: Path,
    backup_dir: Path,
    *,
    dry_run_only: bool = False,
) -> dict:
    migrations = discover_migrations(migrations_dir)
    lock_path = db_path.with_suffix(db_path.suffix + ".writer.lock")
    with OsWriterLock(lock_path):
        connection = connect_database(db_path)
        try:
            validate_migration_history(connection, migrations)
            applied = applied_migrations(connection)
            pending = [item for item in migrations if item.version not in applied]
            if not pending:
                checks = verify_connection(connection)
                return result(
                    "NO_CHANGES",
                    "所有Migration已套用且checksum一致",
                    database_path=str(db_path.resolve()),
                    applied_versions=sorted(applied),
                    pending_versions=[],
                    checks=checks,
                )

            backup_manifest = create_backup(
                connection,
                source_database_path=db_path,
                backup_root=backup_dir,
                reason="PRE_MIGRATION",
            )
        finally:
            connection.close()

        with tempfile.TemporaryDirectory(
            prefix="p1008-migration-dryrun-",
            dir=db_path.parent,
        ) as temp_dir:
            dry_run_db = Path(temp_dir) / "dry_run.sqlite3"
            clone_database(Path(backup_manifest["backup_path"]), dry_run_db)
            dry_connection = connect_database(dry_run_db)
            try:
                for migration in pending:
                    apply_one_migration(
                        dry_connection,
                        migration,
                        mode="DRY_RUN",
                        backup_id=backup_manifest["backup_id"],
                    )
                dry_checks = verify_connection(dry_connection)
            finally:
                dry_connection.close()
            if (
                dry_checks["integrity_check_status"] != "PASS"
                or dry_checks["foreign_key_check_status"] != "PASS"
            ):
                raise DatabaseError("Migration Dry-Run完整性檢查失敗")

        if dry_run_only:
            return result(
                "PASS",
                "Migration Dry-Run通過；正式資料庫未套用變更",
                database_path=str(db_path.resolve()),
                pending_versions=[item.version for item in pending],
                backup=backup_manifest,
                dry_run_checks=dry_checks,
            )

        connection = connect_database(db_path)
        try:
            validate_migration_history(connection, migrations)
            for migration in pending:
                apply_one_migration(
                    connection,
                    migration,
                    mode="APPLY",
                    backup_id=backup_manifest["backup_id"],
                )
            final_checks = verify_connection(connection)
        finally:
            connection.close()
        if (
            final_checks["integrity_check_status"] != "PASS"
            or final_checks["foreign_key_check_status"] != "PASS"
        ):
            raise DatabaseError("正式Migration後完整性檢查失敗，應停止Writer並回復備份")
        return result(
            "PASS",
            "Migration Dry-Run與正式套用均通過",
            database_path=str(db_path.resolve()),
            applied_versions=[item.version for item in pending],
            backup=backup_manifest,
            dry_run_checks=dry_checks,
            final_checks=final_checks,
        )


@contextlib.contextmanager
def writer_lease(
    db_path: Path,
    *,
    writer_id: str,
    task_type: str,
    lease_seconds: int = 60,
) -> Iterator[tuple[sqlite3.Connection, str]]:
    lock_path = db_path.with_suffix(db_path.suffix + ".writer.lock")
    with OsWriterLock(lock_path):
        connection = connect_database(db_path)
        run_uid = new_ulid()
        now = utc_now()
        expires_at = (
            dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=lease_seconds)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        try:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                """
                SELECT pipeline_run_uid, writer_id, lease_expires_at
                FROM pipeline_runs
                WHERE status='RUNNING'
                """
            ).fetchone()
            takeover_from = None
            if active:
                if parse_utc(active["lease_expires_at"]) > dt.datetime.now(dt.timezone.utc):
                    raise ActiveLeaseError(
                        f"Writer租約仍有效：{active['writer_id']} / {active['pipeline_run_uid']}"
                    )
                takeover_from = active["pipeline_run_uid"]
                connection.execute(
                    """
                    UPDATE pipeline_runs
                    SET status='ABANDONED', message_zh=?
                    WHERE pipeline_run_uid=?
                    """,
                    ("Writer租約逾時，已由新Writer接管", takeover_from),
                )
                connection.execute(
                    """
                    INSERT INTO audit_logs(
                        audit_uid, event_type, actor_id, target_type, target_uid,
                        occurred_at, details_json, actionable, message_zh
                    ) VALUES (?, 'WRITER_LEASE_TAKEOVER', ?, 'PIPELINE_RUN', ?, ?, ?, 0, ?)
                    """,
                    (
                        new_ulid(),
                        writer_id,
                        takeover_from,
                        now,
                        canonical_json({"previous_writer_id": active["writer_id"]}),
                        "逾時Writer租約已接管並保留稽核紀錄",
                    ),
                )
            connection.execute(
                """
                INSERT INTO pipeline_runs(
                    pipeline_run_uid, writer_id, task_type, started_at,
                    heartbeat_at, lease_expires_at, status,
                    takeover_from_uid, message_zh
                ) VALUES (?, ?, ?, ?, ?, ?, 'RUNNING', ?, ?)
                """,
                (
                    run_uid,
                    writer_id,
                    task_type,
                    now,
                    now,
                    expires_at,
                    takeover_from,
                    "Writer租約有效",
                ),
            )
            connection.execute("COMMIT")
            yield connection, run_uid
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE pipeline_runs
                SET status='COMPLETED', heartbeat_at=?, lease_expires_at=?, message_zh=?
                WHERE pipeline_run_uid=?
                """,
                (utc_now(), utc_now(), "Writer工作已完成", run_uid),
            )
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            if table_exists(connection, "pipeline_runs"):
                connection.execute(
                    """
                    UPDATE pipeline_runs
                    SET status='FAILED', heartbeat_at=?, lease_expires_at=?, message_zh=?
                    WHERE pipeline_run_uid=? AND status='RUNNING'
                    """,
                    (utc_now(), utc_now(), "Writer工作失敗", run_uid),
                )
            raise
        finally:
            connection.close()


def database_status(db_path: Path, migrations_dir: Path) -> dict:
    if not db_path.exists():
        return result(
            "PASS_WITH_WARNINGS",
            "正式運行資料庫尚未建立",
            database_path=str(db_path),
            exists=False,
        )
    migrations = discover_migrations(migrations_dir)
    connection = connect_database(db_path)
    try:
        validate_migration_history(connection, migrations)
        applied = applied_migrations(connection)
        checks = verify_connection(connection)
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
    finally:
        connection.close()
    return result(
        "PASS",
        "資料庫Schema、Migration checksum及完整性檢查通過",
        database_path=str(db_path.resolve()),
        exists=True,
        applied_versions=sorted(applied),
        tables=tables,
        checks=checks,
    )


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P1008 SQLite維運工具")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--migrations", type=Path, default=DEFAULT_MIGRATIONS_DIR)
    parser.add_argument("--backups", type=Path, default=DEFAULT_BACKUP_DIR)
    subparsers = parser.add_subparsers(dest="command", required=True)

    migrate = subparsers.add_parser("migrate")
    migrate.add_argument("--dry-run-only", action="store_true")

    backup = subparsers.add_parser("backup")
    backup.add_argument("--reason", default="OWNER_MANUAL")

    subparsers.add_parser("verify")
    subparsers.add_parser("status")

    restore = subparsers.add_parser("restore-test")
    restore.add_argument("--backup-path", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        if args.command == "migrate":
            output = migrate_database(
                args.db,
                args.migrations,
                args.backups,
                dry_run_only=args.dry_run_only,
            )
        elif args.command == "backup":
            with OsWriterLock(args.db.with_suffix(args.db.suffix + ".writer.lock")):
                connection = connect_database(args.db)
                try:
                    output = create_backup(
                        connection,
                        source_database_path=args.db,
                        backup_root=args.backups,
                        reason=args.reason,
                    )
                finally:
                    connection.close()
        elif args.command == "verify":
            connection = connect_database(args.db)
            try:
                checks = verify_connection(connection)
            finally:
                connection.close()
            output = result("PASS", "SQLite完整性與外鍵檢查完成", checks=checks)
        elif args.command == "status":
            output = database_status(args.db, args.migrations)
        else:
            args.db.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="p1008-restore-test-",
                dir=args.db.parent,
            ) as temp_dir:
                target = Path(temp_dir) / "restored.sqlite3"
                output = restore_backup(args.backup_path, target)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                result("FAIL", str(exc), error_type=type(exc).__name__),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
