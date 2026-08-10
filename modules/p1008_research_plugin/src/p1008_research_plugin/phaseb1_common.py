"""Shared deterministic and filesystem-safe Phase B1 helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


FORMAL_WRITE_ROOTS = ("data", "rules")


class PhaseB1BoundaryError(RuntimeError):
    """Raised before a Phase B1 operation can cross its runtime-only boundary."""


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def ensure_runtime_output(package_root: Path, output_root: Path) -> Path:
    package_root = package_root.resolve()
    allowed = (package_root / "runtime" / "report_production").resolve()
    resolved = output_root.resolve()
    if not resolved.is_relative_to(allowed):
        raise PhaseB1BoundaryError(
            "Phase B1 output must stay under runtime/report_production"
        )
    return resolved


def atomic_write(path: Path, data: bytes, *, overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        raise PhaseB1BoundaryError(f"Refusing to overwrite Phase B1 artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, value: Any, *, overwrite: bool = False) -> str:
    data = canonical_json_bytes(value)
    atomic_write(path, data, overwrite=overwrite)
    return sha256_bytes(data)


def protected_state_hashes(package_root: Path) -> dict[str, str]:
    """Hash formal authority and rule state without inspecting credentials."""

    relative_paths = [
        "data/CSV_AUTHORITY_MANIFEST.json",
        "data/2317_master_v9.csv",
        "data/2317_daily_price.csv",
        "data/2317_daily_market_activity.csv",
        "data/2317_cash_flow_authority.csv",
        "data/macro_snapshot.csv",
        "data/macro_event_observations.csv",
        "data/fx_trend_observations.csv",
        "rules/RULE_STATUS_MANIFEST.json",
    ]
    result = {
        relative: sha256_file(package_root / relative)
        for relative in relative_paths
    }
    sqlite_path = (
        Path.home() / "AppData" / "Local" / "P1008" / "data" / "warroom.sqlite3"
    )
    result["runtime_sqlite"] = (
        sha256_file(sqlite_path) if sqlite_path.is_file() else "NOT_PRESENT"
    )
    result["HOLD_MIDR_MRD_STATE"] = result["rules/RULE_STATUS_MANIFEST.json"]
    return result
