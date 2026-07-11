from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
P2_01_TOOL = PROJECT_ROOT / "db" / "tools" / "p1008_db.py"
BASE_MIGRATION = PROJECT_ROOT / "db" / "migrations" / "0001_initial_schema.sql"
EXTENSION_MIGRATION = PROJECT_ROOT / "db" / "p2-02" / "legacy_migration_extension.sql"
DEFAULT_RUNTIME_DB = (
    Path(os.environ.get("LOCALAPPDATA", PROJECT_ROOT / "staging"))
    / "P1008"
    / "data"
    / "warroom.sqlite3"
)
PARSER_VERSION = "p2-02.1"


def load_p2_01_tool():
    spec = importlib.util.spec_from_file_location("p1008_db_for_p202", P2_01_TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dbcore = load_p2_01_tool()


@dataclass(frozen=True)
class FieldSpec:
    name_zh: str
    target_kind: str
    classification: str
    value_type: str
    unit: str | None = None
    metric_code: str | None = None
    formula_id: str | None = None


@dataclass(frozen=True)
class ParsedRow:
    source_line: int
    logical_row_number: int
    values: list[str]
    row_sha256: str


@dataclass(frozen=True)
class DatasetSpec:
    code: str
    file_name: str
    source_code: str
    source_token: str
    subject_key: str
    subject_token: str
    frequency: str
    row_key_column: str
    period_column: str
    fields: dict[str, FieldSpec]


def context(name_zh: str, classification: str = "IDENTITY_CONTEXT", value_type: str = "TEXT"):
    return FieldSpec(name_zh, "CONTEXT", classification, value_type)


def metadata(name_zh: str):
    return FieldSpec(name_zh, "METADATA", "GOVERNANCE_METADATA", "TEXT")


def raw(name_zh: str, value_type: str, unit: str | None = None, *, estimated: bool = False):
    classification = "ESTIMATED_FACT" if estimated else "RAW_FACT"
    return FieldSpec(name_zh, "OBSERVATION", classification, value_type, unit)


def normalized(name_zh: str, value_type: str, unit: str | None = None):
    return FieldSpec(name_zh, "OBSERVATION", "NORMALIZED_FACT", value_type, unit)


def derived(name_zh: str, value_type: str, unit: str | None = None):
    target = "DERIVED_METRIC" if value_type == "DECIMAL" else "OBSERVATION_LEGACY_DERIVED"
    classification = "LEGACY_DERIVED" if value_type == "DECIMAL" else "LEGACY_INFERENCE"
    return FieldSpec(
        name_zh,
        target,
        classification,
        value_type,
        unit,
        formula_id="LEGACY_UNVERIFIED",
    )


MASTER_FIELDS = {
    "Quarter": context("季度"),
    "QuarterEndDate": context("季末日期", "TIME_AXIS", "DATE"),
    "EstimatedEffectiveDate": context("估算有效日期", "TIME_AXIS", "DATE"),
    "Revenue_Q_100M": raw("單季營收", "DECIMAL", "TWD_100M"),
    "GrossMarginPct": raw("毛利率", "DECIMAL", "PERCENT"),
    "OperatingIncome_Q_100M": raw("單季營業利益", "DECIMAL", "TWD_100M"),
    "OperatingMarginPct": derived("營業利益率", "DECIMAL", "PERCENT"),
    "OperatingMarginStatus": derived("營業利益率狀態", "TEXT"),
    "TaxExpense_Q_1M": raw("單季所得稅費用", "DECIMAL", "TWD_1M"),
    "TaxRev_Pct": derived("稅費營收比", "DECIMAL", "PERCENT"),
    "TaxRevMean_Pct": derived("稅費營收比平均", "DECIMAL", "PERCENT"),
    "TaxRevStd_Pct": derived("稅費營收比標準差", "DECIMAL", "PERCENT"),
    "TaxZ": derived("稅務Z分數", "DECIMAL", "SCORE"),
    "TaxZ_Status": derived("稅務Z狀態", "TEXT"),
    "EPS_Q": raw("單季每股盈餘", "DECIMAL", "TWD_PER_SHARE"),
    "EPS_YoY_Pct": derived("單季EPS年增率", "DECIMAL", "PERCENT"),
    "EPS_TTM": derived("近四季每股盈餘", "DECIMAL", "TWD_PER_SHARE"),
    "BVPS": raw("每股淨值", "DECIMAL", "TWD_PER_SHARE"),
    "QuarterEndClose": raw("季末收盤價", "DECIMAL", "TWD_PER_SHARE"),
    "CloseAdjusted": derived("還原權值收盤價", "DECIMAL", "TWD_PER_SHARE"),
    "ROE_Annual_Pct": raw("年度股東權益報酬率", "DECIMAL", "PERCENT"),
    "ROE_TTM_Pct": derived("近四季股東權益報酬率", "DECIMAL", "PERCENT"),
    "PB_QuarterEnd": derived("季末股價淨值比", "DECIMAL", "RATIO"),
    "PB_Adjusted": derived("還原權值股價淨值比", "DECIMAL", "RATIO"),
    "PB_Zone": derived("股價淨值比區間", "TEXT"),
    "ROE_Signal": derived("ROE訊號標籤", "TEXT"),
    "payoutRatio_Pct": derived("配息率", "DECIMAL", "PERCENT"),
    "CashDividend": raw("現金股利", "DECIMAL", "TWD_PER_SHARE"),
    "DividendYield_Pct": derived("現金殖利率", "DECIMAL", "PERCENT"),
    "FCF_Annual_100M": raw("年度自由現金流", "DECIMAL", "TWD_100M"),
    "MarketCap_100M": derived("季末市值", "DECIMAL", "TWD_100M"),
    "FCFYield_Annual_Pct": derived("年度自由現金流殖利率", "DECIMAL", "PERCENT"),
    "ROIC_Approx_Pct": derived("近似投入資本報酬率", "DECIMAL", "PERCENT"),
    "ROIC_Precise_Pct": derived("精確投入資本報酬率", "DECIMAL", "PERCENT"),
    "ROIC_Status": derived("投入資本報酬率狀態", "TEXT"),
    "NOPAT_Annual_100M": derived("年化稅後營業利益", "DECIMAL", "TWD_100M"),
    "InvestedCapital_100M": derived("投入資本", "DECIMAL", "TWD_100M"),
    "Cash_100M": raw("現金及約當現金", "DECIMAL", "TWD_100M"),
    "InterestBearingDebt_100M": raw("有息負債", "DECIMAL", "TWD_100M"),
    "NetDebt_100M": derived("淨負債", "DECIMAL", "TWD_100M"),
    "NetDebtStatus": derived("淨負債狀態", "TEXT"),
    "EBITDA_Approx_100M": derived("近似EBITDA", "DECIMAL", "TWD_100M"),
    "DA_Est_100M": raw("估算折舊攤銷", "DECIMAL", "TWD_100M", estimated=True),
    "NetDebtToEBITDA_Approx": derived("近似淨負債對EBITDA", "DECIMAL", "RATIO"),
    "NetDebtToEBITDA_Status": derived("淨負債對EBITDA狀態", "TEXT"),
    "BalanceSheetDataQuality": metadata("資產負債表資料品質"),
    "DataSource": metadata("資料來源"),
    "DataSupportLevel": metadata("資料支援等級"),
    "LookaheadRisk": metadata("前視偏誤風險"),
    "Notes": metadata("資料備註"),
    "ForeignHoldRatio_Pct": raw("外資持股比例", "DECIMAL", "PERCENT", estimated=True),
    "ForeignHoldChange_Pct": derived("外資持股季度變化", "DECIMAL", "PERCENT"),
    "ForeignHoldTrend": derived("外資持股趨勢", "TEXT"),
    "AI_Revenue_Pct": raw("AI營收占比", "DECIMAL", "PERCENT", estimated=True),
}

DAILY_FIELDS = {
    "Date": context("交易日期", "TIME_AXIS", "DATE"),
    "Close": raw("收盤價", "DECIMAL", "TWD_PER_SHARE"),
    "QuarterKey": context("參照季度"),
    "BVPS_ref": normalized("參照每股淨值", "DECIMAL", "TWD_PER_SHARE"),
    "PB_daily": derived("每日股價淨值比", "DECIMAL", "RATIO"),
    "DataSupportLevel": metadata("資料支援等級"),
    "Status": metadata("資料列狀態"),
}

MACRO_FIELDS = {
    "Date": context("快照日期", "TIME_AXIS", "DATE"),
    "TWD_USD": raw("美元兌新台幣", "DECIMAL", "TWD_PER_USD"),
    "VIX": raw("VIX恐慌指數", "DECIMAL", "INDEX_POINT"),
    "WTI_Oil": raw("WTI原油價格", "DECIMAL", "USD_PER_BARREL"),
    "US_10Y_Yield": raw("美國十年期公債殖利率", "DECIMAL", "PERCENT"),
    "Fed_Rate": raw("聯邦基金利率", "DECIMAL", "PERCENT"),
    "Fed_Hike_Prob_YE": raw("年底升息機率", "DECIMAL", "PERCENT"),
    "DXY": raw("美元指數", "DECIMAL", "INDEX_POINT"),
    "US_GDP_QoQ": raw("美國GDP季增率", "DECIMAL", "PERCENT"),
    "US_CPI_YoY": raw("美國CPI年增率", "DECIMAL", "PERCENT"),
    "TW_GDP_QoQ": raw("台灣GDP季增率", "DECIMAL", "PERCENT"),
    "TAIEX_Weekly_Chg": raw("台股週變動率", "DECIMAL", "PERCENT"),
    "CSP_Capex_Signal": derived("CSP資本支出訊號", "TEXT"),
    "Hon_Hai_Rev_YoY": raw("鴻海營收年增率或描述", "TEXT"),
    "Foreign_Net_Buy": raw("外資買賣超", "DECIMAL", "TWD_100M"),
    "TW_Export_YoY": raw("台灣出口年增率", "DECIMAL", "PERCENT"),
    "RiskLevel": derived("市場風險等級", "TEXT"),
    "RiskNote": derived("市場風險說明", "TEXT"),
}

DATASETS = (
    DatasetSpec(
        "MASTER_V9",
        "2317_master_v9.csv",
        "CSV_MASTER_V9",
        "CSVM9",
        "LISTING:TWSE:2317",
        "TWSE_2317",
        "QUARTERLY",
        "Quarter",
        "Quarter",
        MASTER_FIELDS,
    ),
    DatasetSpec(
        "DAILY_PRICE",
        "2317_daily_price.csv",
        "CSV_DAILY_L3",
        "CSVDLY",
        "LISTING:TWSE:2317",
        "TWSE_2317",
        "DAILY",
        "Date",
        "Date",
        DAILY_FIELDS,
    ),
    DatasetSpec(
        "MACRO_SNAPSHOT",
        "macro_snapshot.csv",
        "CSV_MACRO_L3",
        "CSVMAC",
        "MACRO:GLOBAL_TW_US",
        "MACRO_GLOBAL",
        "EVENT",
        "Date",
        "Date",
        MACRO_FIELDS,
    ),
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


def stable_ulid(timestamp: dt.datetime, key: str) -> str:
    timestamp_ms = int(timestamp.timestamp() * 1000) & ((1 << 48) - 1)
    randomness = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:10], "big")
    value = (timestamp_ms << 80) | randomness
    chars = []
    for _ in range(26):
        chars.append(dbcore.CROCKFORD32[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def timestamp_for_period(period: str) -> dt.datetime:
    if re.fullmatch(r"\d{4}Q[1-4]", period):
        year, quarter = int(period[:4]), int(period[-1])
        month = quarter * 3
        day = 31 if month in (3, 12) else 30
        return dt.datetime(year, month, day, tzinfo=dt.timezone.utc)
    return dt.datetime.combine(parse_date(period), dt.time.min, tzinfo=dt.timezone.utc)


def iso_z(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_decimal(raw_value: str) -> str:
    candidate = raw_value.strip().replace(",", "")
    if candidate.endswith("%"):
        candidate = candidate[:-1]
    if candidate.startswith("+"):
        candidate = candidate[1:]
    try:
        number = Decimal(candidate)
    except InvalidOperation as exc:
        raise ValueError(f"不是有效Decimal：{raw_value}") from exc
    if not number.is_finite():
        raise ValueError(f"Decimal不可為非有限值：{raw_value}")
    normalized = format(number, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    if normalized in ("", "-0"):
        normalized = "0"
    return normalized


def parse_csv_with_lines(path: Path) -> tuple[list[str], int, list[ParsedRow]]:
    header = None
    header_line = 0
    rows: list[ParsedRow] = []
    logical = 0
    for source_line, physical_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if not physical_line.strip() or physical_line.lstrip().startswith("#"):
            continue
        values = next(csv.reader([physical_line]))
        if header is None:
            header = [item.strip() for item in values]
            header_line = source_line
            continue
        logical += 1
        rows.append(
            ParsedRow(
                source_line=source_line,
                logical_row_number=logical,
                values=[item.strip() for item in values],
                row_sha256=sha256_text(physical_line),
            )
        )
    if not header:
        raise ValueError(f"找不到CSV表頭：{path}")
    return header, header_line, rows


def metric_code(dataset: DatasetSpec, column: str, field: FieldSpec) -> str:
    if field.metric_code:
        return field.metric_code
    return f"{dataset.code}.{column}".upper()


def validation_note(field: FieldSpec) -> str:
    if field.classification == "LEGACY_DERIVED":
        return "Legacy數值公式尚未驗證，僅供遷移比較"
    if field.classification == "LEGACY_INFERENCE":
        return "Legacy文字判讀邏輯尚未驗證，僅供觀察"
    if field.classification == "ESTIMATED_FACT":
        return "來源欄位屬估算或人工整理，僅供觀察"
    if field.classification == "NORMALIZED_FACT":
        return "來源為Legacy參照值，尚未完成跨檔Evidence去重"
    return "來源為既有L3 CSV，已保留原值與來源位置"


def schema_migrations() -> list:
    return [
        dbcore.Migration(1, "initial_schema", BASE_MIGRATION, dbcore.sha256_file(BASE_MIGRATION)),
        dbcore.Migration(
            2,
            "p2_02_legacy_migration_extension",
            EXTENSION_MIGRATION,
            dbcore.sha256_file(EXTENSION_MIGRATION),
        ),
    ]


def create_staging_schema(connection: sqlite3.Connection) -> None:
    for migration in schema_migrations():
        dbcore.apply_one_migration(connection, migration, mode="DRY_RUN", backup_id=None)
    checks = dbcore.verify_connection(connection)
    if checks["integrity_check_status"] != "PASS" or checks["foreign_key_check_status"] != "PASS":
        raise RuntimeError("staging Schema完整性檢查失敗")


def ensure_headers_match(dataset: DatasetSpec, header: list[str]) -> None:
    expected = list(dataset.fields)
    if header != expected:
        missing = [field for field in expected if field not in header]
        unknown = [field for field in header if field not in expected]
        raise ValueError(
            f"{dataset.file_name}表頭未完全映射；missing={missing}, unknown={unknown}"
        )


def insert_subjects(connection: sqlite3.Connection, created_at: str) -> dict[str, str]:
    base = dt.datetime(2026, 6, 22, tzinfo=dt.timezone.utc)
    subjects = [
        ("LEGAL_ENTITY:HON_HAI_PRECISION_INDUSTRY", "COMPANY", "鴻海精密工業股份有限公司", None, None, None, None),
        ("INSTRUMENT:HON_HAI_COMMON_EQUITY", "SECURITY", "鴻海普通股", None, None, None, "LEGAL_ENTITY:HON_HAI_PRECISION_INDUSTRY"),
        ("LISTING:TWSE:2317", "SECURITY", "鴻海普通股臺灣證券交易所掛牌", "2317", "TWSE", "TWD", "INSTRUMENT:HON_HAI_COMMON_EQUITY"),
        ("MACRO:GLOBAL_TW_US", "MACRO", "台灣與美國總經快照", None, None, None, None),
    ]
    uids = {key: stable_ulid(base, f"subject:{key}") for key, *_ in subjects}
    for key, subject_type, name, ticker, market, currency, parent_key in subjects:
        connection.execute(
            """
            INSERT INTO subjects(
                subject_uid, subject_type, canonical_key, name, ticker, market,
                isin, cik, currency, parent_subject_uid, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, 'ACTIVE', ?, ?)
            """,
            (
                uids[key],
                subject_type,
                key,
                name,
                ticker,
                market,
                currency,
                uids.get(parent_key),
                created_at,
                created_at,
            ),
        )
    return uids


def insert_sources_and_artifacts(
    connection: sqlite3.Connection, created_at: str
) -> tuple[dict[str, str], dict[str, str], dict[str, dict]]:
    base = dt.datetime(2026, 6, 22, tzinfo=dt.timezone.utc)
    source_uids: dict[str, str] = {}
    artifact_uids: dict[str, str] = {}
    artifacts: dict[str, dict] = {}
    for dataset in DATASETS:
        path = DATA_DIR / dataset.file_name
        source_uid = stable_ulid(base, f"source:{dataset.source_code}")
        artifact_uid = stable_ulid(
            dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc),
            f"artifact:{dataset.file_name}:{dbcore.sha256_file(path)}",
        )
        source_uids[dataset.code] = source_uid
        artifact_uids[dataset.code] = artifact_uid
        retrieved_at = iso_z(dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc))
        connection.execute(
            """
            INSERT INTO sources(
                source_uid, source_code, source_name, source_type, official_url,
                quality_level, license_scope, retrieval_method, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, 'LEGACY_CSV', NULL, 'A3', 'OWNER_INTERNAL_USE',
                      'READ_ONLY_FILE', 1, ?, ?)
            """,
            (
                source_uid,
                dataset.source_code,
                f"{dataset.file_name}唯讀遷移來源",
                created_at,
                created_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO raw_artifacts(
                artifact_uid, source_uid, retrieved_at, source_url, local_path,
                mime_type, sha256, http_status, parser_version, created_at
            ) VALUES (?, ?, ?, ?, ?, 'text/csv', ?, NULL, ?, ?)
            """,
            (
                artifact_uid,
                source_uid,
                retrieved_at,
                f"local://data/{dataset.file_name}",
                f"data/{dataset.file_name}",
                dbcore.sha256_file(path),
                PARSER_VERSION,
                created_at,
            ),
        )
        artifacts[dataset.code] = {
            "path": path,
            "sha256": dbcore.sha256_file(path),
            "retrieved_at": retrieved_at,
        }
    return source_uids, artifact_uids, artifacts


def insert_field_mappings(
    connection: sqlite3.Connection,
    run_uid: str,
    created_at: str,
) -> tuple[dict[tuple[str, str], str], list[dict]]:
    metric_uids: dict[tuple[str, str], str] = {}
    output: list[dict] = []
    base = dt.datetime(2026, 6, 22, tzinfo=dt.timezone.utc)
    for dataset in DATASETS:
        for ordinal, (column, field) in enumerate(dataset.fields.items(), start=1):
            code = None
            metric_uid = None
            if field.target_kind not in ("CONTEXT", "METADATA"):
                code = metric_code(dataset, column, field)
                metric_uid = stable_ulid(base, f"metric:{code}")
                metric_uids[(dataset.code, column)] = metric_uid
                is_derived = field.classification in ("LEGACY_DERIVED", "LEGACY_INFERENCE")
                connection.execute(
                    """
                    INSERT INTO metric_definitions(
                        metric_uid, metric_code, name_zh, frequency, value_type,
                        canonical_unit, is_derived, formula_version,
                        required_for_report, model_usage, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'OBSERVATION_ONLY', ?, ?)
                    """,
                    (
                        metric_uid,
                        code,
                        field.name_zh,
                        dataset.frequency,
                        field.value_type,
                        field.unit,
                        int(is_derived),
                        "LEGACY_UNVERIFIED" if is_derived else None,
                        created_at,
                        created_at,
                    ),
                )
            mapping_uid = stable_ulid(base, f"mapping:{run_uid}:{dataset.code}:{column}")
            note = validation_note(field)
            status = "PASS_WITH_WARNINGS" if field.target_kind not in ("CONTEXT", "METADATA") else "PASS"
            connection.execute(
                """
                INSERT INTO legacy_field_mappings(
                    mapping_uid, legacy_run_uid, dataset_code, source_column,
                    source_ordinal, target_kind, metric_uid, metric_code, name_zh,
                    value_type, canonical_unit, classification, formula_id,
                    validation_status, model_usage, status_note_zh
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OBSERVATION_ONLY', ?)
                """,
                (
                    mapping_uid,
                    run_uid,
                    dataset.code,
                    column,
                    ordinal,
                    field.target_kind,
                    metric_uid,
                    code,
                    field.name_zh,
                    field.value_type,
                    field.unit,
                    field.classification,
                    field.formula_id,
                    status,
                    note,
                ),
            )
            output.append(
                {
                    "dataset_code": dataset.code,
                    "source_column": column,
                    "source_ordinal": ordinal,
                    "target_kind": field.target_kind,
                    "metric_code": code,
                    "name_zh": field.name_zh,
                    "value_type": field.value_type,
                    "canonical_unit": field.unit,
                    "classification": field.classification,
                    "formula_id": field.formula_id,
                    "validation_status": status,
                    "model_usage": "OBSERVATION_ONLY",
                    "status_note_zh": note,
                }
            )
    return metric_uids, output


def period_times(dataset: DatasetSpec, row: dict[str, str], artifact_retrieved_at: str):
    if dataset.code == "MASTER_V9":
        period_start = f"{row['Quarter'][:4]}-{(int(row['Quarter'][-1]) - 1) * 3 + 1:02d}-01"
        period_end = row["QuarterEndDate"]
        effective = f"{row['EstimatedEffectiveDate']}T00:00:00Z"
        published = effective
    else:
        period_start = row["Date"]
        period_end = row["Date"]
        effective = f"{row['Date']}T00:00:00Z"
        published = effective
    retrieved = max(artifact_retrieved_at, effective)
    return period_start, period_end, published, effective, retrieved


def safe_token(value: str) -> str:
    return re.sub(r"[^A-Z0-9_]", "_", value.upper()).strip("_")


def migrate_dataset(
    connection: sqlite3.Connection,
    dataset: DatasetSpec,
    run_uid: str,
    subject_uid: str,
    source_uid: str,
    artifact_uid: str,
    artifact: dict,
    metric_uids: dict[tuple[str, str], str],
    created_at: str,
) -> dict:
    header, header_line, parsed_rows = parse_csv_with_lines(artifact["path"])
    ensure_headers_match(dataset, header)
    valid_rows = 0
    invalid_rows = 0
    observation_count = 0
    derived_count = 0
    evidence_count = 0
    empty_cells = 0
    decimal_count = 0
    invalid_details: list[dict] = []
    row_mapping: list[dict] = []
    for parsed in parsed_rows:
        issues = []
        if len(parsed.values) != len(header):
            issues.append(f"欄數{len(parsed.values)}，預期{len(header)}")
            row = {
                header[index]: parsed.values[index] if index < len(parsed.values) else ""
                for index in range(len(header))
            }
            row_status = "EXCLUDED_INVALID"
            invalid_rows += 1
        else:
            row = dict(zip(header, parsed.values))
            row_status = "VALID"
            valid_rows += 1
        row_key = row.get(dataset.row_key_column) or f"LINE_{parsed.source_line}"
        period_key = row.get(dataset.period_column) or row_key
        row_uid = stable_ulid(
            timestamp_for_period(period_key) if row_status == "VALID" else dt.datetime(2026, 6, 22, tzinfo=dt.timezone.utc),
            f"legacy-row:{artifact['sha256']}:{parsed.source_line}:{parsed.row_sha256}",
        )
        connection.execute(
            """
            INSERT INTO legacy_source_rows(
                legacy_row_uid, legacy_run_uid, artifact_uid, dataset_code,
                source_file, source_line, logical_row_number, row_key, period_key,
                raw_row_sha256, source_row_json, row_status, issues_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_uid,
                run_uid,
                artifact_uid,
                dataset.code,
                dataset.file_name,
                parsed.source_line,
                parsed.logical_row_number,
                row_key,
                period_key,
                parsed.row_sha256,
                dbcore.canonical_json(row),
                row_status,
                dbcore.canonical_json(issues),
                created_at,
            ),
        )
        row_mapping.append(
            {
                "dataset_code": dataset.code,
                "source_file": dataset.file_name,
                "source_line": parsed.source_line,
                "logical_row_number": parsed.logical_row_number,
                "row_key": row_key,
                "period_key": period_key,
                "legacy_row_uid": row_uid,
                "row_status": row_status,
                "issues": issues,
            }
        )
        if row_status != "VALID":
            invalid_details.append(row_mapping[-1])
            continue

        period_start, period_end, published, effective, retrieved = period_times(
            dataset, row, artifact["retrieved_at"]
        )
        for ordinal, column in enumerate(header, start=1):
            field = dataset.fields[column]
            if field.target_kind in ("CONTEXT", "METADATA"):
                continue
            raw_value = row[column]
            if raw_value in ("", "N/A"):
                empty_cells += 1
                continue
            normalized_value = (
                normalize_decimal(raw_value)
                if field.value_type == "DECIMAL"
                else raw_value.strip()
            )
            if field.value_type == "DECIMAL":
                decimal_count += 1
                if Decimal(normalized_value) != Decimal(
                    raw_value.strip().replace("%", "").replace("+", "").replace(",", "")
                ):
                    raise ValueError(f"Decimal精度不一致：{dataset.file_name}:{parsed.source_line}:{column}")
            code = metric_code(dataset, column, field)
            hash_material = dbcore.canonical_json(
                {
                    "artifact_sha256": artifact["sha256"],
                    "source_line": parsed.source_line,
                    "column": column,
                    "raw_value": raw_value,
                    "normalized_value": normalized_value,
                    "period_key": period_key,
                }
            )
            evidence_hash = sha256_text(hash_material)
            evidence_id = (
                f"EVD-{dataset.source_token}-{dataset.subject_token}-"
                f"{safe_token(column)}-{safe_token(period_key)}-R01-{evidence_hash[:8]}"
            )
            timestamp = timestamp_for_period(period_key)
            evidence_uid = stable_ulid(timestamp, f"evidence:{evidence_id}")
            target_uid = stable_ulid(timestamp, f"target:{evidence_id}")
            validation_status = "PASS_WITH_WARNINGS"
            note = validation_note(field)
            if field.target_kind == "DERIVED_METRIC":
                connection.execute(
                    """
                    INSERT INTO derived_metrics(
                        derived_uid, subject_uid, metric_uid, value_decimal, as_of,
                        formula_id, formula_version, calculated_at,
                        validation_status, created_at
                    ) VALUES (?, ?, ?, ?, ?, 'LEGACY_UNVERIFIED', '0.0.0', ?,
                              'PASS_WITH_WARNINGS', ?)
                    """,
                    (
                        target_uid,
                        subject_uid,
                        metric_uids[(dataset.code, column)],
                        normalized_value,
                        effective,
                        created_at,
                        created_at,
                    ),
                )
                observation_uid = None
                derived_uid = target_uid
                derived_count += 1
            else:
                value_decimal = normalized_value if field.value_type == "DECIMAL" else None
                value_text = normalized_value if field.value_type != "DECIMAL" else None
                connection.execute(
                    """
                    INSERT INTO observations(
                        observation_uid, subject_uid, metric_uid, value_decimal,
                        value_text, unit, period_start, period_end, published_at,
                        effective_at, retrieved_at, source_uid, artifact_uid,
                        revision, validation_status, support_level,
                        supersedes_observation_uid, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1,
                              'PASS_WITH_WARNINGS', 'L3', NULL, ?)
                    """,
                    (
                        target_uid,
                        subject_uid,
                        metric_uids[(dataset.code, column)],
                        value_decimal,
                        value_text,
                        field.unit,
                        period_start,
                        period_end,
                        published,
                        effective,
                        retrieved,
                        source_uid,
                        artifact_uid,
                        created_at,
                    ),
                )
                observation_uid = target_uid
                derived_uid = None
                observation_count += 1
            connection.execute(
                """
                INSERT INTO evidence_records(
                    evidence_uid, evidence_id, legacy_run_uid, legacy_row_uid,
                    artifact_uid, observation_uid, derived_uid, source_column,
                    source_ordinal, raw_value, normalized_value, period_key,
                    revision, evidence_hash_sha256, validation_status,
                    model_usage, message_zh, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?,
                          ?, 'OBSERVATION_ONLY', ?, ?)
                """,
                (
                    evidence_uid,
                    evidence_id,
                    run_uid,
                    row_uid,
                    artifact_uid,
                    observation_uid,
                    derived_uid,
                    column,
                    ordinal,
                    raw_value,
                    normalized_value,
                    period_key,
                    evidence_hash,
                    validation_status,
                    note,
                    created_at,
                ),
            )
            evidence_count += 1
    return {
        "dataset_code": dataset.code,
        "file_name": dataset.file_name,
        "header_line": header_line,
        "column_count": len(header),
        "source_rows": len(parsed_rows),
        "valid_rows": valid_rows,
        "excluded_invalid_rows": invalid_rows,
        "observations": observation_count,
        "derived_metrics": derived_count,
        "evidence_records": evidence_count,
        "empty_metric_cells": empty_cells,
        "decimal_values": decimal_count,
        "invalid_details": invalid_details,
        "row_mapping": row_mapping,
    }


def write_csv(path: Path, rows: Iterable[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def run_migration(output_dir: Path, runtime_db: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    staging_db = output_dir / "warroom_p2_02_dryrun.sqlite3"
    runtime_hash_before = dbcore.sha256_file(runtime_db)
    source_hashes = {
        dataset.file_name: dbcore.sha256_file(DATA_DIR / dataset.file_name)
        for dataset in DATASETS
    }
    created_at = dbcore.utc_now()
    run_id = f"P2-02-{created_at.replace('-', '').replace(':', '')}"
    run_uid = stable_ulid(
        dt.datetime.now(dt.timezone.utc),
        f"legacy-run:{run_id}:{dbcore.canonical_json(source_hashes)}",
    )
    connection = dbcore.connect_database(staging_db)
    try:
        create_staging_schema(connection)
        connection.execute(
            """
            INSERT INTO legacy_migration_runs(
                legacy_run_uid, run_id, started_at, finished_at, status,
                status_zh, status_note_zh, source_hashes_json,
                runtime_database_sha256_before, runtime_database_sha256_after,
                actionable
            ) VALUES (?, ?, ?, NULL, 'RUNNING', '執行中',
                      'CSV唯讀遷移Dry-Run執行中', ?, ?, NULL, 0)
            """,
            (run_uid, run_id, created_at, dbcore.canonical_json(source_hashes), runtime_hash_before),
        )
        subjects = insert_subjects(connection, created_at)
        sources, artifacts_uids, artifacts = insert_sources_and_artifacts(connection, created_at)
        metric_uids, field_mapping = insert_field_mappings(connection, run_uid, created_at)
        dataset_results = []
        all_row_mappings = []
        connection.execute("BEGIN IMMEDIATE")
        try:
            for dataset in DATASETS:
                result = migrate_dataset(
                    connection,
                    dataset,
                    run_uid,
                    subjects[dataset.subject_key],
                    sources[dataset.code],
                    artifacts_uids[dataset.code],
                    artifacts[dataset.code],
                    metric_uids,
                    created_at,
                )
                all_row_mappings.extend(result.pop("row_mapping"))
                dataset_results.append(result)
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        checks = dbcore.verify_connection(connection)
        evidence_orphans = connection.execute(
            """
            SELECT COUNT(*) FROM evidence_records e
            LEFT JOIN legacy_source_rows r ON r.legacy_row_uid=e.legacy_row_uid
            WHERE r.legacy_row_uid IS NULL
            """
        ).fetchone()[0]
        target_orphans = connection.execute(
            """
            SELECT COUNT(*) FROM evidence_records e
            LEFT JOIN observations o ON o.observation_uid=e.observation_uid
            LEFT JOIN derived_metrics d ON d.derived_uid=e.derived_uid
            WHERE (e.observation_uid IS NOT NULL AND o.observation_uid IS NULL)
               OR (e.derived_uid IS NOT NULL AND d.derived_uid IS NULL)
            """
        ).fetchone()[0]
        runtime_hash_after = dbcore.sha256_file(runtime_db)
        if runtime_hash_before != runtime_hash_after:
            raise RuntimeError("Runtime SQLite SHA-256發生變更，Dry-Run立即失敗")
        finished_at = dbcore.utc_now()
        connection.execute(
            """
            UPDATE legacy_migration_runs
            SET finished_at=?, status='PASS', status_zh='通過',
                status_note_zh='CSV唯讀遷移Dry-Run完成',
                runtime_database_sha256_after=?
            WHERE legacy_run_uid=?
            """,
            (finished_at, runtime_hash_after, run_uid),
        )
    except Exception:
        if dbcore.table_exists(connection, "legacy_migration_runs"):
            connection.execute(
                """
                UPDATE legacy_migration_runs
                SET finished_at=?, status='FAIL', status_zh='失敗',
                    status_note_zh='CSV唯讀遷移Dry-Run失敗',
                    runtime_database_sha256_after=?
                WHERE legacy_run_uid=?
                """,
                (
                    dbcore.utc_now(),
                    dbcore.sha256_file(runtime_db),
                    run_uid,
                ),
            )
        raise
    finally:
        connection.close()

    staging_hash = dbcore.sha256_file(staging_db)
    summary = {
        "batch_id": "P2-02",
        "run_id": run_id,
        "generated_at": finished_at,
        "status": "PASS",
        "status_zh": "通過",
        "status_note_zh": "三份CSV已唯讀遷移至staging拋棄式SQLite並完成追溯驗證",
        "actionable": False,
        "owner_acceptance": "PENDING",
        "runtime_database": {
            "path": str(runtime_db.resolve()),
            "sha256_before": runtime_hash_before,
            "sha256_after": runtime_hash_after,
            "unchanged": runtime_hash_before == runtime_hash_after,
        },
        "staging_database": {
            "path": str(staging_db.resolve()),
            "sha256": staging_hash,
            "schema_version": checks["schema_version"],
            "integrity_check_status": checks["integrity_check_status"],
            "foreign_key_check_status": checks["foreign_key_check_status"],
        },
        "source_hashes": source_hashes,
        "datasets": dataset_results,
        "totals": {
            "source_rows": sum(item["source_rows"] for item in dataset_results),
            "valid_rows": sum(item["valid_rows"] for item in dataset_results),
            "excluded_invalid_rows": sum(item["excluded_invalid_rows"] for item in dataset_results),
            "observations": sum(item["observations"] for item in dataset_results),
            "derived_metrics": sum(item["derived_metrics"] for item in dataset_results),
            "evidence_records": sum(item["evidence_records"] for item in dataset_results),
            "empty_metric_cells": sum(item["empty_metric_cells"] for item in dataset_results),
            "decimal_values": sum(item["decimal_values"] for item in dataset_results),
            "field_mappings": len(field_mapping),
            "evidence_row_orphans": evidence_orphans,
            "evidence_target_orphans": target_orphans,
        },
        "limitations_zh": [
            "所有遷移值維持OBSERVATION_ONLY，不代表正式升格",
            "Legacy衍生值公式尚未驗證，統一標示LEGACY_UNVERIFIED",
            "每日與總經CSV的發布時間只有日期，暫以UTC 00:00保存並標示警告",
            "macro_snapshot.csv欄數異常資料列已排除，不修改原檔",
        ],
    }
    (output_dir / "DRY_RUN.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "FIELD_MAPPING.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "status_zh": "通過",
                "status_note_zh": "三份CSV全部欄位已建立明確Mapping",
                "actionable": False,
                "mappings": field_mapping,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    write_csv(
        output_dir / "ROW_MAPPING.csv",
        all_row_mappings,
        [
            "dataset_code",
            "source_file",
            "source_line",
            "logical_row_number",
            "row_key",
            "period_key",
            "legacy_row_uid",
            "row_status",
            "issues",
        ],
    )
    return summary


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P1008 P2-02 CSV唯讀遷移Dry-Run")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--runtime-db", type=Path, default=DEFAULT_RUNTIME_DB)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    now = dt.datetime.now(dt.timezone.utc)
    output_dir = args.output_dir or (
        PROJECT_ROOT
        / "staging"
        / "p2-02"
        / now.strftime("%Y-%m-%d")
        / f"run_{now.strftime('%Y%m%dT%H%M%SZ')}"
    )
    try:
        output = run_migration(output_dir, args.runtime_db)
        print(json.dumps(output, ensure_ascii=False, indent=2))
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

