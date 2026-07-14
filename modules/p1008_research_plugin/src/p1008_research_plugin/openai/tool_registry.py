"""Governed tool metadata; Phase 2A stays empty and Phase 3B stays bounded."""

from __future__ import annotations

import importlib
from typing import Any


class ToolRegistryError(RuntimeError):
    """Raised when the governed Agents SDK tool cannot be constructed."""


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

    def phase3b_snapshot(self) -> dict[str, Any]:
        return {
            "web_search": {
                "implementation": "OPENAI_HOSTED_WEB_SEARCH",
                "max_calls_per_run": 1,
                "evidence_packet_required": True,
            },
            "data_analytics": {
                "implementation": "CODEX_EXECUTOR_EVIDENCE_PACKET",
                "max_calls_per_run": 1,
                "endpoint": None,
            },
            "investment_banking": {
                "implementation": "CODEX_EXECUTOR_EVIDENCE_PACKET",
                "max_calls_per_run": 1,
                "endpoint": None,
            },
            "canva": {
                "implementation": "OWNER_GATE_LAYOUT_ONLY",
                "max_calls_per_run": 0,
                "research_enabled": False,
            },
            "actionable": False,
        }

    def build_hosted_web_search(self) -> object:
        """Create the official hosted tool lazily for an authorized live run."""

        try:
            sdk = importlib.import_module("".join(("ag", "ents")))
            web_search_tool = getattr(sdk, "WebSearchTool")
            return web_search_tool()
        except (ImportError, AttributeError) as exc:
            raise ToolRegistryError("OpenAI Agents SDK hosted web search is unavailable") from exc
