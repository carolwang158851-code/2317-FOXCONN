"""Canonical typed research output and deterministic hashing."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True)
class TypedResearchArtifact:
    payload: dict[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TypedResearchArtifact":
        return cls(copy.deepcopy(dict(value)))

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.payload)

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.payload)

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest().upper()
