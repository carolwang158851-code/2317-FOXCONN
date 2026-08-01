"""Normalize a minimal research request without enriching missing facts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any, Mapping

from .runtime_guard import RuntimeBoundaryError, RuntimeGuard


class ContextBuilder:
    ALLOWED_KEYS = frozenset({"symbol", "question", "capability"})

    def build(self, request: Mapping[str, Any]) -> dict[str, Any]:
        extra = sorted(set(request) - self.ALLOWED_KEYS)
        if extra:
            raise RuntimeBoundaryError(f"Unknown request fields: {extra}")
        RuntimeGuard.assert_safe_request(request)
        symbol = str(request.get("symbol", "")).strip().upper()
        if symbol == "2317":
            symbol = "2317.TW"
        if symbol != "2317.TW":
            raise RuntimeBoundaryError("Phase 2A accepts symbol 2317 only")
        question = str(request["question"]).strip()
        if not question or len(question) > 500:
            raise RuntimeBoundaryError("Question length is outside Phase 2A limits")
        capability = str(request.get("capability", "echo_research")).strip().lower()
        normalized = {
            "capability": capability,
            "question": question,
            "symbol": symbol,
        }
        material = json.dumps(
            normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        return {
            **normalized,
            "context_id": hashlib.sha256(material).hexdigest().upper()[:24],
            "facts": [],
            "missing_evidence_preserved": True,
            "actionable": False,
        }

    def build_phase3b(
        self,
        *,
        run_type: str,
        as_of_date: str,
        baseline_hash: str,
        evidence_ids: list[str],
    ) -> dict[str, Any]:
        allowed_run_types = {
            "DAILY",
            "MONTHLY_REVENUE",
            "QUARTERLY_EARNINGS",
            "MAJOR_EVENT",
        }
        normalized_run_type = str(run_type).strip().upper()
        if normalized_run_type not in allowed_run_types:
            raise RuntimeBoundaryError("Unknown Phase 3B run type")
        try:
            normalized_date = date.fromisoformat(str(as_of_date)).isoformat()
        except ValueError as exc:
            raise RuntimeBoundaryError("Invalid Phase 3B as_of_date") from exc
        normalized_hash = str(baseline_hash).strip().upper()
        if not re.fullmatch(r"[A-F0-9]{64}", normalized_hash):
            raise RuntimeBoundaryError("Invalid Phase 3B baseline hash")
        normalized_ids = sorted({str(item).strip() for item in evidence_ids if str(item).strip()})
        material = json.dumps(
            {
                "run_type": normalized_run_type,
                "as_of_date": normalized_date,
                "baseline_hash": normalized_hash,
                "evidence_ids": normalized_ids,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return {
            "context_id": hashlib.sha256(material).hexdigest().upper()[:24],
            "run_type": normalized_run_type,
            "as_of_date": normalized_date,
            "baseline_hash": normalized_hash,
            "evidence_ids": normalized_ids,
            "manual_shadow": True,
            "actionable": False,
        }
