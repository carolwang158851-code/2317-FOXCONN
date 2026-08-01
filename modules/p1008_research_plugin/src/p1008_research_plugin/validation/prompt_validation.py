"""Verify role separation and required governance instructions."""

from __future__ import annotations

from typing import Any, Mapping

from ..runtime.prompt_builder import PromptBundle


class PromptValidationError(RuntimeError):
    """Raised when a prompt drops a required governance principle."""


class PromptValidator:
    REQUIRED_SYSTEM_LINES = (
        "You are NOT the authority.",
        "You are NOT the decision maker.",
        "Unknown remains unknown.",
        "Always produce typed output.",
        "Actionable is always false.",
    )

    def validate(self, bundle: PromptBundle, context: Mapping[str, Any]) -> None:
        for line in self.REQUIRED_SYSTEM_LINES:
            if line not in bundle.system:
                raise PromptValidationError(f"Missing system rule: {line}")
        if str(context["question"]) in bundle.system:
            raise PromptValidationError("User question leaked into system instructions")
        messages = bundle.as_messages()
        if [message["role"] for message in messages] != [
            "system",
            "system",
            "system",
            "user",
        ]:
            raise PromptValidationError("Prompt roles are not isolated")
