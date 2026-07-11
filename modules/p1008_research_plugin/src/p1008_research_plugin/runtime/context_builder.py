"""Normalize a minimal research request without enriching missing facts."""

from __future__ import annotations

import hashlib
import json
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
