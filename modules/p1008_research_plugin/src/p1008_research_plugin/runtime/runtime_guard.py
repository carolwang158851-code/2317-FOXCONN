"""Deterministic anti-authority and prompt-injection guard."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping


class RuntimeBoundaryError(RuntimeError):
    """Raised when input or output crosses a Phase 2A boundary."""


class RuntimeGuard:
    FORBIDDEN_COMMANDS = (
        "BUY",
        "SELL",
        "LONG",
        "SHORT",
        "TARGET PRICE",
        "ENABLE",
        "DISABLE",
        "APPROVE",
        "COMMIT",
        "UPDATE",
        "WRITE",
        "DELETE",
    )
    INJECTION_PATTERNS = (
        r"ignore\s+(all\s+)?previous",
        r"bypass\s+governance",
        r"reveal\s+(the\s+)?system\s+prompt",
        r"developer\s+message",
        r"change\s+your\s+instructions",
    )

    @classmethod
    def _contains_command(cls, text: str) -> bool:
        upper = text.upper()
        for command in cls.FORBIDDEN_COMMANDS:
            pattern = r"\b" + re.escape(command).replace(r"\ ", r"\s+") + r"\b"
            if re.search(pattern, upper):
                return True
        return False

    @classmethod
    def assert_safe_text(cls, text: str, surface: str) -> None:
        if cls._contains_command(text):
            raise RuntimeBoundaryError(f"{surface} contains a forbidden command")
        for pattern in cls.INJECTION_PATTERNS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                raise RuntimeBoundaryError(f"{surface} contains prompt injection")

    @classmethod
    def assert_safe_request(cls, request: Mapping[str, Any]) -> None:
        question = request.get("question")
        if not isinstance(question, str):
            raise RuntimeBoundaryError("Request question must be text")
        cls.assert_safe_text(question, "request")

    @classmethod
    def assert_safe_output(cls, output: Mapping[str, Any]) -> None:
        if output.get("actionable") is not False:
            raise RuntimeBoundaryError("Output actionable must be false")
        serialized = json.dumps(output, ensure_ascii=False, sort_keys=True)
        cls.assert_safe_text(serialized, "output")
