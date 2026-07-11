"""Minimal deterministic semantic-version handling."""

from __future__ import annotations

import re
from dataclasses import dataclass


class VersionError(ValueError):
    """Raised when a capability version is not strict semantic versioning."""


@dataclass(frozen=True, order=True)
class SemanticVersion:
    major: int
    minor: int
    patch: int

    PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")

    @classmethod
    def parse(cls, value: str) -> "SemanticVersion":
        match = cls.PATTERN.fullmatch(value)
        if not match:
            raise VersionError(f"Invalid capability version: {value}")
        return cls(*(int(item) for item in match.groups()))

    def compatible_with_framework(self, framework_major: int) -> bool:
        return self.major in (0, framework_major)
