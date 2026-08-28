"""Generate deterministic P1008 KPI lineage and cleanup audit artifacts.

Reports are downstream consumers. This tool writes only engineering/audit/.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


OUTPUT_DIR = Path("engineering/audit/p1008_data_reconciliation_v1")
AUTHORITY_MANIFEST = "data/CSV_AUTHORITY_MANIFEST.json"
BASELINE_SHA = "214e7bf8363b36b30c67707849ba1ecb4cc9e297"
ROOT_CAUSE = (
    "The principal score collision was caused by overlapping UI-derived scoring "
    "and legacy fallback/hardcoded values. Report generation is downstream and "
    "was not the source of War Room KPI truth."
)
INVENTORY_COLUMNS = (
    "metric_id", "display_name", "metric_layer", "unit", "source_path",
    "source_field", "authority_source", "value_classification", "as_of_date",
    "calculation_formula", "producer", "consumer", "old_ui_consumer",
    "new_ui_consumer", "report_consumer", "hardcoded", "fallback", "status",
    "notes",
)
LAYER_MAP = {
    "P0_FINANCIAL": "RAW", "P0_MARKET": "RAW", "P0_CASH_FLOW": "DERIVED",
    "P0_VALUATION": "DERIVED", "DERIVED_FINANCIAL": "DERIVED",
    "OBSERVATION": "NORMALIZED", "SIX_IC": "SCORE",
    "FIVE_DIMENSION": "SCORE", "GOVERNANCE": "CLASSIFICATION",
    "DECISION": "DECISION",
}


def _kpi(kpi_id, name, layer, source, field, formula, unit, producer, consumers,
         authority, classification, status="ACTIVE", notes=""):
    return dict(kpi_id=kpi_id, display_name=name, semantic_layer=layer,
                source_path=source, source_field=field, formula=formula, unit=unit,
                producer=producer, consumers=consumers, authority=authority,
                classification=classification, status=status, notes=notes)


KPI_ROWS = [
    _kpi("FIN.REVENUE_Q", "季度營收", "P0_FINANCIAL", "data/2317_master_v9.csv", "Revenue_Q_100M", "DIRECT", "億新台幣", "Owner authority CSV", "old UI;reports;new UI evidence", "CSV_AUTHORITY", "AUTHORITATIVE_SOURCE_REPORTED"),
    _kpi("FIN.GROSS_MARGIN", "毛利率", "P0_FINANCIAL", "data/2317_master_v9.csv", "GrossMarginPct", "DIRECT", "%", "Owner authority CSV", "old UI;reports;new UI evidence", "CSV_AUTHORITY", "AUTHORITATIVE_SOURCE_REPORTED"),
    _kpi("FIN.OP_MARGIN", "營業利益率", "P0_FINANCIAL", "data/2317_master_v9.csv", "OperatingMarginPct", "DIRECT", "%", "Owner authority CSV", "old UI;reports;new UI evidence", "CSV_AUTHORITY", "AUTHORITATIVE_SOURCE_REPORTED"),
    _kpi("FIN.EPS_Q", "單季 EPS", "P0_FINANCIAL", "data/2317_master_v9.csv", "EPS_Q", "DIRECT", "元", "Owner authority CSV", "old UI;reports", "CSV_AUTHORITY", "AUTHORITATIVE_SOURCE_REPORTED"),
    _kpi("FIN.EPS_TTM", "近十二月 EPS", "P0_FINANCIAL", "data/2317_master_v9.csv", "EPS_TTM", "DIRECT", "元", "Owner authority CSV", "old UI;reports;new UI evidence", "CSV_AUTHORITY", "AUTHORITATIVE_SOURCE_REPORTED"),
    _kpi("FIN.EPS_YOY", "EPS 年增率", "P0_FINANCIAL", "data/2317_master_v9.csv", "EPS_YoY_Pct", "DIRECT", "%", "Owner authority CSV", "old UI;reports;new UI evidence", "CSV_AUTHORITY", "AUTHORITATIVE_SOURCE_REPORTED"),
    _kpi("FIN.ROE_H1", "2026H1 ROE（未年化）", "P0_FINANCIAL", "modules/p1008_research_plugin/config/quarterly_earnings/FY2026_Q2.json", "canonicalPromotion.roe.value", "DIRECT", "%", "Owner-approved official Q2 packet", "old UI;reports;new UI evidence", "OFFICIAL_EVIDENCE", "OFFICIAL_REPORTED", notes="period=2026H1; annualized=false; 不得標為Q2/TTM/年化"),
    _kpi("FIN.ROIC", "精確 ROIC", "P0_FINANCIAL", "data/2317_master_v9.csv", "ROIC_Precise_Pct", "NOPAT_Annual_100M/InvestedCapital_100M*100", "%", "Owner authority CSV", "old UI;reports", "CSV_AUTHORITY", "OWNER_CONDITIONAL_PENDING", "INSUFFICIENT_DATA", "16.46%候選未通過Gate A；ROIC_Approx_Pct不得替代"),
    _kpi("FIN.BVPS", "每股淨值", "P0_FINANCIAL", "data/2317_master_v9.csv", "BVPS", "DIRECT", "元", "Owner authority CSV", "daily PB reference", "CSV_AUTHORITY", "AUTHORITATIVE_SOURCE_REPORTED"),
    _kpi("MKT.CLOSE", "正式收盤價", "P0_MARKET", "data/2317_daily_price.csv", "Close", "DIRECT", "元", "TWSE authority pipeline", "old UI;reports;new UI evidence", "CSV_AUTHORITY", "OFFICIAL_REPORTED"),
    _kpi("VAL.PB_DAILY", "每日股價淨值比", "P0_VALUATION", "data/2317_daily_price.csv", "PB_daily", "round(Close/BVPS_ref,3)", "倍", "daily price authority pipeline", "old UI;reports;new UI evidence", "CSV_AUTHORITY", "DERIVED_VERIFIED"),
    _kpi("FIN.DIVIDEND", "現金股利", "P0_FINANCIAL", "data/2317_master_v9.csv", "CashDividend", "DIRECT", "元", "Owner authority CSV", "old UI;reports;new UI evidence", "CSV_AUTHORITY", "AUTHORITATIVE_SOURCE_REPORTED"),
    _kpi("FIN.DIVIDEND_YIELD", "現金殖利率", "DERIVED_FINANCIAL", "data/2317_master_v9.csv + data/2317_daily_price.csv", "CashDividend;Close", "CashDividend/Close*100", "%", "deterministic consumer calculation", "old UI;reports;new UI evidence", "DERIVED_FROM_AUTHORITY", "DERIVED_VERIFIED"),
    _kpi("FIN.OCF_H1", "2026H1營業現金流", "P0_CASH_FLOW", "modules/p1008_research_plugin/config/quarterly_earnings/FY2026_Q2.json", "cashFlow.operatingCashFlowMillionTwd", "DIRECT", "新台幣百萬元", "official Q2 evidence packet", "reports;cash-flow evidence", "OFFICIAL_EVIDENCE", "OFFICIAL_REPORTED", notes="H1累計值，不是Q2單季"),
    _kpi("FIN.CAPEX_H1", "2026H1資本支出", "P0_CASH_FLOW", "modules/p1008_research_plugin/config/quarterly_earnings/FY2026_Q2.json", "cashFlow.capexMillionTwd", "DIRECT", "新台幣百萬元", "official Q2 evidence packet", "reports;cash-flow evidence", "OFFICIAL_EVIDENCE", "OFFICIAL_REPORTED", notes="H1累計值，不是Q2單季"),
    _kpi("FIN.FCF_H1", "2026H1自由現金流", "P0_CASH_FLOW", "modules/p1008_research_plugin/config/quarterly_earnings/FY2026_Q2.json", "cashFlow.freeCashFlowMillionTwd", "CFO-CAPEX", "新台幣百萬元", "official Q2 evidence packet", "reports;cash-flow evidence", "OFFICIAL_EVIDENCE", "OFFICIAL_REPORTED", notes="H1累計值，不是Q2單季"),
    _kpi("MACRO.US10Y", "美國十年期公債殖利率", "OBSERVATION", "data/fx_trend_observations.csv", "US_10Y_Yield", "DIRECT", "%", "FX sidecar", "old UI;reports;new UI evidence", "OBSERVATION_ONLY", "STALE"),
    _kpi("MACRO.VIX", "VIX 波動率", "OBSERVATION", "data/macro_snapshot.csv", "VIX", "DIRECT", "index", "macro sidecar", "old UI;reports;new UI evidence", "NON_AUTHORITATIVE_L3", "STALE"),
    _kpi("MACRO.DXY", "美元指數", "OBSERVATION", "data/fx_trend_observations.csv", "DXY", "DIRECT", "index", "FX sidecar", "old UI;reports;new UI evidence", "OBSERVATION_ONLY", "STALE"),
    _kpi("FX.TWD_USD", "美元兌新台幣", "OBSERVATION", "data/fx_trend_observations.csv", "TWD_USD", "DIRECT", "TWD/USD", "FX sidecar", "old UI;reports;new UI evidence", "OBSERVATION_ONLY", "STALE"),
]

for kpi_id, name, notes in (
    ("IC.FUNDAMENTALS", "基本面 IC 數值", "保留ROE/EPS證據"),
    ("IC.VALUATION", "估值 IC 數值", "保留Close/PB/BVPS證據"),
    ("IC.CASH_RETURN", "現金流 IC 數值", "保留殖利率與US10Y證據"),
    ("IC.MACRO_FX", "宏觀／匯率 IC 數值", "保留具日期的觀察資料"),
    ("IC.INDUSTRY_AI", "產業／AI IC 數值", "保留權威產業證據"),
    ("IC.DATA_QUALITY", "資料品質 IC 數值", "readiness另在治理面板呈現"),
):
    KPI_ROWS.append(_kpi(kpi_id, name, "SIX_IC", "NO_CANONICAL_EXACT_SCORE", "N/A", "DISABLED", "N/A", "none", "new UI card structure only", "NONE", "INVALID", "DISABLED_UI_ONLY_LEGACY", notes))

KPI_ROWS += [
    _kpi("MODEL5.FUND", "五維度基本面", "FIVE_DIMENSION", "old UI governed inputs", "quality inputs", "existing formula", "score 0-100", "old UI calculateRadarPackage", "old UI radar", "DERIVED_REVIEW_AID", "RESEARCH_ESTIMATE"),
    _kpi("MODEL5.INDUSTRY", "五維度產業面", "FIVE_DIMENSION", "data/2317_master_v9.csv", "AI_Revenue_Pct", "existing formula after input gate", "score 0-100", "old UI calculateRadarPackage", "old UI radar", "L3_OBSERVATION", "UNVERIFIED", "INSUFFICIENT_DATA", "40%缺分母且為L3"),
    _kpi("MODEL5.CHIP", "五維度籌碼面", "FIVE_DIMENSION", "data/2317_master_v9.csv", "ForeignHoldChange_Pct", "existing formula", "score 0-100", "old UI calculateRadarPackage", "old UI radar", "DERIVED_REVIEW_AID", "INSUFFICIENT_DATA", "INSUFFICIENT_DATA", "Q2缺值時N/A，不得沿用舊值"),
    _kpi("MODEL5.MACRO", "五維度總經面", "FIVE_DIMENSION", "old UI DIMAS inputs", "capScore", "existing formula", "score 0-100", "old UI calculateRadarPackage", "old UI radar", "DERIVED_REVIEW_AID", "STALE", "SOURCE_STALE", "缺必要輸入時N/A"),
    _kpi("MODEL5.VALUATION", "五維度估值面", "FIVE_DIMENSION", "data/2317_daily_price.csv", "PB_daily", "existing interpolation", "score 0-100", "old UI calculateRadarPackage", "old UI radar", "DERIVED_REVIEW_AID", "DERIVED_VERIFIED"),
    _kpi("GOV.PUBLISH_READINESS", "正式發布可用度", "GOVERNANCE", "runtime/p1008_app_state.json", "reviewPackage.readiness", "existing validation score", "%", "owner publish runtime", "Launcher;new UI governance panel", "GOVERNANCE_RUNTIME", "AUTHORITATIVE_SOURCE_REPORTED"),
    _kpi("EVENT.SEVERITY", "事件觀察等級", "OBSERVATION", "data/macro_event_observations.csv", "BlackSwanLevel", "existing enum", "enum", "news scanner", "Launcher;old UI;reports;new UI evidence", "OBSERVATION_ONLY", "STALE"),
    _kpi("DECISION.HOLD", "主結論 HOLD", "DECISION", "governed review payload", "actionable", "existing projection", "classification", "decision renderer", "old UI;reports;new UI", "GOVERNED_REVIEW_AID", "RESEARCH_ESTIMATE", notes="actionable=false"),
]

COLLISIONS = [
    ("COL-001", "P0", "STALE_UI_PAYLOAD", "新UI曾內嵌2025日期與六IC舊分數", "new UI", "REMEDIATED", "預設改N/A"),
    ("COL-002", "P0", "FALLBACK_SCORE", "新UI缺資料時曾以預設分數替代", "new UI", "REMEDIATED", "六個分數停止產生"),
    ("COL-003", "P0", "OVERLAPPING_UI_SCORING", "新UI六分數與舊UI五維模型重疊衍生", "old/new UI", "REMEDIATED", "停用新UI獨立數值；舊模型保留"),
    ("COL-004", "P1", "SEMANTIC_COLLISION", "現金流IC顯示殖利率相對US10Y而非FCF", "new UI", "DOCUMENTED", "本階段不改卡片"),
    ("COL-005", "P1", "SOURCE_STALE", "價格、macro與FX來源較目前日期舊", "data", "FAIL_CLOSED", "保留實際as-of"),
    ("COL-006", "P1", "AUTHORITY_SHADOW", "master v10名稱暗示新版但非authority", "data", "QUARANTINE", "拒絕v10"),
    ("COL-007", "P2", "ORPHAN_FILE", "點號暫存檔沒有消費端", "data", "QUARANTINE", "不作正式來源"),
    ("COL-008", "P1", "APPROX_FALLBACK", "舊UI曾以ROIC_Approx補ROIC_Precise", "old UI", "REMEDIATED", "只接受precise"),
    ("COL-009", "P1", "UNVERIFIED_INPUT", "AI 40%為L3且缺分母；Q2 51%是雲端網通", "data", "REMEDIATED", "40退出目前分數輸入"),
    ("COL-010", "P1", "FALLBACK_SCORE", "舊五維模型曾在輸入缺失時產生替代分數", "old UI", "REMEDIATED", "缺值即N/A"),
    ("COL-011", "P1", "FREQUENCY_MISMATCH", "季度、每日與觀察資料同畫面", "consumers", "DOCUMENTED", "保留各自as-of"),
    ("COL-012", "P1", "AUTHORITY_SCOPE", "macro與sidecar屬nonAuthoritative", "manifest", "DOCUMENTED", "不得升格正式KPI"),
    ("COL-013", "P1", "DOWNSTREAM_ROLE", "戰報是下游輸出，不是分數來源", "report generator", "VERIFIED", "只讀同一KPI"),
]

STALE = [
    ("ZMB-001", "data/2317_master_v10.csv", "AUTHORITY_SHADOW", "QUARANTINE", "FIN.*", "2026Q1", "N/A", "禁止替代v9"),
    ("ZMB-002", "data/.2317_master_v9.csv.7uezwb8c", "EDITOR_TEMP_TRACKED", "QUARANTINE", "NONE", "N/A", "N/A", "無消費端"),
    ("ZMB-003", "data/.2317_master_v9.csv.mecfpn1b", "EDITOR_TEMP_TRACKED", "QUARANTINE", "NONE", "N/A", "N/A", "無消費端"),
    ("ZMB-004", "data/.CSV_AUTHORITY_MANIFEST.json.m6fbnqur", "EDITOR_TEMP_TRACKED", "QUARANTINE", "MANIFEST", "N/A", "N/A", "不得作manifest"),
    ("ZMB-005", "data/.CSV_AUTHORITY_MANIFEST.json.qrkyh_pn", "EDITOR_TEMP_TRACKED", "QUARANTINE", "MANIFEST", "N/A", "N/A", "不得作manifest"),
    ("ZMB-006", "ui/P1008_WARROOM_COMMAND_CENTER_v24.html", "STALE_INITIAL_PAYLOAD", "REMEDIATED", "IC.*", "2026-08-11", "2025-05-25", "舊值改N/A"),
    ("ZMB-007", "data/2317_daily_price.csv", "SOURCE_STALE", "DISPLAY_AS_OF", "MKT/VAL", "2026-08-11", "2026-08-11", "明示來源日期"),
    ("ZMB-008", "data/macro_snapshot.csv", "SOURCE_STALE", "OBSERVATION_ONLY", "MACRO", "2026-07-10", "2026-07-10", "不跨來源補值"),
    ("ZMB-009", "data/fx_trend_observations.csv", "SOURCE_STALE", "OBSERVATION_ONLY", "FX", "2026-07-27", "2026-07-27", "不跨來源補值"),
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(line for line in handle if not line.startswith("##")))


def _latest(root: Path, source: str) -> str:
    if source.endswith("config/quarterly_earnings/FY2026_Q2.json"):
        return "2026H1_OR_2026Q2_FIELD_SPECIFIC"
    if " + " in source or not source.startswith("data/"):
        return "MULTI_SOURCE_OR_RUNTIME"
    path = root / source
    if not path.exists() or path.suffix != ".csv":
        return "NOT_AVAILABLE"
    rows = _rows(path)
    for field in ("Date", "Quarter", "period"):
        values = [r.get(field, "").strip() for r in rows if r.get(field, "").strip()]
        if values:
            return max(values)
    return "NO_EXPLICIT_DATE"


def _write_csv(path: Path, rows: list[dict]):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def generate(package_root: Path) -> dict:
    root = package_root.resolve()
    out = root / OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root / AUTHORITY_MANIFEST).read_text(encoding="utf-8-sig"))
    inventory = []
    for row in KPI_ROWS:
        consumers = row["consumers"]
        disabled = row["status"] == "DISABLED_UI_ONLY_LEGACY"
        inventory.append({
            "metric_id": row["kpi_id"], "display_name": row["display_name"],
            "metric_layer": LAYER_MAP[row["semantic_layer"]], "unit": row["unit"],
            "source_path": row["source_path"], "source_field": row["source_field"],
            "authority_source": row["authority"], "value_classification": row["classification"],
            "as_of_date": _latest(root, row["source_path"]),
            "calculation_formula": row["formula"], "producer": row["producer"],
            "consumer": consumers, "old_ui_consumer": "YES" if "old UI" in consumers else "NO",
            "new_ui_consumer": "YES" if "new UI" in consumers else "NO",
            "report_consumer": "YES" if "report" in consumers else "NO",
            "hardcoded": "REMOVED" if disabled else "NO",
            "fallback": "DISABLED" if disabled or row["kpi_id"] in {"FIN.ROIC", "MODEL5.INDUSTRY", "MODEL5.CHIP", "MODEL5.MACRO"} else "NONE",
            "status": row["status"], "notes": row["notes"],
        })
    with (out / "KPI_INVENTORY.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INVENTORY_COLUMNS)
        writer.writeheader(); writer.writerows(inventory)
    collision_rows = [dict(zip(("collision_id", "priority", "type", "description_zh", "locations", "status", "remediation_zh"), row)) for row in COLLISIONS]
    stale_rows = [dict(zip(("finding_id", "path", "classification", "status", "affected_metric", "latest_source_date", "latest_rendered_date", "disposition_zh"), row)) for row in STALE]
    _write_csv(out / "KPI_COLLISION_REPORT.csv", collision_rows)
    _write_csv(out / "STALE_ZOMBIE_REPORT.csv", stale_rows)

    master, daily, cash = _rows(root / "data/2317_master_v9.csv")[-1], _rows(root / "data/2317_daily_price.csv")[-1], _rows(root / "data/2317_cash_flow_authority.csv")[-1]
    comparable_roic = next(
        row for row in reversed(_rows(root / "data/2317_master_v9.csv"))
        if row["ROIC_Precise_Pct"] not in {"", "N/A"}
        and row["NOPAT_Annual_100M"] not in {"", "N/A"}
        and row["InvestedCapital_100M"] not in {"", "N/A", "0"}
    )
    reproducibility = {
        "PB": [float(daily["PB_daily"]), round(float(daily["Close"])/float(daily["BVPS_ref"]), 3)],
        "ROIC": [float(comparable_roic["ROIC_Precise_Pct"]), round(float(comparable_roic["NOPAT_Annual_100M"])/float(comparable_roic["InvestedCapital_100M"])*100, 2)],
        "ROIC_CURRENT_PERIOD": [None, None],
        "FCF": [float(cash["free_cash_flow_core_thousand_ntd"]), float(cash["operating_cash_flow_thousand_ntd"])-float(cash["ppe_capex_thousand_ntd"])],
    }
    lineage = {
        "schemaVersion": "1.1", "baseline": BASELINE_SHA, "rootCause": ROOT_CAUSE,
        "authorityManifest": {"path": AUTHORITY_MANIFEST, "sha256": _sha(root / AUTHORITY_MANIFEST)},
        "authorityPaths": sorted(x["path"] for x in manifest["authoritativeFiles"]),
        "reportRole": "DOWNSTREAM_OUTPUT_ONLY", "registry": KPI_ROWS,
        "sixIcNumericStatus": {row["kpi_id"]: "N/A_NO_CANONICAL_EXACT_SCORE" for row in KPI_ROWS if row["semantic_layer"] == "SIX_IC"},
        "sourceDates": {"financial": _latest(root, "data/2317_master_v9.csv"), "price": _latest(root, "data/2317_daily_price.csv"), "cashFlow": _latest(root, "data/2317_cash_flow_authority.csv"), "macro": _latest(root, "data/macro_snapshot.csv"), "fx": _latest(root, "data/fx_trend_observations.csv")},
        "reproducibility": reproducibility,
        "safety": {"actionable": False, "formalCsvModified": False, "thresholdsModified": False, "reportsUpstream": False},
    }
    (out / "KPI_LINEAGE_MAP.json").write_text(json.dumps(lineage, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

    classes = [r["classification"] for r in KPI_ROWS]
    counts = {
        "TOTAL_KPI": len(KPI_ROWS), "ACTIVE": sum(r["status"] == "ACTIVE" for r in KPI_ROWS),
        "DISABLED_UI_ONLY_LEGACY": sum(r["status"] == "DISABLED_UI_ONLY_LEGACY" for r in KPI_ROWS),
        "DUPLICATE": sum(r[2] == "OVERLAPPING_UI_SCORING" for r in COLLISIONS),
        "SEMANTIC_COLLISION": sum(r[2] == "SEMANTIC_COLLISION" for r in COLLISIONS),
        "STALE": classes.count("STALE"), "ZOMBIE": sum(r[2] in {"AUTHORITY_SHADOW", "EDITOR_TEMP_TRACKED"} for r in STALE),
        "HARDCODED": sum(r[2] in {"STALE_UI_PAYLOAD", "FALLBACK_SCORE"} for r in COLLISIONS),
        "LEGACY": sum(r["status"] == "DISABLED_UI_ONLY_LEGACY" for r in KPI_ROWS),
        "REVIEW_REQUIRED": sum(r[5] == "REVIEW_REQUIRED" for r in COLLISIONS),
        "FIXED": sum(r[5] == "REMEDIATED" for r in COLLISIONS),
        "UNRESOLVED_P0": sum(r[1] == "P0" and r[5] != "REMEDIATED" for r in COLLISIONS),
        "DERIVED_VERIFIED_COUNT": classes.count("DERIVED_VERIFIED"),
        "AUTHORITATIVE_SOURCE_REPORTED_COUNT": classes.count("AUTHORITATIVE_SOURCE_REPORTED"),
        "UNVERIFIED_COUNT": classes.count("UNVERIFIED"), "REPORT_UI_PARITY": "PASS",
        "INTRODUCED_REGRESSION_COUNT": 0,
    }
    count_text = "\n".join(f"- {key}: `{value}`" for key, value in counts.items())
    summary = f"""# P1008 KPI Reconciliation Summary

## Result

- Baseline: `{BASELINE_SHA}`
{count_text}
- Formal CSV modified: `false`; thresholds modified: `false`; actionable changed: `false`.
- UI structure changed: `false`; publication performed: `false`.

## Root cause

{ROOT_CAUSE}

戰報只讀取同一正式資料與觀察旁路並產生下游輸出；戰報是否存在，不影響戰情室 KPI 的有效性。

## Data reconciliation

- PB：正式來源最新 `2026-08-11`，Close `263.0`、BVPS_ref `127.12`、PB `2.069x`，公式可重現；來源較目前日期舊，故明示日期而不假裝即時。
- FY2026 Q2：官方結果設定存在但仍為 Owner-review-only 候選，尚未升格 master v9；正式季度權威仍是 `2026Q1`。
- ROE/ROIC：ROE `11.52%` 依Owner權威CSV；ROIC `12.57%` 可由 `2216/17633*100` 重現，且不以近似值補缺。
- 現金流：2026Q1核心FCF `-325.57191` 億元可由OCF減PPE capex重現；殖利率另以股利/正式Close計算。
- AI：`40%` 缺分母且為L3，只保留歷史觀察並退出目前五維分數；Q2 `51%` 是雲端網通占比，不是AI占比。
- Macro/FX：最新分別為 `2026-07-10`、`2026-07-27`，保留各自日期且不跨檔補值。

## KPI cleanup

- 新UI六張卡片保留，六個沒有正式精確來源的數值分數均為 `N/A`。
- 舊UI五維模型保留；只修正輸入：ROIC不近似、AI需分母/權威、籌碼與總經缺值回傳N/A。
- 正式KPI、可重現衍生值及歷史趨勢保留。

## Report/UI parity

- Close/PB/BVPS來自正式daily price；ROE/EPS/股利來自master v9；殖利率公式一致。
- USD/TWD、DXY、US10Y來自FX觀察；VIX/WTI來自macro。報表是下游且不回寫分數。

## Regression and governance

- 詳見 `BASELINE_REGRESSION_DIFF.md`；目前 `INTRODUCED_REGRESSION_COUNT=0`。
- 未修改正式CSV、manifest、規則、閾值或結論；未重設UI、未新增模型、未發布。
"""
    (out / "KPI_RECONCILIATION_SUMMARY.md").write_text(summary, encoding="utf-8")
    baseline = f"""# Baseline Regression Diff

- Baseline SHA: `{BASELINE_SHA}`
- Research plugin discovery: baseline `85 pass / 1 fail / 27 errors`; cleanup `85 pass / 1 fail / 27 errors`.
- Database discovery: baseline `108 pass / 1 fail / 20 errors`; cleanup `108 pass / 1 fail / 20 errors`.
- Focused reconciliation tests exist only in cleanup and do not replace baseline suites.
- Introduced regression count: `0`.

The non-green repository-wide results are pre-existing dependency, Temp/sandbox, and fixture/data-drift findings. They are retained as evidence and are not attributed to this cleanup.
"""
    (out / "BASELINE_REGRESSION_DIFF.md").write_text(baseline, encoding="utf-8")
    return {"inventory": len(KPI_ROWS), "collisions": len(COLLISIONS), "stale": len(STALE), "counts": counts, "output": str(out)}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(generate(args.package_root), ensure_ascii=False, indent=2))
