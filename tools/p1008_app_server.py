#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local P1008 web app server with a small whitelisted control API.

The API intentionally exposes only fixed P1008 jobs. It never accepts arbitrary
shell commands. Formal CSV publish is available only through the isolated Owner
publish gate and is never part of the Launcher default data pipeline.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import owner_publish_csv_v2 as owner_publish
import warroom_report_governance as report_governance
import warroom_report_trigger_runtime as report_trigger_runtime
import warroom_rolling_brief as rolling_brief


UTF8_MIME_TYPES = {
    ".html": "text/html",
    ".htm": "text/html",
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".svg": "image/svg+xml",
    ".xml": "application/xml",
}

FORMAL_CSV_FILES = [
    "data/2317_master_v9.csv",
    "data/2317_daily_price.csv",
    "data/2317_daily_market_activity.csv",
    "data/macro_snapshot.csv",
    "data/macro_event_observations.csv",
    "data/fx_trend_observations.csv",
    "data/CSV_AUTHORITY_MANIFEST.json",
]

STATE_REL = "runtime/p1008_app_state.json"
DAILY_PRICE_STATUS_REL = "runtime/daily_price_incremental/latest_status.json"
MARKET_ACTIVITY_STATUS_REL = "runtime/market_activity_incremental/latest_status.json"
FRESHNESS_STATUS_REL = "runtime/authority_freshness/latest_status.json"
SOURCE_MANIFEST_REL = "data/NEWS_SCAN_SOURCE_MANIFEST.json"
OFFICIAL_IR_STATUS_REL = "runtime/official_ir_evidence/latest_status.json"
SERVER_VERSION = "P1008_APP_SERVER_20260812_OFFICIAL_IR_EVIDENCE_V1"

WEEKDAY_ZH = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
FIELD_LABEL_ZH = {
    "DXY": "美元指數",
    "TWD_USD": "新台幣兌美元",
    "US_10Y_Yield": "美國 10 年期公債殖利率",
    "VIX": "市場波動率指數",
    "WTI_Oil": "WTI 原油價格",
    "BOJ_Rate": "日本央行政策利率",
    "JPY_USD": "日圓兌美元",
    "RateSpread_US_JP": "美日利差",
    "Close": "2317 日收盤價",
}
SOURCE_LABEL_ZH = {
    "dxy": "美元指數",
    "twd_usd": "新台幣兌美元",
    "us10y": "美國 10 年期公債殖利率",
    "vix": "市場波動率指數",
    "wti": "WTI 原油價格",
    "stock_price": "2317 日收盤價",
    "jpy_usd": "日圓兌美元",
    "boj_rate": "日本央行政策利率",
}


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def server_context() -> dict[str, Any]:
    started_from_codex = any(
        os.environ.get(key)
        for key in ("CODEX_SHELL", "CODEX_THREAD_ID", "CODEX_INTERNAL_ORIGINATOR_OVERRIDE")
    )
    codex_network_sandbox = os.environ.get("CODEX_SANDBOX_NETWORK_DISABLED") == "1"
    return {
        "startedFromCodex": bool(started_from_codex),
        "codexNetworkSandbox": bool(codex_network_sandbox),
        "networkModeZh": (
            "Codex 沙盒啟動，外網 connector 可能被禁用"
            if codex_network_sandbox
            else "Windows 本機啟動，connector 走本機網路/proxy"
        ),
        "adviceZh": (
            "請從資料夾直接雙擊 P1008_APP.bat 後重跑；不要沿用 Codex 測試啟動的 localhost server。"
            if codex_network_sandbox
            else "若來源仍失敗，優先檢查公司 proxy/firewall、來源 URL 或 manifest。"
        ),
    }


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def formal_csv_hashes(package_root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for rel in FORMAL_CSV_FILES:
        path = package_root / rel
        hashes[rel] = sha256_file(path) if path.exists() else "MISSING"
    return hashes


def git_head(package_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(package_root), "rev-parse", "HEAD"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "UNKNOWN"
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else "UNKNOWN"


def parse_candidate_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def market_context(candidate_date: str) -> dict[str, Any]:
    parsed = parse_candidate_date(candidate_date)
    if not parsed:
        return {
            "status": "UNKNOWN",
            "isWeekend": False,
            "zh": "無法判斷候選日期是否為交易日；請以 TWSE 交易日曆或 Owner 判斷為準。",
        }
    weekday = WEEKDAY_ZH[parsed.weekday()]
    if parsed.weekday() >= 5:
        return {
            "status": "WEEKEND_CLOSED",
            "isWeekend": True,
            "weekdayZh": weekday,
            "zh": f"{candidate_date} 是{weekday}，台股例行休市；沒有 2317 日收盤價屬正常狀況。",
        }
    return {
        "status": "TRADING_DAY_OR_HOLIDAY_UNKNOWN",
        "isWeekend": False,
        "weekdayZh": weekday,
        "zh": f"{candidate_date} 是{weekday}；系統尚未接入正式 TWSE 休市日曆，若當天為國定假日需由 Owner 或交易所日曆確認。",
    }


def labeled_list(items: list[str], labels: dict[str, str]) -> str:
    output: list[str] = []
    for item in items:
        key = str(item).strip()
        label = labels.get(key) or labels.get(key.lower())
        output.append(f"{key}（{label}）" if label else key)
    return "、".join(output)


def split_csv_after(text: str, prefix: str) -> list[str]:
    if not text.startswith(prefix):
        return []
    return [item.strip() for item in text[len(prefix):].split(",") if item.strip()]


def translate_warning_zh(note: str, candidate_date: str) -> tuple[str, str]:
    context = market_context(candidate_date)
    if "未取得 2317 收盤價" in note:
        if context.get("isWeekend"):
            return (
                "info",
                f"休市提示：{context['zh']} 本次不產生 daily_price candidate，也不會補假資料；若其他候選檔通過，只會發布已生成的候選 CSV。",
            )
        return (
            "warning",
            "價格缺口：未取得 2317 日收盤價，因此不產生 daily_price candidate。若不是休市日，需檢查 TWSE connector 或由 Owner 補正式收盤價來源。",
        )
    if "沿用正式 CSV 最近交易日" in note and "收盤價" in note:
        return ("info", f"休市沿用：{note}")
    if "休市沿用列僅供 runtime/UI" in note:
        return ("info", note)
    if note.startswith("BOJ_Rate missing"):
        return ("info", "FX 觀察缺口：BOJ_Rate 尚未取得，無法計算美日利差；此為 sidecar 觀察欄位，不會直接改 HOLD。")
    if note.startswith("JPY_USD missing"):
        return ("info", "FX 觀察缺口：JPY_USD 尚未取得，FX sidecar 標示資料缺口；此欄位目前不直接阻擋 macro_snapshot。")
    if "macro_event_observations_candidate.csv not generated" in note:
        return ("info", "新聞觀察提示：未提供 Owner 事件輸入，因此不產生事件 candidate；系統不得自動幻想新聞。")
    if "macro_event_observations_candidate.csv reset to header-only" in note:
        return ("info", "新聞觀察提示：事件候選檔已重置為只有表頭，避免舊事件被誤 append。")
    if "沿用正式 CSV 最近值" in note:
        return ("info", f"沿用提示：{note} 這是維持觀察連續性，不代表新資料已取得。")
    return ("warning", note)


def readiness_explanation_zh(readiness: dict[str, Any], candidate_date: str) -> dict[str, list[str]]:
    blockers_zh: list[str] = []
    advisories_zh: list[str] = []
    improvements_zh: list[str] = []

    for raw in readiness.get("blockers", []) or []:
        text = str(raw)
        critical = split_csv_after(text, "Missing critical fields:")
        sources = split_csv_after(text, "Missing required sources:")
        if critical:
            blockers_zh.append(
                "正式發布阻擋：總經核心欄位缺值："
                f"{labeled_list(critical, FIELD_LABEL_ZH)}。這些欄位會影響宏觀風險、匯率壓力與市場壓力判斷，未補齊前不可升格正式 CSV。"
            )
            improvements_zh.append("改善方向：接入 Owner 核准來源，或在更新資料時由 Owner 手動輸入 DXY、TWD/USD、US10Y、VIX、WTI。")
            continue
        if sources:
            blockers_zh.append(
                "正式發布阻擋：總經 connector/source 未取得正式來源："
                f"{labeled_list(sources, SOURCE_LABEL_ZH)}。系統可沿用正式 CSV 最近值作畫面觀察，但缺少本次可追溯來源時不能把候選資料升格正式 CSV。"
            )
            improvements_zh.append("改善方向：優先接 FRED/TWSE/央行/交易所等官方或準官方 connector；公開市場來源作交叉驗證，Yahoo 只能當最後備援。")
            continue
        if text.startswith("Readiness score"):
            blockers_zh.append(
                f"正式發布阻擋：Readiness 目前 {readiness.get('score', 'N/A')}%，低於門檻 {readiness.get('threshold', 95)}%。主因通常是總經來源缺失或 candidate 檢核未通過。"
            )
            continue
        blockers_zh.append(f"正式發布阻擋：{text}")

    context = market_context(candidate_date)
    warnings = readiness.get("warningsZh", []) or []
    has_daily_close_note = any("2317 收盤價" in str(warning) or "daily_price" in str(warning) for warning in warnings)
    if context.get("isWeekend") and not has_daily_close_note:
        advisories_zh.append(context["zh"])

    for warning in warnings:
        level, translated = translate_warning_zh(str(warning), candidate_date)
        if level == "warning":
            advisories_zh.append(f"警告：{translated}")
        else:
            advisories_zh.append(translated)

    return {
        "blockersZh": list(dict.fromkeys(blockers_zh)),
        "advisoriesZh": list(dict.fromkeys(advisories_zh)),
        "improvementsZh": list(dict.fromkeys(improvements_zh)),
    }


def latest_staging_date(package_root: Path) -> str:
    staging_dir = package_root / "staging"
    if not staging_dir.exists():
        return ""
    candidates = sorted(
        item.name for item in staging_dir.iterdir()
        if item.is_dir() and len(item.name) == 10 and item.name[4] == "-" and item.name[7] == "-"
    )
    return candidates[-1] if candidates else ""


def load_source_manifest(package_root: Path) -> tuple[dict[str, Any], list[str]]:
    manifest_path = package_root / SOURCE_MANIFEST_REL
    manifest = read_json(manifest_path, default={}) or {}
    warnings: list[str] = []
    if not manifest:
        warnings.append(f"{SOURCE_MANIFEST_REL} missing or invalid; news scan will run no-network.")
    sources = manifest.get("sources", []) if isinstance(manifest.get("sources", []), list) else []
    for source in sources:
        if not source.get("enabled"):
            continue
        if source.get("requiresNetwork") and source.get("connectorStatus") != "APPROVED":
            warnings.append(
                f"Source {source.get('sourceId', 'UNKNOWN')} is enabled but not APPROVED; network disabled for this source."
            )
    return manifest, warnings


def approved_network_sources(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    sources = manifest.get("sources", []) if isinstance(manifest.get("sources", []), list) else []
    return [
        source for source in sources
        if source.get("enabled")
        and source.get("requiresNetwork")
        and source.get("connectorStatus") == "APPROVED"
    ]


class P1008JobManager:
    def __init__(self, package_root: Path) -> None:
        self.package_root = package_root.resolve()
        self.resolved_package_root = str(self.package_root)
        self.git_head = git_head(self.package_root)
        self.server_instance_id = uuid.uuid4().hex
        self.lock = threading.Lock()
        self.active_thread: threading.Thread | None = None
        self.state = self._initial_state()

    @property
    def state_path(self) -> Path:
        return self.package_root / STATE_REL

    def _initial_state(self) -> dict[str, Any]:
        persisted = read_json(self.package_root / STATE_REL, default={}) or {}
        if persisted.get("status") == "RUNNING":
            persisted["status"] = "INTERRUPTED"
            persisted.setdefault("warnings", []).append("Server restarted while a previous job was RUNNING.")
        if persisted:
            return persisted
        return {
            "jobId": "",
            "jobType": "",
            "status": "IDLE",
            "startedAt": "",
            "finishedAt": "",
            "steps": [],
            "formalCsvModified": False,
            "errors": [],
            "warnings": [],
            "logPath": "",
            "componentStatus": {},
        }

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            state = dict(self.state)
        state["serverVersion"] = SERVER_VERSION
        state["resolvedPackageRoot"] = self.resolved_package_root
        state["gitHead"] = self.git_head
        authority_manifest = self.package_root / "data/CSV_AUTHORITY_MANIFEST.json"
        state["authorityManifestSha256"] = (
            sha256_file(authority_manifest) if authority_manifest.is_file() else "MISSING"
        )
        state["serverInstanceId"] = self.server_instance_id
        state["serverContext"] = server_context()
        state["pendingOwnerReview"] = self.pending_owner_review()
        state["sourceManifest"] = self.source_manifest_status()
        state["marketActivity"] = read_json(
            self.package_root / MARKET_ACTIVITY_STATUS_REL, default={}
        ) or {}
        state["latestReport"] = self.latest_report_status()
        state["reportTrigger"] = report_trigger_runtime.launcher_status(self.package_root)
        state["officialIR"] = read_json(
            self.package_root / OFFICIAL_IR_STATUS_REL, default={}
        ) or {}
        state["reviewPackage"] = self.review_package()
        state["launcherGate"] = self.launcher_gate_status(state["reviewPackage"], state)
        return state

    def source_manifest_status(self) -> dict[str, Any]:
        manifest, warnings = load_source_manifest(self.package_root)
        sources = manifest.get("sources", []) if isinstance(manifest.get("sources", []), list) else []
        approved = approved_network_sources(manifest)
        enabled_network = [
            source for source in sources
            if source.get("enabled") and source.get("requiresNetwork")
        ]
        pending_network = [
            source for source in enabled_network
            if source.get("connectorStatus") != "APPROVED"
        ]
        news = read_json(self.package_root / "runtime" / "warroom_news_scan_snapshot.json", default={}) or {}
        return {
            "path": SOURCE_MANIFEST_REL,
            "status": manifest.get("status", "UNKNOWN"),
            "version": manifest.get("manifestVersion", ""),
            "sourceCount": len(sources),
            "enabledNetworkCount": len(enabled_network),
            "approvedNetworkCount": len(approved),
            "pendingNetworkCount": len(pending_network),
            "networkSummary": news.get("networkSummary", {}) or {},
            "sourceHealth": news.get("sourceHealth", []) or [],
            "dependencyStatus": news.get("dependencyStatus", {}) or {},
            "warnings": warnings,
        }

    def pending_owner_review(self) -> dict[str, Any]:
        runtime = read_json(self.package_root / "runtime" / "warroom_realtime_snapshot.json", default={}) or {}
        news = read_json(self.package_root / "runtime" / "warroom_news_scan_snapshot.json", default={}) or {}
        review = read_json(self.package_root / "runtime" / "warroom_event_review_state.json", default={}) or {}
        pending = bool(runtime.get("ownerConfirmationRequired") or news.get("ownerConfirmationRequired") or review.get("ownerAckRequired"))
        return {
            "pending": pending,
            "runtimeCandidateDate": runtime.get("candidateDate", ""),
            "newsCandidateDate": news.get("candidateDate", ""),
            "reviewStatus": review.get("status", ""),
            "pendingReviewCount": len(review.get("pendingReviews", []) or []),
        }

    def latest_report_status(self) -> dict[str, Any]:
        manifest = read_json(self.package_root / "runtime" / "warroom_report_manifest.json", default={}) or {}
        latest = manifest.get("latest", {}) if isinstance(manifest.get("latest", {}), dict) else {}
        health = rolling_brief.report_library_health(self.package_root)
        return {
            "manifestPath": "runtime/warroom_report_manifest.json",
            "count": len(manifest.get("reports", []) or []),
            "latestDaily": latest.get("daily"),
            "latestWeekly": latest.get("weekly"),
            "latestMonthly": latest.get("monthly"),
            "latestRollingBriefDate": health.get("latestRollingBriefDate", ""),
            "latestArchivedReportDate": health.get("latestArchivedReportDate", ""),
            "health": health,
        }

    def _resolve_staging_dir(self, date_str: str | None = None) -> Path:
        if date_str:
            staging_dir = self.package_root / "staging" / date_str
            if not (staging_dir / "DRY_RUN.json").exists():
                raise FileNotFoundError(f"DRY_RUN not found for staging date {date_str}.")
            return staging_dir
        latest_date = latest_staging_date(self.package_root)
        if latest_date:
            staging_dir = self.package_root / "staging" / latest_date
            if (staging_dir / "DRY_RUN.json").exists():
                return staging_dir
        return owner_publish.latest_staging_dir(self.package_root)

    def review_package(self, date_str: str | None = None) -> dict[str, Any]:
        try:
            staging_dir = self._resolve_staging_dir(date_str)
            dry_run_path = staging_dir / "DRY_RUN.json"
            dry_run = owner_publish.read_json(dry_run_path)
            readiness = owner_publish.build_publish_readiness(self.package_root, dry_run)
            candidate_date = str(dry_run.get("candidateDate") or staging_dir.name)
            explanations = readiness_explanation_zh(readiness, candidate_date)
            generated_files = dry_run.get("generatedFiles", []) or []
            pending_owner = self.pending_owner_review()
            news = read_json(self.package_root / "runtime" / "warroom_news_scan_snapshot.json", default={}) or {}
            event_review = read_json(self.package_root / "runtime" / "warroom_event_review_state.json", default={}) or {}
            latest_report = self.latest_report_status()
            approval_phrase = f"OWNER_APPROVE_PUBLISH_{candidate_date}"
            return {
                "status": "READY",
                "stagingDate": staging_dir.name,
                "candidateDate": candidate_date,
                "dryRunPath": str(dry_run_path.relative_to(self.package_root)).replace("/", "\\"),
                "generatedFiles": generated_files,
                "candidatePending": bool(generated_files),
                "dailyRow": dry_run.get("dailyRow"),
                "macroSourceHealth": dry_run.get("macroSourceHealth", []) or [],
                "macroSourceSummary": dry_run.get("macroSourceSummary", {}) or {},
                "marketProxyManifest": dry_run.get("marketProxyManifest", []) or [],
                "readiness": readiness,
                "readinessExplanation": explanations,
                "marketContext": market_context(candidate_date),
                "ownerApprovalPhrase": approval_phrase,
                "pendingOwnerReview": pending_owner,
                "newsScan": {
                    "toolVersion": news.get("toolVersion", ""),
                    "generatedAt": news.get("generatedAt", ""),
                    "highestLevel": news.get("highestLevel", "NONE"),
                    "holdUnderReview": bool(news.get("holdUnderReview")),
                    "ownerReviewRequired": bool(news.get("ownerReviewRequired") or news.get("ownerConfirmationRequired")),
                    "candidateRowCount": int(news.get("candidateRowCount") or 0),
                    "rawEventCount": int(news.get("rawEventCount") or 0),
                    "discoveredEventCount": int(news.get("discoveredEventCount") or 0),
                    "ignoredEventCount": int(news.get("ignoredEventCount") or 0),
                    "reviewDeadline": news.get("reviewDeadline", ""),
                    "networkSummary": news.get("networkSummary", {}) or {},
                    "sourceHealth": news.get("sourceHealth", []) or [],
                    "dependencyStatus": news.get("dependencyStatus", {}) or {},
                    "warnings": news.get("warnings", []) or [],
                },
                "eventReview": {
                    "status": event_review.get("status", "NO_RUNTIME_STATE"),
                    "ownerAckRequired": bool(event_review.get("ownerAckRequired")),
                    "pendingReviews": event_review.get("pendingReviews", []) or [],
                },
                "latestReport": latest_report,
                "formalCsvHashes": formal_csv_hashes(self.package_root),
                "formalPublishAllowed": bool(readiness.get("allowed")) and bool(generated_files) and not readiness.get("noActionRequired"),
                "formalPublishRequired": bool(generated_files) and not readiness.get("noActionRequired"),
                "formalPublishBlocked": bool(generated_files) and not readiness.get("allowed"),
                "actionable": False,
            }
        except Exception as error:  # noqa: BLE001 - launcher should show a review error instead of crashing.
            return {
                "status": "ERROR",
                "error": str(error),
                "candidateDate": "",
                "stagingDate": "",
                "generatedFiles": [],
                "candidatePending": False,
                "readiness": {
                    "allowed": False,
                    "score": 0,
                    "threshold": owner_publish.MIN_PUBLISH_SCORE,
                    "blockers": [str(error)],
                    "candidateDiagnostics": [],
                    "warningsZh": [],
                },
                "formalPublishAllowed": False,
                "formalPublishRequired": False,
                "formalPublishBlocked": True,
                "actionable": False,
            }

    def launcher_gate_status(self, review_package: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
        if state is None:
            state = dict(self.state)
            state["latestReport"] = self.latest_report_status()
        latest_report = state.get("latestReport") or {}
        report_health = latest_report.get("health") or {}
        if report_health.get("status") != "PASS":
            return {
                "code": "REPORT_LIBRARY_FAIL_CLOSED",
                "zh": (
                    "Rolling brief／研報庫身分驗證未通過；新 UI 與研報庫入口已停用。"
                    f" 請依 Launcher health 指示修復：{report_health.get('code', 'UNKNOWN')}。"
                ),
                "canEnterNewUi": False,
            }
        if state.get("status") == "RUNNING":
            return {"code": "PIPELINE_RUNNING", "zh": "更新流程執行中，請留在 Launcher。", "canEnterNewUi": False}
        if state.get("errors"):
            return {"code": "PIPELINE_FAILED", "zh": "更新或發布流程有錯誤，請先在 Launcher 檢查 log。", "canEnterNewUi": False}
        if state.get("formalCsvModified") and not (
            state.get("jobType") == "owner-publish" and state.get("status") == "SUCCEEDED"
        ):
            return {"code": "FORMAL_CSV_BOUNDARY_VIOLATED", "zh": "正式 CSV hash 非預期改變，停止進入新 UI。", "canEnterNewUi": False}
        if review_package.get("status") == "ERROR":
            return {"code": "OWNER_REVIEW_REQUIRED", "zh": "無法建立審查包，請留在 Launcher。", "canEnterNewUi": False}
        pending_owner = review_package.get("pendingOwnerReview", {}) or {}
        news = review_package.get("newsScan", {}) or {}
        event_review = review_package.get("eventReview", {}) or {}
        if (
            review_package.get("candidatePending")
            or pending_owner.get("pending")
            or news.get("holdUnderReview")
            or news.get("ownerReviewRequired")
            or event_review.get("ownerAckRequired")
            or review_package.get("formalPublishBlocked")
        ):
            return {"code": "OWNER_REVIEW_REQUIRED", "zh": "存在候選 CSV、總經/新聞/FX 或 Owner 待決，需留在 Launcher 審查。", "canEnterNewUi": False}
        return {"code": "READY_TO_ENTER_NEW_UI", "zh": "無待決審查，可進入新 UI 決策摘要。", "canEnterNewUi": True}

    def start_job(self, job_type: str) -> tuple[int, dict[str, Any]]:
        with self.lock:
            if self.active_thread and self.active_thread.is_alive():
                state = dict(self.state)
                state["message"] = "A P1008 job is already running."
                return 409, state
            job_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{job_type}"
            log_rel = f"logs/p1008_app_{job_id}.log"
            self.state = {
                "jobId": job_id,
                "jobType": job_type,
                "status": "RUNNING",
                "startedAt": now_iso(),
                "finishedAt": "",
                "steps": [],
                "formalCsvModified": False,
                "formalCsvHashesBefore": {},
                "formalCsvHashesAfter": {},
                "errors": [],
                "warnings": [],
                "logPath": log_rel,
                "componentStatus": {},
            }
            self._persist_locked()
            thread = threading.Thread(target=self._run_job, args=(job_type, job_id), daemon=True)
            self.active_thread = thread
            thread.start()
            return 202, dict(self.state)

    def start_owner_publish(self, date_str: str | None, approval_phrase: str) -> tuple[int, dict[str, Any]]:
        with self.lock:
            if self.active_thread and self.active_thread.is_alive():
                state = dict(self.state)
                state["message"] = "A P1008 job is already running."
                return 409, state
            job_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-owner-publish"
            log_rel = f"logs/p1008_app_{job_id}.log"
            self.state = {
                "jobId": job_id,
                "jobType": "owner-publish",
                "status": "RUNNING",
                "startedAt": now_iso(),
                "finishedAt": "",
                "steps": [],
                "formalCsvModified": False,
                "formalCsvHashesBefore": {},
                "formalCsvHashesAfter": {},
                "errors": [],
                "warnings": [],
                "logPath": log_rel,
                "publishDate": date_str or "",
            }
            self._persist_locked()
            thread = threading.Thread(
                target=self._run_owner_publish_job,
                args=(job_id, date_str, approval_phrase),
                daemon=True,
            )
            self.active_thread = thread
            thread.start()
            return 202, dict(self.state)

    def _persist_locked(self) -> None:
        write_json(self.state_path, self.state)

    def _append_log(self, message: str) -> None:
        log_path = self.package_root / self.state["logPath"]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{now_iso()}] {message}\n")

    def _set_step(self, step_id: str, label: str, status: str, **extra: Any) -> None:
        with self.lock:
            steps = [step for step in self.state.get("steps", []) if step.get("id") != step_id]
            step = {"id": step_id, "label": label, "status": status, **extra}
            steps.append(step)
            self.state["steps"] = steps
            self._persist_locked()
        self._append_log(f"{step_id}: {status} {extra.get('message', '')}".rstrip())

    def _add_warning(self, warning: str) -> None:
        with self.lock:
            self.state.setdefault("warnings", []).append(warning)
            self._persist_locked()
        self._append_log(f"WARNING: {warning}")

    def _add_error(self, error: str) -> None:
        with self.lock:
            self.state.setdefault("errors", []).append(error)
            self._persist_locked()
        self._append_log(f"ERROR: {error}")

    def _run_job(self, job_type: str, job_id: str) -> None:
        try:
            self._run_job_inner(job_type)
            with self.lock:
                requested_status = self.state.get("overallStatus")
                self.state["status"] = requested_status or (
                    "FAILED" if self.state.get("errors") else "SUCCEEDED"
                )
                self.state["finishedAt"] = now_iso()
                self._persist_locked()
            self._append_log(f"JOB {job_id} finished with status={self.state['status']}")
        except Exception as error:  # noqa: BLE001 - local app should preserve unexpected failures in state.
            self._add_error(f"UNHANDLED: {error}")
            with self.lock:
                self.state["status"] = "FAILED"
                self.state["finishedAt"] = now_iso()
                self._persist_locked()

    def _run_owner_publish_job(self, job_id: str, date_str: str | None, approval_phrase: str) -> None:
        before = formal_csv_hashes(self.package_root)
        with self.lock:
            self.state["formalCsvHashesBefore"] = before
            self._persist_locked()
        try:
            self._run_owner_publish_inner(date_str, approval_phrase, before)
            with self.lock:
                self.state["status"] = "FAILED" if self.state.get("errors") else "SUCCEEDED"
                self.state["finishedAt"] = now_iso()
                self.state["pendingOwnerReview"] = self.pending_owner_review()
                self.state["reviewPackage"] = self.review_package()
                self._persist_locked()
            self._append_log(f"JOB {job_id} finished with status={self.state['status']}")
        except Exception as error:  # noqa: BLE001 - preserve unexpected failures in app state.
            self._add_error(f"UNHANDLED: {error}")
            with self.lock:
                self.state["status"] = "FAILED"
                self.state["finishedAt"] = now_iso()
                self._persist_locked()

    def _run_owner_publish_inner(self, date_str: str | None, approval_phrase: str, before: dict[str, str]) -> None:
        self._set_step("owner-review", "Build Owner review package", "RUNNING")
        review = self.review_package(date_str)
        if review.get("status") == "ERROR":
            message = review.get("error", "Review package failed.")
            self._set_step("owner-review", "Build Owner review package", "FAILED", message=message)
            self._add_error(message)
            return

        candidate_date = str(review.get("candidateDate") or date_str or "")
        expected_web_phrase = f"OWNER_APPROVE_PUBLISH_{candidate_date}"
        if approval_phrase.strip() != expected_web_phrase:
            message = f"Owner approval phrase mismatch. Expected {expected_web_phrase}."
            self._set_step("owner-review", "Build Owner review package", "FAILED", message=message)
            self._add_error(message)
            return
        if not review.get("formalPublishAllowed"):
            blockers = review.get("readiness", {}).get("blockers", []) or ["Formal publish is not allowed."]
            message = "; ".join(str(item) for item in blockers)
            self._set_step("owner-review", "Build Owner review package", "FAILED", message=message)
            self._add_error(message)
            return
        self._set_step("owner-review", "Build Owner review package", "SUCCEEDED", message=f"candidateDate={candidate_date}")

        self._set_step("owner-publish", "Owner formal CSV publish", "RUNNING")
        args = [
            str(self.package_root / "tools" / "owner_publish_csv_v2.py"),
            "--package-root",
            str(self.package_root),
            "--date",
            candidate_date,
            "--publish",
        ]
        started = time.monotonic()
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["P1008_APP_SERVER"] = "1"
        try:
            completed = subprocess.run(
                [sys.executable, *args],
                cwd=str(self.package_root),
                input=f"APPROVE {candidate_date}\n",
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=180,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            message = "Owner formal CSV publish timed out after 180s."
            self._append_log((error.stdout or "") + (error.stderr or ""))
            self._set_step("owner-publish", "Owner formal CSV publish", "FAILED", exitCode="TIMEOUT", durationSeconds=round(time.monotonic() - started, 2), message=message)
            self._add_error(message)
            return

        output = (completed.stdout or "") + (completed.stderr or "")
        if output.strip():
            self._append_log(output.rstrip())
        after = formal_csv_hashes(self.package_root)
        with self.lock:
            self.state["formalCsvHashesAfter"] = after
            self.state["formalCsvModified"] = after != before
            self.state["formalCsvModifiedExpected"] = completed.returncode == 0 and after != before
            self._persist_locked()
        status = "SUCCEEDED" if completed.returncode == 0 else "FAILED"
        self._set_step(
            "owner-publish",
            "Owner formal CSV publish",
            status,
            exitCode=completed.returncode,
            durationSeconds=round(time.monotonic() - started, 2),
            message=f"exit={completed.returncode}",
        )
        if completed.returncode != 0:
            self._add_error(f"Owner formal CSV publish failed with exit code {completed.returncode}.")

    def _run_job_inner(self, job_type: str) -> None:
        before = self._preflight()
        if self.state.get("errors"):
            self._refresh(before)
            return

        bootstrap_error = self._bootstrap_report_library_step()
        if bootstrap_error:
            self._add_error(bootstrap_error)
            self._refresh(before)
            return

        component_failures: list[str] = []
        if job_type in {"default", "update-data"}:
            daily_before = formal_csv_hashes(self.package_root)
            daily_exit = self._run_bat_step(
                "daily-price-authority",
                "TWSE Daily Price incremental authority update",
                self.package_root / "P1008_1A_UPDATE_DAILY_PRICE.bat",
                [],
                timeout_seconds=180,
            )
            daily_after = formal_csv_hashes(self.package_root)
            daily_result = read_json(
                self.package_root / DAILY_PRICE_STATUS_REL, default={}
            ) or {}
            daily_status = str(daily_result.get("launcher_status") or "BLOCKED")
            daily_boundary = self._daily_price_boundary_error(
                daily_before, daily_after, daily_status
            )
            if daily_exit != 0 or daily_boundary:
                daily_status = "FAILED"
                reason = daily_boundary or f"Daily Price BAT exit={daily_exit}"
                component_failures.append(reason)
            self._set_component_status(
                "dailyPrice",
                daily_status,
                exitCode=daily_exit,
                lastSuccessDate=daily_result.get("last_success_date", ""),
                receiptPaths=daily_result.get("receipt_paths", []) or [],
            )

            if daily_status == "FAILED":
                market_status = "BLOCKED"
                market_result = self._write_launcher_market_status(
                    "MARKET_ACTIVITY_BLOCKED_BY_DAILY_PRICE",
                    market_status,
                    "Daily Price failed; no market-activity publish was attempted",
                )
                self._set_step(
                    "market-activity",
                    "TWSE market activity incremental update",
                    "BLOCKED",
                    message="BLOCKED_BY_DAILY_PRICE",
                )
                component_failures.append("Market Activity blocked by failed Daily Price step")
            else:
                market_before = formal_csv_hashes(self.package_root)
                market_exit = self._run_bat_step(
                    "market-activity",
                    "TWSE market activity incremental update",
                    self.package_root / "P1008_1B_UPDATE_MARKET_ACTIVITY.bat",
                    [],
                    timeout_seconds=180,
                )
                market_after = formal_csv_hashes(self.package_root)
                market_result = read_json(
                    self.package_root / MARKET_ACTIVITY_STATUS_REL, default={}
                ) or {}
                market_status = str(market_result.get("launcher_status") or "STALE")
                boundary_error = self._market_activity_boundary_error(
                    market_before, market_after, market_status
                )
                if market_exit != 0 or boundary_error:
                    market_status = (
                        "BLOCKED"
                        if market_result.get("status") == "MARKET_ACTIVITY_BLOCKED_BY_DAILY_PRICE"
                        else "STALE"
                    )
                    failure = boundary_error or f"Market Activity BAT exit={market_exit}"
                    component_failures.append(failure)
                    market_result = self._write_launcher_market_status(
                        (
                            "MARKET_ACTIVITY_BLOCKED_BY_DAILY_PRICE"
                            if market_status == "BLOCKED"
                            else "MARKET_ACTIVITY_STALE"
                        ),
                        market_status,
                        failure,
                    )
                if not component_failures:
                    receipt_paths = market_result.get("receipt_paths", []) or []
                    receipt_dir = (
                        str(Path(receipt_paths[0]).parent) if receipt_paths else ""
                    )
                    freshness_exit = self._run_bat_step(
                        "authority-freshness",
                        "TWSE authority freshness and continuity gate",
                        self.package_root / "tools/p1008_validate_authority_freshness.cmd",
                        ["--receipt-dir", receipt_dir],
                        timeout_seconds=60,
                    )
                    freshness_result = read_json(
                        self.package_root / FRESHNESS_STATUS_REL, default={}
                    ) or {}
                    freshness_status = str(
                        freshness_result.get("status") or "FAIL_CLOSED"
                    )
                    self._set_component_status(
                        "freshness",
                        freshness_status,
                        exitCode=freshness_exit,
                        twseLatestDate=freshness_result.get(
                            "twse_latest_validated_trading_date", ""
                        ),
                    )
                    if freshness_exit != 0:
                        component_failures.append(
                            f"Authority Freshness BAT exit={freshness_exit}"
                        )
            self._set_component_status(
                "marketActivity",
                market_status,
                exitCode=(None if daily_status == "FAILED" else market_exit),
                statusCode=market_result.get("status", ""),
                lastSuccessDate=(market_result.get("last_success_date") or self._market_activity_last_date()),
                receiptPaths=market_result.get("receipt_paths", []) or [],
                logPath=(market_result.get("run_dir") or "logs/last_market_activity_update.log"),
            )

            if not component_failures:
                other_data_exit = self._run_bat_step(
                    "update-data",
                    "Other staging/runtime data update",
                    self.package_root / "P1008_1_UPDATE_DATA.bat",
                    [],
                    timeout_seconds=420,
                )
                if other_data_exit != 0:
                    component_failures.append(f"Other Data BAT exit={other_data_exit}")

        if job_type in {"default", "news-scan"} and not component_failures:
            self._run_news_scan_step()
            news_step = next(
                (step for step in self.state.get("steps", []) if step.get("id") == "news-scan"),
                {},
            )
            news_status = (
                "FAILED"
                if news_step.get("status") != "SUCCEEDED"
                else (
                    "UPDATED"
                    if (read_json(self.package_root / "runtime/warroom_news_scan_snapshot.json", default={}) or {}).get("candidateRowCount", 0)
                    else "NO_CHANGE"
                )
            )
            self._set_component_status("news", news_status, exitCode=news_step.get("exitCode"))

        if job_type in {"default", "news-scan", "official-ir-scan"} and not component_failures:
            self._run_official_ir_step()
            official_step = next(
                (step for step in self.state.get("steps", []) if step.get("id") == "official-ir-scan"),
                {},
            )
            official = read_json(self.package_root / OFFICIAL_IR_STATUS_REL, default={}) or {}
            official_status = str(official.get("status") or "FAIL_CLOSED")
            if official_step.get("status") != "SUCCEEDED":
                official_status = "FAIL_CLOSED"
                component_failures.append("REPORT_TRIGGER_EVIDENCE_INCOMPLETE")
            detected = official.get("detected_evidence") or []
            first = detected[0] if detected else {}
            self._set_component_status(
                "officialIR", official_status,
                event=official.get("canonical_event_id", ""),
                fiscalPeriod=(official.get("schedule") or {}).get("fiscal_period", ""),
                officialSource=first.get("source_id", "") or (official.get("schedule") or {}).get("source_id", ""),
                documentType=(first.get("quality_metadata") or {}).get("document_type", ""),
                retrievedAt=official.get("evaluated_at_utc", ""),
                sourceScanComplete=official.get("source_scan_complete") is True,
                actionable=False,
            )

        if job_type in {"default", "news-scan", "official-ir-scan"} and not component_failures:
            self._evaluate_report_trigger_step()

        if job_type == "default" and not component_failures:
            rolling_error = self._refresh_rolling_brief_step()
            if rolling_error:
                component_failures.append(rolling_error)

        if job_type == "report":
            self._evaluate_report_trigger_step()
        if job_type in {"analysis-candidate", "report-candidate"}:
            is_analysis = job_type == "analysis-candidate"
            try:
                trigger = report_trigger_runtime.require_valid_trigger(self.package_root)
                if not is_analysis:
                    report_trigger_runtime.require_analysis_candidate(self.package_root, trigger)
            except report_trigger_runtime.RuntimeTriggerError as exc:
                code = "REPORT_TRIGGER_REQUIRED" if is_analysis else "ANALYSIS_CANDIDATE_REQUIRED"
                self._set_step(
                    job_type,
                    "Build Phase B1 Analysis candidate" if is_analysis else "Build Phase B1 Report candidate",
                    "BLOCKED",
                    code=code,
                    message=str(exc),
                    actionable=False,
                )
                self._set_component_status(
                    "phaseB1", "FAIL_CLOSED", code=code, actionable=False
                )
                self._refresh(before)
                return
            bat_name = "P1008_BUILD_ANALYSIS.bat" if is_analysis else "P1008_BUILD_REPORT.bat"
            label = "Build Phase B1 Analysis candidate" if is_analysis else "Build Phase B1 Report candidate"
            exit_code = self._run_bat_step(
                job_type,
                label,
                self.package_root / bat_name,
                [],
                timeout_seconds=180,
            )
            latest = self._latest_phaseb1_status()
            status = (
                "ANALYSIS_CANDIDATE_READY"
                if is_analysis and exit_code == 0
                else "REPORT_CANDIDATE_READY"
                if not is_analysis and exit_code == 0
                else "FAIL_CLOSED"
            )
            self._set_component_status(
                "phaseB1",
                status,
                runId=latest.get("runId", ""),
                outputPath=latest.get("outputPath", ""),
                actionable=False,
            )
        if job_type in {"default", "update-data", "official-ir-scan"}:
            if component_failures:
                for failure in component_failures:
                    self._add_error(failure)
            components = self.state.get("componentStatus", {}) or {}
            partial = any(
                str((components.get(name) or {}).get("status", ""))
                in {"FAILED", "STALE", "BLOCKED", "FAIL_CLOSED"}
                for name in ("dailyPrice", "marketActivity", "news", "officialIR", "rollingBrief", "reportLibrary")
            )
            with self.lock:
                self.state["overallStatus"] = "PARTIAL_FAILURE" if partial else "SUCCEEDED"
                self._persist_locked()
        self._refresh(
            before,
            allow_authority_change=job_type in {"default", "update-data"},
        )

    def _evaluate_report_trigger_step(self) -> None:
        """Evaluate and persist G1 state; never start candidate production."""
        self._set_step(
            "report-governance", "Reconcile validated evidence and evaluate report trigger", "RUNNING"
        )
        try:
            receipt = report_trigger_runtime.evaluate_and_persist(
                self.package_root, evaluated_at_utc=now_iso()
            )
        except (report_trigger_runtime.RuntimeTriggerError, report_governance.GovernanceValidationError) as exc:
            self._set_step(
                "report-governance", "Reconcile validated evidence and evaluate report trigger",
                "FAIL_CLOSED", message=str(exc), actionable=False,
            )
            self._set_component_status(
                "reportGovernance", "FAIL_CLOSED", reportTriggerValid=False,
                archiveEligible=False, libraryAppended=False, error=str(exc), actionable=False,
            )
            return
        self._set_step(
            "report-governance", "Reconcile validated evidence and evaluate report trigger",
            "SUCCEEDED", decision=receipt["decision"], decisionId=receipt["decision_id"],
            actionable=False,
        )
        self._set_component_status(
            "reportGovernance", receipt["decision"], reportKey=receipt["report_key"],
            revision=receipt["revision"], eventType=receipt["event_type"],
            validationState=receipt["cross_validation"]["validation_status"],
            reportTriggerValid=receipt["report_trigger_valid"],
            materialEventConfirmed=receipt["material_event_confirmed"],
            archiveEligible=False, libraryAppended=False, reportGenerated=False,
            actionable=False,
        )

    def _set_component_status(self, component: str, status: str, **extra: Any) -> None:
        with self.lock:
            components = dict(self.state.get("componentStatus", {}) or {})
            components[component] = {"status": status, **extra}
            self.state["componentStatus"] = components
            self._persist_locked()

    def _refresh_rolling_brief_step(self) -> str:
        """Refresh the current view and verify archive-index consistency."""
        self._set_step(
            "rolling-brief",
            "Refresh rolling current war-room brief",
            "RUNNING",
        )
        try:
            result = rolling_brief.refresh_current_brief(self.package_root)
        except (rolling_brief.RollingBriefError, OSError) as exc:
            message = str(exc)
            self._set_step(
                "rolling-brief",
                "Refresh rolling current war-room brief",
                "FAILED",
                message=message,
            )
            self._set_component_status(
                "rollingBrief", "FAILED", error=message, actionable=False
            )
            return f"Rolling brief refresh failed: {message}"

        self._set_step(
            "rolling-brief",
            "Refresh rolling current war-room brief",
            "SUCCEEDED",
            message=result.get("authorityDate", ""),
        )
        self._set_component_status(
            "rollingBrief",
            "UPDATED",
            authorityDate=result.get("authorityDate", ""),
            dataCutoffs=result.get("dataCutoffs", {}),
            dataAlignmentStatus=result.get("dataAlignmentStatus", ""),
            marketActivityFreshness=result.get("marketActivityFreshness", {}),
            briefContentSha256=result.get("briefContentSha256", ""),
            briefPath=result.get("briefPath", ""),
            htmlPath=result.get("htmlPath", ""),
            archiveAppended=False,
            actionable=False,
        )
        health = rolling_brief.report_library_health(self.package_root)
        health_status = str(health.get("status") or "FAIL_CLOSED")
        self._set_component_status(
            "reportLibrary",
            health_status,
            code=health.get("code", ""),
            latestArchivedReportDate=health.get("latestArchivedReportDate", ""),
            recoveryInstruction=health.get("recoveryInstruction", ""),
            actionable=False,
        )
        if health_status != "PASS":
            return (
                "Report library health check failed: "
                f"{health.get('code', 'UNKNOWN')} — {health.get('message', '')}"
            )
        return ""

    def _bootstrap_report_library_step(self) -> str:
        """Initialize only a truly empty archive index before the default job.

        Archive history is never recreated when one paired manifest is lost or
        both manifests disagree.  Those conditions remain fail-closed.
        """
        self._set_step(
            "report-library-bootstrap",
            "Validate or initialize report-library manifests",
            "RUNNING",
        )
        try:
            result = rolling_brief.bootstrap_report_library(self.package_root)
        except (rolling_brief.RollingBriefError, OSError) as exc:
            message = str(exc)
            self._set_step(
                "report-library-bootstrap",
                "Validate or initialize report-library manifests",
                "FAILED",
                message=message,
            )
            self._set_component_status(
                "reportLibrary", "FAIL_CLOSED", error=message, actionable=False
            )
            return f"Report library bootstrap failed: {message}"
        status = str(result.get("status") or "FAIL_CLOSED")
        if status == "FAIL_CLOSED":
            message = str(result.get("message") or result.get("code") or "unknown error")
            self._set_step(
                "report-library-bootstrap",
                "Validate or initialize report-library manifests",
                "FAILED",
                message=message,
                code=result.get("code", ""),
            )
            self._set_component_status(
                "reportLibrary",
                "FAIL_CLOSED",
                code=result.get("code", ""),
                recoveryInstruction=result.get("message", ""),
                actionable=False,
            )
            return f"Report library bootstrap failed: {message}"
        self._set_step(
            "report-library-bootstrap",
            "Validate or initialize report-library manifests",
            "SUCCEEDED",
            message=status,
        )
        self._set_component_status(
            "reportLibrary",
            status,
            code=result.get("classification", ""),
            archiveReportCount=result.get("archiveReportCount", 0),
            archiveAppended=False,
            actionable=False,
        )
        return ""

    def _market_activity_last_date(self) -> str:
        path = self.package_root / "data/2317_daily_market_activity.csv"
        try:
            with path.open("r", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            return rows[-1].get("date", "") if rows else ""
        except OSError:
            return ""

    def _latest_phaseb1_status(self) -> dict[str, str]:
        root = self.package_root / "runtime" / "report_production"
        candidates: list[tuple[str, dict[str, Any], Path]] = []
        if root.is_dir():
            for path in root.glob("*/run_manifest.json"):
                payload = read_json(path, default={}) or {}
                if payload.get("eventType") == "MONTHLY_REVENUE":
                    candidates.append((str(payload.get("generatedAtUtc") or ""), payload, path.parent))
        if not candidates:
            return {"runId": "", "outputPath": ""}
        _timestamp, payload, output_path = sorted(candidates, key=lambda item: (item[0], str(item[2])))[-1]
        return {
            "runId": str(payload.get("runId") or ""),
            "outputPath": str(output_path),
        }

    def _write_launcher_market_status(
        self, status: str, launcher_status: str, error: str
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": status,
            "launcher_status": launcher_status,
            "market_liquidity_analysis_status": "MARKET_LIQUIDITY_ANALYSIS_LIMITED",
            "last_success_date": self._market_activity_last_date(),
            "receipt_paths": [],
            "run_dir": "logs/last_market_activity_update.log",
            "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "P1008 Launcher",
            "error": error,
            "actionable": False,
        }
        write_json(self.package_root / MARKET_ACTIVITY_STATUS_REL, payload)
        return payload

    @staticmethod
    def _daily_price_boundary_error(
        before: dict[str, str], after: dict[str, str], launcher_status: str
    ) -> str:
        allowed = {"data/2317_daily_price.csv", "data/CSV_AUTHORITY_MANIFEST.json"}
        changed = {key for key in before if before.get(key) != after.get(key)}
        unexpected = changed - allowed
        if unexpected:
            return "Daily Price changed unauthorized formal files: " + ", ".join(
                sorted(unexpected)
            )
        if launcher_status == "UPDATED" and changed != allowed:
            return "Daily Price UPDATED did not atomically change CSV and manifest only"
        if launcher_status != "UPDATED" and changed:
            return "Daily Price non-update status changed formal CSV or manifest"
        return ""

    @staticmethod
    def _market_activity_boundary_error(
        before: dict[str, str], after: dict[str, str], launcher_status: str
    ) -> str:
        allowed = {
            "data/2317_daily_market_activity.csv",
            "data/CSV_AUTHORITY_MANIFEST.json",
        }
        changed = {key for key in before if before.get(key) != after.get(key)}
        unexpected = changed - allowed
        if unexpected:
            return "Market Activity changed unauthorized formal files: " + ", ".join(
                sorted(unexpected)
            )
        if launcher_status == "UPDATED" and changed != allowed:
            return "Market Activity UPDATED did not atomically change CSV and manifest only"
        if launcher_status != "UPDATED" and changed:
            return "Market Activity non-update status changed formal CSV or manifest"
        return ""

    def _preflight(self) -> dict[str, str]:
        self._set_step("preflight", "Preflight checks", "RUNNING")
        required = [
            "ui/P1008_WARROOM_COMMAND_CENTER_v24.html",
            "tools/warroom_data_fetcher_v2.py",
            "tools/warroom_daily_price_updater.py",
            "tools/warroom_market_activity_updater.py",
            "tools/warroom_authority_freshness.py",
            "P1008_1_UPDATE_DATA.bat",
            "P1008_1A_UPDATE_DAILY_PRICE.bat",
            "P1008_1B_UPDATE_MARKET_ACTIVITY.bat",
            "tools/p1008_validate_authority_freshness.cmd",
            "tools/warroom_news_scanner_v2.py",
            "tools/warroom_periodic_report_v1.py",
            SOURCE_MANIFEST_REL,
        ]
        missing = [rel for rel in required if not (self.package_root / rel).exists()]
        before = formal_csv_hashes(self.package_root)
        manifest, warnings = load_source_manifest(self.package_root)
        for warning in warnings:
            self._add_warning(warning)
        with self.lock:
            self.state["formalCsvHashesBefore"] = before
            self.state["sourceManifestStatus"] = manifest.get("status", "UNKNOWN")
            self._persist_locked()
        if missing:
            message = "Missing required files: " + ", ".join(missing)
            self._set_step("preflight", "Preflight checks", "FAILED", message=message)
            self._add_error(message)
        else:
            self._set_step("preflight", "Preflight checks", "SUCCEEDED", message="Python, manifests, and package files are present.")
        return before

    def _run_news_scan_step(self) -> None:
        manifest, warnings = load_source_manifest(self.package_root)
        for warning in warnings:
            if warning not in self.state.get("warnings", []):
                self._add_warning(warning)
        approved_network = approved_network_sources(manifest)
        args = [
            str(self.package_root / "tools" / "warroom_news_scanner_v2.py"),
            "--package-root",
            str(self.package_root),
            "--dry-run",
            "--scan-window",
            "auto",
        ]
        if approved_network:
            args.append("--allow-network")
            self._add_warning("News scanner v2 will fetch enabled APPROVED public sources; outputs remain observation-only.")
        else:
            args.append("--no-network")
            self._add_warning("No approved network news connector; news scan ran no-network.")
        self._run_python_step("news-scan", "Observation-only news scan v2", args, timeout_seconds=240)

    def _run_official_ir_step(self) -> None:
        """Scan fixed authorized Official IR sources; never generate content."""
        args = [
            str(self.package_root / "tools" / "warroom_official_ir_ingestion.py"),
            "--package-root",
            str(self.package_root),
        ]
        self._run_python_step(
            "official-ir-scan", "Governed Official IR evidence scan", args,
            timeout_seconds=90,
        )

    def _run_bat_step(
        self,
        step_id: str,
        label: str,
        bat_path: Path,
        args: list[str],
        timeout_seconds: int,
    ) -> int | None:
        command = [os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"), "/d", "/c", str(bat_path), *args]
        self._set_step(step_id, label, "RUNNING", command=command)
        started = time.monotonic()
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["P1008_APP_SERVER"] = "1"
        env["P1008_NO_PAUSE"] = "1"
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.package_root),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout_seconds,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            output = (error.stdout or "") + (error.stderr or "")
            if output.strip():
                self._append_log(output.rstrip())
            self._set_step(
                step_id,
                label,
                "FAILED",
                exitCode="TIMEOUT",
                durationSeconds=round(time.monotonic() - started, 2),
                message=f"timed out after {timeout_seconds}s",
            )
            return None
        output = (completed.stdout or "") + (completed.stderr or "")
        if output.strip():
            self._append_log(output.rstrip())
        status = "SUCCEEDED" if completed.returncode == 0 else "FAILED"
        self._set_step(
            step_id,
            label,
            status,
            exitCode=completed.returncode,
            durationSeconds=round(time.monotonic() - started, 2),
            message=f"exit={completed.returncode}",
        )
        return completed.returncode

    def _run_python_step(
        self,
        step_id: str,
        label: str,
        args: list[str],
        timeout_seconds: int,
        *,
        allow_after_errors: bool = False,
    ) -> None:
        if self.state.get("errors") and not allow_after_errors:
            return
        self._set_step(step_id, label, "RUNNING", command=[sys.executable, *args])
        started = time.monotonic()
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["P1008_APP_SERVER"] = "1"
        try:
            completed = subprocess.run(
                [sys.executable, *args],
                cwd=str(self.package_root),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout_seconds,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            message = f"{label} timed out after {timeout_seconds}s."
            self._append_log((error.stdout or "") + (error.stderr or ""))
            self._set_step(step_id, label, "FAILED", exitCode="TIMEOUT", durationSeconds=round(time.monotonic() - started, 2), message=message)
            self._add_error(message)
            return
        output = (completed.stdout or "") + (completed.stderr or "")
        if output.strip():
            self._append_log(output.rstrip())
        status = "SUCCEEDED" if completed.returncode == 0 else "FAILED"
        message = f"exit={completed.returncode}"
        self._set_step(step_id, label, status, exitCode=completed.returncode, durationSeconds=round(time.monotonic() - started, 2), message=message)
        if completed.returncode != 0:
            self._add_error(f"{label} failed with exit code {completed.returncode}.")

    def _assert_hashes_unchanged(self, before: dict[str, str]) -> None:
        after = formal_csv_hashes(self.package_root)
        with self.lock:
            self.state["formalCsvHashesAfter"] = after
            self.state["formalCsvModified"] = after != before
            self._persist_locked()
        if after != before:
            self._add_error("Formal CSV hash changed during app pipeline; stopping before any further action.")

    def _refresh(
        self, before: dict[str, str], *, allow_authority_change: bool = False
    ) -> None:
        self._set_step("refresh", "Refresh app state", "RUNNING")
        after = formal_csv_hashes(self.package_root)
        latest_date = latest_staging_date(self.package_root)
        with self.lock:
            self.state["formalCsvHashesAfter"] = after
            self.state["formalCsvModified"] = after != before
            changed = {key for key in before if before.get(key) != after.get(key)}
            expected_authority_change = (
                allow_authority_change
                and bool(changed)
                and changed.issubset(
                    {
                        "data/2317_daily_price.csv",
                        "data/2317_daily_market_activity.csv",
                        "data/CSV_AUTHORITY_MANIFEST.json",
                    }
                )
            )
            self.state["formalCsvModifiedExpected"] = expected_authority_change
            self.state["latestStagingDate"] = latest_date or date.today().isoformat()
            self.state["pendingOwnerReview"] = self.pending_owner_review()
            if after != before and not expected_authority_change:
                self.state.setdefault("errors", []).append("Formal CSV hash changed; Owner gate boundary violated.")
                self.state["status"] = "FAILED"
            self._persist_locked()
        self._set_step("refresh", "Refresh app state", "SUCCEEDED", message=f"latestStagingDate={latest_date or 'N/A'}")


class P1008AppHandler(http.server.SimpleHTTPRequestHandler):
    manager: P1008JobManager

    def guess_type(self, path: str) -> str:
        ext = Path(path).suffix.lower()
        mime_type = UTF8_MIME_TYPES.get(ext)
        if mime_type:
            return f"{mime_type}; charset=utf-8"
        return super().guess_type(path)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - inherited signature.
        sys.stdout.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, status: int, text: str) -> None:
        body = text.encode("utf-8", errors="replace")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSON body: {error}") from error
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object.")
        return payload

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler hook.
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/p1008/status":
            self._send_json(200, self.manager.snapshot())
            return
        if parsed.path == "/api/p1008/review-package":
            query = urllib.parse.parse_qs(parsed.query)
            date_str = (query.get("date") or [""])[0] or None
            review = self.manager.review_package(date_str)
            payload = dict(review)
            payload["launcherGate"] = self.manager.launcher_gate_status(review)
            self._send_json(200, payload)
            return
        if parsed.path == "/api/p1008/log":
            query = urllib.parse.parse_qs(parsed.query)
            job_id = (query.get("jobId") or [""])[0]
            state = self.manager.snapshot()
            if job_id and job_id != state.get("jobId"):
                self._send_text(404, "Unknown jobId")
                return
            log_rel = state.get("logPath") or ""
            log_path = self.manager.package_root / log_rel
            if not log_path.exists():
                self._send_text(200, "")
                return
            self._send_text(200, log_path.read_text(encoding="utf-8", errors="replace")[-20000:])
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler hook.
        parsed = urllib.parse.urlparse(self.path)
        routes = {
            "/api/p1008/run/default": "default",
            "/api/p1008/run/update-data": "update-data",
            "/api/p1008/run/news-scan": "news-scan",
            "/api/p1008/run/official-ir-scan": "official-ir-scan",
            "/api/p1008/run/report": "report",
            "/api/p1008/run/analysis-candidate": "analysis-candidate",
            "/api/p1008/run/report-candidate": "report-candidate",
        }
        if parsed.path in {"/api/p1008/publish/formal", "/api/p1008/owner-publish/formal"}:
            try:
                body = self._read_json_body()
            except ValueError as error:
                self._send_json(400, {"error": str(error)})
                return
            date_str = str(body.get("date") or "").strip() or None
            approval_phrase = str(body.get("approvalPhrase") or "").strip()
            status, payload = self.manager.start_owner_publish(date_str, approval_phrase)
            self._send_json(status, payload)
            return
        job_type = routes.get(parsed.path)
        if not job_type:
            self._send_json(404, {"error": "Unknown API route"})
            return
        status, payload = self.manager.start_job(job_type)
        self._send_json(status, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve P1008 local app and whitelisted control API.")
    parser.add_argument("port", type=int)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--directory", type=Path, default=Path.cwd())
    args = parser.parse_args()

    package_root = args.directory.resolve()
    manager = P1008JobManager(package_root)

    handler = lambda *h_args, **h_kwargs: P1008AppHandler(
        *h_args,
        directory=str(package_root),
        **h_kwargs,
    )
    P1008AppHandler.manager = manager
    httpd = http.server.ThreadingHTTPServer((args.bind, args.port), handler)
    print(f"Serving P1008 app at http://{args.bind}:{args.port}/ from {package_root}")
    print("P1008 app API enabled: /api/p1008/status, /api/p1008/review-package")
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
