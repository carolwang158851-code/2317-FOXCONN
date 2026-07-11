"""Smallest governed Phase 2A orchestration path."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..runtime.runtime_config import RuntimeConfig
from ..runtime.runtime_manager import RuntimeManager
from .lifecycle import RequestLifecycle
from .request_dispatcher import RequestDispatcher


class ResearchOrchestrator:
    def __init__(self, package_root: Path, config: RuntimeConfig | None = None) -> None:
        self.manager = RuntimeManager(package_root, config)
        self.dispatcher = RequestDispatcher(self.manager.capabilities)

    def run(self, request: Mapping[str, Any]) -> dict[str, Any]:
        lifecycle = RequestLifecycle()
        lifecycle.advance("RECEIVED")
        context = self.dispatcher.dispatch(request)
        lifecycle.advance("CONTEXT_BUILT")
        result = self.manager.execute(context)
        lifecycle.advance("MOCK_EXECUTED")
        lifecycle.advance("OUTPUT_VALIDATED")
        lifecycle.advance("ARTIFACT_BUILT")
        lifecycle.advance("COMPLETED")
        return {**result, "request_id": context["context_id"], "lifecycle": lifecycle.snapshot()}
