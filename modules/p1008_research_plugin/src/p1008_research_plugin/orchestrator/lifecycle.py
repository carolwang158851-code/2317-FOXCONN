"""Per-request in-memory lifecycle; no ledger or projection state."""

from __future__ import annotations


class LifecycleError(RuntimeError):
    """Raised when pipeline stages are advanced out of order."""


class RequestLifecycle:
    ORDER = (
        "RECEIVED",
        "CONTEXT_BUILT",
        "MOCK_EXECUTED",
        "OUTPUT_VALIDATED",
        "ARTIFACT_BUILT",
        "COMPLETED",
    )

    def __init__(self) -> None:
        self._stages: list[str] = []

    def advance(self, stage: str) -> None:
        expected = self.ORDER[len(self._stages)] if len(self._stages) < len(self.ORDER) else None
        if stage != expected:
            raise LifecycleError(f"Expected lifecycle stage {expected}, received {stage}")
        self._stages.append(stage)

    def snapshot(self) -> list[str]:
        return list(self._stages)
