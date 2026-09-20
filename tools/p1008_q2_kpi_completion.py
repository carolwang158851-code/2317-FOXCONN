"""Quarantined one-time FY2026 Q2 promotion utility.

The governed Q2 authority already exists and now uses field-level availability.
Re-running the historical promotion algorithm would attempt to recreate
superseded values, so every public entry point fails closed without writing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TOOL_STATUS = "OBSOLETE_LEGACY_MAINTENANCE_ONLY"
QUARANTINE_REASON = "SUPERSEDED_BY_CURRENT_QUARTERLY_AUTHORITY_INTERFACE"


class ObsoleteQ2CompletionError(RuntimeError):
    """Raised when the quarantined one-time promotion tool is invoked."""


def disposition() -> dict[str, Any]:
    return {
        "status": TOOL_STATUS,
        "reason": QUARANTINE_REASON,
        "authorityMutation": False,
        "actionable": False,
    }


def _raise_quarantined() -> None:
    raise ObsoleteQ2CompletionError(f"{TOOL_STATUS}:{QUARANTINE_REASON}")


def build_candidate(package_root: Path = PACKAGE_ROOT) -> dict[str, Any]:
    del package_root
    _raise_quarantined()


def promote(package_root: Path = PACKAGE_ROOT) -> dict[str, Any]:
    del package_root
    _raise_quarantined()


def write_outputs(candidate: dict[str, Any], package_root: Path = PACKAGE_ROOT) -> None:
    del candidate, package_root
    _raise_quarantined()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, default=PACKAGE_ROOT)
    parser.parse_args()
    print(json.dumps(disposition(), ensure_ascii=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
