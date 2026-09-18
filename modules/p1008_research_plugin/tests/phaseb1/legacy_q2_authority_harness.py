"""Test-only frozen authority overlay for the legacy FY2026 Q2 report fixture."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


LEGACY_PRICE_SHA256 = "1C32081288731725CBA000C1CCC5144A24DD2A6F9A15A2964F930D8953839C6D"
LEGACY_MANIFEST_SHA256 = "C6FF94A1FB2C9C877D7620184BDDD9A6270355ED833318638C3D87EB634A5398"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


@contextmanager
def legacy_q2_authority_overlay(package_root: Path, authority_root: Path):
    """Expose the frozen pre-event price state at the test I/O boundary only."""
    package_root = package_root.resolve()
    authority_root = authority_root.resolve()
    canonical_manifest = (package_root / "data/CSV_AUTHORITY_MANIFEST.json").resolve()
    canonical_price = (package_root / "data/2317_daily_price.csv").resolve()
    frozen_manifest = (authority_root / "data/CSV_AUTHORITY_MANIFEST.json").read_bytes()
    frozen_price = (authority_root / "data/2317_daily_price.csv").read_bytes()
    if _sha256(frozen_manifest) != LEGACY_MANIFEST_SHA256:
        raise AssertionError("frozen legacy authority manifest SHA mismatch")
    if _sha256(frozen_price) != LEGACY_PRICE_SHA256:
        raise AssertionError("frozen legacy daily-price SHA mismatch")

    current_manifest = json.loads(canonical_manifest.read_text(encoding="utf-8-sig"))
    historical_manifest = json.loads(frozen_manifest.decode("utf-8-sig"))
    historical_price_entry = next(
        entry
        for entry in historical_manifest["authoritativeFiles"]
        if entry["path"] == "data/2317_daily_price.csv"
    )
    merged_manifest = json.loads(json.dumps(current_manifest))
    for section in ("authoritativeFiles", "nonAuthoritativeFiles"):
        for index, entry in enumerate(merged_manifest.get(section, [])):
            if entry.get("path") == "data/2317_daily_price.csv":
                merged_manifest[section][index] = historical_price_entry
    merged_text = json.dumps(merged_manifest, ensure_ascii=False, indent=2) + "\n"

    original_read_bytes = Path.read_bytes
    original_read_text = Path.read_text

    def read_bytes(path: Path) -> bytes:
        if path.resolve() == canonical_price:
            return frozen_price
        return original_read_bytes(path)

    def read_text(path: Path, *args, **kwargs) -> str:
        if path.resolve() == canonical_manifest:
            return merged_text
        return original_read_text(path, *args, **kwargs)

    with patch.object(Path, "read_bytes", read_bytes), patch.object(Path, "read_text", read_text):
        yield
