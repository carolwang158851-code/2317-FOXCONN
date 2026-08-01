"""Build role-separated prompts from frozen local prompt files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class PromptBundle:
    system: str
    runtime_rules: str
    capability: str
    user: str

    def as_messages(self) -> tuple[dict[str, str], ...]:
        return (
            {"role": "system", "content": self.system},
            {"role": "system", "content": self.runtime_rules},
            {"role": "system", "content": self.capability},
            {"role": "user", "content": self.user},
        )


class PromptBuilder:
    def __init__(self, prompt_root: Path | None = None) -> None:
        self.prompt_root = prompt_root or Path(__file__).resolve().parents[1] / "prompts"

    def _read(self, name: str) -> str:
        path = self.prompt_root / name
        return path.read_text(encoding="utf-8").strip()

    def build(self, context: Mapping[str, Any]) -> PromptBundle:
        user_payload = {
            "capability": context["capability"],
            "context_id": context["context_id"],
            "question": context["question"],
            "symbol": context["symbol"],
        }
        return PromptBundle(
            system=self._read("system_prompt.md"),
            runtime_rules=self._read("runtime_rules.md"),
            capability=self._read("capability_prompt.md"),
            user=json.dumps(user_payload, ensure_ascii=False, sort_keys=True),
        )
