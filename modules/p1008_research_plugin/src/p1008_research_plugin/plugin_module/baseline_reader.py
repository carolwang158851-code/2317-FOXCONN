"""Read the existing war-room authority into one hashed, read-only baseline."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date
from io import StringIO
from pathlib import Path
from typing import Any, Mapping

from .contracts import BaselineSnapshot


class BaselineReadError(RuntimeError):
    """Raised when the formal baseline cannot be read without guessing."""


class BaselineReader:
    REQUIRED_FILES = (
        "data/2317_master_v9.csv",
        "data/2317_daily_price.csv",
        "data/macro_snapshot.csv",
        "data/fx_trend_observations.csv",
    )

    def __init__(self, package_root: Path) -> None:
        self.package_root = package_root.resolve()

    @staticmethod
    def _canonical_hash(as_of_date: date, source_files: list[str], data: Mapping[str, Any]) -> str:
        material = json.dumps(
            {
                "as_of_date": as_of_date.isoformat(),
                "source_files": source_files,
                "data": data,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(material).hexdigest().upper()

    @classmethod
    def from_mapping(
        cls,
        as_of_date: date | str,
        data: Mapping[str, Any],
        source_files: list[str],
    ) -> BaselineSnapshot:
        normalized_date = date.fromisoformat(as_of_date) if isinstance(as_of_date, str) else as_of_date
        normalized_data = json.loads(json.dumps(data, ensure_ascii=False, sort_keys=True))
        return BaselineSnapshot(
            as_of_date=normalized_date,
            source_files=source_files,
            data=normalized_data,
            baseline_hash=cls._canonical_hash(normalized_date, source_files, normalized_data),
        )

    @staticmethod
    def _read_csv(path: Path) -> list[dict[str, str]]:
        if not path.is_file():
            raise BaselineReadError(f"Missing baseline source: {path.name}")
        text = path.read_text(encoding="utf-8-sig", errors="strict")
        content = "\n".join(
            line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
        )
        reader = csv.DictReader(StringIO(content))
        if not reader.fieldnames:
            raise BaselineReadError(f"Missing CSV schema: {path.name}")
        rows = [
            {str(key): str(value or "").strip() for key, value in row.items()}
            for row in reader
        ]
        if not rows:
            raise BaselineReadError(f"Missing CSV rows: {path.name}")
        return rows

    @staticmethod
    def _latest_on_or_before(
        rows: list[dict[str, str]], key: str, as_of_date: date
    ) -> dict[str, str]:
        eligible = []
        for row in rows:
            value = row.get(key, "")[:10]
            try:
                row_date = date.fromisoformat(value)
            except ValueError:
                continue
            if row_date <= as_of_date:
                eligible.append((row_date, row))
        if not eligible:
            raise BaselineReadError(f"No baseline row on or before {as_of_date} for {key}")
        return max(eligible, key=lambda item: item[0])[1]

    def read(self, as_of_date: date | str) -> BaselineSnapshot:
        normalized_date = date.fromisoformat(as_of_date) if isinstance(as_of_date, str) else as_of_date
        paths = {relative: self.package_root / relative for relative in self.REQUIRED_FILES}
        rows = {relative: self._read_csv(path) for relative, path in paths.items()}

        master = self._latest_on_or_before(
            rows["data/2317_master_v9.csv"], "QuarterEndDate", normalized_date
        )
        daily = self._latest_on_or_before(
            rows["data/2317_daily_price.csv"], "Date", normalized_date
        )
        macro = self._latest_on_or_before(
            rows["data/macro_snapshot.csv"], "Date", normalized_date
        )
        fx = self._latest_on_or_before(
            rows["data/fx_trend_observations.csv"], "Date", normalized_date
        )

        data = {
            "revenue": {
                "quarter": master.get("Quarter", ""),
                "revenue_q_100m": master.get("Revenue_Q_100M", ""),
                "hon_hai_revenue_yoy": macro.get("Hon_Hai_Rev_YoY", ""),
            },
            "EPS": {
                "eps_q": master.get("EPS_Q", ""),
                "eps_ttm": master.get("EPS_TTM", ""),
                "eps_yoy_pct": master.get("EPS_YoY_Pct", ""),
            },
            "margins": {
                "gross_margin_pct": master.get("GrossMarginPct", ""),
                "operating_margin_pct": master.get("OperatingMarginPct", ""),
            },
            "valuation": {
                "close": daily.get("Close", ""),
                "bvps": daily.get("BVPS_ref", ""),
                "pb": daily.get("PB_daily", ""),
                "pb_zone": master.get("PB_Zone", ""),
            },
            "fx_impact": {
                "twd_usd": macro.get("TWD_USD", ""),
                "dxy": macro.get("DXY", ""),
                "fx_trend": fx.get("FxTrend", ""),
                "fx_pressure_level": fx.get("FxPressureLevel", ""),
                "eps_impact_estimate": fx.get("EPSImpactEstimateZh", ""),
            },
            "baseline_dates": {
                "master": master.get("QuarterEndDate", ""),
                "daily": daily.get("Date", ""),
                "macro": macro.get("Date", ""),
                "fx": fx.get("Date", ""),
            },
        }
        return self.from_mapping(normalized_date, data, list(self.REQUIRED_FILES))
