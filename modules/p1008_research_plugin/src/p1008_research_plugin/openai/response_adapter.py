"""Adapt provider mappings without filling missing research content."""

from __future__ import annotations

import copy
from typing import Any, Mapping


class ResponseAdapterError(RuntimeError):
    """Raised when provider output is not a typed mapping candidate."""


class ResponseAdapter:
    def adapt(self, value: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ResponseAdapterError("Provider response must be a mapping")
        return copy.deepcopy(dict(value))
