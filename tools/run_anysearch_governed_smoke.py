"""Run the one fixed Owner-authorized AnySearch staging smoke request."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_SRC = ROOT / "modules" / "p1008_research_plugin" / "src"
if str(MODULE_SRC) not in sys.path:
    sys.path.insert(0, str(MODULE_SRC))

from p1008_research_plugin.adapters.anysearch_runtime import (  # noqa: E402
    execute_governed_search,
    owner_authorized_smoke_request,
    write_staging_output,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="P1008 governed AnySearch one-search smoke")
    parser.add_argument("--owner-authorized-one-search", action="store_true")
    args = parser.parse_args()
    if not args.owner_authorized_one_search:
        parser.error("--owner-authorized-one-search is required")
    envelope = execute_governed_search(owner_authorized_smoke_request(), allow_anonymous=True)
    path = write_staging_output(envelope, ROOT / "runtime" / "anysearch_staging")
    print(json.dumps({"status": envelope["status"], "candidate_count": len(envelope["candidates"]), "staging_path": str(path), "actionable": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
