"""Anti-trading and no-state-change boundary gate."""

from __future__ import annotations

from typing import Any, Mapping

from ..runtime.runtime_guard import RuntimeGuard


class BoundaryValidator:
    def validate_request(self, request: Mapping[str, Any]) -> None:
        RuntimeGuard.assert_safe_request(request)

    def validate_output(self, output: Mapping[str, Any]) -> None:
        RuntimeGuard.assert_safe_output(output)
