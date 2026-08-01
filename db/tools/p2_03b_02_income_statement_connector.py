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
EXTENSION = (
    PROJECT_ROOT
    / "db"
    / "p2-03b-02"
    / "income_statement_connector_extension.sql"
)
SWAGGER_URL = "https://openapi.twse.com.tw/v1/swagger.json"
ENDPOINT_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci"
ENDPOINT_PATH = "/opendata/t187ap06_L_ci"
ALLOWED_HOST = "openapi.twse.com.tw"
CONNECTOR_ID = "MOPS_TWSE_INCOME_STATEMENT_GENERAL_2317_V1"
SOURCE_CODE = "MOPS_TWSE_OPENAPI_INCOME_STATEMENT_GENERAL"
PARSER_VERSION = "p2-03b-02.1"
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

FACT_SPECS = (
    ("營業收入", "MOPS_CUM_REVENUE", None),
    ("營業成本", "MOPS_CUM_COST_OF_REVENUE", None),
    ("營業毛利（毛損）淨額", "MOPS_CUM_GROSS_PROFIT_NET", None),
    ("營業利益（損失）", "MOPS_CUM_OPERATING_INCOME", None),
    ("稅前淨利（淨損）", "MOPS_CUM_PROFIT_BEFORE_TAX", None),
    ("所得稅費用（利益）", "MOPS_CUM_INCOME_TAX", None),
    (
        "淨利（淨損）歸屬於母公司業主",
        "MOPS_CUM_NET_INCOME_ATTRIBUTABLE_PARENT",
        None,
    ),
    ("基本每股盈餘（元）", "MOPS_CUM_BASIC_EPS", "TWD_PER_SHARE"),
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
    spec = importlib.util.spec_from_file_location("p1008_db_for_income_statement", P2_01_TOOL)
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
    value = (
        (int(timestamp.timestamp() * 1000) & ((1 << 48) - 1)) << 80
    ) | int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:10], "big")
    chars = []
    for _ in range(26):
        chars.append(dbcore.CROCKFORD32[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise ContractError(f"不允許的Connector URL：{url}")


def fetch_url(url: str, timeout: int = 60) -> HttpResult:
    validate_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "P1008-MOPS-Income-Statement-DryRun/1.0",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResult(
                url=url,
                status=int(response.status),
                mime_type=response.headers.get_content_type(),
                headers={key: value for key, value in response.headers.items()},
                body=response.read(),
            )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PrimarySourceUnavailable(f"TWSE/MOPS主要來源無法使用：{exc}") from exc


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
        raise ContractError("TWSE Swagger缺少綜合損益表200回應Schema") from exc
    fields = list(properties)
    required = {"出表日期", "年度", "季別", "公司代號", *(spec[0] for spec in FACT_SPECS)}
    missing = sorted(required.difference(fields))
    if missing:
        raise ContractError(f"TWSE Swagger缺少必要欄位：{missing}")
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
        raise DataValidationError(f"出表日期格式錯誤：{value}")
    return dt.date(
        int(value[:3]) + 1911,
        int(value[3:5]),
        int(value[5:7]),
    ).isoformat()


def parse_period(year_value: str, quarter_value: str) -> dict:
    if not re.fullmatch(r"\d{3}", year_value):
        raise DataValidationError(f"財報年度格式錯誤：{year_value}")
    if quarter_value not in {"1", "2", "3", "4"}:
        raise DataValidationError(f"財報季別格式錯誤：{quarter_value}")
    fiscal_year = int(year_value) + 1911
    quarter = int(quarter_value)
    end_month_day = {
        1: (3, 31),
        2: (6, 30),
        3: (9, 30),
        4: (12, 31),
    }[quarter]
    return {
        "fiscal_year_roc": year_value,
        "fiscal_year": fiscal_year,
        "fiscal_quarter": quarter,
        "period_label": f"{fiscal_year}Q{quarter}",
        "period_start": dt.date(fiscal_year, 1, 1).isoformat(),
        "period_end": dt.date(fiscal_year, *end_month_day).isoformat(),
        "period_basis": "CUMULATIVE_YTD",
    }


def normalize_decimal(value: str, field: str) -> str:
    candidate = value.strip().replace(",", "")
    try:
        number = Decimal(candidate)
    except InvalidOperation as exc:
        raise DataValidationError(f"{field}不是有效Decimal：{value}") from exc
    if not number.is_finite():
        raise DataValidationError(f"{field}不是有限Decimal：{value}")
    normalized = format(number, "f").rstrip("0").rstrip(".")
    return normalized or "0"


def validate_response(payload, contract: dict) -> tuple[dict, list[str]]:
    if not isinstance(payload, list):
        raise ContractError("TWSE/MOPS實際回應頂層不是陣列")
    selected = [
        row for row in payload
        if isinstance(row, dict) and row.get("公司代號") == "2317"
    ]
    if len(selected) != 1:
        raise DataValidationError(
            f"TWSE/MOPS回應中公司代號=2317筆數應為1，實際為{len(selected)}"
        )
    row = selected[0]
    if list(row) != contract["fields"]:
        raise ContractError(
            f"2317欄位與Swagger不一致：actual={list(row)}, expected={contract['fields']}"
        )
    warnings = []
    if contract["documented_top_level_shape"] != "ARRAY":
        warnings.append("SWAGGER_RESPONSE_SHAPE_MISMATCH")
    return row, warnings


def create_schema(connection: sqlite3.Connection) -> None:
    migrations = (
        dbcore.Migration(
            1,
            "initial_schema",
            BASE_MIGRATION,
            dbcore.sha256_file(BASE_MIGRATION),
        ),
        dbcore.Migration(
            5,
            "income_statement_connector_extension",
            EXTENSION,
            dbcore.sha256_file(EXTENSION),
        ),
    )
    for migration in migrations:
        dbcore.apply_one_migration(connection, migration, mode="DRY_RUN", backup_id=None)


def protected_hashes(runtime_db: Path) -> dict[str, str]:
    return {
        str(path.resolve()): dbcore.sha256_file(path)
        for path in (*FORMAL_CSVS, runtime_db)
    }


def save_raw(output_dir: Path, name: str, result: HttpResult, retrieved_at: str) -> dict:
    raw_dir = output_dir / "raw" / "mops_twse"
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
        "status_note_zh": "未修改的TWSE/MOPS官方HTTPS回應",
        "actionable": False,
    }
    (raw_dir / f"{name}.metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return metadata


def build_fact_candidates(row: dict, period: dict, artifact_sha: str) -> list[dict]:
    facts = []
    for source_field, metric_code, verified_unit in FACT_SPECS:
        normalized = normalize_decimal(row[source_field], source_field)
        evidence_hash = sha256_bytes(
            canonical_json(
                {
                    "artifact_sha256": artifact_sha,
                    "company_code": "2317",
                    "period": period["period_label"],
                    "source_field": source_field,
                    "raw_value": row[source_field],
                }
            ).encode("utf-8")
        )
        evidence_id = (
            f"EVD-MOPS-TWSE_2317-{metric_code.removeprefix('MOPS_')}-"
            f"{period['period_label']}-R01-{evidence_hash[:8]}"
        )
        if verified_unit:
            promotion_status = "OBSERVATION_ONLY"
            unit_status = "VERIFIED"
            message_zh = "官方累計基本每股盈餘；僅供觀察，不代表單季EPS"
        else:
            promotion_status = "BLOCKED_UNIT_UNVERIFIED"
            unit_status = "UNVERIFIED"
            message_zh = "官方金額已保存，但Swagger未聲明單位，禁止建立正式Observation"
        facts.append(
            {
                "source_field": source_field,
                "metric_code": metric_code,
                "raw_value": row[source_field],
                "normalized_value": normalized,
                "unit_code": verified_unit,
                "unit_status": unit_status,
                "period_basis": "CUMULATIVE_YTD",
                "promotion_status": promotion_status,
                "evidence_id": evidence_id,
                "message_zh": message_zh,
                "actionable": False,
            }
        )
    return facts


def insert_candidate(
    connection: sqlite3.Connection,
    row: dict,
    warnings: list[str],
    endpoint_meta: dict,
    swagger_meta: dict,
    contract: dict,
    retrieved_at: str,
) -> dict:
    source_report_date = roc_date_to_iso(row["出表日期"])
    period = parse_period(row["年度"], row["季別"])
    timestamp = dt.datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    created_at = retrieved_at
    subject_uid = deterministic_ulid(
        timestamp, "LEGAL_ENTITY:HON_HAI_PRECISION_INDUSTRY"
    )
    metric_uid = deterministic_ulid(timestamp, "METRIC:MOPS_CUM_BASIC_EPS")
    source_uid = deterministic_ulid(timestamp, f"SOURCE:{SOURCE_CODE}")
    artifact_uid = deterministic_ulid(timestamp, f"ARTIFACT:{endpoint_meta['sha256']}")
    statement_row_uid = deterministic_ulid(
        timestamp,
        f"STATEMENT_ROW:2317:{period['period_label']}:{endpoint_meta['sha256']}",
    )
    execution_uid = deterministic_ulid(
        timestamp, f"EXECUTION:{CONNECTOR_ID}:{endpoint_meta['sha256']}"
    )
    row_sha = sha256_bytes(canonical_json(row).encode("utf-8"))
    facts = build_fact_candidates(row, period, endpoint_meta["sha256"])
    all_warnings = warnings + [
        "SOURCE_REPORT_DATE_NOT_PUBLICATION_TIME",
        "CUMULATIVE_PERIOD_NOT_SINGLE_QUARTER",
        "MONETARY_UNIT_UNVERIFIED",
        "REPORTING_SCOPE_UNVERIFIED",
    ]

    connection.execute(
        """
        INSERT INTO subjects(
            subject_uid, subject_type, canonical_key, name, ticker, market,
            isin, cik, currency, parent_subject_uid, status, created_at, updated_at
        ) VALUES (?, 'COMPANY', 'LEGAL_ENTITY:HON_HAI_PRECISION_INDUSTRY',
                  '鴻海精密工業股份有限公司', '2317', 'TWSE',
                  NULL, NULL, 'TWD', NULL, 'ACTIVE', ?, ?)
        """,
        (subject_uid, created_at, created_at),
    )
    connection.execute(
        """
        INSERT INTO metric_definitions(
            metric_uid, metric_code, name_zh, frequency, value_type,
            canonical_unit, is_derived, formula_version, required_for_report,
            model_usage, created_at, updated_at
        ) VALUES (?, 'MOPS_CUM_BASIC_EPS', 'MOPS累計基本每股盈餘',
                  'QUARTERLY', 'DECIMAL', 'TWD_PER_SHARE', 0, NULL, 0,
                  'OBSERVATION_ONLY', ?, ?)
        """,
        (metric_uid, created_at, created_at),
    )
    connection.execute(
        """
        INSERT INTO sources(
            source_uid, source_code, source_name, source_type, official_url,
            quality_level, license_scope, retrieval_method, enabled,
            created_at, updated_at
        ) VALUES (?, ?, 'TWSE OpenAPI公開資訊觀測站綜合損益表',
                  'OFFICIAL_REGULATORY_DISCLOSURE', ?, 'A1',
                  'OWNER_INTERNAL_DRY_RUN_REDISTRIBUTION_NOT_APPROVED',
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
                  'NO_FALLBACK', 'ACTIVE_DRY_RUN', 'OWNER_ITEM_73')
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
    connection.execute(
        """
        INSERT INTO financial_statement_rows(
            statement_row_uid, artifact_uid, subject_uid, company_code,
            source_report_date, fiscal_year_roc, fiscal_year, fiscal_quarter,
            period_start, period_end, period_basis, reporting_scope_status,
            source_row_sha256, raw_row_json, validation_status, message_zh,
            created_at
        ) VALUES (?, ?, ?, '2317', ?, ?, ?, ?, ?, ?, 'CUMULATIVE_YTD',
                  'UNVERIFIED', ?, ?, 'PASS_WITH_WARNINGS',
                  '官方申報列已保存；金額單位、報表範圍與發布時點尚未完整驗證', ?)
        """,
        (
            statement_row_uid,
            artifact_uid,
            subject_uid,
            source_report_date,
            period["fiscal_year_roc"],
            period["fiscal_year"],
            period["fiscal_quarter"],
            period["period_start"],
            period["period_end"],
            row_sha,
            canonical_json(row),
            created_at,
        ),
    )

    observation_count = 0
    blocked_fact_count = 0
    for fact in facts:
        fact_uid = deterministic_ulid(
            timestamp, f"FACT:{fact['evidence_id']}"
        )
        observation_uid = None
        if fact["promotion_status"] == "OBSERVATION_ONLY":
            observation_uid = deterministic_ulid(
                timestamp, f"OBSERVATION:{fact['evidence_id']}"
            )
            connection.execute(
                """
                INSERT INTO observations(
                    observation_uid, subject_uid, metric_uid, value_decimal,
                    value_text, unit, period_start, period_end, published_at,
                    effective_at, retrieved_at, source_uid, artifact_uid,
                    revision, validation_status, support_level,
                    supersedes_observation_uid, created_at
                ) VALUES (?, ?, ?, ?, NULL, 'TWD_PER_SHARE', ?, ?, ?, ?, ?,
                          ?, ?, 1, 'PASS_WITH_WARNINGS', 'L1', NULL, ?)
                """,
                (
                    observation_uid,
                    subject_uid,
                    metric_uid,
                    fact["normalized_value"],
                    period["period_start"],
                    period["period_end"],
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
                    source_row_sha256, source_code_value, source_period_value,
                    source_field, raw_value, normalized_value, validation_status,
                    model_usage, warnings_json, message_zh, created_at
                ) VALUES (?, ?, ?, ?, ?, '2317', ?, ?, ?, ?,
                          'PASS_WITH_WARNINGS', 'OBSERVATION_ONLY', ?,
                          '官方累計基本每股盈餘；不得視為單季EPS或直接觸發規則', ?)
                """,
                (
                    deterministic_ulid(timestamp, f"EVIDENCE:{fact['evidence_id']}"),
                    fact["evidence_id"],
                    observation_uid,
                    artifact_uid,
                    row_sha,
                    period["period_label"],
                    fact["source_field"],
                    fact["raw_value"],
                    fact["normalized_value"],
                    canonical_json(all_warnings),
                    created_at,
                ),
            )
            observation_count += 1
        else:
            blocked_fact_count += 1
        fact["observation_uid"] = observation_uid
        connection.execute(
            """
            INSERT INTO financial_statement_facts(
                fact_uid, statement_row_uid, evidence_id, source_field,
                metric_code, raw_value, normalized_value, unit_code,
                unit_status, period_basis, promotion_status, observation_uid,
                actionable, message_zh, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'CUMULATIVE_YTD', ?, ?,
                      0, ?, ?)
            """,
            (
                fact_uid,
                statement_row_uid,
                fact["evidence_id"],
                fact["source_field"],
                fact["metric_code"],
                fact["raw_value"],
                fact["normalized_value"],
                fact["unit_code"],
                fact["unit_status"],
                fact["promotion_status"],
                observation_uid,
                fact["message_zh"],
                created_at,
            ),
        )

    warning_notes = {
        "SWAGGER_RESPONSE_SHAPE_MISMATCH":
            "Swagger描述單一物件，實際回應為陣列；已依物件欄位驗證2317資料列",
        "SOURCE_REPORT_DATE_NOT_PUBLICATION_TIME":
            "出表日期不是已驗證的法定發布時分秒；暫以擷取時間限制可用性",
        "CUMULATIVE_PERIOD_NOT_SINGLE_QUARTER":
            "官方申報值按累計期間保存，不得直接當作單季數字",
        "MONETARY_UNIT_UNVERIFIED":
            "Swagger未聲明金額單位，七個金額事實禁止建立Observation",
        "REPORTING_SCOPE_UNVERIFIED":
            "端點契約未聲明合併或個體報表範圍，禁止升格正式決策資料",
    }
    for code in all_warnings:
        connection.execute(
            """
            INSERT INTO validation_results(
                validation_uid, target_type, target_uid, rule_code, severity,
                status, message_zh, checked_at, validator_version
            ) VALUES (?, 'STATEMENT_ROW', ?, ?, 'WARNING',
                      'PASS_WITH_WARNINGS', ?, ?, ?)
            """,
            (
                deterministic_ulid(
                    timestamp, f"VALIDATION:{statement_row_uid}:{code}"
                ),
                statement_row_uid,
                code,
                warning_notes[code],
                created_at,
                PARSER_VERSION,
            ),
        )
    connection.execute(
        """
        INSERT INTO connector_executions(
            execution_uid, connector_id, started_at, finished_at, http_status,
            mime_type, raw_sha256, response_count, selected_count,
            observation_count, blocked_fact_count, status_code, status_zh,
            status_note_zh, error_code, fallback_used, actionable
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 'PASS_WITH_WARNINGS',
                  '通過但有警告',
                  '已保存2317官方累計損益資料；只有累計EPS建立觀察候選，金額因單位未驗證而阻擋',
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
            observation_count,
            blocked_fact_count,
        ),
    )
    return {
        "subject": {
            "canonical_key": "LEGAL_ENTITY:HON_HAI_PRECISION_INDUSTRY",
            "ticker": "2317",
            "market": "TWSE",
            "currency": "TWD",
        },
        "source_report_date": source_report_date,
        "period": period,
        "source_authority": "A1",
        "evidence_level": "L1",
        "validation_status": "PASS_WITH_WARNINGS",
        "model_usage": "OBSERVATION_ONLY",
        "warnings": all_warnings,
        "facts": facts,
        "observation_count": observation_count,
        "blocked_fact_count": blocked_fact_count,
        "reporting_scope_status": "UNVERIFIED",
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
    swagger_result = fetcher(SWAGGER_URL, 60)
    endpoint_result = fetcher(ENDPOINT_URL, 60)
    if swagger_result.status != 200 or endpoint_result.status != 200:
        raise PrimarySourceUnavailable("TWSE/MOPS主要來源HTTP狀態不是200")
    if (
        swagger_result.mime_type != "application/json"
        or endpoint_result.mime_type != "application/json"
    ):
        raise ContractError("TWSE/MOPS官方回應MIME不是application/json")

    swagger_meta = save_raw(output_dir, "swagger.json", swagger_result, started_at)
    endpoint_meta = save_raw(
        output_dir, "t187ap06_L_ci.json", endpoint_result, started_at
    )
    swagger = parse_json_bytes(swagger_result.body, "Swagger")
    payload = parse_json_bytes(endpoint_result.body, "綜合損益表")
    contract = extract_contract(swagger)
    row, warnings = validate_response(payload, contract)
    endpoint_meta["response_count"] = len(payload)

    staging_db = output_dir / "mops_2317_income_statement_candidate.sqlite3"
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

    (output_dir / "CANDIDATE_FACTS.json").write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = {
        "batch_id": "P2-03B-02",
        "generated_at": utc_now(),
        "status": "PASS_WITH_WARNINGS",
        "status_zh": "通過但有警告",
        "status_note_zh":
            "已保存2317官方累計綜合損益資料；累計EPS僅供觀察，七個金額因單位未驗證而阻擋",
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
            "documented_top_level_shape":
                contract["documented_top_level_shape"],
            "actual_top_level_shape": "ARRAY",
            "fallback_policy": "NO_FALLBACK",
            "network_requests": 2,
            "scheduled": False,
            "historical_backfill": False,
            "single_quarter_derivation": False,
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
    parser = argparse.ArgumentParser(
        description="P1008 2317上市公司綜合損益表Connector Dry-Run"
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--runtime-db", type=Path, default=DEFAULT_RUNTIME_DB)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    now = dt.datetime.now(dt.timezone.utc)
    output_dir = args.output_dir or (
        PROJECT_ROOT
        / "staging"
        / "p2-03b-02"
        / now.strftime("%Y-%m-%d")
        / f"run_{now.strftime('%Y%m%dT%H%M%SZ')}"
    )
    try:
        print(
            json.dumps(
                run_connector(output_dir, args.runtime_db),
                ensure_ascii=False,
                indent=2,
            )
        )
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
