"""Empty tool registry for a phase that authorizes no tools."""

from __future__ import annotations

from typing import Any


class ToolRegistry:
    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": [],
            "deferred": [
                "deep_research",
                "financial",
                "macro",
                "foreign_flow",
                "news",
                "warroom",
            ],
            "actionable": False,
        }

    def register(self, _tool: object) -> None:
        raise RuntimeError("Phase 2A tool registration is forbidden")
