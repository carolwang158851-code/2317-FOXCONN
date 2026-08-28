"""Governed local-only historical KPI normalization for war-report charts.

The builder reads existing authority snapshots and the already-validated Q2
extraction config.  It never writes authority, acquires data, or substitutes a
missing denominator.  Direct and derived observations share a deterministic
identity and fail closed on conflicting upserts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..adapters.authority_adapter import AuthorityAdapter
from ..contract_loader import ContractLoader
from ..phaseb1_common import canonical_json_bytes, sha256_bytes, sha256_file


class HistoricalKPIBaselineError(RuntimeError):
    """A historical observation cannot satisfy the governed contract."""


_REQUIRED = (
    "metric_id", "metric_family", "period", "period_type", "period_start",
    "period_end", "fiscal_year", "fiscal_quarter", "value", "unit",
    "currency", "basis", "direct_or_derived", "formula_version", "source_id",
    "source_type", "source_locator", "source_hash", "input_observation_ids",
    "availability_state", "notes",
)
_ALLOWED_SOURCE_TYPES = {"GOVERNED_PRODUCTION_AUTHORITY", "OFFICIAL_LOCAL_FILING"}


def _dec(value: Any) -> Decimal:
    return Decimal(str(value).replace(",", "").replace("%", ""))


def _quarter_dates(period: str) -> tuple[str, str, int, int]:
    if len(period) != 6 or period[4] != "Q" or period[5] not in "1234":
        raise HistoricalKPIBaselineError(f"QUARTER_PERIOD_INVALID:{period}")
    year, quarter = int(period[:4]), int(period[5])
    starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
    ends = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    sm, sd = starts[quarter]
    em, ed = ends[quarter]
    return date(year, sm, sd).isoformat(), date(year, em, ed).isoformat(), year, quarter


def observation(
    *, metric_id: str, metric_family: str, period: str, period_type: str,
    period_start: str, period_end: str, fiscal_year: int,
    fiscal_quarter: int | None, value: Any, unit: str, currency: str | None,
    basis: str, direct_or_derived: str, formula_version: str,
    source_id: str, source_type: str, source_locator: str, source_hash: str,
    input_observation_ids: Sequence[str] = (), availability_state: str = "AVAILABLE",
    notes: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "metric_id": metric_id, "metric_family": metric_family, "period": period,
        "period_type": period_type, "period_start": period_start, "period_end": period_end,
        "fiscal_year": fiscal_year, "fiscal_quarter": fiscal_quarter,
        "value": str(value) if value is not None else None, "unit": unit,
        "currency": currency, "basis": basis, "direct_or_derived": direct_or_derived,
        "formula_version": formula_version, "source_id": source_id,
        "source_type": source_type, "source_locator": source_locator,
        "source_hash": source_hash.upper(), "input_observation_ids": list(input_observation_ids),
        "availability_state": availability_state, "notes": notes,
    }
    missing = [name for name in _REQUIRED if name not in payload]
    if missing or not source_locator or len(payload["source_hash"]) != 64:
        raise HistoricalKPIBaselineError(f"OBSERVATION_PROVENANCE_INVALID:{missing}")
    if source_type not in _ALLOWED_SOURCE_TYPES:
        raise HistoricalKPIBaselineError("THIRD_PARTY_HISTORICAL_SOURCE_REJECTED")
    if direct_or_derived not in {"DIRECT", "DERIVED"}:
        raise HistoricalKPIBaselineError("DIRECT_DERIVED_STATE_INVALID")
    if direct_or_derived == "DERIVED" and (not formula_version or not input_observation_ids):
        raise HistoricalKPIBaselineError("DERIVED_LINEAGE_MISSING")
    key = "|".join((metric_id, period, basis, formula_version))
    payload["observation_id"] = "HKPI-" + sha256_bytes(key.encode("utf-8"))[:24]
    payload["observation_key"] = key
    payload["actionable"] = False
    return payload


@dataclass
class ObservationStore:
    _by_key: dict[str, dict[str, Any]]

    def __init__(self) -> None:
        self._by_key = {}

    def upsert(self, item: Mapping[str, Any]) -> str:
        candidate = dict(item)
        key = str(candidate.get("observation_key") or "")
        if not key:
            raise HistoricalKPIBaselineError("OBSERVATION_KEY_MISSING")
        prior = self._by_key.get(key)
        if prior is None:
            self._by_key[key] = candidate
            return "APPENDED"
        if canonical_json_bytes(prior) == canonical_json_bytes(candidate):
            return "NO_OP_IDENTICAL"
        raise HistoricalKPIBaselineError(f"CONFLICTING_OBSERVATION:{key}")

    def values(self) -> list[dict[str, Any]]:
        return sorted(self._by_key.values(), key=lambda x: (x["metric_family"], x["metric_id"], x["period_end"], x["basis"]))


def derive_standalone(
    cumulative: Mapping[str, Any], prior_cumulative: Mapping[str, Any], *,
    result_period: str, result_period_type: str, formula_version: str,
) -> dict[str, Any]:
    comparable = ("metric_id", "unit", "currency")
    if any(cumulative.get(name) != prior_cumulative.get(name) for name in comparable):
        raise HistoricalKPIBaselineError("CUMULATIVE_INPUT_BASIS_MISMATCH")
    if cumulative.get("basis") != prior_cumulative.get("basis"):
        raise HistoricalKPIBaselineError("CUMULATIVE_INPUT_BASIS_MISMATCH")
    start, end, year, quarter = _quarter_dates(result_period)
    return observation(
        metric_id=str(cumulative["metric_id"]), metric_family=str(cumulative["metric_family"]),
        period=result_period, period_type=result_period_type, period_start=start,
        period_end=end, fiscal_year=year, fiscal_quarter=quarter,
        value=_dec(cumulative["value"]) - _dec(prior_cumulative["value"]),
        unit=str(cumulative["unit"]), currency=cumulative.get("currency"),
        basis="Q_STANDALONE", direct_or_derived="DERIVED", formula_version=formula_version,
        source_id=str(cumulative["source_id"]), source_type=str(cumulative["source_type"]),
        source_locator=str(cumulative["source_locator"]), source_hash=str(cumulative["source_hash"]),
        input_observation_ids=[str(prior_cumulative["observation_id"]), str(cumulative["observation_id"])],
        notes="同會計範圍、單位、來源版本之累計值相減。",
    )


def select_quarter_end_price(rows: Iterable[Mapping[str, str]], quarter_end: str) -> Mapping[str, str]:
    eligible = [row for row in rows if row.get("Date", row.get("date", "")) <= quarter_end]
    if not eligible:
        raise HistoricalKPIBaselineError("QUARTER_END_PRICE_UNAVAILABLE")
    return max(eligible, key=lambda row: row.get("Date", row.get("date", "")))


def _direct_quarter(
    *, metric: str, family: str, period: str, value: Any, unit: str,
    source_id: str, source_type: str, locator: str, source_hash: str,
    basis: str = "Q_STANDALONE", notes: str = "",
) -> dict[str, Any]:
    start, end, year, quarter = _quarter_dates(period)
    return observation(
        metric_id=metric, metric_family=family, period=period,
        period_type=f"Q{quarter}_STANDALONE" if basis == "Q_STANDALONE" else "POINT_IN_TIME",
        period_start=start, period_end=end, fiscal_year=year, fiscal_quarter=quarter,
        value=value, unit=unit, currency="TWD" if "新台幣" in unit else None,
        basis=basis, direct_or_derived="DIRECT", formula_version="DIRECT_V1",
        source_id=source_id, source_type=source_type, source_locator=locator,
        source_hash=source_hash, notes=notes,
    )


def build_historical_kpi_baseline(package_root: Path, analysis: Any) -> dict[str, Any]:
    if analysis.event_type != "QUARTERLY_EARNINGS" or analysis.quarterly_earnings is None:
        raise HistoricalKPIBaselineError("QUARTERLY_ANALYSIS_REQUIRED")
    adapter = AuthorityAdapter(package_root, ContractLoader(package_root))
    cash = adapter.read_csv("data/2317_cash_flow_authority.csv")
    master = adapter.read_csv("data/2317_master_v9.csv")
    daily_price = adapter.read_csv("data/2317_daily_price.csv")
    qconfig_path = package_root / "modules/p1008_research_plugin/config/quarterly_earnings/FY2026_Q2.json"
    qconfig = json.loads(qconfig_path.read_text(encoding="utf-8"))
    qhash = str(qconfig["expectedSourceSha256"]).upper()
    analysis_source_hash = getattr(
        analysis.quarterly_earnings, "source_hash",
        getattr(analysis.quarterly_earnings, "source_sha256", None),
    )
    if qhash != str(analysis_source_hash).upper():
        raise HistoricalKPIBaselineError("Q2_SOURCE_HASH_MISMATCH")
    store = ObservationStore()
    raw_source_ids: set[str] = set()

    # Official standalone Q1 rows already governed by cash-flow authority.
    for row in cash.rows:
        period = row["period"]
        for metric, column in (("CFO", "operating_cash_flow_thousand_ntd"), ("CAPEX", "ppe_capex_thousand_ntd"), ("FCF", "free_cash_flow_core_thousand_ntd")):
            item = _direct_quarter(
                metric=metric, family="CASH_FLOW", period=period,
                value=_dec(row[column]) / Decimal("1000"), unit="新台幣百萬元",
                source_id=f"AUTH-CASHFLOW-{cash.actual_sha256[:16]}",
                source_type="GOVERNED_PRODUCTION_AUTHORITY",
                locator=f"data/2317_cash_flow_authority.csv#{period}:{column}",
                source_hash=cash.actual_sha256,
                notes=f"{row['verification_status']}；合併報表。",
            )
            store.upsert(item)
            raw_source_ids.add(item["source_id"])

    # Preserve H1 cumulative values, then derive Q2 only through H1 minus Q1.
    cash_cfg = qconfig["cashFlow"]
    h1_start, h1_end, h1_year, _ = (*_quarter_dates("2026Q2"),)
    h1_inputs: dict[str, dict[str, Any]] = {}
    for metric, field in (("CFO", "operatingCashFlowMillionTwd"), ("CAPEX", "capexMillionTwd"), ("FCF", "freeCashFlowMillionTwd")):
        h1 = observation(
            metric_id=metric, metric_family="CASH_FLOW", period="2026H1",
            period_type="H1_CUMULATIVE", period_start="2026-01-01", period_end="2026-06-30",
            fiscal_year=h1_year, fiscal_quarter=None, value=cash_cfg[field], unit="新台幣百萬元",
            currency="TWD", basis="YTD_CUMULATIVE", direct_or_derived="DIRECT",
            formula_version="DIRECT_V1", source_id=f"OFFICIAL-Q2-{qhash[:16]}",
            source_type="OFFICIAL_LOCAL_FILING", source_locator="FY2026_Q2.json#cashFlow",
            source_hash=qhash, notes=cash_cfg["status"],
        )
        store.upsert(h1)
        h1_inputs[metric] = h1
        raw_source_ids.add(h1["source_id"])
    q1_by_metric = {item["metric_id"]: item for item in store.values() if item["period"] == "2026Q1"}
    # A standalone Q1 is YTD-equivalent for the subtraction gate; clone basis only in-memory.
    for metric in ("CFO", "CAPEX"):
        q1 = dict(q1_by_metric[metric])
        q1["basis"] = "YTD_CUMULATIVE"
        q2 = derive_standalone(h1_inputs[metric], q1, result_period="2026Q2", result_period_type="Q2_STANDALONE", formula_version="H1_MINUS_Q1_SAME_BASIS_V1")
        store.upsert(q2)
    q2_cfo = next(x for x in store.values() if x["metric_id"] == "CFO" and x["period"] == "2026Q2")
    q2_capex = next(x for x in store.values() if x["metric_id"] == "CAPEX" and x["period"] == "2026Q2")
    q2_fcf = observation(
        metric_id="FCF", metric_family="CASH_FLOW", period="2026Q2", period_type="Q2_STANDALONE",
        period_start="2026-04-01", period_end="2026-06-30", fiscal_year=2026, fiscal_quarter=2,
        value=_dec(q2_cfo["value"]) - _dec(q2_capex["value"]), unit="新台幣百萬元",
        currency="TWD", basis="Q_STANDALONE", direct_or_derived="DERIVED",
        formula_version="CFO_MINUS_CAPEX_V1", source_id=f"OFFICIAL-Q2-{qhash[:16]}",
        source_type="OFFICIAL_LOCAL_FILING", source_locator="FY2026_Q2.json#cashFlow",
        source_hash=qhash, input_observation_ids=[q2_cfo["observation_id"], q2_capex["observation_id"]],
        notes="Capex以正數現金流出呈現；FCF=CFO-Capex。",
    )
    store.upsert(q2_fcf)

    # Point-in-time working-capital amounts; NWC is explicitly a proxy.
    bs = qconfig["balanceSheet"]
    wc_periods = {
        "2025Q2": bs["priorYear"], "2026Q1": bs["q1"], "2026Q2": bs,
    }
    wc_fields = (("AR", "accountsReceivableNetMillionTwd"), ("INVENTORY", "inventoryMillionTwd"), ("AP", "accountsPayableMillionTwd"))
    for period, values in wc_periods.items():
        direct: dict[str, dict[str, Any]] = {}
        for metric, field in wc_fields:
            item = _direct_quarter(
                metric=metric, family="WORKING_CAPITAL", period=period, value=values[field],
                unit="新台幣百萬元", source_id=f"OFFICIAL-Q2-{qhash[:16]}",
                source_type="OFFICIAL_LOCAL_FILING", locator=f"FY2026_Q2.json#balanceSheet:{period}:{field}",
                source_hash=qhash, basis="QUARTER_END_BALANCE",
            )
            store.upsert(item)
            direct[metric] = item
        start, end, year, quarter = _quarter_dates(period)
        nwc = observation(
            metric_id="NWC_PROXY", metric_family="WORKING_CAPITAL", period=period,
            period_type="POINT_IN_TIME", period_start=start, period_end=end, fiscal_year=year,
            fiscal_quarter=quarter, value=_dec(direct["AR"]["value"]) + _dec(direct["INVENTORY"]["value"]) - _dec(direct["AP"]["value"]),
            unit="新台幣百萬元", currency="TWD", basis="QUARTER_END_BALANCE",
            direct_or_derived="DERIVED", formula_version="AR_PLUS_INVENTORY_MINUS_AP_V1",
            source_id=f"OFFICIAL-Q2-{qhash[:16]}", source_type="OFFICIAL_LOCAL_FILING",
            source_locator=f"FY2026_Q2.json#balanceSheet:{period}", source_hash=qhash,
            input_observation_ids=[direct[x]["observation_id"] for x in ("AR", "INVENTORY", "AP")],
            notes="NWC Proxy，不等同公司正式揭露之淨營運資金。",
        )
        store.upsert(nwc)

    days = qconfig["workingCapitalDays"]
    for index, period in enumerate(days["periods"]):
        components: dict[str, dict[str, Any]] = {}
        for metric, field in (("DSO", "accountsReceivableDays"), ("DIO", "inventoryDays"), ("DPO", "accountsPayableDays")):
            start, end, year, quarter = _quarter_dates(period)
            item = observation(
                metric_id=metric, metric_family="WORKING_CAPITAL_DAYS", period=period,
                period_type="Q%d_STANDALONE" % quarter, period_start=start, period_end=end,
                fiscal_year=year, fiscal_quarter=quarter, value=days[field][index], unit="天",
                currency=None, basis="EXISTING_GOVERNED_CCC_METHOD_V1", direct_or_derived="DIRECT",
                formula_version="DIRECT_V1", source_id=f"OFFICIAL-Q2-{qhash[:16]}",
                source_type="OFFICIAL_LOCAL_FILING", source_locator=f"FY2026_Q2.json#workingCapitalDays:{period}:{field}",
                source_hash=qhash, notes="沿用既有戰情室同口徑工作天數序列；不另建第二套方法。",
            )
            store.upsert(item)
            components[metric] = item
        start, end, year, quarter = _quarter_dates(period)
        ccc_value = _dec(components["DSO"]["value"]) + _dec(components["DIO"]["value"]) - _dec(components["DPO"]["value"])
        if ccc_value != _dec(days["cashConversionCycleDays"][index]):
            raise HistoricalKPIBaselineError(f"CCC_SOURCE_FORMULA_MISMATCH:{period}")
        store.upsert(observation(
            metric_id="CCC", metric_family="WORKING_CAPITAL_DAYS", period=period,
            period_type="Q%d_STANDALONE" % quarter, period_start=start, period_end=end,
            fiscal_year=year, fiscal_quarter=quarter, value=ccc_value, unit="天", currency=None,
            basis="EXISTING_GOVERNED_CCC_METHOD_V1", direct_or_derived="DERIVED",
            formula_version="DSO_PLUS_DIO_MINUS_DPO_V1", source_id=f"OFFICIAL-Q2-{qhash[:16]}",
            source_type="OFFICIAL_LOCAL_FILING", source_locator=f"FY2026_Q2.json#workingCapitalDays:{period}",
            source_hash=qhash, input_observation_ids=[components[x]["observation_id"] for x in ("DSO", "DIO", "DPO")],
            notes="沿用唯一既有CCC方法。",
        ))

    # Existing governed master supports P/B and TTM P/E.  P/S begins only after
    # four local quarterly revenue observations exist; no forward denominator.
    master_rows = list(master.rows)
    daily_rows = list(daily_price.rows)
    revenue_window: list[Decimal] = []
    for index, row in enumerate(master_rows):
        period = row["Quarter"]
        start, end, year, quarter = _quarter_dates(period)
        in_quarter = [item for item in daily_rows if start <= item["Date"] <= end]
        if in_quarter:
            price_row = select_quarter_end_price(in_quarter, end)
            price = price_row["Close"]
            valuation_date = price_row["Date"]
            price_source = "data/2317_daily_price.csv#Date=" + valuation_date
            component_hashes = {"master_v9": master.actual_sha256, "daily_price": daily_price.actual_sha256}
            combined_hash = sha256_bytes(canonical_json_bytes(component_hashes))
            combined_locator = f"data/2317_master_v9.csv#{period};{price_source}"
            source_id = f"AUTH-VALUATION-COMPOSITE-{combined_hash[:16]}"
            source_note = "正式日價覆蓋期間優先採季末日前最後有效交易日。"
        else:
            price = row["QuarterEndClose"]
            valuation_date = row["QuarterEndDate"]
            price_source = "data/2317_master_v9.csv#QuarterEndClose"
            component_hashes = {"master_v9": master.actual_sha256}
            combined_hash = master.actual_sha256
            combined_locator = f"data/2317_master_v9.csv#{period}"
            source_id = f"AUTH-MASTER-{master.actual_sha256[:16]}"
            source_note = "本機日價authority未覆蓋本期；沿用既有受治理季末收盤價觀察。"
        common = dict(
            metric_family="VALUATION", period=period, period_type="POINT_IN_TIME",
            period_start=start, period_end=end, fiscal_year=year, fiscal_quarter=quarter,
            unit="倍", currency=None, basis="QUARTER_END_LAST_VALID_TRADING_DAY",
            source_id=source_id, source_type="GOVERNED_PRODUCTION_AUTHORITY",
            source_locator=combined_locator, source_hash=combined_hash,
            availability_state="AVAILABLE", notes=source_note + " 不套用交易門檻。",
        )
        pb = observation(
            metric_id="PB", value=_dec(price) / _dec(row["BVPS"]), direct_or_derived="DERIVED",
            formula_version="QUARTER_END_PRICE_DIVIDED_BY_PERIOD_END_BVPS_V1",
            input_observation_ids=[f"{period}:PRICE", f"{period}:BVPS"], **common,
        )
        pb.update({"valuation_date": valuation_date, "price": price, "price_source": price_source, "component_source_hashes": component_hashes, "reported_master_pb": row["PB_QuarterEnd"]})
        store.upsert(pb)
        if row.get("EPS_TTM") and _dec(row["EPS_TTM"]) != 0:
            pe = observation(
                metric_id="PE_TTM", value=_dec(price) / _dec(row["EPS_TTM"]),
                direct_or_derived="DERIVED", formula_version="QUARTER_END_PRICE_DIVIDED_BY_TTM_EPS_V1",
                input_observation_ids=[f"{period}:QuarterEndClose", f"{period}:EPS_TTM"], **common,
            )
            pe.update({"valuation_date": valuation_date, "price": price, "price_source": price_source, "component_source_hashes": component_hashes})
            store.upsert(pe)
        revenue_window.append(_dec(row["Revenue_Q_100M"]))
        if len(revenue_window) > 4:
            revenue_window.pop(0)
        if len(revenue_window) == 4 and sum(revenue_window) != 0 and row.get("MarketCap_100M") not in {None, "", "N/A"}:
            ps_common = dict(common)
            ps_common.update({
                "source_id": f"AUTH-MASTER-{master.actual_sha256[:16]}",
                "source_locator": f"data/2317_master_v9.csv#{period}",
                "source_hash": master.actual_sha256,
                "notes": "季末市值除以四季滾動營收；不套用交易門檻。",
            })
            ps = observation(
                metric_id="PS_TTM", value=_dec(row["MarketCap_100M"]) / sum(revenue_window),
                direct_or_derived="DERIVED", formula_version="QUARTER_END_MARKET_CAP_DIVIDED_BY_TTM_REVENUE_V1",
                input_observation_ids=[f"{master_rows[j]['Quarter']}:Revenue_Q_100M" for j in range(index - 3, index + 1)] + [f"{period}:MarketCap_100M"], **ps_common,
            )
            ps.update({"valuation_date": row["QuarterEndDate"], "price": row["QuarterEndClose"], "price_source": "data/2317_master_v9.csv#QuarterEndClose"})
            store.upsert(ps)

    observations = store.values()
    family_counts: dict[str, int] = {}
    for item in observations:
        family_counts[item["metric_id"]] = family_counts.get(item["metric_id"], 0) + 1
    return {
        "schema_version": "P1008_HISTORICAL_KPI_BASELINE_V1",
        "generated_from_local_sources_only": True,
        "observations": observations,
        "observation_count": len(observations),
        "metric_counts": family_counts,
        "source_hashes": {
            "cash_flow_authority": cash.actual_sha256,
            "master_v9": master.actual_sha256,
            "daily_price": daily_price.actual_sha256,
            "q2_official_filing": qhash,
            "q2_config": sha256_file(qconfig_path),
        },
        "unavailable": {
            "period_end_share_count": "LOCAL_SOURCE_GAP",
            "weighted_average_share_count": "LOCAL_SOURCE_GAP",
            "fcf_per_share": "FCF_PER_SHARE_CONTRACT_REQUIRED",
            "peer_history": "NO_VERIFIED_HISTORICAL_SNAPSHOTS",
            "older_cash_flow": "LOCAL_SOURCE_GAP",
            "older_working_capital": "LOCAL_SOURCE_GAP",
        },
        "raw_authority_modified": False,
        "actionable": False,
    }


def observations_for(baseline: Mapping[str, Any], metric: str, *, basis: str | None = None) -> list[dict[str, Any]]:
    rows = [dict(item) for item in baseline["observations"] if item["metric_id"] == metric]
    if basis is not None:
        rows = [item for item in rows if item["basis"] == basis]
    return sorted(rows, key=lambda item: item["period_end"])
