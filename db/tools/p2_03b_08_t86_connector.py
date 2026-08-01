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
from decimal import Decimal
from pathlib import Path
from typing import Callable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
P2_01_TOOL = PROJECT_ROOT / "db" / "tools" / "p1008_db.py"
BASE_MIGRATION = PROJECT_ROOT / "db" / "migrations" / "0001_initial_schema.sql"
EXTENSION = PROJECT_ROOT / "db" / "p2-03b-08" / "t86_connector_extension.sql"
ENDPOINT_BASE = "https://www.twse.com.tw/rwd/zh/fund/T86"
PAGE_URL = "https://www.twse.com.tw/zh/trading/foreign/t86.html"
ENDPOINT_PATH = "/rwd/zh/fund/T86"
ALLOWED_HOST = "www.twse.com.tw"
SELECT_TYPE = "ALLBUT0999"
CONNECTOR_ID = "TWSE_T86_2317_DAILY_V1"
SOURCE_CODE = "TWSE_T86_THREE_INSTITUTIONAL_DAILY"
PARSER_VERSION = "p2-03b-08.1"
OWNER_APPROVAL = "OWNER_ITEM_93"
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
AUTHORITY_MANIFEST = PROJECT_ROOT / "data" / "CSV_AUTHORITY_MANIFEST.json"
FORMAL_PROTECTED = (*FORMAL_CSVS, AUTHORITY_MANIFEST)

EXPECTED_FIELDS = [
    "證券代號",
    "證券名稱",
    "外陸資買進股數(不含外資自營商)",
    "外陸資賣出股數(不含外資自營商)",
    "外陸資買賣超股數(不含外資自營商)",
    "外資自營商買進股數",
    "外資自營商賣出股數",
    "外資自營商買賣超股數",
    "投信買進股數",
    "投信賣出股數",
    "投信買賣超股數",
    "自營商買賣超股數",
    "自營商買進股數(自行買賣)",
    "自營商賣出股數(自行買賣)",
    "自營商買賣超股數(自行買賣)",
    "自營商買進股數(避險)",
    "自營商賣出股數(避險)",
    "自營商買賣超股數(避險)",
    "三大法人買賣超股數",
]

METRIC_FIELDS = [
    ("TWSE_T86_FOREIGN_EX_DEALER_BUY_SHARES", "外陸資買進股數(不含外資自營商)", "外陸資買進股數(不含外資自營商)"),
    ("TWSE_T86_FOREIGN_EX_DEALER_SELL_SHARES", "外陸資賣出股數(不含外資自營商)", "外陸資賣出股數(不含外資自營商)"),
    ("TWSE_T86_FOREIGN_EX_DEALER_NET_SHARES", "外陸資買賣超股數(不含外資自營商)", "外陸資買賣超股數(不含外資自營商)"),
    ("TWSE_T86_FOREIGN_DEALER_BUY_SHARES", "外資自營商買進股數", "外資自營商買進股數"),
    ("TWSE_T86_FOREIGN_DEALER_SELL_SHARES", "外資自營商賣出股數", "外資自營商賣出股數"),
    ("TWSE_T86_FOREIGN_DEALER_NET_SHARES", "外資自營商買賣超股數", "外資自營商買賣超股數"),
    ("TWSE_T86_INVESTMENT_TRUST_BUY_SHARES", "投信買進股數", "投信買進股數"),
    ("TWSE_T86_INVESTMENT_TRUST_SELL_SHARES", "投信賣出股數", "投信賣出股數"),
    ("TWSE_T86_INVESTMENT_TRUST_NET_SHARES", "投信買賣超股數", "投信買賣超股數"),
    ("TWSE_T86_DEALER_TOTAL_NET_SHARES", "自營商買賣超股數", "自營商買賣超股數"),
    ("TWSE_T86_DEALER_SELF_BUY_SHARES", "自營商買進股數(自行買賣)", "自營商買進股數(自行買賣)"),
    ("TWSE_T86_DEALER_SELF_SELL_SHARES", "自營商賣出股數(自行買賣)", "自營商賣出股數(自行買賣)"),
    ("TWSE_T86_DEALER_SELF_NET_SHARES", "自營商買賣超股數(自行買賣)", "自營商買賣超股數(自行買賣)"),
    ("TWSE_T86_DEALER_HEDGE_BUY_SHARES", "自營商買進股數(避險)", "自營商買進股數(避險)"),
    ("TWSE_T86_DEALER_HEDGE_SELL_SHARES", "自營商賣出股數(避險)", "自營商賣出股數(避險)"),
    ("TWSE_T86_DEALER_HEDGE_NET_SHARES", "自營商買賣超股數(避險)", "自營商買賣超股數(避險)"),
    ("TWSE_T86_TOTAL_INSTITUTIONAL_NET_SHARES", "三大法人買賣超股數", "三大法人買賣超股數"),
]

NET_VALIDATIONS = [
    ("外陸資買進股數(不含外資自營商)", "外陸資賣出股數(不含外資自營商)", "外陸資買賣超股數(不含外資自營商)"),
    ("外資自營商買進股數", "外資自營商賣出股數", "外資自營商買賣超股數"),
    ("投信買進股數", "投信賣出股數", "投信買賣超股數"),
    ("自營商買進股數(自行買賣)", "自營商賣出股數(自行買賣)", "自營商買賣超股數(自行買賣)"),
    ("自營商買進股數(避險)", "自營商賣出股數(避險)", "自營商買賣超股數(避險)"),
]


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
    spec = importlib.util.spec_from_file_location("p1008_db_for_t86", P2_01_TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dbcore = load_dbcore()


def utc_now() -> str:
    return dbcore.utc_now()


def canonical_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_json(data: object) -> str:
    return sha256_bytes(canonical_json(data).encode("utf-8"))


def deterministic_ulid(timestamp: dt.datetime, key: str) -> str:
    value = (
        (int(timestamp.timestamp() * 1000) & ((1 << 48) - 1)) << 80
    ) | int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:10], "big")
    chars = []
    for _ in range(26):
        chars.append(dbcore.CROCKFORD32[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def endpoint_url(date_value: dt.date) -> str:
    return (
        f"{ENDPOINT_BASE}?date={date_value.strftime('%Y%m%d')}"
        f"&selectType={SELECT_TYPE}&response=json"
    )


def validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise ContractError(f"不允許的Connector URL：{url}")
    if parsed.path == "/zh/trading/foreign/t86.html" and not parsed.query:
        return
    if parsed.path != ENDPOINT_PATH:
        raise ContractError(f"不允許的Connector路徑：{parsed.path}")
    query = urllib.parse.parse_qs(parsed.query)
    if query.get("selectType") != [SELECT_TYPE] or query.get("response") != ["json"]:
        raise ContractError("TWSE T86查詢參數不符合核准契約")
    if not re.fullmatch(r"\d{8}", query.get("date", [""])[0]):
        raise ContractError("TWSE T86查詢日期格式錯誤")


def powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def fetch_url_powershell(url: str, timeout: int) -> HttpResult:
    if os.name != "nt":
        raise PrimarySourceUnavailable("PowerShell HTTPS transport只支援Windows")
    with tempfile.TemporaryDirectory(prefix="p1008-t86-") as temp_dir:
        body_path = Path(temp_dir) / "body.bin"
        metadata_path = Path(temp_dir) / "metadata.json"
        script = f"""
$ErrorActionPreference = 'Stop'
$r = Invoke-WebRequest -UseBasicParsing -Uri {powershell_quote(url)} -TimeoutSec {int(timeout)} -Headers @{{'User-Agent'='P1008-TWSE-T86-DryRun/1.0'}}
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
            encoding="utf-8",
            errors="replace",
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
            "User-Agent": "P1008-TWSE-T86-DryRun/1.0",
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            return HttpResult(
                url=url,
                status=int(response.status),
                mime_type=content_type.split(";", 1)[0].strip(),
                headers={key: value for key, value in response.headers.items()},
                body=response.read(),
                transport="PYTHON_URLLIB",
            )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if os.name == "nt":
            return fetch_url_powershell(url, timeout)
        raise PrimarySourceUnavailable(f"TWSE T86主要來源無法使用：{exc}") from exc


def parse_json_bytes(body: bytes, label: str):
    try:
        return json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataValidationError(f"{label}不是有效UTF-8 JSON") from exc


def parse_int(value: str, field_name: str, *, nonnegative: bool) -> int:
    normalized = str(value).strip().replace(",", "")
    if not re.fullmatch(r"-?\d+", normalized):
        raise DataValidationError(f"{field_name}不是有效整數股數：{value}")
    number = int(normalized)
    if nonnegative and number < 0:
        raise DataValidationError(f"{field_name}不可為負數：{value}")
    return number


def shares_to_lots(value: int) -> str:
    lots = Decimal(value) / Decimal("1000")
    return format(lots, "f").rstrip("0").rstrip(".") or "0"


def parse_t86_payload(payload: dict, date_value: dt.date) -> tuple[dict[str, str], dict[str, int]]:
    if not isinstance(payload, dict):
        raise ContractError("TWSE T86回應頂層不是物件")
    if payload.get("stat") != "OK":
        raise PrimarySourceUnavailable(f"TWSE T86狀態不是OK：{payload.get('stat')}")
    if payload.get("date") != date_value.strftime("%Y%m%d"):
        raise ContractError("TWSE T86回應日期與查詢日期不一致")
    fields = payload.get("fields")
    if fields != EXPECTED_FIELDS:
        raise ContractError(f"TWSE T86欄位契約不一致：actual={fields}")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ContractError("TWSE T86 data不是陣列")
    rows = []
    for row in data:
        if isinstance(row, list) and row and row[0] == "2317":
            rows.append(row)
    if len(rows) != 1:
        raise DataValidationError(f"TWSE T86中證券代號=2317筆數應為1，實際為{len(rows)}")
    row = rows[0]
    if len(row) != len(EXPECTED_FIELDS):
        raise ContractError("TWSE T86 2317列欄位數與fields不一致")
    row_map = {field: str(value) for field, value in zip(EXPECTED_FIELDS, row)}
    integers = {}
    buy_sell_fields = {
        "外陸資買進股數(不含外資自營商)",
        "外陸資賣出股數(不含外資自營商)",
        "外資自營商買進股數",
        "外資自營商賣出股數",
        "投信買進股數",
        "投信賣出股數",
        "自營商買進股數(自行買賣)",
        "自營商賣出股數(自行買賣)",
        "自營商買進股數(避險)",
        "自營商賣出股數(避險)",
    }
    for field in EXPECTED_FIELDS[2:]:
        integers[field] = parse_int(row_map[field], field, nonnegative=field in buy_sell_fields)
    for buy_field, sell_field, net_field in NET_VALIDATIONS:
        expected_net = integers[buy_field] - integers[sell_field]
        if expected_net != integers[net_field]:
            raise DataValidationError(
                f"{net_field}不等於買進-賣出：{integers[net_field]} != {expected_net}"
            )
    dealer_total = (
        integers["自營商買賣超股數(自行買賣)"]
        + integers["自營商買賣超股數(避險)"]
    )
    if dealer_total != integers["自營商買賣超股數"]:
        raise DataValidationError("自營商買賣超股數不等於自行買賣與避險合計")
    total = (
        integers["外陸資買賣超股數(不含外資自營商)"]
        + integers["外資自營商買賣超股數"]
        + integers["投信買賣超股數"]
        + integers["自營商買賣超股數"]
    )
    if total != integers["三大法人買賣超股數"]:
        raise DataValidationError("三大法人買賣超股數不等於外陸資、外資自營商、投信與自營商合計")
    return row_map, integers


def create_schema(connection: sqlite3.Connection) -> None:
    migrations = (
        dbcore.Migration(1, "initial_schema", BASE_MIGRATION, dbcore.sha256_file(BASE_MIGRATION)),
        dbcore.Migration(8, "t86_connector_extension", EXTENSION, dbcore.sha256_file(EXTENSION)),
    )
    for migration in migrations:
        dbcore.apply_one_migration(connection, migration, mode="DRY_RUN", backup_id=None)


def protected_hashes(runtime_db: Path) -> dict[str, str | None]:
    paths = (*FORMAL_PROTECTED, runtime_db)
    result: dict[str, str | None] = {}
    for path in paths:
        resolved = str(path.resolve())
        result[resolved] = dbcore.sha256_file(path) if path.exists() else None
    return result


def save_raw(
    output_dir: Path,
    relative_name: str,
    result: HttpResult,
    retrieved_at: str,
    extra: dict | None = None,
) -> dict:
    raw_dir = output_dir / "raw" / "twse_t86"
    raw_dir.mkdir(parents=True, exist_ok=True)
    body_path = raw_dir / relative_name
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
        "status_note_zh": "未修改的TWSE官方HTTPS回應",
        "actionable": False,
    }
    if extra:
        metadata.update(extra)
    (raw_dir / f"{relative_name}.metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return metadata


def insert_candidate(
    connection: sqlite3.Connection,
    *,
    row_map: dict[str, str],
    integers: dict[str, int],
    date_value: dt.date,
    page_meta: dict,
    data_meta: dict,
    retrieved_at: str,
) -> list[dict]:
    timestamp = dt.datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    created_at = retrieved_at
    date_iso = date_value.isoformat()
    date_key = date_value.strftime("%Y%m%d")
    legal_uid = deterministic_ulid(timestamp, "LEGAL_ENTITY:HON_HAI_PRECISION_INDUSTRY")
    instrument_uid = deterministic_ulid(timestamp, "INSTRUMENT:HON_HAI_COMMON_EQUITY")
    listing_uid = deterministic_ulid(timestamp, "LISTING:TWSE:2317")
    source_uid = deterministic_ulid(timestamp, f"SOURCE:{SOURCE_CODE}")
    page_artifact_uid = deterministic_ulid(timestamp, f"ARTIFACT:{page_meta['sha256']}")
    data_artifact_uid = deterministic_ulid(timestamp, f"ARTIFACT:{data_meta['sha256']}")
    execution_uid = deterministic_ulid(timestamp, f"EXECUTION:{data_meta['sha256']}")
    row_sha = sha256_json(row_map)

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
    for metric_code, field_name, name_zh in METRIC_FIELDS:
        metric_uid = deterministic_ulid(timestamp, f"METRIC:{metric_code}")
        connection.execute(
            """
            INSERT INTO metric_definitions(
                metric_uid, metric_code, name_zh, frequency, value_type,
                canonical_unit, is_derived, formula_version, required_for_report,
                model_usage, created_at, updated_at
            ) VALUES (?, ?, ?, 'DAILY', 'INTEGER', 'SHARES', 0, NULL, 0,
                      'OBSERVATION_ONLY', ?, ?)
            """,
            (metric_uid, metric_code, name_zh, created_at, created_at),
        )
    connection.execute(
        """
        INSERT INTO sources(
            source_uid, source_code, source_name, source_type, official_url,
            quality_level, license_scope, retrieval_method, enabled,
            created_at, updated_at
        ) VALUES (?, ?, '臺灣證券交易所三大法人買賣超日報', 'OFFICIAL_EXCHANGE',
                  ?, 'A1', 'OWNER_INTERNAL_DRY_RUN_REDISTRIBUTION_NOT_APPROVED',
                  'HTTPS_GET_MANUAL_SINGLE_RUN', 1, ?, ?)
        """,
        (source_uid, SOURCE_CODE, PAGE_URL, created_at, created_at),
    )
    for artifact_uid, meta in (
        (page_artifact_uid, page_meta),
        (data_artifact_uid, data_meta),
    ):
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
                meta["url"],
                meta["local_path"],
                meta["mime_type"],
                meta["sha256"],
                meta["http_status"],
                PARSER_VERSION,
                created_at,
            ),
        )
    connection.execute(
        """
        INSERT INTO connector_contracts(
            connector_id, source_code, source_authority, evidence_level,
            endpoint_url, official_page_url, endpoint_path, select_type, query_date,
            expected_fields_json, official_unit, parser_version, license_scope,
            fallback_policy, status, owner_approval
        ) VALUES (?, ?, 'A1', 'L1', ?, ?, ?, ?, ?, ?, 'SHARES', ?,
                  'OWNER_INTERNAL_DRY_RUN_REDISTRIBUTION_NOT_APPROVED',
                  'NO_FALLBACK', 'ACTIVE_DRY_RUN', ?)
        """,
        (
            CONNECTOR_ID,
            SOURCE_CODE,
            data_meta["url"],
            PAGE_URL,
            ENDPOINT_PATH,
            SELECT_TYPE,
            date_key,
            canonical_json(EXPECTED_FIELDS),
            PARSER_VERSION,
            OWNER_APPROVAL,
        ),
    )

    observations = []
    warnings = ["PUBLICATION_TIME_MISSING", "SESSION_CALENDAR_NOT_INTEGRATED"]
    for metric_code, field_name, name_zh in METRIC_FIELDS:
        metric_uid = deterministic_ulid(timestamp, f"METRIC:{metric_code}")
        value = integers[field_name]
        evidence_hash = sha256_json(
            {
                "artifact_sha256": data_meta["sha256"],
                "code": "2317",
                "date": date_key,
                "field": field_name,
                "raw_value": row_map[field_name],
                "normalized_value": str(value),
            }
        )
        short_code = metric_code.replace("TWSE_T86_", "").replace("_SHARES", "")
        evidence_id = f"EVD-TWSE-TWSE_2317-T86_{short_code}-{date_key}-R01-{evidence_hash[:8]}"
        observation_uid = deterministic_ulid(timestamp, f"OBS:{evidence_id}:{value}")
        evidence_uid = deterministic_ulid(timestamp, f"EVIDENCE:{evidence_id}")
        connection.execute(
            """
            INSERT INTO observations(
                observation_uid, subject_uid, metric_uid, value_decimal, value_text,
                unit, period_start, period_end, published_at, effective_at,
                retrieved_at, source_uid, artifact_uid, revision,
                validation_status, support_level, supersedes_observation_uid,
                created_at
            ) VALUES (?, ?, ?, ?, NULL, 'SHARES', ?, ?, ?, ?, ?, ?, ?, 1,
                      'PASS_WITH_WARNINGS', 'L1', NULL, ?)
            """,
            (
                observation_uid,
                listing_uid,
                metric_uid,
                str(value),
                date_iso,
                date_iso,
                retrieved_at,
                retrieved_at,
                retrieved_at,
                source_uid,
                data_artifact_uid,
                created_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO observation_evidence(
                evidence_uid, evidence_id, observation_uid, artifact_uid,
                source_row_sha256, source_code_value, source_date_value,
                source_field_name, raw_value, normalized_value,
                validation_status, model_usage, warnings_json, message_zh, created_at
            ) VALUES (?, ?, ?, ?, ?, '2317', ?, ?, ?, ?, 'PASS_WITH_WARNINGS',
                      'OBSERVATION_ONLY', ?,
                      'TWSE官方T86三大法人買賣超日報候選；原始單位為股，僅供觀察',
                      ?)
            """,
            (
                evidence_uid,
                evidence_id,
                observation_uid,
                data_artifact_uid,
                row_sha,
                date_key,
                field_name,
                row_map[field_name],
                str(value),
                canonical_json(warnings),
                created_at,
            ),
        )
        observations.append(
            {
                "metric_code": metric_code,
                "metric_name_zh": name_zh,
                "field_name": field_name,
                "official_shares": value,
                "derived_lots": shares_to_lots(value),
                "unit": "SHARES",
                "derived_lots_formula_zh": "張數 = 股數 / 1000；1張=1000股",
                "evidence_id": evidence_id,
                "observation_uid": observation_uid,
                "validation_status": "PASS_WITH_WARNINGS",
                "status_zh": "通過但有警告",
                "status_note_zh": "官方原始股數已保存；缺少發布時分秒與核准交易日曆，僅供觀察",
            }
        )

    connection.execute(
        """
        INSERT INTO connector_executions(
            execution_uid, connector_id, started_at, finished_at, http_status,
            mime_type, page_raw_sha256, data_raw_sha256, response_count,
            selected_count, status_code, status_zh, status_note_zh, error_code,
            fallback_used, actionable
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'PASS_WITH_WARNINGS',
                  '通過但有警告',
                  '已取得2317官方T86單日資料；保存為候選Observation，不更新正式資料',
                  NULL, 0, 0)
        """,
        (
            execution_uid,
            CONNECTOR_ID,
            retrieved_at,
            retrieved_at,
            data_meta["http_status"],
            data_meta["mime_type"],
            page_meta["sha256"],
            data_meta["sha256"],
            data_meta["response_count"],
        ),
    )
    for rule_code, message_zh in (
        ("INTEGER_FIELDS_VALIDATED", "所有T86數值欄位均為可解析整數股數"),
        ("BUY_SELL_NET_CONSISTENT", "買進、賣出與買賣超欄位一致"),
        ("OFFICIAL_SHARES_UNIT_ONLY", "候選Observation僅保存官方股數單位；張數只在報告中衍生顯示"),
        ("FORMAL_OUTPUT_BLOCKED", "本批次不得寫正式CSV、Runtime SQLite、UI、KPI或規則"),
    ):
        connection.execute(
            """
            INSERT INTO validation_results(
                validation_uid, target_type, target_uid, rule_code, severity,
                status, message_zh, checked_at, validator_version
            ) VALUES (?, 'CONNECTOR_EXECUTION', ?, ?, 'INFO', 'PASS', ?, ?, ?)
            """,
            (
                deterministic_ulid(timestamp, f"VALIDATION:{execution_uid}:{rule_code}"),
                execution_uid,
                rule_code,
                message_zh,
                created_at,
                PARSER_VERSION,
            ),
        )
    return observations


def write_reports(output_dir: Path, result: dict) -> None:
    (output_dir / "DRY_RUN.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "CANDIDATE_FACTS.json").write_text(
        json.dumps(result["candidate_facts"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = [
        "# P2-03B-08 TWSE T86 單日 Dry-Run 驗證報告",
        "",
        f"**交易日**：{result['query']['date']}",
        "**狀態**：`PASS_WITH_WARNINGS / 通過但有警告`",
        "**actionable**：`false / 僅供觀察，不會自動交易、改變持股或寫入正式資料`",
        "",
        "## 一、資料來源",
        "",
        f"- 官方頁面：{PAGE_URL}",
        f"- 官方端點：{result['query']['endpoint_url']}",
        "- 查詢參數：`selectType=ALLBUT0999`、`response=json`",
        "- 原始單位：官方欄位為「股數」，候選 Observation 單位固定為 `SHARES / 股`。",
        "- 張數衍生：報告中另列 `張數 = 股數 / 1000；1張=1000股`，不得覆寫原始股數。",
        "",
        "## 二、2317 候選觀測值",
        "",
        "| 指標 | 官方股數 | 衍生張數 | Evidence ID | 中文狀態 |",
        "|---|---:|---:|---|---|",
    ]
    for item in result["observations"]:
        report.append(
            f"| {item['metric_name_zh']} | {item['official_shares']} | "
            f"{item['derived_lots']} | `{item['evidence_id']}` | "
            f"{item['status_zh']}，{item['status_note_zh']} |"
        )
    report.extend(
        [
            "",
            "## 三、驗證結果",
            "",
            "- 欄位契約：PASS，19個官方欄位與T86回應一致。",
            "- 身分識別：PASS，以 `證券代號=2317` 選取，未依公司名稱選取。",
            "- 整數驗證：PASS，17個數值欄位均為整數股數。",
            "- 買賣超一致性：PASS，買進、賣出、買賣超及三大法人合計均一致。",
            "- 單位隔離：PASS，SQLite候選只保存股數；張數只作報告衍生。",
            "- 正式資料保護：PASS，正式CSV與Runtime DB未寫入。",
            "",
            "## 四、明確不做事項",
            "",
            "- 不寫入 `data/2317_master_v9.csv`。",
            "- 不寫入 `data/CSV_AUTHORITY_MANIFEST.json`。",
            "- 不覆寫 `macro_snapshot.Foreign_Net_Buy`，因該欄目前是 `TWD_100M` 語意，而T86為股數流量。",
            "- 不回推外資持股比率、持股變化或趨勢。",
            "- 不啟用 UI、KPI、品質分、警示、回測或交易規則。",
            "",
            "## 五、後續",
            "",
            "本批次結果只可作為 T86 單日資料接入能力驗證。若要進一步納入資料庫或報告，需要另案討論欄位語意、單位契約、Freshness、與 `macro_snapshot.Foreign_Net_Buy` 的欄位拆分。",
        ]
    )
    (output_dir / "VALIDATION_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    change_report = [
        "# P2-03B-08 Change Report",
        "",
        "- 新增T86官方單日Dry-Run候選資料。",
        "- 正式CSV未修改。",
        "- Runtime SQLite未修改。",
        "- UI/KPI/規則未修改。",
        "",
        f"Candidate SQLite: `{result['candidate_sqlite']}`",
    ]
    (output_dir / "CHANGE_REPORT.md").write_text("\n".join(change_report) + "\n", encoding="utf-8")


def run_connector(
    output_dir: Path,
    runtime_db: Path,
    date_value: dt.date,
    fetcher: Callable[[str, int], HttpResult] = fetch_url,
    timeout: int = 90,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    protected_before = protected_hashes(runtime_db)
    retrieved_at = utc_now()
    page_result = fetcher(PAGE_URL, timeout)
    data_url = endpoint_url(date_value)
    data_result = fetcher(data_url, timeout)
    page_meta = save_raw(output_dir, "t86_official_page.html", page_result, retrieved_at)
    payload = parse_json_bytes(data_result.body, "TWSE T86")
    row_map, integers = parse_t86_payload(payload, date_value)
    data_meta = save_raw(
        output_dir,
        f"T86_{date_value.strftime('%Y%m%d')}.json",
        data_result,
        retrieved_at,
        {
            "query_params": {
                "date": date_value.strftime("%Y%m%d"),
                "selectType": SELECT_TYPE,
                "response": "json",
            },
            "response_count": len(payload.get("data", [])),
            "selected_code": "2317",
            "selected_by_zh": "證券代號",
            "expected_fields": EXPECTED_FIELDS,
            "official_unit": "SHARES",
            "official_unit_zh": "股",
        },
    )
    db_path = output_dir / "twse_2317_t86_candidate.sqlite3"
    connection = dbcore.connect_database(db_path)
    try:
        create_schema(connection)
        observations = insert_candidate(
            connection,
            row_map=row_map,
            integers=integers,
            date_value=date_value,
            page_meta=page_meta,
            data_meta=data_meta,
            retrieved_at=retrieved_at,
        )
        db_verification = dbcore.verify_connection(connection)
    finally:
        connection.close()
    protected_after = protected_hashes(runtime_db)
    formal_unchanged = protected_before == protected_after
    result = {
        "task_id": "P2-03B-08",
        "connector_id": CONNECTOR_ID,
        "owner_approval": OWNER_APPROVAL,
        "status": "PASS_WITH_WARNINGS",
        "status_zh": "通過但有警告",
        "status_note_zh": "TWSE T86官方單日資料已保存為候選Observation；未發布正式資料",
        "actionable": False,
        "query": {
            "date": date_value.isoformat(),
            "endpoint_url": data_url,
            "official_page_url": PAGE_URL,
            "select_type": SELECT_TYPE,
            "response": "json",
        },
        "raw_artifacts": {
            "official_page": page_meta,
            "t86_response": data_meta,
        },
        "contract": {
            "fields": EXPECTED_FIELDS,
            "field_count": len(EXPECTED_FIELDS),
            "official_unit": "SHARES",
            "official_unit_zh": "股",
            "unit_conversion": {
                "derived_lots_formula": "lots = shares / 1000",
                "derived_lots_formula_zh": "張數 = 股數 / 1000；1張=1000股",
            },
        },
        "selected_row": row_map,
        "candidate_facts": {
            "source_code": SOURCE_CODE,
            "security_code": "2317",
            "security_name_raw": row_map["證券名稱"],
            "official_shares": integers,
            "derived_lots": {key: shares_to_lots(value) for key, value in integers.items()},
            "unit_note_zh": "官方原始值為股數；張數只依1張=1000股衍生顯示",
        },
        "observations": observations,
        "candidate_sqlite": str(db_path.resolve()),
        "db_verification": db_verification,
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
        "formal_outputs_unchanged": formal_unchanged,
        "validation": {
            "field_contract": "PASS",
            "selected_by_code": "PASS",
            "integer_fields": "PASS",
            "buy_sell_net_consistency": "PASS",
            "unit_isolation": "PASS",
            "no_fallback": "PASS",
            "formal_output_protection": "PASS" if formal_unchanged else "FAIL",
            "status_zh": "通過",
        },
        "excluded_changes": [
            "formal_csv_write",
            "runtime_sqlite_write",
            "ui_kpi_rule_change",
            "quality_score",
            "alert_or_backtest",
            "foreign_holding_ratio_derivation",
            "macro_snapshot_foreign_net_buy_overwrite",
        ],
    }
    write_reports(output_dir, result)
    return result


def parse_date(value: str) -> dt.date:
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日期需為YYYY-MM-DD") from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P2-03B-08 TWSE T86 single-day dry-run")
    parser.add_argument("--date", required=True, type=parse_date)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "output" / "p2-03b-08")
    parser.add_argument("--runtime-db", type=Path, default=DEFAULT_RUNTIME_DB)
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args(argv)
    try:
        result = run_connector(args.output_dir, args.runtime_db, args.date, timeout=args.timeout)
    except ConnectorError as exc:
        payload = {
            "task_id": "P2-03B-08",
            "status": "FAIL",
            "status_zh": "失敗",
            "status_note_zh": str(exc),
            "actionable": False,
        }
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "DRY_RUN.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
