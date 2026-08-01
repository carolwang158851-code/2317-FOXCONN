"""Validate and dispatch a request to the only enabled capability."""

from __future__ import annotations

from typing import Any, Mapping

from ..runtime.capability_registry import CapabilityRegistry
from ..runtime.context_builder import ContextBuilder
from ..validation.boundary_validation import BoundaryValidator


class RequestDispatcher:
    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry
        self.context_builder = ContextBuilder()
        self.boundary = BoundaryValidator()

    def dispatch(self, request: Mapping[str, Any]) -> dict[str, Any]:
        self.boundary.validate_request(request)
        context = self.context_builder.build(request)
        self.registry.require_enabled(context["capability"])
        return context
