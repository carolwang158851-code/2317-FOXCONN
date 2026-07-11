from __future__ import annotations

import argparse
import base64
import copy
import csv
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
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
    PROJECT_ROOT / "db" / "p2-03b-07" / "foreign_holding_connector_extension.sql"
)
ENDPOINT_BASE = "https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS"
PAGE_URL = "https://www.twse.com.tw/zh/trading/foreign/mi-qfiis.html"
ALLOWED_HOST = "www.twse.com.tw"
SELECT_TYPE = "ALLBUT0999"
CONNECTOR_ID = "TWSE_MI_QFIIS_2317_QUARTERLY_V1"
SOURCE_CODE = "TWSE_FOREIGN_MAINLAND_HOLDING"
PARSER_VERSION = "p2-03b-07.1"
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
MASTER_CSV = FORMAL_CSVS[0]
AUTHORITY_MANIFEST = PROJECT_ROOT / "data" / "CSV_AUTHORITY_MANIFEST.json"
FORMAL_PROTECTED = (*FORMAL_CSVS, AUTHORITY_MANIFEST)

EXPECTED_FIELDS = [
    "證券代號",
    "證券名稱",
    "國際證券編碼",
    "發行股數",
    "外資及陸資尚可投資股數",
    "全體外資及陸資持有股數",
    "外資及陸資尚可投資比率",
    "全體外資及陸資持股比率",
    "外資及陸資共用法令投資上限比率",
    "陸資法令投資上限比率",
    "與前日異動原因(註)",
    "最近一次上市公司申報外資及陸資持股異動日期",
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
    spec = importlib.util.spec_from_file_location("p1008_db_for_foreign_holding", P2_01_TOOL)
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


def validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise ContractError(f"不允許的Connector URL：{url}")
    if parsed.path != "/rwd/zh/fund/MI_QFIIS":
        raise ContractError(f"不允許的Connector路徑：{parsed.path}")
    query = urllib.parse.parse_qs(parsed.query)
    if query.get("selectType") != [SELECT_TYPE] or query.get("response") != ["json"]:
        raise ContractError("TWSE外資持股查詢參數不符合核准契約")
    if not re.fullmatch(r"\d{8}", query.get("date", [""])[0]):
        raise ContractError("TWSE外資持股查詢日期格式錯誤")


def powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def fetch_url_powershell(url: str, timeout: int) -> HttpResult:
    if os.name != "nt":
        raise PrimarySourceUnavailable("PowerShell HTTPS transport只支援Windows")
    with tempfile.TemporaryDirectory(prefix="p1008-foreign-holding-") as temp_dir:
        body_path = Path(temp_dir) / "body.bin"
        metadata_path = Path(temp_dir) / "metadata.json"
        script = f"""
$ErrorActionPreference = 'Stop'
$r = Invoke-WebRequest -UseBasicParsing -Uri {powershell_quote(url)} -TimeoutSec {int(timeout)} -Headers @{{'User-Agent'='P1008-TWSE-Foreign-Holding-DryRun/1.0'}}
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
            "User-Agent": "P1008-TWSE-Foreign-Holding-DryRun/1.0",
            "Accept": "application/json",
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
        raise PrimarySourceUnavailable(f"TWSE主要來源無法使用：{exc}") from exc


def endpoint_url(date_value: dt.date) -> str:
    return (
        f"{ENDPOINT_BASE}?date={date_value.strftime('%Y%m%d')}"
        f"&selectType={SELECT_TYPE}&response=json"
    )


def quarter_end(year: int, quarter: int) -> dt.date:
    return {
        1: dt.date(year, 3, 31),
        2: dt.date(year, 6, 30),
        3: dt.date(year, 9, 30),
        4: dt.date(year, 12, 31),
    }[quarter]


def required_quarters() -> list[dict]:
    result = []
    year, quarter = 2020, 4
    while (year, quarter) <= (2026, 1):
        result.append(
            {
                "quarter": f"{year}Q{quarter}",
                "quarter_end": quarter_end(year, quarter),
                "is_candidate_row": (year, quarter) >= (2021, 1),
            }
        )
        quarter += 1
        if quarter == 5:
            year += 1
            quarter = 1
    return result


def parse_json(body: bytes) -> dict:
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataValidationError("TWSE回應不是有效UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ContractError("TWSE回應頂層不是物件")
    return payload


def decimal_value(value: object, field: str) -> Decimal:
    candidate = str(value).replace(",", "").strip()
    try:
        result = Decimal(candidate)
    except InvalidOperation as exc:
        raise DataValidationError(f"{field}不是有效Decimal：{value}") from exc
    if not result.is_finite():
        raise DataValidationError(f"{field}不是有限Decimal")
    return result


def decimal_text(value: Decimal, places: str | None = None) -> str:
    if places is not None:
        value = value.quantize(Decimal(places))
    result = format(value, "f")
    if places is None and "." in result:
        result = result.rstrip("0").rstrip(".")
    return result or "0"


def parse_snapshot(payload: dict, expected_date: dt.date) -> dict | None:
    if payload.get("stat") != "OK":
        return None
    if payload.get("date") != expected_date.strftime("%Y%m%d"):
        raise DataValidationError(
            f"TWSE回應日期與查詢日期不一致：{payload.get('date')}"
        )
    if payload.get("fields") != EXPECTED_FIELDS:
        raise ContractError("TWSE MI_QFIIS欄位契約不一致")
    rows = [
        row
        for row in payload.get("data", [])
        if isinstance(row, list) and len(row) == len(EXPECTED_FIELDS) and row[0] == "2317"
    ]
    if len(rows) != 1:
        if not rows:
            return None
        raise DataValidationError(f"TWSE回應中2317筆數不是1：{len(rows)}")
    row = dict(zip(EXPECTED_FIELDS, rows[0]))
    if row["國際證券編碼"] != "TW0002317005":
        raise DataValidationError(f"2317 ISIN錯誤：{row['國際證券編碼']}")
    issued = decimal_value(row["發行股數"], "發行股數")
    holding = decimal_value(row["全體外資及陸資持有股數"], "持有股數")
    declared = decimal_value(row["全體外資及陸資持股比率"], "持股比率")
    recomputed = holding / issued * Decimal("100")
    difference = abs(declared - recomputed)
    if difference > Decimal("0.01"):
        raise DataValidationError(
            f"官方持股比率與股數重算差異超過0.01個百分點：{difference}"
        )
    return {
        "official_as_of_date": expected_date.isoformat(),
        "row": row,
        "issued_shares": decimal_text(issued),
        "available_investment_shares": decimal_text(
            decimal_value(row["外資及陸資尚可投資股數"], "尚可投資股數")
        ),
        "holding_shares": decimal_text(holding),
        "available_ratio_pct": decimal_text(
            decimal_value(row["外資及陸資尚可投資比率"], "尚可投資比率"),
            "0.01",
        ),
        "holding_ratio_pct": decimal_text(declared, "0.01"),
        "recomputed_ratio_pct": decimal_text(recomputed, "0.000001"),
        "recompute_difference_pct": decimal_text(difference, "0.000001"),
        "common_legal_limit_pct": decimal_text(
            decimal_value(row["外資及陸資共用法令投資上限比率"], "共用法令上限"),
            "0.01",
        ),
        "mainland_legal_limit_pct": decimal_text(
            decimal_value(row["陸資法令投資上限比率"], "陸資法令上限"),
            "0.01",
        ),
        "notes": str(payload.get("notes", "")),
        "total": int(payload.get("total", len(payload.get("data", [])))),
    }


def collect_snapshot(
    item: dict,
    fetcher: Callable[[str, int], HttpResult],
    *,
    max_lookback_days: int = 10,
    sleep_seconds: float = 0.0,
) -> tuple[dict, HttpResult, list[dict]]:
    attempts = []
    for offset in range(max_lookback_days + 1):
        requested = item["quarter_end"] - dt.timedelta(days=offset)
        url = endpoint_url(requested)
        result = fetcher(url, 90)
        if result.status != 200:
            raise PrimarySourceUnavailable(f"TWSE HTTP狀態不是200：{result.status}")
        if result.mime_type != "application/json":
            raise ContractError(f"TWSE回應MIME不是application/json：{result.mime_type}")
        payload = parse_json(result.body)
        parsed = parse_snapshot(payload, requested)
        attempts.append(
            {
                "requested_date": requested.isoformat(),
                "http_status": result.status,
                "stat": payload.get("stat"),
                "selected": parsed is not None,
            }
        )
        if parsed is not None:
            parsed.update(
                {
                    "quarter": item["quarter"],
                    "requested_quarter_end": item["quarter_end"].isoformat(),
                    "date_alignment_status": (
                        "EXACT_QUARTER_END"
                        if offset == 0
                        else "PRIOR_AVAILABLE_DATE"
                    ),
                    "lookback_days": offset,
                    "is_candidate_row": item["is_candidate_row"],
                    "transport": result.transport,
                }
            )
            return parsed, result, attempts
        if sleep_seconds:
            time.sleep(sleep_seconds)
    raise DataValidationError(
        f"{item['quarter']}在季末前{max_lookback_days}日內找不到2317官方資料"
    )


def build_series(snapshots: list[dict]) -> list[dict]:
    ordered = sorted(snapshots, key=lambda item: item["quarter"])
    if len(ordered) != 22 or ordered[0]["quarter"] != "2020Q4":
        raise DataValidationError("官方季末序列必須包含2020Q4至2026Q1共22期")
    result = []
    for prior, current in zip(ordered, ordered[1:]):
        prior_ratio = Decimal(prior["holding_ratio_pct"])
        ratio = Decimal(current["holding_ratio_pct"])
        change = ratio - prior_ratio
        trend = (
            "RISING"
            if change > Decimal("0.5")
            else "DECLINING"
            if change < Decimal("-0.5")
            else "STABLE"
        )
        result.append(
            {
                "quarter": current["quarter"],
                "ratio_pct": decimal_text(ratio, "0.01"),
                "prior_ratio_pct": decimal_text(prior_ratio, "0.01"),
                "change_pct_point": decimal_text(change, "0.01"),
                "trend": trend,
                "snapshot": current,
            }
        )
    if len(result) != 21 or result[-1]["quarter"] != "2026Q1":
        raise DataValidationError("正式候選序列必須包含2021Q1至2026Q1共21期")
    return result


def read_master() -> tuple[list[str], list[str], list[dict[str, str]]]:
    lines = MASTER_CSV.read_text(encoding="utf-8-sig").splitlines()
    comments = [line for line in lines if line.startswith("##")]
    data_lines = [line for line in lines if line.strip() and not line.startswith("##")]
    reader = csv.DictReader(data_lines)
    if reader.fieldnames is None:
        raise DataValidationError("正式master缺少表頭")
    rows = list(reader)
    if len(rows) != 21 or len(reader.fieldnames) != 54:
        raise DataValidationError("正式master列數或欄數不符21x54")
    return comments, reader.fieldnames, rows


def update_comments(comments: list[str]) -> list[str]:
    replacements = {
        "## version:": "## version: v9.3-candidate",
        "## lastUpdated:": "## lastUpdated: 2026-06-22",
        "## foreignNote:": "## foreignNote: TWSE official quarter-end foreign and mainland area holding ratio",
        "## foreignDataQuality:": "## foreignDataQuality: OFFICIAL_TWSE_A1_L1 / OBSERVATION_ONLY",
        "## foreignSource:": "## foreignSource: TWSE MI_QFIIS selectType=ALLBUT0999; 2020Q4 derivation baseline + 2021Q1~2026Q1 official series",
    }
    result = []
    seen = set()
    for line in comments:
        replaced = line
        for prefix, value in replacements.items():
            if line.startswith(prefix):
                replaced = value
                seen.add(prefix)
                break
        if line.startswith("## changeLog:") and "v9.3" not in line:
            replaced = (
                line
                + "; v9.3 replaced foreign holding interpolation with TWSE official MI_QFIIS quarter-end series"
            )
        result.append(replaced)
    for prefix, value in replacements.items():
        if prefix not in seen:
            result.append(value)
    result.extend(
        [
            "## foreignCorrection_v9_3: ForeignHoldRatio_Pct now means TWSE official all foreign and mainland area holding ratio",
            "## foreignDerivation_v9_3: ForeignHoldChange_Pct=current official ratio-prior official ratio; ForeignHoldTrend uses +/-0.5pp thresholds",
            "## foreignRuleUsage_v9_3: OBSERVATION_ONLY; no automatic alert, score, backtest, or trading rule activation",
        ]
    )
    return result


def csv_bytes(comments: list[str], fieldnames: list[str], rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO(newline="")
    for line in comments:
        buffer.write(line + "\n")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def build_master_candidate(series: list[dict]) -> tuple[bytes, list[dict], list[dict]]:
    comments, fieldnames, rows = read_master()
    by_quarter = {item["quarter"]: item for item in series}
    if set(by_quarter) != {row["Quarter"] for row in rows}:
        raise DataValidationError("官方序列與正式master季度集合不一致")
    changes = []
    untouched_hashes = {}
    target_fields = {
        "ForeignHoldRatio_Pct",
        "ForeignHoldChange_Pct",
        "ForeignHoldTrend",
    }
    for row in rows:
        untouched = {key: value for key, value in row.items() if key not in target_fields}
        untouched_hashes[row["Quarter"]] = sha256_json(untouched)
        official = by_quarter[row["Quarter"]]
        replacements = {
            "ForeignHoldRatio_Pct": official["ratio_pct"],
            "ForeignHoldChange_Pct": official["change_pct_point"],
            "ForeignHoldTrend": official["trend"],
        }
        for field, after in replacements.items():
            before = row[field]
            changes.append(
                {
                    "quarter": row["Quarter"],
                    "field": field,
                    "before": before,
                    "after": after,
                    "changed": before != after,
                    "official_as_of_date": official["snapshot"]["official_as_of_date"],
                    "date_alignment_status": official["snapshot"]["date_alignment_status"],
                }
            )
            row[field] = after
    content = csv_bytes(update_comments(comments), fieldnames, rows)
    parsed_lines = [
        line
        for line in content.decode("utf-8").splitlines()
        if line.strip() and not line.startswith("##")
    ]
    candidate_rows = list(csv.DictReader(parsed_lines))
    for row in candidate_rows:
        untouched = {key: value for key, value in row.items() if key not in target_fields}
        if sha256_json(untouched) != untouched_hashes[row["Quarter"]]:
            raise DataValidationError(f"{row['Quarter']}非外資欄位發生未核准變更")
    return content, changes, candidate_rows


def build_authority_candidate(master_content: bytes) -> bytes:
    manifest = copy.deepcopy(
        json.loads(AUTHORITY_MANIFEST.read_text(encoding="utf-8-sig"))
    )
    manifest["approvalSource"] = (
        "Owner conversation approvals P1008 items 16-18, 25-29, 75, 77, 80 "
        "and approved P2-03B-07 Release Manifest"
    )
    target = next(
        item
        for item in manifest["authoritativeFiles"]
        if item["path"] == "data/2317_master_v9.csv"
    )
    target["fileVersion"] = "v9.3"
    target["sha256"] = sha256_bytes(master_content)
    target["fileSizeBytes"] = len(master_content)
    overrides = target.setdefault("fieldOverrides", {})
    overrides["ForeignHoldRatio_Pct"] = {
        "quality": "OFFICIAL_TWSE_A1_L1",
        "ruleUsage": "OBSERVATION_ONLY",
        "sourceMetricZh": "全體外資及陸資持股比率",
        "technicalColumnCompatibility": "ForeignHoldRatio_Pct",
        "periodCoverage": "2021Q1~2026Q1",
        "derivationBaseline": "2020Q4",
        "zh": "技術欄名維持相容；內容已改為TWSE官方外資及陸資合計持股比率",
    }
    overrides["ForeignHoldChange_Pct"] = {
        "quality": "DERIVED_FROM_OFFICIAL_TWSE_A1_L1",
        "ruleUsage": "OBSERVATION_ONLY",
        "formula": "CURRENT_OFFICIAL_RATIO_MINUS_PRIOR_OFFICIAL_RATIO",
        "unitZh": "百分點",
        "zh": "依相鄰季TWSE官方持股比率計算，僅供觀察",
    }
    overrides["ForeignHoldTrend"] = {
        "quality": "DERIVED_FROM_OFFICIAL_TWSE_A1_L1",
        "ruleUsage": "OBSERVATION_ONLY",
        "formula": "RISING_GT_0.5PP_STABLE_WITHIN_0.5PP_DECLINING_LT_NEG_0.5PP",
        "zh": "依官方季度變化重算，未接入品質分、回測或交易規則",
    }
    warnings = target.setdefault("warnings", [])
    warnings.append(
        {
            "code": "FOREIGN_HOLDING_OFFICIAL_SERIES_CORRECTION",
            "zh": "2021Q1至2026Q1外資欄位已改用TWSE官方外資及陸資合計持股序列；技術欄名暫時保留相容性",
        }
    )
    return (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def create_schema(connection: sqlite3.Connection) -> None:
    migrations = (
        dbcore.Migration(
            1, "initial_schema", BASE_MIGRATION, dbcore.sha256_file(BASE_MIGRATION)
        ),
        dbcore.Migration(
            9,
            "foreign_holding_connector_extension",
            EXTENSION,
            dbcore.sha256_file(EXTENSION),
        ),
    )
    for migration in migrations:
        dbcore.apply_one_migration(connection, migration, mode="DRY_RUN", backup_id=None)


def protected_hashes(runtime_db: Path) -> dict[str, str]:
    return {
        str(path.resolve()): dbcore.sha256_file(path)
        for path in (*FORMAL_PROTECTED, runtime_db)
    }


def save_raw(
    output_dir: Path,
    quarter: str,
    result: HttpResult,
    retrieved_at: str,
) -> dict:
    raw_dir = output_dir / "raw" / "twse_mi_qfiis"
    raw_dir.mkdir(parents=True, exist_ok=True)
    name = f"{quarter}_{urllib.parse.parse_qs(urllib.parse.urlparse(result.url).query)['date'][0]}.json"
    path = raw_dir / name
    path.write_bytes(result.body)
    metadata = {
        "url": result.url,
        "retrieved_at": retrieved_at,
        "http_status": result.status,
        "mime_type": result.mime_type,
        "headers": result.headers,
        "sha256": sha256_bytes(result.body),
        "local_path": str(path.resolve()),
        "transport": result.transport,
        "status": "RAW_ARTIFACT",
        "status_zh": "原始證據",
        "status_note_zh": "未修改的TWSE官方MI_QFIIS JSON",
        "actionable": False,
    }
    (raw_dir / f"{name}.metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return metadata


def build_release(
    output_dir: Path,
    snapshots: list[dict],
    series: list[dict],
    raw_metas: list[dict],
    master_content: bytes,
    authority_content: bytes,
    changes: list[dict],
) -> dict:
    candidate_dir = output_dir / "candidate"
    data_dir = candidate_dir / "data"
    data_dir.mkdir(parents=True)
    master_path = data_dir / "2317_master_v9.csv"
    authority_path = data_dir / "CSV_AUTHORITY_MANIFEST.json"
    daily_path = data_dir / "2317_daily_price.csv"
    macro_path = data_dir / "macro_snapshot.csv"
    master_path.write_bytes(master_content)
    authority_path.write_bytes(authority_content)
    daily_path.write_bytes(FORMAL_CSVS[1].read_bytes())
    macro_path.write_bytes(FORMAL_CSVS[2].read_bytes())
    items = [
        {
            "path": "data/2317_master_v9.csv",
            "candidate_path": "candidate/data/2317_master_v9.csv",
            "before_sha256": dbcore.sha256_file(MASTER_CSV),
            "candidate_sha256": sha256_bytes(master_content),
            "changed": True,
            "row_count": 21,
            "column_count": 54,
        },
        {
            "path": "data/2317_daily_price.csv",
            "candidate_path": "candidate/data/2317_daily_price.csv",
            "before_sha256": dbcore.sha256_file(FORMAL_CSVS[1]),
            "candidate_sha256": dbcore.sha256_file(FORMAL_CSVS[1]),
            "changed": False,
        },
        {
            "path": "data/macro_snapshot.csv",
            "candidate_path": "candidate/data/macro_snapshot.csv",
            "before_sha256": dbcore.sha256_file(FORMAL_CSVS[2]),
            "candidate_sha256": dbcore.sha256_file(FORMAL_CSVS[2]),
            "changed": False,
        },
        {
            "path": "data/CSV_AUTHORITY_MANIFEST.json",
            "candidate_path": "candidate/data/CSV_AUTHORITY_MANIFEST.json",
            "before_sha256": dbcore.sha256_file(AUTHORITY_MANIFEST),
            "candidate_sha256": sha256_bytes(authority_content),
            "changed": True,
        },
    ]
    payload = {
        "release_type": "OWNER_APPROVED_OFFICIAL_FOREIGN_HOLDING_SERIES_CORRECTION",
        "batch_id": "P2-03B-07",
        "as_of": "2026-06-22",
        "subject": "LISTING:TWSE:2317",
        "source": {
            "code": SOURCE_CODE,
            "authority": "A1",
            "evidence_level": "L1",
            "endpoint": ENDPOINT_BASE,
            "select_type": SELECT_TYPE,
            "source_metric_zh": "全體外資及陸資持股比率",
        },
        "period_coverage": {
            "derivation_baseline": "2020Q4",
            "candidate_start": "2021Q1",
            "candidate_end": "2026Q1",
            "snapshot_count": 22,
            "candidate_row_count": 21,
        },
        "raw_snapshots": [
            {
                "quarter": snapshot["quarter"],
                "requested_quarter_end": snapshot["requested_quarter_end"],
                "official_as_of_date": snapshot["official_as_of_date"],
                "date_alignment_status": snapshot["date_alignment_status"],
                "sha256": meta["sha256"],
            }
            for snapshot, meta in zip(snapshots, raw_metas)
        ],
        "items": items,
        "changes": changes,
        "formulas": {
            "ForeignHoldRatio_Pct": "TWSE_OFFICIAL_ALL_FOREIGN_MAINLAND_HOLDING_RATIO",
            "ForeignHoldChange_Pct": "CURRENT_OFFICIAL_RATIO_MINUS_PRIOR_OFFICIAL_RATIO",
            "ForeignHoldTrend": "RISING_GT_0.5PP_STABLE_WITHIN_0.5PP_DECLINING_LT_NEG_0.5PP",
        },
        "rule_usage": "OBSERVATION_ONLY",
        "excluded_changes": [
            "DataSource",
            "DataSupportLevel",
            "Runtime SQLite",
            "UI rule wiring",
            "quality score",
            "backtest",
            "T86 institutional trading",
        ],
        "validation_status": "PASS_WITH_WARNINGS",
        "actionable": False,
    }
    manifest_sha = sha256_json(payload)
    release_id = f"REL-P1008-FH-20260622-{manifest_sha[:8]}"
    manifest = {
        "release_id": release_id,
        "manifest_sha256": manifest_sha,
        "manifest_hash_scope": "CANONICAL_PAYLOAD",
        "generated_at": utc_now(),
        "owner_approval": {
            "status": "PENDING",
            "approval_item": 86,
            "approved_manifest_sha256": None,
        },
        "publication": {
            "status": "NOT_PUBLISHED",
            "publisher": None,
            "post_publish_verified": False,
        },
        "payload": payload,
    }
    (candidate_dir / "RELEASE_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    diff = {
        "release_id": release_id,
        "status": "PASS_WITH_WARNINGS",
        "status_zh": "通過但有警告",
        "status_note_zh": "21季外資三欄已依TWSE官方序列建立候選；尚未發布",
        "changed_field_count": sum(1 for change in changes if change["changed"]),
        "total_compared_field_count": len(changes),
        "changes": changes,
        "actionable": False,
    }
    (candidate_dir / "DIFF_REPORT.json").write_text(
        json.dumps(diff, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def insert_database(
    connection: sqlite3.Connection,
    snapshots: list[dict],
    raw_metas: list[dict],
    series: list[dict],
    changes: list[dict],
    manifest: dict,
    retrieved_at: str,
) -> None:
    timestamp = dt.datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    subject_uid = deterministic_ulid(
        timestamp, "LEGAL_ENTITY:HON_HAI_PRECISION_INDUSTRY"
    )
    source_uid = deterministic_ulid(timestamp, f"SOURCE:{SOURCE_CODE}")
    connection.execute(
        """
        INSERT INTO subjects(
            subject_uid, subject_type, canonical_key, name, ticker, market,
            isin, cik, currency, parent_subject_uid, status, created_at, updated_at
        ) VALUES (?, 'COMPANY', 'LEGAL_ENTITY:HON_HAI_PRECISION_INDUSTRY',
                  '鴻海精密工業股份有限公司', '2317', 'TWSE',
                  'TW0002317005', NULL, 'TWD', NULL, 'ACTIVE', ?, ?)
        """,
        (subject_uid, retrieved_at, retrieved_at),
    )
    connection.execute(
        """
        INSERT INTO sources(
            source_uid, source_code, source_name, source_type, official_url,
            quality_level, license_scope, retrieval_method, enabled,
            created_at, updated_at
        ) VALUES (?, ?, 'TWSE外資及陸資投資持股統計',
                  'OFFICIAL_MARKET_STATISTICS', ?, 'A1',
                  'OWNER_INTERNAL_CANDIDATE_REDISTRIBUTION_NOT_APPROVED',
                  'HTTPS_GET_QUARTER_END_SERIES', 1, ?, ?)
        """,
        (source_uid, SOURCE_CODE, PAGE_URL, retrieved_at, retrieved_at),
    )
    connection.execute(
        """
        INSERT INTO connector_contracts(
            connector_id, source_code, source_authority, evidence_level,
            endpoint_url, select_type, expected_fields_json, parser_version,
            fallback_policy, owner_approval, actionable
        ) VALUES (?, ?, 'A1', 'L1', ?, 'ALLBUT0999', ?, ?,
                  'NO_SOURCE_FALLBACK', 'OWNER_ITEM_85_REVISED', 0)
        """,
        (
            CONNECTOR_ID,
            SOURCE_CODE,
            ENDPOINT_BASE,
            canonical_json(EXPECTED_FIELDS),
            PARSER_VERSION,
        ),
    )
    snapshot_uids = {}
    for snapshot, meta in zip(snapshots, raw_metas):
        artifact_uid = deterministic_ulid(timestamp, f"ARTIFACT:{meta['sha256']}")
        snapshot_uid = deterministic_ulid(
            timestamp, f"SNAPSHOT:{snapshot['quarter']}:{meta['sha256']}"
        )
        snapshot_uids[snapshot["quarter"]] = snapshot_uid
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
                retrieved_at,
            ),
        )
        row = snapshot["row"]
        connection.execute(
            """
            INSERT INTO foreign_holding_snapshots(
                snapshot_uid, artifact_uid, subject_uid, requested_quarter,
                requested_quarter_end, official_as_of_date, date_alignment_status,
                company_code, isin, issued_shares, available_investment_shares,
                foreign_mainland_holding_shares, available_investment_ratio_pct,
                foreign_mainland_holding_ratio_pct, recomputed_ratio_pct,
                recompute_difference_pct, common_legal_limit_pct,
                mainland_legal_limit_pct, change_reason_raw,
                latest_company_report_date_raw, notes_text, source_row_sha256,
                validation_status, message_zh, created_at, actionable
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '2317', 'TW0002317005',
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      'PASS_WITH_WARNINGS',
                      'TWSE官方季末外資及陸資持股快照已驗證；候選尚未發布',
                      ?, 0)
            """,
            (
                snapshot_uid,
                artifact_uid,
                subject_uid,
                snapshot["quarter"],
                snapshot["requested_quarter_end"],
                snapshot["official_as_of_date"],
                snapshot["date_alignment_status"],
                snapshot["issued_shares"],
                snapshot["available_investment_shares"],
                snapshot["holding_shares"],
                snapshot["available_ratio_pct"],
                snapshot["holding_ratio_pct"],
                snapshot["recomputed_ratio_pct"],
                snapshot["recompute_difference_pct"],
                snapshot["common_legal_limit_pct"],
                snapshot["mainland_legal_limit_pct"],
                str(row["與前日異動原因(註)"]),
                str(row["最近一次上市公司申報外資及陸資持股異動日期"]),
                snapshot["notes"],
                sha256_json(row),
                retrieved_at,
            ),
        )
    for item in series:
        connection.execute(
            """
            INSERT INTO foreign_holding_series(
                series_uid, snapshot_uid, quarter, ratio_pct, prior_ratio_pct,
                change_pct_point, trend, is_candidate_row, promotion_status,
                message_zh, created_at, actionable
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'CANDIDATE_PENDING_OWNER',
                      '依TWSE官方季末序列重算；等待Owner核准Manifest', ?, 0)
            """,
            (
                deterministic_ulid(timestamp, f"SERIES:{item['quarter']}"),
                snapshot_uids[item["quarter"]],
                item["quarter"],
                item["ratio_pct"],
                item["prior_ratio_pct"],
                item["change_pct_point"],
                item["trend"],
                retrieved_at,
            ),
        )
    for change in changes:
        connection.execute(
            """
            INSERT INTO candidate_changes(
                change_uid, quarter, field_name, before_value, after_value,
                changed, source_authority, evidence_level, status_zh,
                message_zh, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'A1', 'L1', '候選待核准',
                      'TWSE官方序列修正候選；未核准Manifest前不得發布', ?)
            """,
            (
                deterministic_ulid(
                    timestamp, f"CHANGE:{change['quarter']}:{change['field']}"
                ),
                change["quarter"],
                change["field"],
                change["before"],
                change["after"],
                int(change["changed"]),
                retrieved_at,
            ),
        )
    connection.execute(
        """
        INSERT INTO candidate_releases(
            release_uid, release_id, manifest_sha256, candidate_master_sha256,
            candidate_authority_manifest_sha256, status, status_zh,
            status_note_zh, created_at, actionable
        ) VALUES (?, ?, ?, ?, ?, 'READY_FOR_OWNER_REVIEW', '等待Owner檢視',
                  '候選已綁定Manifest SHA-256，尚未發布', ?, 0)
        """,
        (
            deterministic_ulid(timestamp, f"RELEASE:{manifest['release_id']}"),
            manifest["release_id"],
            manifest["manifest_sha256"],
            next(
                item["candidate_sha256"]
                for item in manifest["payload"]["items"]
                if item["path"] == "data/2317_master_v9.csv"
            ),
            next(
                item["candidate_sha256"]
                for item in manifest["payload"]["items"]
                if item["path"] == "data/CSV_AUTHORITY_MANIFEST.json"
            ),
            retrieved_at,
        ),
    )
    connection.execute(
        """
        INSERT INTO connector_executions(
            execution_uid, connector_id, started_at, finished_at,
            requested_quarter_count, successful_snapshot_count,
            candidate_row_count, status_code, status_zh, status_note_zh,
            fallback_used, actionable
        ) VALUES (?, ?, ?, ?, 22, 22, 21, 'PASS_WITH_WARNINGS',
                  '通過但有警告',
                  'TWSE官方22期快照已重建21季候選；等待Owner核准Manifest',
                  0, 0)
        """,
        (
            deterministic_ulid(timestamp, f"EXECUTION:{manifest['release_id']}"),
            CONNECTOR_ID,
            retrieved_at,
            retrieved_at,
        ),
    )


def run_connector(
    output_dir: Path,
    runtime_db: Path,
    fetcher: Callable[[str, int], HttpResult] = fetch_url,
    *,
    sleep_seconds: float = 0.1,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    started_at = utc_now()
    protected_before = protected_hashes(runtime_db)
    snapshots = []
    raw_metas = []
    attempt_log = []
    for item in required_quarters():
        snapshot, result, attempts = collect_snapshot(
            item, fetcher, max_lookback_days=10, sleep_seconds=sleep_seconds
        )
        meta = save_raw(output_dir, item["quarter"], result, started_at)
        snapshots.append(snapshot)
        raw_metas.append(meta)
        attempt_log.append({"quarter": item["quarter"], "attempts": attempts})
        if sleep_seconds:
            time.sleep(sleep_seconds)
    series = build_series(snapshots)
    master_content, changes, candidate_rows = build_master_candidate(series)
    authority_content = build_authority_candidate(master_content)
    manifest = build_release(
        output_dir,
        snapshots,
        series,
        raw_metas,
        master_content,
        authority_content,
        changes,
    )
    staging_db = output_dir / "twse_2317_foreign_holding_candidate.sqlite3"
    connection = dbcore.connect_database(staging_db)
    try:
        create_schema(connection)
        insert_database(
            connection,
            snapshots,
            raw_metas,
            series,
            changes,
            manifest,
            started_at,
        )
        checks = dbcore.verify_connection(connection)
    finally:
        connection.close()
    protected_after = protected_hashes(runtime_db)
    if protected_before != protected_after:
        raise ConnectorError("Runtime SQLite或正式資料在Connector期間發生變更")
    summary = {
        "batch_id": "P2-03B-07",
        "generated_at": utc_now(),
        "status": "PASS_WITH_WARNINGS",
        "status_zh": "通過但有警告",
        "status_note_zh": "TWSE官方季末序列與CSV修正候選已建立；等待Owner核准Manifest，尚未發布",
        "actionable": False,
        "owner_acceptance": "PENDING_MANIFEST_APPROVAL",
        "connector": {
            "connector_id": CONNECTOR_ID,
            "source_code": SOURCE_CODE,
            "source_authority": "A1",
            "evidence_level": "L1",
            "endpoint": ENDPOINT_BASE,
            "select_type": SELECT_TYPE,
            "snapshot_count": 22,
            "candidate_row_count": 21,
            "network_requests": sum(len(item["attempts"]) for item in attempt_log),
            "fallback_policy": "NO_SOURCE_FALLBACK",
            "t86_used": False,
            "scheduled": False,
        },
        "release": {
            "release_id": manifest["release_id"],
            "manifest_sha256": manifest["manifest_sha256"],
            "status": "READY_FOR_OWNER_REVIEW",
            "status_zh": "等待Owner檢視",
            "candidate_dir": str((output_dir / "candidate").resolve()),
            "published": False,
        },
        "series": [
            {
                "quarter": item["quarter"],
                "official_as_of_date": item["snapshot"]["official_as_of_date"],
                "date_alignment_status": item["snapshot"]["date_alignment_status"],
                "ratio_pct": item["ratio_pct"],
                "change_pct_point": item["change_pct_point"],
                "trend": item["trend"],
            }
            for item in series
        ],
        "changes": {
            "compared": len(changes),
            "changed": sum(1 for item in changes if item["changed"]),
            "unchanged": sum(1 for item in changes if not item["changed"]),
        },
        "candidate_2026Q1": next(
            row for row in candidate_rows if row["Quarter"] == "2026Q1"
        ),
        "attempt_log": attempt_log,
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
    (output_dir / "OFFICIAL_SERIES.json").write_text(
        json.dumps(summary["series"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="P1008 TWSE 2317外資及陸資持股官方季末序列候選"
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--runtime-db", type=Path, default=DEFAULT_RUNTIME_DB)
    parser.add_argument("--sleep-seconds", type=float, default=0.1)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    now = dt.datetime.now(dt.timezone.utc)
    output_dir = args.output_dir or (
        PROJECT_ROOT
        / "staging"
        / "p2-03b-07"
        / now.strftime("%Y-%m-%d")
        / f"run_{now.strftime('%Y%m%dT%H%M%SZ')}"
    )
    try:
        result = run_connector(
            output_dir,
            args.runtime_db,
            sleep_seconds=args.sleep_seconds,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
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
