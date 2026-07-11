"""In-memory health snapshot; not a Status API."""

from __future__ import annotations

from typing import Any

from .runtime_config import RuntimeConfig


class RuntimeHealth:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config

    def snapshot(self, mock_calls: int) -> dict[str, Any]:
        return {
            "phase": "PHASE_2A",
            "status": "MOCK_READY_PRODUCTION_DISABLED",
            "provider": self.config.provider_id,
            "openai_enabled": False,
            "network_enabled": False,
            "mock_calls": mock_calls,
            "runtime_state_changed": False,
            "actionable": False,
        }
