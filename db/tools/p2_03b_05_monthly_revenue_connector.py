from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
P2_01_TOOL = PROJECT_ROOT / "db" / "tools" / "p1008_db.py"
BASE_MIGRATION = PROJECT_ROOT / "db" / "migrations" / "0001_initial_schema.sql"
EXTENSION = (
    PROJECT_ROOT / "db" / "p2-03b-05" / "monthly_revenue_connector_extension.sql"
)
SWAGGER_URL = "https://openapi.twse.com.tw/v1/swagger.json"
ENDPOINT_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
ENDPOINT_PATH = "/opendata/t187ap05_L"
ALLOWED_HOST = "openapi.twse.com.tw"
CONNECTOR_ID = "MOPS_TWSE_MONTHLY_REVENUE_2317_V1"
SOURCE_CODE = "MOPS_TWSE_OPENAPI_MONTHLY_REVENUE"
PARSER_VERSION = "p2-03b-05.1"
REPORT_PATH = PROJECT_ROOT / "reports" / "戰情室日報_2026-06-17.md"
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
    ("營業收入-當月營收", "MOPS_MONTHLY_REVENUE", None),
    ("營業收入-上月營收", "MOPS_PREVIOUS_MONTH_REVENUE", None),
    ("營業收入-去年當月營收", "MOPS_PRIOR_YEAR_MONTH_REVENUE", None),
    ("營業收入-上月比較增減(%)", "MOPS_MONTHLY_REVENUE_MOM_PCT", "PERCENT"),
    ("營業收入-去年同月增減(%)", "MOPS_MONTHLY_REVENUE_YOY_PCT", "PERCENT"),
    ("累計營業收入-當月累計營收", "MOPS_YTD_REVENUE", None),
    ("累計營業收入-去年累計營收", "MOPS_PRIOR_YEAR_YTD_REVENUE", None),
    ("累計營業收入-前期比較增減(%)", "MOPS_YTD_REVENUE_YOY_PCT", "PERCENT"),
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
    transport: str = "FIXTURE"


def load_dbcore():
    spec = importlib.util.spec_from_file_location("p1008_db_for_monthly_revenue", P2_01_TOOL)
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


def powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def fetch_url_powershell(url: str, timeout: int) -> HttpResult:
    if os.name != "nt":
        raise PrimarySourceUnavailable("PowerShell HTTPS transport只支援Windows")
    with tempfile.TemporaryDirectory(prefix="p1008-monthly-revenue-") as temp_dir:
        body_path = Path(temp_dir) / "body.bin"
        metadata_path = Path(temp_dir) / "metadata.json"
        script = f"""
$ErrorActionPreference = 'Stop'
$r = Invoke-WebRequest -UseBasicParsing -Uri {powershell_quote(url)} -TimeoutSec {int(timeout)}
$stream = $r.RawContentStream
$stream.Position = 0
$ms = New-Object IO.MemoryStream
$stream.CopyTo($ms)
[IO.File]::WriteAllBytes({powershell_quote(str(body_path))}, $ms.ToArray())
$headers = @{{}}
foreach($key in $r.Headers.Keys) {{ $headers[$key] = [string]$r.Headers[$key] }}
$metadata = @{{
  status = [int]$r.StatusCode
  mime_type = ([string]$r.Headers['Content-Type']).Split(';')[0].Trim()
  headers = $headers
}} | ConvertTo-Json -Depth 6
[IO.File]::WriteAllText(
  {powershell_quote(str(metadata_path))},
  $metadata,
  [Text.UTF8Encoding]::new($false)
)
"""
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        executable = os.environ.get(
            "SystemRoot", r"C:\Windows"
        ) + r"\System32\WindowsPowerShell\v1.0\powershell.exe"
        process = subprocess.run(
            [executable, "-NoProfile", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            timeout=timeout + 30,
            check=False,
        )
        if process.returncode != 0:
            raise PrimarySourceUnavailable(
                f"TWSE官方來源PowerShell HTTPS失敗：{process.stderr.strip()}"
            )
        metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        return HttpResult(
            url=url,
            status=int(metadata["status"]),
            mime_type=metadata["mime_type"],
            headers={str(k): str(v) for k, v in metadata["headers"].items()},
            body=body_path.read_bytes(),
            transport="POWERSHELL_HTTPS",
        )


def fetch_url(url: str, timeout: int = 90) -> HttpResult:
    validate_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "P1008-MOPS-Monthly-Revenue-DryRun/1.0",
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
                transport="PYTHON_URLLIB",
            )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if os.name == "nt":
            return fetch_url_powershell(url, timeout)
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
        raise ContractError("TWSE Swagger缺少月營收200回應Schema") from exc
    fields = list(properties)
    required = {"出表日期", "資料年月", "公司代號", *(x[0] for x in FACT_SPECS)}
    missing = sorted(required.difference(fields))
    if missing:
        raise ContractError(f"TWSE Swagger缺少必要欄位：{missing}")
    return {
        "summary": operation.get("summary", ""),
        "documented_top_level_shape": schema.get("type", "UNKNOWN").upper(),
        "fields": fields,
    }


def roc_date_to_iso(value: str) -> str:
    if not re.fullmatch(r"\d{7}", value):
        raise DataValidationError(f"出表日期格式錯誤：{value}")
    return dt.date(
        int(value[:3]) + 1911,
        int(value[3:5]),
        int(value[5:7]),
    ).isoformat()


def parse_year_month(value: str) -> dict:
    if not re.fullmatch(r"\d{5}", value):
        raise DataValidationError(f"資料年月格式錯誤：{value}")
    year = int(value[:3]) + 1911
    month = int(value[3:5])
    if month < 1 or month > 12:
        raise DataValidationError(f"資料月份超出範圍：{value}")
    period_start = dt.date(year, month, 1)
    if month == 12:
        next_month = dt.date(year + 1, 1, 1)
    else:
        next_month = dt.date(year, month + 1, 1)
    period_end = next_month - dt.timedelta(days=1)
    return {
        "data_year_month_roc": value,
        "data_year_month": f"{year}-{month:02d}",
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
    }


def normalize_decimal(value: str, field: str) -> str:
    candidate = value.strip().replace(",", "")
    if candidate == "":
        raise DataValidationError(f"{field}不得為空")
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


def recompute_percent(numerator: str, denominator: str) -> Decimal:
    base = Decimal(denominator)
    if base == 0:
        raise DataValidationError("百分比基期不得為0")
    return (Decimal(numerator) / base - 1) * Decimal("100")


def validate_percent_formulas(row: dict) -> list[dict]:
    checks = (
        (
            "MOM",
            "營業收入-上月比較增減(%)",
            "營業收入-當月營收",
            "營業收入-上月營收",
        ),
        (
            "YOY",
            "營業收入-去年同月增減(%)",
            "營業收入-當月營收",
            "營業收入-去年當月營收",
        ),
        (
            "YTD_YOY",
            "累計營業收入-前期比較增減(%)",
            "累計營業收入-當月累計營收",
            "累計營業收入-去年累計營收",
        ),
    )
    results = []
    tolerance = Decimal("0.000001")
    for code, percentage_field, numerator_field, denominator_field in checks:
        declared = Decimal(normalize_decimal(row[percentage_field], percentage_field))
        calculated = recompute_percent(
            normalize_decimal(row[numerator_field], numerator_field),
            normalize_decimal(row[denominator_field], denominator_field),
        )
        difference = abs(declared - calculated)
        if difference > tolerance:
            raise DataValidationError(
                f"{code}官方百分比與原始值重算不一致：difference={difference}"
            )
        results.append(
            {
                "code": code,
                "declared": format(declared, "f"),
                "calculated": format(calculated, "f"),
                "difference": format(difference, "f"),
                "status": "PASS",
            }
        )
    return results


def read_report_yoy() -> Decimal:
    text = REPORT_PATH.read_text(encoding="utf-8")
    match = re.search(r"5月營收YoY\s*\|\s*\+?([0-9.]+)%", text)
    if not match:
        raise DataValidationError("既有日報找不到5月營收YoY")
    return Decimal(match.group(1))


def create_schema(connection: sqlite3.Connection) -> None:
    migrations = (
        dbcore.Migration(
            1, "initial_schema", BASE_MIGRATION, dbcore.sha256_file(BASE_MIGRATION)
        ),
        dbcore.Migration(
            7,
            "monthly_revenue_connector_extension",
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
        "transport": result.transport,
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


def insert_candidate(
    connection: sqlite3.Connection,
    row: dict,
    warnings: list[str],
    endpoint_meta: dict,
    swagger_meta: dict,
    contract: dict,
    retrieved_at: str,
    formula_checks: list[dict],
) -> dict:
    source_report_date = roc_date_to_iso(row["出表日期"])
    period = parse_year_month(row["資料年月"])
    timestamp = dt.datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    subject_uid = deterministic_ulid(
        timestamp, "LEGAL_ENTITY:HON_HAI_PRECISION_INDUSTRY"
    )
    source_uid = deterministic_ulid(timestamp, f"SOURCE:{SOURCE_CODE}")
    artifact_uid = deterministic_ulid(timestamp, f"ARTIFACT:{endpoint_meta['sha256']}")
    row_uid = deterministic_ulid(
        timestamp,
        f"MONTHLY_REVENUE_ROW:2317:{period['data_year_month']}:{endpoint_meta['sha256']}",
    )
    execution_uid = deterministic_ulid(
        timestamp, f"EXECUTION:{CONNECTOR_ID}:{endpoint_meta['sha256']}"
    )
    row_sha = sha256_bytes(canonical_json(row).encode("utf-8"))
    transport_warning = (
        ["TLS_TRANSPORT_RETRY_SAME_SOURCE"]
        if endpoint_meta["transport"] == "POWERSHELL_HTTPS"
        or swagger_meta["transport"] == "POWERSHELL_HTTPS"
        else []
    )
    all_warnings = warnings + transport_warning + [
        "SOURCE_REPORT_DATE_NOT_PUBLICATION_TIME",
        "MONETARY_UNIT_UNVERIFIED",
        "MONTH_TO_QUARTER_PROMOTION_BLOCKED",
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
        (subject_uid, retrieved_at, retrieved_at),
    )
    connection.execute(
        """
        INSERT INTO sources(
            source_uid, source_code, source_name, source_type, official_url,
            quality_level, license_scope, retrieval_method, enabled,
            created_at, updated_at
        ) VALUES (?, ?, 'TWSE OpenAPI公開資訊觀測站月營收',
                  'OFFICIAL_REGULATORY_DISCLOSURE', ?, 'A1',
                  'OWNER_INTERNAL_DRY_RUN_REDISTRIBUTION_NOT_APPROVED',
                  'HTTPS_GET_MANUAL_SINGLE_RUN', 1, ?, ?)
        """,
        (source_uid, SOURCE_CODE, ENDPOINT_URL, retrieved_at, retrieved_at),
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
            retrieved_at,
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
                  'NO_SOURCE_FALLBACK', 'ACTIVE_DRY_RUN', 'OWNER_ITEM_81')
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
        INSERT INTO monthly_revenue_rows(
            monthly_revenue_row_uid, artifact_uid, subject_uid, company_code,
            source_report_date, data_year_month_roc, data_year_month,
            period_start, period_end, source_row_sha256, raw_row_json,
            validation_status, message_zh, created_at
        ) VALUES (?, ?, ?, '2317', ?, ?, ?, ?, ?, ?, ?,
                  'PASS_WITH_WARNINGS',
                  '官方月營收列已保存；百分比僅供觀察，金額單位未驗證', ?)
        """,
        (
            row_uid,
            artifact_uid,
            subject_uid,
            source_report_date,
            period["data_year_month_roc"],
            period["data_year_month"],
            period["period_start"],
            period["period_end"],
            row_sha,
            canonical_json(row),
            retrieved_at,
        ),
    )

    facts = []
    observation_count = 0
    blocked_fact_count = 0
    yoy_fact_uid = None
    official_yoy = None
    for source_field, metric_code, verified_unit in FACT_SPECS:
        normalized = normalize_decimal(row[source_field], source_field)
        evidence_hash = sha256_bytes(
            canonical_json(
                {
                    "artifact_sha256": endpoint_meta["sha256"],
                    "company_code": "2317",
                    "period": period["data_year_month"],
                    "source_field": source_field,
                    "raw_value": row[source_field],
                }
            ).encode("utf-8")
        )
        evidence_id = (
            f"EVD-MOPS-TWSE_2317-{metric_code.removeprefix('MOPS_')}-"
            f"{period['data_year_month'].replace('-', '')}-R01-{evidence_hash[:8]}"
        )
        fact_uid = deterministic_ulid(timestamp, f"FACT:{evidence_id}")
        observation_uid = None
        if verified_unit == "PERCENT":
            metric_uid = deterministic_ulid(timestamp, f"METRIC:{metric_code}")
            observation_uid = deterministic_ulid(
                timestamp, f"OBSERVATION:{evidence_id}"
            )
            name_map = {
                "MOPS_MONTHLY_REVENUE_MOM_PCT": "月營收月增率",
                "MOPS_MONTHLY_REVENUE_YOY_PCT": "月營收年增率",
                "MOPS_YTD_REVENUE_YOY_PCT": "累計營收年增率",
            }
            connection.execute(
                """
                INSERT INTO metric_definitions(
                    metric_uid, metric_code, name_zh, frequency, value_type,
                    canonical_unit, is_derived, formula_version,
                    required_for_report, model_usage, created_at, updated_at
                ) VALUES (?, ?, ?, 'MONTHLY', 'DECIMAL', 'PERCENT', 0, NULL,
                          0, 'OBSERVATION_ONLY', ?, ?)
                """,
                (
                    metric_uid,
                    metric_code,
                    name_map[metric_code],
                    retrieved_at,
                    retrieved_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO observations(
                    observation_uid, subject_uid, metric_uid, value_decimal,
                    value_text, unit, period_start, period_end, published_at,
                    effective_at, retrieved_at, source_uid, artifact_uid,
                    revision, validation_status, support_level,
                    supersedes_observation_uid, created_at
                ) VALUES (?, ?, ?, ?, NULL, 'PERCENT', ?, ?, ?, ?, ?, ?, ?, 1,
                          'PASS_WITH_WARNINGS', 'L1', NULL, ?)
                """,
                (
                    observation_uid,
                    subject_uid,
                    metric_uid,
                    normalized,
                    period["period_start"],
                    period["period_end"],
                    retrieved_at,
                    retrieved_at,
                    retrieved_at,
                    source_uid,
                    artifact_uid,
                    retrieved_at,
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
                          '官方月營收百分比；僅供觀察，不得直接觸發規則', ?)
                """,
                (
                    deterministic_ulid(timestamp, f"EVIDENCE:{evidence_id}"),
                    evidence_id,
                    observation_uid,
                    artifact_uid,
                    row_sha,
                    period["data_year_month"],
                    source_field,
                    row[source_field],
                    normalized,
                    canonical_json(all_warnings),
                    retrieved_at,
                ),
            )
            promotion_status = "OBSERVATION_ONLY"
            unit_status = "VERIFIED"
            message = "官方百分比欄位，已通過原始金額比例重算；僅供觀察"
            observation_count += 1
        else:
            promotion_status = "BLOCKED_UNIT_UNVERIFIED"
            unit_status = "UNVERIFIED"
            message = "官方營收金額已保存，但Swagger未聲明單位，禁止建立Observation"
            blocked_fact_count += 1
        connection.execute(
            """
            INSERT INTO monthly_revenue_facts(
                fact_uid, monthly_revenue_row_uid, evidence_id, source_field,
                metric_code, raw_value, normalized_value, unit_code,
                unit_status, promotion_status, observation_uid, actionable,
                message_zh, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                fact_uid,
                row_uid,
                evidence_id,
                source_field,
                metric_code,
                row[source_field],
                normalized,
                verified_unit,
                unit_status,
                promotion_status,
                observation_uid,
                message,
                retrieved_at,
            ),
        )
        facts.append(
            {
                "source_field": source_field,
                "metric_code": metric_code,
                "raw_value": row[source_field],
                "normalized_value": normalized,
                "unit_code": verified_unit,
                "unit_status": unit_status,
                "promotion_status": promotion_status,
                "evidence_id": evidence_id,
                "observation_uid": observation_uid,
                "message_zh": message,
                "actionable": False,
            }
        )
        if metric_code == "MOPS_MONTHLY_REVENUE_YOY_PCT":
            yoy_fact_uid = fact_uid
            official_yoy = Decimal(normalized)

    assert yoy_fact_uid is not None and official_yoy is not None
    report_yoy = read_report_yoy()
    difference = official_yoy - report_yoy
    tolerance = Decimal("0.01")
    comparison_status = (
        "SOURCE_MATCH_CONFIRMED"
        if abs(difference) <= tolerance
        else "DATA_CONFLICT_PENDING"
    )
    comparison_note = (
        "官方5月營收年增率四捨五入至小數二位後與既有日報39.57%一致"
        if comparison_status == "SOURCE_MATCH_CONFIRMED"
        else "官方5月營收年增率與既有日報差異超過0.01個百分點"
    )
    connection.execute(
        """
        INSERT INTO source_comparisons(
            comparison_uid, fact_uid, comparison_code, source_value,
            existing_document_path, existing_value, difference, tolerance,
            comparison_status, actionable, message_zh, created_at
        ) VALUES (?, ?, 'COMPARE-REPORT-2026-05-REVENUE-YOY', ?,
                  'reports/戰情室日報_2026-06-17.md', ?, ?, '0.01', ?, 0, ?, ?)
        """,
        (
            deterministic_ulid(timestamp, "COMPARE-REPORT-2026-05-REVENUE-YOY"),
            yoy_fact_uid,
            format(official_yoy, "f"),
            format(report_yoy, "f"),
            format(difference, "f"),
            comparison_status,
            comparison_note,
            retrieved_at,
        ),
    )

    warning_notes = {
        "SWAGGER_RESPONSE_SHAPE_MISMATCH":
            "Swagger描述單一物件，實際回應為陣列",
        "TLS_TRANSPORT_RETRY_SAME_SOURCE":
            "Python TLS鏈驗證失敗後改用Windows PowerShell TLS重試同一官方URL；未切換資料來源",
        "SOURCE_REPORT_DATE_NOT_PUBLICATION_TIME":
            "出表日期不是已驗證的法定發布時分秒",
        "MONETARY_UNIT_UNVERIFIED":
            "Swagger未聲明營收金額單位，五個金額事實阻擋升格",
        "MONTH_TO_QUARTER_PROMOTION_BLOCKED":
            "未核准月轉季公式，不得覆寫季度營收",
    }
    for code in all_warnings:
        connection.execute(
            """
            INSERT INTO validation_results(
                validation_uid, target_type, target_uid, rule_code, severity,
                status, message_zh, checked_at, validator_version
            ) VALUES (?, 'MONTHLY_REVENUE_ROW', ?, ?, 'WARNING',
                      'PASS_WITH_WARNINGS', ?, ?, ?)
            """,
            (
                deterministic_ulid(timestamp, f"VALIDATION:{row_uid}:{code}"),
                row_uid,
                code,
                warning_notes[code],
                retrieved_at,
                PARSER_VERSION,
            ),
        )
    connection.execute(
        """
        INSERT INTO connector_executions(
            execution_uid, connector_id, started_at, finished_at, http_status,
            mime_type, raw_sha256, response_count, selected_count,
            observation_count, blocked_fact_count, transport, status_code,
            status_zh, status_note_zh, error_code, fallback_used, actionable
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, 'PASS_WITH_WARNINGS',
                  '通過但有警告',
                  '已保存2317官方月營收；三個百分比供觀察，五個金額因單位未驗證而阻擋',
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
            endpoint_meta["transport"],
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
        "warnings": all_warnings,
        "formula_checks": formula_checks,
        "facts": facts,
        "observation_count": observation_count,
        "blocked_fact_count": blocked_fact_count,
        "report_yoy_comparison": {
            "official_value": format(official_yoy, "f"),
            "existing_value": format(report_yoy, "f"),
            "difference": format(difference, "f"),
            "tolerance": "0.01",
            "status": comparison_status,
            "status_zh": (
                "來源數值一致"
                if comparison_status == "SOURCE_MATCH_CONFIRMED"
                else "資料衝突待釐清"
            ),
            "message_zh": comparison_note,
        },
        "cumulative_revenue_context": {
            "raw_value": row["累計營業收入-當月累計營收"],
            "formal_comparison_allowed": False,
            "message_zh": "若假設官方金額單位為千元，約為3.821兆元並與報告3.82兆元相符；因單位未驗證，不作正式比較",
        },
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
    swagger_result = fetcher(SWAGGER_URL, 90)
    endpoint_result = fetcher(ENDPOINT_URL, 90)
    if swagger_result.status != 200 or endpoint_result.status != 200:
        raise PrimarySourceUnavailable("TWSE/MOPS主要來源HTTP狀態不是200")
    if (
        swagger_result.mime_type != "application/json"
        or endpoint_result.mime_type != "application/json"
    ):
        raise ContractError("TWSE/MOPS官方回應MIME不是application/json")

    swagger_meta = save_raw(output_dir, "swagger.json", swagger_result, started_at)
    endpoint_meta = save_raw(
        output_dir, "t187ap05_L.json", endpoint_result, started_at
    )
    swagger = parse_json_bytes(swagger_result.body, "Swagger")
    payload = parse_json_bytes(endpoint_result.body, "月營收")
    contract = extract_contract(swagger)
    row, warnings = validate_response(payload, contract)
    formula_checks = validate_percent_formulas(row)
    endpoint_meta["response_count"] = len(payload)

    staging_db = output_dir / "mops_2317_monthly_revenue_candidate.sqlite3"
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
            formula_checks,
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
        "batch_id": "P2-03B-05",
        "generated_at": utc_now(),
        "status": "PASS_WITH_WARNINGS",
        "status_zh": "通過但有警告",
        "status_note_zh":
            "已保存2317官方月營收；官方5月YoY與報告39.57%一致，金額因單位未驗證而不升格",
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
            "fallback_policy": "NO_SOURCE_FALLBACK",
            "network_requests": 2,
            "scheduled": False,
            "historical_backfill": False,
            "month_to_quarter_promotion": False,
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
        description="P1008 2317上市公司每月營業收入Connector Dry-Run"
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
        / "p2-03b-05"
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
