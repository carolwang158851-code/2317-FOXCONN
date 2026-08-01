"""Replaceable provider interface and deterministic Phase 2A mock."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol

from ..runtime.prompt_builder import PromptBundle


class OpenAIClientInterface(Protocol):
    provider_id: str

    def generate(
        self,
        capability_id: str,
        model_id: str,
        context: Mapping[str, Any],
        prompt: PromptBundle,
    ) -> Mapping[str, Any]: ...


class MockOpenAIClient:
    """Local mock proving the interface without an API request or SDK."""

    provider_id = "phase2a-mock"

    def __init__(self, echo_handler: Callable[[Mapping[str, Any]], dict[str, Any]]) -> None:
        self._echo_handler = echo_handler
        self.mock_calls = 0

    def generate(
        self,
        capability_id: str,
        model_id: str,
        context: Mapping[str, Any],
        prompt: PromptBundle,
    ) -> Mapping[str, Any]:
        if capability_id != "echo_research" or model_id != "phase2a-mock":
            raise RuntimeError("Mock client received an unauthorized route")
        if not prompt.as_messages():
            raise RuntimeError("Prompt bundle is empty")
        self.mock_calls += 1
        return self._echo_handler(context)
