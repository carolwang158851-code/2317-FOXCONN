#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1008 observation-only multi-source news scanner v2.

The scanner may fetch approved public sources, but it only writes staging and
runtime observation artifacts. It never appends formal CSV files, never changes
HOLD, and never emits trading instructions.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import warroom_news_scanner_v1 as v1


TOOL_VERSION = "warroom_news_scanner_v2"
MACRO_EVENT_TARGET = v1.MACRO_EVENT_TARGET
MACRO_EVENT_CANDIDATE = v1.MACRO_EVENT_CANDIDATE
SOURCE_MANIFEST = v1.SOURCE_MANIFEST
EVENT_REVIEW_STATE = v1.EVENT_REVIEW_STATE
MACRO_EVENT_COLUMNS = v1.MACRO_EVENT_COLUMNS
SCAN_WINDOWS = v1.SCAN_WINDOWS
ALLOWED_SOURCE_TIERS = v1.ALLOWED_SOURCE_TIERS

USER_AGENT = "P1008WarroomNewsScanner/2.0 (+local-owner-approved-observation)"
DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_MAX_ITEMS_PER_SOURCE = 12
DEFAULT_MAX_SEARCH_QUERIES = 6
CRAWLER_GOVERNANCE_STATE = Path("runtime/news_crawler_governance_state.json")
CTEE_SOURCE_ID = "commercial_times_search"
DEFAULT_DEPRECATED_URL_PATTERNS = [
    "news.cnyes.com/search/all?keyword=",
    "www.cnyes.com/search/all?keyword=",
]

DIRECT_KEYWORDS = [
    "2317",
    "hon hai",
    "foxconn",
    "foxconn industrial internet",
    "foxconn technology group",
    "鴻海",
    "鴻海精密",
    "富士康",
    "工業富聯",
    "FII",
]

CUSTOMER_SUPPLY_KEYWORDS = [
    "nvidia",
    "apple",
    "ai server",
    "ai伺服器",
    "gb200",
    "gb300",
    "blackwell",
    "iphone",
    "server",
    "supply chain",
    "供應鏈",
    "伺服器",
    "雲端",
    "代工",
    "電動車",
    "MIH",
]

MACRO_FX_KEYWORDS = [
    "fed",
    "fomc",
    "cpi",
    "rate",
    "rates",
    "dxy",
    "twd",
    "usd/twd",
    "us10y",
    "10-year",
    "jpy",
    "boj",
    "oil",
    "wti",
    "tariff",
    "export control",
    "sanction",
    "geopolitical",
    "earthquake",
    "war",
    "美元指數",
    "美元台幣",
    "台幣",
    "匯率",
    "利率",
    "美債",
    "油價",
    "關稅",
    "出口管制",
    "制裁",
    "地震",
    "停工",
    "戰爭",
    "供應鏈中斷",
]

DEFAULT_QUERY_MATRIX = [
    "鴻海",
    "2317",
    "Hon Hai",
    "Foxconn",
    "富士康",
    "鴻海 AI server",
    "Foxconn NVIDIA GB200",
    "鴻海 匯率",
    "鴻海 出口管制",
]

SOURCE_SCORE = {
    "OFFICIAL": 42,
    "PUBLIC_MARKET": 25,
    "MEDIA": 18,
    "OWNER_NOTE": 35,
    "UNVERIFIED": 5,
}

REVIEW_TRIGGER_KEYWORDS = [
    "2317",
    "hon hai",
    "foxconn",
    "foxconn industrial internet",
    "fii",
    "gb200",
    "gb300",
    "blackwell",
    "ai server",
    "server rack",
    "rack-scale",
    "supply chain",
    "build in america",
    "export control",
    "sanction",
    "tariff",
    "earthquake",
    "shutdown",
    "halt",
    "outage",
    "fire",
    "war",
    "鴻海",
    "富士康",
    "工業富聯",
    "出口管制",
    "制裁",
    "關稅",
    "地震",
    "停工",
    "供應鏈",
    "AI伺服器",
]

CSP_PROVIDER_KEYWORDS = [
    "microsoft",
    "azure",
    "amazon",
    "aws",
    "google cloud",
    "alphabet",
    "meta",
    "oracle",
    "coreweave",
    "openai",
    "xai",
    "tesla",
    "hyperscaler",
    "hyperscale",
    "csp",
    "雲端服務",
    "雲端業者",
    "超大規模",
]

CSP_DEMAND_KEYWORDS = [
    "capex",
    "capital expenditure",
    "data center",
    "datacenter",
    "ai infrastructure",
    "cloud infrastructure",
    "compute capacity",
    "gpu cluster",
    "accelerated computing",
    "cloud capacity",
    "server capacity",
    "資料中心",
    "資本支出",
    "AI基礎建設",
    "AI 基礎建設",
    "雲端基礎建設",
]

AI_PLATFORM_KEYWORDS = [
    "gb200",
    "gb300",
    "blackwell",
    "ai server",
    "server rack",
    "rack-scale",
    "rack scale",
    "nvlink",
    "nvidia ai",
    "AI伺服器",
]

DIRECT_REVIEW_KEYWORDS = [
    "2317",
    "hon hai",
    "foxconn",
    "foxconn industrial internet",
    "fii",
    "鴻海",
    "富士康",
    "工業富聯",
]

DISRUPTION_REVIEW_KEYWORDS = [
    "export control",
    "sanction",
    "tariff",
    "earthquake",
    "shutdown",
    "halt",
    "outage",
    "fire",
    "war",
    "出口管制",
    "制裁",
    "關稅",
    "地震",
    "停工",
    "供應鏈中斷",
]

GENERIC_NAV_TITLES = {
    "apple",
    "mac",
    "ipad",
    "iphone",
    "watch",
    "airpods",
    "tv & home",
    "entertainment",
    "accessories",
    "support",
    "account",
    "login",
    "logout",
    "community",
    "careers",
    "store",
    "shop",
    "news",
    "newsroom",
    "news archive",
    "autonomous machines",
    "cloud & data center",
    "data center",
    "deep learning & ai",
    "design & pro visualization",
    "healthcare",
    "high performance computing",
    "gaming",
    "gaming & entertainment",
    "professional visualization",
    "robotics",
    "self-driving cars",
    "industries",
    "drivers",
    "about nvidia",
    "view all products",
    "gpu technology conference",
    "apple services",
    "apple stories",
    "apple pay",
    "apple store",
    "apple store account",
    "apple one",
    "apple tv",
    "apple music",
    "vision",
    "tv 和家庭",
    "登出",
    "登入",
    "管理你的 apple 帳號",
    "apple store 帳號",
    "商店",
}

LISTING_PATH_SEGMENTS = {
    "news",
    "newsroom",
    "archive",
    "search",
    "tag",
    "tags",
    "category",
    "categories",
    "data-center",
    "deep-learning-ai",
    "autonomous-machines",
    "design-visualization",
    "healthcare",
    "high-performance-computing",
    "self-driving-cars",
    "geforce",
    "industries",
    "download",
    "about-nvidia",
    "careers",
    "communities",
    "products.html",
    "gtc",
    "apple-vision-pro",
    "apple-services",
    "apple-stories",
    "apple-pay",
    "apple-one",
    "apple-tv",
    "apple-music",
    "account",
    "tv-home",
    "shop",
    "store",
    "mac",
}


# Make v1 helpers use the corrected v2 keyword matrix when imported here.
v1.TOOL_VERSION = TOOL_VERSION
v1.DIRECT_KEYWORDS = DIRECT_KEYWORDS
v1.CUSTOMER_SUPPLY_KEYWORDS = CUSTOMER_SUPPLY_KEYWORDS
v1.MACRO_FX_KEYWORDS = MACRO_FX_KEYWORDS


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv_dicts(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    return v1.read_csv_dicts(path)


def write_csv_rows(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    v1.write_csv_rows(path, columns, rows)


def parse_bool(value: Any) -> bool:
    return v1.parse_bool(value)


def parse_int(value: Any, default: int = 0) -> int:
    return v1.parse_int(value, default)


def parse_timestamp(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value or "").strip()
    if not text:
        return fallback
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed.replace(tzinfo=None)
    except ValueError:
        pass
    try:
        parsed_email = parsedate_to_datetime(text)
        return parsed_email.replace(tzinfo=None)
    except (TypeError, ValueError, AttributeError):
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return fallback


def choose_scan_window(name: str) -> str:
    return v1.choose_scan_window(name)


def normalize_text(*parts: Any) -> str:
    return v1.normalize_text(*parts)


def contains_any(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(keyword.lower() in lower for keyword in keywords)


def row_signal_text(row: dict[str, Any], include_source_name: bool = False) -> str:
    parsed_url = urllib.parse.urlparse(str(row.get("SourceUrl") or ""))
    url_path = urllib.parse.unquote(parsed_url.path)
    parts: list[Any] = [
        row.get("EventTitle"),
        row.get("SummaryZh"),
        row.get("DecisionImpactZh"),
        row.get("RiskTag"),
        row.get("RelatedMetrics"),
        url_path,
    ]
    if include_source_name:
        parts.append(row.get("SourceName"))
    return normalize_text(*parts)


def has_csp_demand_signal(row: dict[str, Any]) -> bool:
    text = row_signal_text(row, include_source_name=True)
    return contains_any(text, CSP_PROVIDER_KEYWORDS) and (
        contains_any(text, CSP_DEMAND_KEYWORDS) or contains_any(text, AI_PLATFORM_KEYWORDS)
    )


def has_ai_platform_supply_signal(row: dict[str, Any]) -> bool:
    return contains_any(row_signal_text(row, include_source_name=True), AI_PLATFORM_KEYWORDS)


def has_review_trigger(row: dict[str, Any], relevance_tag: str) -> bool:
    text = row_signal_text(row, include_source_name=True)
    if contains_any(text, DIRECT_REVIEW_KEYWORDS):
        return True
    if contains_any(text, DISRUPTION_REVIEW_KEYWORDS) and (
        contains_any(text, DIRECT_REVIEW_KEYWORDS + CSP_PROVIDER_KEYWORDS + AI_PLATFORM_KEYWORDS)
    ):
        return True
    if has_csp_demand_signal(row) and (
        has_ai_platform_supply_signal(row) or relevance_tag in {"CSP_CAPEX_DEMAND", "DIRECT_2317"}
    ):
        return True
    return False


def relevance_score(row: dict[str, Any]) -> tuple[int, str]:
    text = row_signal_text(row)
    if contains_any(text, DIRECT_KEYWORDS):
        return 45, "DIRECT_2317"
    if has_csp_demand_signal(row):
        return 36, "CSP_CAPEX_DEMAND"
    if contains_any(text, CUSTOMER_SUPPLY_KEYWORDS):
        return 30, "CUSTOMER_SUPPLY_CHAIN"
    if contains_any(text, MACRO_FX_KEYWORDS):
        return 18, "MACRO_FX_MARKET"
    return 0, "LOW_RELEVANCE"


def level_rank(level: str) -> int:
    return v1.level_rank(level)


def review_deadline(generated_at: datetime, level: str) -> str:
    return v1.review_deadline(generated_at, level)


def classify_fetch_error(error: str) -> str:
    lower = str(error or "").lower()
    if "10061" in lower or "connection refused" in lower or "actively refused" in lower:
        return "CONNECTION_REFUSED"
    if "timed out" in lower or "timeout" in lower:
        return "TIMEOUT_TRANSIENT"
    if "getaddrinfo" in lower or "name resolution" in lower or "nodename" in lower:
        return "DNS_ERROR"
    if "proxy" in lower:
        return "PROXY_ERROR"
    if "certificate" in lower or "ssl" in lower or "tls" in lower:
        return "TLS_ERROR"
    if "http error 403" in lower:
        return "HTTP_403_POLICY_BLOCKED"
    if "http error 404" in lower:
        return "HTTP_404"
    return "FETCH_ERROR"


def _crawler_now(args: argparse.Namespace) -> datetime:
    supplied = getattr(args, "_crawler_now_utc", None)
    if isinstance(supplied, datetime):
        return supplied if supplied.tzinfo else supplied.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _crawler_source_state(args: argparse.Namespace, source_id: str) -> dict[str, Any]:
    state = getattr(args, "_crawler_state", None)
    if not isinstance(state, dict):
        state = {"sources": {}}
        setattr(args, "_crawler_state", state)
    sources = state.setdefault("sources", {})
    return sources.setdefault(source_id, {})


def _ctee_web_search_candidate() -> dict[str, Any]:
    return {
        "status": "CANDIDATE_ONLY_NOT_EXECUTED",
        "domain": "ctee.com.tw",
        "query": "site:ctee.com.tw 鴻海 OR Foxconn OR 2317",
        "reason": "Direct source is under HTTP 403 policy cooldown; anti-bot controls must not be bypassed.",
    }


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def dependency_status() -> dict[str, dict[str, str]]:
    status: dict[str, dict[str, str]] = {}
    for module_name in ["feedparser", "trafilatura", "playwright"]:
        try:
            __import__(module_name)
            status[module_name] = {"available": "true", "error": ""}
        except Exception as error:  # noqa: BLE001 - optional dependency diagnostics.
            status[module_name] = {"available": "false", "error": str(error)}
    return status


@dataclass
class FetchResult:
    ok: bool
    url: str
    final_url: str
    status: str
    content_type: str
    text: str
    error: str
    fetch_mode: str
    duration_ms: int


class BasicHTMLExtractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.meta_description = ""
        self.anchors: list[dict[str, str]] = []
        self.times: list[str] = []
        self.text_parts: list[str] = []
        self._in_title = False
        self._current_href = ""
        self._current_anchor_text: list[str] = []
        self._capture_text = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name.lower(): value or "" for name, value in attrs}
        if tag.lower() == "title":
            self._in_title = True
        elif tag.lower() == "meta":
            key = (attr_map.get("name") or attr_map.get("property") or "").lower()
            if key in {"description", "og:description"} and attr_map.get("content"):
                self.meta_description = attr_map["content"].strip()
        elif tag.lower() == "a" and attr_map.get("href"):
            self._current_href = urllib.parse.urljoin(self.base_url, attr_map["href"])
            self._current_anchor_text = []
        elif tag.lower() == "time":
            timestamp = attr_map.get("datetime") or attr_map.get("content") or ""
            if timestamp:
                self.times.append(timestamp)
        if tag.lower() in {"p", "article", "section", "h1", "h2", "h3", "li", "td"}:
            self._capture_text = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
        elif tag.lower() == "a" and self._current_href:
            text = " ".join(part.strip() for part in self._current_anchor_text if part.strip())
            if text:
                self.anchors.append({"href": self._current_href, "text": text[:240]})
            self._current_href = ""
            self._current_anchor_text = []
        if tag.lower() in {"p", "article", "section", "h1", "h2", "h3", "li", "td"}:
            self._capture_text = False

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        if self._current_href:
            self._current_anchor_text.append(text)
        if self._capture_text:
            self.text_parts.append(text)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()

    @property
    def body_text(self) -> str:
        return " ".join(self.text_parts).strip()


def basic_html_extract(text: str, base_url: str) -> dict[str, Any]:
    parser = BasicHTMLExtractor(base_url)
    try:
        parser.feed(text)
    except Exception:
        pass
    return {
        "title": html.unescape(parser.title),
        "summary": html.unescape(parser.meta_description or parser.body_text[:500]),
        "anchors": parser.anchors,
        "publishedAt": parser.times[0] if parser.times else "",
        "extractor": "basic_html_parser",
    }


def trafilatura_extract(text: str, base_url: str) -> dict[str, Any]:
    try:
        import trafilatura  # type: ignore
    except Exception:
        return basic_html_extract(text, base_url)
    try:
        metadata = trafilatura.extract_metadata(text, default_url=base_url)
        extracted = trafilatura.extract(text, url=base_url, include_links=False, include_comments=False) or ""
        basic = basic_html_extract(text, base_url)
        title = getattr(metadata, "title", "") if metadata else ""
        date = getattr(metadata, "date", "") if metadata else ""
        description = getattr(metadata, "description", "") if metadata else ""
        return {
            "title": title or basic.get("title", ""),
            "summary": description or extracted[:500] or basic.get("summary", ""),
            "anchors": basic.get("anchors", []),
            "publishedAt": date or basic.get("publishedAt", ""),
            "extractor": "trafilatura",
        }
    except Exception:
        return basic_html_extract(text, base_url)


def fetch_url(url: str, timeout_seconds: int) -> FetchResult:
    started = time.monotonic()
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/html;q=0.9, */*;q=0.5",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(2_000_000)
            content_type = response.headers.get("Content-Type", "")
            charset = response.headers.get_content_charset() or "utf-8"
            text = raw.decode(charset, errors="replace")
            return FetchResult(
                ok=True,
                url=url,
                final_url=response.geturl(),
                status=str(getattr(response, "status", "200")),
                content_type=content_type,
                text=text,
                error="",
                fetch_mode="https",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
    except Exception as error:  # noqa: BLE001 - scanner must report source health, not crash.
        return FetchResult(
            ok=False,
            url=url,
            final_url=url,
            status=classify_fetch_error(str(error)),
            content_type="",
            text="",
            error=str(error),
            fetch_mode="https",
            duration_ms=int((time.monotonic() - started) * 1000),
        )


def powershell_fetch_url(url: str, timeout_seconds: int) -> FetchResult:
    started = time.monotonic()
    if sys.platform != "win32":
        return FetchResult(False, url, url, "POWERSHELL_UNAVAILABLE", "", "", "PowerShell fallback is Windows-only.", "powershell", 0)
    command = (
        "$ProgressPreference='SilentlyContinue';"
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new();"
        "$u=$env:P1008_FETCH_URL;$t=[int]$env:P1008_FETCH_TIMEOUT;"
        "try{"
        "$r=Invoke-WebRequest -UseBasicParsing -Uri $u -TimeoutSec $t -MaximumRedirection 5;"
        "$final=$u;"
        "try{if($r.BaseResponse -and $r.BaseResponse.ResponseUri){$final=$r.BaseResponse.ResponseUri.AbsoluteUri}}catch{};"
        "$ct='';try{$ct=[string]$r.Headers['Content-Type']}catch{};"
        "\"P1008_STATUS=$($r.StatusCode)\";"
        "\"P1008_FINAL=$final\";"
        "\"P1008_CONTENT_TYPE=$ct\";"
        "\"P1008_BODY_BEGIN\";"
        "$body=[string]$r.Content;"
        "if($body.Length -gt 2000000){$body=$body.Substring(0,2000000)};"
        "$body;"
        "}catch{"
        "\"P1008_ERROR=$($_.Exception.Message)\";"
        "exit 2"
        "}"
    )
    env = os.environ.copy()
    env["P1008_FETCH_URL"] = url
    env["P1008_FETCH_TIMEOUT"] = str(max(1, timeout_seconds))
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(3, timeout_seconds + 5),
            check=False,
            env=env,
        )
    except Exception as error:  # noqa: BLE001 - fallback diagnostics only.
        return FetchResult(
            ok=False,
            url=url,
            final_url=url,
            status=classify_fetch_error(str(error)),
            content_type="",
            text="",
            error=str(error),
            fetch_mode="powershell",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if completed.returncode != 0:
        error = stdout.strip() or stderr.strip() or f"PowerShell fetch exited {completed.returncode}"
        return FetchResult(
            ok=False,
            url=url,
            final_url=url,
            status=classify_fetch_error(error),
            content_type="",
            text="",
            error=error,
            fetch_mode="powershell",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    marker = "P1008_BODY_BEGIN"
    header_text, _, body = stdout.partition(marker)
    headers: dict[str, str] = {}
    for line in header_text.splitlines():
        if line.startswith("P1008_") and "=" in line:
            key, value = line.split("=", 1)
            headers[key] = value.strip()
    status = headers.get("P1008_STATUS", "200")
    return FetchResult(
        ok=True,
        url=url,
        final_url=headers.get("P1008_FINAL", url) or url,
        status=status,
        content_type=headers.get("P1008_CONTENT_TYPE", ""),
        text=body.lstrip("\r\n"),
        error="",
        fetch_mode="powershell",
        duration_ms=int((time.monotonic() - started) * 1000),
    )


_browser_unavailable_error = ""


def browser_fetch_url(url: str, timeout_seconds: int) -> FetchResult:
    global _browser_unavailable_error
    started = time.monotonic()
    if _browser_unavailable_error:
        return FetchResult(False, url, url, "BROWSER_UNAVAILABLE", "", "", _browser_unavailable_error, "browser", 0)
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as error:  # noqa: BLE001
        _browser_unavailable_error = str(error)
        return FetchResult(False, url, url, "BROWSER_UNAVAILABLE", "", "", str(error), "browser", 0)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            text = page.content()
            final_url = page.url
            status = str(response.status) if response else "BROWSER_OK"
            browser.close()
            return FetchResult(
                ok=True,
                url=url,
                final_url=final_url,
                status=status,
                content_type="text/html",
                text=text,
                error="",
                fetch_mode="browser",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
    except Exception as error:  # noqa: BLE001
        return FetchResult(
            ok=False,
            url=url,
            final_url=url,
            status=classify_fetch_error(str(error)),
            content_type="",
            text="",
            error=str(error),
            fetch_mode="browser",
            duration_ms=int((time.monotonic() - started) * 1000),
        )


def parse_feed_entries(text: str, source: dict[str, Any], fetch: FetchResult) -> list[dict[str, Any]]:
    try:
        import feedparser  # type: ignore
    except Exception:
        return parse_feed_entries_basic(text, source, fetch)
    parsed = feedparser.parse(text)
    rows: list[dict[str, Any]] = []
    for entry in parsed.entries or []:
        link = entry.get("link") or fetch.final_url
        title = str(entry.get("title") or "").strip()
        summary = re.sub(r"<[^>]+>", " ", str(entry.get("summary") or entry.get("description") or "")).strip()
        published = entry.get("published") or entry.get("updated") or ""
        rows.append(raw_event_from_source(source, title, link, summary, published, "RSS_FEED", fetch))
    return rows


def parse_feed_entries_basic(text: str, source: dict[str, Any], fetch: FetchResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError:
        return rows

    def local(tag: str) -> str:
        return tag.split("}", 1)[-1].lower()

    for item in root.iter():
        if local(item.tag) not in {"item", "entry"}:
            continue
        fields: dict[str, str] = {}
        for child in list(item):
            key = local(child.tag)
            if key == "link":
                fields[key] = child.attrib.get("href") or (child.text or "")
            elif child.text:
                fields[key] = child.text
        title = (fields.get("title") or "").strip()
        link = urllib.parse.urljoin(fetch.final_url, (fields.get("link") or fetch.final_url).strip())
        summary = (fields.get("summary") or fields.get("description") or fields.get("content") or "").strip()
        published = fields.get("published") or fields.get("updated") or fields.get("pubdate") or ""
        rows.append(raw_event_from_source(source, title, link, summary, published, "RSS_FEED_BASIC", fetch))
    return rows


def parse_sitemap_entries(text: str, source: dict[str, Any], fetch: FetchResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError:
        return rows
    urls: list[tuple[str, str]] = []
    for url_node in root.iter():
        if not url_node.tag.lower().endswith("url"):
            continue
        loc = ""
        lastmod = ""
        for child in list(url_node):
            tag = child.tag.split("}", 1)[-1].lower()
            if tag == "loc":
                loc = (child.text or "").strip()
            elif tag == "lastmod":
                lastmod = (child.text or "").strip()
        if loc:
            urls.append((loc, lastmod))
    for loc, lastmod in urls[: safe_int(source.get("maxItemsPerSource"), DEFAULT_MAX_ITEMS_PER_SOURCE)]:
        decoded = urllib.parse.unquote(loc)
        decoded_path = urllib.parse.unquote(urllib.parse.urlparse(decoded).path)
        title = decoded.rsplit("/", 1)[-1] or decoded
        if not is_relevant_text(f"{title} {decoded_path}"):
            continue
        rows.append(raw_event_from_source(source, title, loc, decoded, lastmod, "SITEMAP", fetch))
    return rows


def parse_html_entries(text: str, source: dict[str, Any], fetch: FetchResult) -> list[dict[str, Any]]:
    extracted = trafilatura_extract(text, fetch.final_url)
    rows: list[dict[str, Any]] = []
    title = str(extracted.get("title") or "").strip()
    summary = str(extracted.get("summary") or "").strip()
    published = str(extracted.get("publishedAt") or "").strip()
    final_path = urllib.parse.unquote(urllib.parse.urlparse(fetch.final_url).path)
    if (
        title
        and is_relevant_text(f"{title} {summary} {final_path}")
        and not looks_like_listing_or_navigation(title, fetch.final_url, "HTML_ARTICLE")
    ):
        rows.append(raw_event_from_source(source, title, fetch.final_url, summary, published, "HTML_ARTICLE", fetch))

    seen_links: set[str] = set()
    for anchor in extracted.get("anchors", []) or []:
        href = str(anchor.get("href") or "").strip()
        anchor_text = re.sub(r"\s+", " ", str(anchor.get("text") or "").strip())
        if not href or href in seen_links or not anchor_text:
            continue
        seen_links.add(href)
        href_path = urllib.parse.unquote(urllib.parse.urlparse(href).path)
        combined = f"{anchor_text} {href_path}"
        if not is_relevant_text(combined):
            continue
        if looks_like_listing_or_navigation(anchor_text, href, "HTML_LINK"):
            continue
        rows.append(raw_event_from_source(source, anchor_text, href, summary[:260], published, "HTML_LINK", fetch))
        if len(rows) >= safe_int(source.get("maxItemsPerSource"), DEFAULT_MAX_ITEMS_PER_SOURCE):
            break
    return rows


def is_relevant_text(text: str) -> bool:
    return contains_any(text, DIRECT_KEYWORDS + CUSTOMER_SUPPLY_KEYWORDS + MACRO_FX_KEYWORDS)


def has_date_or_article_path(url: str) -> bool:
    parsed = urllib.parse.urlparse(str(url or ""))
    path = parsed.path.lower()
    if re.search(r"/20\d{2}([/-]\d{1,2})?([/-]\d{1,2})?/", path):
        return True
    if re.search(r"/\d{4}/\d{1,2}/\d{1,2}/", path):
        return True
    if re.search(r"/article/|/articles/|/story/|/blog/|/blogs/|/press-release/|/press-releases/|/公告|/newsroom/20\d{2}", path):
        return True
    return False


def looks_like_listing_or_navigation(title: str, url: str, discovery_mode: str = "") -> bool:
    title_clean = re.sub(r"\s+", " ", str(title or "").strip()).lower()
    parsed = urllib.parse.urlparse(str(url or ""))
    path = parsed.path.strip("/").lower()
    segments = [segment for segment in path.split("/") if segment]
    mode = str(discovery_mode or "").upper()

    if has_date_or_article_path(url):
        return False
    if not segments and mode in {"HTML_ARTICLE", "HTML_LINK", "SITEMAP"}:
        return True
    if title_clean in GENERIC_NAV_TITLES:
        return True
    if any(marker in title_clean for marker in ["news archive", "search results", "site search", "新聞搜尋"]):
        return True
    if any(marker in title_clean for marker in ["搜尋結果", "登入", "登出", "帳號", "account"]):
        return True
    if len(segments) <= 2 and any(segment in LISTING_PATH_SEGMENTS for segment in segments):
        return True
    if parsed.fragment and not parsed.query and (not segments or any(segment in LISTING_PATH_SEGMENTS for segment in segments)):
        return True
    if parsed.query and any(key in parsed.query.lower() for key in ["q=", "query=", "search=", "keyword="]) and mode != "HTML_LINK":
        return True
    return False


def raw_event_from_source(
    source: dict[str, Any],
    title: str,
    url: str,
    summary: str,
    published_at: str,
    discovery_mode: str,
    fetch: FetchResult,
) -> dict[str, Any]:
    source_tier = str(source.get("sourceTier") or "UNVERIFIED").upper()
    if source_tier not in ALLOWED_SOURCE_TIERS:
        source_tier = "UNVERIFIED"
    return {
        "PublishedAt": published_at,
        "EventType": "NEWS",
        "EventTitle": html.unescape(re.sub(r"\s+", " ", str(title or "").strip()))[:240],
        "Region": source.get("region") or "GLOBAL",
        "SourceTier": source_tier,
        "SourceName": source.get("sourceName") or source.get("sourceId") or "UNKNOWN_SOURCE",
        "SourceUrl": url,
        "SummaryZh": html.unescape(re.sub(r"\s+", " ", str(summary or "").strip()))[:700],
        "DecisionImpactZh": "Observation only. Owner review is required before any formal conclusion changes.",
        "RiskTag": "",
        "RelatedMetrics": "",
        "Keywords": " ".join(source.get("keywords", []) or []),
        "DiscoveryMode": discovery_mode,
        "SourceId": source.get("sourceId") or "",
        "FetchMode": fetch.fetch_mode,
        "FetchStatus": fetch.status,
        "OfficialConfirmation": source_tier == "OFFICIAL",
        "MarketConfirmation": source_tier == "PUBLIC_MARKET",
        "MissingPublishedAt": not bool(str(published_at or "").strip()),
        "CorroborationCount": "1",
    }


def source_modes(source: dict[str, Any], url: str) -> list[str]:
    raw = source.get("discoveryMode") or source.get("discoveryModes") or []
    if isinstance(raw, str):
        modes = [raw]
    else:
        modes = [str(item) for item in raw if str(item).strip()]
    if not modes:
        connector_type = str(source.get("connectorType") or "").upper()
        if "RSS" in connector_type:
            modes = ["RSS"]
        elif "SITEMAP" in connector_type:
            modes = ["SITEMAP"]
        else:
            modes = ["HTML"]
    lower_url = url.lower()
    if not raw:
        if "sitemap" in lower_url:
            modes = ["SITEMAP"]
        elif lower_url.endswith((".rss", ".xml", ".atom")) or "rss" in lower_url:
            modes = ["RSS"]
    return [mode.upper() for mode in modes]


def query_matrix(manifest: dict[str, Any], source: dict[str, Any]) -> list[str]:
    raw = source.get("queries") or manifest.get("defaultQueryMatrix") or DEFAULT_QUERY_MATRIX
    if not isinstance(raw, list):
        raw = DEFAULT_QUERY_MATRIX
    max_queries = safe_int(source.get("maxSearchQueries"), DEFAULT_MAX_SEARCH_QUERIES)
    return [str(item).strip() for item in raw if str(item).strip()][:max_queries]


def deprecated_url_patterns(manifest: dict[str, Any]) -> list[str]:
    raw = manifest.get("deprecatedUrlPatterns") or []
    patterns = DEFAULT_DEPRECATED_URL_PATTERNS[:]
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, list):
        patterns.extend(str(item).strip().lower() for item in raw if str(item).strip())
    return sorted(set(patterns))


def is_deprecated_source_url(url: str, manifest: dict[str, Any]) -> bool:
    lower_url = str(url or "").lower()
    return any(pattern and pattern in lower_url for pattern in deprecated_url_patterns(manifest))


def urls_for_source(source: dict[str, Any], manifest: dict[str, Any]) -> list[dict[str, str]]:
    urls: list[dict[str, str]] = []
    for key in ["url", "urls", "feedUrls", "sitemapUrls"]:
        raw = source.get(key)
        if isinstance(raw, str) and raw.strip():
            candidate_url = raw.strip()
            if not is_deprecated_source_url(candidate_url, manifest):
                urls.append({"url": candidate_url, "purpose": key})
        elif isinstance(raw, list):
            for item in raw:
                candidate_url = str(item or "").strip()
                if candidate_url and not is_deprecated_source_url(candidate_url, manifest):
                    urls.append({"url": candidate_url, "purpose": key})

    templates = source.get("searchUrlTemplates") or []
    if isinstance(templates, str):
        templates = [templates]
    for template in templates:
        template_text = str(template or "").strip()
        if not template_text or is_deprecated_source_url(template_text, manifest):
            continue
        for query in query_matrix(manifest, source):
            encoded = urllib.parse.quote(query)
            urls.append(
                {
                    "url": template_text.replace("{query}", encoded).replace("{query_raw}", query),
                    "purpose": "searchUrlTemplates",
                }
            )
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in urls:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        deduped.append(item)
    return deduped


def scan_source(
    source: dict[str, Any],
    manifest: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_id = str(source.get("sourceId") or source.get("sourceName") or "UNKNOWN")
    health: dict[str, Any] = {
        "sourceId": source_id,
        "sourceName": source.get("sourceName") or source_id,
        "sourceTier": source.get("sourceTier") or "UNVERIFIED",
        "connectorStatus": source.get("connectorStatus") or "",
        "enabled": bool(source.get("enabled")),
        "requiresNetwork": bool(source.get("requiresNetwork")),
        "status": "SKIPPED",
        "statusZh": "",
        "urlCount": 0,
        "fetchOk": 0,
        "fetchFailed": 0,
        "itemsDiscovered": 0,
        "itemsAccepted": 0,
        "lastError": "",
        "lastErrorType": "",
        "fetchModes": [],
        "severity": "NORMAL",
        "policyBlocked": 0,
    }
    if not source.get("enabled"):
        health["status"] = "DISABLED"
        health["statusZh"] = "來源未啟用。"
        return [], health
    if source.get("requiresNetwork") and args.no_network:
        health["status"] = "SKIPPED_NO_NETWORK"
        health["statusZh"] = "本次以 no-network 執行，跳過網路來源。"
        return [], health
    if source.get("requiresNetwork") and str(source.get("connectorStatus")) != "APPROVED":
        health["status"] = "SKIPPED_NOT_APPROVED"
        health["statusZh"] = "來源尚未 APPROVED，不連網。"
        return [], health
    if not source.get("requiresNetwork"):
        health["status"] = "LOCAL_INPUT_ONLY"
        health["statusZh"] = "本地輸入來源，非爬蟲來源。"
        return [], health

    now_utc = _crawler_now(args)
    governance = _crawler_source_state(args, source_id)
    cadence = str(source.get("scanCadence") or "DAILY").upper()
    health["scanCadence"] = cadence
    if cadence == "WEEKLY":
        last_success = _parse_utc(governance.get("lastSuccessfulAtUtc"))
        if last_success and now_utc - last_success < timedelta(days=7):
            health["status"] = "SKIPPED_CADENCE"
            health["statusZh"] = "每週來源尚未到下一次掃描時間。"
            health["nextEligibleAtUtc"] = (last_success + timedelta(days=7)).isoformat().replace("+00:00", "Z")
            return [], health
    if source_id == CTEE_SOURCE_ID:
        cooldown_until = _parse_utc(governance.get("cooldownUntilUtc"))
        if cooldown_until and now_utc < cooldown_until:
            health.update(
                {
                    "status": "HTTP_403_POLICY_BLOCKED",
                    "statusZh": "工商時報直接抓取處於 24 小時政策冷卻；本次不重試。",
                    "severity": "WARNING",
                    "policyBlocked": 1,
                    "cooldownUntilUtc": cooldown_until.isoformat().replace("+00:00", "Z"),
                    "webSearchCandidate": _ctee_web_search_candidate(),
                }
            )
            return [], health

    timeout = safe_int(source.get("requestTimeoutSeconds"), args.timeout_seconds)
    urls = urls_for_source(source, manifest)
    health["urlCount"] = len(urls)
    if not urls:
        health["status"] = "NO_URL"
        health["statusZh"] = "來源已核准但未設定 URL。"
        return [], health

    rows: list[dict[str, Any]] = []
    max_items = safe_int(source.get("maxItemsPerSource"), DEFAULT_MAX_ITEMS_PER_SOURCE)
    rate_limit = max(0, safe_int(source.get("rateLimitSeconds"), 0))
    for index, url_item in enumerate(urls):
        if index > 0 and rate_limit:
            time.sleep(rate_limit)
        url = url_item["url"]
        fetch = fetch_url(url, timeout)
        if not fetch.ok and fetch.status in {"CONNECTION_REFUSED", "PROXY_ERROR", "TLS_ERROR", "TIMEOUT_TRANSIENT", "FETCH_ERROR"}:
            powershell_fetch = powershell_fetch_url(url, timeout)
            if powershell_fetch.ok:
                fetch = powershell_fetch
            elif not health.get("lastError"):
                health["powershellFallbackError"] = powershell_fetch.error
        if (
            not fetch.ok
            and fetch.status != "HTTP_403_POLICY_BLOCKED"
            and args.browser_fallback
        ):
            browser_fetch = browser_fetch_url(url, timeout)
            if browser_fetch.ok:
                fetch = browser_fetch
            elif not health.get("lastError"):
                health["browserFallbackError"] = browser_fetch.error
        health["fetchModes"] = sorted(set((health.get("fetchModes") or []) + [fetch.fetch_mode]))
        if not fetch.ok:
            if source_id == CTEE_SOURCE_ID and fetch.status == "HTTP_403_POLICY_BLOCKED":
                cooldown_until = now_utc + timedelta(hours=24)
                governance.update(
                    {
                        "lastAttemptAtUtc": now_utc.isoformat().replace("+00:00", "Z"),
                        "lastStatus": "HTTP_403_POLICY_BLOCKED",
                        "cooldownUntilUtc": cooldown_until.isoformat().replace("+00:00", "Z"),
                    }
                )
                health.update(
                    {
                        "policyBlocked": 1,
                        "lastError": fetch.error,
                        "lastErrorType": fetch.status,
                        "cooldownUntilUtc": governance["cooldownUntilUtc"],
                        "webSearchCandidate": _ctee_web_search_candidate(),
                    }
                )
                break
            health["fetchFailed"] += 1
            health["lastError"] = fetch.error
            health["lastErrorType"] = fetch.status
            continue
        health["fetchOk"] += 1
        modes = source_modes(source, fetch.final_url)
        discovered: list[dict[str, Any]] = []
        if "RSS" in modes or "ATOM" in modes:
            discovered.extend(parse_feed_entries(fetch.text, source, fetch))
        if "SITEMAP" in modes:
            discovered.extend(parse_sitemap_entries(fetch.text, source, fetch))
        if "HTML" in modes or "SEARCH" in modes or not discovered:
            discovered.extend(parse_html_entries(fetch.text, source, fetch))
        rows.extend(discovered)
        if len(rows) >= max_items:
            rows = rows[:max_items]
            break

    health["itemsDiscovered"] = len(rows)
    governance["lastAttemptAtUtc"] = now_utc.isoformat().replace("+00:00", "Z")
    if health["fetchOk"]:
        health["status"] = "OK" if rows else "OK_NO_RELEVANT_ITEMS"
        health["statusZh"] = "來源可連線，已完成公開內容掃描。"
    elif health["fetchFailed"]:
        health["status"] = health.get("lastErrorType") or "FETCH_FAILED"
        health["statusZh"] = "來源連線失敗，請檢查網路、防火牆、proxy 或 URL。"
    if health["fetchOk"]:
        health["status"] = "SUCCESS"
        health["statusZh"] = "來源連線與解析成功。"
        health["severity"] = "NORMAL"
        governance["lastSuccessfulAtUtc"] = governance["lastAttemptAtUtc"]
        governance["lastStatus"] = "SUCCESS"
    elif health.get("policyBlocked"):
        health["status"] = "HTTP_403_POLICY_BLOCKED"
        health["statusZh"] = "來源拒絕直接抓取；已停止並建立 domain-restricted Web Search 候選。"
        health["severity"] = "WARNING"
        governance["lastStatus"] = health["status"]
    elif health["fetchFailed"]:
        if health.get("lastErrorType") == "TIMEOUT_TRANSIENT":
            health["status"] = "TIMEOUT_TRANSIENT"
            health["statusZh"] = "來源暫時逾時；不阻塞其他來源或日報路由。"
            health["severity"] = "WARNING"
        else:
            health["status"] = "SOURCE_FAILED"
            health["statusZh"] = "來源連線或解析失敗。"
            health["severity"] = "FAILURE"
        governance["lastStatus"] = health["status"]
    return rows, health


def cluster_key(row: dict[str, Any]) -> str:
    title = str(row.get("EventTitle") or "").lower()
    title = re.sub(r"https?://\S+", " ", title)
    title = re.sub(r"[^\w\u4e00-\u9fff]+", " ", title)
    tokens = [token for token in title.split() if len(token) > 1]
    if not tokens:
        url = urllib.parse.urlparse(str(row.get("SourceUrl") or ""))
        return hashlib.sha256((url.netloc + url.path).encode("utf-8")).hexdigest()[:16]
    return " ".join(tokens[:12])


def corroborate_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(cluster_key(row), []).append(row)
    output: list[dict[str, Any]] = []
    for grouped in groups.values():
        grouped.sort(key=lambda row: (SOURCE_SCORE.get(str(row.get("SourceTier")).upper(), 0), len(str(row.get("SummaryZh") or ""))), reverse=True)
        primary = dict(grouped[0])
        source_names = sorted({str(row.get("SourceName") or "") for row in grouped if row.get("SourceName")})
        source_tiers = {str(row.get("SourceTier") or "").upper() for row in grouped}
        corroboration_count = len(source_names) or len(grouped)
        official = "OFFICIAL" in source_tiers or any(parse_bool(row.get("OfficialConfirmation")) for row in grouped)
        market = "PUBLIC_MARKET" in source_tiers or any(parse_bool(row.get("MarketConfirmation")) for row in grouped)
        urls = [str(row.get("SourceUrl") or "") for row in grouped if row.get("SourceUrl")]
        summaries = [str(row.get("SummaryZh") or "") for row in grouped if row.get("SummaryZh")]
        primary["CorroborationCount"] = str(corroboration_count)
        primary["OfficialConfirmation"] = official
        primary["MarketConfirmation"] = market
        primary["CorroboratingSources"] = "; ".join(source_names)
        if len(source_names) > 1:
            primary["SourceName"] = " + ".join(source_names[:4])
            primary["SourceUrl"] = urls[0] if urls else primary.get("SourceUrl", "")
            primary["SummaryZh"] = (primary.get("SummaryZh") or primary.get("EventTitle") or "") + " | corroborated by " + ", ".join(source_names[:4])
        elif summaries:
            primary["SummaryZh"] = summaries[0]
        output.append(primary)
    return output


def build_event_key(row: dict[str, Any], published_at: datetime) -> str:
    raw = "|".join(
        [
            published_at.strftime("%Y-%m-%d"),
            cluster_key(row),
            str(row.get("CorroboratingSources") or row.get("SourceName") or "").strip().lower(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()


def classify_event_v2(row: dict[str, Any], generated_at: datetime, lookback_hours: int) -> dict[str, Any] | None:
    has_published_at = bool(str(row.get("PublishedAt") or row.get("Date") or "").strip())
    published_at = parse_timestamp(row.get("PublishedAt") or row.get("Date"), generated_at)
    age_hours = max(0.0, (generated_at - published_at).total_seconds() / 3600)
    if has_published_at and age_hours > lookback_hours:
        return {
            "accepted": False,
            "reason": "OUTSIDE_LOOKBACK",
            "title": row.get("EventTitle", ""),
            "publishedAt": published_at.strftime("%Y-%m-%dT%H:%M:%S"),
            "ageHours": round(age_hours, 2),
        }
    title = str(row.get("EventTitle") or "").strip()
    if not title:
        return {"accepted": False, "reason": "MISSING_EVENT_TITLE", "title": ""}
    source_url = str(row.get("SourceUrl") or "").strip()
    discovery_mode = str(row.get("DiscoveryMode") or "").strip()
    if looks_like_listing_or_navigation(title, source_url, discovery_mode):
        return {
            "accepted": False,
            "reason": "NON_EVENT_LISTING_OR_NAVIGATION",
            "title": title,
            "sourceUrl": source_url,
        }
    source_tier = str(row.get("SourceTier") or "UNVERIFIED").strip().upper()
    if source_tier not in ALLOWED_SOURCE_TIERS:
        source_tier = "UNVERIFIED"

    relevance, relevance_tag = relevance_score(row)
    corroboration_count = max(1, parse_int(row.get("CorroborationCount"), 1))
    official_confirmation = parse_bool(row.get("OfficialConfirmation")) or source_tier == "OFFICIAL"
    market_confirmation = parse_bool(row.get("MarketConfirmation")) or source_tier == "PUBLIC_MARKET"
    article_evidence = has_published_at or has_date_or_article_path(source_url)
    if source_tier == "OFFICIAL" and discovery_mode.upper().startswith("HTML") and not article_evidence:
        return {
            "accepted": False,
            "reason": "OFFICIAL_HTML_NON_ARTICLE",
            "title": title,
            "sourceUrl": source_url,
        }
    score = SOURCE_SCORE.get(source_tier, 5) + relevance
    if corroboration_count >= 2:
        score += 20
    if official_confirmation:
        score += 22
    if market_confirmation:
        score += 10
    if has_published_at and age_hours > 72:
        score -= 20
    elif has_published_at and age_hours > 24:
        score -= 10
    elif has_published_at and age_hours > 6:
        score -= 5
    if not has_published_at:
        score -= 8
    score = max(0, min(100, score))

    if relevance <= 0:
        return {
            "accepted": False,
            "reason": "LOW_RELEVANCE",
            "title": title,
            "score": score,
            "sourceTier": source_tier,
            "relevanceTag": relevance_tag,
        }

    review_trigger = has_review_trigger(row, relevance_tag)
    raw_level = "OBSERVE"
    if official_confirmation and relevance >= 30 and article_evidence and review_trigger:
        raw_level = "REVIEW_REQUIRED"
    elif source_tier in {"MEDIA", "PUBLIC_MARKET"} and corroboration_count >= 2 and relevance >= 30 and review_trigger:
        raw_level = "REVIEW_REQUIRED"
    elif score >= 62 or relevance >= 18:
        raw_level = "WATCH"

    level = raw_level
    if source_tier == "UNVERIFIED" and level_rank(level) > level_rank("OBSERVE"):
        level = "OBSERVE"
    if source_tier == "MEDIA" and corroboration_count < 2 and not official_confirmation and level_rank(level) > level_rank("WATCH"):
        level = "WATCH"
    if not has_published_at and not official_confirmation and level == "REVIEW_REQUIRED":
        level = "WATCH"
    if official_confirmation and not article_evidence and level == "REVIEW_REQUIRED":
        level = "WATCH"

    if level == "REVIEW_REQUIRED":
        evidence_status = "REVIEW_REQUIRED_EVIDENCE"
    elif source_tier == "UNVERIFIED":
        evidence_status = "UNVERIFIED_OBSERVE"
    elif source_tier == "MEDIA" and corroboration_count < 2 and not official_confirmation:
        evidence_status = "SINGLE_MEDIA_WATCH"
    elif not has_published_at:
        evidence_status = "OBSERVATION_NO_PUBLISHED_AT"
    else:
        evidence_status = "OBSERVATION_EVIDENCE"

    event_key = build_event_key(row, published_at)
    source_names = str(row.get("CorroboratingSources") or row.get("SourceName") or "").strip()
    candidate_row = {
        "Date": published_at.strftime("%Y-%m-%d"),
        "EventType": str(row.get("EventType") or "NEWS").strip().upper(),
        "EventTitle": title,
        "Region": str(row.get("Region") or "GLOBAL").strip(),
        "SourceTier": source_tier,
        "SourceName": str(row.get("SourceName") or "UNKNOWN_SOURCE").strip(),
        "SourceUrl": str(row.get("SourceUrl") or "").strip(),
        "EvidenceStatus": evidence_status,
        "RiskTag": str(row.get("RiskTag") or relevance_tag).strip(),
        "BlackSwanLevel": level,
        "RelatedMetrics": str(row.get("RelatedMetrics") or relevance_tag).strip(),
        "SummaryZh": str(row.get("SummaryZh") or title).strip(),
        "DecisionImpactZh": str(row.get("DecisionImpactZh") or "Observation only; Owner review required before any formal conclusion changes.").strip(),
        "Actionable": "false",
    }
    return {
        "accepted": True,
        "eventKey": event_key,
        "publishedAt": published_at.strftime("%Y-%m-%dT%H:%M:%S"),
        "ageHours": round(age_hours, 2),
        "score": score,
        "sourceScore": SOURCE_SCORE.get(source_tier, 5),
        "relevanceScore": relevance,
        "relevanceTag": relevance_tag,
        "corroborationCount": corroboration_count,
        "corroboratingSources": source_names,
        "officialConfirmation": official_confirmation,
        "marketConfirmation": market_confirmation,
        "missingPublishedAt": not has_published_at,
        "rawLevel": raw_level,
        "level": level,
        "reviewDeadline": review_deadline(generated_at, level),
        "candidateRow": candidate_row,
    }


def load_manifest(package_root: Path, manifest_rel: str) -> tuple[dict[str, Any], list[str]]:
    manifest_path = package_root / manifest_rel
    warnings: list[str] = []
    if not manifest_path.exists():
        return {"sources": [], "status": "MISSING"}, [f"Source manifest missing: {manifest_rel}"]
    manifest = read_json(manifest_path)
    for source in manifest.get("sources", []) or []:
        tier = str(source.get("sourceTier", "")).upper()
        if tier not in ALLOWED_SOURCE_TIERS:
            warnings.append(f"Source {source.get('sourceId', 'UNKNOWN')} has invalid SourceTier={tier}.")
        if source.get("enabled") and source.get("requiresNetwork") and source.get("connectorStatus") != "APPROVED":
            warnings.append(f"Source {source.get('sourceId', 'UNKNOWN')} is enabled but not APPROVED; v2 will skip it.")
    return manifest, warnings


def load_input_events(args: argparse.Namespace, generated_at: datetime) -> list[dict[str, Any]]:
    return v1.load_input_events(args, generated_at)


def formal_event_keys(package_root: Path) -> set[str]:
    return v1.formal_event_keys(package_root)


def build_network_summary(source_health: list[dict[str, Any]]) -> dict[str, Any]:
    checked = [item for item in source_health if item.get("requiresNetwork") and item.get("enabled")]
    attempted = [
        item
        for item in checked
        if int(item.get("fetchOk") or 0) + int(item.get("fetchFailed") or 0) > 0
        or item.get("status") == "HTTP_403_POLICY_BLOCKED"
    ]
    ok = [
        item
        for item in attempted
        if str(item.get("status")) in {"SUCCESS", "SUCCESS_NO_RELEVANT_EVENT"}
    ]
    failed = [item for item in attempted if str(item.get("status")) == "SOURCE_FAILED"]
    warnings = [
        item
        for item in attempted
        if str(item.get("status")) in {"HTTP_403_POLICY_BLOCKED", "TIMEOUT_TRANSIENT"}
    ]
    transient_failures = [
        item for item in attempted if str(item.get("status")) == "TIMEOUT_TRANSIENT"
    ]
    skipped = [item for item in checked if str(item.get("status", "")).startswith("SKIPPED")]
    refused = [item for item in failed if item.get("lastErrorType") == "CONNECTION_REFUSED"]
    failure_count = len(failed) + len(transient_failures)
    rated_count = len(ok) + failure_count
    return {
        "checked": len(attempted),
        "configured": len(checked),
        "succeeded": len(ok),
        "failed": failure_count,
        "sourceFailed": len(failed),
        "warnings": len(warnings),
        "successNoRelevantEvent": len(
            [item for item in ok if item.get("status") == "SUCCESS_NO_RELEVANT_EVENT"]
        ),
        "skipped": len(skipped),
        "connectionRefused": len(refused),
        "networkLikelyBlocked": bool(failed) and len(refused) == len(failed),
        # Policy warnings (notably CTEE HTTP 403 cooldown) are observable but
        # are not crawler connection/parser failures and must not depress the
        # health rate.  Transient timeouts remain rated connection failures.
        "successRate": round((len(ok) / rated_count) * 100, 1) if rated_count else 0.0,
        "status": (
            "ONLINE_VERIFIED"
            if ok
            else (
                "SOURCE_FAILURES"
                if failure_count
                else ("WARNINGS_ONLY" if warnings else ("NO_NETWORK_RUN" if skipped else "NO_NETWORK_SOURCES"))
            )
        ),
    }


def build_dry_run_fragment(
    package_root: Path,
    staging_dir: Path,
    candidate_date: str,
    scan_summary: dict[str, Any],
    generated_files: list[str],
) -> dict[str, Any]:
    fragment = v1.build_dry_run_fragment(package_root, staging_dir, candidate_date, scan_summary, generated_files)
    fragment["toolVersion"] = TOOL_VERSION
    fragment["inputSources"]["news_scan"] = scan_summary.get("networkSummary", {}).get("status", "NEWS_SCAN_V2")
    fragment["sourceMeta"]["news_scan"]["statusZh"] = (
        "News scan v2 uses Owner-approved public RSS/HTML/search sources when allow-network is set; "
        "all outputs remain observation-only and Actionable=false."
    )
    return fragment


def merge_dry_run(package_root: Path, staging_dir: Path, fragment: dict[str, Any]) -> bool:
    return v1.merge_dry_run(package_root, staging_dir, fragment)


def write_scan_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# P1008 News Scan v2 Dry Run",
        "",
        f"- Generated: {summary['generatedAt']}",
        f"- Window: {summary['scanWindow']['label']} / lookback {summary['scanWindow']['lookbackHours']}h",
        f"- Network status: {summary.get('networkSummary', {}).get('status', 'N/A')}",
        f"- Candidate rows: {summary['candidateRowCount']}",
        f"- Highest level: {summary['highestLevel']}",
        f"- HOLD_UNDER_REVIEW: {str(summary['holdUnderReview']).lower()}",
        f"- Production CSV modified: {str(summary['productionCsvModified']).lower()}",
        f"- Actionable: {str(summary['actionable']).lower()}",
        "",
        "## Network Source Health",
    ]
    for item in summary.get("sourceHealth", []) or []:
        if not item.get("enabled") or not item.get("requiresNetwork"):
            continue
        lines.append(
            f"- {item.get('sourceId')} | {item.get('status')} | fetchOk={item.get('fetchOk')} "
            f"| failed={item.get('fetchFailed')} | items={item.get('itemsDiscovered')} | {item.get('lastErrorType', '')}"
        )
    lines.extend(["", "## Events"])
    if not summary["events"]:
        lines.append("- No qualified event. No formal CSV append is pending.")
    for event in summary["events"]:
        row = event["candidateRow"]
        lines.append(
            f"- {row['Date']} | {row['BlackSwanLevel']} | {row['SourceTier']} | "
            f"{row['EventTitle']} | score={event['score']} | corroboration={event['corroborationCount']} "
            f"| deadline={event['reviewDeadline']}"
        )
    if summary["ignoredEvents"]:
        lines.extend(["", "## Ignored Events"])
        for event in summary["ignoredEvents"][:80]:
            lines.append(f"- {event.get('reason', 'UNKNOWN')}: {event.get('title', '')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_event_review_state(summary: dict[str, Any]) -> dict[str, Any]:
    state = v1.build_event_review_state(summary)
    state["toolVersion"] = TOOL_VERSION
    state["sourceHealthSummary"] = summary.get("networkSummary", {})
    return state


def scan_manifest_sources(
    package_root: Path,
    manifest: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    state_path = package_root / CRAWLER_GOVERNANCE_STATE
    args._crawler_state = read_json(state_path) if state_path.is_file() else {"sources": {}}
    args._crawler_now_utc = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    source_health: list[dict[str, Any]] = []
    for source in manifest.get("sources", []) or []:
        source_rows, health = scan_source(source, manifest, args)
        rows.extend(source_rows)
        source_health.append(health)
    args._crawler_state["updatedAtUtc"] = args._crawler_now_utc.isoformat().replace("+00:00", "Z")
    write_json(state_path, args._crawler_state)
    return rows, source_health


def main() -> int:
    parser = argparse.ArgumentParser(description="Run P1008 observation-only multi-source news scan v2.")
    parser.add_argument("--package-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--date", help="Candidate date YYYY-MM-DD. Defaults to today.")
    parser.add_argument("--scan-window", choices=["auto", *SCAN_WINDOWS.keys()], default="auto")
    parser.add_argument("--lookback-hours", type=int)
    parser.add_argument("--dry-run", action="store_true", help="Accepted for BAT/scheduler clarity; formal CSV is never modified.")
    parser.add_argument("--no-network", action="store_true", help="Do not use network connectors.")
    parser.add_argument("--allow-network", action="store_true", help="Use enabled APPROVED network sources from manifest.")
    parser.add_argument("--browser-fallback", dest="browser_fallback", action="store_true", default=True)
    parser.add_argument("--no-browser-fallback", dest="browser_fallback", action="store_false")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--source-manifest", default=SOURCE_MANIFEST)
    parser.add_argument("--input-events-csv", type=Path)
    parser.add_argument("--published-at")
    parser.add_argument("--event-title")
    parser.add_argument("--event-type", default="NEWS")
    parser.add_argument("--event-region", default="GLOBAL")
    parser.add_argument("--source-tier", default="OWNER_NOTE")
    parser.add_argument("--source-name", default="Owner note")
    parser.add_argument("--source-url", default="")
    parser.add_argument("--summary-zh", default="")
    parser.add_argument("--decision-impact-zh", default="")
    parser.add_argument("--risk-tag", default="")
    parser.add_argument("--related-metrics", default="")
    parser.add_argument("--evidence-status", default="")
    parser.add_argument("--keywords", default="")
    parser.add_argument("--corroboration-count", default="1")
    parser.add_argument("--market-confirmation", action="store_true")
    parser.add_argument("--official-confirmation", action="store_true")
    args = parser.parse_args()

    args.no_network = args.no_network or not args.allow_network
    package_root = args.package_root.resolve()
    generated_at = datetime.now()
    candidate_date = args.date or generated_at.strftime("%Y-%m-%d")
    window_key = choose_scan_window(args.scan_window)
    window = dict(SCAN_WINDOWS[window_key])
    if args.lookback_hours:
        window["lookbackHours"] = args.lookback_hours

    staging_dir = package_root / "staging" / candidate_date
    staging_dir.mkdir(parents=True, exist_ok=True)
    runtime_path = package_root / "runtime" / "warroom_news_scan_snapshot.json"
    event_review_state_path = package_root / EVENT_REVIEW_STATE
    candidate_path = staging_dir / MACRO_EVENT_CANDIDATE

    manifest, manifest_warnings = load_manifest(package_root, args.source_manifest)
    input_events = load_input_events(args, generated_at)
    discovered_events, source_health = scan_manifest_sources(package_root, manifest, args)
    all_raw_events = input_events + discovered_events
    corroborated_events = corroborate_events(all_raw_events)

    accepted_events: list[dict[str, Any]] = []
    ignored_events: list[dict[str, Any]] = []
    seen_event_keys: set[str] = set()
    existing_formal_keys = formal_event_keys(package_root)

    for raw_event in corroborated_events:
        classified = classify_event_v2(raw_event, generated_at, int(window["lookbackHours"]))
        if not classified or not classified.get("accepted"):
            ignored_events.append(classified or {"reason": "CLASSIFICATION_FAILED"})
            continue
        row = classified["candidateRow"]
        formal_key = "|".join([row["Date"], row["EventTitle"], row["SourceUrl"]])
        if classified["eventKey"] in seen_event_keys:
            ignored_events.append({**classified, "accepted": False, "reason": "DUPLICATE_IN_SCAN"})
            continue
        if formal_key in existing_formal_keys:
            ignored_events.append({**classified, "accepted": False, "reason": "DUPLICATE_IN_FORMAL_CSV"})
            continue
        seen_event_keys.add(classified["eventKey"])
        accepted_events.append(classified)

    accepted_events.sort(key=lambda item: (level_rank(item["level"]), item["score"], item["publishedAt"]), reverse=True)
    candidate_rows = [event["candidateRow"] for event in accepted_events]
    if candidate_rows:
        write_csv_rows(candidate_path, MACRO_EVENT_COLUMNS, candidate_rows)
    elif not candidate_path.exists():
        write_csv_rows(candidate_path, MACRO_EVENT_COLUMNS, [])

    generated_files = []
    if candidate_rows:
        generated_files.append(str(candidate_path.relative_to(package_root)))

    highest_level = accepted_events[0]["level"] if accepted_events else "NONE"
    hold_under_review = any(event["level"] == "REVIEW_REQUIRED" for event in accepted_events)
    source_counts: dict[str, int] = {}
    for event in accepted_events:
        tier = event["candidateRow"]["SourceTier"]
        source_counts[tier] = source_counts.get(tier, 0) + 1
    for health in source_health:
        health["itemsAccepted"] = sum(
            1 for event in accepted_events
            if str(health.get("sourceName") or "") in str(event.get("corroboratingSources") or event.get("candidateRow", {}).get("SourceName") or "")
        )
        if health.get("status") == "SUCCESS" and health["itemsAccepted"] == 0:
            health["status"] = "SUCCESS_NO_RELEVANT_EVENT"
            health["statusZh"] = "來源連線與解析成功，但本次沒有相關重大事件。"

    network_summary = build_network_summary(source_health)
    warnings = list(manifest_warnings)
    if network_summary.get("networkLikelyBlocked"):
        warnings.append("All attempted approved network sources were connection-refused; check firewall/proxy or run through an approved browser/proxy path.")
    if args.no_network:
        warnings.append("News scan ran with no-network; approved public sources were not fetched.")

    summary = {
        "task": "P1008_NEWS_SCAN",
        "toolVersion": TOOL_VERSION,
        "generatedAt": generated_at.strftime("%Y-%m-%dT%H:%M:%S"),
        "candidateDate": candidate_date,
        "runtimeOnly": True,
        "runtimeOnlyZh": "Observation-only news scan v2; formal CSV is unchanged.",
        "productionCsvModified": False,
        "productionCsvModifiedZh": "Formal CSV files were not modified.",
        "ownerConfirmationRequired": bool(candidate_rows),
        "ownerConfirmationRequiredZh": "Owner publish gate is required before appending macro_event_observations.csv.",
        "actionable": False,
        "actionableZh": "News scan cannot issue trading instructions or change HOLD.",
        "noNetwork": bool(args.no_network),
        "browserFallbackEnabled": bool(args.browser_fallback),
        "sourceManifestPath": args.source_manifest,
        "sourceManifestStatus": manifest.get("status", "ACTIVE"),
        "scanWindow": window,
        "candidatePath": str(candidate_path.relative_to(package_root)),
        "candidateRowCount": len(candidate_rows),
        "rawEventCount": len(all_raw_events),
        "discoveredEventCount": len(discovered_events),
        "ignoredEventCount": len(ignored_events),
        "generatedFiles": generated_files,
        "highestLevel": highest_level,
        "holdUnderReview": hold_under_review,
        "ownerReviewRequired": hold_under_review or any(event["level"] == "WATCH" for event in accepted_events),
        "reviewDeadline": accepted_events[0]["reviewDeadline"] if accepted_events else "",
        "sourceCounts": source_counts,
        "sourceHealth": source_health,
        "networkSummary": network_summary,
        "dependencyStatus": dependency_status(),
        "macroEventRow": accepted_events[0]["candidateRow"] if accepted_events else None,
        "events": accepted_events,
        "ignoredEvents": ignored_events,
        "warnings": warnings,
        "noPublishRequired": not bool(candidate_rows),
        "eventReviewStatePath": EVENT_REVIEW_STATE,
    }

    event_review_state = build_event_review_state(summary)
    write_json(staging_dir / "NEWS_SCAN.json", summary)
    write_scan_markdown(staging_dir / "NEWS_SCAN.md", summary)
    write_json(runtime_path, summary)
    write_json(event_review_state_path, event_review_state)

    dry_run_fragment = build_dry_run_fragment(package_root, staging_dir, candidate_date, summary, generated_files)
    dry_run_merged = merge_dry_run(package_root, staging_dir, dry_run_fragment)

    log(
        "News scan v2 completed: "
        f"{len(candidate_rows)} candidate row(s), highestLevel={highest_level}, "
        f"network={network_summary.get('status')}."
    )
    log(f"Runtime snapshot: {runtime_path}")
    log(f"Event review state: {event_review_state_path}")
    log(f"Scan summary: {staging_dir / 'NEWS_SCAN.json'}")
    if dry_run_merged:
        log(f"DRY_RUN merged: {staging_dir / 'DRY_RUN.json'}")
    else:
        log("DRY_RUN left unchanged because no event candidate is pending.")
    log("Formal CSV modified: NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
