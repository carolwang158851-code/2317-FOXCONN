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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


CURRENT_BRIEF_REL = "runtime/current_warroom_brief.json"
LATEST_REPORT_REL = "reports/generated/latest_report.html"
RUNTIME_MANIFEST_REL = "runtime/warroom_report_manifest.json"
REPORT_MANIFEST_REL = "reports/P1008_REPORT_MANIFEST.json"
AUTHORITY_MANIFEST_REL = "data/CSV_AUTHORITY_MANIFEST.json"
BRIEF_CONTENT_HASH_FIELD = "briefContentSha256"
EMPTY_MANIFEST_SCHEMA_VERSION = "1.0"
EMPTY_MANIFEST_TOOL_VERSION = "P1008_REPORT_LIBRARY_BOOTSTRAP_v1"
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


def canonical_brief_content(brief: dict[str, Any]) -> bytes:
    """Return the governed brief preimage without its self-referential hash."""
    payload = dict(brief)
    payload.pop(BRIEF_CONTENT_HASH_FIELD, None)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def brief_content_sha256(brief: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_brief_content(brief)).hexdigest().upper()


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


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    """Serialize a governed JSON payload consistently for paired artifacts."""
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _canonical_json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def empty_report_library_manifest(*, now: datetime | None = None) -> dict[str, Any]:
    """Return the only permitted first-run report-library manifest payload."""
    return {
        "schemaVersion": EMPTY_MANIFEST_SCHEMA_VERSION,
        "initializedAtUtc": _utc_timestamp(now),
        "toolVersion": EMPTY_MANIFEST_TOOL_VERSION,
        "reports": [],
        "latest": {"daily": None, "weekly": None, "monthly": None},
        "productionCsvModified": False,
        "actionable": False,
    }


def _validate_report_manifest(manifest: dict[str, Any]) -> None:
    """Reject a malformed archive index without attempting a repair."""
    if not isinstance(manifest.get("reports"), list):
        raise RollingBriefError("Report library manifest reports must be an array")
    latest = manifest.get("latest")
    if not isinstance(latest, dict) or any(
        key not in latest for key in ("daily", "weekly", "monthly")
    ):
        raise RollingBriefError("Report library manifest latest section is invalid")
    if manifest.get("actionable") is not False:
        raise RollingBriefError("Report library manifest actionable must be false")


def bootstrap_report_library(
    package_root: Path, *, now: datetime | None = None
) -> dict[str, Any]:
    """Create the paired empty archive manifests only for a true first run.

    A single lost, mismatched, or invalid manifest is a forensic condition, not
    an invitation to reconstruct archive history.  Those cases remain
    fail-closed and require Owner review.
    """
    root = package_root.resolve()
    runtime_path = root / RUNTIME_MANIFEST_REL
    report_path = root / REPORT_MANIFEST_REL
    runtime_exists = runtime_path.is_file()
    report_exists = report_path.is_file()
    result: dict[str, Any] = {
        "runtimeManifestPath": RUNTIME_MANIFEST_REL,
        "reportManifestPath": REPORT_MANIFEST_REL,
        "archiveReportCount": 0,
        "archiveAppended": False,
        "actionable": False,
    }
    if not runtime_exists and not report_exists:
        payload = empty_report_library_manifest(now=now)
        body = _canonical_json_bytes(payload)
        created_runtime = False
        created_report = False
        try:
            _atomic_write_bytes(runtime_path, body)
            created_runtime = True
            _atomic_write_bytes(report_path, body)
            created_report = True
        except OSError as exc:
            # The files did not exist at entry.  Remove only artifacts created
            # by this failed bootstrap rather than leave a partial pair behind.
            if created_runtime and not created_report and runtime_path.exists():
                runtime_path.unlink()
            raise RollingBriefError("First-run manifest bootstrap could not finalize") from exc
        if runtime_path.read_bytes() != report_path.read_bytes():
            raise RollingBriefError("First-run manifest bootstrap byte identity failed")
        result.update(
            status="REPORT_LIBRARY_BOOTSTRAPPED_EMPTY",
            classification="FIRST_RUN_UNINITIALIZED",
            manifestSha256=sha256_file(runtime_path),
            runtimeManifestSha256=sha256_file(runtime_path),
            reportManifestSha256=sha256_file(report_path),
            manifestByteIdentity=True,
            manifestCanonicalIdentity=True,
        )
        return result
    if runtime_exists != report_exists:
        result.update(
            status="FAIL_CLOSED",
            classification="PARTIAL_MANIFEST_LOSS",
            code="REPORT_LIBRARY_PARTIAL_MANIFEST_LOSS",
            message="Exactly one archive manifest exists; automatic reconstruction is prohibited.",
        )
        return result
    try:
        runtime_manifest = _read_json(runtime_path)
        report_manifest = _read_json(report_path)
        _validate_report_manifest(runtime_manifest)
        _validate_report_manifest(report_manifest)
    except RollingBriefError as exc:
        result.update(
            status="FAIL_CLOSED",
            classification="MANIFEST_INVALID",
            code="REPORT_LIBRARY_MANIFEST_INVALID",
            message=str(exc),
        )
        return result
    runtime_canonical = _canonical_json_text(runtime_manifest)
    report_canonical = _canonical_json_text(report_manifest)
    if runtime_canonical != report_canonical:
        result.update(
            status="FAIL_CLOSED",
            classification="MANIFEST_MISMATCH",
            code="REPORT_LIBRARY_MANIFEST_MISMATCH",
            message="Archive manifests disagree; automatic repair is prohibited.",
        )
        return result
    result.update(
        status="REPORT_LIBRARY_EXISTING_HEALTHY",
        classification="EXISTING_HEALTHY",
        runtimeManifestSha256=sha256_file(runtime_path),
        reportManifestSha256=sha256_file(report_path),
        manifestByteIdentity=runtime_path.read_bytes() == report_path.read_bytes(),
        manifestCanonicalIdentity=True,
        archiveReportCount=len(runtime_manifest["reports"]),
    )
    return result


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


def _data_alignment(price_date: str, activity_date: str) -> tuple[str, dict[str, Any]]:
    try:
        price_day = date.fromisoformat(price_date)
    except ValueError as exc:
        raise RollingBriefError(f"Invalid Daily Price cutoff: {price_date}") from exc
    if not activity_date:
        return (
            "PARTIAL",
            {
                "status": "MISSING",
                "asOfDate": None,
                "referenceDailyPriceDate": price_date,
                "lagCalendarDays": None,
            },
        )
    try:
        activity_day = date.fromisoformat(activity_date)
    except ValueError as exc:
        raise RollingBriefError(
            f"Invalid Market Activity cutoff: {activity_date}"
        ) from exc
    lag_days = (price_day - activity_day).days
    if lag_days == 0:
        return (
            "ALIGNED",
            {
                "status": "CURRENT",
                "asOfDate": activity_date,
                "referenceDailyPriceDate": price_date,
                "lagCalendarDays": 0,
            },
        )
    return (
        "PARTIAL",
        {
            "status": "STALE" if lag_days > 0 else "PARTIAL",
            "asOfDate": activity_date,
            "referenceDailyPriceDate": price_date,
            "lagCalendarDays": lag_days,
        },
    )


def _brief_html(brief: dict[str, Any]) -> str:
    price = brief["marketBaseline"]["dailyPrice"]
    activity = brief["marketBaseline"].get("marketActivity") or {}
    generated = html.escape(str(brief["generatedAtUtc"]))
    authority_date = html.escape(str(brief["authorityDate"]))
    brief_id = html.escape(str(brief["briefId"]))
    content_sha = html.escape(str(brief.get(BRIEF_CONTENT_HASH_FIELD) or ""))
    data_cutoffs = brief.get("dataCutoffs") or {}
    price_date = html.escape(str(data_cutoffs.get("dailyPrice") or "資料未提供"))
    activity_date = html.escape(
        str(data_cutoffs.get("marketActivity") or "資料未提供")
    )
    alignment_status = html.escape(str(brief.get("dataAlignmentStatus") or "PARTIAL"))
    freshness = brief.get("marketActivityFreshness") or {}
    freshness_status = html.escape(str(freshness.get("status") or "MISSING"))
    close = html.escape(str(price.get("close") or "資料未提供"))
    pb = html.escape(str(price.get("pbDaily") or "資料未提供"))
    volume = html.escape(str(activity.get("tradeVolume") or "資料未提供"))
    turnover = html.escape(str(activity.get("tradeValue") or "資料未提供"))
    transactions = html.escape(
        str(activity.get("transactionCount") or "資料未提供")
    )
    return f"""<!doctype html>
<html lang="zh-TW" data-p1008-brief-id="{brief_id}" data-authority-date="{authority_date}" data-brief-content-sha256="{content_sha}" data-price-cutoff="{price_date}" data-market-activity-cutoff="{activity_date}" data-alignment-status="{alignment_status}">
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
    .asof {{ display:block; margin-top:8px; color:#9fb3c8; font-size:12px; }}
    .warning {{ border-color:#b98b2f; color:#fde68a; }}
  </style>
</head>
<body><main>
  <p class="muted">Rolling current brief｜不納入研報庫｜actionable=false</p>
  <h1>P1008 當前戰情快報</h1>
  <p>價格資料截止：{price_date}｜市場活動截止：{activity_date}｜刷新時間：{generated}</p>
  <p class="muted">資料對齊：{alignment_status}｜市場活動新鮮度：{freshness_status}</p>
  <section class="panel">
    <h2>市場資料基線</h2>
    <div class="grid">
      <div class="kpi">收盤價<br><strong>{close}</strong><span class="asof">資料截止：{price_date}</span></div>
      <div class="kpi">P/B<br><strong>{pb}</strong><span class="asof">資料截止：{price_date}</span></div>
      <div class="kpi">成交股數<br><strong>{volume}</strong><span class="asof">資料截止：{activity_date}</span></div>
      <div class="kpi">成交金額（新台幣元）<br><strong>{turnover}</strong><span class="asof">資料截止：{activity_date}</span></div>
      <div class="kpi">成交筆數<br><strong>{transactions}</strong><span class="asof">資料截止：{activity_date}</span></div>
    </div>
  </section>
  {f'<section class="panel warning"><strong>市場活動資料未與價格資料同日。</strong> 本頁保留各自截止日，不補值、不前推；流動性解讀狀態為 {freshness_status}。</section>' if alignment_status != 'ALIGNED' else ''}
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
    activity_date = str(activity.get("date") or "")
    alignment_status, activity_freshness = _data_alignment(
        authority_date, activity_date
    )
    generated_at = _utc_timestamp(now)
    brief_id = f"P1008-CURRENT-{authority_date.replace('-', '')}"
    brief: dict[str, Any] = {
        "schemaVersion": "1.1",
        "briefId": brief_id,
        "recordType": "ROLLING_CURRENT_BRIEF",
        "generatedAtUtc": generated_at,
        "authorityDate": authority_date,
        "dataCutoffs": {
            "dailyPrice": authority_date,
            "marketActivity": activity_date or None,
        },
        "dataAlignmentStatus": alignment_status,
        "marketActivityFreshness": activity_freshness,
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
    brief[BRIEF_CONTENT_HASH_FIELD] = brief_content_sha256(brief)
    json_bytes = (json.dumps(brief, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    html_bytes = _brief_html(brief).encode("utf-8")
    _atomic_write_bytes(root / CURRENT_BRIEF_REL, json_bytes)
    _atomic_write_bytes(root / LATEST_REPORT_REL, html_bytes)
    return {
        "status": "ROLLING_BRIEF_UPDATED",
        "briefId": brief_id,
        "authorityDate": authority_date,
        "dataCutoffs": brief["dataCutoffs"],
        "dataAlignmentStatus": alignment_status,
        "marketActivityFreshness": activity_freshness,
        BRIEF_CONTENT_HASH_FIELD: brief[BRIEF_CONTENT_HASH_FIELD],
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
    if len(missing) == 2:
        result.update(
            status="FIRST_RUN_UNINITIALIZED",
            code="REPORT_LIBRARY_FIRST_RUN_UNINITIALIZED",
            missing=missing,
            message="Both archive manifests are absent; first-run empty bootstrap is permitted.",
            recoveryInstruction="Run P1008_APP.bat once to create the empty paired archive manifests; do not create a Daily Report merely to initialize the library.",
        )
        return result
    if len(missing) == 1:
        result.update(
            status="FAIL_CLOSED",
            code="REPORT_LIBRARY_PARTIAL_MANIFEST_LOSS",
            missing=missing,
            message="Exactly one archive manifest is missing; automatic reconstruction is prohibited.",
            recoveryInstruction="Owner review required: archive manifest loss must be reconciled before the Launcher can open the New UI or Research Library.",
        )
        return result
    try:
        runtime_manifest = _read_json(runtime_path)
        report_manifest = _read_json(report_path)
        _validate_report_manifest(runtime_manifest)
        _validate_report_manifest(report_manifest)
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
    declared_content_sha = str(brief.get(BRIEF_CONTENT_HASH_FIELD) or "")
    recomputed_content_sha = brief_content_sha256(brief)
    if (
        len(declared_content_sha) != 64
        or declared_content_sha.upper() != recomputed_content_sha
    ):
        result.update(
            status="FAIL_CLOSED",
            code="ROLLING_BRIEF_JSON_CONTENT_HASH_MISMATCH",
            message="current_warroom_brief.json 的 governed content SHA-256 不一致。",
            declaredBriefContentSha256=declared_content_sha,
            recomputedBriefContentSha256=recomputed_content_sha,
        )
        return result
    if (
        not brief_id
        or not authority_date
        or f'data-p1008-brief-id="{brief_id}"' not in html_text
        or f'data-authority-date="{authority_date}"' not in html_text
        or f'data-brief-content-sha256="{declared_content_sha}"' not in html_text
    ):
        result.update(
            status="FAIL_CLOSED",
            code="ROLLING_BRIEF_HTML_MISMATCH",
            message="current_warroom_brief.json 與 latest_report.html 身分不一致。",
        )
        return result
    try:
        expected_html = _brief_html(brief)
    except (KeyError, TypeError, RollingBriefError) as exc:
        result.update(
            status="FAIL_CLOSED",
            code="ROLLING_BRIEF_INVALID",
            message=str(exc),
        )
        return result
    if html_text != expected_html:
        result.update(
            status="FAIL_CLOSED",
            code="ROLLING_BRIEF_HTML_CONTENT_MISMATCH",
            message="latest_report.html 與 governed brief payload 的完整渲染不一致。",
            expectedHtmlSha256=hashlib.sha256(expected_html.encode("utf-8")).hexdigest().upper(),
            actualHtmlSha256=sha256_file(html_path),
        )
        return result
    result["latestRollingBriefDate"] = authority_date
    result["dataCutoffs"] = brief.get("dataCutoffs") or {}
    result["dataAlignmentStatus"] = brief.get("dataAlignmentStatus") or ""
    result["marketActivityFreshness"] = brief.get("marketActivityFreshness") or {}
    result[BRIEF_CONTENT_HASH_FIELD] = declared_content_sha
    result["briefId"] = brief_id
    result["briefSha256"] = sha256_file(brief_path)
    result["latestReportHtmlSha256"] = sha256_file(html_path)
    result["code"] = "REPORT_LIBRARY_HEALTHY"
    result["message"] = "Rolling brief 與兩份 archive manifest 已一致驗證。"
    return result
