"""Typed output schema gate."""

from __future__ import annotations

from typing import Any, Mapping

from ..runtime.runtime_validator import RuntimeValidator


class SchemaValidator:
    def __init__(self) -> None:
        self.validator = RuntimeValidator()

    def validate(self, output: Mapping[str, Any]) -> dict[str, Any]:
        return self.validator.validate(output)
