"""Validate and Owner-promote the FY2026 Q2 authority packet."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
AUDIT_REL = Path("engineering/audit/p1008_q2_kpi_completion_v1")
RECEIPT_REL = AUDIT_REL / "Q2_KPI_SOURCE_RECEIPT.json"
CONFIG_REL = Path("modules/p1008_research_plugin/config/quarterly_earnings/FY2026_Q2.json")
CANDIDATE_REL = AUDIT_REL / "Q2_KPI_COMPLETION_CANDIDATE.json"
SUMMARY_REL = AUDIT_REL / "Q2_KPI_COMPLETION_SUMMARY.md"
PROMOTION_REPORT_REL = AUDIT_REL / "Q2_OWNER_PROMOTION_REPORT.json"
OWNER_APPROVAL = "P1008_FY2026Q2_OWNER_PROMOTION_FINAL_OWNER_APPROVAL_DIRECTIVE"
Q2_EFFECTIVE_DATE = "2026-08-13"
CURRENT_DATE = "2026-08-27"


def _d(value: str) -> Decimal:
    return Decimal(str(value))


def _q(value: Decimal, places: str) -> str:
    return format(value.quantize(Decimal(places), rounding=ROUND_HALF_UP), "f")


def _sha_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest().upper()


def _sha(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _read_csv(path: Path) -> tuple[list[str], list[str], list[dict[str, str]]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    comments = [line for line in lines if line.startswith("##")]
    body = "\n".join(line for line in lines if not line.startswith("##")) + "\n"
    reader = csv.DictReader(io.StringIO(body))
    if reader.fieldnames is None:
        raise ValueError(f"CSV_HEADER_MISSING:{path}")
    return comments, list(reader.fieldnames), list(reader)


def _csv_bytes(comments: list[str], fields: list[str], rows: list[dict[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    for line in comments:
        stream.write(line + "\n")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _entry(manifest: dict[str, Any], rel_path: str) -> dict[str, Any]:
    for item in manifest.get("authoritativeFiles", []):
        if item.get("path") == rel_path:
            return item
    raise ValueError(f"AUTHORITY_ENTRY_MISSING:{rel_path}")


def _verify_manifest_file(root: Path, manifest: dict[str, Any], rel_path: str) -> None:
    path = root / rel_path
    item = _entry(manifest, rel_path)
    if _sha(path) != item.get("sha256"):
        raise ValueError(f"PRE_PUBLISH_HASH_MISMATCH:{rel_path}")
    if len(path.read_bytes()) != item.get("fileSizeBytes"):
        raise ValueError(f"PRE_PUBLISH_SIZE_MISMATCH:{rel_path}")


def _roic_gate_evidence(receipt: dict[str, Any]) -> dict[str, Any]:
    results = receipt["sources"]["honHaiResults"]
    twse = receipt["sources"]["twseBalanceSheet"]
    method = receipt["sources"]["p1008Methodology"]
    gates = {
        "A": {
            "status": "FAIL",
            "labelZh": "未證明淨現金可用現金及約當現金減利息負債反推",
            "reasonZh": "官方逐字稿揭露現金及定期存款約1.52兆元與淨現金219,809百萬元；候選使用現金及約當現金963,002百萬元。現金口徑不同，官方未明確定義Net Cash為963,002減利息負債。",
            "sourceLocator": results["sourceLocator"],
        },
        "B": {
            "status": "PASS", "labelZh": "日期、期間及合併範圍相容",
            "reasonZh": "現金、淨現金及歸屬母公司權益均為2026-06-30合併口徑。",
            "sourceLocators": [results["sourceLocator"], twse["sourceLocator"]],
        },
        "C": {
            "status": "PASS", "labelZh": "26.72%僅為既有P1008年度稅率方法輸入",
            "reasonZh": "來源綁定既有master公式與2026Q1反推鏈；不標示為公司Q2有效稅率。",
            "sourceLocator": method["sourceLocator"],
        },
        "D": {
            "status": "PASS", "labelZh": "既有歷史方法採單季營業利益年化",
            "reasonZh": "master roicNote固定為OpInc×(1−TaxRate)×4後除以投入資本。",
            "sourceLocator": method["sourceLocator"],
        },
    }
    all_passed = all(item["status"] == "PASS" for item in gates.values())
    return {
        "gates": gates, "allPassed": all_passed, "trendComparable": all_passed,
        "trendComparableZh": "公式慣例相同，但Q2候選分母的淨現金口徑未通過Gate A，禁止顯示Q1至Q2數值趨勢。",
    }


def build_candidate(package_root: Path = PACKAGE_ROOT) -> dict[str, Any]:
    receipt = json.loads((package_root / RECEIPT_REL).read_text(encoding="utf-8"))
    config = json.loads((package_root / CONFIG_REL).read_text(encoding="utf-8"))
    sources = receipt["sources"]
    results = sources["honHaiResults"]
    twse = sources["twseBalanceSheet"]
    press = sources["honHaiPressRelease"]
    method = sources["p1008Methodology"]
    if config["expectedSourceSha256"] != results["sourceDocumentSha256"]:
        raise ValueError("Q2_RESULTS_SOURCE_HASH_MISMATCH")
    for key in ("operatingIncomeMillionTwd", "pretaxProfitMillionTwd", "incomeTaxExpenseMillionTwd"):
        if config["financials"][key] != results["facts"][key]:
            raise ValueError(f"Q2_RESULTS_FACT_MISMATCH:{key}")
    for key in ("cashAndCashEquivalentsMillionTwd", "netCashMillionTwd"):
        if config["balanceSheet"][key] != results["facts"][key]:
            raise ValueError(f"Q2_BALANCE_FACT_MISMATCH:{key}")

    operating_income = _d(results["facts"]["operatingIncomeMillionTwd"])
    cash = _d(results["facts"]["cashAndCashEquivalentsMillionTwd"])
    net_cash = _d(results["facts"]["netCashMillionTwd"])
    equity = _d(twse["facts"]["parentEquityThousandTwd"]) / 1000
    tax_rate = _d(method["facts"]["annualTaxRatePct"]) / 100
    debt = cash - net_cash
    invested_capital = debt + equity - cash
    nopat = operating_income * (1 - tax_rate) * 4
    roic = nopat / invested_capital * 100
    release_gate = _roic_gate_evidence(receipt)
    return {
        "schemaVersion": "1.1", "status": "OWNER_APPROVED_FOR_PROMOTION",
        "result": "PASS" if release_gate["allPassed"] else "PASS_WITH_ROIC_CONDITIONAL_PENDING",
        "entity": receipt["entity"], "companyCode": receipt["companyCode"], "fiscalPeriod": receipt["fiscalPeriod"],
        "publicationDate": config["publicationDate"], "effectiveDate": Q2_EFFECTIVE_DATE,
        "kpis": {
            "bvps": {"value": twse["facts"]["bookValuePerShareTwd"], "unit": "TWD_PER_SHARE", "period": "2026Q2", "classification": "OFFICIAL_REPORTED", "displayLabelZh": "136.02元（官方申報）", "sourceLocator": twse["sourceLocator"], "sourceDate": twse["sourceDate"], "derivation": None},
            "roe": {"value": press["facts"]["roeH1Pct"], "unit": "PERCENT", "period": press["facts"]["roePeriod"], "annualized": False, "classification": "OFFICIAL_REPORTED", "displayLabelZh": "6.21%（2026上半年官方值，未年化）", "comparablePriorValue": press["facts"]["roePriorH1Pct"], "sourceLocator": press["sourceLocator"], "derivation": None},
            "roic": {
                "candidateValue": _q(roic, "0.01"), "canonicalValue": _q(roic, "0.01") if release_gate["allPassed"] else None,
                "unit": "PERCENT", "period": "2026Q2", "classification": "DERIVED_VERIFIED" if release_gate["allPassed"] else "OWNER_CONDITIONAL_PENDING",
                "displayLabelZh": f"{_q(roic, '0.01')}%（條件式推算，尚未升格）", "formula": "NOPAT_Annual / InvestedCapital * 100",
                "numerator": {"name": "NOPAT_Annual", "valueMillionTwd": _q(nopat, "0.0001"), "formula": "94803 * (1 - 26.72%) * 4"},
                "denominator": {"name": "InvestedCapital", "valueMillionTwd": _q(invested_capital, "0.001"), "formula": "InterestBearingDebt + ParentEquity - Cash", "interestBearingDebtMillionTwd": _q(debt, "0.001"), "parentEquityMillionTwd": _q(equity, "0.001"), "cashMillionTwd": _q(cash, "0.001")},
                "methodologyLocator": method["sourceLocator"], "sourceLocators": [results["sourceLocator"], twse["sourceLocator"]], "releaseGate": release_gate,
            },
        },
        "dataGaps": [] if release_gate["allPassed"] else ["ROIC_NET_CASH_DEFINITION_SCOPE_UNRESOLVED"],
        "authorityMutation": False, "formalCsvModified": False, "actionable": False,
    }


def _q2_master_row(fields: list[str], config: dict[str, Any], candidate: dict[str, Any], quarter_close: str) -> dict[str, str]:
    f, b = config["financials"], config["balanceSheet"]
    bvps, close = _d(candidate["kpis"]["bvps"]["value"]), _d(quarter_close)
    values = {
        "Quarter": "2026Q2", "QuarterEndDate": "2026-06-30", "EstimatedEffectiveDate": Q2_EFFECTIVE_DATE,
        "Revenue_Q_100M": _q(_d(f["revenueMillionTwd"]) / 10, "0.01"), "GrossMarginPct": f["grossMarginPct"], "OperatingIncome_Q_100M": _q(_d(f["operatingIncomeMillionTwd"]) / 10, "0.01"), "OperatingMarginPct": f["operatingMarginPct"], "OperatingMarginStatus": "ABOVE_MINIMUM_FLOOR",
        "TaxExpense_Q_1M": f["incomeTaxExpenseMillionTwd"], "TaxRev_Pct": _q(_d(f["incomeTaxExpenseMillionTwd"]) / _d(f["revenueMillionTwd"]) * 100, "0.001"), "TaxRevMean_Pct": "N/A", "TaxRevStd_Pct": "N/A", "TaxZ": "N/A", "TaxZ_Status": "PERIOD_METHOD_NOT_APPLICABLE",
        "EPS_Q": f["epsTwd"], "EPS_YoY_Pct": f["epsYoyPct"], "EPS_TTM": "15.21", "BVPS": str(bvps), "QuarterEndClose": str(close), "CloseAdjusted": str(close),
        "ROE_Annual_Pct": "N/A", "ROE_TTM_Pct": "N/A", "PB_QuarterEnd": _q(close / bvps, "0.001"), "PB_Adjusted": _q(close / bvps, "0.001"), "PB_Zone": "DESCRIPTIVE_ONLY", "ROE_Signal": "H1_OFFICIAL_NON_ANNUALIZED_6.21",
        "payoutRatio_Pct": "N/A", "CashDividend": "7.17179227", "DividendYield_Pct": _q(_d("7.17179227") / close * 100, "0.01"), "FCF_Annual_100M": "N/A", "MarketCap_100M": "N/A", "FCFYield_Annual_Pct": "N/A",
        "ROIC_Approx_Pct": "N/A", "ROIC_Precise_Pct": candidate["kpis"]["roic"]["canonicalValue"] or "N/A", "ROIC_Status": "DERIVED_VERIFIED" if candidate["kpis"]["roic"]["canonicalValue"] else "OWNER_CONDITIONAL_PENDING", "NOPAT_Annual_100M": "N/A", "InvestedCapital_100M": "N/A",
        "Cash_100M": _q(_d(b["cashAndCashEquivalentsMillionTwd"]) / 10, "0.01"), "InterestBearingDebt_100M": "N/A", "NetDebt_100M": _q(-_d(b["netCashMillionTwd"]) / 10, "0.01"), "NetDebtStatus": "NET_CASH", "EBITDA_Approx_100M": "N/A", "DA_Est_100M": "N/A", "NetDebtToEBITDA_Approx": "N/A", "NetDebtToEBITDA_Status": "N/A",
        "BalanceSheetDataQuality": "OFFICIAL_Q2_PERIOD_END", "DataSource": "HONHAI_RESULTS_TWSE_OPENAPI_OFFICIAL", "DataSupportLevel": "A1_L1_MIXED_PERIOD", "LookaheadRisk": "LOW",
        "Notes": "ROE_2026H1_6.21_OFFICIAL_NON_ANNUALIZED;CASH_FLOW_2026H1_OCF_-69122_CAPEX_80886_FCF_-150009;ROIC_OWNER_CONDITIONAL_PENDING_GATE_A;AI_SHARE_NOT_DISCLOSED;CLOUD_NETWORKING_51_NOT_AI_SHARE",
        "ForeignHoldRatio_Pct": "N/A", "ForeignHoldChange_Pct": "N/A", "ForeignHoldTrend": "N/A", "AI_Revenue_Pct": "N/A",
    }
    if set(fields) != set(values):
        raise ValueError(f"Q2_MASTER_SCHEMA_MISMATCH:missing={sorted(set(fields)-set(values))}:extra={sorted(set(values)-set(fields))}")
    return {name: values[name] for name in fields}


def _atomic_replace(path: Path, content: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def promote(package_root: Path = PACKAGE_ROOT) -> dict[str, Any]:
    root = package_root.resolve()
    master_path, daily_path = root / "data/2317_master_v9.csv", root / "data/2317_daily_price.csv"
    manifest_path, config_path = root / "data/CSV_AUTHORITY_MANIFEST.json", root / CONFIG_REL
    candidate = build_candidate(root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for rel in ("data/2317_master_v9.csv", "data/2317_daily_price.csv"):
        _verify_manifest_file(root, manifest, rel)
    governed = ("data/2317_master_v9.csv", "data/2317_daily_price.csv", "data/CSV_AUTHORITY_MANIFEST.json")
    pre = {rel: {"sha256": _sha(root / rel), "fileSizeBytes": len((root / rel).read_bytes())} for rel in governed}

    comments, fields, master_rows = _read_csv(master_path)
    if any(row["Quarter"] == "2026Q2" for row in master_rows):
        raise ValueError("Q2_ALREADY_PRESENT")
    original_master_rows = deepcopy(master_rows)
    _, daily_fields, daily_rows = _read_csv(daily_path)
    quarter_close = next((row["Close"] for row in daily_rows if row["Date"] == "2026-06-30"), None)
    if quarter_close != "251.0":
        raise ValueError("Q2_QUARTER_END_CLOSE_MISMATCH")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    master_rows.append(_q2_master_row(fields, config, candidate, quarter_close))
    new_master = _csv_bytes(comments, fields, master_rows)
    if master_rows[:-1] != original_master_rows:
        raise ValueError("HISTORICAL_MASTER_MUTATION")

    for row in daily_rows:
        if row["Date"] >= Q2_EFFECTIVE_DATE:
            row["QuarterKey"], row["BVPS_ref"] = "2026Q2", "136.02"
            row["PB_daily"] = _q(_d(row["Close"]) / Decimal("136.02"), "0.001")
    current = next((row for row in daily_rows if row["Date"] == CURRENT_DATE), None)
    if current is None or current["PB_daily"] != "1.853":
        raise ValueError("CURRENT_PB_RECOMPUTE_FAILED")
    new_daily = _csv_bytes([], daily_fields, daily_rows)

    config["canonicalPromotion"] = {
        "status": candidate["result"], "ownerApprovalReference": OWNER_APPROVAL, "canonicalQuarter": "2026Q2", "effectiveDate": Q2_EFFECTIVE_DATE,
        "bvps": candidate["kpis"]["bvps"], "roe": candidate["kpis"]["roe"], "roic": candidate["kpis"]["roic"],
        "currentPb": {"value": "1.853", "unit": "MULTIPLE", "classification": "DERIVED_VERIFIED", "displayLabelZh": "1.853x（推算）", "close": "252.0", "closeDate": CURRENT_DATE, "bvps": "136.02", "bvpsPeriod": "2026Q2", "formula": "252.0 / 136.02"},
        "aiIndustryGuard": {"historicalAi40CurrentInput": False, "cloudNetworking51IsAiShare": False, "aiRevenuePct": None}, "actionable": False,
    }
    new_config = _json_bytes(config)
    published_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_manifest = deepcopy(manifest)
    master_entry, daily_entry = _entry(new_manifest, "data/2317_master_v9.csv"), _entry(new_manifest, "data/2317_daily_price.csv")
    master_entry.update({"sha256": _sha_bytes(new_master), "fileSizeBytes": len(new_master), "rowCount": len(master_rows), "latestQuarter": "2026Q2", "lastPublishedAt": published_at})
    master_entry.setdefault("fieldOverrides", {})["FY2026Q2"] = {"classification": "OFFICIAL_REPORTED_WITH_PERIOD_SPECIFIC_FIELDS", "bvps": "136.02/2026Q2", "roe": "6.21/2026H1/NON_ANNUALIZED", "roic": "OWNER_CONDITIONAL_PENDING", "cashFlow": "2026H1", "aiRevenuePct": None, "sourceConfig": CONFIG_REL.as_posix(), "zh": "Q2官方欄位已升格；ROE與現金流保留H1期間，ROIC因淨現金定義未證明而不升格。"}
    daily_entry.update({"sha256": _sha_bytes(new_daily), "fileSizeBytes": len(new_daily), "rowCount": len(daily_rows), "lastPublishedAt": published_at})
    daily_entry["lastBvpsRebind"] = {"effectiveDate": Q2_EFFECTIVE_DATE, "quarterKey": "2026Q2", "bvps": "136.02", "currentDate": CURRENT_DATE, "currentClose": "252.0", "currentPb": "1.853", "formula": "round(Close / BVPS_ref, 3)", "classification": "DERIVED_VERIFIED", "actionable": False}
    new_manifest["approvedAt"] = published_at[:10]
    new_manifest["approvalSource"] = str(new_manifest.get("approvalSource", "")) + f"; {OWNER_APPROVAL}"
    new_manifest["lastQuarterlyPromotion"] = {"quarter": "2026Q2", "publishedAt": published_at, "result": candidate["result"], "roicStatus": "OWNER_CONDITIONAL_PENDING", "actionable": False}
    new_manifest_bytes = _json_bytes(new_manifest)

    planned = {master_path: new_master, daily_path: new_daily, config_path: new_config, manifest_path: new_manifest_bytes}
    originals = {path: path.read_bytes() for path in planned}
    try:
        for path, content in planned.items():
            _atomic_replace(path, content)
        post_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _verify_manifest_file(root, post_manifest, "data/2317_master_v9.csv")
        _verify_manifest_file(root, post_manifest, "data/2317_daily_price.csv")
        if sum(row["Quarter"] == "2026Q2" for row in _read_csv(master_path)[2]) != 1:
            raise ValueError("Q2_CANONICAL_UNIQUENESS_FAILED")
    except Exception:
        for path, content in originals.items():
            _atomic_replace(path, content)
        raise

    report = {
        "schemaVersion": "1.0", "result": candidate["result"], "ownerApprovalReference": OWNER_APPROVAL,
        "canonicalQuarterBefore": "2026Q1", "canonicalQuarterAfter": "2026Q2", "roicStatus": "OWNER_CONDITIONAL_PENDING",
        "roicReleaseGate": candidate["kpis"]["roic"]["releaseGate"], "pre": pre,
        "post": {rel: {"sha256": _sha(root / rel), "fileSizeBytes": len((root / rel).read_bytes())} for rel in governed},
        "master": {"rowCountBefore": len(master_rows)-1, "rowCountAfter": len(master_rows), "q2Count": 1, "historicalRowsImmutable": True},
        "daily": {"rowCount": len(daily_rows), "reboundFrom": Q2_EFFECTIVE_DATE, "currentClose": "252.0", "currentPb": "1.853"},
        "formalCsvModified": True, "reportPublished": False, "actionable": False,
    }
    report_path = root / PROMOTION_REPORT_REL
    report_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_replace(report_path, _json_bytes(report))
    return report


def write_outputs(candidate: dict[str, Any], package_root: Path = PACKAGE_ROOT) -> None:
    audit = package_root / AUDIT_REL
    audit.mkdir(parents=True, exist_ok=True)
    (package_root / CANDIDATE_REL).write_text(json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    roic = candidate["kpis"]["roic"]
    lines = ["# P1008 FY2026 Q2 KPI Completion Candidate", "", f"狀態：`{candidate['result']}`。不改UI分數，也不形成交易指令。", "", "## 完成結果", "", "- BVPS：136.02元（官方申報）。", "- ROE：6.21%（2026上半年官方值，未年化）；2025H1為5.48%。", f"- ROIC：候選{roic['candidateValue']}%；正式狀態`OWNER_CONDITIONAL_PENDING`。", "", "## ROIC閘門", ""]
    lines.extend(f"- Gate {key}：`{item['status']}`；{item['labelZh']}。" for key, item in roic["releaseGate"]["gates"].items())
    lines.extend(["", "Gate A未通過，所以16.46%不進正式ROIC欄位；Q2其他官方KPI仍可升格。"])
    (package_root / SUMMARY_REL).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, default=PACKAGE_ROOT)
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--approval-reference")
    args = parser.parse_args()
    root = args.package_root.resolve()
    candidate = build_candidate(root)
    write_outputs(candidate, root)
    if args.promote:
        if args.approval_reference != OWNER_APPROVAL:
            raise SystemExit("OWNER_APPROVAL_REFERENCE_MISMATCH")
        print(json.dumps(promote(root), ensure_ascii=True, indent=2))
    else:
        print(json.dumps({"status": candidate["status"], "result": candidate["result"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
