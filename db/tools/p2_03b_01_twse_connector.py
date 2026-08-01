from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
P2_01_TOOL = PROJECT_ROOT / "db" / "tools" / "p1008_db.py"
BASE_MIGRATION = PROJECT_ROOT / "db" / "migrations" / "0001_initial_schema.sql"
EXTENSION = PROJECT_ROOT / "db" / "p2-03b-01" / "twse_connector_extension.sql"
SWAGGER_URL = "https://openapi.twse.com.tw/v1/swagger.json"
ENDPOINT_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
ENDPOINT_PATH = "/exchangeReport/STOCK_DAY_ALL"
ALLOWED_HOST = "openapi.twse.com.tw"
CONNECTOR_ID = "TWSE_STOCK_DAY_ALL_2317_V1"
SOURCE_CODE = "TWSE_OPENAPI_STOCK_DAY_ALL"
PARSER_VERSION = "p2-03b-01.1"
DEFAULT_RUNTIME_DB = (
    Path(os.environ.get("LOCALAPPDATA", PROJECT_ROOT / "staging"))
    / "P1008"
    / "data"
    / "warroom.sqlite3"
)
FORMAL_CSVS = (
    PROJECT_ROOT / "data" / "2317_master_v9.csv",
    PROJECT_ROOT / "data" / "2317_daily_price.csv",
    PROJECT_ROOT / "data" / "macro_snapshot.csv",
)


class ConnectorError(RuntimeError):
    pass


class PrimarySourceUnavailable(ConnectorError):
    pass


class ContractError(ConnectorError):
    pass


class DataValidationError(ConnectorError):
    pass


@dataclass(frozen=True)
class HttpResult:
    url: str
    status: int
    mime_type: str
    headers: dict[str, str]
    body: bytes


def load_dbcore():
    spec = importlib.util.spec_from_file_location("p1008_db_for_twse", P2_01_TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dbcore = load_dbcore()


def utc_now() -> str:
    return dbcore.utc_now()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def canonical_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def deterministic_ulid(timestamp: dt.datetime, key: str) -> str:
    value = ((int(timestamp.timestamp() * 1000) & ((1 << 48) - 1)) << 80) | int.from_bytes(
        hashlib.sha256(key.encode("utf-8")).digest()[:10], "big"
    )
    chars = []
    for _ in range(26):
        chars.append(dbcore.CROCKFORD32[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise ContractError(f"不允許的Connector URL：{url}")


def fetch_url(url: str, timeout: int = 30) -> HttpResult:
    validate_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "P1008-TWSE-Connector-DryRun/1.0",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            return HttpResult(
                url=url,
                status=int(response.status),
                mime_type=response.headers.get_content_type(),
                headers={key: value for key, value in response.headers.items()},
                body=body,
            )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PrimarySourceUnavailable(f"TWSE主要來源無法使用：{exc}") from exc


def parse_json_bytes(body: bytes, label: str):
    try:
        return json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataValidationError(f"{label}不是有效UTF-8 JSON") from exc


def extract_contract(swagger: dict) -> dict:
    try:
        operation = swagger["paths"][ENDPOINT_PATH]["get"]
        schema = operation["responses"]["200"]["schema"]
        properties = schema["properties"]
    except (KeyError, TypeError) as exc:
        raise ContractError("TWSE Swagger缺少STOCK_DAY_ALL 200回應Schema") from exc
    fields = list(properties)
    if not fields:
        raise ContractError("TWSE Swagger欄位契約為空")
    return {
        "summary": operation.get("summary", ""),
        "documented_top_level_shape": schema.get("type", "UNKNOWN").upper(),
        "fields": fields,
        "field_descriptions": {
            field: properties[field].get("description", "") for field in fields
        },
    }


def roc_date_to_iso(value: str) -> str:
    if not re.fullmatch(r"\d{7}", value):
        raise DataValidationError(f"TWSE日期格式錯誤：{value}")
    year = int(value[:3]) + 1911
    month = int(value[3:5])
    day = int(value[5:7])
    return dt.date(year, month, day).isoformat()


def normalize_decimal(value: str) -> str:
    candidate = value.strip().replace(",", "")
    try:
        number = Decimal(candidate)
    except InvalidOperation as exc:
        raise DataValidationError(f"收盤價不是有效Decimal：{value}") from exc
    if not number.is_finite() or number <= 0:
        raise DataValidationError(f"收盤價必須為正數：{value}")
    normalized = format(number, "f").rstrip("0").rstrip(".")
    return normalized or "0"


def validate_response(payload, contract: dict) -> tuple[dict, list[str]]:
    if not isinstance(payload, list):
        raise ContractError("TWSE實際回應頂層不是陣列")
    selected = [row for row in payload if isinstance(row, dict) and row.get("Code") == "2317"]
    if len(selected) != 1:
        raise DataValidationError(
            f"TWSE回應中Code=2317筆數應為1，實際為{len(selected)}"
        )
    row = selected[0]
    expected = contract["fields"]
    if list(row) != expected:
        raise ContractError(
            f"2317欄位與Swagger不一致：actual={list(row)}, expected={expected}"
        )
    warnings = []
    if contract["documented_top_level_shape"] != "ARRAY":
        warnings.append("SWAGGER_RESPONSE_SHAPE_MISMATCH")
    return row, warnings


def create_schema(connection: sqlite3.Connection) -> None:
    migrations = (
        dbcore.Migration(1, "initial_schema", BASE_MIGRATION, dbcore.sha256_file(BASE_MIGRATION)),
        dbcore.Migration(4, "twse_connector_extension", EXTENSION, dbcore.sha256_file(EXTENSION)),
    )
    for migration in migrations:
        dbcore.apply_one_migration(connection, migration, mode="DRY_RUN", backup_id=None)


def protected_hashes(runtime_db: Path) -> dict[str, str]:
    return {
        str(path.resolve()): dbcore.sha256_file(path)
        for path in (*FORMAL_CSVS, runtime_db)
    }


def save_raw(output_dir: Path, name: str, result: HttpResult, retrieved_at: str) -> dict:
    raw_dir = output_dir / "raw" / "twse"
    raw_dir.mkdir(parents=True, exist_ok=True)
    body_path = raw_dir / name
    body_path.write_bytes(result.body)
    metadata = {
        "url": result.url,
        "retrieved_at": retrieved_at,
        "http_status": result.status,
        "mime_type": result.mime_type,
        "headers": result.headers,
        "sha256": sha256_bytes(result.body),
        "local_path": str(body_path.resolve()),
        "status": "RAW_ARTIFACT",
        "status_zh": "原始證據",
        "status_note_zh": "未修改的TWSE官方HTTPS回應",
        "actionable": False,
    }
    (raw_dir / f"{name}.metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return metadata


def insert_candidate(
    connection: sqlite3.Connection,
    row: dict,
    warnings: list[str],
    endpoint_meta: dict,
    swagger_meta: dict,
    contract: dict,
    retrieved_at: str,
) -> dict:
    date_iso = roc_date_to_iso(row["Date"])
    close = normalize_decimal(row["ClosingPrice"])
    timestamp = dt.datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    created_at = retrieved_at
    legal_uid = deterministic_ulid(timestamp, "LEGAL_ENTITY:HON_HAI_PRECISION_INDUSTRY")
    instrument_uid = deterministic_ulid(timestamp, "INSTRUMENT:HON_HAI_COMMON_EQUITY")
    listing_uid = deterministic_ulid(timestamp, "LISTING:TWSE:2317")
    metric_uid = deterministic_ulid(timestamp, "METRIC:TWSE_DAILY_CLOSE")
    source_uid = deterministic_ulid(timestamp, f"SOURCE:{SOURCE_CODE}")
    artifact_uid = deterministic_ulid(timestamp, f"ARTIFACT:{endpoint_meta['sha256']}")
    observation_uid = deterministic_ulid(
        timestamp, f"OBSERVATION:TWSE:2317:CLOSE:{date_iso}:{close}"
    )
    row_sha = sha256_bytes(canonical_json(row).encode("utf-8"))
    evidence_hash = sha256_bytes(
        canonical_json(
            {
                "artifact_sha256": endpoint_meta["sha256"],
                "code": row["Code"],
                "date": row["Date"],
                "closing_price": row["ClosingPrice"],
            }
        ).encode("utf-8")
    )
    evidence_id = (
        f"EVD-TWSE-TWSE_2317-CLOSE-{date_iso.replace('-', '')}-R01-{evidence_hash[:8]}"
    )
    evidence_uid = deterministic_ulid(timestamp, f"EVIDENCE:{evidence_id}")
    execution_uid = deterministic_ulid(timestamp, f"EXECUTION:{endpoint_meta['sha256']}")

    connection.execute(
        """
        INSERT INTO subjects(
            subject_uid, subject_type, canonical_key, name, ticker, market,
            isin, cik, currency, parent_subject_uid, status, created_at, updated_at
        ) VALUES (?, 'COMPANY', 'LEGAL_ENTITY:HON_HAI_PRECISION_INDUSTRY',
                  '鴻海精密工業股份有限公司', NULL, NULL, NULL, NULL, NULL,
                  NULL, 'ACTIVE', ?, ?)
        """,
        (legal_uid, created_at, created_at),
    )
    connection.execute(
        """
        INSERT INTO subjects(
            subject_uid, subject_type, canonical_key, name, ticker, market,
            isin, cik, currency, parent_subject_uid, status, created_at, updated_at
        ) VALUES (?, 'SECURITY', 'INSTRUMENT:HON_HAI_COMMON_EQUITY',
                  '鴻海普通股', NULL, NULL, NULL, NULL, NULL, ?,
                  'ACTIVE', ?, ?)
        """,
        (instrument_uid, legal_uid, created_at, created_at),
    )
    connection.execute(
        """
        INSERT INTO subjects(
            subject_uid, subject_type, canonical_key, name, ticker, market,
            isin, cik, currency, parent_subject_uid, status, created_at, updated_at
        ) VALUES (?, 'SECURITY', 'LISTING:TWSE:2317',
                  '鴻海普通股臺灣證券交易所掛牌', '2317', 'TWSE',
                  NULL, NULL, 'TWD', ?, 'ACTIVE', ?, ?)
        """,
        (listing_uid, instrument_uid, created_at, created_at),
    )
    connection.execute(
        """
        INSERT INTO metric_definitions(
            metric_uid, metric_code, name_zh, frequency, value_type,
            canonical_unit, is_derived, formula_version, required_for_report,
            model_usage, created_at, updated_at
        ) VALUES (?, 'TWSE_DAILY_CLOSE', 'TWSE每日收盤價', 'DAILY', 'DECIMAL',
                  'TWD_PER_SHARE', 0, NULL, 0, 'OBSERVATION_ONLY', ?, ?)
        """,
        (metric_uid, created_at, created_at),
    )
    connection.execute(
        """
        INSERT INTO sources(
            source_uid, source_code, source_name, source_type, official_url,
            quality_level, license_scope, retrieval_method, enabled,
            created_at, updated_at
        ) VALUES (?, ?, '臺灣證券交易所OpenAPI', 'OFFICIAL_EXCHANGE',
                  ?, 'A1', 'OWNER_INTERNAL_DRY_RUN_REDISTRIBUTION_NOT_APPROVED',
                  'HTTPS_GET_MANUAL_SINGLE_RUN', 1, ?, ?)
        """,
        (source_uid, SOURCE_CODE, ENDPOINT_URL, created_at, created_at),
    )
    connection.execute(
        """
        INSERT INTO raw_artifacts(
            artifact_uid, source_uid, retrieved_at, source_url, local_path,
            mime_type, sha256, http_status, parser_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            artifact_uid,
            source_uid,
            retrieved_at,
            ENDPOINT_URL,
            endpoint_meta["local_path"],
            endpoint_meta["mime_type"],
            endpoint_meta["sha256"],
            endpoint_meta["http_status"],
            PARSER_VERSION,
            created_at,
        ),
    )
    connection.execute(
        """
        INSERT INTO connector_contracts(
            connector_id, source_code, source_authority, evidence_level,
            endpoint_url, swagger_url, swagger_sha256, endpoint_path,
            expected_fields_json, actual_top_level_shape,
            documented_top_level_shape, parser_version, license_scope,
            fallback_policy, status, owner_approval
        ) VALUES (?, ?, 'A1', 'L1', ?, ?, ?, ?, ?, 'ARRAY', ?, ?,
                  'OWNER_INTERNAL_DRY_RUN_REDISTRIBUTION_NOT_APPROVED',
                  'NO_FALLBACK', 'ACTIVE_DRY_RUN', 'OWNER_ITEM_71')
        """,
        (
            CONNECTOR_ID,
            SOURCE_CODE,
            ENDPOINT_URL,
            SWAGGER_URL,
            swagger_meta["sha256"],
            ENDPOINT_PATH,
            canonical_json(contract["fields"]),
            contract["documented_top_level_shape"],
            PARSER_VERSION,
        ),
    )
    all_warnings = warnings + [
        "PUBLICATION_TIME_MISSING",
        "SESSION_CALENDAR_NOT_INTEGRATED",
    ]
    connection.execute(
        """
        INSERT INTO observations(
            observation_uid, subject_uid, metric_uid, value_decimal, value_text,
            unit, period_start, period_end, published_at, effective_at,
            retrieved_at, source_uid, artifact_uid, revision,
            validation_status, support_level, supersedes_observation_uid,
            created_at
        ) VALUES (?, ?, ?, ?, NULL, 'TWD_PER_SHARE', ?, ?, ?, ?, ?, ?, ?, 1,
                  'PASS_WITH_WARNINGS', 'L1', NULL, ?)
        """,
        (
            observation_uid,
            listing_uid,
            metric_uid,
            close,
            date_iso,
            date_iso,
            retrieved_at,
            retrieved_at,
            retrieved_at,
            source_uid,
            artifact_uid,
            created_at,
        ),
    )
    connection.execute(
        """
        INSERT INTO observation_evidence(
            evidence_uid, evidence_id, observation_uid, artifact_uid,
            source_row_sha256, source_code_value, source_date_value,
            raw_value, normalized_value, validation_status, model_usage,
            warnings_json, message_zh, created_at
        ) VALUES (?, ?, ?, ?, ?, '2317', ?, ?, ?,
                  'PASS_WITH_WARNINGS', 'OBSERVATION_ONLY', ?,
                  'TWSE官方收盤價候選；缺少發布時分秒及核准交易日曆，暫不更新PB', ?)
        """,
        (
            evidence_uid,
            evidence_id,
            observation_uid,
            artifact_uid,
            row_sha,
            row["Date"],
            row["ClosingPrice"],
            close,
            canonical_json(all_warnings),
            created_at,
        ),
    )
    connection.execute(
        """
        INSERT INTO connector_executions(
            execution_uid, connector_id, started_at, finished_at, http_status,
            mime_type, raw_sha256, response_count, selected_count, status_code,
            status_zh, status_note_zh, error_code, fallback_used, actionable
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'PASS_WITH_WARNINGS',
                  '通過但有警告',
                  '已取得2317官方收盤價；因時間與交易日曆尚未完整，僅建立候選Observation',
                  NULL, 0, 0)
        """,
        (
            execution_uid,
            CONNECTOR_ID,
            retrieved_at,
            retrieved_at,
            endpoint_meta["http_status"],
            endpoint_meta["mime_type"],
            endpoint_meta["sha256"],
            endpoint_meta["response_count"],
        ),
    )
    for code, note in (
        (
            "SWAGGER_RESPONSE_SHAPE_MISMATCH",
            "Swagger描述單一物件，實際回應為陣列；已逐筆使用Swagger物件欄位驗證",
        ),
        (
            "PUBLICATION_TIME_MISSING",
            "官方資料只有交易日期，沒有發布時分秒；暫以擷取時間作可用時間",
        ),
        (
            "SESSION_CALENDAR_NOT_INTEGRATED",
            "尚未接入核准TWSE交易日曆，無法完成正式新鮮度判定",
        ),
    ):
        connection.execute(
            """
            INSERT INTO validation_results(
                validation_uid, target_type, target_uid, rule_code, severity,
                status, message_zh, checked_at, validator_version
            ) VALUES (?, 'OBSERVATION', ?, ?, 'WARNING',
                      'PASS_WITH_WARNINGS', ?, ?, ?)
            """,
            (
                deterministic_ulid(timestamp, f"VALIDATION:{evidence_id}:{code}"),
                observation_uid,
                code,
                note,
                created_at,
                PARSER_VERSION,
            ),
        )
    return {
        "subject": {
            "canonical_key": "LISTING:TWSE:2317",
            "ticker": "2317",
            "market": "TWSE",
            "currency": "TWD",
        },
        "metric_code": "TWSE_DAILY_CLOSE",
        "period_end": date_iso,
        "raw_closing_price": row["ClosingPrice"],
        "value_decimal": close,
        "unit": "TWD_PER_SHARE",
        "source_authority": "A1",
        "evidence_level": "L1",
        "validation_status": "PASS_WITH_WARNINGS",
        "model_usage": "OBSERVATION_ONLY",
        "warnings": all_warnings,
        "evidence_id": evidence_id,
        "observation_uid": observation_uid,
        "artifact_uid": artifact_uid,
        "actionable": False,
    }


def run_connector(
    output_dir: Path,
    runtime_db: Path,
    fetcher: Callable[[str, int], HttpResult] = fetch_url,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    started_at = utc_now()
    protected_before = protected_hashes(runtime_db)
    swagger_result = fetcher(SWAGGER_URL, 30)
    endpoint_result = fetcher(ENDPOINT_URL, 30)
    if swagger_result.status != 200 or endpoint_result.status != 200:
        raise PrimarySourceUnavailable("TWSE主要來源HTTP狀態不是200")
    if swagger_result.mime_type != "application/json" or endpoint_result.mime_type != "application/json":
        raise ContractError("TWSE官方回應MIME不是application/json")

    swagger_meta = save_raw(output_dir, "swagger.json", swagger_result, started_at)
    endpoint_meta = save_raw(output_dir, "STOCK_DAY_ALL.json", endpoint_result, started_at)
    swagger = parse_json_bytes(swagger_result.body, "Swagger")
    payload = parse_json_bytes(endpoint_result.body, "STOCK_DAY_ALL")
    contract = extract_contract(swagger)
    row, warnings = validate_response(payload, contract)
    endpoint_meta["response_count"] = len(payload)

    staging_db = output_dir / "twse_2317_candidate.sqlite3"
    connection = dbcore.connect_database(staging_db)
    try:
        create_schema(connection)
        candidate = insert_candidate(
            connection,
            row,
            warnings,
            endpoint_meta,
            swagger_meta,
            contract,
            started_at,
        )
        checks = dbcore.verify_connection(connection)
    finally:
        connection.close()
    protected_after = protected_hashes(runtime_db)
    if protected_before != protected_after:
        raise ConnectorError("Runtime SQLite或正式CSV在Connector期間發生變更")

    candidate_path = output_dir / "CANDIDATE_OBSERVATION.json"
    candidate_path.write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = {
        "batch_id": "P2-03B-01",
        "generated_at": utc_now(),
        "status": "PASS_WITH_WARNINGS",
        "status_zh": "通過但有警告",
        "status_note_zh": "已取得TWSE官方2317收盤價並建立staging候選；尚未接入交易日曆與發布時分秒，因此不更新PB",
        "actionable": False,
        "owner_acceptance": "PENDING",
        "connector": {
            "connector_id": CONNECTOR_ID,
            "source_code": SOURCE_CODE,
            "source_authority": "A1",
            "evidence_level": "L1",
            "endpoint_url": ENDPOINT_URL,
            "swagger_url": SWAGGER_URL,
            "swagger_sha256": swagger_meta["sha256"],
            "expected_fields": contract["fields"],
            "documented_top_level_shape": contract["documented_top_level_shape"],
            "actual_top_level_shape": "ARRAY",
            "fallback_policy": "NO_FALLBACK",
            "network_requests": 2,
            "scheduled": False,
            "historical_backfill": False,
        },
        "raw_artifacts": {
            "swagger": swagger_meta,
            "endpoint": endpoint_meta,
        },
        "candidate": candidate,
        "staging_database": {
            "path": str(staging_db.resolve()),
            "sha256": dbcore.sha256_file(staging_db),
            "schema_version": checks["schema_version"],
            "integrity_check_status": checks["integrity_check_status"],
            "foreign_key_check_status": checks["foreign_key_check_status"],
        },
        "protected_files": {
            "before": protected_before,
            "after": protected_after,
            "unchanged": protected_before == protected_after,
        },
    }
    (output_dir / "DRY_RUN.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P1008 TWSE 2317每日收盤價Connector Dry-Run")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--runtime-db", type=Path, default=DEFAULT_RUNTIME_DB)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    now = dt.datetime.now(dt.timezone.utc)
    output_dir = args.output_dir or (
        PROJECT_ROOT
        / "staging"
        / "p2-03b-01"
        / now.strftime("%Y-%m-%d")
        / f"run_{now.strftime('%Y%m%dT%H%M%SZ')}"
    )
    try:
        summary = run_connector(output_dir, args.runtime_db)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        failure = dbcore.result(
            "FAIL",
            str(exc),
            error_type=type(exc).__name__,
            error_code=(
                "PRIMARY_SOURCE_UNAVAILABLE"
                if isinstance(exc, PrimarySourceUnavailable)
                else "CONNECTOR_VALIDATION_FAILED"
            ),
            fallback_used=False,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "DRY_RUN.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

