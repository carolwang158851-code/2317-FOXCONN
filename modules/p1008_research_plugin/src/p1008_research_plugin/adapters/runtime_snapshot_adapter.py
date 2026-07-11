"""Read-only access to explicitly approved P1008 runtime JSON snapshots."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


class RuntimeSnapshotError(RuntimeError):
    """Raised when a runtime snapshot path is unsafe or malformed."""


@dataclass(frozen=True)
class SnapshotResult:
    relative_path: str
    exists: bool
    sha256: str | None
    data: Mapping[str, Any] | None


class RuntimeSnapshotAdapter:
    APPROVED_PATHS = frozenset(
        {
            "runtime/p1008_app_state.json",
            "runtime/warroom_news_scan_snapshot.json",
            "runtime/warroom_report_manifest.json",
            "runtime/warroom_event_review_state.json",
        }
    )

    def __init__(self, package_root: Path | str) -> None:
        self.package_root = Path(package_root).resolve()

    def _safe_path(self, relative_path: str) -> Path:
        if relative_path not in self.APPROVED_PATHS:
            raise RuntimeSnapshotError(f"Runtime snapshot is not allowlisted: {relative_path}")
        raw = Path(relative_path)
        if raw.is_absolute() or ".." in raw.parts:
            raise RuntimeSnapshotError(f"Unsafe runtime path: {relative_path}")
        resolved = (self.package_root / raw).resolve()
        if not resolved.is_relative_to(self.package_root):
            raise RuntimeSnapshotError(f"Runtime path escapes package root: {relative_path}")
        return resolved

    def read_snapshot(self, relative_path: str) -> SnapshotResult:
        path = self._safe_path(relative_path)
        if not path.is_file():
            return SnapshotResult(relative_path, False, None, None)
        data = path.read_bytes()
        try:
            document = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeSnapshotError(f"Malformed runtime snapshot: {relative_path}") from exc
        if not isinstance(document, dict):
            raise RuntimeSnapshotError(f"Runtime snapshot must be an object: {relative_path}")
        return SnapshotResult(
            relative_path=relative_path,
            exists=True,
            sha256=hashlib.sha256(data).hexdigest().upper(),
            data=MappingProxyType(document),
        )

    def read_all(self) -> tuple[SnapshotResult, ...]:
        return tuple(self.read_snapshot(path) for path in sorted(self.APPROVED_PATHS))
