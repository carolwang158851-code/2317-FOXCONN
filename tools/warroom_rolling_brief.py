#!/usr/bin/env python3
"""Build and validate the non-archival P1008 rolling war-room brief.

The rolling brief is deliberately separate from the research library.  A
default Launcher update may overwrite the two current-view artifacts, but it
must never append a report card or mutate an archive manifest.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CURRENT_BRIEF_REL = "runtime/current_warroom_brief.json"
LATEST_REPORT_REL = "reports/generated/latest_report.html"
RUNTIME_MANIFEST_REL = "runtime/warroom_report_manifest.json"
REPORT_MANIFEST_REL = "reports/P1008_REPORT_MANIFEST.json"
AUTHORITY_MANIFEST_REL = "data/CSV_AUTHORITY_MANIFEST.json"
RECOVERY_INSTRUCTION = (
    "請從套件根目錄執行 P1008_APP.bat；若研報 manifest 仍缺少或不一致，"
    "請在 Launcher 明確執行『產生日報』建立或修復歸檔索引。"
)


class RollingBriefError(RuntimeError):
    """Raised when a current brief cannot be built without inventing data."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RollingBriefError(f"Cannot read valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise RollingBriefError(f"JSON root must be an object: {path}")
    return value


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _latest_csv_row(path: Path, date_field: str) -> dict[str, str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        raise RollingBriefError(f"Cannot read authority CSV: {path}") from exc
    valid = [row for row in rows if str(row.get(date_field) or "").strip()]
    if not valid:
        raise RollingBriefError(f"Authority CSV has no dated rows: {path}")
    valid.sort(key=lambda row: str(row[date_field]))
    return valid[-1]


def _utc_timestamp(now: datetime | None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _brief_html(brief: dict[str, Any]) -> str:
    price = brief["marketBaseline"]["dailyPrice"]
    activity = brief["marketBaseline"].get("marketActivity") or {}
    generated = html.escape(str(brief["generatedAtUtc"]))
    authority_date = html.escape(str(brief["authorityDate"]))
    brief_id = html.escape(str(brief["briefId"]))
    close = html.escape(str(price.get("close") or "資料未提供"))
    pb = html.escape(str(price.get("pbDaily") or "資料未提供"))
    volume = html.escape(str(activity.get("tradeVolume") or "資料未提供"))
    turnover = html.escape(str(activity.get("tradeValue") or "資料未提供"))
    return f"""<!doctype html>
<html lang="zh-TW" data-p1008-brief-id="{brief_id}" data-authority-date="{authority_date}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="p1008-report-kind" content="ROLLING_CURRENT_BRIEF" />
  <title>P1008 當前戰情快報 — {authority_date}</title>
  <style>
    body {{ margin:0; background:#07111f; color:#e8f3ff; font-family:Arial,'Microsoft JhengHei',sans-serif; }}
    main {{ max-width:1000px; margin:auto; padding:36px 22px; }}
    .panel {{ background:#0f1b2c; border:1px solid #274761; border-radius:16px; padding:22px; margin:16px 0; }}
    h1 {{ color:#67e8f9; }} .muted {{ color:#9fb3c8; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }}
    .kpi {{ background:#091522; border-radius:10px; padding:14px; }}
  </style>
</head>
<body><main>
  <p class="muted">Rolling current brief｜不納入研報庫｜actionable=false</p>
  <h1>P1008 當前戰情快報</h1>
  <p>權威資料日：{authority_date}｜刷新時間：{generated}</p>
  <section class="panel">
    <h2>市場資料基線</h2>
    <div class="grid">
      <div class="kpi">收盤價<br><strong>{close}</strong></div>
      <div class="kpi">P/B<br><strong>{pb}</strong></div>
      <div class="kpi">成交股數<br><strong>{volume}</strong></div>
      <div class="kpi">成交金額（新台幣元）<br><strong>{turnover}</strong></div>
    </div>
  </section>
  <section class="panel">
    <h2>說明</h2>
    <p>此頁由 Launcher 預設更新流程以正式 authority 最新列重新整理；不建立研報卡片、不追加歸檔，也不改變正式資料或治理狀態。</p>
  </section>
</main></body></html>
"""


def refresh_current_brief(
    package_root: Path, *, now: datetime | None = None
) -> dict[str, Any]:
    """Overwrite the two current-view artifacts without touching archives."""
    root = package_root.resolve()
    authority_manifest = root / AUTHORITY_MANIFEST_REL
    if not authority_manifest.is_file():
        raise RollingBriefError(f"Missing authority manifest: {AUTHORITY_MANIFEST_REL}")
    # Parse the manifest as a fail-closed format check before trusting its hash.
    _read_json(authority_manifest)
    price = _latest_csv_row(root / "data/2317_daily_price.csv", "Date")
    activity_path = root / "data/2317_daily_market_activity.csv"
    activity = _latest_csv_row(activity_path, "date") if activity_path.is_file() else {}
    authority_date = str(price["Date"])
    generated_at = _utc_timestamp(now)
    brief_id = f"P1008-CURRENT-{authority_date.replace('-', '')}"
    brief: dict[str, Any] = {
        "schemaVersion": "1.0",
        "briefId": brief_id,
        "recordType": "ROLLING_CURRENT_BRIEF",
        "generatedAtUtc": generated_at,
        "authorityDate": authority_date,
        "authorityManifestSha256": sha256_file(authority_manifest),
        "marketBaseline": {
            "dailyPrice": {
                "date": price.get("Date", ""),
                "close": price.get("Close", ""),
                "pbDaily": price.get("PB_daily", ""),
                "sourceLevel": price.get("DataSupportLevel", ""),
            },
            "marketActivity": (
                {
                    "date": activity.get("date", ""),
                    "tradeVolume": activity.get("trade_volume", ""),
                    "tradeValue": activity.get("trade_value", ""),
                    "transactionCount": activity.get("transaction_count", ""),
                    "sourceUrl": activity.get("source_url", ""),
                }
                if activity
                else None
            ),
        },
        "archiveEligible": False,
        "libraryAppended": False,
        "actionable": False,
    }
    json_bytes = (json.dumps(brief, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    html_bytes = _brief_html(brief).encode("utf-8")
    _atomic_write_bytes(root / CURRENT_BRIEF_REL, json_bytes)
    _atomic_write_bytes(root / LATEST_REPORT_REL, html_bytes)
    return {
        "status": "ROLLING_BRIEF_UPDATED",
        "briefId": brief_id,
        "authorityDate": authority_date,
        "generatedAtUtc": generated_at,
        "briefPath": CURRENT_BRIEF_REL,
        "briefSha256": sha256_file(root / CURRENT_BRIEF_REL),
        "htmlPath": LATEST_REPORT_REL,
        "htmlSha256": sha256_file(root / LATEST_REPORT_REL),
        "archiveAppended": False,
        "actionable": False,
    }


def _latest_archive_date(manifest: dict[str, Any]) -> str:
    dates = [
        str(item.get("date") or "")
        for item in (manifest.get("reports") or [])
        if isinstance(item, dict) and item.get("date")
    ]
    return max(dates, default="")


def report_library_health(package_root: Path) -> dict[str, Any]:
    """Verify archive-manifest identity and current brief/HTML identity."""
    root = package_root.resolve()
    runtime_path = root / RUNTIME_MANIFEST_REL
    report_path = root / REPORT_MANIFEST_REL
    missing = [
        rel
        for rel, path in (
            (RUNTIME_MANIFEST_REL, runtime_path),
            (REPORT_MANIFEST_REL, report_path),
        )
        if not path.is_file()
    ]
    result: dict[str, Any] = {
        "status": "PASS",
        "archiveManifestAgreement": False,
        "runtimeManifestPath": RUNTIME_MANIFEST_REL,
        "reportManifestPath": REPORT_MANIFEST_REL,
        "latestRollingBriefDate": "",
        "latestArchivedReportDate": "",
        "recoveryInstruction": RECOVERY_INSTRUCTION,
        "actionable": False,
    }
    if missing:
        result.update(
            status="FAIL_CLOSED",
            code="REPORT_LIBRARY_MANIFEST_MISSING",
            missing=missing,
            message="研報庫 manifest 缺少，不能宣稱歸檔索引健康。",
        )
        return result
    try:
        runtime_manifest = _read_json(runtime_path)
        report_manifest = _read_json(report_path)
    except RollingBriefError as exc:
        result.update(status="FAIL_CLOSED", code="REPORT_LIBRARY_MANIFEST_INVALID", message=str(exc))
        return result
    runtime_canonical = json.dumps(runtime_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    report_canonical = json.dumps(report_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if runtime_canonical != report_canonical:
        result.update(
            status="FAIL_CLOSED",
            code="REPORT_LIBRARY_MANIFEST_MISMATCH",
            message="runtime 與 reports 研報 manifest 不一致；拒絕顯示為健康研報庫。",
            runtimeManifestSha256=sha256_file(runtime_path),
            reportManifestSha256=sha256_file(report_path),
        )
        return result
    result["archiveManifestAgreement"] = True
    result["runtimeManifestSha256"] = sha256_file(runtime_path)
    result["reportManifestSha256"] = sha256_file(report_path)
    result["latestArchivedReportDate"] = _latest_archive_date(report_manifest)

    brief_path = root / CURRENT_BRIEF_REL
    html_path = root / LATEST_REPORT_REL
    if not brief_path.is_file() or not html_path.is_file():
        result.update(
            status="FAIL_CLOSED",
            code="ROLLING_BRIEF_MISSING",
            message="當前 rolling brief 或 latest_report.html 缺少。",
        )
        return result
    try:
        brief = _read_json(brief_path)
        html_text = html_path.read_text(encoding="utf-8")
    except (RollingBriefError, OSError, UnicodeError) as exc:
        result.update(status="FAIL_CLOSED", code="ROLLING_BRIEF_INVALID", message=str(exc))
        return result
    brief_id = str(brief.get("briefId") or "")
    authority_date = str(brief.get("authorityDate") or "")
    if (
        not brief_id
        or not authority_date
        or f'data-p1008-brief-id="{brief_id}"' not in html_text
        or f'data-authority-date="{authority_date}"' not in html_text
    ):
        result.update(
            status="FAIL_CLOSED",
            code="ROLLING_BRIEF_HTML_MISMATCH",
            message="current_warroom_brief.json 與 latest_report.html 身分不一致。",
        )
        return result
    result["latestRollingBriefDate"] = authority_date
    result["briefId"] = brief_id
    result["briefSha256"] = sha256_file(brief_path)
    result["latestReportHtmlSha256"] = sha256_file(html_path)
    result["code"] = "REPORT_LIBRARY_HEALTHY"
    result["message"] = "Rolling brief 與兩份 archive manifest 已一致驗證。"
    return result
