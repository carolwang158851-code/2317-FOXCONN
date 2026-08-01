"""Build immutable artifact envelopes without writing runtime state."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .typed_output import TypedResearchArtifact


class ArtifactBoundaryError(RuntimeError):
    """Raised when an artifact write targets the governed package."""


@dataclass(frozen=True)
class ArtifactEnvelope:
    artifact_id: str
    logical_locator: str
    sha256: str
    payload: dict[str, Any]
    actionable: bool = False

    def metadata(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "logical_locator": self.logical_locator,
            "sha256": self.sha256,
            "persisted": False,
            "actionable": False,
        }


class ArtifactWriter:
    def __init__(self, package_root: Path) -> None:
        self.package_root = package_root.resolve()

    def build(self, artifact: TypedResearchArtifact) -> ArtifactEnvelope:
        digest = artifact.sha256()
        artifact_id = f"P1008-P2A-{digest[:24]}"
        return ArtifactEnvelope(
            artifact_id=artifact_id,
            logical_locator=f"runtime/research_plugin/artifacts/{artifact_id}.json",
            sha256=digest,
            payload=artifact.to_dict(),
        )

    def write_test_only(self, envelope: ArtifactEnvelope, sandbox_root: Path) -> Path:
        root = sandbox_root.resolve()
        if root == self.package_root or root.is_relative_to(self.package_root):
            raise ArtifactBoundaryError("Test artifact root cannot be inside the package")
        target = root / envelope.logical_locator
        target.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(
            envelope.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        target.write_text(text + "\n", encoding="utf-8")
        return target
