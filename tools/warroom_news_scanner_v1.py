#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Observation-only scheduled news scanner for P1008.

This tool writes only staging/runtime observation artifacts:
- staging/<date>/macro_event_observations_candidate.csv when qualified events exist
- staging/<date>/NEWS_SCAN.json
- staging/<date>/NEWS_SCAN.md
- runtime/warroom_news_scan_snapshot.json

It never appends formal CSV files and never changes HOLD logic.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


TOOL_VERSION = "warroom_news_scanner_v1"
MACRO_EVENT_TARGET = "data/macro_event_observations.csv"
MACRO_EVENT_CANDIDATE = "macro_event_observations_candidate.csv"
SOURCE_MANIFEST = "data/NEWS_SCAN_SOURCE_MANIFEST.json"
EVENT_REVIEW_STATE = "runtime/warroom_event_review_state.json"

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

ALLOWED_SOURCE_TIERS = {
    "OFFICIAL",
    "PUBLIC_MARKET",
    "MEDIA",
    "OWNER_NOTE",
    "UNVERIFIED",
}

SCAN_WINDOWS = {
    "preopen": {"label": "PRE_OPEN", "lookbackHours": 16, "scheduledTimeTST": "08:10"},
    "intraday": {"label": "INTRADAY", "lookbackHours": 6, "scheduledTimeTST": "12:30"},
    "postclose": {"label": "POST_CLOSE", "lookbackHours": 8, "scheduledTimeTST": "15:30"},
    "global": {"label": "GLOBAL_FED_FX", "lookbackHours": 12, "scheduledTimeTST": "21:30"},
    "report": {"label": "WEEKLY_REPORT_AUDIT", "lookbackHours": 168, "scheduledTimeTST": "WEEKEND_OR_MONDAY"},
}

SOURCE_SCORE = {
    "OFFICIAL": 40,
    "PUBLIC_MARKET": 25,
    "MEDIA": 15,
    "OWNER_NOTE": 35,
    "UNVERIFIED": 5,
}

DIRECT_KEYWORDS = [
    "2317",
    "hon hai",
    "foxconn",
    "foxconn industrial internet",
    "鴻海",
    "鸿海",
    "富士康",
]

CUSTOMER_SUPPLY_KEYWORDS = [
    "nvidia",
    "輝達",
    "英伟达",
    "apple",
    "蘋果",
    "苹果",
    "ai server",
    "ai伺服器",
    "gb200",
    "gb300",
    "iphone",
    "server",
    "supply chain",
    "供應鏈",
    "供应链",
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
    "央行",
    "匯率",
    "汇率",
    "利率",
    "通膨",
    "油價",
    "油价",
    "關稅",
    "关税",
    "出口管制",
    "地緣",
    "地缘",
]


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv_dicts(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv_rows(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def parse_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_timestamp(value: Any, fallback: datetime) -> datetime:
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
        return datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return fallback


def choose_scan_window(name: str) -> str:
    if name != "auto":
        return name
    hour = datetime.now().hour
    if hour < 11:
        return "preopen"
    if hour < 15:
        return "intraday"
    if hour < 20:
        return "postclose"
    return "global"


def normalize_text(*parts: Any) -> str:
    return " ".join(str(part or "").strip().lower() for part in parts if str(part or "").strip())


def contains_any(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(keyword.lower() in lower for keyword in keywords)


def relevance_score(row: dict[str, Any]) -> tuple[int, str]:
    text = normalize_text(
        row.get("EventTitle"),
        row.get("SummaryZh"),
        row.get("DecisionImpactZh"),
        row.get("RiskTag"),
        row.get("RelatedMetrics"),
        row.get("Keywords"),
    )
    if contains_any(text, DIRECT_KEYWORDS):
        return 40, "DIRECT_2317"
    if contains_any(text, CUSTOMER_SUPPLY_KEYWORDS):
        return 25, "CUSTOMER_SUPPLY_CHAIN"
    if contains_any(text, MACRO_FX_KEYWORDS):
        return 15, "MACRO_FX_MARKET"
    return 0, "LOW_RELEVANCE"


def build_event_key(row: dict[str, Any], published_at: datetime) -> str:
    raw = "|".join(
        [
            published_at.strftime("%Y-%m-%d"),
            str(row.get("EventTitle", "")).strip().lower(),
            str(row.get("SourceUrl", "")).strip().lower(),
            str(row.get("SourceName", "")).strip().lower(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()


def level_rank(level: str) -> int:
    return {"NONE": 0, "OBSERVE": 1, "WATCH": 2, "REVIEW_REQUIRED": 3}.get(level, 0)


def cap_level(level: str, source_tier: str, corroboration_count: int, official_confirmation: bool, relevance: int) -> str:
    if source_tier == "UNVERIFIED":
        return "OBSERVE" if level_rank(level) >= 1 else "NONE"
    if source_tier == "MEDIA" and corroboration_count < 2 and not official_confirmation:
        return "WATCH" if level_rank(level) >= 2 else level
    if level == "REVIEW_REQUIRED" and relevance < 25:
        return "WATCH"
    if level == "REVIEW_REQUIRED" and not official_confirmation and corroboration_count < 2:
        return "WATCH"
    return level


def review_deadline(generated_at: datetime, level: str) -> str:
    if level == "REVIEW_REQUIRED":
        deadline = generated_at + timedelta(hours=12)
    elif level == "WATCH":
        deadline = generated_at + timedelta(hours=72)
    else:
        deadline = generated_at + timedelta(days=7)
    return deadline.strftime("%Y-%m-%dT%H:%M:%S")


def classify_event(row: dict[str, Any], generated_at: datetime, lookback_hours: int) -> dict[str, Any] | None:
    published_at = parse_timestamp(row.get("PublishedAt") or row.get("Date"), generated_at)
    age_hours = max(0.0, (generated_at - published_at).total_seconds() / 3600)
    if age_hours > lookback_hours:
        return {
            "accepted": False,
            "reason": "OUTSIDE_LOOKBACK",
            "title": row.get("EventTitle", ""),
            "publishedAt": published_at.strftime("%Y-%m-%dT%H:%M:%S"),
            "ageHours": round(age_hours, 2),
        }

    title = str(row.get("EventTitle", "")).strip()
    if not title:
        return {"accepted": False, "reason": "MISSING_EVENT_TITLE", "title": ""}

    source_tier = str(row.get("SourceTier") or "UNVERIFIED").strip().upper()
    if source_tier not in ALLOWED_SOURCE_TIERS:
        source_tier = "UNVERIFIED"

    relevance, relevance_tag = relevance_score(row)
    corroboration_count = max(1, parse_int(row.get("CorroborationCount"), 1))
    official_confirmation = parse_bool(row.get("OfficialConfirmation")) or source_tier == "OFFICIAL"
    market_confirmation = parse_bool(row.get("MarketConfirmation"))

    score = SOURCE_SCORE[source_tier] + relevance
    if corroboration_count >= 2:
        score += 15
    if official_confirmation:
        score += 20
    if market_confirmation:
        score += 10
    if age_hours > 72:
        score -= 20
    elif age_hours > 24:
        score -= 10
    elif age_hours > 6:
        score -= 5
    score = max(0, min(100, score))

    if score >= 85:
        raw_level = "REVIEW_REQUIRED"
    elif score >= 65:
        raw_level = "WATCH"
    elif score >= 45:
        raw_level = "OBSERVE"
    else:
        return {
            "accepted": False,
            "reason": "BELOW_OBSERVE_THRESHOLD",
            "title": title,
            "score": score,
            "sourceTier": source_tier,
            "relevanceTag": relevance_tag,
        }

    level = cap_level(raw_level, source_tier, corroboration_count, official_confirmation, relevance)
    if level == "REVIEW_REQUIRED":
        evidence_status = "REVIEW_REQUIRED_EVIDENCE"
    elif source_tier == "UNVERIFIED":
        evidence_status = "UNVERIFIED_OBSERVE"
    elif source_tier == "MEDIA" and corroboration_count < 2 and not official_confirmation:
        evidence_status = "SINGLE_MEDIA_WATCH"
    else:
        evidence_status = "OBSERVATION_EVIDENCE"

    event_type = str(row.get("EventType") or "NEWS").strip().upper()
    event_key = build_event_key(row, published_at)
    candidate_row = {
        "Date": published_at.strftime("%Y-%m-%d"),
        "EventType": event_type,
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
        "sourceScore": SOURCE_SCORE[source_tier],
        "relevanceScore": relevance,
        "relevanceTag": relevance_tag,
        "corroborationCount": corroboration_count,
        "officialConfirmation": official_confirmation,
        "marketConfirmation": market_confirmation,
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
        if source.get("enabled") and source.get("requiresNetwork"):
            warnings.append(f"Source {source.get('sourceId', 'UNKNOWN')} is network-based; v1 scanner keeps connectors pending.")
    return manifest, warnings


def load_input_events(args: argparse.Namespace, generated_at: datetime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if args.input_events_csv:
        _, csv_rows = read_csv_dicts(Path(args.input_events_csv))
        rows.extend(csv_rows)

    if args.event_title:
        rows.append(
            {
                "PublishedAt": args.published_at or generated_at.strftime("%Y-%m-%dT%H:%M:%S"),
                "EventType": args.event_type,
                "EventTitle": args.event_title,
                "Region": args.event_region,
                "SourceTier": args.source_tier,
                "SourceName": args.source_name,
                "SourceUrl": args.source_url,
                "EvidenceStatus": args.evidence_status,
                "RiskTag": args.risk_tag,
                "RelatedMetrics": args.related_metrics,
                "SummaryZh": args.summary_zh,
                "DecisionImpactZh": args.decision_impact_zh,
                "Keywords": args.keywords,
                "CorroborationCount": args.corroboration_count,
                "MarketConfirmation": args.market_confirmation,
                "OfficialConfirmation": args.official_confirmation,
            }
        )
    return rows


def formal_event_keys(package_root: Path) -> set[str]:
    _, rows = read_csv_dicts(package_root / MACRO_EVENT_TARGET)
    return {"|".join([row.get("Date", ""), row.get("EventTitle", ""), row.get("SourceUrl", "")]) for row in rows}


def build_dry_run_fragment(
    package_root: Path,
    staging_dir: Path,
    candidate_date: str,
    scan_summary: dict[str, Any],
    generated_files: list[str],
) -> dict[str, Any]:
    warnings = [item for item in scan_summary.get("warnings", []) if item]
    return {
        "task": "P1008_NEWS_SCAN",
        "toolVersion": TOOL_VERSION,
        "generatedAt": scan_summary["generatedAt"],
        "candidateDate": candidate_date,
        "productionCsvModified": False,
        "formalPublishRuleZh": "News scan only creates observation candidates; Owner publish gate is still required.",
        "inputSources": {
            "news_scan": "LOCAL_MANIFEST_ONLY" if scan_summary.get("noNetwork") else "CONNECTOR_PENDING",
        },
        "sourceMeta": {
            "news_scan": {
                "requiredForFormal": False,
                "dataset": "macro_event_observations",
                "sourceUrl": str(scan_summary.get("sourceManifestPath", "")),
                "statusZh": "Observation-only scheduled news scan; connectors remain pending unless separately approved.",
            }
        },
        "criticalMissingFields": [],
        "missingFields": [],
        "optionalMissingFields": [],
        "unavailableCandidateFields": [],
        "dataQualityWarningsZh": warnings,
        "alreadyPublishedTargets": [],
        "validationChecks": [
            {
                "dataset": "macro_event_observations",
                "schemaColumns": len(MACRO_EVENT_COLUMNS),
                "rowColumns": len(MACRO_EVENT_COLUMNS),
                "status": "PASS",
                "statusZh": "News scan candidate is observation-only; Actionable=false; HOLD and rules unchanged.",
            }
        ],
        "generatedFiles": generated_files,
        "noPublishRequired": not generated_files,
        "newsScan": scan_summary,
        "dryRunPath": str(staging_dir / "DRY_RUN.json").replace(str(package_root) + "\\", ""),
    }


def merge_dry_run(package_root: Path, staging_dir: Path, fragment: dict[str, Any]) -> bool:
    dry_run_path = staging_dir / "DRY_RUN.json"
    generated_files = fragment.get("generatedFiles", []) or []
    if dry_run_path.exists():
        dry_run = read_json(dry_run_path)
        dry_run["newsScan"] = fragment["newsScan"]
        dry_run["dataQualityWarningsZh"] = list(
            dict.fromkeys((dry_run.get("dataQualityWarningsZh", []) or []) + fragment.get("dataQualityWarningsZh", []))
        )
        dry_run["validationChecks"] = (dry_run.get("validationChecks", []) or []) + fragment.get("validationChecks", [])
        dry_run["inputSources"] = {**(dry_run.get("inputSources", {}) or {}), **fragment.get("inputSources", {})}
        dry_run["sourceMeta"] = {**(dry_run.get("sourceMeta", {}) or {}), **fragment.get("sourceMeta", {})}
        if generated_files:
            dry_run["generatedFiles"] = list(dict.fromkeys((dry_run.get("generatedFiles", []) or []) + generated_files))
        write_json(dry_run_path, dry_run)
        return True

    if generated_files:
        write_json(dry_run_path, fragment)
        return True
    return False


def write_scan_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# P1008 News Scan Dry Run",
        "",
        f"- Generated: {summary['generatedAt']}",
        f"- Window: {summary['scanWindow']['label']} / lookback {summary['scanWindow']['lookbackHours']}h",
        f"- Candidate rows: {summary['candidateRowCount']}",
        f"- Highest level: {summary['highestLevel']}",
        f"- HOLD_UNDER_REVIEW: {str(summary['holdUnderReview']).lower()}",
        f"- Production CSV modified: {str(summary['productionCsvModified']).lower()}",
        f"- Actionable: {str(summary['actionable']).lower()}",
        "",
        "## Events",
    ]
    if not summary["events"]:
        lines.append("- No qualified event. No formal CSV append is pending.")
    for event in summary["events"]:
        row = event["candidateRow"]
        lines.append(
            f"- {row['Date']} | {row['BlackSwanLevel']} | {row['SourceTier']} | "
            f"{row['EventTitle']} | score={event['score']} | deadline={event['reviewDeadline']}"
        )
    if summary["ignoredEvents"]:
        lines.extend(["", "## Ignored Events"])
        for event in summary["ignoredEvents"]:
            lines.append(f"- {event.get('reason', 'UNKNOWN')}: {event.get('title', '')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_event_review_state(summary: dict[str, Any]) -> dict[str, Any]:
    pending_reviews = []
    for event in summary.get("events", []) or []:
        level = str(event.get("level", "")).upper()
        if level not in {"WATCH", "REVIEW_REQUIRED"}:
            continue
        row = event.get("candidateRow", {}) or {}
        pending_reviews.append(
            {
                "eventKey": event.get("eventKey") or "",
                "eventDate": row.get("Date") or event.get("publishedAt") or "",
                "eventTitle": row.get("EventTitle") or "",
                "level": level,
                "sourceTier": row.get("SourceTier") or "",
                "reviewStatus": "PENDING_OWNER_ACK",
                "reviewDeadline": event.get("reviewDeadline") or summary.get("reviewDeadline") or "",
                "reviewConclusionZh": "待 Owner 確認；事件只作重審提示，不改 HOLD。",
                "actionable": False,
            }
        )
    return {
        "task": "P1008_EVENT_REVIEW_STATE",
        "toolVersion": TOOL_VERSION,
        "generatedAt": summary["generatedAt"],
        "sourceSnapshot": "runtime/warroom_news_scan_snapshot.json",
        "productionCsvModified": False,
        "actionable": False,
        "status": "REVIEW_REQUIRED" if any(item["level"] == "REVIEW_REQUIRED" for item in pending_reviews) else ("WATCH_PENDING" if pending_reviews else "NO_PENDING_REVIEW"),
        "ownerAckRequired": bool(pending_reviews),
        "pendingReviews": pending_reviews,
        "lastScan": {
            "generatedAt": summary["generatedAt"],
            "highestLevel": summary.get("highestLevel", "NONE"),
            "holdUnderReview": bool(summary.get("holdUnderReview", False)),
            "candidateRowCount": int(summary.get("candidateRowCount", 0) or 0),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run P1008 observation-only scheduled news scan.")
    parser.add_argument("--package-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--date", help="Candidate date YYYY-MM-DD. Defaults to today.")
    parser.add_argument("--scan-window", choices=["auto", *SCAN_WINDOWS.keys()], default="auto")
    parser.add_argument("--lookback-hours", type=int)
    parser.add_argument("--dry-run", action="store_true", help="Accepted for BAT/scheduler clarity; formal CSV is never modified.")
    parser.add_argument("--no-network", action="store_true", help="Do not use network connectors.")
    parser.add_argument("--allow-network", action="store_true", help="Reserved for separately approved connectors; v1 keeps them pending.")
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

    package_root = args.package_root.resolve()
    generated_at = datetime.now()
    candidate_date = args.date or generated_at.strftime("%Y-%m-%d")
    window_key = choose_scan_window(args.scan_window)
    window = dict(SCAN_WINDOWS[window_key])
    if args.lookback_hours:
        window["lookbackHours"] = args.lookback_hours
    no_network = args.no_network or not args.allow_network

    staging_dir = package_root / "staging" / candidate_date
    staging_dir.mkdir(parents=True, exist_ok=True)
    runtime_path = package_root / "runtime" / "warroom_news_scan_snapshot.json"
    event_review_state_path = package_root / EVENT_REVIEW_STATE
    candidate_path = staging_dir / MACRO_EVENT_CANDIDATE

    manifest, manifest_warnings = load_manifest(package_root, args.source_manifest)
    input_events = load_input_events(args, generated_at)
    if not no_network:
        manifest_warnings.append("Network connectors are connector-pending in v1; no automatic news fetch was executed.")

    accepted_events: list[dict[str, Any]] = []
    ignored_events: list[dict[str, Any]] = []
    seen_event_keys: set[str] = set()
    existing_formal_keys = formal_event_keys(package_root)

    for raw_event in input_events:
        classified = classify_event(raw_event, generated_at, int(window["lookbackHours"]))
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

    summary = {
        "task": "P1008_NEWS_SCAN",
        "toolVersion": TOOL_VERSION,
        "generatedAt": generated_at.strftime("%Y-%m-%dT%H:%M:%S"),
        "candidateDate": candidate_date,
        "runtimeOnly": True,
        "runtimeOnlyZh": "Observation-only news scan; formal CSV is unchanged.",
        "productionCsvModified": False,
        "productionCsvModifiedZh": "Formal CSV files were not modified.",
        "ownerConfirmationRequired": bool(candidate_rows),
        "ownerConfirmationRequiredZh": "Owner publish gate is required before appending macro_event_observations.csv.",
        "actionable": False,
        "actionableZh": "News scan cannot issue trading instructions or change HOLD.",
        "noNetwork": no_network,
        "sourceManifestPath": args.source_manifest,
        "sourceManifestStatus": manifest.get("status", "ACTIVE"),
        "scanWindow": window,
        "candidatePath": str(candidate_path.relative_to(package_root)),
        "candidateRowCount": len(candidate_rows),
        "generatedFiles": generated_files,
        "highestLevel": highest_level,
        "holdUnderReview": hold_under_review,
        "ownerReviewRequired": hold_under_review or any(event["level"] == "WATCH" for event in accepted_events),
        "reviewDeadline": accepted_events[0]["reviewDeadline"] if accepted_events else "",
        "sourceCounts": source_counts,
        "macroEventRow": accepted_events[0]["candidateRow"] if accepted_events else None,
        "events": accepted_events,
        "ignoredEvents": ignored_events,
        "warnings": manifest_warnings,
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

    log(f"News scan completed: {len(candidate_rows)} candidate row(s), highestLevel={highest_level}.")
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
