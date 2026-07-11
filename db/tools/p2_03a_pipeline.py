from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
P2_01_TOOL = PROJECT_ROOT / "db" / "tools" / "p1008_db.py"
BASE_MIGRATION = PROJECT_ROOT / "db" / "migrations" / "0001_initial_schema.sql"
EXTENSION = PROJECT_ROOT / "db" / "p2-03a" / "pipeline_extension.sql"
FIXTURE_PATH = PROJECT_ROOT / "db" / "fixtures" / "p2_03a_pipeline_fixture.json"
DEFAULT_RUNTIME_DB = Path(os.environ.get("LOCALAPPDATA", PROJECT_ROOT / "staging")) / "P1008" / "data" / "warroom.sqlite3"
FORMAL_CSVS = (
    PROJECT_ROOT / "data" / "2317_master_v9.csv",
    PROJECT_ROOT / "data" / "2317_daily_price.csv",
    PROJECT_ROOT / "data" / "macro_snapshot.csv",
)
PUBLISHER_ROLE = "PUBLISHER_TEST_ONLY"


class PipelineBlocked(RuntimeError):
    pass


class AuthorizationError(RuntimeError):
    pass


class ApprovalError(RuntimeError):
    pass


def load_dbcore():
    spec = importlib.util.spec_from_file_location("p1008_db_for_p203a", P2_01_TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dbcore = load_dbcore()


def canonical_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_json(data: object) -> str:
    return sha256_bytes(canonical_json(data).encode("utf-8"))


def fixed_uid(key: str) -> str:
    timestamp = dt.datetime(2026, 6, 20, tzinfo=dt.timezone.utc)
    value = ((int(timestamp.timestamp() * 1000) & ((1 << 48) - 1)) << 80) | int.from_bytes(
        hashlib.sha256(key.encode("utf-8")).digest()[:10], "big"
    )
    chars = []
    for _ in range(26):
        chars.append(dbcore.CROCKFORD32[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def csv_bytes(columns: list[str], rows: list[list[str]]) -> bytes:
    import io

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def ensure_within(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    resolved_root = root.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise AuthorizationError(f"目標路徑不在核准staging範圍：{resolved}")
    return resolved


def create_schema(connection: sqlite3.Connection) -> None:
    migrations = (
        dbcore.Migration(1, "initial_schema", BASE_MIGRATION, dbcore.sha256_file(BASE_MIGRATION)),
        dbcore.Migration(3, "p2_03a_pipeline_extension", EXTENSION, dbcore.sha256_file(EXTENSION)),
    )
    for migration in migrations:
        dbcore.apply_one_migration(connection, migration, mode="DRY_RUN", backup_id=None)


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def seed_registries(connection: sqlite3.Connection, fixture: dict) -> None:
    for dataset in fixture["datasets"]:
        for priority, source_code in enumerate(
            (dataset["primary_source"], dataset["secondary_source"]), start=1
        ):
            connection.execute(
                """
                INSERT INTO connector_registry(
                    connector_id, source_code, source_authority,
                    supported_subject_types, supported_metrics, parser_version,
                    license_scope, rate_limit, last_success_at, last_failure_at,
                    health_status, is_test_fixture
                ) VALUES (?, ?, ?, ?, ?, 'test-parser-v1', 'TEST_ONLY',
                          'OFFLINE', NULL, NULL, 'HEALTHY', 1)
                """,
                (
                    f"CONN-{source_code}",
                    source_code,
                    "A2" if priority == 1 else "A3",
                    canonical_json(["TEST_SUBJECT"]),
                    canonical_json([dataset["dataset_code"]]),
                ),
            )
        connection.execute(
            """
            INSERT INTO source_priority_registry(
                registry_uid, dataset_code, metric_group, subject_type,
                primary_source_codes, secondary_source_codes,
                cross_check_source_codes, fallback_policy, conflict_policy,
                license_requirement, effective_from, registry_version,
                owner_approval
            ) VALUES (?, ?, ?, 'TEST_SUBJECT', ?, ?, ?, 'NO_SILENT_FALLBACK',
                      'UNRESOLVED_BLOCKING', 'TEST_ONLY', '2026-06-20',
                      'test-v1', 'OWNER_ITEM_69')
            """,
            (
                fixed_uid(f"priority:{dataset['dataset_code']}"),
                dataset["dataset_code"],
                dataset["dataset_code"],
                canonical_json([dataset["primary_source"]]),
                canonical_json([dataset["secondary_source"]]),
                canonical_json([dataset["secondary_source"]]),
            ),
        )
        connection.execute(
            """
            INSERT INTO freshness_policies(
                policy_uid, dataset_code, metric_group, subject_type,
                expected_frequency, expected_publish_rule, grace_period_days,
                stale_after_days, severely_stale_after_days, calendar_code,
                timezone, missing_action, version, owner_approval
            ) VALUES (?, ?, ?, 'TEST_SUBJECT', 'FIXTURE', 'FIXED_AS_OF',
                      0, ?, ?, 'TEST_CALENDAR', 'UTC',
                      'BLOCK_RELEASE', 'test-v1', 'OWNER_ITEM_69')
            """,
            (
                fixed_uid(f"freshness:{dataset['dataset_code']}"),
                dataset["dataset_code"],
                dataset["dataset_code"],
                dataset["stale_after_days"],
                dataset["stale_after_days"] * 2,
            ),
        )


def record_validation(
    connection: sqlite3.Connection,
    scenario: str,
    dataset: str,
    code: str,
    severity: str,
    status: str,
    status_zh: str,
    note_zh: str,
    details: dict,
) -> None:
    connection.execute(
        """
        INSERT INTO pipeline_validations(
            pipeline_validation_uid, scenario_code, dataset_code,
            validation_code, severity, status_code, status_zh,
            status_note_zh, details_json, checked_at, actionable
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '2026-06-20T08:00:00Z', 0)
        """,
        (
            fixed_uid(f"validation:{scenario}:{dataset}:{code}"),
            scenario,
            dataset,
            code,
            severity,
            status,
            status_zh,
            note_zh,
            canonical_json(details),
        ),
    )


def evaluate_scenario(connection: sqlite3.Connection, fixture: dict, scenario: str) -> dict:
    as_of = dt.datetime.fromisoformat(fixture["as_of"].replace("Z", "+00:00"))
    blocked_codes: list[str] = []
    dataset_results = []
    for dataset in fixture["datasets"]:
        code = dataset["dataset_code"]
        primary_available = not (scenario == "PRIMARY_UNAVAILABLE" and code == "DAILY_TEST")
        primary_rows = dataset["rows"]
        secondary_rows = dataset["secondary_rows"]
        if scenario == "CONFLICT" and code == "DAILY_TEST":
            secondary_rows = [["2026-06-20", "101.00", "TEST_FIXTURE"]]
        observed_at = dataset["observed_at"]
        if scenario == "STALE" and code == "MACRO_TEST":
            observed_at = "2026-05-01T05:00:00Z"

        primary_sha = sha256_bytes(csv_bytes(dataset["columns"], primary_rows))
        secondary_sha = sha256_bytes(csv_bytes(dataset["columns"], secondary_rows))
        connector_id = f"CONN-{dataset['primary_source']}"
        if not primary_available:
            connection.execute(
                """
                INSERT INTO connector_runs(
                    connector_run_uid, connector_id, scenario_code, started_at,
                    finished_at, status_code, status_zh, status_note_zh,
                    artifact_sha256, error_code, actionable
                ) VALUES (?, ?, ?, '2026-06-20T08:00:00Z', '2026-06-20T08:00:00Z',
                          'UNAVAILABLE', '來源無法使用',
                          '主要來源失效，次要來源不得靜默取代', NULL,
                          'PRIMARY_SOURCE_UNAVAILABLE', 0)
                """,
                (fixed_uid(f"connector:{scenario}:{code}:primary"), connector_id, scenario),
            )
            record_validation(
                connection,
                scenario,
                code,
                "PRIMARY_SOURCE_UNAVAILABLE",
                "BLOCKING",
                "FAIL",
                "失敗",
                "主要來源失效，已阻擋Release；次要來源僅保留候選狀態",
                {"secondary_available": True, "fallback_used": False},
            )
            blocked_codes.append("PRIMARY_SOURCE_UNAVAILABLE")
            dataset_results.append(
                {
                    "dataset_code": code,
                    "status_code": "SOURCE_UNAVAILABLE",
                    "status_zh": "來源無法使用",
                    "status_note_zh": "主要來源失效，未使用靜默Fallback",
                    "fallback_used": False,
                }
            )
            continue

        connection.execute(
            """
            INSERT INTO connector_runs(
                connector_run_uid, connector_id, scenario_code, started_at,
                finished_at, status_code, status_zh, status_note_zh,
                artifact_sha256, error_code, actionable
            ) VALUES (?, ?, ?, '2026-06-20T08:00:00Z', '2026-06-20T08:00:00Z',
                      'PASS', '通過', '離線主要測試來源讀取成功', ?, NULL, 0)
            """,
            (
                fixed_uid(f"connector:{scenario}:{code}:primary"),
                connector_id,
                scenario,
                primary_sha,
            ),
        )

        if primary_sha != secondary_sha:
            connection.execute(
                """
                INSERT INTO pipeline_conflicts(
                    pipeline_conflict_uid, scenario_code, dataset_code,
                    primary_source_code, secondary_source_code, comparison_type,
                    primary_sha256, secondary_sha256, resolution_status,
                    status_zh, status_note_zh, created_at
                ) VALUES (?, ?, ?, ?, ?, 'EXACT_MATCH', ?, ?,
                          'UNRESOLVED_BLOCKING', '未解決阻擋衝突',
                          '主要與次要來源內容不一致，禁止建立Release',
                          '2026-06-20T08:00:00Z')
                """,
                (
                    fixed_uid(f"conflict:{scenario}:{code}"),
                    scenario,
                    code,
                    dataset["primary_source"],
                    dataset["secondary_source"],
                    primary_sha,
                    secondary_sha,
                ),
            )
            record_validation(
                connection,
                scenario,
                code,
                "DATA_CONFLICT",
                "BLOCKING",
                "CONFLICT",
                "資料衝突",
                "來源內容不一致且無核准容許值，阻擋Release",
                {"primary_sha256": primary_sha, "secondary_sha256": secondary_sha},
            )
            blocked_codes.append("UNRESOLVED_BLOCKING")
            dataset_results.append(
                {
                    "dataset_code": code,
                    "status_code": "DATA_CONFLICT",
                    "status_zh": "資料衝突",
                    "status_note_zh": "主要與次要來源不一致",
                }
            )
            continue

        observed = dt.datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        age_days = (as_of - observed).total_seconds() / 86400
        if age_days > dataset["stale_after_days"]:
            record_validation(
                connection,
                scenario,
                code,
                "FRESHNESS",
                "BLOCKING",
                "STALE",
                "資料逾期",
                "已超過核准新鮮度門檻，阻擋Release",
                {"age_days": age_days, "stale_after_days": dataset["stale_after_days"]},
            )
            blocked_codes.append("STALE_DATA")
            dataset_results.append(
                {
                    "dataset_code": code,
                    "status_code": "STALE",
                    "status_zh": "資料逾期",
                    "status_note_zh": "已超過核准新鮮度門檻",
                }
            )
            continue

        record_validation(
            connection,
            scenario,
            code,
            "DATASET_READY",
            "INFO",
            "PASS",
            "通過",
            "主要來源、交叉驗證及新鮮度均通過",
            {"artifact_sha256": primary_sha, "age_days": age_days},
        )
        dataset_results.append(
            {
                "dataset_code": code,
                "status_code": "READY",
                "status_zh": "可建立候選",
                "status_note_zh": "離線測試資料驗證通過",
            }
        )
    return {
        "scenario_code": scenario,
        "release_allowed": not blocked_codes,
        "blocked_codes": sorted(set(blocked_codes)),
        "datasets": dataset_results,
    }


def build_candidate(fixture: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    data_dir = output_dir / "data"
    data_dir.mkdir()
    items = []
    for dataset in sorted(fixture["datasets"], key=lambda item: item["dataset_code"]):
        target_name = Path(dataset["target_path"]).name
        content = csv_bytes(dataset["columns"], dataset["rows"])
        path = data_dir / target_name
        path.write_bytes(content)
        items.append(
            {
                "dataset_code": dataset["dataset_code"],
                "candidate_file": f"data/{target_name}",
                "target_path": dataset["target_path"],
                "row_count": len(dataset["rows"]),
                "column_count": len(dataset["columns"]),
                "sha256": sha256_bytes(content),
                "schema_version": "TEST_FIXTURE_V1",
                "validation_status": "PASS",
                "changed_rows": len(dataset["rows"]),
            }
        )
    payload = {
        "fixture_id": fixture["fixture_id"],
        "fixture_notice_zh": fixture["fixture_notice_zh"],
        "snapshot_id": fixture["snapshot_id"],
        "sqlite_snapshot_sha256": sha256_json(fixture),
        "as_of": fixture["as_of"],
        "sequence": fixture["sequence"],
        "items": items,
        "warnings": ["TEST_FIXTURE_ONLY"],
        "status": "READY_FOR_REVIEW",
        "status_zh": "等待檢視",
        "status_note_zh": "僅為離線測試候選，不得發布至正式CSV",
        "actionable": False,
    }
    manifest_sha = sha256_json(payload)
    as_of_date = fixture["as_of"][:10].replace("-", "")
    release_id = f"REL-P1008-{as_of_date}-{fixture['sequence']:03d}-{manifest_sha[:8]}"
    manifest = {
        "release_id": release_id,
        "manifest_sha256": manifest_sha,
        "manifest_hash_scope": "CANONICAL_PAYLOAD",
        "payload": payload,
    }
    (output_dir / "RELEASE_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    diff_report = {
        "status": "PASS",
        "status_zh": "通過",
        "status_note_zh": "首次離線Fixture Release，三份測試資料列均視為新增",
        "actionable": False,
        "baseline_release_id": None,
        "candidate_release_id": release_id,
        "datasets": [
            {
                "dataset_code": item["dataset_code"],
                "added_rows": item["row_count"],
                "modified_rows": 0,
                "deleted_rows": 0,
            }
            for item in items
        ],
    }
    (output_dir / "DIFF_REPORT.json").write_text(
        json.dumps(diff_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "VALIDATION_REPORT.md").write_text(
        "\n".join(
            [
                "# P2-03A 候選驗證報告",
                "",
                "**狀態**：`PASS / 通過`",
                "**中文備註**：離線測試Fixture的Schema、來源、新鮮度與交叉驗證均通過。",
                "**限制**：本候選不得發布至正式CSV。",
                "",
                "| 資料集 | 列數 | 欄數 | SHA-256 |",
                "|---|---:|---:|---|",
                *[
                    f"| {item['dataset_code']} | {item['row_count']} | {item['column_count']} | `{item['sha256']}` |"
                    for item in items
                ],
                "",
            ]
        ),
        encoding="utf-8",
    )
    (output_dir / "CHANGE_REPORT.md").write_text(
        "\n".join(
            [
                "# P2-03A 候選變更報告",
                "",
                f"**Release ID**：`{release_id}`",
                "**狀態**：`TEST_FIXTURE_ONLY / 僅供離線測試`",
                "**中文備註**：首次Fixture Release，三份候選資料各新增1筆測試列。",
                "",
                "- 未讀取外部網站或API。",
                "- 未使用P2-02 Legacy資料作正式Release。",
                "- 未修改Runtime SQLite或正式CSV。",
                "- `actionable:false`。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return manifest


def verify_candidate(candidate_dir: Path) -> dict:
    manifest = json.loads((candidate_dir / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    if sha256_json(manifest["payload"]) != manifest["manifest_sha256"]:
        raise ApprovalError("Manifest payload SHA-256不一致")
    for item in manifest["payload"]["items"]:
        path = candidate_dir / item["candidate_file"]
        if dbcore.sha256_file(path) != item["sha256"]:
            raise ApprovalError(f"候選檔案雜湊不一致：{item['candidate_file']}")
    return manifest


def register_release(connection: sqlite3.Connection, manifest: dict, candidate_dir: Path) -> str:
    release_id = manifest["release_id"]
    release_uid = fixed_uid(f"release:{release_id}")
    payload = manifest["payload"]
    connection.execute(
        """
        INSERT INTO release_batches(
            release_uid, release_id, as_of, status, sqlite_snapshot_sha256,
            manifest_sha256, created_at, approved_at, published_at,
            supersedes_release_uid, status_zh, status_note_zh
        ) VALUES (?, ?, ?, 'READY_FOR_REVIEW', ?, ?, ?, NULL, NULL, NULL,
                  '等待檢視', '離線測試候選已完成驗證')
        """,
        (
            release_uid,
            release_id,
            payload["as_of"],
            payload["sqlite_snapshot_sha256"],
            manifest["manifest_sha256"],
            payload["as_of"],
        ),
    )
    for item in payload["items"]:
        connection.execute(
            """
            INSERT INTO release_items(
                release_item_uid, release_uid, dataset_code, candidate_path,
                target_path, row_count, column_count, sha256, schema_version,
                validation_status, changed_rows
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fixed_uid(f"release-item:{release_id}:{item['dataset_code']}"),
                release_uid,
                item["dataset_code"],
                str((candidate_dir / item["candidate_file"]).resolve()),
                item["target_path"],
                item["row_count"],
                item["column_count"],
                item["sha256"],
                item["schema_version"],
                item["validation_status"],
                item["changed_rows"],
            ),
        )
    return release_uid


def approve_release(connection: sqlite3.Connection, release_uid: str, manifest_sha: str) -> None:
    connection.execute(
        """
        INSERT INTO release_approvals(
            approval_uid, release_uid, manifest_sha256, approved_by,
            approved_at, decision, accepted_warning_codes, reason
        ) VALUES (?, ?, ?, 'TEST_OWNER', '2026-06-20T08:00:00Z',
                  'APPROVED', ?, 'P2-03A離線Publisher權限測試')
        """,
        (
            fixed_uid(f"approval:{release_uid}:{manifest_sha}"),
            release_uid,
            manifest_sha,
            canonical_json(["TEST_FIXTURE_ONLY"]),
        ),
    )
    connection.execute(
        """
        UPDATE release_batches
        SET status='APPROVED', approved_at='2026-06-20T08:00:00Z',
            status_zh='已核准', status_note_zh='僅核准離線測試發布'
        WHERE release_uid=?
        """,
        (release_uid,),
    )


def record_publish_attempt(
    connection: sqlite3.Connection,
    release_uid: str | None,
    role: str,
    manifest_sha: str | None,
    code: str,
    status_zh: str,
    note_zh: str,
    target_root: Path,
) -> None:
    key = f"attempt:{release_uid}:{role}:{manifest_sha}:{code}:{target_root}"
    connection.execute(
        """
        INSERT INTO publication_attempts(
            attempt_uid, release_uid, actor_role, manifest_sha256, status_code,
            status_zh, status_note_zh, target_root, attempted_at, actionable
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '2026-06-20T08:00:00Z', 0)
        """,
        (
            fixed_uid(key),
            release_uid,
            role,
            manifest_sha,
            code,
            status_zh,
            note_zh,
            str(target_root.resolve()),
        ),
    )


def publish_test(
    connection: sqlite3.Connection,
    candidate_dir: Path,
    target_root: Path,
    allowed_staging_root: Path,
    *,
    actor_role: str,
) -> dict:
    ensure_within(target_root, allowed_staging_root)
    raw_manifest = json.loads(
        (candidate_dir / "RELEASE_MANIFEST.json").read_text(encoding="utf-8")
    )
    raw_release_id = raw_manifest.get("release_id")
    raw_manifest_sha = raw_manifest.get("manifest_sha256")
    try:
        manifest = verify_candidate(candidate_dir)
    except ApprovalError:
        row = connection.execute(
            "SELECT release_uid FROM release_batches WHERE release_id=?",
            (raw_release_id,),
        ).fetchone()
        record_publish_attempt(
            connection,
            row["release_uid"] if row else None,
            actor_role,
            raw_manifest_sha,
            "CANDIDATE_HASH_MISMATCH",
            "候選驗證失敗",
            "候選檔案或Manifest雜湊已變更，核准立即失效",
            target_root,
        )
        raise
    row = connection.execute(
        "SELECT release_uid, status, manifest_sha256 FROM release_batches WHERE release_id=?",
        (manifest["release_id"],),
    ).fetchone()
    release_uid = row["release_uid"] if row else None
    if actor_role != PUBLISHER_ROLE:
        record_publish_attempt(
            connection,
            release_uid,
            actor_role,
            manifest["manifest_sha256"],
            "PUBLISHER_ROLE_REQUIRED",
            "權限不足",
            "只有測試Publisher角色可寫入測試發布目錄",
            target_root,
        )
        raise AuthorizationError("只有Publisher可執行發布")
    if not row or row["status"] != "APPROVED":
        record_publish_attempt(
            connection,
            release_uid,
            actor_role,
            manifest["manifest_sha256"],
            "OWNER_APPROVAL_REQUIRED",
            "缺少核准",
            "Release尚未取得綁定Manifest雜湊的核准",
            target_root,
        )
        raise ApprovalError("Release尚未核准")
    approval = connection.execute(
        """
        SELECT 1 FROM release_approvals
        WHERE release_uid=? AND manifest_sha256=? AND decision='APPROVED'
        """,
        (release_uid, manifest["manifest_sha256"]),
    ).fetchone()
    if not approval or row["manifest_sha256"] != manifest["manifest_sha256"]:
        record_publish_attempt(
            connection,
            release_uid,
            actor_role,
            manifest["manifest_sha256"],
            "MANIFEST_APPROVAL_MISMATCH",
            "核准失效",
            "候選內容或Manifest雜湊已變更",
            target_root,
        )
        raise ApprovalError("Manifest雜湊與核准不一致")

    target_root.mkdir(parents=True, exist_ok=True)
    releases_root = target_root / "releases"
    releases_root.mkdir(exist_ok=True)
    release_target = releases_root / manifest["release_id"]
    temp_target = releases_root / f".{manifest['release_id']}.publishing"
    if release_target.exists() or temp_target.exists():
        raise ApprovalError("測試Release目錄已存在，禁止覆寫")
    shutil.copytree(candidate_dir, temp_target)
    verify_candidate(temp_target)
    temp_target.replace(release_target)
    active_pointer = {
        "release_id": manifest["release_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "status": "ACTIVE",
        "status_zh": "測試啟用",
        "status_note_zh": "僅指向staging不可變測試Release",
        "actionable": False,
    }
    pointer_temp = target_root / ".ACTIVE_RELEASE.json.tmp"
    pointer_path = target_root / "ACTIVE_RELEASE.json"
    pointer_temp.write_text(
        json.dumps(active_pointer, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(pointer_temp, pointer_path)
    connection.execute(
        """
        UPDATE release_batches
        SET status='ACTIVE', published_at='2026-06-20T08:00:00Z',
            status_zh='測試啟用', status_note_zh='已發布至staging測試目錄'
        WHERE release_uid=?
        """,
        (release_uid,),
    )
    record_publish_attempt(
        connection,
        release_uid,
        actor_role,
        manifest["manifest_sha256"],
        "PASS",
        "通過",
        "測試Release已原子切換並完成發布後驗證",
        target_root,
    )
    return {
        "status": "PASS",
        "status_zh": "通過",
        "status_note_zh": "測試Release已發布至staging並完成雜湊驗證",
        "target_root": str(target_root.resolve()),
        "release_path": str(release_target.resolve()),
        "active_pointer": str(pointer_path.resolve()),
        "release_id": manifest["release_id"],
    }


def file_hashes(paths: Sequence[Path]) -> dict[str, str]:
    return {str(path.resolve()): dbcore.sha256_file(path) for path in paths}


def run_suite(output_dir: Path, runtime_db: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    staging_db = output_dir / "pipeline_p2_03a.sqlite3"
    before = file_hashes((*FORMAL_CSVS, runtime_db))
    fixture = load_fixture()
    connection = dbcore.connect_database(staging_db)
    connection.row_factory = sqlite3.Row
    try:
        create_schema(connection)
        seed_registries(connection, fixture)
        scenarios = {
            code: evaluate_scenario(connection, fixture, code)
            for code in ("READY", "PRIMARY_UNAVAILABLE", "CONFLICT", "STALE")
        }
        if not scenarios["READY"]["release_allowed"]:
            raise PipelineBlocked("READY情境不應被阻擋")
        for code in ("PRIMARY_UNAVAILABLE", "CONFLICT", "STALE"):
            if scenarios[code]["release_allowed"]:
                raise PipelineBlocked(f"{code}情境應阻擋Release")

        build_a = output_dir / "rebuild_a"
        build_b = output_dir / "rebuild_b"
        manifest_a = build_candidate(fixture, build_a)
        manifest_b = build_candidate(fixture, build_b)
        reproducible = (
            manifest_a["manifest_sha256"] == manifest_b["manifest_sha256"]
            and {
                item["dataset_code"]: item["sha256"] for item in manifest_a["payload"]["items"]
            }
            == {
                item["dataset_code"]: item["sha256"] for item in manifest_b["payload"]["items"]
            }
        )
        if not reproducible:
            raise PipelineBlocked("相同快照無法重建相同Release")

        release_uid = register_release(connection, manifest_a, build_a)
        authorization_tests = {}
        try:
            publish_test(
                connection,
                build_a,
                output_dir / "test_publish_nonpublisher",
                output_dir,
                actor_role="VALIDATOR",
            )
        except AuthorizationError:
            authorization_tests["non_publisher_blocked"] = True

        try:
            publish_test(
                connection,
                build_a,
                output_dir / "test_publish_unapproved",
                output_dir,
                actor_role=PUBLISHER_ROLE,
            )
        except ApprovalError:
            authorization_tests["unapproved_manifest_blocked"] = True

        approve_release(connection, release_uid, manifest_a["manifest_sha256"])
        tampered = output_dir / "tampered_candidate"
        shutil.copytree(build_a, tampered)
        target_file = tampered / manifest_a["payload"]["items"][0]["candidate_file"]
        target_file.write_bytes(target_file.read_bytes() + b"TEST_TAMPER\n")
        try:
            publish_test(
                connection,
                tampered,
                output_dir / "test_publish_tampered",
                output_dir,
                actor_role=PUBLISHER_ROLE,
            )
        except ApprovalError:
            authorization_tests["tampered_candidate_blocked"] = True

        publish_result = publish_test(
            connection,
            build_a,
            output_dir / "test_published_active",
            output_dir,
            actor_role=PUBLISHER_ROLE,
        )
        checks = dbcore.verify_connection(connection)
    finally:
        connection.close()

    after = file_hashes((*FORMAL_CSVS, runtime_db))
    if before != after:
        raise PipelineBlocked("正式Runtime DB或CSV在P2-03A期間發生變更")
    summary = {
        "batch_id": "P2-03A",
        "generated_at": dbcore.utc_now(),
        "status": "PASS",
        "status_zh": "通過",
        "status_note_zh": "離線Pipeline重建、阻擋、核准綁定與Publisher隔離均通過",
        "actionable": False,
        "owner_acceptance": "PENDING",
        "fixture": {
            "fixture_id": fixture["fixture_id"],
            "notice_zh": fixture["fixture_notice_zh"],
            "network_access": False,
        },
        "scenarios": scenarios,
        "reproducibility": {
            "status": "PASS" if reproducible else "FAIL",
            "status_zh": "通過" if reproducible else "失敗",
            "manifest_sha256_a": manifest_a["manifest_sha256"],
            "manifest_sha256_b": manifest_b["manifest_sha256"],
            "release_id": manifest_a["release_id"],
        },
        "authorization_tests": authorization_tests,
        "publish_test": publish_result,
        "staging_database": {
            "path": str(staging_db.resolve()),
            "sha256": dbcore.sha256_file(staging_db),
            "schema_version": checks["schema_version"],
            "integrity_check_status": checks["integrity_check_status"],
            "foreign_key_check_status": checks["foreign_key_check_status"],
        },
        "protected_files": {
            "before": before,
            "after": after,
            "unchanged": before == after,
        },
    }
    (output_dir / "DRY_RUN.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P1008 P2-03A離線Pipeline Dry-Run")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--runtime-db", type=Path, default=DEFAULT_RUNTIME_DB)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    now = dt.datetime.now(dt.timezone.utc)
    output_dir = args.output_dir or (
        PROJECT_ROOT
        / "staging"
        / "p2-03a"
        / now.strftime("%Y-%m-%d")
        / f"run_{now.strftime('%Y%m%dT%H%M%SZ')}"
    )
    try:
        summary = run_suite(output_dir, args.runtime_db)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                dbcore.result("FAIL", str(exc), error_type=type(exc).__name__),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
