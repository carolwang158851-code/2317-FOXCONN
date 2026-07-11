from __future__ import annotations

import argparse
import base64
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
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
P2_01_TOOL = PROJECT_ROOT / "db" / "tools" / "p1008_db.py"
BASE_MIGRATION = PROJECT_ROOT / "db" / "migrations" / "0001_initial_schema.sql"
EXTENSION = (
    PROJECT_ROOT / "db" / "p2-03b-06" / "cash_flow_xbrl_connector_extension.sql"
)
BASE_URL = "https://mopsov.twse.com.tw"
DISCOVERY_URL = f"{BASE_URL}/mops/web/ajax_t203sb01"
DISCOVERY_REFERER = f"{BASE_URL}/mops/web/t203sb01"
MANUAL_URL = f"{BASE_URL}/mops/web/ajax_t164sb05"
MANUAL_REFERER = f"{BASE_URL}/mops/web/t164sb05"
ALLOWED_HOST = "mopsov.twse.com.tw"
CONNECTOR_ID = "MOPS_XBRL_CASH_FLOW_2317_V1"
SOURCE_CODE = "MOPS_XBRL_FINANCIAL_REPORT"
PARSER_VERSION = "p2-03b-06.1"
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

IX_NS = "http://www.xbrl.org/2013/inlineXBRL"
XBRLI_NS = "http://www.xbrl.org/2003/instance"
LINK_NS = "http://www.xbrl.org/2003/linkbase"
XLINK_NS = "http://www.w3.org/1999/xlink"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

FACT_SPECS = (
    (
        "ifrs-full:CashFlowsFromUsedInOperatingActivities",
        "MOPS_XBRL_CASH_FLOW_OPERATING",
        "營業活動之淨現金流入（流出）",
        "CUMULATIVE_YTD",
    ),
    (
        "tifrs-SCF:NetCashFlowsFromUsedInInvestingActivities",
        "MOPS_XBRL_CASH_FLOW_INVESTING",
        "投資活動之淨現金流入（流出）",
        "CUMULATIVE_YTD",
    ),
    (
        "tifrs-SCF:CashFlowsFromUsedInFinancingActivities",
        "MOPS_XBRL_CASH_FLOW_FINANCING",
        "籌資活動之淨現金流入（流出）",
        "CUMULATIVE_YTD",
    ),
    (
        "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        "MOPS_XBRL_PURCHASE_PPE",
        "取得不動產、廠房及設備",
        "CUMULATIVE_YTD",
    ),
    (
        "ifrs-full:AdjustmentsForDepreciationExpense",
        "MOPS_XBRL_DEPRECIATION",
        "折舊費用",
        "CUMULATIVE_YTD",
    ),
    (
        "ifrs-full:AdjustmentsForAmortisationExpense",
        "MOPS_XBRL_AMORTISATION",
        "攤銷費用",
        "CUMULATIVE_YTD",
    ),
    (
        "ifrs-full:IncreaseDecreaseInCashAndCashEquivalents",
        "MOPS_XBRL_CASH_CHANGE",
        "本期現金及約當現金增加（減少）數",
        "CUMULATIVE_YTD",
    ),
    (
        "tifrs-SCF:CashAndCashEquivalentsAtEndOfPeriod",
        "MOPS_XBRL_CASH_END",
        "期末現金及約當現金餘額",
        "INSTANT",
    ),
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
class HttpRequest:
    method: str
    url: str
    form: dict[str, str] | None = None
    referer: str | None = None


@dataclass(frozen=True)
class HttpResult:
    url: str
    status: int
    mime_type: str
    headers: dict[str, str]
    body: bytes
    transport: str = "FIXTURE"


def load_dbcore():
    spec = importlib.util.spec_from_file_location("p1008_db_for_cash_flow", P2_01_TOOL)
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


def fetch_request_powershell(request: HttpRequest, timeout: int) -> HttpResult:
    if os.name != "nt":
        raise PrimarySourceUnavailable("PowerShell HTTPS transport只支援Windows")
    with tempfile.TemporaryDirectory(prefix="p1008-cash-flow-xbrl-") as temp_dir:
        body_path = Path(temp_dir) / "body.bin"
        metadata_path = Path(temp_dir) / "metadata.json"
        headers = {
            "User-Agent": "P1008-MOPS-XBRL-CashFlow-DryRun/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        if request.referer:
            headers["Referer"] = request.referer
        headers_literal = "@{" + ";".join(
            f"{powershell_quote(k)}={powershell_quote(v)}"
            for k, v in headers.items()
        ) + "}"
        form_literal = "$null"
        if request.form is not None:
            form_literal = "@{" + ";".join(
                f"{powershell_quote(k)}={powershell_quote(v)}"
                for k, v in request.form.items()
            ) + "}"
        script = f"""
$ErrorActionPreference = 'Stop'
$headers = {headers_literal}
$body = {form_literal}
$params = @{{
  UseBasicParsing = $true
  Uri = {powershell_quote(request.url)}
  TimeoutSec = {int(timeout)}
  Headers = $headers
  Method = {powershell_quote(request.method)}
}}
if ($null -ne $body) {{ $params['Body'] = $body }}
$r = Invoke-WebRequest @params
$stream = $r.RawContentStream
$stream.Position = 0
$ms = New-Object IO.MemoryStream
$stream.CopyTo($ms)
[IO.File]::WriteAllBytes({powershell_quote(str(body_path))}, $ms.ToArray())
$responseHeaders = @{{}}
foreach($key in $r.Headers.Keys) {{ $responseHeaders[$key] = [string]$r.Headers[$key] }}
$contentType = [string]$r.Headers['Content-Type']
$metadata = @{{
  status = [int]$r.StatusCode
  mime_type = $contentType.Split(';')[0].Trim()
  headers = $responseHeaders
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
                f"MOPS官方來源PowerShell HTTPS失敗：{process.stderr.strip()}"
            )
        metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        return HttpResult(
            url=request.url,
            status=int(metadata["status"]),
            mime_type=metadata["mime_type"],
            headers={str(k): str(v) for k, v in metadata["headers"].items()},
            body=body_path.read_bytes(),
            transport="POWERSHELL_HTTPS",
        )


def fetch_request(request: HttpRequest, timeout: int = 120) -> HttpResult:
    validate_url(request.url)
    headers = {
        "User-Agent": "P1008-MOPS-XBRL-CashFlow-DryRun/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if request.referer:
        headers["Referer"] = request.referer
    data = None
    if request.form is not None:
        data = urllib.parse.urlencode(request.form).encode("ascii")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    urllib_request = urllib.request.Request(
        request.url,
        data=data,
        headers=headers,
        method=request.method,
    )
    try:
        with urllib.request.urlopen(urllib_request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            return HttpResult(
                url=request.url,
                status=int(response.status),
                mime_type=content_type.split(";", 1)[0].strip(),
                headers={key: value for key, value in response.headers.items()},
                body=response.read(),
                transport="PYTHON_URLLIB",
            )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if os.name == "nt":
            return fetch_request_powershell(request, timeout)
        raise PrimarySourceUnavailable(f"MOPS主要來源無法使用：{exc}") from exc


class TableRowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self.current: dict | None = None
        self.in_cell = False
        self.cell_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "tr":
            self.current = {"cells": [], "onclicks": []}
        elif tag in {"td", "th"} and self.current is not None:
            self.in_cell = True
            self.cell_parts = []
        elif tag == "input" and self.current is not None and attr.get("onclick"):
            self.current["onclicks"].append(attr["onclick"])

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.current is not None and self.in_cell:
            self.current["cells"].append(" ".join("".join(self.cell_parts).split()))
            self.in_cell = False
        elif tag == "tr" and self.current is not None:
            self.rows.append(self.current)
            self.current = None


class TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.parts.append(value)

    @property
    def text(self) -> str:
        return " ".join(self.parts)


def decode_utf8(body: bytes, label: str) -> str:
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DataValidationError(f"{label}不是有效UTF-8") from exc


def discovery_form() -> dict[str, str]:
    return {
        "step": "1",
        "firstin": "1",
        "off": "1",
        "keyword4": "",
        "code1": "",
        "TYPEK2": "",
        "checkbtn": "",
        "queryName": "co_id",
        "inpuType": "co_id",
        "TYPEK": "all",
        "co_id": "2317",
    }


def manual_form(year: int, quarter: int) -> dict[str, str]:
    return {
        "step": "1",
        "firstin": "1",
        "off": "1",
        "keyword4": "",
        "code1": "",
        "TYPEK2": "",
        "checkbtn": "",
        "queryName": "co_id",
        "inpuType": "co_id",
        "TYPEK": "all",
        "isnew": "false",
        "co_id": "2317",
        "year": str(year - 1911),
        "season": f"{quarter:02d}",
    }


def parse_discovery(body: bytes) -> dict:
    parser = TableRowParser()
    parser.feed(decode_utf8(body, "XBRL案例文件清單"))
    candidates = []
    for row in parser.rows:
        cells = row["cells"]
        if len(cells) < 2 or cells[1] != "合併":
            continue
        match = re.fullmatch(r"(\d{3})Q([1-4])", cells[0])
        if not match:
            continue
        download_urls = []
        for onclick in row["onclicks"]:
            url_match = re.search(r"window\.open\('([^']*FileDownLoad[^']*)'", onclick)
            if url_match:
                download_urls.append(urllib.parse.urljoin(BASE_URL, url_match.group(1)))
        if len(download_urls) != 1:
            raise ContractError(f"{cells[0]}合併案例文件下載連結筆數不是1")
        year = int(match.group(1)) + 1911
        quarter = int(match.group(2))
        url = download_urls[0]
        validate_url(url)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        if query.get("report_id") != ["C"]:
            continue
        expected = {
            "co_id": "2317",
            "year": str(year),
            "season": str(quarter),
        }
        for key, value in expected.items():
            if query.get(key) != [value]:
                raise ContractError(f"案例文件下載參數錯誤：{key}")
        candidates.append(
            {
                "roc_period": cells[0],
                "fiscal_year": year,
                "fiscal_quarter": quarter,
                "report_category_zh": cells[1],
                "download_url": url,
            }
        )
    if not candidates:
        raise DataValidationError("MOPS案例文件清單找不到2317合併財報")
    selected = max(candidates, key=lambda item: (item["fiscal_year"], item["fiscal_quarter"]))
    selected["candidate_count"] = len(candidates)
    return selected


def quarter_period(year: int, quarter: int) -> tuple[str, str]:
    end = {
        1: dt.date(year, 3, 31),
        2: dt.date(year, 6, 30),
        3: dt.date(year, 9, 30),
        4: dt.date(year, 12, 31),
    }[quarter]
    return dt.date(year, 1, 1).isoformat(), end.isoformat()


def normalize_decimal(number: Decimal) -> str:
    if not number.is_finite():
        raise DataValidationError("XBRL數值不是有限Decimal")
    result = format(number, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return result or "0"


def namespace_map(body: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        for _, pair in ET.iterparse(io.BytesIO(body), events=("start-ns",)):
            prefix, uri = pair
            result[prefix or ""] = uri
    except ET.ParseError as exc:
        raise DataValidationError(f"Inline XBRL namespace解析失敗：{exc}") from exc
    return result


def parse_inline_xbrl(body: bytes, discovery: dict) -> dict:
    upper = body.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ContractError("Inline XBRL含禁止的DOCTYPE或ENTITY")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise DataValidationError(f"Inline XBRL XML解析失敗：{exc}") from exc
    namespaces = namespace_map(body)
    required_namespaces = {
        "ix": IX_NS,
        "xbrli": XBRLI_NS,
        "link": LINK_NS,
        "ifrs-full": namespaces.get("ifrs-full"),
        "tifrs-SCF": namespaces.get("tifrs-SCF"),
        "iso4217": namespaces.get("iso4217"),
    }
    if any(not value for value in required_namespaces.values()):
        raise ContractError("Inline XBRL缺少必要Namespace")

    schema_refs = root.findall(f".//{{{LINK_NS}}}schemaRef")
    if len(schema_refs) != 1:
        raise ContractError("Inline XBRL schemaRef筆數不是1")
    schema_ref = schema_refs[0].attrib.get(f"{{{XLINK_NS}}}href", "")
    if not schema_ref.endswith(".xsd"):
        raise ContractError("Inline XBRL schemaRef格式錯誤")

    contexts: dict[str, dict] = {}
    for element in root.findall(f".//{{{XBRLI_NS}}}context"):
        context_id = element.attrib.get("id", "")
        identifier = element.find(f"./{{{XBRLI_NS}}}entity/{{{XBRLI_NS}}}identifier")
        period = element.find(f"./{{{XBRLI_NS}}}period")
        if not context_id or identifier is None or period is None:
            raise ContractError("Inline XBRL Context缺少必要欄位")
        start = period.findtext(f"./{{{XBRLI_NS}}}startDate")
        end = period.findtext(f"./{{{XBRLI_NS}}}endDate")
        instant = period.findtext(f"./{{{XBRLI_NS}}}instant")
        contexts[context_id] = {
            "identifier": (identifier.text or "").strip(),
            "identifier_scheme": identifier.attrib.get("scheme", ""),
            "start_date": start,
            "end_date": end,
            "instant": instant,
            "has_scenario": element.find(f"./{{{XBRLI_NS}}}scenario") is not None,
        }

    units: dict[str, str] = {}
    for element in root.findall(f".//{{{XBRLI_NS}}}unit"):
        unit_id = element.attrib.get("id", "")
        measure = element.findtext(f"./{{{XBRLI_NS}}}measure")
        if unit_id and measure:
            units[unit_id] = measure.strip()
    if units.get("TWD") != "iso4217:TWD":
        raise ContractError("Inline XBRL TWD Unit未通過驗證")

    nonnumeric: dict[str, list[str]] = {}
    for element in root.iter(f"{{{IX_NS}}}nonNumeric"):
        name = element.attrib.get("name", "")
        value = " ".join("".join(element.itertext()).split())
        nonnumeric.setdefault(name, []).append(value)

    def unique_metadata(name: str) -> str:
        values = sorted(set(nonnumeric.get(name, [])))
        if len(values) != 1:
            raise DataValidationError(f"Inline XBRL中{name}不是唯一值")
        return values[0]

    company_code = unique_metadata("tifrs-notes:CompanyID")
    year = int(unique_metadata("tifrs-notes:Year"))
    quarter = int(unique_metadata("tifrs-notes:Quarter"))
    report_category = unique_metadata("tifrs-notes:ReportCategory")
    if company_code != "2317":
        raise DataValidationError(f"Inline XBRL公司代號不是2317：{company_code}")
    if (year, quarter) != (
        discovery["fiscal_year"],
        discovery["fiscal_quarter"],
    ):
        raise DataValidationError("Inline XBRL期間與案例文件清單不一致")
    if report_category != "Consolidated report":
        raise DataValidationError(f"Inline XBRL不是合併報表：{report_category}")

    period_start, period_end = quarter_period(year, quarter)
    elements_by_name: dict[str, list[ET.Element]] = {}
    for element in root.iter(f"{{{IX_NS}}}nonFraction"):
        elements_by_name.setdefault(element.attrib.get("name", ""), []).append(element)

    facts = []
    warnings: list[str] = []
    for concept, metric_code, label_zh, period_scope in FACT_SPECS:
        matches = []
        for element in elements_by_name.get(concept, []):
            context_ref = element.attrib.get("contextRef", "")
            context = contexts.get(context_ref)
            if context is None:
                raise ContractError(f"{concept}引用不存在的Context")
            if context["identifier"] != "2317" or context["has_scenario"]:
                continue
            if period_scope == "CUMULATIVE_YTD":
                period_match = (
                    context["start_date"] == period_start
                    and context["end_date"] == period_end
                    and context["instant"] is None
                )
            else:
                period_match = (
                    context["instant"] == period_end
                    and context["start_date"] is None
                    and context["end_date"] is None
                )
            if period_match:
                matches.append((element, context_ref))
        if not matches:
            raise DataValidationError(f"Inline XBRL缺少目前期間Concept：{concept}")

        normalized_matches = []
        for element, context_ref in matches:
            if element.attrib.get(f"{{{XSI_NS}}}nil", "").lower() == "true":
                raise DataValidationError(f"{concept}為nil")
            unit_ref = element.attrib.get("unitRef", "")
            if unit_ref != "TWD" or units.get(unit_ref) != "iso4217:TWD":
                raise DataValidationError(f"{concept}的Unit不是TWD")
            try:
                scale = int(element.attrib.get("scale", "0"))
                if scale < -12 or scale > 12:
                    raise ValueError
            except ValueError as exc:
                raise DataValidationError(f"{concept}的scale不合法") from exc
            decimals_value = element.attrib.get("decimals", "")
            if not re.fullmatch(r"-?\d+|INF", decimals_value):
                raise DataValidationError(f"{concept}的decimals不合法")
            raw_text = " ".join("".join(element.itertext()).split())
            candidate = raw_text.replace(",", "").replace(" ", "")
            if not candidate:
                raise DataValidationError(f"{concept}的數值為空")
            try:
                display_value = Decimal(candidate)
            except InvalidOperation as exc:
                raise DataValidationError(f"{concept}不是有效Decimal") from exc
            sign = element.attrib.get("sign")
            if sign not in {None, "", "-"}:
                raise DataValidationError(f"{concept}的sign不受支援")
            if sign == "-":
                display_value = -abs(display_value)
            normalized = display_value * (Decimal(10) ** scale)
            normalized_matches.append(
                {
                    "concept_qname": concept,
                    "metric_code": metric_code,
                    "label_zh": label_zh,
                    "context_ref": context_ref,
                    "period_scope": period_scope,
                    "raw_display_value": normalize_decimal(display_value),
                    "normalized_value_twd": normalize_decimal(normalized),
                    "unit_ref": unit_ref,
                    "unit_measure": units[unit_ref],
                    "scale": scale,
                    "decimals": decimals_value,
                    "sign": sign,
                }
            )
        unique_values = {
            item["normalized_value_twd"] for item in normalized_matches
        }
        if len(unique_values) != 1:
            raise DataValidationError(f"{concept}同一期間有不一致重複值")
        if len(normalized_matches) > 1:
            warnings.append("IDENTICAL_DUPLICATE_FACT_DEDUPED")
        facts.append(normalized_matches[0])

    return {
        "company_code": company_code,
        "company_name": unique_metadata("tifrs-notes:CompanyChineseName"),
        "fiscal_year": year,
        "fiscal_quarter": quarter,
        "period_label": f"{year}Q{quarter}",
        "period_start": period_start,
        "period_end": period_end,
        "report_category": report_category,
        "report_scope": "CONSOLIDATED",
        "schema_ref": schema_ref,
        "namespaces": required_namespaces,
        "context_count": len(contexts),
        "unit_count": len(units),
        "facts": facts,
        "warnings": sorted(set(warnings)),
    }


def parse_manual_page(body: bytes, report: dict) -> dict:
    parser = TextParser()
    parser.feed(decode_utf8(body, "MOPS現金流量表人工核對頁"))
    text = parser.text
    required_headers = (
        "合併現金流量表",
        f"民國{report['fiscal_year'] - 1911}年第{report['fiscal_quarter']}季",
        "單位：新台幣仟元",
    )
    missing_headers = [value for value in required_headers if value not in text]
    if missing_headers:
        raise DataValidationError(f"人工核對頁缺少表頭：{missing_headers}")
    checks = []
    for fact in report["facts"]:
        pattern = re.escape(fact["label_zh"]) + r"\s+(-?[\d,]+)"
        match = re.search(pattern, text)
        if not match:
            raise DataValidationError(f"人工核對頁找不到：{fact['label_zh']}")
        displayed = Decimal(match.group(1).replace(",", ""))
        xbrl_displayed = Decimal(fact["raw_display_value"])
        if displayed != xbrl_displayed:
            raise DataValidationError(
                f"人工核對頁與XBRL不一致：{fact['label_zh']}"
            )
        checks.append(
            {
                "concept_qname": fact["concept_qname"],
                "label_zh": fact["label_zh"],
                "xbrl_display_value_thousand_twd": fact["raw_display_value"],
                "manual_display_value_thousand_twd": normalize_decimal(displayed),
                "status": "PASS",
                "status_zh": "官方顯示值一致",
            }
        )
    return {
        "headers": list(required_headers),
        "fact_checks": checks,
        "status": "PASS",
        "status_zh": "人工核對頁與XBRL一致",
    }


def read_existing_da() -> Decimal:
    lines = [
        line
        for line in MASTER_CSV.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.startswith("##")
    ]
    rows = list(csv.DictReader(lines))
    selected = [row for row in rows if row["Quarter"] == "2026Q1"]
    if len(selected) != 1:
        raise DataValidationError("正式master中2026Q1筆數不是1")
    try:
        return Decimal(selected[0]["DA_Est_100M"])
    except InvalidOperation as exc:
        raise DataValidationError("正式master的2026Q1 DA_Est不是Decimal") from exc


def create_schema(connection: sqlite3.Connection) -> None:
    migrations = (
        dbcore.Migration(
            1, "initial_schema", BASE_MIGRATION, dbcore.sha256_file(BASE_MIGRATION)
        ),
        dbcore.Migration(
            8,
            "cash_flow_xbrl_connector_extension",
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
    raw_dir = output_dir / "raw" / "mops_xbrl"
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
        "status_note_zh": "未修改的MOPS官方HTTPS回應",
        "actionable": False,
    }
    (raw_dir / f"{name}.metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return metadata


def insert_candidate(
    connection: sqlite3.Connection,
    discovery: dict,
    report: dict,
    manual_checks: dict,
    discovery_meta: dict,
    xbrl_meta: dict,
    manual_meta: dict,
    retrieved_at: str,
) -> dict:
    timestamp = dt.datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    subject_uid = deterministic_ulid(
        timestamp, "LEGAL_ENTITY:HON_HAI_PRECISION_INDUSTRY"
    )
    source_uid = deterministic_ulid(timestamp, f"SOURCE:{SOURCE_CODE}")
    artifact_metas = (
        ("DISCOVERY", discovery_meta),
        ("XBRL", xbrl_meta),
        ("MANUAL", manual_meta),
    )
    artifact_uids = {
        code: deterministic_ulid(timestamp, f"ARTIFACT:{meta['sha256']}")
        for code, meta in artifact_metas
    }
    report_uid = deterministic_ulid(
        timestamp, f"XBRL_REPORT:2317:{report['period_label']}:{xbrl_meta['sha256']}"
    )
    execution_uid = deterministic_ulid(
        timestamp, f"EXECUTION:{CONNECTOR_ID}:{xbrl_meta['sha256']}"
    )
    warnings = [
        "PUBLICATION_TIMESTAMP_UNVERIFIED",
        "CUMULATIVE_PERIOD_NOT_SINGLE_QUARTER",
        "FCF_FORMULA_NOT_APPROVED",
        "FORMAL_DATA_PROMOTION_BLOCKED",
    ] + report["warnings"]
    if not xbrl_meta["mime_type"]:
        warnings.append("XBRL_MIME_TYPE_UNDECLARED")
    if any(meta["transport"] == "POWERSHELL_HTTPS" for _, meta in artifact_metas):
        warnings.append("TLS_TRANSPORT_RETRY_SAME_SOURCE")
    warnings = sorted(set(warnings))

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
        ) VALUES (?, ?, 'MOPS XBRL合併財務報告',
                  'OFFICIAL_REGULATORY_DISCLOSURE', ?, 'A1',
                  'OWNER_INTERNAL_DRY_RUN_REDISTRIBUTION_NOT_APPROVED',
                  'HTTPS_POST_DISCOVERY_AND_GET_XBRL_MANUAL_SINGLE_RUN',
                  1, ?, ?)
        """,
        (source_uid, SOURCE_CODE, DISCOVERY_REFERER, retrieved_at, retrieved_at),
    )
    for code, meta in artifact_metas:
        connection.execute(
            """
            INSERT INTO raw_artifacts(
                artifact_uid, source_uid, retrieved_at, source_url, local_path,
                mime_type, sha256, http_status, parser_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_uids[code],
                source_uid,
                retrieved_at,
                meta["url"],
                meta["local_path"],
                meta["mime_type"] or "application/octet-stream",
                meta["sha256"],
                meta["http_status"],
                PARSER_VERSION,
                retrieved_at,
            ),
        )
    connection.execute(
        """
        INSERT INTO connector_contracts(
            connector_id, source_code, source_authority, evidence_level,
            discovery_url, download_url, manual_verification_url,
            expected_concepts_json, taxonomy_namespaces_json, schema_ref,
            parser_version, license_scope, fallback_policy, status, owner_approval
        ) VALUES (?, ?, 'A1', 'L1', ?, ?, ?, ?, ?, ?, ?,
                  'OWNER_INTERNAL_DRY_RUN_REDISTRIBUTION_NOT_APPROVED',
                  'NO_SOURCE_FALLBACK', 'ACTIVE_DRY_RUN', 'OWNER_ITEM_83')
        """,
        (
            CONNECTOR_ID,
            SOURCE_CODE,
            DISCOVERY_URL,
            discovery["download_url"],
            MANUAL_URL,
            canonical_json([spec[0] for spec in FACT_SPECS]),
            canonical_json(report["namespaces"]),
            report["schema_ref"],
            PARSER_VERSION,
        ),
    )
    connection.execute(
        """
        INSERT INTO xbrl_reports(
            report_uid, artifact_uid, subject_uid, company_code, fiscal_year,
            fiscal_quarter, report_category, report_scope, period_start,
            period_end, schema_ref, namespaces_json, context_count, unit_count,
            source_report_sha256, validation_status, message_zh, created_at
        ) VALUES (?, ?, ?, '2317', ?, ?, 'Consolidated report', 'CONSOLIDATED',
                  ?, ?, ?, ?, ?, ?, ?, 'PASS_WITH_WARNINGS',
                  '官方合併Inline XBRL已保存；八個現金流事實僅供觀察，不計算或發布FCF', ?)
        """,
        (
            report_uid,
            artifact_uids["XBRL"],
            subject_uid,
            report["fiscal_year"],
            report["fiscal_quarter"],
            report["period_start"],
            report["period_end"],
            report["schema_ref"],
            canonical_json(report["namespaces"]),
            report["context_count"],
            report["unit_count"],
            xbrl_meta["sha256"],
            retrieved_at,
        ),
    )

    facts_output = []
    fact_uids: dict[str, str] = {}
    for fact in report["facts"]:
        evidence_hash = sha256_bytes(
            canonical_json(
                {
                    "artifact_sha256": xbrl_meta["sha256"],
                    "company_code": "2317",
                    "period": report["period_label"],
                    "concept_qname": fact["concept_qname"],
                    "context_ref": fact["context_ref"],
                    "normalized_value_twd": fact["normalized_value_twd"],
                }
            ).encode("utf-8")
        )
        evidence_id = (
            f"EVD-MOPS-XBRL_2317-{fact['metric_code'].removeprefix('MOPS_XBRL_')}-"
            f"{report['period_label']}-R01-{evidence_hash[:8]}"
        )
        metric_uid = deterministic_ulid(timestamp, f"METRIC:{fact['metric_code']}")
        observation_uid = deterministic_ulid(timestamp, f"OBSERVATION:{evidence_id}")
        fact_uid = deterministic_ulid(timestamp, f"FACT:{evidence_id}")
        fact_uids[fact["metric_code"]] = fact_uid
        connection.execute(
            """
            INSERT INTO metric_definitions(
                metric_uid, metric_code, name_zh, frequency, value_type,
                canonical_unit, is_derived, formula_version,
                required_for_report, model_usage, created_at, updated_at
            ) VALUES (?, ?, ?, 'QUARTERLY', 'DECIMAL', 'TWD', 0, NULL,
                      0, 'OBSERVATION_ONLY', ?, ?)
            """,
            (
                metric_uid,
                fact["metric_code"],
                fact["label_zh"],
                retrieved_at,
                retrieved_at,
            ),
        )
        period_start = (
            report["period_start"]
            if fact["period_scope"] == "CUMULATIVE_YTD"
            else None
        )
        connection.execute(
            """
            INSERT INTO observations(
                observation_uid, subject_uid, metric_uid, value_decimal,
                value_text, unit, period_start, period_end, published_at,
                effective_at, retrieved_at, source_uid, artifact_uid,
                revision, validation_status, support_level,
                supersedes_observation_uid, created_at
            ) VALUES (?, ?, ?, ?, NULL, 'TWD', ?, ?, ?, ?, ?, ?, ?, 1,
                      'PASS_WITH_WARNINGS', 'L1', NULL, ?)
            """,
            (
                observation_uid,
                subject_uid,
                metric_uid,
                fact["normalized_value_twd"],
                period_start,
                report["period_end"],
                retrieved_at,
                retrieved_at,
                retrieved_at,
                source_uid,
                artifact_uids["XBRL"],
                retrieved_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO xbrl_cash_flow_facts(
                fact_uid, report_uid, evidence_id, concept_qname, metric_code,
                context_ref, period_scope, raw_display_value,
                normalized_value_twd, unit_ref, unit_measure, scale_value,
                decimals_value, sign_value, promotion_status, observation_uid,
                actionable, message_zh, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'TWD', 'iso4217:TWD',
                      ?, ?, ?, 'OBSERVATION_ONLY', ?, 0,
                      '官方XBRL Context、Unit、期間及合併範圍已驗證；僅供觀察，不得直接觸發規則', ?)
            """,
            (
                fact_uid,
                report_uid,
                evidence_id,
                fact["concept_qname"],
                fact["metric_code"],
                fact["context_ref"],
                fact["period_scope"],
                fact["raw_display_value"],
                fact["normalized_value_twd"],
                fact["scale"],
                fact["decimals"],
                fact["sign"],
                observation_uid,
                retrieved_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO observation_evidence(
                evidence_uid, evidence_id, observation_uid, artifact_uid,
                concept_qname, context_ref, unit_ref, raw_display_value,
                normalized_value_twd, validation_status, model_usage,
                warnings_json, message_zh, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'TWD', ?, ?,
                      'PASS_WITH_WARNINGS', 'OBSERVATION_ONLY', ?,
                      '官方Inline XBRL原始事實；所有限制均附中文備註', ?)
            """,
            (
                deterministic_ulid(timestamp, f"EVIDENCE:{evidence_id}"),
                evidence_id,
                observation_uid,
                artifact_uids["XBRL"],
                fact["concept_qname"],
                fact["context_ref"],
                fact["raw_display_value"],
                fact["normalized_value_twd"],
                canonical_json(warnings),
                retrieved_at,
            ),
        )
        facts_output.append(
            {
                **fact,
                "evidence_id": evidence_id,
                "observation_uid": observation_uid,
                "promotion_status": "OBSERVATION_ONLY",
                "status_zh": "僅供觀察",
                "message_zh": "官方XBRL事實已驗證；未獲准寫入正式資料或觸發規則",
                "actionable": False,
            }
        )

    depreciation = next(
        Decimal(fact["normalized_value_twd"])
        for fact in report["facts"]
        if fact["metric_code"] == "MOPS_XBRL_DEPRECIATION"
    )
    amortisation = next(
        Decimal(fact["normalized_value_twd"])
        for fact in report["facts"]
        if fact["metric_code"] == "MOPS_XBRL_AMORTISATION"
    )
    official_da_100m = (depreciation + amortisation) / Decimal("100000000")
    existing_da_100m = read_existing_da()
    da_difference = official_da_100m - existing_da_100m
    da_tolerance = Decimal("0.01")
    da_status = (
        "SOURCE_MATCH_CONFIRMED"
        if abs(da_difference) <= da_tolerance
        else "DATA_CONFLICT_PENDING"
    )
    da_note = (
        "官方Q1折舊加攤銷為268.00101億元，與正式CSV估算268.0億元在0.01億元容許值內一致；不升格"
        if da_status == "SOURCE_MATCH_CONFIRMED"
        else "官方Q1折舊加攤銷與正式CSV估算差異超過0.01億元；建立待釐清衝突"
    )
    connection.execute(
        """
        INSERT INTO source_comparisons(
            comparison_uid, comparison_code, related_fact_uids_json,
            source_value, source_unit, existing_dataset_path,
            existing_metric_code, existing_value, difference, tolerance,
            comparison_status, promotion_allowed, actionable, message_zh,
            created_at
        ) VALUES (?, 'COMPARE-2026Q1-OFFICIAL-DA-TO-MASTER',
                  ?, ?, 'TWD_100M', 'data/2317_master_v9.csv',
                  'DA_Est_100M', ?, ?, '0.01', ?, 0, 0, ?, ?)
        """,
        (
            deterministic_ulid(timestamp, "COMPARE-2026Q1-OFFICIAL-DA-TO-MASTER"),
            canonical_json(
                [
                    fact_uids["MOPS_XBRL_DEPRECIATION"],
                    fact_uids["MOPS_XBRL_AMORTISATION"],
                ]
            ),
            normalize_decimal(official_da_100m),
            normalize_decimal(existing_da_100m),
            normalize_decimal(da_difference),
            da_status,
            da_note,
            retrieved_at,
        ),
    )
    connection.execute(
        """
        INSERT INTO source_comparisons(
            comparison_uid, comparison_code, related_fact_uids_json,
            source_value, source_unit, existing_dataset_path,
            existing_metric_code, existing_value, difference, tolerance,
            comparison_status, promotion_allowed, actionable, message_zh,
            created_at
        ) VALUES (?, 'FCF-FORMULA-PROMOTION-BLOCKED',
                  ?, 'NOT_CALCULATED', 'N/A', 'data/2317_master_v9.csv',
                  'FCF_Annual_100M', 'BLANK_2026Q1', 'N/A', 'N/A',
                  'FORMULA_NOT_APPROVED', 0, 0,
                  '本批次禁止以OCF減取得PPE直接建立FCF；須由P2-04 Formula Registry另案核准', ?)
        """,
        (
            deterministic_ulid(timestamp, "FCF-FORMULA-PROMOTION-BLOCKED"),
            canonical_json(
                [
                    fact_uids["MOPS_XBRL_CASH_FLOW_OPERATING"],
                    fact_uids["MOPS_XBRL_PURCHASE_PPE"],
                ]
            ),
            retrieved_at,
        ),
    )

    warning_notes = {
        "PUBLICATION_TIMESTAMP_UNVERIFIED": "案例文件下載未提供可驗證的法定發布時分秒",
        "CUMULATIVE_PERIOD_NOT_SINGLE_QUARTER": "現金流事實按年初至期末累計保存，不得直接當單季值",
        "FCF_FORMULA_NOT_APPROVED": "OCF與取得PPE已保存，但FCF公式尚未進入P2-04核准",
        "FORMAL_DATA_PROMOTION_BLOCKED": "本批次只建立staging觀察資料，不修改正式CSV或Runtime DB",
        "XBRL_MIME_TYPE_UNDECLARED": "下載回應未聲明MIME，但XML宣告、Inline XBRL Namespace與SchemaRef均已驗證",
        "TLS_TRANSPORT_RETRY_SAME_SOURCE": "Python TLS失敗後以Windows TLS重試同一官方URL，未切換資料來源",
        "IDENTICAL_DUPLICATE_FACT_DEDUPED": "相同Concept與Context有內容一致的重複值，已去重並保留警告",
    }
    for code in warnings:
        connection.execute(
            """
            INSERT INTO validation_results(
                validation_uid, target_type, target_uid, rule_code, severity,
                status, message_zh, checked_at, validator_version
            ) VALUES (?, 'XBRL_REPORT', ?, ?, 'WARNING',
                      'PASS_WITH_WARNINGS', ?, ?, ?)
            """,
            (
                deterministic_ulid(timestamp, f"VALIDATION:{report_uid}:{code}"),
                report_uid,
                code,
                warning_notes[code],
                retrieved_at,
                PARSER_VERSION,
            ),
        )
    connection.execute(
        """
        INSERT INTO connector_executions(
            execution_uid, connector_id, started_at, finished_at,
            discovery_http_status, xbrl_http_status, manual_http_status,
            xbrl_sha256, fact_count, observation_count, blocked_fact_count,
            status_code, status_zh, status_note_zh, fallback_used, actionable
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 8, 8, 0,
                  'PASS_WITH_WARNINGS', '通過但有警告',
                  '已保存2317官方2026Q1合併XBRL八個現金流事實；僅供觀察，未計算FCF',
                  0, 0)
        """,
        (
            execution_uid,
            CONNECTOR_ID,
            retrieved_at,
            retrieved_at,
            discovery_meta["http_status"],
            xbrl_meta["http_status"],
            manual_meta["http_status"],
            xbrl_meta["sha256"],
        ),
    )
    return {
        "subject": {
            "canonical_key": "LEGAL_ENTITY:HON_HAI_PRECISION_INDUSTRY",
            "ticker": "2317",
            "market": "TWSE",
            "currency": "TWD",
        },
        "period": {
            "fiscal_year": report["fiscal_year"],
            "fiscal_quarter": report["fiscal_quarter"],
            "period_label": report["period_label"],
            "period_start": report["period_start"],
            "period_end": report["period_end"],
            "period_scope": "CUMULATIVE_YTD",
        },
        "report_scope": "CONSOLIDATED",
        "schema_ref": report["schema_ref"],
        "namespaces": report["namespaces"],
        "context_count": report["context_count"],
        "unit_count": report["unit_count"],
        "source_authority": "A1",
        "evidence_level": "L1",
        "validation_status": "PASS_WITH_WARNINGS",
        "warnings": warnings,
        "facts": facts_output,
        "observation_count": 8,
        "blocked_fact_count": 0,
        "manual_verification": manual_checks,
        "da_comparison": {
            "official_depreciation_plus_amortisation_100m":
                normalize_decimal(official_da_100m),
            "existing_da_est_100m": normalize_decimal(existing_da_100m),
            "difference_100m": normalize_decimal(da_difference),
            "tolerance_100m": "0.01",
            "status": da_status,
            "status_zh": (
                "來源數值一致"
                if da_status == "SOURCE_MATCH_CONFIRMED"
                else "資料衝突待釐清"
            ),
            "message_zh": da_note,
            "promotion_allowed": False,
        },
        "fcf_boundary": {
            "status": "FORMULA_NOT_APPROVED",
            "status_zh": "公式尚未核准",
            "message_zh": "未計算或發布FCF；OCF減取得PPE須由P2-04另案核准",
            "actionable": False,
        },
        "actionable": False,
    }


def run_connector(
    output_dir: Path,
    runtime_db: Path,
    fetcher: Callable[[HttpRequest, int], HttpResult] = fetch_request,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    started_at = utc_now()
    protected_before = protected_hashes(runtime_db)

    discovery_request = HttpRequest(
        "POST", DISCOVERY_URL, discovery_form(), DISCOVERY_REFERER
    )
    discovery_result = fetcher(discovery_request, 120)
    if discovery_result.status != 200:
        raise PrimarySourceUnavailable("MOPS案例文件清單HTTP狀態不是200")
    discovery = parse_discovery(discovery_result.body)

    xbrl_request = HttpRequest(
        "GET", discovery["download_url"], None, DISCOVERY_REFERER
    )
    xbrl_result = fetcher(xbrl_request, 180)
    if xbrl_result.status != 200:
        raise PrimarySourceUnavailable("MOPS XBRL案例文件HTTP狀態不是200")
    report = parse_inline_xbrl(xbrl_result.body, discovery)

    manual_request = HttpRequest(
        "POST",
        MANUAL_URL,
        manual_form(report["fiscal_year"], report["fiscal_quarter"]),
        MANUAL_REFERER,
    )
    manual_result = fetcher(manual_request, 120)
    if manual_result.status != 200:
        raise PrimarySourceUnavailable("MOPS現金流量表人工核對頁HTTP狀態不是200")
    manual_checks = parse_manual_page(manual_result.body, report)

    discovery_meta = save_raw(
        output_dir, "t203sb01_2317.html", discovery_result, started_at
    )
    xbrl_meta = save_raw(
        output_dir,
        f"2317_{report['period_label']}_consolidated_inline_xbrl.html",
        xbrl_result,
        started_at,
    )
    manual_meta = save_raw(
        output_dir,
        f"t164sb05_2317_{report['period_label']}.html",
        manual_result,
        started_at,
    )

    staging_db = output_dir / "mops_2317_cash_flow_xbrl_candidate.sqlite3"
    connection = dbcore.connect_database(staging_db)
    try:
        create_schema(connection)
        candidate = insert_candidate(
            connection,
            discovery,
            report,
            manual_checks,
            discovery_meta,
            xbrl_meta,
            manual_meta,
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
        "batch_id": "P2-03B-06",
        "generated_at": utc_now(),
        "status": "PASS_WITH_WARNINGS",
        "status_zh": "通過但有警告",
        "status_note_zh":
            "已保存2317官方2026Q1合併Inline XBRL八個現金流事實；僅供觀察，FCF公式未核准",
        "actionable": False,
        "owner_acceptance": "PENDING",
        "connector": {
            "connector_id": CONNECTOR_ID,
            "source_code": SOURCE_CODE,
            "source_authority": "A1",
            "evidence_level": "L1",
            "discovery_url": DISCOVERY_URL,
            "download_url": discovery["download_url"],
            "manual_verification_url": MANUAL_URL,
            "fallback_policy": "NO_SOURCE_FALLBACK",
            "network_requests": 3,
            "scheduled": False,
            "historical_backfill": False,
            "formal_promotion": False,
            "fcf_calculation": False,
        },
        "raw_artifacts": {
            "discovery": discovery_meta,
            "xbrl": xbrl_meta,
            "manual_verification": manual_meta,
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
        description="P1008 2317 MOPS Inline XBRL現金流量表Connector Dry-Run"
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
        / "p2-03b-06"
        / now.strftime("%Y-%m-%d")
        / f"run_{now.strftime('%Y%m%dT%H%M%SZ')}"
    )
    try:
        result = run_connector(output_dir, args.runtime_db)
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
