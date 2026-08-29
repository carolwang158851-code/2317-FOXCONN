"""Layered historical research reconstruction for P1008 war reports.

The verified local baseline remains immutable and canonical.  This module adds
source-receipted official observations, exact derivations, explicitly labelled
estimates, and external cross-checks without promoting any of them into formal
production authority.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..phaseb1_common import canonical_json_bytes, sha256_bytes, sha256_file
from .historical_kpi_baseline import HistoricalKPIBaselineError, build_historical_kpi_baseline


T0 = "T0_DIRECT_OFFICIAL"
T1 = "T1_EXACT_DERIVED"
T2 = "T2_ESTIMATED_DERIVED"
T3 = "T3_EXTERNAL_CROSSCHECK"
T4 = "T4_MODEL_SCENARIO"
DATA_CLASSES = (T0, T1, T2, T3, T4)
CONFIDENCE_CLASSES = ("HIGH", "MEDIUM", "LOW")


def _dec(value: Any) -> Decimal:
    return Decimal(str(value).replace(",", "").replace("%", ""))


def _period_dates(period: str) -> tuple[str, str, int, int | None, str]:
    year = int(period[:4])
    if period.endswith("FY"):
        return f"{year}-01-01", f"{year}-12-31", year, None, "FY_CUMULATIVE"
    if period.endswith("H1"):
        return f"{year}-01-01", f"{year}-06-30", year, None, "H1_CUMULATIVE"
    if period.endswith("M9"):
        return f"{year}-01-01", f"{year}-09-30", year, None, "M9_CUMULATIVE"
    if len(period) == 6 and period[4] == "Q" and period[5] in "1234":
        quarter = int(period[5])
        starts = {1: "01-01", 2: "04-01", 3: "07-01", 4: "10-01"}
        ends = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
        return f"{year}-{starts[quarter]}", f"{year}-{ends[quarter]}", year, quarter, f"Q{quarter}_STANDALONE"
    raise HistoricalKPIBaselineError(f"RESEARCH_PERIOD_INVALID:{period}")


def estimate_weighted_average_shares(
    *, parent_net_income_million_twd: Any, reported_basic_eps_twd: Any,
    period: str, source_ids: Sequence[str], decimal_places: int = 2,
) -> dict[str, Any]:
    """Estimate compatible basic weighted-average shares with EPS rounding bounds."""
    income = _dec(parent_net_income_million_twd)
    eps = _dec(reported_basic_eps_twd)
    half = Decimal(5).scaleb(-(decimal_places + 1))
    eps_low, eps_high = eps - half, eps + half
    if income <= 0 or eps_low <= 0:
        raise HistoricalKPIBaselineError("WA_SHARE_ESTIMATE_INPUT_INVALID")
    point = income / eps
    lower = income / eps_high
    upper = income / eps_low
    return {
        "metric_id": "WA_SHARES_BASIC_EST", "period": period,
        "value": str(point), "lower_bound": str(lower), "upper_bound": str(upper),
        "unit": "百萬股", "basis": "BASIC_EPS_COMPATIBLE_WEIGHTED_AVERAGE",
        "data_class": T2, "direct_or_derived": "ESTIMATED",
        "estimate_method": "PARENT_NET_INCOME_DIVIDED_BY_REPORTED_BASIC_EPS_V1",
        "formula": "母公司業主淨利／公告基本EPS",
        "inputs": {"parent_net_income_million_twd": str(income), "reported_basic_eps_twd": str(eps)},
        "input_observation_ids": list(source_ids),
        "assumptions": [f"基本EPS依小數第{decimal_places}位四捨五入揭露", "淨利與EPS期間及普通股範圍相容"],
        "rounding_effect": f"unrounded EPS in [{eps_low}, {eps_high})",
        "confidence_class": "HIGH", "limitations": "EPS四捨五入造成分母區間；非公司直接揭露股數。",
        "reconciliation_state": "ESTIMATE_ACTIVE", "actionable": False,
    }


def fcf_per_share(
    *, fcf_million_twd: Any, weighted_average_shares: Mapping[str, Any],
    period: str, fcf_observation_id: str,
) -> dict[str, Any]:
    shares = _dec(weighted_average_shares["value"])
    if shares <= 0 or weighted_average_shares.get("basis") != "BASIC_EPS_COMPATIBLE_WEIGHTED_AVERAGE":
        raise HistoricalKPIBaselineError("FCF_PER_SHARE_DENOMINATOR_INVALID")
    denominator_class = weighted_average_shares["data_class"]
    if denominator_class not in {T0, T1, T2}:
        raise HistoricalKPIBaselineError("FCF_PER_SHARE_DENOMINATOR_CLASS_INVALID")
    data_class = T2 if denominator_class == T2 else T1
    fcf = _dec(fcf_million_twd)
    result = {
        "metric_id": "FCF_PER_SHARE", "period": period, "value": str(fcf / shares),
        "unit": "新台幣元／股", "basis": "FCF_PER_SHARE_V1",
        "data_class": data_class, "direct_or_derived": "ESTIMATED" if data_class == T2 else "DERIVED",
        "formula": "期間FCF／相容期間基本加權平均普通股數",
        "formula_version": "FCF_PER_SHARE_V1",
        "input_observation_ids": [fcf_observation_id, str(weighted_average_shares["observation_id"])],
        "confidence_class": weighted_average_shares.get("confidence_class", "HIGH"),
        "limitations": "流量指標使用加權平均股數；不得以期末股數替代。",
        "actionable": False,
    }
    if data_class == T2:
        lower_shares = _dec(weighted_average_shares["lower_bound"])
        upper_shares = _dec(weighted_average_shares["upper_bound"])
        values = (fcf / lower_shares, fcf / upper_shares)
        result["lower_bound"] = str(min(values))
        result["upper_bound"] = str(max(values))
        result["estimate_method"] = "FCF_DIVIDED_BY_T2_WA_SHARES_V1"
        result["assumptions"] = weighted_average_shares["assumptions"]
        result["rounding_effect"] = weighted_average_shares["rounding_effect"]
        result["reconciliation_state"] = "ESTIMATE_ACTIVE"
    return result


def reconcile_estimate(estimate: Mapping[str, Any], official_value: Any) -> dict[str, Any]:
    estimated = _dec(estimate["value"])
    official = _dec(official_value)
    absolute = official - estimated
    return {
        "estimated_value": str(estimated), "official_value": str(official),
        "absolute_difference": str(absolute),
        "percentage_difference": str((absolute / official * 100) if official else Decimal(0)),
        "estimate_method": estimate.get("estimate_method"),
        "reconciliation_state": "OFFICIAL_REPLACEMENT_AVAILABLE",
        "canonical_data_class": T0, "estimate_lineage_preserved": True,
    }


def resolve_crosscheck(primary: Mapping[str, Any], checks: Sequence[Mapping[str, Any]], *, material_tolerance_pct: Decimal = Decimal("1")) -> dict[str, Any]:
    primary_value = _dec(primary["value"])
    differences = []
    conflict = False
    for check in checks:
        diff = (_dec(check["value"]) - primary_value) / primary_value * 100 if primary_value else Decimal(0)
        differences.append({"source_id": check["source_id"], "difference_pct": str(diff)})
        conflict = conflict or abs(diff) > material_tolerance_pct
    return {"canonical_value": str(primary_value), "canonical_data_class": primary["data_class"], "crosschecks": differences, "state": "CROSSCHECK_CONFLICT" if conflict else "CROSSCHECK_CONSISTENT", "averaged": False}


def _catalog_path(package_root: Path) -> Path:
    return package_root / "contracts/p1008_report_production/v1.1/P1008_HISTORICAL_RESEARCH_SOURCE_CATALOG_V1.json"


def load_source_catalog(package_root: Path) -> dict[str, Any]:
    path = _catalog_path(package_root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    receipts = payload.get("source_receipts", [])
    if not receipts or any(item.get("source_tier") not in {T0, T3} for item in receipts):
        raise HistoricalKPIBaselineError("SOURCE_CATALOG_TIER_INVALID")
    for item in receipts:
        if not str(item.get("source_locator", "")).startswith("https://") or len(str(item.get("content_hash", ""))) != 64:
            raise HistoricalKPIBaselineError("SOURCE_RECEIPT_INVALID")
        if "snippet" in str(item.get("notes", "")).casefold():
            raise HistoricalKPIBaselineError("SEARCH_SNIPPET_NOT_PRIMARY_EVIDENCE")
    return payload


def _source_map(catalog: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {item["source_id"]: item for item in catalog["source_receipts"]}


def _research_observation(
    *, metric_id: str, metric_family: str, period: str, value: Any, unit: str,
    basis: str, data_class: str, source: Mapping[str, Any], formula: str = "DIRECT_REPORTED",
    inputs: Sequence[str] = (), notes: str = "", confidence: str = "HIGH",
) -> dict[str, Any]:
    if data_class not in DATA_CLASSES or confidence not in CONFIDENCE_CLASSES:
        raise HistoricalKPIBaselineError("RESEARCH_CLASS_INVALID")
    start, end, year, quarter, period_type = _period_dates(period)
    key = "|".join((metric_id, period, basis, formula, data_class))
    item = {
        "observation_id": "RKPI-" + sha256_bytes(key.encode("utf-8"))[:24],
        "observation_key": key, "metric_id": metric_id, "metric_family": metric_family,
        "period": period, "period_type": period_type, "period_start": start,
        "period_end": end, "fiscal_year": year, "fiscal_quarter": quarter,
        "value": str(value), "unit": unit, "currency": "TWD" if "新台幣" in unit else None,
        "basis": basis, "data_class": data_class,
        "direct_or_derived": "DIRECT" if data_class == T0 else ("DERIVED" if data_class == T1 else ("ESTIMATED" if data_class == T2 else "CROSSCHECK")),
        "formula_version": formula, "formula": formula,
        "source_id": source["source_id"], "source_type": source["source_type"],
        "source_locator": source["source_locator"], "source_hash": source["content_hash"],
        "input_observation_ids": list(inputs), "availability_state": "AVAILABLE",
        "confidence_class": confidence, "notes": notes, "actionable": False,
    }
    if data_class == T1 and not inputs:
        raise HistoricalKPIBaselineError("DERIVED_LINEAGE_MISSING")
    return item


def _append_unique(rows: list[dict[str, Any]], item: Mapping[str, Any]) -> None:
    key = str(item["observation_key"])
    existing = next((row for row in rows if row["observation_key"] == key), None)
    if existing is None:
        rows.append(dict(item))
    elif canonical_json_bytes(existing) != canonical_json_bytes(dict(item)):
        raise HistoricalKPIBaselineError(f"CONFLICTING_RESEARCH_OBSERVATION:{key}")


def _with_identity(item: Mapping[str, Any], *, source: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(item)
    key = "|".join((str(result["metric_id"]), str(result["period"]), str(result["basis"]), str(result.get("estimate_method", result.get("formula_version", ""))), str(result["data_class"])))
    result.update({
        "observation_id": "RKPI-" + sha256_bytes(key.encode("utf-8"))[:24],
        "observation_key": key, "source_id": source["source_id"],
        "source_type": source["source_type"], "source_locator": source["source_locator"],
        "source_hash": source["content_hash"], "availability_state": "AVAILABLE",
    })
    start, end, year, quarter, period_type = _period_dates(str(result["period"]))
    result.update({"metric_family": "PER_SHARE", "period_start": start, "period_end": end, "fiscal_year": year, "fiscal_quarter": quarter, "period_type": period_type, "currency": None})
    return result


def build_layered_historical_research_baseline(package_root: Path, analysis: Any) -> dict[str, Any]:
    core = build_historical_kpi_baseline(package_root, analysis)
    catalog = load_source_catalog(package_root)
    sources = _source_map(catalog)
    rows: list[dict[str, Any]] = []
    for raw in deepcopy(core["observations"]):
        raw["data_class"] = T0 if raw["direct_or_derived"] == "DIRECT" else T1
        raw["confidence_class"] = "HIGH"
        rows.append(raw)

    cumulative_by_period_metric: dict[tuple[str, str], dict[str, Any]] = {}
    for record in catalog["official_observations"]["cash_flow_cumulative_million_twd"]:
        source = sources[record["source_id"]]
        for metric in ("CFO", "CAPEX", "FCF"):
            item = _research_observation(
                metric_id=metric, metric_family="CASH_FLOW", period=record["period"], value=record[metric],
                unit="新台幣百萬元", basis="YTD_CUMULATIVE", data_class=T0, source=source,
                notes=f"{record['basis']}；Capex以正數現金流出呈現。",
            )
            _append_unique(rows, item)
            cumulative_by_period_metric[(record["period"], metric)] = item

    # Keep rounded IR disclosure inputs as auditable observations without
    # merging them into the higher-precision cumulative research series.
    rounded_ir_inputs: dict[tuple[str, str], dict[str, Any]] = {}
    for record in catalog["official_observations"]["cash_flow_derivation_inputs_rounded_ir_million_twd"]:
        source = sources[record["source_id"]]
        for metric in ("CFO", "CAPEX", "FCF"):
            item = _research_observation(
                metric_id=f"{metric}_IR_ROUNDED_INPUT",
                metric_family="CASH_FLOW_DERIVATION_INPUT",
                period=record["period"],
                value=record[metric],
                unit="新台幣百萬元",
                basis="YTD_CUMULATIVE_IR_ROUNDED",
                data_class=T0,
                source=source,
                notes=f"{record['basis']}；僅供同揭露精度之單季精確相減；不取代精確累計序列。",
            )
            _append_unique(rows, item)
            rounded_ir_inputs[(record["period"], metric)] = item

    # Standalone periods are exact arithmetic from same-basis cumulative statements.
    local_q1 = {(row["period"], row["metric_id"]): row for row in rows if row["period"] == "2025Q1" and row["metric_id"] in {"CFO", "CAPEX", "FCF"}}
    derivations = (
        ("2025Q2", "2025H1", "2025Q1", "H1_MINUS_Q1_SAME_STATEMENT_BASIS_V1"),
        ("2025Q3", "2025M9", "2025H1", "M9_MINUS_H1_SAME_STATEMENT_BASIS_V1"),
        ("2025Q4", "2025FY", "2025M9", "FY_MINUS_M9_IR_RESULTS_ROUNDED_V1"),
    )
    for result_period, current_period, prior_period, formula in derivations:
        for metric in ("CFO", "CAPEX", "FCF"):
            current = cumulative_by_period_metric[(current_period, metric)]
            if result_period == "2025Q4":
                prior = rounded_ir_inputs[(prior_period, metric)]
            else:
                prior = local_q1[(prior_period, metric)] if prior_period == "2025Q1" else cumulative_by_period_metric[(prior_period, metric)]
            value = _dec(current["value"]) - _dec(prior["value"])
            item = _research_observation(
                metric_id=metric, metric_family="CASH_FLOW", period=result_period, value=value,
                unit="新台幣百萬元", basis="Q_STANDALONE", data_class=T1,
                source=sources[current["source_id"]], formula=formula,
                inputs=[prior["observation_id"], current["observation_id"]],
                notes="同範圍累計報表相減；若來源為整數百萬元表，保留其揭露精度。",
            )
            _append_unique(rows, item)

    # Extend point-in-time working capital without changing the governed direct CCC series.
    import csv
    with (package_root / "data/2317_master_v9.csv").open(encoding="utf-8-sig", newline="") as handle:
        master_rows = {row["Quarter"]: row for row in csv.DictReader(line for line in handle if line.strip() and not line.startswith("##"))}
    for record in catalog["official_observations"]["working_capital_million_twd"]:
        source = sources[record["source_id"]]
        components: dict[str, dict[str, Any]] = {}
        for metric in ("AR", "INVENTORY", "AP"):
            item = _research_observation(metric_id=metric, metric_family="WORKING_CAPITAL", period=record["period"], value=record[metric], unit="新台幣百萬元", basis="QUARTER_END_BALANCE", data_class=T0, source=source)
            _append_unique(rows, item)
            components[metric] = item
        nwc = _research_observation(
            metric_id="NWC_PROXY", metric_family="WORKING_CAPITAL", period=record["period"],
            value=_dec(record["AR"]) + _dec(record["INVENTORY"]) - _dec(record["AP"]), unit="新台幣百萬元",
            basis="QUARTER_END_BALANCE", data_class=T1, source=source,
            formula="AR_PLUS_INVENTORY_MINUS_AP_V1", inputs=[components[x]["observation_id"] for x in ("AR", "INVENTORY", "AP")],
            notes="NWC Proxy，不等同公司正式揭露之淨營運資金。",
        )
        _append_unique(rows, nwc)
        master = master_rows[record["period"]]
        revenue = _dec(master["Revenue_Q_100M"]) * 100
        cogs = revenue * (Decimal(1) - _dec(master["GrossMarginPct"]) / 100)
        dso = _dec(record["AR"]) / revenue * 90
        dio = _dec(record["INVENTORY"]) / cogs * 90
        dpo = _dec(record["AP"]) / cogs * 90
        ccc = _research_observation(
            metric_id="CCC_EST", metric_family="WORKING_CAPITAL_DAYS", period=record["period"],
            value=dso + dio - dpo, unit="天", basis="CCC_EST_V1_END_BALANCE_90_DAY",
            data_class=T2, source=source, formula="END_AR_DIV_REVENUE_PLUS_END_INV_DIV_COGS_MINUS_END_AP_DIV_COGS_TIMES_90_V1",
            inputs=[components[x]["observation_id"] for x in ("AR", "INVENTORY", "AP")],
            notes="估算：使用季末餘額而非平均餘額，與CCC_GOVERNED分列。", confidence="MEDIUM",
        )
        ccc.update({"estimate_method": ccc["formula_version"], "assumptions": ["季度90天", "COGS=營收×(1-毛利率)", "季末餘額代理平均餘額"], "rounding_effect": "來源金額及毛利率揭露精度", "limitations": "季末餘額可能受季節性與拉貨時點影響。", "reconciliation_state": "ESTIMATE_ACTIVE"})
        _append_unique(rows, ccc)

    wa_by_period: dict[str, dict[str, Any]] = {}
    for record in catalog["official_observations"]["weighted_average_shares_million"]:
        source = sources[record["source_id"]]
        item = _research_observation(
            metric_id="WA_SHARES_BASIC", metric_family="SHARE_COUNT", period=record["period"], value=record["value"],
            unit="百萬股", basis="BASIC_EPS_COMPATIBLE_WEIGHTED_AVERAGE", data_class=T0, source=source,
            notes=f"官方EPS附註；母公司業主淨利{record['parent_net_income_million_twd']}百萬元、基本EPS {record['basic_eps_twd']}元。",
        )
        _append_unique(rows, item)
        wa_by_period[record["period"]] = item

    q2_source = sources["HONHAI_2025Q2_CONSOLIDATED"]
    q3_source = sources["HONHAI_2025Q3_CONSOLIDATED"]
    q2_2026_source = {
        "source_id": "HONHAI_FY2026_Q2_GOVERNED_PACKET", "source_type": "OFFICIAL_LOCAL_FILING",
        "source_locator": "modules/p1008_research_plugin/config/quarterly_earnings/FY2026_Q2.json#financials",
        "content_hash": str(analysis.quarterly_earnings.source_hash).upper(),
    }
    estimate = estimate_weighted_average_shares(
        parent_net_income_million_twd=analysis.quarterly_earnings.attributable_profit.value,
        reported_basic_eps_twd=analysis.quarterly_earnings.eps.value,
        period="2026Q2", source_ids=list(analysis.quarterly_earnings.eps.evidence_ids),
    )
    estimate = _with_identity(estimate, source=q2_2026_source)
    _append_unique(rows, estimate)

    fcf_rows = {(row["period"], row["metric_id"]): row for row in rows if row["metric_id"] == "FCF" and row["basis"] == "Q_STANDALONE"}
    for period, wa, source in (("2025Q2", wa_by_period["2025Q2"], q2_source), ("2025Q3", wa_by_period["2025Q3"], q3_source), ("2026Q2", estimate, q2_2026_source)):
        fcf_row = fcf_rows[(period, "FCF")]
        per_share = fcf_per_share(fcf_million_twd=fcf_row["value"], weighted_average_shares=wa, period=period, fcf_observation_id=fcf_row["observation_id"])
        per_share = _with_identity(per_share, source=source)
        _append_unique(rows, per_share)

    crosschecks = []
    for record in catalog["external_crosschecks"]:
        source = sources[record["source_id"]]
        item = _research_observation(metric_id=record["metric_id"], metric_family="SHARE_COUNT", period=record["period"], value=record["value"], unit=record["unit"], basis=record["basis"], data_class=T3, source=source, confidence=record["confidence"], notes="外部交叉核對；不可覆寫T0/T1。")
        _append_unique(rows, item)
        crosschecks.append(item)

    # Explicitly preserve the Q1 price discrepancy rather than mutating master authority.
    q1_pb = next(row for row in rows if row["metric_id"] == "PB" and row["period"] == "2026Q1")
    master_q1 = master_rows["2026Q1"]
    price_reconciliation = {
        "reconciliation_id": "P1008-PRICE-RECON-2026Q1",
        "metric": "QUARTER_END_PRICE", "period": "2026Q1",
        "master_price_value": master_q1["QuarterEndClose"], "daily_authority_value": q1_pb["price"],
        "source_period": "2026-03-31", "root_cause": "MASTER_QUARTER_SNAPSHOT_DIFFERS_FROM_LATER_FORMAL_DAILY_AUTHORITY; SOURCE_LINEAGE_NOT_PROVEN_FOR_MASTER_VALUE",
        "canonical_runtime_value": q1_pb["price"], "canonical_source": q1_pb["price_source"],
        "raw_master_modified": False, "actionable": False,
    }

    rows.sort(key=lambda row: (row["metric_family"], row["metric_id"], row["period_end"], row["basis"], row["data_class"]))
    metric_counts: dict[str, dict[str, int]] = {}
    for row in rows:
        metric_counts.setdefault(row["metric_id"], {tier: 0 for tier in DATA_CLASSES})[row["data_class"]] += 1
    ledger = [
        {
            "metric": row["metric_id"], "period": row["period"], "displayed_value": row["value"],
            "classification": row["data_class"], "formula": row.get("formula", row.get("formula_version")),
            "inputs": row.get("input_observation_ids", []), "sources": [row["source_id"]], "basis": row["basis"],
            "assumptions": row.get("assumptions", []), "rounding_or_uncertainty": row.get("rounding_effect", "NONE"),
            "confidence": row.get("confidence_class", "HIGH"), "limitations": row.get("limitations", row.get("notes", "")),
            "reconciliation_status": row.get("reconciliation_state", "NOT_APPLICABLE"),
        }
        for row in rows if row["data_class"] in {T1, T2}
    ]
    return {
        "schema_version": "P1008_LAYERED_HISTORICAL_RESEARCH_BASELINE_V1",
        "data_tier_contract": list(DATA_CLASSES), "verified_core_baseline": core,
        "observations": rows, "observation_count": len(rows), "metric_tier_counts": metric_counts,
        "source_receipts": catalog["source_receipts"],
        "source_hashes": {**core["source_hashes"], "historical_research_source_catalog": sha256_file(_catalog_path(package_root))},
        "estimation_derivation_ledger": ledger, "price_reconciliation": price_reconciliation,
        "external_crosscheck_results": {"observations": crosschecks, "policy": "T3_NEVER_OVERWRITES_T0_T1_AND_CONFLICTS_ARE_NOT_AVERAGED"},
        "scenario_contract": {"data_class": T4, "historical_actual_series_allowed": False},
        "decision_engine_evidence_policy": {T0: "DECISION_TRANSITION_ALLOWED_IF_CONTRACT_MET", T1: "DECISION_TRANSITION_ALLOWED_IF_CONTRACT_MET", T2: "WATCH_OR_PARTIAL_ONLY_WITHOUT_CORROBORATION", T3: "CROSSCHECK_SUPPORT_ONLY", T4: "SCENARIO_ONLY"},
        "unavailable": {"official_2026q2_weighted_average_shares": "T2_ESTIMATE_ACTIVE_PENDING_OFFICIAL_RECONCILIATION", "persistent_raw_source_archive": "NO_SANCTIONED_PERSISTENT_LOCATION", "historical_peer_snapshot": "NOT_GENERATED"},
        "raw_authority_modified": False, "generated_from_local_sources_only": False,
        "actionable": False,
    }


def research_observations_for(baseline: Mapping[str, Any], metric: str, *, basis: str | None = None) -> list[dict[str, Any]]:
    rows = [dict(item) for item in baseline["observations"] if item["metric_id"] == metric]
    if basis is not None:
        rows = [item for item in rows if item["basis"] == basis]
    return sorted(rows, key=lambda item: (item["period_end"], item["data_class"]))
