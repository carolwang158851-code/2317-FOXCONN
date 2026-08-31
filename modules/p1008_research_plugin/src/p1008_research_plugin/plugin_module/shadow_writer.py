"""Constrained writer for uncommitted manual Shadow report candidates."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .contracts import FinancialBriefReport, ShadowFailureManifest, canonical_json_ready
from ..phaseb1_common import PhaseB1BoundaryError, atomic_write


class ShadowWriteError(RuntimeError):
    """Raised when a candidate attempts to cross the Shadow artifact boundary."""


class ShadowWriter:
    def __init__(self, package_root: Path) -> None:
        self.package_root = package_root.resolve()
        self.shadow_root = (self.package_root / "runtime" / "research_plugin").resolve()

    def _assert_shadow_path(self, path: Path) -> None:
        if not path.resolve().is_relative_to(self.shadow_root):
            raise ShadowWriteError("Shadow artifact path escaped its runtime root")

    @staticmethod
    def _serialize(report: FinancialBriefReport) -> tuple[dict[str, Any], bytes]:
        payload = canonical_json_ready(report)
        raw = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        return payload, raw

    def _write_atomic(self, path: Path, raw: bytes, *, replace: bool) -> None:
        self._assert_shadow_path(path)
        try:
            atomic_write(
                path,
                raw,
                overwrite=replace,
                capability="RESEARCH_PLUGIN_RUNTIME",
            )
        except PhaseB1BoundaryError as exc:
            raise ShadowWriteError(f"Shadow artifact write denied: {exc}") from exc

    def write(self, report: FinancialBriefReport) -> dict[str, Any]:
        if report.actionable or not report.manual_shadow:
            raise ShadowWriteError("Only non-actionable manual Shadow output may be written")
        if not re.fullmatch(r"[A-Z0-9-]{8,96}", report.run_id):
            raise ShadowWriteError("Unsafe Shadow run identifier")

        _payload, raw = self._serialize(report)
        run_path = self.shadow_root / "runs" / f"{report.run_id}.json"
        latest_path = self.shadow_root / "latest_report_candidate.json"
        self._write_atomic(run_path, raw, replace=False)
        self._write_atomic(latest_path, raw, replace=True)
        return {
            "latest": latest_path.relative_to(self.package_root).as_posix(),
            "run": run_path.relative_to(self.package_root).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest().upper(),
            "persisted": True,
            "formal_state_changed": False,
            "actionable": False,
        }

    def write_failure(self, audit: ShadowFailureManifest) -> dict[str, Any]:
        """Persist a non-candidate audit without changing the periodic-reader target."""

        if audit.actionable or audit.candidate_written:
            raise ShadowWriteError("Failure audit crossed its observation boundary")
        if not re.fullmatch(r"[A-Z0-9-]{8,96}", audit.run_id):
            raise ShadowWriteError("Unsafe Shadow run identifier")
        payload = canonical_json_ready(audit)
        raw = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        failure_path = self.shadow_root / "failures" / f"{audit.run_id}.json"
        self._write_atomic(failure_path, raw, replace=False)
        return {
            "failure": failure_path.relative_to(self.package_root).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest().upper(),
            "persisted": True,
            "candidate_written": False,
            "formal_state_changed": False,
            "actionable": False,
        }
