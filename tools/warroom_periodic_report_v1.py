#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""產生 P1008 本機定期戰報。

This tool reads formal CSV files plus observation-only sidecars and runtime
snapshots. It writes report artifacts and manifests only. It never modifies
formal CSV files and never changes HOLD or rule status.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


TOOL_VERSION = "P1008_PERIODIC_REPORT_GENERATOR_v1"
REPORT_MANIFEST = "reports/P1008_REPORT_MANIFEST.json"
RUNTIME_REPORT_MANIFEST = "runtime/warroom_report_manifest.json"
EVENT_REVIEW_STATE = "runtime/warroom_event_review_state.json"
PLUGIN_SHADOW_CANDIDATE = "runtime/research_plugin/latest_report_candidate.json"

DAILY_COLUMNS = ["Date", "Close", "QuarterKey", "BVPS_ref", "PB_daily", "DataSupportLevel", "Status"]
MACRO_COLUMNS = [
    "Date",
    "TWD_USD",
    "VIX",
    "WTI_Oil",
    "US_10Y_Yield",
    "Fed_Rate",
    "Fed_Hike_Prob_YE",
    "DXY",
    "US_GDP_QoQ",
    "US_CPI_YoY",
    "TW_GDP_QoQ",
    "TAIEX_Weekly_Chg",
    "CSP_Capex_Signal",
    "Hon_Hai_Rev_YoY",
    "Foreign_Net_Buy",
    "TW_Export_YoY",
    "RiskLevel",
    "RiskNote",
]
MACRO_EVENT_COLUMNS = [
    "Date",
    "EventType",
    "EventTitle",
    "Region",
    "SourceTier",
    "SourceName",
    "SourceUrl",
    "EvidenceStatus",
    "RiskTag",
    "BlackSwanLevel",
    "RelatedMetrics",
    "SummaryZh",
    "DecisionImpactZh",
    "Actionable",
]
FX_TREND_COLUMNS = [
    "Date",
    "TWD_USD",
    "DXY",
    "JPY_USD",
    "US_10Y_Yield",
    "Fed_Rate",
    "BOJ_Rate",
    "RateSpread_US_JP",
    "FxTrend",
    "FxPressureLevel",
    "EPSImpactEstimateZh",
    "SourceTier",
    "SourceUrl",
    "SummaryZh",
    "Actionable",
]


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [INFO] {message}")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


class ShadowCandidateError(RuntimeError):
    """Raised when an existing plugin candidate cannot pass the report boundary."""


def read_shadow_candidate(
    package_root: Path, report_date: str | None = None
) -> dict[str, Any] | None:
    """Read, but never repair, the latest non-actionable manual Shadow candidate."""

    path = package_root.resolve() / PLUGIN_SHADOW_CANDIDATE
    if not path.is_file():
        return None
    try:
        candidate = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ShadowCandidateError("Plugin Shadow candidate is unreadable") from exc
    if not isinstance(candidate, dict):
        raise ShadowCandidateError("Plugin Shadow candidate must be an object")
    if candidate.get("actionable") is not False or candidate.get("manual_shadow") is not True:
        raise ShadowCandidateError("Plugin Shadow candidate crossed its observation boundary")
    if candidate.get("status") not in {
        "NO_MATERIAL_CHANGE",
        "MATERIAL_CHANGE_CANDIDATE",
    }:
        raise ShadowCandidateError("Plugin Shadow candidate status is invalid")
    if report_date and candidate.get("as_of_date") != report_date:
        return None
    if not re.fullmatch(r"[A-F0-9]{64}", str(candidate.get("baseline_hash", ""))):
        raise ShadowCandidateError("Plugin Shadow baseline hash is invalid")
    required_lists = ("plugin_trace", "new_evidence", "evidence_ids", "source_locators")
    if any(not isinstance(candidate.get(field), list) for field in required_lists):
        raise ShadowCandidateError("Plugin Shadow candidate list schema is invalid")
    changed_fields = candidate.get("changed_fields")
    change_evidence = candidate.get("change_evidence")
    if not isinstance(changed_fields, list) or not isinstance(change_evidence, dict):
        raise ShadowCandidateError("Plugin Shadow evidence binding is invalid")
    if set(changed_fields) != set(change_evidence):
        raise ShadowCandidateError("Plugin Shadow changed fields are not evidence-bound")
    narrative = " ".join(
        str(candidate.get(field, "")) for field in ("investment_impact", "catalysts", "risks")
    )
    if re.search(r"\b(?:BUY|SELL|ADD|TRIM)\b", narrative, re.IGNORECASE):
        raise ShadowCandidateError("Plugin Shadow candidate contains a trading instruction")
    return candidate


def append_shadow_candidate(
    markdown: str, candidate: dict[str, Any] | None
) -> str:
    """Append the candidate as three clearly separated, observation-only sections."""

    if candidate is None:
        return markdown
    baseline = json.dumps(
        candidate.get("war_room_baseline", {}), ensure_ascii=False, sort_keys=True, indent=2
    )
    evidence_rows = []
    for item in candidate.get("new_evidence", []):
        locators = ", ".join(
            str(source.get("locator", "")) for source in item.get("source_locators", [])
        )
        evidence_rows.append(
            [
                item.get("evidence_id", ""),
                item.get("summary", ""),
                ", ".join(item.get("changed_fields", [])),
                locators,
            ]
        )
    if not evidence_rows:
        evidence_rows = [["-", "NO_MATERIAL_CHANGE", "-", "-"]]
    impact_rows = []
    for field, label in (
        ("revenue", "Revenue"),
        ("EPS", "EPS"),
        ("margins", "Margins"),
        ("valuation", "Valuation"),
        ("fx_impact", "FX impact"),
    ):
        metric = candidate.get(field, {}) or {}
        impact_rows.append(
            [label, metric.get("investment_impact", ""), ", ".join(metric.get("evidence_ids", []))]
        )
    section = "\n".join(
        [
            "",
            "## Plugin Module Shadow（Owner gate 前）",
            "",
            f"- Status: `{candidate.get('status', '')}`",
            f"- Run: `{candidate.get('run_id', '')}` / `{candidate.get('run_type', '')}`",
            "- Actionable: `false`",
            "",
            "### 戰情室基線",
            "",
            "```json",
            baseline,
            "```",
            "",
            "### 本次新增證據",
            "",
            markdown_table(["evidence_id", "summary", "changed_fields", "source"], evidence_rows),
            "",
            "### 對投資判讀的影響",
            "",
            f"- Direction: `{candidate.get('sentiment', '')}`; confidence: `{candidate.get('confidence', '')}`",
            f"- Summary: {candidate.get('investment_impact', '')}",
            "",
            markdown_table(["field", "impact", "evidence_ids"], impact_rows),
            "",
        ]
    )
    return markdown.rstrip() + "\n" + section


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def read_csv_rows(path: Path, expected_columns: list[str] | None = None) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], [f"MISSING_FILE: {path}"]
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    content_lines = [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not content_lines:
        return [], [f"NO_CSV_HEADER: {path}"]
    reader = csv.DictReader(content_lines)
    rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    issues: list[str] = []
    if expected_columns and list(reader.fieldnames or []) != expected_columns:
        issues.append(f"SCHEMA_MISMATCH: {path.name}")
    return rows, issues


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def finite_float(row: dict[str, str] | None, field: str) -> float | None:
    if not row:
        return None
    value = row.get(field)
    if value in (None, "", "N/A"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def sort_by_date(rows: list[dict[str, str]], reverse: bool = True) -> list[dict[str, str]]:
    return sorted(rows, key=lambda row: row.get("Date", ""), reverse=reverse)


def latest(rows: list[dict[str, str]], key: str = "Date") -> dict[str, str] | None:
    if not rows:
        return None
    return sorted(rows, key=lambda row: row.get(key, ""))[-1]


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "| " + " | ".join(headers) + " |\n| " + " | ".join(["---"] * len(headers)) + " |\n"
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        escaped = [str(value).replace("\n", " ").replace("|", "/") for value in row]
        lines.append("| " + " | ".join(escaped) + " |")
    return "\n".join(lines) + "\n"


def build_event_review_state(package_root: Path, news_scan: dict[str, Any] | None, generated_at: str) -> dict[str, Any]:
    events = (news_scan or {}).get("events", []) or []
    pending = []
    for event in events:
        level = str(event.get("level", "")).upper()
        if level not in {"WATCH", "REVIEW_REQUIRED"}:
            continue
        row = event.get("candidateRow", {}) or {}
        pending.append(
            {
                "eventKey": event.get("eventKey") or "",
                "eventDate": row.get("Date") or event.get("publishedAt") or "",
                "eventTitle": row.get("EventTitle") or "",
                "level": level,
                "sourceTier": row.get("SourceTier") or "",
                "reviewStatus": "PENDING_OWNER_ACK",
                "reviewDeadline": event.get("reviewDeadline") or (news_scan or {}).get("reviewDeadline") or "",
                "reviewConclusionZh": "待 Owner 確認；事件只作重審提示，不改 HOLD。",
                "actionable": False,
            }
        )
    state = {
        "task": "P1008_EVENT_REVIEW_STATE",
        "toolVersion": TOOL_VERSION,
        "generatedAt": generated_at,
        "sourceSnapshot": "runtime/warroom_news_scan_snapshot.json",
        "productionCsvModified": False,
        "actionable": False,
        "status": "REVIEW_REQUIRED" if any(item["level"] == "REVIEW_REQUIRED" for item in pending) else ("WATCH_PENDING" if pending else "NO_PENDING_REVIEW"),
        "ownerAckRequired": bool(pending),
        "pendingReviews": pending,
        "lastScan": {
            "generatedAt": (news_scan or {}).get("generatedAt", ""),
            "highestLevel": (news_scan or {}).get("highestLevel", "NONE"),
            "holdUnderReview": bool((news_scan or {}).get("holdUnderReview", False)),
            "candidateRowCount": int((news_scan or {}).get("candidateRowCount", 0) or 0),
        },
    }
    write_json(package_root / EVENT_REVIEW_STATE, state)
    return state


def build_event_review_state(package_root: Path, news_scan: dict[str, Any] | None, generated_at: str) -> dict[str, Any]:
    """Write review state without reopening already-published event reviews."""
    snapshot = news_scan or {}
    formal_synced = bool(snapshot.get("formalSynced", False))
    review_flag = bool(snapshot.get("ownerReviewRequired", False) or snapshot.get("holdUnderReview", False))
    events = snapshot.get("events", []) or []

    pending = []
    if not formal_synced and review_flag:
        for event in events:
            level = str(event.get("level", "")).upper()
            if level not in {"WATCH", "REVIEW_REQUIRED"}:
                continue
            row = event.get("candidateRow", {}) or {}
            pending.append(
                {
                    "eventKey": event.get("eventKey") or "",
                    "eventDate": row.get("Date") or event.get("publishedAt") or "",
                    "eventTitle": row.get("EventTitle") or event.get("title") or "",
                    "level": level,
                    "sourceTier": row.get("SourceTier") or event.get("sourceTier") or "",
                    "reviewStatus": "PENDING_OWNER_ACK",
                    "reviewDeadline": event.get("reviewDeadline") or snapshot.get("reviewDeadline") or "",
                    "reviewConclusionZh": "待 Owner 確認；事件只作重審提示，不改主結論。",
                    "actionable": False,
                }
            )

    if formal_synced:
        status = "OWNER_PUBLISHED"
    elif any(item["level"] == "REVIEW_REQUIRED" for item in pending):
        status = "REVIEW_REQUIRED"
    elif pending:
        status = "WATCH_PENDING"
    else:
        status = "NO_PENDING_REVIEW"

    state = {
        "task": "P1008_EVENT_REVIEW_STATE",
        "toolVersion": TOOL_VERSION,
        "generatedAt": generated_at,
        "sourceSnapshot": "runtime/warroom_news_scan_snapshot.json",
        "productionCsvModified": False,
        "actionable": False,
        "status": status,
        "ownerAckRequired": bool(pending),
        "pendingReviews": pending,
        "lastScan": {
            "generatedAt": snapshot.get("generatedAt", ""),
            "highestLevel": snapshot.get("highestLevel", "NONE"),
            "holdUnderReview": bool(snapshot.get("holdUnderReview", False)) and not formal_synced,
            "formalSynced": formal_synced,
            "candidateRowCount": int(snapshot.get("candidateRowCount", 0) or 0),
        },
    }
    write_json(package_root / EVENT_REVIEW_STATE, state)
    return state


def rows_since(rows: list[dict[str, str]], anchor: datetime, hours: int) -> list[dict[str, str]]:
    cutoff = anchor - timedelta(hours=hours)
    selected = []
    for row in rows:
        row_dt = parse_date(row.get("Date"))
        if row_dt and row_dt >= cutoff:
            selected.append(row)
    return selected


def build_report_markdown(
    period: str,
    report_date: str,
    generated_at: str,
    data: dict[str, Any],
) -> str:
    latest_daily = data["latestDaily"]
    latest_macro = data["latestMacro"]
    latest_master = data["latestMaster"]
    news_scan = data["newsScan"]
    review_state = data["reviewState"]
    owner_log_tail = data["ownerLogTail"]
    price = finite_float(latest_daily, "Close")
    pb = finite_float(latest_daily, "PB_daily")
    risk_level = (latest_macro or {}).get("RiskLevel", "N/A")
    highest_news = (news_scan or {}).get("highestLevel", "NONE")
    hold_under_review = bool((news_scan or {}).get("holdUnderReview", False))
    status = "REVIEW_REQUIRED" if hold_under_review or review_state.get("ownerAckRequired") else "LOGIC_REVIEW_ONLY"
    if not latest_daily or not latest_macro or not latest_master:
        status = "DATA_BLOCKED"

    recent_daily = sort_by_date(data["dailyRows"], reverse=False)[-10:]
    price_rows = [
        [
            row.get("Date", ""),
            row.get("Close", ""),
            row.get("PB_daily", ""),
            row.get("Status", ""),
        ]
        for row in recent_daily
    ]
    fx_rows = [
        [
            row.get("Date", ""),
            row.get("TWD_USD", ""),
            row.get("DXY", ""),
            row.get("JPY_USD", ""),
            row.get("FxTrend", ""),
            row.get("FxPressureLevel", ""),
            row.get("Actionable", ""),
        ]
        for row in sort_by_date(data["fxRows"], reverse=True)[:7]
    ]

    event_rows = []
    for row in sort_by_date(data["eventRows"], reverse=True)[:10]:
        event_rows.append(
            [
                row.get("Date", ""),
                row.get("EventType", ""),
                row.get("EventTitle", ""),
                row.get("SourceTier", ""),
                row.get("BlackSwanLevel", ""),
                row.get("Actionable", ""),
            ]
        )
    for event in (news_scan or {}).get("events", [])[:10]:
        row = event.get("candidateRow", {}) or {}
        event_rows.append(
            [
                row.get("Date", ""),
                row.get("EventType", "NEWS_SCAN"),
                row.get("EventTitle", ""),
                row.get("SourceTier", ""),
                row.get("BlackSwanLevel", event.get("level", "")),
                row.get("Actionable", "false"),
            ]
        )

    anchor = parse_date(report_date) or datetime.now()
    seventy_two_hour_events = rows_since(data["eventRows"], anchor, 72)
    seven_day_events = rows_since(data["eventRows"], anchor, 24 * 7)
    pending_reviews = review_state.get("pendingReviews", []) or []

    pending_rows = [
        [
            item.get("eventDate", ""),
            item.get("eventTitle", ""),
            item.get("level", ""),
            item.get("reviewStatus", ""),
            item.get("reviewDeadline", ""),
            str(item.get("actionable", False)).lower(),
        ]
        for item in pending_reviews
    ]

    period_zh = {"daily": "日報", "weekly": "週報", "monthly": "月報"}.get(period, period)
    lines = [
        f"# P1008 {period_zh} {report_date}",
        "",
        f"- 產生器：`{TOOL_VERSION}`",
        f"- 產生時間：`{generated_at}`",
        "- 正式 CSV 是否被修改：`false`",
        "- Actionable：`false`",
        "",
        "## 三層結論",
        "",
        f"- 戰報狀態：`{status}`",
        f"- 主結論 IC：維持原戰情室判讀；本戰報只做資料稽核與重審提示。",
        f"- Owner 動作：{'需於 deadline 前完成事件 review' if pending_reviews else '無待決事件；例行檢查資料與來源即可'}。",
        "",
        "## 最新資料摘要",
        "",
        markdown_table(
            ["資料集", "最新日期", "關鍵欄位", "治理邊界"],
            [
                ["每日股價", (latest_daily or {}).get("Date", "N/A"), f"Close={price if price is not None else 'N/A'}, PB={pb if pb is not None else 'N/A'}", "正式 CSV"],
                ["總經快照", (latest_macro or {}).get("Date", "N/A"), f"RiskLevel={risk_level}", "正式 CSV，維持 18 欄"],
                ["Master KPI", (latest_master or {}).get("Quarter", "N/A"), f"EPS_TTM={(latest_master or {}).get('EPS_TTM', 'N/A')}, ROE={(latest_master or {}).get('ROE_TTM_Pct', 'N/A')}", "正式 CSV"],
                ["新聞掃描", (news_scan or {}).get("generatedAt", "N/A"), f"highestLevel={highest_news}, HOLD_UNDER_REVIEW={str(hold_under_review).lower()}", "runtime 觀察"],
                ["事件 review", review_state.get("generatedAt", "N/A"), f"status={review_state.get('status', 'N/A')}", "runtime 治理狀態"],
            ],
        ),
        "",
        "## PB / Price 圖表資料",
        "",
        markdown_table(["Date", "Close", "PB_daily", "Status"], price_rows),
        "",
        "## FX 趨勢觀察",
        "",
        markdown_table(["日期", "TWD/USD", "DXY", "JPY/USD", "FX 趨勢", "壓力等級", "Actionable"], fx_rows),
        "",
        "## 事件反證表",
        "",
        markdown_table(["日期", "類型", "標題", "來源層級", "等級", "Actionable"], event_rows),
        "",
        "## 72h / 7d 保護檢查",
        "",
        markdown_table(
            ["Check", "Result", "Required handling"],
            [
                ["72h WATCH/REVIEW_REQUIRED", f"{len(seventy_two_hour_events)} 筆正式旁路列", "若含 REVIEW_REQUIRED，首頁應維持 HOLD_UNDER_REVIEW 至 Owner ack"],
                ["7d 事件 review", f"{len(seven_day_events)} 筆正式旁路列", "週/月報需列入反證表並檢查 stale / ack / unresolved"],
                ["runtime 新聞掃描", f"{(news_scan or {}).get('candidateRowCount', 0)} 筆候選列", "只作觀察與 Owner gate，不改正式 KPI"],
            ],
        ),
        "",
        "## Owner 待決",
        "",
        markdown_table(["事件日期", "標題", "等級", "Review 狀態", "期限", "Actionable"], pending_rows),
        "",
        "## HOLD_UNDER_REVIEW 必答",
        "",
        markdown_table(
            ["問題", "回答"],
            [
                ["事件是否解除？", "已解除 / 無待決" if not pending_reviews else "未解除，等待 Owner ack。"],
                ["是否反映在 KPI / FX / 市場資料？", "正式 CSV 不自動改寫；FX/event sidecar 只作觀察與反證。"],
                ["原 HOLD 邏輯是否仍有效？", "未發現可自動改變 HOLD 的正式資料；若 REVIEW_REQUIRED 存在，需 Owner 人工重審。"],
            ],
        ),
        "",
        "## Owner Publish Review 摘要",
        "",
        "```text",
        owner_log_tail or "無可用的 Owner publish review log。",
        "```",
        "",
        "## 安全邊界",
        "",
        "- 不覆寫正式 CSV。",
        "- 不擴欄 `macro_snapshot.csv`。",
        "- 不啟用 `KEEP_DISABLED` 規則。",
        "- 新聞與 FX 不直接改 HOLD、不輸出買賣指令。",
    ]
    return "\n".join(lines) + "\n"


def compact_text(value: Any, limit: int = 96) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def normalized_event_candidates(data: dict[str, Any]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for row in data.get("eventRows", []) or []:
        candidates.append(
            {
                "Date": row.get("Date", ""),
                "EventType": row.get("EventType", ""),
                "EventTitle": row.get("EventTitle", ""),
                "SourceTier": row.get("SourceTier", ""),
                "SourceName": row.get("SourceName", ""),
                "SourceUrl": row.get("SourceUrl", ""),
                "RiskTag": row.get("RiskTag", ""),
                "BlackSwanLevel": row.get("BlackSwanLevel", ""),
                "DecisionImpactZh": row.get("DecisionImpactZh", ""),
                "Actionable": row.get("Actionable", "false"),
            }
        )
    for event in ((data.get("newsScan") or {}).get("events", []) or []):
        row = event.get("candidateRow", {}) or {}
        candidates.append(
            {
                "Date": row.get("Date") or event.get("publishedAt") or "",
                "EventType": row.get("EventType", "NEWS_SCAN"),
                "EventTitle": row.get("EventTitle") or event.get("title") or "",
                "SourceTier": row.get("SourceTier") or event.get("sourceTier") or "",
                "SourceName": row.get("SourceName") or event.get("sourceName") or "",
                "SourceUrl": row.get("SourceUrl") or event.get("url") or "",
                "RiskTag": row.get("RiskTag") or event.get("riskTag") or "",
                "BlackSwanLevel": row.get("BlackSwanLevel") or event.get("level") or "",
                "DecisionImpactZh": row.get("DecisionImpactZh") or event.get("summaryZh") or "",
                "Actionable": row.get("Actionable", "false"),
            }
        )
    deduped: dict[str, dict[str, str]] = {}
    for row in candidates:
        title = row.get("EventTitle", "").strip().lower()
        url = row.get("SourceUrl", "").strip().lower()
        key = url or f"{row.get('Date', '')}|{title}"
        if not title and not url:
            continue
        deduped[key] = row
    priority = {"REVIEW_REQUIRED": 0, "WATCH": 1, "OBSERVE": 2}
    return sorted(
        deduped.values(),
        key=lambda row: (
            priority.get(row.get("BlackSwanLevel", "").upper(), 9),
            row.get("Date", ""),
            row.get("SourceTier", ""),
        ),
        reverse=False,
    )


def event_level_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    counts = {"REVIEW_REQUIRED": 0, "WATCH": 0, "OBSERVE": 0, "OTHER": 0}
    for row in rows:
        level = row.get("BlackSwanLevel", "").upper()
        if level in counts:
            counts[level] += 1
        else:
            counts["OTHER"] += 1
    return counts


def event_quality_score(row: dict[str, str]) -> int:
    text = " ".join(
        [
            row.get("EventTitle", ""),
            row.get("RiskTag", ""),
            row.get("RelatedMetrics", ""),
            row.get("DecisionImpactZh", ""),
            row.get("SourceName", ""),
        ]
    ).lower()
    title = row.get("EventTitle", "").strip().lower()
    score = 0
    if row.get("SourceTier", "").upper() == "OFFICIAL":
        score += 2
    if row.get("BlackSwanLevel", "").upper() == "REVIEW_REQUIRED":
        score += 2
    elif row.get("BlackSwanLevel", "").upper() == "WATCH":
        score += 1
    csp_terms = [
        "microsoft",
        "azure",
        "aws",
        "amazon",
        "google",
        "alphabet",
        "meta",
        "oracle",
        "openai",
        "xai",
        "coreweave",
        "anthropic",
    ]
    capex_terms = [
        "capex",
        "capital expenditure",
        "data center",
        "datacenter",
        "infrastructure",
        "server",
        "gpu",
        "blackwell",
        "gb200",
        "gb300",
        "capital partners",
        "compute at scale",
        "build in america",
        "partners build",
        "export control",
        "ai server",
        "ai伺服器",
        "出口管制",
        "供應鏈",
        "supply chain",
    ]
    ai_terms = ["blackwell", "gb200", "gb300", "ai server", "ai伺服器"]
    nvidia_specific_terms = [
        "blackwell",
        "gb200",
        "gb300",
        "capital partners",
        "compute at scale",
        "build in america",
        "partners build",
        "data center",
        "datacenter",
        "server",
        "gpu",
        "supply chain",
        "供應鏈",
    ]
    company_terms = ["鴻海", "hon hai", "foxconn", "2317", "富士康"]
    macro_terms = ["dxy", "us10y", "fed", "cpi", "wti", "美元", "台幣", "匯率", "關稅", "出口管制"]
    csp_hit = any(term in text for term in csp_terms)
    capex_hit = any(term in text for term in capex_terms)
    if csp_hit and capex_hit:
        score += 10
    elif csp_hit:
        score += 2
    if any(term in text for term in ai_terms):
        score += 8
    if "nvidia" in text and any(term in text for term in nvidia_specific_terms):
        score += 8
    elif "nvidia" in text:
        score += 2
    if any(term in text for term in company_terms):
        score += 5
    if any(term in text for term in macro_terms):
        score += 3
    generic_titles = ["最新消息", "全文搜尋", "press releases", "newsroom", "電動車ev", "supply chain"]
    if title in generic_titles or any(title.startswith(term) for term in ["最新消息 -", "全文搜尋", "ai & machine learning", "build agents"]):
        score -= 18
    if len(title) < 8:
        score -= 4
    return score


def event_decision_focus(row: dict[str, str]) -> str:
    text = " ".join([row.get("EventTitle", ""), row.get("RiskTag", ""), row.get("DecisionImpactZh", "")]).lower()
    csp_hit = any(term in text for term in ["microsoft", "azure", "aws", "amazon", "google", "alphabet", "meta", "oracle", "openai", "xai", "coreweave", "anthropic"])
    capex_hit = any(term in text for term in ["capex", "capital expenditure", "data center", "datacenter", "infrastructure", "server", "gpu", "blackwell", "gb200", "gb300", "export control", "ai server", "ai伺服器", "出口管制", "供應鏈", "supply chain"])
    if csp_hit and capex_hit:
        return "CSP / AI capex demand signal；檢查是否影響 AI server 營收假設。"
    nvidia_specific = "nvidia" in text and any(term in text for term in ["blackwell", "gb200", "gb300", "capital partners", "compute at scale", "build in america", "partners build", "data center", "datacenter", "server", "gpu", "supply chain", "供應鏈"])
    if nvidia_specific or any(term in text for term in ["blackwell", "gb200", "gb300", "ai server", "ai伺服器"]):
        return "NVIDIA / Blackwell 供應鏈訊號；檢查是否反映在鴻海 AI server KPI。"
    if any(term in text for term in ["鴻海", "hon hai", "foxconn", "2317", "富士康"]):
        return "鴻海直接事件；確認是否為具體營運、客戶、產能或財務影響。"
    if any(term in text for term in ["dxy", "us10y", "fed", "cpi", "wti", "美元", "台幣", "匯率", "關稅", "出口管制"]):
        return "總經 / FX / 政策壓力；只作重審提示，不直接改主結論。"
    return row.get("DecisionImpactZh") or "觀察材料；未達主文決策重點。"


def build_report_markdown(
    period: str,
    report_date: str,
    generated_at: str,
    data: dict[str, Any],
) -> str:
    latest_daily = data["latestDaily"]
    latest_macro = data["latestMacro"]
    latest_master = data["latestMaster"]
    news_scan = data["newsScan"] or {}
    review_state = data["reviewState"]
    owner_log_tail = data["ownerLogTail"]

    price = finite_float(latest_daily, "Close")
    pb = finite_float(latest_daily, "PB_daily")
    risk_level = (latest_macro or {}).get("RiskLevel", "N/A")
    highest_news = news_scan.get("highestLevel", "NONE")
    formal_synced = bool(news_scan.get("formalSynced", False))
    hold_under_review = bool(news_scan.get("holdUnderReview", False)) and not formal_synced
    owner_ack_required = bool(review_state.get("ownerAckRequired", False))
    missing_core = not latest_daily or not latest_macro or not latest_master

    if missing_core:
        status = "DATA_BLOCKED"
        decision_action = "先補齊正式 CSV / runtime 缺口；不要進行正式發布或依戰報下結論。"
    elif hold_under_review or owner_ack_required:
        status = "OWNER_REVIEW_REQUIRED"
        decision_action = "只審核下方前 5 個聚合事件與 Owner 待決表；確認是否影響 AI server / CSP capex / FX / 總經假設。"
    else:
        status = "READY_FOR_NEW_UI"
        decision_action = "可進入新 UI 查看六大系統摘要；舊 UI 只作 KPI 明細追查，不需要逐條閱讀原始新聞。"

    period_zh = {"daily": "日報", "weekly": "週報", "monthly": "月報"}.get(period, period)
    recent_daily = sort_by_date(data["dailyRows"], reverse=False)[-10:]
    price_rows = [
        [row.get("Date", ""), row.get("Close", ""), row.get("PB_daily", ""), row.get("Status", "")]
        for row in recent_daily
    ]
    fx_rows = [
        [
            row.get("Date", ""),
            row.get("TWD_USD", ""),
            row.get("DXY", ""),
            row.get("JPY_USD", ""),
            row.get("FxTrend", ""),
            row.get("FxPressureLevel", ""),
            row.get("Actionable", ""),
        ]
        for row in sort_by_date(data["fxRows"], reverse=True)[:7]
    ]

    event_candidates = normalized_event_candidates(data)
    counts = event_level_counts(event_candidates)
    total_discovered = int(news_scan.get("candidateRowCount", 0) or len(event_candidates))
    ranked_events = sorted(
        event_candidates,
        key=lambda row: (event_quality_score(row), row.get("Date", "")),
        reverse=True,
    )
    presentable_events = [row for row in ranked_events if event_quality_score(row) >= 6]
    if not presentable_events:
        presentable_events = ranked_events
    top_event_rows = [
        [
            row.get("Date", ""),
            compact_text(row.get("EventTitle", ""), 72),
            row.get("SourceTier", ""),
            row.get("SourceName", ""),
            row.get("BlackSwanLevel", ""),
            compact_text(event_decision_focus(row), 92),
            row.get("Actionable", "false"),
        ]
        for row in presentable_events[:5]
    ]

    anchor = parse_date(report_date) or datetime.now()
    seventy_two_hour_events = rows_since(data["eventRows"], anchor, 72)
    seven_day_events = rows_since(data["eventRows"], anchor, 24 * 7)
    pending_reviews = review_state.get("pendingReviews", []) or []
    pending_rows = [
        [
            item.get("eventDate", ""),
            compact_text(item.get("eventTitle", ""), 72),
            item.get("level", ""),
            item.get("reviewStatus", ""),
            item.get("reviewDeadline", ""),
            str(item.get("actionable", False)).lower(),
        ]
        for item in pending_reviews[:5]
    ]

    if total_discovered:
        news_takeaway = (
            f"本期新聞掃描共 {total_discovered} 則候選，戰報已聚合為 "
            f"{counts['REVIEW_REQUIRED']} REVIEW_REQUIRED / {counts['WATCH']} WATCH / {counts['OBSERVE']} OBSERVE。"
            f"其中 {len(presentable_events)} 則具備主文摘要訊號；決策者只看排序後前 5 筆與待決表，原始清單保留作稽核。"
        )
    else:
        news_takeaway = "本期沒有可接受新聞候選；不得自行補新聞或產生假事件。"

    lines = [
        f"# P1008 {period_zh} {report_date}",
        "",
        f"- 產生工具：`{TOOL_VERSION}`",
        f"- 產生時間：`{generated_at}`",
        "- 本戰報只讀取正式 CSV、旁路 CSV 與 runtime snapshot；不修改正式 CSV。",
        "- Actionable：`false`；不輸出買賣指令。",
        "",
        "## Executive Summary",
        "",
        f"- 本期狀態：`{status}`",
        f"- 決策者今天要做：{decision_action}",
        "- 主結論 IC：沿用戰情室正式規則與資料；新聞與 FX 只觸發重審提示，不直接改變主結論。",
        "- AI/CSP 新聞規則：CSP 名稱本身不等於鴻海 AI 營收訊號；需同時具備 capex、data center、server/GPU、Blackwell/GB、出口管制或供應鏈語境才進主文排序。",
        f"- 新聞處理：{news_takeaway}",
        "",
        "## KPI / CSV 狀態",
        "",
        markdown_table(
            ["資料", "日期 / 期間", "重點數值", "判讀"],
            [
                [
                    "價格 / 估值",
                    (latest_daily or {}).get("Date", "N/A"),
                    f"Close={price if price is not None else 'N/A'}, PB_daily={pb if pb is not None else 'N/A'}",
                    "正式 daily price CSV；休市沿用只供 UI 顯示，不自動 append。",
                ],
                [
                    "總經快照",
                    (latest_macro or {}).get("Date", "N/A"),
                    f"RiskLevel={risk_level}",
                    "正式 macro_snapshot.csv；旁路事件不得覆寫此表。",
                ],
                [
                    "財務 KPI",
                    (latest_master or {}).get("Quarter", "N/A"),
                    f"EPS_TTM={(latest_master or {}).get('EPS_TTM', 'N/A')}, ROE={(latest_master or {}).get('ROE_TTM_Pct', 'N/A')}",
                    "正式 master KPI CSV。",
                ],
                [
                    "新聞掃描",
                    news_scan.get("generatedAt", "N/A"),
                    f"highestLevel={highest_news}, formalSynced={str(formal_synced).lower()}",
                    "runtime 觀察；只提供重審與反證材料。",
                ],
                [
                    "Owner Review",
                    review_state.get("generatedAt", "N/A"),
                    f"status={review_state.get('status', 'N/A')}, pending={len(pending_reviews)}",
                    "若 pending=0，Launcher 不應停留在待審狀態。",
                ],
            ],
        ),
        "",
        "## Price / Valuation",
        "",
        markdown_table(["Date", "Close", "PB_daily", "Status"], price_rows),
        "",
        "## FX / Macro Sidecar",
        "",
        markdown_table(["日期", "TWD/USD", "DXY", "JPY/USD", "FX 趨勢", "壓力等級", "Actionable"], fx_rows),
        "",
        "## 新聞事件摘要",
        "",
        markdown_table(
            ["候選總數", "REVIEW_REQUIRED", "WATCH", "OBSERVE", "報告處理方式"],
            [[total_discovered, counts["REVIEW_REQUIRED"], counts["WATCH"], counts["OBSERVE"], f"只列前 5 個高訊號聚合事件；完整清單留在 NEWS_SCAN 稽核檔，低訊號索引頁不放主文前列。"]],
        ),
        markdown_table(["日期", "標題", "來源層級", "來源", "等級", "決策影響", "Actionable"], top_event_rows),
        "",
        "## 72h / 7d 保護檢查",
        "",
        markdown_table(
            ["Check", "Result", "Required handling"],
            [
                ["72h WATCH / REVIEW_REQUIRED", f"{len(seventy_two_hour_events)} 筆正式旁路列", "若含 REVIEW_REQUIRED，需 Owner ack；已 formalSynced 則不得重新卡 Gate。"],
                ["7d 事件回顧", f"{len(seven_day_events)} 筆正式旁路列", "週/月報需檢查 stale / ack / unresolved。"],
                ["runtime 新聞候選", f"{total_discovered} 則候選", "只作聚合摘要與重審材料，不直接改 KPI。"],
            ],
        ),
        "",
        "## Owner 待決",
        "",
        markdown_table(["事件日期", "標題", "等級", "Review 狀態", "Deadline", "Actionable"], pending_rows),
        "",
        "## 本期建議",
        "",
        "- Launcher：只處理資料更新、候選資料審查與正式 CSV publish gate。",
        "- 新 UI：作為決策摘要首頁，承接六大系統、最新戰報、研報庫與 SOP 入口。",
        "- 舊 UI：只在主結論 IC、Owner gate、資料治理或 KPI 明細需要追查時開啟。",
        "- 新聞：不要要求決策者逐條審 45 則；系統先做去重、分級、聚合，再列出前 5 個需看事件。",
        "",
        "## Owner Publish Review 摘要",
        "",
        "```text",
        owner_log_tail or "尚無 Owner publish review log。",
        "```",
        "",
        "## 安全邊界",
        "",
        "- 不覆寫正式 CSV。",
        "- 不擴欄 `macro_snapshot.csv`。",
        "- 不啟用 `KEEP_DISABLED` 規則。",
        "- 新聞與 FX 不直接改主結論、不輸出買賣指令。",
    ]
    return "\n".join(lines) + "\n"


def write_report_html(path: Path, report_id: str, title: str, markdown: str) -> None:
    escaped_title = html.escape(title)
    escaped_markdown = html.escape(markdown)
    viewer_href = f"../../report_viewer.html?id={html.escape(report_id)}"
    body = f"""<!doctype html>
<html lang="zh-TW">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escaped_title}</title>
  <style>
    body {{ margin:0; background:#020617; color:#e2e8f0; font-family:Arial,'Microsoft JhengHei',sans-serif; }}
    main {{ max-width:1160px; margin:0 auto; padding:28px 18px 48px; }}
    a {{ color:#67e8f9; font-weight:700; }}
    pre {{ white-space:pre-wrap; line-height:1.65; background:#0f172a; border:1px solid #334155; border-radius:8px; padding:18px; overflow:auto; }}
  </style>
</head>
<body>
  <main>
    <p><a href="{viewer_href}">用 P1008 戰報閱讀器開啟</a></p>
    <pre>{escaped_markdown}</pre>
  </main>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")


def clean_numeric(value: Any) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return float(str(value).replace(",", "").replace("%", "").replace("x", "").strip())
    except ValueError:
        return None


def clean_compact(value: Any, limit: int = 90) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if not text:
        return "N/A"
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def clean_latest_event_rows(data: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in data.get("eventRows", []) or []:
        rows.append(
            {
                "Date": row.get("Date", ""),
                "Title": row.get("EventTitle", ""),
                "SourceTier": row.get("SourceTier", ""),
                "SourceName": row.get("SourceName", ""),
                "RiskTag": row.get("RiskTag", ""),
                "Level": row.get("BlackSwanLevel", ""),
                "Actionable": row.get("Actionable", "false"),
                "Url": row.get("SourceUrl", ""),
            }
        )
    for event in ((data.get("newsScan") or {}).get("events", []) or []):
        row = event.get("candidateRow", {}) or {}
        rows.append(
            {
                "Date": row.get("Date") or event.get("publishedAt") or "",
                "Title": row.get("EventTitle") or event.get("title") or "",
                "SourceTier": row.get("SourceTier") or event.get("sourceTier") or "",
                "SourceName": row.get("SourceName") or event.get("sourceName") or "",
                "RiskTag": row.get("RiskTag") or event.get("riskTag") or event.get("relevanceTag") or "",
                "Level": row.get("BlackSwanLevel") or event.get("level") or "",
                "Actionable": row.get("Actionable", "false"),
                "Url": row.get("SourceUrl") or event.get("url") or "",
            }
        )

    deduped: dict[str, dict[str, str]] = {}
    for row in rows:
        key = (row.get("Url") or f"{row.get('Date')}|{row.get('Title')}").strip().lower()
        if key:
            deduped[key] = row
    return list(deduped.values())


def clean_event_signal_score(row: dict[str, str]) -> int:
    text = " ".join(
        [
            row.get("Title", ""),
            row.get("RiskTag", ""),
            row.get("SourceName", ""),
        ]
    ).lower()
    score = 0
    if row.get("SourceTier", "").upper() == "OFFICIAL":
        score += 30
    if row.get("Level", "").upper() == "REVIEW_REQUIRED":
        score += 25
    elif row.get("Level", "").upper() == "WATCH":
        score += 10
    if any(term in text for term in ["csp", "capex", "data center", "datacenter", "server", "gpu", "blackwell", "gb200", "gb300", "azure", "aws", "google", "meta", "oracle", "coreweave", "anthropic", "nvidia"]):
        score += 30
    if any(term in text for term in ["hon hai", "foxconn", "2317", "鴻海", "富士康"]):
        score += 20
    if any(term in text for term in ["fed", "dxy", "us10y", "wti", "cpi", "匯率", "美元", "利率"]):
        score += 12
    if len(row.get("Title", "").strip()) < 8:
        score -= 15
    return score


def clean_event_focus(row: dict[str, str]) -> str:
    text = " ".join([row.get("Title", ""), row.get("RiskTag", "")]).lower()
    if any(term in text for term in ["csp", "capex", "data center", "datacenter", "server", "gpu", "blackwell", "gb200", "gb300", "azure", "aws", "google", "meta", "oracle", "coreweave", "anthropic", "nvidia"]):
        return "CSP / AI capex demand signal: check whether it supports Hon Hai AI server revenue and shipment assumptions."
    if any(term in text for term in ["hon hai", "foxconn", "2317", "鴻海", "富士康"]):
        return "Direct Hon Hai event: verify whether it changes KPI, revenue, margin, or supply-chain assumptions."
    if any(term in text for term in ["fed", "dxy", "us10y", "wti", "cpi", "匯率", "美元", "利率"]):
        return "Macro / FX watch item: use as review trigger only; do not change HOLD automatically."
    return "Observation only: keep as counter-evidence, not a trading instruction."


def clean_event_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    counts = {"REVIEW_REQUIRED": 0, "WATCH": 0, "OBSERVE": 0, "OTHER": 0}
    for row in rows:
        level = row.get("Level", "").upper()
        counts[level if level in counts else "OTHER"] += 1
    return counts


def clean_next_business_day(value: str) -> str:
    anchor = parse_date(value) or datetime.now()
    day = anchor + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.strftime("%Y-%m-%d")


def build_report_markdown(
    period: str,
    report_date: str,
    generated_at: str,
    data: dict[str, Any],
) -> str:
    latest_daily = data["latestDaily"] or {}
    latest_macro = data["latestMacro"] or {}
    latest_master = data["latestMaster"] or {}
    news_scan = data["newsScan"] or {}
    review_state = data["reviewState"] or {}
    app_state = data.get("appState") or {}
    owner_log_tail = data["ownerLogTail"]

    price = finite_float(latest_daily, "Close")
    pb = finite_float(latest_daily, "PB_daily")
    bvps = finite_float(latest_daily, "BVPS_ref") or finite_float(latest_master, "BVPS")
    roe = finite_float(latest_master, "ROE_TTM_Pct")
    eps_yoy = finite_float(latest_master, "EPS_YoY_Pct")
    eps_ttm = finite_float(latest_master, "EPS_TTM")
    dividend_yield = finite_float(latest_master, "DividendYield_Pct")
    twd_usd = finite_float(latest_macro, "TWD_USD")
    dxy = finite_float(latest_macro, "DXY")
    us10y = finite_float(latest_macro, "US_10Y_Yield")
    vix = finite_float(latest_macro, "VIX")
    wti = finite_float(latest_macro, "WTI_Oil")
    latest_fx = latest(data.get("fxRows", []), "Date") or {}
    fx_pressure = latest_fx.get("FxPressureLevel", "N/A")
    readiness = ((app_state.get("reviewPackage") or {}).get("readiness") or {})
    readiness_score = readiness.get("score", "N/A")

    formal_synced = bool(news_scan.get("formalSynced", False))
    owner_ack_required = bool(review_state.get("ownerAckRequired", False))
    missing_core = not latest_daily or not latest_macro or not latest_master
    if missing_core:
        status = "DATA_BLOCKED"
        decision_action = "不要進入決策摘要；先回 Launcher 重跑資料流程並確認缺漏欄位。"
    elif owner_ack_required and not formal_synced:
        status = "OWNER_REVIEW_REQUIRED"
        decision_action = "留在 Launcher 完成 Owner review；只審高訊號事件，不逐條閱讀新聞。"
    else:
        status = "READY_FOR_NEW_UI"
        decision_action = "可進入新 UI 看六大系統摘要；舊 UI 只作 KPI 明細查證。"

    valuation_state = "待資料"
    if pb is not None:
        if pb <= 1.6:
            valuation_state = "估值有支撐"
        elif pb <= 2.1:
            valuation_state = "合理區上緣"
        elif pb <= 2.3:
            valuation_state = "估值 WATCH"
        else:
            valuation_state = "估值偏高"

    events = clean_latest_event_rows(data)
    event_counts = clean_event_counts(events)
    ranked_events = sorted(events, key=lambda row: (clean_event_signal_score(row), row.get("Date", "")), reverse=True)
    high_signal_events = [row for row in ranked_events if clean_event_signal_score(row) >= 35] or ranked_events[:5]
    news_total = int(news_scan.get("candidateRowCount", 0) or len(events))
    next_review = clean_next_business_day(latest_daily.get("Date") or report_date)

    recent_daily = sort_by_date(data["dailyRows"], reverse=False)[-10:]
    price_rows = [
        [row.get("Date", ""), row.get("Close", ""), row.get("PB_daily", ""), row.get("Status", "")]
        for row in recent_daily
    ]
    fx_rows = [
        [
            row.get("Date", ""),
            row.get("TWD_USD", ""),
            row.get("DXY", ""),
            row.get("JPY_USD", ""),
            row.get("FxTrend", ""),
            row.get("FxPressureLevel", ""),
            row.get("Actionable", ""),
        ]
        for row in sort_by_date(data["fxRows"], reverse=True)[:7]
    ]
    top_event_rows = [
        [
            row.get("Date", ""),
            clean_compact(row.get("Title", ""), 74),
            row.get("SourceTier", ""),
            row.get("SourceName", ""),
            row.get("Level", ""),
            clean_event_focus(row),
            row.get("Actionable", "false"),
        ]
        for row in high_signal_events[:5]
    ]
    pending_reviews = review_state.get("pendingReviews", []) or []
    pending_rows = [
        [
            item.get("eventDate", ""),
            clean_compact(item.get("eventTitle", ""), 72),
            item.get("level", ""),
            item.get("reviewStatus", ""),
            item.get("reviewDeadline", ""),
            str(item.get("actionable", False)).lower(),
        ]
        for item in pending_reviews[:5]
    ] or [["-", "無待審事件", "-", "-", "-", "false"]]

    period_zh = {"daily": "日報", "weekly": "週報", "monthly": "月報"}.get(period, period)
    six_system_rows = [
        ["基本面 IC", f"ROE={roe if roe is not None else 'N/A'}%, EPS YoY={eps_yoy if eps_yoy is not None else 'N/A'}%, EPS TTM={eps_ttm if eps_ttm is not None else 'N/A'}", "基本面支撐", "看 EPS/ROE 是否延續，月營收與毛利率是下一輪驗證。"],
        ["估值 IC", f"Close={price if price is not None else 'N/A'}, BVPS={bvps if bvps is not None else 'N/A'}, PB={pb if pb is not None else 'N/A'}", valuation_state, "PB 1.6x 以下支撐、1.6-2.1x 合理、2.1x 以上 WATCH、2.3x 以上偏高。"],
        ["現金流 IC", f"Dividend yield={dividend_yield if dividend_yield is not None else 'N/A'}%, US10Y={us10y if us10y is not None else 'N/A'}%", "現金回報中性", "此 IC 衡量股東現金回報、FCF、負債與低風險收益比較，不是籌碼面。"],
        ["宏觀 / 匯率 IC", f"USD/TWD={twd_usd}, DXY={dxy}, US10Y={us10y}, VIX={vix}, WTI={wti}", f"FX {fx_pressure}", "USD/TWD 季均值變動 ±1%，先以 ±NT$0.05-0.10 EPS 敏感度估算；只提示重審。"],
        ["產業 / AI IC", f"news={news_total}, high_signal={len(high_signal_events)}", "CSP 需求待驗證", "聚焦美國七大 CSP capex、AI server、GB200/GB300、NVIDIA/雲端客戶需求，不要求決策者逐條讀新聞。"],
        ["資料品質 IC", f"readiness={readiness_score}%, formalSynced={str(formal_synced).lower()}", "正式可用" if formal_synced else "待審", "schema、來源覆蓋、Actionable=false、Owner publish 與 event sync 是通過條件。"],
    ]
    owner_publish_rows = [
        ["App job", app_state.get("jobId", "N/A"), app_state.get("status", "N/A"), app_state.get("finishedAt", "N/A")],
        ["Readiness", f"{readiness.get('score', 'N/A')} / {readiness.get('threshold', 'N/A')}", "allowed" if readiness.get("allowed") else "review", f"sources={readiness.get('sourceAvailable', 'N/A')}/{readiness.get('sourceTotal', 'N/A')}"],
        ["Formal CSV publish", app_state.get("publishDate", "N/A"), "已完成" if app_state.get("formalCsvModified") else "未修改", "Owner gate only"],
        ["Report generation", generated_at, "未修改正式 CSV", "productionCsvModified=false"],
    ]

    return "\n".join(
        [
            f"# P1008 {period_zh} {report_date}",
            "",
            f"- 生成器：`{TOOL_VERSION}`",
            f"- 生成時間：`{generated_at}`",
            "- 安全邊界：本報只讀正式 CSV、旁路 CSV 與 runtime snapshot；不修改正式 CSV。",
            "- Actionable：`false`；不輸出買賣指令。",
            "",
            "## 1. 決策者先看",
            "",
            f"- 本期狀態：`{status}`",
            f"- 今天要做：{decision_action}",
            f"- 下一次檢視：{next_review} 開盤前，或 REVIEW_REQUIRED / 宏觀異常觸發時。",
            f"- 新聞處理：本次蒐集 {news_total} 則，系統只保留 {len(high_signal_events[:5])} 筆高訊號摘要在主文；完整清單留在 NEWS_SCAN 稽核檔。",
            "",
            "## 2. 六大系統 KPI 摘要",
            "",
            markdown_table(["系統", "核心數據", "判讀", "決策含義"], six_system_rows),
            "",
            "## 3. KPI / CSV 狀態",
            "",
            markdown_table(
                ["資料", "日期 / 期間", "重點數值", "判讀"],
                [
                    ["價格 / 估值", latest_daily.get("Date", "N/A"), f"Close={price}, PB_daily={pb}", "正式 daily price CSV；休市沿用只供 Launcher / 新 UI 視覺提示。"],
                    ["總經快照", latest_macro.get("Date", "N/A"), f"RiskLevel={latest_macro.get('RiskLevel', 'N/A')}", "正式 macro_snapshot.csv；新聞與 FX 旁路不覆寫此表。"],
                    ["Master KPI", latest_master.get("Quarter", "N/A"), f"EPS_TTM={eps_ttm}, ROE={roe}", "正式 master KPI CSV。"],
                    ["新聞掃描", news_scan.get("generatedAt", "N/A"), f"highestLevel={news_scan.get('highestLevel', 'NONE')}, formalSynced={str(formal_synced).lower()}", "runtime / event sidecar；只提供重審與反證材料。"],
                    ["Owner Review", review_state.get("generatedAt", "N/A"), f"status={review_state.get('status', 'N/A')}, pending={len(pending_reviews)}", "pending=0 時不再阻擋進入新 UI。"],
                ],
            ),
            "",
            "## 4. Price / Valuation",
            "",
            markdown_table(["Date", "Close", "PB_daily", "Status"], price_rows),
            "",
            "## 5. FX / Macro Sidecar",
            "",
            markdown_table(["日期", "TWD/USD", "DXY", "JPY/USD", "FX 趨勢", "壓力等級", "Actionable"], fx_rows),
            "",
            "## 6. 新聞事件摘要",
            "",
            markdown_table(
                ["候選總數", "REVIEW_REQUIRED", "WATCH", "OBSERVE", "報告處理方式"],
                [[news_total, event_counts["REVIEW_REQUIRED"], event_counts["WATCH"], event_counts["OBSERVE"], "只列高訊號聚合事件；低訊號與重複新聞不佔用主文篇幅。"]],
            ),
            markdown_table(["日期", "標題", "來源層級", "來源", "等級", "決策影響", "Actionable"], top_event_rows),
            "",
            "## 7. Owner 待決",
            "",
            markdown_table(["事件日期", "標題", "等級", "Review 狀態", "Deadline", "Actionable"], pending_rows),
            "",
            "## 8. 本期建議",
            "",
            "- Launcher：只負責更新資料、新聞掃描、Owner review 與正式 CSV publish gate。",
            "- 新 UI：負責六大系統摘要與決策視野，正式資料通過後才進入。",
            "- 舊 UI：只作主 IC、Owner gate、KPI 明細與戰報查證，不再承擔一鍵更新流程。",
            "- 新聞：不讓決策者閱讀 45 則原始新聞；由系統歸納成高訊號事件、主題與反證。",
            "",
            "## 9. Owner Publish Review 摘要",
            "",
            markdown_table(["項目", "日期 / ID", "狀態", "補充"], owner_publish_rows),
            "",
            "## 10. 安全邊界",
            "",
            "- 不覆寫正式 CSV。",
            "- 不擴欄 `macro_snapshot.csv`。",
            "- 不啟用 `KEEP_DISABLED` 規則。",
            "- 新聞與 FX 不直接改變 HOLD 主結論。",
        ]
    ) + "\n"


def write_report_html(path: Path, report_id: str, title: str, markdown: str) -> None:
    escaped_title = html.escape(title)
    escaped_markdown = html.escape(markdown)
    viewer_href = f"../../report_viewer.html?id={html.escape(report_id)}"
    body = f"""<!doctype html>
<html lang="zh-TW">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escaped_title}</title>
  <style>
    body {{ margin:0; background:#020617; color:#e2e8f0; font-family:Arial,'Microsoft JhengHei',sans-serif; }}
    main {{ max-width:1160px; margin:0 auto; padding:28px 18px 48px; }}
    a {{ color:#67e8f9; font-weight:700; }}
    pre {{ white-space:pre-wrap; line-height:1.65; background:#0f172a; border:1px solid #334155; border-radius:8px; padding:18px; overflow:auto; }}
  </style>
</head>
<body>
  <main>
    <p><a href="{viewer_href}">用 P1008 戰報閱讀器開啟</a></p>
    <pre>{escaped_markdown}</pre>
  </main>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")


def update_report_manifest(package_root: Path, report: dict[str, Any], generated_at: str) -> dict[str, Any]:
    manifest_path = package_root / REPORT_MANIFEST
    manifest = read_json(manifest_path, default={}) or {}
    reports = [item for item in manifest.get("reports", []) if item.get("id") != report["id"]]
    reports.append(report)
    reports.sort(key=lambda item: (item.get("date", ""), item.get("period", ""), item.get("id", "")), reverse=True)

    latest_by_period: dict[str, Any] = {"daily": None, "weekly": None, "monthly": None}
    for item in reports:
        period = item.get("period")
        if period in latest_by_period and latest_by_period[period] is None:
            latest_by_period[period] = item

    manifest = {
        "schemaVersion": "1.0",
        "generatedAt": generated_at,
        "toolVersion": TOOL_VERSION,
        "productionCsvModified": False,
        "actionable": False,
        "latest": latest_by_period,
        "reports": reports,
    }
    write_json(manifest_path, manifest)
    write_json(package_root / RUNTIME_REPORT_MANIFEST, manifest)
    return manifest


def write_report_html(path: Path, report_id: str, title: str, markdown: str) -> None:
    body_html = report_markdown_to_html(markdown)
    viewer_href = f"../../report_viewer.html?id={html.escape(report_id)}"
    body = f"""<!doctype html>
<html lang="zh-TW">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: dark; --bg:#07111f; --panel:#0f1b2c; --line:#274761; --text:#e8f3ff; --muted:#9fb3c8; --warn:#ffd166; --cyan:#67e8f9; }}
    body {{ margin:0; background:linear-gradient(180deg,#06101d,#081827 48%,#050b13); color:var(--text); font-family:Arial,'Microsoft JhengHei',sans-serif; }}
    main {{ max-width:1180px; margin:0 auto; padding:28px 18px 54px; }}
    .nav {{ display:flex; flex-wrap:wrap; gap:10px; margin-bottom:16px; }}
    .nav a, .nav button {{ color:var(--cyan); text-decoration:none; border:1px solid var(--line); border-radius:8px; padding:8px 12px; background:#0b1626; font-weight:700; font:inherit; cursor:pointer; }}
    .nav button:disabled {{ opacity:.48; cursor:not-allowed; }}
    .nav button[aria-pressed="true"] {{ border-color:rgba(52,211,153,.62); color:#a7f3d0; background:rgba(6,78,59,.35); }}
    h1 {{ font-size:30px; margin:10px 0 18px; letter-spacing:0; }}
    h2 {{ font-size:20px; margin:26px 0 12px; color:#f8fafc; border-left:4px solid var(--warn); padding-left:10px; }}
    p, ul, .table-wrap {{ background:rgba(15,27,44,.82); border:1px solid rgba(80,128,166,.42); border-radius:10px; }}
    p {{ padding:12px 14px; line-height:1.65; }}
    ul {{ padding:12px 18px 12px 34px; line-height:1.75; }}
    li {{ margin:4px 0; }}
    code {{ color:#fef08a; }}
    .table-wrap {{ overflow:auto; margin:12px 0 18px; }}
    table {{ width:100%; border-collapse:collapse; min-width:760px; }}
    th, td {{ padding:10px 12px; border-bottom:1px solid rgba(80,128,166,.32); text-align:left; vertical-align:top; line-height:1.5; }}
    th {{ color:#b6e7ff; font-size:12px; text-transform:uppercase; letter-spacing:.03em; background:rgba(19,37,59,.9); }}
    td {{ color:#e8f3ff; font-size:14px; }}
    tr:last-child td {{ border-bottom:0; }}
    .chart-card {{ margin:14px 0 20px; background:rgba(15,27,44,.92); border:1px solid rgba(80,128,166,.46); border-radius:12px; padding:14px; }}
    .chart-card img {{ display:block; width:100%; height:auto; border-radius:10px; background:#0f1b2c; }}
    .chart-card figcaption {{ color:var(--muted); font-size:13px; line-height:1.55; margin-top:8px; }}
    :fullscreen {{ background:#07111f; }}
    body.p1008-focus-mode {{ background:#07111f; }}
    body.p1008-focus-mode main {{ max-width:none; min-height:100vh; }}
    @media (max-width:760px) {{ main {{ padding:18px 10px 36px; }} h1 {{ font-size:24px; }} table {{ min-width:680px; }} }}
  </style>
  <script>
    const P1008_IMMERSIVE_KEY = "p1008_immersive_mode";
    function readImmersivePref() {{
      try {{ return localStorage.getItem(P1008_IMMERSIVE_KEY) === "1"; }} catch (err) {{ return false; }}
    }}
    function writeImmersivePref(active) {{
      try {{ localStorage.setItem(P1008_IMMERSIVE_KEY, active ? "1" : "0"); }} catch (err) {{}}
    }}
    function immersiveRequested() {{
      return new URLSearchParams(window.location.search).get("fs") === "1" || readImmersivePref();
    }}
    function immersiveActive() {{
      return document.body.classList.contains("p1008-focus-mode") || immersiveRequested();
    }}
    function withImmersive(href) {{
      const url = new URL(href, window.location.href);
      if (immersiveActive()) url.searchParams.set("fs", "1");
      else url.searchParams.delete("fs");
      return url.href;
    }}
    function syncImmersiveLinks() {{
      document.querySelectorAll("a[href]").forEach((link) => {{
        const raw = link.getAttribute("href");
        if (!raw || /^(#|mailto:|tel:|javascript:)/i.test(raw)) return;
        const url = new URL(raw, window.location.href);
        if (url.protocol === window.location.protocol && url.host === window.location.host) {{
          link.setAttribute("href", withImmersive(raw));
        }}
      }});
    }}
    async function toggleFullscreen() {{
      const next = !document.body.classList.contains("p1008-focus-mode");
      if (!next && document.fullscreenElement) {{
        try {{ await document.exitFullscreen(); }} catch (err) {{}}
      }}
      document.body.classList.toggle("p1008-focus-mode", next);
      writeImmersivePref(next);
      syncImmersiveLinks();
      updateFullscreenButton();
    }}
    function updateFullscreenButton() {{
      const btn = document.getElementById("fullscreen-toggle");
      if (!btn) return;
      const active = Boolean(document.body.classList.contains("p1008-focus-mode") || document.fullscreenElement);
      btn.disabled = false;
      btn.textContent = active ? "退出全螢幕" : "全螢幕";
      btn.setAttribute("aria-pressed", active ? "true" : "false");
      btn.title = "切換戰情室沉浸模式；內部跳轉會保持此狀態";
    }}
    document.addEventListener("click", (event) => {{
      const link = event.target.closest?.("a[href]");
      if (!link) return;
      const raw = link.getAttribute("href");
      if (!raw || /^(#|mailto:|tel:|javascript:)/i.test(raw)) return;
      const url = new URL(raw, window.location.href);
      if (url.protocol === window.location.protocol && url.host === window.location.host) {{
        link.setAttribute("href", withImmersive(raw));
      }}
    }}, true);
    document.addEventListener("fullscreenchange", updateFullscreenButton);
    document.addEventListener("DOMContentLoaded", () => {{
      if (immersiveRequested()) document.body.classList.add("p1008-focus-mode");
      syncImmersiveLinks();
      updateFullscreenButton();
    }});
  </script>
</head>
<body>
  <main>
    <div class="nav">
      <button id="fullscreen-toggle" type="button" onclick="toggleFullscreen()" aria-pressed="false">全螢幕</button>
      <a href="{viewer_href}">開啟報告 Viewer</a>
      <a href="../../reports.html?from=report">回研報庫</a>
      <a href="../../launcher.html?stay=1">回 Launcher</a>
    </div>
    {body_html}
  </main>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")


def build_report(args: argparse.Namespace) -> int:
    package_root = Path(args.package_root).resolve()
    generated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    report_date = args.date or datetime.now().strftime("%Y-%m-%d")
    period = args.period

    daily_rows, daily_issues = read_csv_rows(package_root / "data/2317_daily_price.csv", DAILY_COLUMNS)
    macro_rows, macro_issues = read_csv_rows(package_root / "data/macro_snapshot.csv", MACRO_COLUMNS)
    master_rows, master_issues = read_csv_rows(package_root / "data/2317_master_v9.csv")
    event_rows, event_issues = read_csv_rows(package_root / "data/macro_event_observations.csv", MACRO_EVENT_COLUMNS)
    fx_rows, fx_issues = read_csv_rows(package_root / "data/fx_trend_observations.csv", FX_TREND_COLUMNS)
    news_scan = read_json(package_root / "runtime/warroom_news_scan_snapshot.json", default={}) or {}
    app_state = read_json(package_root / "runtime/p1008_app_state.json", default={}) or {}
    owner_log_path = package_root / "logs/last_owner_publish_review.log"
    owner_log_tail = ""
    if owner_log_path.exists():
        owner_log_tail = "\n".join(owner_log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-24:])

    review_state = build_event_review_state(package_root, news_scan, generated_at)
    latest_master = latest(master_rows, "Quarter")
    latest_daily = latest(daily_rows, "Date")
    latest_macro = latest(macro_rows, "Date")
    data = {
        "dailyRows": daily_rows,
        "macroRows": macro_rows,
        "masterRows": master_rows,
        "eventRows": event_rows,
        "fxRows": fx_rows,
        "latestDaily": latest_daily,
        "latestMacro": latest_macro,
        "latestMaster": latest_master,
        "newsScan": news_scan,
        "appState": app_state,
        "reviewState": review_state,
        "ownerLogTail": owner_log_tail,
    }

    report_id = f"P1008_{period.upper()}_REPORT_{report_date.replace('-', '')}"
    period_zh = {"daily": "日報", "weekly": "週報", "monthly": "月報"}.get(period, period)
    title = f"P1008 {period_zh} {report_date}"
    report_dir = package_root / "reports/generated"
    md_rel = f"generated/{report_id}.md"
    html_rel = f"generated/{report_id}.html"
    md_path = report_dir / f"{report_id}.md"
    html_path = report_dir / f"{report_id}.html"
    latest_html_path = report_dir / "latest_report.html"
    charts = write_report_charts(package_root, report_id, data)
    markdown = build_report_markdown(period, report_date, generated_at, data)
    markdown = append_chart_markdown(markdown, charts)
    shadow_candidate = read_shadow_candidate(package_root, report_date)
    markdown = append_shadow_candidate(markdown, shadow_candidate)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown, encoding="utf-8", newline="\n")
    write_report_html(html_path, report_id, title, markdown)
    write_report_html(latest_html_path, report_id, title, markdown)

    issues = daily_issues + macro_issues + master_issues + event_issues + fx_issues
    report = {
        "id": report_id,
        "period": period,
        "date": report_date,
        "title": title,
        "tags": [period_zh, "資料稽核", "主結論檢查", "actionable:false"],
        "md": md_rel,
        "html": html_rel,
        "source": TOOL_VERSION,
        "actionable": False,
        "productionCsvModified": False,
        "status": "GENERATED_WITH_WARNINGS" if issues else "GENERATED",
        "issues": issues,
        "eventReviewState": EVENT_REVIEW_STATE,
        "pluginShadowCandidate": (
            PLUGIN_SHADOW_CANDIDATE if shadow_candidate is not None else ""
        ),
    }
    report["tags"] = [period_zh, "戰報", "新聞去噪", "圖表", "actionable:false"]
    report["charts"] = [f"generated/charts/{chart['path']}" for chart in charts]
    manifest = update_report_manifest(package_root, report, generated_at)

    log(f"Report markdown: {md_path}")
    log(f"Report html: {html_path}")
    log(f"Latest direct html: {latest_html_path}")
    log(f"Report manifest: {package_root / REPORT_MANIFEST}")
    log(f"Runtime report manifest: {package_root / RUNTIME_REPORT_MANIFEST}")
    log(f"Reports in manifest: {len(manifest.get('reports', []))}")
    log("Formal CSV modified: NO")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="產生 P1008 本機定期戰報產物。")
    parser.add_argument("--package-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--date", default="")
    parser.add_argument("--period", choices=["daily", "weekly", "monthly"], default="daily")
    return parser.parse_args()


def report_period_zh(period: str) -> str:
    return {"daily": "日報", "weekly": "週報", "monthly": "月報"}.get(period, period)


def report_compact(value: Any, limit: int = 96) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if not text:
        return "N/A"
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "..."


def report_num(value: Any, digits: int = 2, suffix: str = "") -> str:
    number = clean_numeric(value)
    if number is None:
        return "N/A"
    text = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    return f"{text}{suffix}"


def report_ratio(value: Any) -> str:
    number = clean_numeric(value)
    if number is None:
        return "N/A"
    return f"{number:.3f}".rstrip("0").rstrip(".") + "x"


def report_mojibake(value: Any) -> bool:
    text = str(value or "")
    if not text:
        return False
    bad_tokens = ["�", "嚗", "蝬", "摰", "銝", "隞", "鞈", "蝟", "餈", "撖", "雿", "瘙", "甇", "閮", "頝"]
    if any(token in text for token in bad_tokens):
        return True
    return text.count("?") >= 2 and len(text) <= 80


def report_clean_label(value: Any, fallback: str = "來源文字待核對") -> str:
    text = report_compact(value, 120)
    if report_mojibake(text):
        return fallback
    return text


def report_valuation_state(pb: float | None) -> tuple[str, str]:
    if pb is None:
        return "待補資料", "缺少 PB，估值 IC 只能維持觀察。"
    if pb <= 1.6:
        return "低於支撐區", "PB 低於 1.6x，需檢查是否為基本面惡化或市場錯殺。"
    if pb <= 2.1:
        return "合理區上緣", "PB 介於 1.6x 到 2.1x，屬合理區偏上，不應標成估值過熱。"
    if pb <= 2.3:
        return "估值 WATCH", "PB 高於 2.1x 但低於 2.3x，需觀察 EPS/ROE 是否同步上修。"
    return "估值偏高", "PB 高於 2.3x，若 EPS/ROE 未上修，估值風險升高。"


def report_cashflow_state(dividend_yield: float | None, us10y: float | None) -> tuple[str, str]:
    if dividend_yield is None:
        return "待補股東回報", "缺少殖利率，現金流 / 股東回報 IC 不做強判斷。"
    if us10y is None:
        return "股東回報觀察", "有殖利率但缺 US10Y，無法判斷相對無風險利率吸引力。"
    spread = dividend_yield - us10y
    if spread >= 0.5:
        return "股東回報支撐", f"殖利率約高於 US10Y {spread:.2f} 個百分點，對低風險收益比較有支撐。"
    if spread >= -0.5:
        return "現金回報中性", f"殖利率與 US10Y 接近（差 {spread:.2f} 個百分點），不構成明顯加分或扣分。"
    return "現金回報偏弱", f"殖利率低於 US10Y {abs(spread):.2f} 個百分點，對收益型資金吸引力偏弱。"


def report_news_summary(news_scan: dict[str, Any]) -> tuple[str, str]:
    network = news_scan.get("networkSummary") or {}
    checked = int(network.get("checked", 0) or 0)
    succeeded = int(network.get("succeeded", 0) or 0)
    total = int(news_scan.get("candidateRowCount", 0) or 0)
    high = str(news_scan.get("highestLevel", "NONE") or "NONE").upper()
    connector_text = f"新聞 connector {succeeded}/{checked} 成功" if checked else "新聞 connector 尚未完成掃描"
    if total <= 0:
        return connector_text, "本期沒有可接受新聞候選，系統不得自行補新聞。"
    return connector_text, f"本期掃描收斂為 {total} 則候選，最高等級 {high}；主文只保留高訊號摘要，完整清單留在 NEWS_SCAN 稽核。"


def report_event_rows(data: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in data.get("eventRows", []) or []:
        rows.append(
            {
                "Date": row.get("Date", ""),
                "Title": row.get("EventTitle", ""),
                "SourceTier": row.get("SourceTier", ""),
                "SourceName": row.get("SourceName", ""),
                "RiskTag": row.get("RiskTag", ""),
                "Level": row.get("BlackSwanLevel", ""),
                "Actionable": row.get("Actionable", "false"),
                "Url": row.get("SourceUrl", ""),
                "Summary": row.get("SummaryZh", ""),
            }
        )
    for event in ((data.get("newsScan") or {}).get("events", []) or []):
        row = event.get("candidateRow", {}) or {}
        rows.append(
            {
                "Date": row.get("Date") or event.get("publishedAt") or "",
                "Title": row.get("EventTitle") or event.get("title") or "",
                "SourceTier": row.get("SourceTier") or event.get("sourceTier") or "",
                "SourceName": row.get("SourceName") or event.get("sourceName") or "",
                "RiskTag": row.get("RiskTag") or event.get("riskTag") or event.get("relevanceTag") or "",
                "Level": row.get("BlackSwanLevel") or event.get("level") or "",
                "Actionable": row.get("Actionable", "false"),
                "Url": row.get("SourceUrl") or event.get("url") or "",
                "Summary": row.get("SummaryZh") or event.get("summaryZh") or "",
            }
        )
    deduped: dict[str, dict[str, str]] = {}
    for row in rows:
        key = (row.get("Url") or f"{row.get('Date')}|{row.get('Title')}").strip().lower()
        if key:
            deduped[key] = row
    return list(deduped.values())


def report_event_score(row: dict[str, str]) -> int:
    text = " ".join([row.get("Title", ""), row.get("RiskTag", ""), row.get("SourceName", ""), row.get("Summary", "")]).lower()
    score = 0
    if row.get("SourceTier", "").upper() == "OFFICIAL":
        score += 30
    if row.get("Level", "").upper() == "REVIEW_REQUIRED":
        score += 25
    elif row.get("Level", "").upper() == "WATCH":
        score += 10
    if any(term in text for term in ["csp", "capex", "data center", "datacenter", "server", "gpu", "blackwell", "gb200", "gb300", "azure", "aws", "google", "meta", "oracle", "coreweave", "nvidia", "ai server"]):
        score += 30
    if any(term in text for term in ["hon hai", "foxconn", "2317", "鴻海", "富士康"]):
        score += 25
    if any(term in text for term in ["fed", "dxy", "us10y", "wti", "cpi", "匯率", "美元", "利率"]):
        score += 12
    if report_mojibake(row.get("Title")):
        score -= 12
    return score


def report_event_focus(row: dict[str, str]) -> str:
    text = " ".join([row.get("Title", ""), row.get("RiskTag", ""), row.get("Summary", "")]).lower()
    if any(term in text for term in ["csp", "capex", "data center", "datacenter", "server", "gpu", "blackwell", "gb200", "gb300", "azure", "aws", "google", "meta", "oracle", "coreweave", "nvidia", "ai server"]):
        return "檢查是否支撐鴻海 AI server 營收、出貨與毛利假設。"
    if any(term in text for term in ["hon hai", "foxconn", "2317", "鴻海", "富士康"]):
        return "直接關聯鴻海，需核對是否改變營收、供應鏈或 KPI 假設。"
    if any(term in text for term in ["fed", "dxy", "us10y", "wti", "cpi", "匯率", "美元", "利率"]):
        return "總經 / FX 重審提示，只作風險觀察，不改主 IC。"
    return "保留為反證材料，不要求決策者逐條閱讀。"


def report_event_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    counts = {"REVIEW_REQUIRED": 0, "WATCH": 0, "OBSERVE": 0, "OTHER": 0}
    for row in rows:
        level = row.get("Level", "").upper()
        counts[level if level in counts else "OTHER"] += 1
    return counts


def report_next_business_day(value: str) -> str:
    anchor = parse_date(value) or datetime.now()
    day = anchor + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.strftime("%Y-%m-%d")


def build_report_markdown(
    period: str,
    report_date: str,
    generated_at: str,
    data: dict[str, Any],
) -> str:
    latest_daily = data["latestDaily"] or {}
    latest_macro = data["latestMacro"] or {}
    latest_master = data["latestMaster"] or {}
    news_scan = data["newsScan"] or {}
    review_state = data["reviewState"] or {}
    app_state = data.get("appState") or {}

    price = finite_float(latest_daily, "Close")
    pb = finite_float(latest_daily, "PB_daily")
    bvps = finite_float(latest_daily, "BVPS_ref") or finite_float(latest_master, "BVPS")
    roe = finite_float(latest_master, "ROE_TTM_Pct")
    eps_yoy = finite_float(latest_master, "EPS_YoY_Pct")
    eps_ttm = finite_float(latest_master, "EPS_TTM")
    dividend_yield = finite_float(latest_master, "DividendYield_Pct")
    twd_usd = finite_float(latest_macro, "TWD_USD")
    dxy = finite_float(latest_macro, "DXY")
    us10y = finite_float(latest_macro, "US_10Y_Yield")
    vix = finite_float(latest_macro, "VIX")
    wti = finite_float(latest_macro, "WTI_Oil")
    latest_fx = latest(data.get("fxRows", []), "Date") or {}

    readiness = ((app_state.get("reviewPackage") or {}).get("readiness") or {})
    readiness_score = readiness.get("score", "N/A")
    readiness_threshold = readiness.get("threshold", 95)
    readiness_allowed = bool(readiness.get("allowed", False))
    formal_synced = bool(news_scan.get("formalSynced", False))
    owner_ack_required = bool(review_state.get("ownerAckRequired", False))
    formal_modified = bool(app_state.get("formalCsvModified", False))
    pending_publish = bool((app_state.get("pendingOwnerReview") or {}).get("pending", False))

    if not latest_daily or not latest_macro or not latest_master:
        gate_status = "DATA_BLOCKED"
        decision_line = "核心 CSV 不完整，停留在 Launcher 補資料，不進入新 UI 決策摘要。"
    elif pending_publish or owner_ack_required:
        gate_status = "OWNER_REVIEW_REQUIRED"
        decision_line = "仍有候選資料或事件待 Owner 審查，先在 Launcher 完成核准或註記。"
    else:
        gate_status = "READY_FOR_NEW_UI"
        decision_line = "正式 CSV / 新聞 / FX 狀態已同步，可進入新 UI 看六大系統摘要；舊 UI 只作 KPI 明細。"

    valuation_state, valuation_reason = report_valuation_state(pb)
    cashflow_state, cashflow_reason = report_cashflow_state(dividend_yield, us10y)
    connector_text, news_text = report_news_summary(news_scan)
    next_review = report_next_business_day(latest_daily.get("Date") or report_date)
    events = report_event_rows(data)
    event_counts = report_event_counts(events)
    ranked_events = sorted(events, key=lambda row: (report_event_score(row), row.get("Date", "")), reverse=True)
    high_signal_events = [row for row in ranked_events if report_event_score(row) >= 35][:5]
    news_total = int(news_scan.get("candidateRowCount", 0) or len(events))
    if not high_signal_events and ranked_events:
        high_signal_events = ranked_events[:3]

    fx_pressure = latest_fx.get("FxPressureLevel", "N/A")
    macro_tone = "中性觀察"
    if vix is not None and vix >= 20:
        macro_tone = "風險升高"
    elif dxy is not None and dxy >= 102:
        macro_tone = "美元偏強"
    elif fx_pressure and fx_pressure != "N/A":
        macro_tone = str(fx_pressure)

    six_system_rows = [
        ["基本面 IC", f"ROE {report_num(roe, 2, '%')} / EPS YoY {report_num(eps_yoy, 1, '%')} / EPS TTM {report_num(eps_ttm, 2)}", "基本面支撐" if (roe or 0) >= 10 and (eps_yoy or 0) >= 0 else "基本面觀察", "EPS 與 ROE 是 HOLD 的主要支撐，若後續下修才需要重審估值。"],
        ["估值 IC", f"Close {report_num(price, 1)} / BVPS {report_num(bvps, 2)} / PB {report_ratio(pb)}", valuation_state, valuation_reason],
        ["現金流 / 股東回報 IC", f"殖利率 {report_num(dividend_yield, 2, '%')} / US10Y {report_num(us10y, 3, '%')}", cashflow_state, cashflow_reason],
        ["宏觀 / 匯率 IC", f"USD/TWD {report_num(twd_usd, 3)} / DXY {report_num(dxy, 3)} / VIX {report_num(vix, 2)} / WTI {report_num(wti, 2)}", macro_tone, "USD/TWD 季均值每變動 1%，先用 NT$0.05-0.10 EPS 敏感度重審，不直接改主 IC。"],
        ["產業 / AI IC", f"新聞候選 {news_total}，高訊號 {len(high_signal_events)}", "CSP 需求待驗證", "重點看美國七大 CSP capex、AI server、GB200/GB300、NVIDIA 與雲端客戶需求，不要求逐條讀新聞。"],
        ["資料品質 IC", f"正式發布 readiness {readiness_score}/{readiness_threshold}，connector {connector_text}", "正式可用" if readiness_allowed else "待審", "這是正式 CSV 發布稽核分數，不是六大 IC 投資分數。"],
    ]

    market_rows = [
        ["2317 close", latest_daily.get("Date", "N/A"), report_num(price, 1), latest_daily.get("DataSupportLevel", "N/A")],
        ["PB", latest_daily.get("Date", "N/A"), report_ratio(pb), "Close / BVPS"],
        ["USD/TWD", latest_macro.get("Date", "N/A"), report_num(twd_usd, 3), latest_fx.get("SourceTier") or "macro_snapshot"],
        ["US10Y", latest_macro.get("Date", "N/A"), report_num(us10y, 3, "%"), "macro_snapshot"],
        ["VIX / DXY / WTI", latest_macro.get("Date", "N/A"), f"{report_num(vix, 2)} / {report_num(dxy, 2)} / {report_num(wti, 2)}", "macro_snapshot"],
    ]

    news_rows = []
    for row in high_signal_events:
        news_rows.append(
            [
                row.get("Date", "N/A"),
                report_clean_label(row.get("Title"), "標題編碼待核對，請開原始來源確認"),
                report_clean_label(row.get("SourceName"), row.get("SourceTier", "來源待核對")),
                row.get("Level", "N/A"),
                report_event_focus(row),
                row.get("Actionable", "false"),
            ]
        )
    if not news_rows:
        news_rows = [["-", "本期無可用高訊號新聞", "-", "NONE", "不做新聞解讀。", "false"]]

    pending_reviews = review_state.get("pendingReviews", []) or []
    owner_rows = [
        ["Launcher gate", gate_status, decision_line],
        ["正式 CSV", "已更新" if formal_modified else "未修改", "一鍵流程不會發布；Owner publish gate 才會 append。"],
        ["事件審查", review_state.get("status", "N/A"), f"pending={len(pending_reviews)}；formalSynced={str(formal_synced).lower()}"],
        ["下次檢視", next_review, "開盤前或異常事件觸發時重審；戰情室不輸出買賣指令。"],
    ]

    return "\n".join(
        [
            f"# P1008 {report_period_zh(period)} {report_date}",
            "",
            "## 今日結論",
            "",
            f"- 戰情室狀態：`{gate_status}`。",
            f"- 決策摘要：{decision_line}",
            f"- 估值判讀：{valuation_state}；{valuation_reason}",
            f"- 新聞處理：{news_text}",
            "- 安全邊界：本報只提供重審提示與反證材料，`Actionable=false`，不輸出買賣指令。",
            "",
            "## 關鍵數據卡",
            "",
            markdown_table(["項目", "日期", "數值", "來源 / 口徑"], market_rows),
            "",
            "## 六大系統摘要",
            "",
            markdown_table(["系統", "核心數據", "判讀", "決策含義"], six_system_rows),
            "",
            "## 國際與產業新聞去噪",
            "",
            f"- {connector_text}；本期候選 {news_total} 則，REVIEW_REQUIRED {event_counts['REVIEW_REQUIRED']}、WATCH {event_counts['WATCH']}、OBSERVE {event_counts['OBSERVE']}。",
            "- 報告主文只列高訊號事件；原始新聞清單留在 NEWS_SCAN 稽核檔，不要求決策者閱讀全部候選。",
            "",
            markdown_table(["日期", "事件摘要", "來源", "等級", "對鴻海的判讀工作", "Actionable"], news_rows),
            "",
            "## FX / Macro 判讀",
            "",
            markdown_table(
                ["項目", "目前值", "判讀", "處理方式"],
                [
                    ["USD/TWD", report_num(twd_usd, 3), f"FX pressure={fx_pressure}", "用 EPS 敏感度重審，不直接改 HOLD。"],
                    ["DXY / US10Y", f"{report_num(dxy, 3)} / {report_num(us10y, 3, '%')}", macro_tone, "確認美元與利率是否壓縮估值倍數。"],
                    ["VIX / WTI", f"{report_num(vix, 2)} / {report_num(wti, 2)}", "風險與成本監控", "VIX>20 或油價急升時列入重審提示。"],
                ],
            ),
            "",
            "## Owner 待辦",
            "",
            markdown_table(["項目", "狀態", "Owner 要做什麼"], owner_rows),
            "",
            "## 報告使用規則",
            "",
            "- Launcher 負責資料更新、新聞 / FX 檢核與 Owner publish gate。",
            "- 新 UI 負責六大系統摘要與決策視野，不承擔正式 CSV 發布。",
            "- 舊 UI 只作 KPI 明細、來源稽核與戰報追溯。",
            "- 新聞與 FX sidecar 永遠不能直接改 HOLD 主 IC；只能觸發 OBSERVE / WATCH / REVIEW_REQUIRED。",
            "",
            f"_Generated at {generated_at}; tool={TOOL_VERSION}; productionCsvModified=false for report generation._",
        ]
    ) + "\n"


def report_svg_escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def report_chart_series(values: list[float], width: int, height: int, pad: int) -> list[tuple[float, float]]:
    if not values:
        return []
    vmin = min(values)
    vmax = max(values)
    span = vmax - vmin if vmax != vmin else 1.0
    usable_w = max(1, width - pad * 2)
    usable_h = max(1, height - pad * 2)
    points = []
    for idx, value in enumerate(values):
        x = pad + (usable_w * idx / max(1, len(values) - 1))
        y = pad + usable_h - ((value - vmin) / span * usable_h)
        points.append((x, y))
    return points


def report_polyline(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def report_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def report_price_pb_chart(daily_rows: list[dict[str, str]], chart_path: Path) -> dict[str, str] | None:
    rows = sort_by_date(daily_rows, reverse=False)[-12:]
    values_close = [finite_float(row, "Close") for row in rows]
    values_pb = [finite_float(row, "PB_daily") for row in rows]
    if sum(value is not None for value in values_close) < 4:
        return None
    close = [float(value) for value in values_close if value is not None]
    pb = [float(value) for value in values_pb if value is not None]
    labels = [row.get("Date", "")[5:] for row in rows if finite_float(row, "Close") is not None]
    width, height, pad = 920, 360, 56
    close_points = report_chart_series(close, width, height, pad)
    pb_points = report_chart_series(pb, width, height, pad) if len(pb) == len(close) else []
    axis = "\n".join(
        [
            f'<text x="{x:.1f}" y="{height - 22}" class="tick">{report_svg_escape(label)}</text>'
            for (x, _), label in zip(close_points, labels)
        ]
    )
    subtitle = f"{rows[0].get('Date', '')} to {rows[-1].get('Date', '')}; Close {report_num(close[-1], 1)}, PB {report_ratio(pb[-1] if pb else None)}"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <style>
    .bg{{fill:#0f1b2c}} .grid{{stroke:#274761;stroke-width:1;opacity:.65}} .axis{{stroke:#5f7894;stroke-width:1}}
    .title{{fill:#e8f3ff;font:700 22px Arial,'Microsoft JhengHei',sans-serif}} .sub{{fill:#9fb3c8;font:14px Arial,'Microsoft JhengHei',sans-serif}}
    .tick{{fill:#9fb3c8;font:12px Consolas,monospace;text-anchor:middle}} .label{{fill:#e8f3ff;font:700 14px Arial,'Microsoft JhengHei',sans-serif}}
  </style>
  <rect class="bg" x="0" y="0" width="{width}" height="{height}" rx="16"/>
  <text class="title" x="28" y="38">Price / PB 趨勢</text>
  <text class="sub" x="28" y="62">{report_svg_escape(subtitle)}</text>
  <line class="grid" x1="{pad}" y1="110" x2="{width-pad}" y2="110"/><line class="grid" x1="{pad}" y1="180" x2="{width-pad}" y2="180"/><line class="grid" x1="{pad}" y1="250" x2="{width-pad}" y2="250"/>
  <line class="axis" x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}"/>
  <polyline fill="none" stroke="#67e8f9" stroke-width="4" points="{report_polyline(close_points)}"/>
  {'<polyline fill="none" stroke="#ffd166" stroke-width="3" stroke-dasharray="7 7" points="' + report_polyline(pb_points) + '"/>' if pb_points else ''}
  {axis}
  <text class="label" x="{width-240}" y="42" fill="#67e8f9">Close</text>
  <text class="label" x="{width-160}" y="42" fill="#ffd166">PB</text>
</svg>
"""
    report_write_text(chart_path, svg)
    return {"title": "Price / PB 趨勢", "path": chart_path.name, "note": "最近 12 筆正式 daily price；Close 與 PB 用各自尺度顯示形狀。"}


def report_macro_band_chart(latest_macro: dict[str, str], latest_fx: dict[str, str], chart_path: Path) -> dict[str, str] | None:
    items = [
        ("USD/TWD", finite_float(latest_macro, "TWD_USD"), 30.0, 33.5, "匯率壓力"),
        ("DXY", finite_float(latest_macro, "DXY"), 95.0, 105.0, "美元強弱"),
        ("US10Y", finite_float(latest_macro, "US_10Y_Yield"), 3.0, 5.2, "利率壓力"),
        ("VIX", finite_float(latest_macro, "VIX"), 10.0, 30.0, "波動風險"),
        ("WTI", finite_float(latest_macro, "WTI_Oil"), 55.0, 90.0, "成本風險"),
    ]
    if not any(value is not None for _, value, _, _, _ in items):
        return None
    width, height = 920, 380
    rows = []
    y = 96
    for label, value, low, high, note in items:
        value_text = report_num(value, 3 if label in {"USD/TWD", "DXY", "US10Y"} else 2)
        pct = 0.5 if value is None else max(0.0, min(1.0, (value - low) / (high - low)))
        x = 260 + pct * 520
        rows.append(
            f"""<text x="36" y="{y+7}" class="label">{report_svg_escape(label)}</text>
  <text x="138" y="{y+7}" class="value">{report_svg_escape(value_text)}</text>
  <rect x="260" y="{y-12}" width="520" height="24" rx="7" fill="#123a31"/>
  <rect x="433" y="{y-12}" width="174" height="24" fill="#4a3e21" opacity=".85"/>
  <rect x="607" y="{y-12}" width="173" height="24" rx="7" fill="#482536" opacity=".8"/>
  <circle cx="{x:.1f}" cy="{y}" r="8" fill="#ffd166" stroke="#fff4c2" stroke-width="2"/>
  <text x="804" y="{y+7}" class="sub">{report_svg_escape(note)}</text>"""
        )
        y += 52
    subtitle = f"Date {latest_macro.get('Date', 'N/A')}; FX pressure {latest_fx.get('FxPressureLevel', 'N/A')}"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <style>
    .bg{{fill:#0f1b2c}} .title{{fill:#e8f3ff;font:700 22px Arial,'Microsoft JhengHei',sans-serif}} .sub{{fill:#9fb3c8;font:13px Arial,'Microsoft JhengHei',sans-serif}}
    .label{{fill:#e8f3ff;font:700 15px Arial,'Microsoft JhengHei',sans-serif}} .value{{fill:#f8fafc;font:700 16px Consolas,monospace}}
  </style>
  <rect class="bg" x="0" y="0" width="{width}" height="{height}" rx="16"/>
  <text class="title" x="28" y="38">總經 / FX 指標帶</text>
  <text class="sub" x="28" y="62">{report_svg_escape(subtitle)}</text>
  <text x="260" y="82" class="sub">支撐</text><text x="444" y="82" class="sub">觀察</text><text x="626" y="82" class="sub">警戒</text>
  {''.join(rows)}
</svg>
"""
    report_write_text(chart_path, svg)
    return {"title": "總經 / FX 指標帶", "path": chart_path.name, "note": "以固定監控區間顯示位置；不把 FX 或新聞直接轉成主 IC。"}


def report_news_distribution_chart(counts: dict[str, int], chart_path: Path) -> dict[str, str] | None:
    labels = ["REVIEW_REQUIRED", "WATCH", "OBSERVE"]
    values = [int(counts.get(label, 0) or 0) for label in labels]
    if not any(values):
        return None
    width, height = 920, 330
    max_value = max(values) or 1
    colors = {"REVIEW_REQUIRED": "#f390ca", "WATCH": "#ffe15b", "OBSERVE": "#a3befa"}
    rows = []
    y = 108
    for label, value in zip(labels, values):
        bar_w = 580 * value / max_value
        rows.append(
            f"""<text x="36" y="{y+16}" class="label">{report_svg_escape(label)}</text>
  <rect x="250" y="{y}" width="580" height="28" rx="8" fill="#17283e"/>
  <rect x="250" y="{y}" width="{bar_w:.1f}" height="28" rx="8" fill="{colors[label]}"/>
  <text x="{min(810, 266 + bar_w):.1f}" y="{y+19}" class="value">{value}</text>"""
        )
        y += 58
    total = sum(values)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <style>
    .bg{{fill:#0f1b2c}} .title{{fill:#e8f3ff;font:700 22px Arial,'Microsoft JhengHei',sans-serif}} .sub{{fill:#9fb3c8;font:13px Arial,'Microsoft JhengHei',sans-serif}}
    .label{{fill:#e8f3ff;font:700 14px Arial,'Microsoft JhengHei',sans-serif}} .value{{fill:#07111f;font:700 15px Consolas,monospace}}
  </style>
  <rect class="bg" x="0" y="0" width="{width}" height="{height}" rx="16"/>
  <text class="title" x="28" y="38">新聞事件等級分布</text>
  <text class="sub" x="28" y="62">主文只列高訊號；完整候選留在 NEWS_SCAN 稽核。Total={total}</text>
  {''.join(rows)}
</svg>
"""
    report_write_text(chart_path, svg)
    return {"title": "新聞事件等級分布", "path": chart_path.name, "note": "REVIEW_REQUIRED / WATCH / OBSERVE 統計，不代表買賣訊號。"}


def write_report_charts(package_root: Path, report_id: str, data: dict[str, Any]) -> list[dict[str, str]]:
    chart_dir = package_root / "reports/generated/charts"
    charts: list[dict[str, str]] = []
    price_chart = report_price_pb_chart(data.get("dailyRows", []), chart_dir / f"{report_id}_price_pb.svg")
    if price_chart:
        charts.append(price_chart)
    latest_macro = data.get("latestMacro") or {}
    latest_fx = latest(data.get("fxRows", []), "Date") or {}
    macro_chart = report_macro_band_chart(latest_macro, latest_fx, chart_dir / f"{report_id}_macro_fx.svg")
    if macro_chart:
        charts.append(macro_chart)
    events = report_event_rows(data)
    counts = report_event_counts(events)
    news_chart = report_news_distribution_chart(counts, chart_dir / f"{report_id}_news_distribution.svg")
    if news_chart:
        charts.append(news_chart)
    return charts


def append_chart_markdown(markdown: str, charts: list[dict[str, str]]) -> str:
    if not charts:
        return markdown + "\n## 圖表摘要\n\n- 圖表未產生：本機缺少足夠資料或圖表依賴。報告仍保留表格與文字判讀。\n"
    lines = [markdown.rstrip(), "", "## 圖表摘要", ""]
    for chart in charts:
        rel = f"charts/{chart['path']}"
        lines.append(f"![{chart['title']}]({rel})")
        lines.append(f"- {chart['note']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def chart_section_html(charts: list[dict[str, str]]) -> str:
    if not charts:
        return '<h2>圖表摘要</h2><p>圖表未產生：本機缺少足夠資料或圖表依賴。</p>'
    cards = ['<h2>圖表摘要</h2><div class="chart-grid">']
    for chart in charts:
        src = f"charts/{html.escape(chart['path'], quote=True)}"
        cards.append(
            f"""<figure class="chart-card">
  <img src="{src}" alt="{html.escape(chart['title'], quote=True)}" />
  <figcaption><strong>{html.escape(chart['title'])}</strong><br>{html.escape(chart['note'])}</figcaption>
</figure>"""
        )
    cards.append("</div>")
    return "\n".join(cards)


# Clean chart helpers for the active report renderer. These intentionally use
# inline SVG so generated reports work from file:// and do not depend on the
# old UI's Chart.js runtime.
def report_svg_escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def report_chart_series(values: list[float], width: int, height: int, pad: int) -> list[tuple[float, float]]:
    if not values:
        return []
    vmin = min(values)
    vmax = max(values)
    span = vmax - vmin if vmax != vmin else 1.0
    usable_w = max(1, width - pad * 2)
    usable_h = max(1, height - pad * 2)
    points: list[tuple[float, float]] = []
    for idx, value in enumerate(values):
        x = pad + (usable_w * idx / max(1, len(values) - 1))
        y = pad + usable_h - ((value - vmin) / span * usable_h)
        points.append((x, y))
    return points


def report_scaled_points(
    values: list[float],
    width: int,
    height: int,
    pad_x: int,
    pad_y: int,
    vmin: float,
    vmax: float,
) -> list[tuple[float, float]]:
    span = vmax - vmin if vmax != vmin else 1.0
    usable_w = max(1, width - pad_x * 2)
    usable_h = max(1, height - pad_y * 2)
    points: list[tuple[float, float]] = []
    for idx, value in enumerate(values):
        x = pad_x + (usable_w * idx / max(1, len(values) - 1))
        y = pad_y + usable_h - ((value - vmin) / span * usable_h)
        points.append((x, y))
    return points


def report_polyline(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def report_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def report_price_pb_chart(daily_rows: list[dict[str, str]], chart_path: Path) -> dict[str, str] | None:
    rows = sort_by_date(daily_rows, reverse=False)[-60:]
    clean_rows: list[tuple[str, float, float | None]] = []
    for row in rows:
        close_value = finite_float(row, "Close")
        if close_value is None:
            continue
        clean_rows.append((row.get("Date", ""), float(close_value), finite_float(row, "PB_daily")))
    if len(clean_rows) < 4:
        return None

    dates = [item[0] for item in clean_rows]
    closes = [item[1] for item in clean_rows]
    pb_values = [item[2] for item in clean_rows if item[2] is not None and item[2] > 0]
    latest_pb = pb_values[-1] if pb_values else None
    latest_close = closes[-1]
    bvps = latest_close / latest_pb if latest_pb else None

    width, height, pad_x, pad_y = 1040, 430, 66, 70
    band_values = [bvps * multiple for multiple in (1.6, 2.1, 2.3)] if bvps else []
    vmin = min(closes + band_values) * 0.96
    vmax = max(closes + band_values) * 1.04
    points = report_scaled_points(closes, width, height, pad_x, pad_y, vmin, vmax)

    def y_for(value: float) -> float:
        return pad_y + (height - pad_y * 2) - ((value - vmin) / (vmax - vmin if vmax != vmin else 1.0)) * (height - pad_y * 2)

    band_svg = ""
    if bvps:
        zones = [
            (vmin, bvps * 1.6, "rgba(39,140,103,.14)"),
            (bvps * 1.6, bvps * 2.1, "rgba(59,130,246,.13)"),
            (bvps * 2.1, bvps * 2.3, "rgba(245,158,11,.15)"),
            (bvps * 2.3, vmax, "rgba(244,63,94,.14)"),
        ]
        zone_rects = []
        for low, high, color in zones:
            top = y_for(min(high, vmax))
            bottom = y_for(max(low, vmin))
            if bottom > top:
                zone_rects.append(
                    f'<rect x="{pad_x}" y="{top:.1f}" width="{width - pad_x * 2}" height="{bottom - top:.1f}" fill="{color}"/>'
                )
        band_lines = []
        for multiple, tone in [(1.6, "#45d483"), (2.1, "#ffd166"), (2.3, "#f87171")]:
            value = bvps * multiple
            y = y_for(value)
            band_lines.append(
                f'<line x1="{pad_x}" y1="{y:.1f}" x2="{width - pad_x}" y2="{y:.1f}" class="band-line"/>'
                f'<text x="{width - pad_x + 10}" y="{y + 4:.1f}" fill="{tone}" class="axis-label">{multiple:.1f}x</text>'
            )
        band_svg = "\n  ".join(zone_rects + band_lines)

    label_indexes = sorted(set([0, len(dates) // 2, len(dates) - 1]))
    x_labels = "\n  ".join(
        f'<text x="{points[idx][0]:.1f}" y="{height - 24}" class="tick">{report_svg_escape(dates[idx][5:].replace("-", "/"))}</text>'
        for idx in label_indexes
        if 0 <= idx < len(points)
    )
    area_points = f"{points[0][0]:.1f},{height - pad_y:.1f} {report_polyline(points)} {points[-1][0]:.1f},{height - pad_y:.1f}"
    subtitle = (
        f"{dates[0]} 到 {dates[-1]}；Close {report_num(latest_close, 1)}"
        + (f"；PB {report_ratio(latest_pb)}；BVPS {report_num(bvps, 2)}" if bvps else "")
    )
    latest_x, latest_y = points[-1]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <style>
    .bg{{fill:#0f1b2c}} .plot{{fill:#0a1524;stroke:#2d5874;stroke-width:1}}
    .grid{{stroke:#274761;stroke-width:1;opacity:.55}} .band-line{{stroke:#dbeafe;stroke-width:1;stroke-dasharray:5 7;opacity:.72}}
    .title{{fill:#e8f3ff;font:800 24px Arial,'Microsoft JhengHei',sans-serif}} .sub{{fill:#9fb3c8;font:14px Arial,'Microsoft JhengHei',sans-serif}}
    .tick{{fill:#9fb3c8;font:12px Consolas,monospace;text-anchor:middle}} .axis-label{{font:800 13px Consolas,monospace}}
    .line{{fill:none;stroke:#67e8f9;stroke-width:4;stroke-linecap:round;stroke-linejoin:round}}
    .area{{fill:url(#priceFade);opacity:.72}} .dot{{fill:#f8fafc;stroke:#67e8f9;stroke-width:3}}
  </style>
  <defs>
    <linearGradient id="priceFade" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0%" stop-color="#67e8f9" stop-opacity=".28"/>
      <stop offset="75%" stop-color="#0ea5e9" stop-opacity=".06"/>
      <stop offset="100%" stop-color="#0ea5e9" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <rect class="bg" x="0" y="0" width="{width}" height="{height}" rx="18"/>
  <text class="title" x="28" y="38">價格 / PB River 趨勢</text>
  <text class="sub" x="28" y="64">{report_svg_escape(subtitle)}</text>
  <rect class="plot" x="{pad_x}" y="{pad_y}" width="{width - pad_x * 2}" height="{height - pad_y * 2}" rx="10"/>
  {band_svg}
  <line class="grid" x1="{pad_x}" y1="{pad_y + 72}" x2="{width - pad_x}" y2="{pad_y + 72}"/>
  <line class="grid" x1="{pad_x}" y1="{pad_y + 144}" x2="{width - pad_x}" y2="{pad_y + 144}"/>
  <line class="grid" x1="{pad_x}" y1="{pad_y + 216}" x2="{width - pad_x}" y2="{pad_y + 216}"/>
  <polygon class="area" points="{area_points}"/>
  <polyline class="line" points="{report_polyline(points)}"/>
  <circle class="dot" cx="{latest_x:.1f}" cy="{latest_y:.1f}" r="6"/>
  <text x="{max(pad_x + 10, latest_x - 150):.1f}" y="{max(pad_y + 22, latest_y - 16):.1f}" class="axis-label" fill="#e8f3ff">latest {report_num(latest_close, 1)}</text>
  {x_labels}
</svg>
"""
    report_write_text(chart_path, svg)
    return {
        "title": "價格 / PB River 趨勢",
        "path": chart_path.name,
        "note": "參考舊 UI PB River：用正式 daily price 顯示 Close，並以 BVPS 推估 1.6x / 2.1x / 2.3x 區間。",
    }


def report_macro_band_chart(latest_macro: dict[str, str], latest_fx: dict[str, str], chart_path: Path) -> dict[str, str] | None:
    items = [
        ("USD/TWD", finite_float(latest_macro, "TWD_USD"), 30.0, 33.5, "FX pressure"),
        ("DXY", finite_float(latest_macro, "DXY"), 95.0, 105.0, "美元指數"),
        ("US10Y", finite_float(latest_macro, "US_10Y_Yield"), 3.0, 5.2, "利率壓力"),
        ("VIX", finite_float(latest_macro, "VIX"), 10.0, 30.0, "風險情緒"),
        ("WTI", finite_float(latest_macro, "WTI_Oil"), 55.0, 90.0, "油價壓力"),
    ]
    if not any(value is not None for _, value, _, _, _ in items):
        return None
    width, height = 1040, 420
    rows_svg = []
    y = 112
    for label, value, low, high, note in items:
        value_text = report_num(value, 3 if label in {"USD/TWD", "DXY", "US10Y"} else 2)
        pct = 0.5 if value is None else max(0.0, min(1.0, (value - low) / (high - low)))
        x = 314 + pct * 560
        rows_svg.append(
            f"""<text x="36" y="{y+7}" class="label">{report_svg_escape(label)}</text>
  <text x="154" y="{y+7}" class="value">{report_svg_escape(value_text)}</text>
  <rect x="314" y="{y-14}" width="560" height="28" rx="8" fill="#123a31"/>
  <rect x="501" y="{y-14}" width="186" height="28" fill="#4a3e21" opacity=".88"/>
  <rect x="687" y="{y-14}" width="187" height="28" rx="8" fill="#482536" opacity=".84"/>
  <circle cx="{x:.1f}" cy="{y}" r="8" fill="#ffd166" stroke="#fff4c2" stroke-width="2"/>
  <text x="904" y="{y+7}" class="sub">{report_svg_escape(note)}</text>"""
        )
        y += 56
    subtitle = f"Date {latest_macro.get('Date', 'N/A')}；FX pressure {latest_fx.get('FxPressureLevel', 'N/A')}"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <style>
    .bg{{fill:#0f1b2c}} .title{{fill:#e8f3ff;font:800 24px Arial,'Microsoft JhengHei',sans-serif}} .sub{{fill:#9fb3c8;font:13px Arial,'Microsoft JhengHei',sans-serif}}
    .label{{fill:#e8f3ff;font:800 15px Arial,'Microsoft JhengHei',sans-serif}} .value{{fill:#f8fafc;font:800 16px Consolas,monospace}}
  </style>
  <rect class="bg" x="0" y="0" width="{width}" height="{height}" rx="18"/>
  <text class="title" x="28" y="38">總經 / FX 指標帶</text>
  <text class="sub" x="28" y="64">{report_svg_escape(subtitle)}</text>
  <text x="314" y="88" class="sub">支撐</text><text x="514" y="88" class="sub">觀察</text><text x="704" y="88" class="sub">警戒</text>
  {''.join(rows_svg)}
</svg>
"""
    report_write_text(chart_path, svg)
    return {
        "title": "總經 / FX 指標帶",
        "path": chart_path.name,
        "note": "沿用新 UI signal meter 的綠/黃/紅監控帶；FX 或新聞只作重審提示，不直接改主 IC。",
    }


def report_news_distribution_chart(counts: dict[str, int], chart_path: Path) -> dict[str, str] | None:
    labels = ["REVIEW_REQUIRED", "WATCH", "OBSERVE"]
    values = [int(counts.get(label, 0) or 0) for label in labels]
    if not any(values):
        return None
    width, height = 1040, 350
    max_value = max(values) or 1
    colors = {"REVIEW_REQUIRED": "#f390ca", "WATCH": "#ffe15b", "OBSERVE": "#a3befa"}
    rows_svg = []
    y = 116
    for label, value in zip(labels, values):
        bar_w = 620 * value / max_value
        rows_svg.append(
            f"""<text x="36" y="{y+18}" class="label">{report_svg_escape(label)}</text>
  <rect x="290" y="{y}" width="620" height="30" rx="8" fill="#17283e"/>
  <rect x="290" y="{y}" width="{bar_w:.1f}" height="30" rx="8" fill="{colors[label]}"/>
  <text x="{min(884, 306 + bar_w):.1f}" y="{y+21}" class="value">{value}</text>"""
        )
        y += 64
    total = sum(values)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <style>
    .bg{{fill:#0f1b2c}} .title{{fill:#e8f3ff;font:800 24px Arial,'Microsoft JhengHei',sans-serif}} .sub{{fill:#9fb3c8;font:13px Arial,'Microsoft JhengHei',sans-serif}}
    .label{{fill:#e8f3ff;font:800 14px Arial,'Microsoft JhengHei',sans-serif}} .value{{fill:#07111f;font:900 15px Consolas,monospace}}
  </style>
  <rect class="bg" x="0" y="0" width="{width}" height="{height}" rx="18"/>
  <text class="title" x="28" y="38">新聞事件等級分布</text>
  <text class="sub" x="28" y="64">日報只摘要高訊號事件；完整 45+ 清單保留在 NEWS_SCAN 稽核。Total={total}</text>
  {''.join(rows_svg)}
</svg>
"""
    report_write_text(chart_path, svg)
    return {
        "title": "新聞事件等級分布",
        "path": chart_path.name,
        "note": "統計 REVIEW_REQUIRED / WATCH / OBSERVE，協助去噪；不代表交易建議。",
    }


def append_chart_markdown(markdown: str, charts: list[dict[str, str]]) -> str:
    if not charts:
        return markdown.rstrip() + "\n\n## 圖表摘要\n\n- 本期沒有足夠資料產生圖表；請回 Launcher 檢查 CSV 與 runtime 狀態。\n"
    lines = [markdown.rstrip(), "", "## 圖表摘要", ""]
    for chart in charts:
        rel = f"charts/{chart['path']}"
        lines.append(f"![{chart['title']}]({rel})")
        lines.append(f"- {chart['note']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def chart_section_html(charts: list[dict[str, str]]) -> str:
    if not charts:
        return ""
    cards = ['<h2>圖表摘要</h2><div class="chart-grid">']
    for chart in charts:
        src = f"charts/{html.escape(chart['path'], quote=True)}"
        cards.append(
            f"""<figure class="chart-card">
  <img src="{src}" alt="{html.escape(chart['title'], quote=True)}" />
  <figcaption><strong>{html.escape(chart['title'])}</strong><br>{html.escape(chart['note'])}</figcaption>
</figure>"""
        )
    cards.append("</div>")
    return "\n".join(cards)


def report_markdown_to_html(markdown: str) -> str:
    parts: list[str] = []
    lines = markdown.splitlines()
    i = 0
    in_list = False
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            if in_list:
                parts.append("</ul>")
                in_list = False
            i += 1
            continue
        if stripped.startswith("|"):
            if in_list:
                parts.append("</ul>")
                in_list = False
            table_lines: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            rows: list[list[str]] = []
            for table_line in table_lines:
                cells = [cell.strip() for cell in table_line.strip("|").split("|")]
                if cells and all(set(cell) <= {"-", " "} for cell in cells):
                    continue
                rows.append(cells)
            if rows:
                parts.append("<div class=\"table-wrap\"><table><thead><tr>")
                parts.extend(f"<th>{html.escape(cell)}</th>" for cell in rows[0])
                parts.append("</tr></thead><tbody>")
                for row in rows[1:]:
                    parts.append("<tr>")
                    parts.extend(f"<td>{html.escape(cell)}</td>" for cell in row)
                    parts.append("</tr>")
                parts.append("</tbody></table></div>")
            continue
        if stripped.startswith("# "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h1>{html.escape(stripped[2:])}</h1>")
        elif stripped.startswith("## "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h2>{html.escape(stripped[3:])}</h2>")
        elif stripped.startswith("![") and "](" in stripped and stripped.endswith(")"):
            if in_list:
                parts.append("</ul>")
                in_list = False
            alt = stripped[2:stripped.index("](")]
            src = stripped[stripped.index("](") + 2:-1]
            parts.append(
                f'<figure class="chart-card"><img src="{html.escape(src, quote=True)}" alt="{html.escape(alt, quote=True)}" />'
                f'<figcaption>{html.escape(alt)}</figcaption></figure>'
            )
        elif stripped.startswith("- "):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{html.escape(stripped[2:])}</li>")
        else:
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<p>{html.escape(stripped)}</p>")
        i += 1
    if in_list:
        parts.append("</ul>")
    return "\n".join(parts)


def write_report_html(path: Path, report_id: str, title: str, markdown: str) -> None:
    body_html = report_markdown_to_html(markdown)
    viewer_href = f"../../report_viewer.html?id={html.escape(report_id)}"
    body = f"""<!doctype html>
<html lang="zh-TW">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: dark; --bg:#07111f; --panel:#0f1b2c; --line:#274761; --text:#e8f3ff; --muted:#9fb3c8; --warn:#ffd166; --cyan:#67e8f9; }}
    body {{ margin:0; background:linear-gradient(180deg,#06101d,#081827 48%,#050b13); color:var(--text); font-family:Arial,'Microsoft JhengHei',sans-serif; }}
    main {{ max-width:1180px; margin:0 auto; padding:28px 18px 54px; }}
    .nav {{ display:flex; flex-wrap:wrap; gap:10px; margin-bottom:16px; }}
    .nav a, .nav button {{ color:var(--cyan); text-decoration:none; border:1px solid var(--line); border-radius:8px; padding:8px 12px; background:#0b1626; font-weight:700; font:inherit; cursor:pointer; }}
    .nav button:disabled {{ opacity:.48; cursor:not-allowed; }}
    .nav button[aria-pressed="true"] {{ border-color:rgba(52,211,153,.62); color:#a7f3d0; background:rgba(6,78,59,.35); }}
    h1 {{ font-size:30px; margin:10px 0 18px; letter-spacing:0; }}
    h2 {{ font-size:20px; margin:26px 0 12px; color:#f8fafc; border-left:4px solid var(--warn); padding-left:10px; }}
    p, ul, .table-wrap {{ background:rgba(15,27,44,.82); border:1px solid rgba(80,128,166,.42); border-radius:10px; }}
    p {{ padding:12px 14px; line-height:1.65; }}
    ul {{ padding:12px 18px 12px 34px; line-height:1.75; }}
    li {{ margin:4px 0; }}
    code {{ color:#fef08a; }}
    .table-wrap {{ overflow:auto; margin:12px 0 18px; }}
    table {{ width:100%; border-collapse:collapse; min-width:760px; }}
    th, td {{ padding:10px 12px; border-bottom:1px solid rgba(80,128,166,.32); text-align:left; vertical-align:top; line-height:1.5; }}
    th {{ color:#b6e7ff; font-size:12px; text-transform:uppercase; letter-spacing:.03em; background:rgba(19,37,59,.9); }}
    td {{ color:#e8f3ff; font-size:14px; }}
    tr:last-child td {{ border-bottom:0; }}
    @media (max-width:760px) {{ main {{ padding:18px 10px 36px; }} h1 {{ font-size:24px; }} table {{ min-width:680px; }} }}
  </style>
</head>
<body>
  <main>
    <div class="nav">
      <a href="{viewer_href}">研報庫閱讀器</a>
      <a href="../../reports.html?from=report">返回研報庫</a>
      <a href="../../launcher.html?stay=1">返回 Launcher</a>
    </div>
    {body_html}
  </main>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")


def build_report(args: argparse.Namespace) -> int:
    package_root = Path(args.package_root).resolve()
    generated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    report_date = args.date or datetime.now().strftime("%Y-%m-%d")
    period = args.period

    daily_rows, daily_issues = read_csv_rows(package_root / "data/2317_daily_price.csv", DAILY_COLUMNS)
    macro_rows, macro_issues = read_csv_rows(package_root / "data/macro_snapshot.csv", MACRO_COLUMNS)
    master_rows, master_issues = read_csv_rows(package_root / "data/2317_master_v9.csv")
    event_rows, event_issues = read_csv_rows(package_root / "data/macro_event_observations.csv", MACRO_EVENT_COLUMNS)
    fx_rows, fx_issues = read_csv_rows(package_root / "data/fx_trend_observations.csv", FX_TREND_COLUMNS)
    news_scan = read_json(package_root / "runtime/warroom_news_scan_snapshot.json", default={}) or {}
    app_state = read_json(package_root / "runtime/p1008_app_state.json", default={}) or {}
    owner_log_path = package_root / "logs/last_owner_publish_review.log"
    owner_log_tail = ""
    if owner_log_path.exists():
        owner_log_tail = "\n".join(owner_log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-24:])

    review_state = build_event_review_state(package_root, news_scan, generated_at)
    data = {
        "dailyRows": daily_rows,
        "macroRows": macro_rows,
        "masterRows": master_rows,
        "eventRows": event_rows,
        "fxRows": fx_rows,
        "latestDaily": latest(daily_rows, "Date"),
        "latestMacro": latest(macro_rows, "Date"),
        "latestMaster": latest(master_rows, "Quarter"),
        "newsScan": news_scan,
        "appState": app_state,
        "reviewState": review_state,
        "ownerLogTail": owner_log_tail,
    }

    report_id = f"P1008_{period.upper()}_REPORT_{report_date.replace('-', '')}"
    period_zh = report_period_zh(period)
    title = f"P1008 {period_zh} {report_date}"
    report_dir = package_root / "reports/generated"
    md_rel = f"generated/{report_id}.md"
    html_rel = f"generated/{report_id}.html"
    md_path = report_dir / f"{report_id}.md"
    html_path = report_dir / f"{report_id}.html"
    latest_html_path = report_dir / "latest_report.html"
    markdown = build_report_markdown(period, report_date, generated_at, data)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown, encoding="utf-8", newline="\n")
    write_report_html(html_path, report_id, title, markdown)
    write_report_html(latest_html_path, report_id, title, markdown)

    issues = daily_issues + macro_issues + master_issues + event_issues + fx_issues
    report = {
        "id": report_id,
        "period": period,
        "date": report_date,
        "title": title,
        "tags": [period_zh, "每日戰報", "六大系統摘要", "actionable:false"],
        "md": md_rel,
        "html": html_rel,
        "source": TOOL_VERSION,
        "actionable": False,
        "productionCsvModified": False,
        "status": "GENERATED_WITH_WARNINGS" if issues else "GENERATED",
        "issues": issues,
        "eventReviewState": EVENT_REVIEW_STATE,
    }
    manifest = update_report_manifest(package_root, report, generated_at)

    log(f"Report markdown: {md_path}")
    log(f"Report html: {html_path}")
    log(f"Latest direct html: {latest_html_path}")
    log(f"Report manifest: {package_root / REPORT_MANIFEST}")
    log(f"Runtime report manifest: {package_root / RUNTIME_REPORT_MANIFEST}")
    log(f"Reports in manifest: {len(manifest.get('reports', []))}")
    log("Formal CSV modified: NO")
    return 0


def write_report_html(path: Path, report_id: str, title: str, markdown: str) -> None:
    body_html = report_markdown_to_html(markdown)
    viewer_href = f"../../report_viewer.html?id={html.escape(report_id)}"
    body = f"""<!doctype html>
<html lang="zh-TW">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: dark; --bg:#07111f; --panel:#0f1b2c; --line:#274761; --text:#e8f3ff; --muted:#9fb3c8; --warn:#ffd166; --cyan:#67e8f9; }}
    body {{ margin:0; background:linear-gradient(180deg,#06101d,#081827 48%,#050b13); color:var(--text); font-family:Arial,'Microsoft JhengHei',sans-serif; }}
    main {{ max-width:1180px; margin:0 auto; padding:28px 18px 54px; }}
    .nav {{ display:flex; flex-wrap:wrap; gap:10px; margin-bottom:16px; }}
    .nav a {{ color:var(--cyan); text-decoration:none; border:1px solid var(--line); border-radius:8px; padding:8px 12px; background:#0b1626; font-weight:700; }}
    h1 {{ font-size:30px; margin:10px 0 18px; letter-spacing:0; }}
    h2 {{ font-size:20px; margin:26px 0 12px; color:#f8fafc; border-left:4px solid var(--warn); padding-left:10px; }}
    p, ul, .table-wrap {{ background:rgba(15,27,44,.82); border:1px solid rgba(80,128,166,.42); border-radius:10px; }}
    p {{ padding:12px 14px; line-height:1.65; }}
    ul {{ padding:12px 18px 12px 34px; line-height:1.75; }}
    li {{ margin:4px 0; }}
    code {{ color:#fef08a; }}
    .table-wrap {{ overflow:auto; margin:12px 0 18px; }}
    table {{ width:100%; border-collapse:collapse; min-width:760px; }}
    th, td {{ padding:10px 12px; border-bottom:1px solid rgba(80,128,166,.32); text-align:left; vertical-align:top; line-height:1.5; }}
    th {{ color:#b6e7ff; font-size:12px; text-transform:uppercase; letter-spacing:.03em; background:rgba(19,37,59,.9); }}
    td {{ color:#e8f3ff; font-size:14px; }}
    tr:last-child td {{ border-bottom:0; }}
    .chart-card {{ margin:14px 0 20px; background:rgba(15,27,44,.92); border:1px solid rgba(80,128,166,.46); border-radius:12px; padding:14px; }}
    .chart-card img {{ display:block; width:100%; height:auto; border-radius:10px; background:#0f1b2c; }}
    .chart-card figcaption {{ color:var(--muted); font-size:13px; line-height:1.55; margin-top:8px; }}
    :fullscreen {{ background:#07111f; }}
    body.p1008-focus-mode {{ background:#07111f; }}
    body.p1008-focus-mode main {{ max-width:none; min-height:100vh; }}
    @media (max-width:760px) {{ main {{ padding:18px 10px 36px; }} h1 {{ font-size:24px; }} table {{ min-width:680px; }} }}
  </style>
  <script>
    const P1008_IMMERSIVE_KEY = "p1008_immersive_mode";
    function readImmersivePref() {{
      try {{ return localStorage.getItem(P1008_IMMERSIVE_KEY) === "1"; }} catch (err) {{ return false; }}
    }}
    function writeImmersivePref(active) {{
      try {{ localStorage.setItem(P1008_IMMERSIVE_KEY, active ? "1" : "0"); }} catch (err) {{}}
    }}
    function immersiveRequested() {{
      return new URLSearchParams(window.location.search).get("fs") === "1" || readImmersivePref();
    }}
    function immersiveActive() {{
      return document.body.classList.contains("p1008-focus-mode") || immersiveRequested();
    }}
    function withImmersive(href) {{
      const url = new URL(href, window.location.href);
      if (immersiveActive()) url.searchParams.set("fs", "1");
      else url.searchParams.delete("fs");
      return url.href;
    }}
    function syncImmersiveLinks() {{
      document.querySelectorAll("a[href]").forEach((link) => {{
        const raw = link.getAttribute("href");
        if (!raw || /^(#|mailto:|tel:|javascript:)/i.test(raw)) return;
        const url = new URL(raw, window.location.href);
        if (url.protocol === window.location.protocol && url.host === window.location.host) {{
          link.setAttribute("href", withImmersive(raw));
        }}
      }});
    }}
    async function toggleFullscreen() {{
      const next = !document.body.classList.contains("p1008-focus-mode");
      if (!next && document.fullscreenElement) {{
        try {{ await document.exitFullscreen(); }} catch (err) {{}}
      }}
      document.body.classList.toggle("p1008-focus-mode", next);
      writeImmersivePref(next);
      syncImmersiveLinks();
      updateFullscreenButton();
    }}
    function updateFullscreenButton() {{
      const btn = document.getElementById("fullscreen-toggle");
      if (!btn) return;
      const active = Boolean(document.body.classList.contains("p1008-focus-mode") || document.fullscreenElement);
      btn.disabled = false;
      btn.textContent = active ? "退出全螢幕" : "全螢幕";
      btn.setAttribute("aria-pressed", active ? "true" : "false");
      btn.title = "切換戰情室沉浸模式；內部跳轉會保持此狀態";
    }}
    document.addEventListener("click", (event) => {{
      const link = event.target.closest?.("a[href]");
      if (!link) return;
      const raw = link.getAttribute("href");
      if (!raw || /^(#|mailto:|tel:|javascript:)/i.test(raw)) return;
      const url = new URL(raw, window.location.href);
      if (url.protocol === window.location.protocol && url.host === window.location.host) {{
        link.setAttribute("href", withImmersive(raw));
      }}
    }}, true);
    document.addEventListener("fullscreenchange", updateFullscreenButton);
    document.addEventListener("DOMContentLoaded", () => {{
      if (immersiveRequested()) document.body.classList.add("p1008-focus-mode");
      syncImmersiveLinks();
      updateFullscreenButton();
    }});
  </script>
</head>
<body>
  <main>
    <div class="nav">
      <button id="fullscreen-toggle" type="button" onclick="toggleFullscreen()" aria-pressed="false">全螢幕</button>
      <a href="{viewer_href}">開啟報告 Viewer</a>
      <a href="../../reports.html?from=report">回研報庫</a>
      <a href="../../launcher.html?stay=1">回 Launcher</a>
    </div>
    {body_html}
  </main>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")


def build_report(args: argparse.Namespace) -> int:
    package_root = Path(args.package_root).resolve()
    generated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    report_date = args.date or datetime.now().strftime("%Y-%m-%d")
    period = args.period

    daily_rows, daily_issues = read_csv_rows(package_root / "data/2317_daily_price.csv", DAILY_COLUMNS)
    macro_rows, macro_issues = read_csv_rows(package_root / "data/macro_snapshot.csv", MACRO_COLUMNS)
    master_rows, master_issues = read_csv_rows(package_root / "data/2317_master_v9.csv")
    event_rows, event_issues = read_csv_rows(package_root / "data/macro_event_observations.csv", MACRO_EVENT_COLUMNS)
    fx_rows, fx_issues = read_csv_rows(package_root / "data/fx_trend_observations.csv", FX_TREND_COLUMNS)
    news_scan = read_json(package_root / "runtime/warroom_news_scan_snapshot.json", default={}) or {}
    app_state = read_json(package_root / "runtime/p1008_app_state.json", default={}) or {}
    owner_log_path = package_root / "logs/last_owner_publish_review.log"
    owner_log_tail = ""
    if owner_log_path.exists():
        owner_log_tail = "\n".join(owner_log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-24:])

    review_state = build_event_review_state(package_root, news_scan, generated_at)
    data = {
        "dailyRows": daily_rows,
        "macroRows": macro_rows,
        "masterRows": master_rows,
        "eventRows": event_rows,
        "fxRows": fx_rows,
        "latestDaily": latest(daily_rows, "Date"),
        "latestMacro": latest(macro_rows, "Date"),
        "latestMaster": latest(master_rows, "Quarter"),
        "newsScan": news_scan,
        "appState": app_state,
        "reviewState": review_state,
        "ownerLogTail": owner_log_tail,
    }

    report_id = f"P1008_{period.upper()}_REPORT_{report_date.replace('-', '')}"
    period_zh = report_period_zh(period)
    title = f"P1008 {period_zh} {report_date}"
    report_dir = package_root / "reports/generated"
    md_rel = f"generated/{report_id}.md"
    html_rel = f"generated/{report_id}.html"
    md_path = report_dir / f"{report_id}.md"
    html_path = report_dir / f"{report_id}.html"
    latest_html_path = report_dir / "latest_report.html"
    charts = write_report_charts(package_root, report_id, data)
    markdown = build_report_markdown(period, report_date, generated_at, data)
    markdown = append_chart_markdown(markdown, charts)
    shadow_candidate = read_shadow_candidate(package_root, report_date)
    markdown = append_shadow_candidate(markdown, shadow_candidate)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown, encoding="utf-8", newline="\n")
    write_report_html(html_path, report_id, title, markdown)
    write_report_html(latest_html_path, report_id, title, markdown)

    issues = daily_issues + macro_issues + master_issues + event_issues + fx_issues
    report = {
        "id": report_id,
        "period": period,
        "date": report_date,
        "title": title,
        "tags": [period_zh, "戰報", "新聞去噪", "圖表", "actionable:false"],
        "md": md_rel,
        "html": html_rel,
        "charts": [f"generated/charts/{chart['path']}" for chart in charts],
        "source": TOOL_VERSION,
        "actionable": False,
        "productionCsvModified": False,
        "status": "GENERATED_WITH_WARNINGS" if issues else "GENERATED",
        "issues": issues,
        "eventReviewState": EVENT_REVIEW_STATE,
        "pluginShadowCandidate": (
            PLUGIN_SHADOW_CANDIDATE if shadow_candidate is not None else ""
        ),
    }
    manifest = update_report_manifest(package_root, report, generated_at)

    log(f"Report markdown: {md_path}")
    log(f"Report html: {html_path}")
    log(f"Latest direct html: {latest_html_path}")
    log(f"Report manifest: {package_root / REPORT_MANIFEST}")
    log(f"Runtime report manifest: {package_root / RUNTIME_REPORT_MANIFEST}")
    log(f"Reports in manifest: {len(manifest.get('reports', []))}")
    log("Formal CSV modified: NO")
    return 0


def report_eps_pb_chart(master_rows: list[dict[str, str]], chart_path: Path) -> dict[str, str] | None:
    rows = sorted(master_rows, key=lambda row: row.get("QuarterEndDate") or row.get("Quarter") or "")[-12:]
    clean_rows: list[tuple[str, float, float | None]] = []
    for row in rows:
        eps_value = finite_float(row, "EPS_Q")
        if eps_value is None:
            continue
        clean_rows.append((row.get("Quarter", ""), float(eps_value), finite_float(row, "PB_QuarterEnd")))
    if len(clean_rows) < 4:
        return None

    labels = [item[0] for item in clean_rows]
    eps_values = [item[1] for item in clean_rows]
    pb_values = [item[2] for item in clean_rows if item[2] is not None]
    width, height, pad_x, pad_y = 1040, 400, 66, 70
    plot_w = width - pad_x * 2
    plot_h = height - pad_y * 2
    eps_min = min(0.0, min(eps_values)) * 1.15
    eps_max = max(0.1, max(eps_values)) * 1.15
    eps_span = eps_max - eps_min if eps_max != eps_min else 1.0

    def eps_y(value: float) -> float:
        return pad_y + plot_h - ((value - eps_min) / eps_span) * plot_h

    bar_gap = 8
    bar_w = max(18, (plot_w / len(clean_rows)) - bar_gap)
    zero_y = eps_y(0.0)
    bars = []
    for idx, (_, eps, _) in enumerate(clean_rows):
        x = pad_x + idx * (plot_w / len(clean_rows)) + bar_gap / 2
        y = eps_y(max(eps, 0.0))
        h = abs(eps_y(eps) - zero_y)
        color = "#38bdf8" if eps >= 0 else "#f87171"
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(2, h):.1f}" rx="5" fill="{color}" opacity=".86"/>')

    pb_line = ""
    if len(pb_values) >= 4:
        pb_by_row = [item[2] for item in clean_rows]
        pb_valid = [value for value in pb_by_row if value is not None]
        pb_min = min(pb_valid) * 0.96
        pb_max = max(pb_valid) * 1.04
        pb_span = pb_max - pb_min if pb_max != pb_min else 1.0
        points = []
        for idx, value in enumerate(pb_by_row):
            if value is None:
                continue
            x = pad_x + idx * (plot_w / max(1, len(clean_rows) - 1))
            y = pad_y + plot_h - ((value - pb_min) / pb_span) * plot_h
            points.append((x, y))
        pb_line = (
            f'<polyline fill="none" stroke="#f59e0b" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" points="{report_polyline(points)}"/>'
            f'<text x="{width - pad_x - 154}" y="48" class="legend" fill="#f59e0b">PB_QuarterEnd</text>'
        )

    tick_indexes = sorted(set([0, len(labels) // 2, len(labels) - 1]))
    ticks = "\n  ".join(
        f'<text x="{pad_x + idx * (plot_w / max(1, len(clean_rows) - 1)):.1f}" y="{height - 24}" class="tick">{report_svg_escape(labels[idx])}</text>'
        for idx in tick_indexes
    )
    subtitle = f"{labels[0]} 到 {labels[-1]}；latest EPS_Q {report_num(eps_values[-1], 2)}"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <style>
    .bg{{fill:#0f1b2c}} .plot{{fill:#0a1524;stroke:#2d5874;stroke-width:1}}
    .grid{{stroke:#274761;stroke-width:1;opacity:.55}} .zero{{stroke:#e8f3ff;stroke-width:1;opacity:.45}}
    .title{{fill:#e8f3ff;font:800 24px Arial,'Microsoft JhengHei',sans-serif}} .sub{{fill:#9fb3c8;font:14px Arial,'Microsoft JhengHei',sans-serif}}
    .tick{{fill:#9fb3c8;font:12px Consolas,monospace;text-anchor:middle}} .legend{{font:800 14px Arial,'Microsoft JhengHei',sans-serif}}
  </style>
  <rect class="bg" x="0" y="0" width="{width}" height="{height}" rx="18"/>
  <text class="title" x="28" y="38">EPS / PB 季度趨勢</text>
  <text class="sub" x="28" y="64">{report_svg_escape(subtitle)}</text>
  <text x="{width - pad_x - 292}" y="48" class="legend" fill="#38bdf8">EPS_Q</text>
  {pb_line}
  <rect class="plot" x="{pad_x}" y="{pad_y}" width="{plot_w}" height="{plot_h}" rx="10"/>
  <line class="grid" x1="{pad_x}" y1="{pad_y + 72}" x2="{width - pad_x}" y2="{pad_y + 72}"/>
  <line class="grid" x1="{pad_x}" y1="{pad_y + 144}" x2="{width - pad_x}" y2="{pad_y + 144}"/>
  <line class="zero" x1="{pad_x}" y1="{zero_y:.1f}" x2="{width - pad_x}" y2="{zero_y:.1f}"/>
  {''.join(bars)}
  {ticks}
</svg>
"""
    report_write_text(chart_path, svg)
    return {
        "title": "EPS / PB 季度趨勢",
        "path": chart_path.name,
        "note": "轉調舊 UI BacktestModule：EPS_Q 用長條、PB_QuarterEnd 用折線，協助判斷估值是否有基本面支撐。",
    }


def write_report_charts(package_root: Path, report_id: str, data: dict[str, Any]) -> list[dict[str, str]]:
    chart_dir = package_root / "reports/generated/charts"
    charts: list[dict[str, str]] = []
    price_chart = report_price_pb_chart(data.get("dailyRows", []), chart_dir / f"{report_id}_price_pb.svg")
    if price_chart:
        charts.append(price_chart)
    eps_pb_chart = report_eps_pb_chart(data.get("masterRows", []), chart_dir / f"{report_id}_eps_pb.svg")
    if eps_pb_chart:
        charts.append(eps_pb_chart)
    latest_macro = data.get("latestMacro") or {}
    latest_fx = latest(data.get("fxRows", []), "Date") or {}
    macro_chart = report_macro_band_chart(latest_macro, latest_fx, chart_dir / f"{report_id}_macro_fx.svg")
    if macro_chart:
        charts.append(macro_chart)
    events = report_event_rows(data)
    counts = report_event_counts(events)
    news_chart = report_news_distribution_chart(counts, chart_dir / f"{report_id}_news_distribution.svg")
    if news_chart:
        charts.append(news_chart)
    return charts


def report_human_actionable(value: Any = None) -> str:
    return "否，僅作觀察與重審提示，不輸出買賣或自動改主 IC"


def report_sync_text(pending_reviews: list[Any], formal_synced: bool) -> str:
    if pending_reviews:
        return f"仍有 {len(pending_reviews)} 筆事件待 Owner 審查，請留在 Launcher 處理。"
    if formal_synced:
        return "已完成：無待審事件，新聞 / FX 旁路已同步正式 CSV。"
    return "尚未同步：可進新 UI 前，請先確認 Launcher 是否仍有候選資料。"


def report_event_rows(data: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add_candidate(row: dict[str, Any], event: dict[str, Any] | None = None) -> None:
        event = event or {}
        rows.append(
            {
                "Date": str(row.get("Date") or event.get("publishedAt") or ""),
                "Title": str(row.get("EventTitle") or event.get("title") or ""),
                "SourceTier": str(row.get("SourceTier") or event.get("sourceTier") or ""),
                "SourceName": str(row.get("SourceName") or event.get("sourceName") or ""),
                "RiskTag": str(row.get("RiskTag") or event.get("riskTag") or event.get("relevanceTag") or ""),
                "Level": str(row.get("BlackSwanLevel") or event.get("level") or ""),
                "Actionable": str(row.get("Actionable", "false")),
                "Url": str(row.get("SourceUrl") or event.get("url") or ""),
                "Summary": str(row.get("SummaryZh") or event.get("summaryZh") or ""),
            }
        )

    for row in data.get("eventRows", []) or []:
        add_candidate(row)
    for event in ((data.get("newsScan") or {}).get("events", []) or []):
        add_candidate(event.get("candidateRow", {}) or {}, event)

    deduped: dict[str, dict[str, str]] = {}
    for row in rows:
        title = report_clean_label(row.get("Title"), "")
        url = (row.get("Url") or "").strip().lower()
        date = (row.get("Date") or "").strip()
        source = (row.get("SourceName") or row.get("SourceTier") or "").strip().lower()
        key = f"{date}|{source}|{title[:120].lower()}" if title else f"{date}|{source}|{url}"
        if key and key not in deduped:
            deduped[key] = row
    return list(deduped.values())


def report_event_text(row: dict[str, str]) -> str:
    title = report_clean_label(row.get("Title"), "未命名事件")
    return report_compact(title, 86)


def report_event_score(row: dict[str, str]) -> int:
    text = " ".join([row.get("Title", ""), row.get("RiskTag", ""), row.get("SourceName", ""), row.get("Summary", "")]).lower()
    score = 0
    title = report_clean_label(row.get("Title"), "").strip().lower()
    url = (row.get("Url") or "").lower()
    if title in {"全文搜尋", "search", "search result", "搜尋結果"} or "/search/" in url or "search_type=" in url:
        score -= 70
    if row.get("SourceTier", "").upper() == "OFFICIAL":
        score += 30
    if row.get("Level", "").upper() == "REVIEW_REQUIRED":
        score += 25
    elif row.get("Level", "").upper() == "WATCH":
        score += 10
    if any(term in text for term in ["營收", "6月", "六月", "revenue", "sales", "8218", "8,218", "第2季", "上半年"]):
        score += 80
    if any(term in text for term in ["鴻海", "hon hai", "foxconn", "2317"]):
        score += 40
    if any(term in text for term in ["csp", "capex", "data center", "datacenter", "server", "gpu", "blackwell", "gb200", "gb300", "azure", "aws", "google", "meta", "oracle", "coreweave", "nvidia", "ai server"]):
        score += 30
    if any(term in text for term in ["fed", "dxy", "us10y", "wti", "cpi", "美元", "利率"]):
        score += 12
    if report_mojibake(row.get("Title")):
        score -= 12
    return score


def report_event_focus(row: dict[str, str]) -> str:
    text = " ".join([row.get("Title", ""), row.get("RiskTag", ""), row.get("Summary", "")]).lower()
    if any(term in text for term in ["營收", "6月", "六月", "revenue", "sales", "8218", "8,218", "第2季", "上半年"]):
        return "直接關聯營收動能：確認 AI 機櫃、ICT 旺季與 Q3 展望是否支撐 EPS / ROE 假設。"
    if any(term in text for term in ["鴻海", "hon hai", "foxconn", "2317"]):
        return "直接關聯鴻海：檢查是否改變營收、毛利、出貨或供應鏈 KPI 假設。"
    if any(term in text for term in ["csp", "capex", "data center", "datacenter", "server", "gpu", "blackwell", "gb200", "gb300", "azure", "aws", "google", "meta", "oracle", "coreweave", "nvidia", "ai server"]):
        return "AI server 需求訊號：判斷是否支撐鴻海 CSP 客戶訂單與出貨假設。"
    if any(term in text for term in ["fed", "dxy", "us10y", "wti", "cpi", "美元", "利率"]):
        return "總經 / FX 風險提示：只作重審觸發，不直接改主 IC。"
    return "低訊號事件：保留稽核，不放大為決策結論。"


def report_eps_pb_chart(master_rows: list[dict[str, str]], chart_path: Path) -> dict[str, str] | None:
    rows = sorted(master_rows, key=lambda row: row.get("QuarterEndDate") or row.get("Quarter") or "")[-12:]
    clean_rows: list[tuple[str, float, float | None]] = []
    for row in rows:
        eps_value = finite_float(row, "EPS_Q")
        if eps_value is None:
            continue
        clean_rows.append((row.get("Quarter", ""), float(eps_value), finite_float(row, "PB_QuarterEnd")))
    if len(clean_rows) < 4:
        return None

    labels = [item[0] for item in clean_rows]
    eps_values = [item[1] for item in clean_rows]
    pb_by_row = [item[2] for item in clean_rows]
    pb_valid = [value for value in pb_by_row if value is not None]
    width, height, pad_x, pad_y = 1040, 400, 66, 70
    plot_w = width - pad_x * 2
    plot_h = height - pad_y * 2
    eps_min = min(0.0, min(eps_values)) * 1.15
    eps_max = max(0.1, max(eps_values)) * 1.15
    eps_span = eps_max - eps_min if eps_max != eps_min else 1.0

    def eps_y(value: float) -> float:
        return pad_y + plot_h - ((value - eps_min) / eps_span) * plot_h

    bar_gap = 8
    bar_w = max(18, (plot_w / len(clean_rows)) - bar_gap)
    zero_y = eps_y(0.0)
    bars = []
    for idx, (_, eps, _) in enumerate(clean_rows):
        x = pad_x + idx * (plot_w / len(clean_rows)) + bar_gap / 2
        y = eps_y(max(eps, 0.0))
        h = abs(eps_y(eps) - zero_y)
        color = "#38bdf8" if eps >= 0 else "#f87171"
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(2, h):.1f}" rx="5" fill="{color}" opacity=".72"/>')

    pb_line = ""
    if len(pb_valid) >= 4:
        pb_min = min(pb_valid) * 0.96
        pb_max = max(pb_valid) * 1.04
        pb_span = pb_max - pb_min if pb_max != pb_min else 1.0
        points = []
        dots = []
        for idx, value in enumerate(pb_by_row):
            if value is None:
                continue
            x = pad_x + idx * (plot_w / max(1, len(clean_rows) - 1))
            y = pad_y + plot_h - ((value - pb_min) / pb_span) * plot_h
            points.append((x, y))
            dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="#fff7cc" stroke="#f59e0b" stroke-width="2"/>')
        pb_line = (
            f'<polyline fill="none" stroke="#f59e0b" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round" points="{report_polyline(points)}"/>'
            + "".join(dots)
            + f'<text x="{width - pad_x - 154}" y="48" class="legend" fill="#f59e0b">PB_QuarterEnd</text>'
        )

    tick_indexes = sorted(set([0, len(labels) // 2, len(labels) - 1]))
    ticks = "\n  ".join(
        f'<text x="{pad_x + idx * (plot_w / max(1, len(clean_rows) - 1)):.1f}" y="{height - 24}" class="tick">{report_svg_escape(labels[idx])}</text>'
        for idx in tick_indexes
    )
    subtitle = f"{labels[0]} 到 {labels[-1]}；latest EPS_Q {report_num(eps_values[-1], 2)}"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <style>
    .bg{{fill:#0f1b2c}} .plot{{fill:#0a1524;stroke:#2d5874;stroke-width:1}}
    .grid{{stroke:#274761;stroke-width:1;opacity:.55}} .zero{{stroke:#e8f3ff;stroke-width:1;opacity:.45}}
    .title{{fill:#e8f3ff;font:800 24px Arial,'Microsoft JhengHei',sans-serif}} .sub{{fill:#9fb3c8;font:14px Arial,'Microsoft JhengHei',sans-serif}}
    .tick{{fill:#9fb3c8;font:12px Consolas,monospace;text-anchor:middle}} .legend{{font:800 14px Arial,'Microsoft JhengHei',sans-serif}}
  </style>
  <rect class="bg" x="0" y="0" width="{width}" height="{height}" rx="18"/>
  <text class="title" x="28" y="38">EPS / PB 季度趨勢</text>
  <text class="sub" x="28" y="64">{report_svg_escape(subtitle)}</text>
  <text x="{width - pad_x - 292}" y="48" class="legend" fill="#38bdf8">EPS_Q</text>
  <rect class="plot" x="{pad_x}" y="{pad_y}" width="{plot_w}" height="{plot_h}" rx="10"/>
  <line class="grid" x1="{pad_x}" y1="{pad_y + 72}" x2="{width - pad_x}" y2="{pad_y + 72}"/>
  <line class="grid" x1="{pad_x}" y1="{pad_y + 144}" x2="{width - pad_x}" y2="{pad_y + 144}"/>
  <line class="zero" x1="{pad_x}" y1="{zero_y:.1f}" x2="{width - pad_x}" y2="{zero_y:.1f}"/>
  {''.join(bars)}
  {pb_line}
  {ticks}
</svg>
"""
    report_write_text(chart_path, svg)
    return {
        "title": "EPS / PB 季度趨勢",
        "path": chart_path.name,
        "note": "轉調舊 UI BacktestModule：EPS_Q 用長條、PB_QuarterEnd 用橘色折線，協助判斷估值是否有基本面支撐。",
    }


def build_report_markdown(
    period: str,
    report_date: str,
    generated_at: str,
    data: dict[str, Any],
) -> str:
    latest_daily = data["latestDaily"] or {}
    latest_macro = data["latestMacro"] or {}
    latest_master = data["latestMaster"] or {}
    news_scan = data["newsScan"] or {}
    review_state = data["reviewState"] or {}
    app_state = data.get("appState") or {}

    price = finite_float(latest_daily, "Close")
    pb = finite_float(latest_daily, "PB_daily")
    bvps = finite_float(latest_daily, "BVPS_ref") or finite_float(latest_master, "BVPS")
    roe = finite_float(latest_master, "ROE_TTM_Pct")
    eps_yoy = finite_float(latest_master, "EPS_YoY_Pct")
    eps_ttm = finite_float(latest_master, "EPS_TTM")
    dividend_yield = finite_float(latest_master, "DividendYield_Pct")
    twd_usd = finite_float(latest_macro, "TWD_USD")
    dxy = finite_float(latest_macro, "DXY")
    us10y = finite_float(latest_macro, "US_10Y_Yield")
    vix = finite_float(latest_macro, "VIX")
    wti = finite_float(latest_macro, "WTI_Oil")
    latest_fx = latest(data.get("fxRows", []), "Date") or {}

    readiness = ((app_state.get("reviewPackage") or {}).get("readiness") or {})
    readiness_score = readiness.get("score", "N/A")
    readiness_threshold = readiness.get("threshold", 95)
    readiness_allowed = bool(readiness.get("allowed", False))
    formal_synced = bool(news_scan.get("formalSynced", False))
    formal_modified = bool(app_state.get("formalCsvModified", False))
    pending_publish = bool((app_state.get("pendingOwnerReview") or {}).get("pending", False))
    pending_reviews = review_state.get("pendingReviews", []) or []

    gate_status = "READY_FOR_NEW_UI"
    decision_line = "正式 CSV、新聞與 FX 狀態已同步；可進入新 UI 看六大系統摘要，舊 UI 僅作 KPI 明細追溯。"
    if not latest_daily or not latest_macro or not latest_master:
        gate_status = "DATA_BLOCKED"
        decision_line = "核心 CSV 不完整；請先回 Launcher 完成資料更新與 Owner gate。"
    elif pending_publish or pending_reviews:
        gate_status = "OWNER_REVIEW_REQUIRED"
        decision_line = "仍有候選資料或事件待審；請留在 Launcher 處理，不要直接進入新 UI 決策。"

    valuation_state, valuation_reason = report_valuation_state(pb)
    cashflow_state, cashflow_reason = report_cashflow_state(dividend_yield, us10y)
    next_review = report_next_business_day(latest_daily.get("Date") or report_date)
    events = report_event_rows(data)
    event_counts = report_event_counts(events)
    ranked_events = sorted(events, key=lambda row: (report_event_score(row), row.get("Date", "")), reverse=True)
    high_signal_events: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for row in ranked_events:
        key = (row.get("Url") or row.get("Title") or "").strip().lower()
        if not key or key in seen_keys:
            continue
        if report_event_score(row) < 35 and len(high_signal_events) >= 3:
            continue
        high_signal_events.append(row)
        seen_keys.add(key)
        if len(high_signal_events) >= 6:
            break
    summary_event_counts = report_event_counts(high_signal_events)

    news_total = int(news_scan.get("candidateRowCount", 0) or len(events))
    source_health = news_scan.get("sourceHealth") or []
    network_total = len([s for s in source_health if s.get("connectorStatus") != "LOCAL_INPUT_ONLY"]) or int(news_scan.get("networkSummary", {}).get("approvedSources", 0) or 0)
    network_success = len([s for s in source_health if str(s.get("status", "")).upper() in {"OK", "SUCCEEDED", "SUCCESS"}])
    connector_text = f"{network_success}/{network_total} 個網路來源成功" if network_total else "新聞來源狀態未提供"
    fx_pressure = latest_fx.get("FxPressureLevel", "N/A")
    macro_tone = "風險成本監控"
    if vix is not None and vix >= 20:
        macro_tone = "風險升高"
    elif dxy is not None and dxy >= 102:
        macro_tone = "美元偏強"
    elif fx_pressure and fx_pressure != "N/A":
        macro_tone = str(fx_pressure)

    market_rows = [
        ["2317 close", latest_daily.get("Date", "N/A"), report_num(price, 1), latest_daily.get("DataSupportLevel", "正式 CSV")],
        ["PB", latest_daily.get("Date", "N/A"), report_ratio(pb), "Close / BVPS"],
        ["USD/TWD", latest_macro.get("Date", "N/A"), report_num(twd_usd, 3), latest_fx.get("SourceTier") or "macro_snapshot"],
        ["US10Y", latest_macro.get("Date", "N/A"), report_num(us10y, 3, "%"), "macro_snapshot"],
        ["VIX / DXY / WTI", latest_macro.get("Date", "N/A"), f"{report_num(vix, 2)} / {report_num(dxy, 2)} / {report_num(wti, 2)}", "macro_snapshot"],
    ]
    six_system_rows = [
        ["基本面 IC", f"ROE {report_num(roe, 2, '%')} / EPS YoY {report_num(eps_yoy, 1, '%')} / EPS TTM {report_num(eps_ttm, 2)}", "基本面支撐", "EPS 與 ROE 是 HOLD 的主要支撐，若後續下修才需要重審估值。"],
        ["估值 IC", f"Close {report_num(price, 1)} / BVPS {report_num(bvps, 2)} / PB {report_ratio(pb)}", valuation_state, valuation_reason],
        ["現金流 / 股東回報 IC", f"殖利率 {report_num(dividend_yield, 2, '%')} / US10Y {report_num(us10y, 3, '%')}", cashflow_state, cashflow_reason],
        ["宏觀 / 匯率 IC", f"USD/TWD {report_num(twd_usd, 3)} / DXY {report_num(dxy, 3)} / VIX {report_num(vix, 2)} / WTI {report_num(wti, 2)}", macro_tone, "USD/TWD 季均值每變動 1%，先用 NT$0.05-0.10 EPS 敏感度重審；不直接改主 IC。"],
        ["產業 / AI IC", f"新聞候選 {news_total}；高訊號 {len(high_signal_events)}", "CSP 需求待驗證", "重點看美國七大 CSP capex、AI server、GB200/GB300、NVIDIA 與雲端客戶需求。"],
        ["資料品質 IC", f"readiness {readiness_score}/{readiness_threshold}；新聞 connector {connector_text}", "正式可用" if readiness_allowed else "待補強", "這是正式 CSV 發布稽核分數，不是六大 IC 投資分數。"],
    ]
    news_rows = [
        [
            row.get("Date", "N/A"),
            report_event_text(row),
            report_clean_label(row.get("SourceName"), row.get("SourceTier", "來源未明")),
            row.get("Level", "N/A"),
            report_event_focus(row),
            report_human_actionable(row.get("Actionable")),
        ]
        for row in high_signal_events
    ] or [["-", "本期沒有高訊號事件", "-", "NONE", "只保留 NEWS_SCAN 稽核，不放進決策摘要。", report_human_actionable()]]

    owner_rows = [
        ["Launcher gate", "可進入新 UI" if gate_status == "READY_FOR_NEW_UI" else gate_status, decision_line],
        ["正式 CSV", "已更新" if formal_modified else "未變更", "一鍵流程不會自動發布；只有 Owner publish gate 會 append。"],
        ["事件審查", "已同步" if formal_synced and not pending_reviews else "待審", report_sync_text(pending_reviews, formal_synced)],
        ["下次檢視", next_review, "開盤前或異常事件觸發時重審；戰情室不輸出買賣指令。"],
    ]

    return "\n".join(
        [
            f"# P1008 {report_period_zh(period)} {report_date}",
            "",
            "## 今日結論",
            "",
            f"- 戰情室狀態：`{gate_status}`。",
            f"- 決策摘要：{decision_line}",
            f"- 估值判斷：{valuation_state}；{valuation_reason}",
            f"- 新聞去噪：本期候選 {news_total} 則，日報只列 {len(news_rows)} 則需要決策者看的高訊號事件。",
            "- 安全邊界：本報只提供重審提示與反證材料；不輸出買賣指令，也不自動改主 IC。",
            "",
            "## 關鍵數據卡",
            "",
            markdown_table(["項目", "資料日期", "目前值", "來源 / 說明"], market_rows),
            "",
            "## 六大系統摘要",
            "",
            markdown_table(["系統", "目前讀數", "判斷", "決策者要看什麼"], six_system_rows),
            "",
            "## 國際與產業新聞去噪",
            "",
            f"- 新聞 connector：{connector_text}；本期候選 {news_total} 則，日報去噪後列 {len(high_signal_events)} 則：REVIEW_REQUIRED {summary_event_counts['REVIEW_REQUIRED']}、WATCH {summary_event_counts['WATCH']}、OBSERVE {summary_event_counts['OBSERVE']}。",
            "- 日報只列高訊號與直接關聯鴻海事件；完整清單保留在 NEWS_SCAN 稽核，不要求決策者逐條閱讀。",
            "",
            markdown_table(["日期", "事件摘要", "來源", "等級", "決策者要看什麼", "可否直接行動"], news_rows),
            "",
            "## FX / Macro 判讀",
            "",
            markdown_table(
                ["項目", "目前值", "判斷", "處理方式"],
                [
                    ["USD/TWD", report_num(twd_usd, 3), f"FX pressure={fx_pressure}", "用 EPS 敏感度重審，不直接改 HOLD。"],
                    ["DXY / US10Y", f"{report_num(dxy, 3)} / {report_num(us10y, 3, '%')}", macro_tone, "確認美元與利率是否壓縮估值倍數。"],
                    ["VIX / WTI", f"{report_num(vix, 2)} / {report_num(wti, 2)}", "風險與成本監控", "VIX>20 或油價急升時列入重審提示。"],
                ],
            ),
            "",
            "## Owner 待辦",
            "",
            markdown_table(["項目", "狀態", "決策者要知道"], owner_rows),
            "",
            "## 報告使用規則",
            "",
            "- Launcher 負責資料更新、新聞 / FX 檢核與 Owner publish gate。",
            "- 新 UI 負責六大系統摘要與決策視野，不承擔正式 CSV 發布。",
            "- 舊 UI 只作 KPI 明細、來源稽核與戰報追溯。",
            "- 新聞與 FX sidecar 永遠不能直接改 HOLD 主 IC；只能觸發 OBSERVE / WATCH / REVIEW_REQUIRED。",
            "- 系統註記：本報由本機戰報產生器輸出，產生報告本身不會修改正式 CSV。",
            "",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(build_report(parse_args()))
