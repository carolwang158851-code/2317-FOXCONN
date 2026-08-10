"""Run one Owner-authorized AnySearch request from a trusted issuance index."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_SRC = ROOT / "modules" / "p1008_research_plugin" / "src"
if str(MODULE_SRC) not in sys.path:
    sys.path.insert(0, str(MODULE_SRC))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import warroom_periodic_report_v1 as periodic_report  # noqa: E402
from p1008_research_plugin.adapters.anysearch_runtime import (  # noqa: E402
    execute_governed_search,
    write_staging_output,
)
from p1008_research_plugin.adapters.research_skill_governance_adapter import (  # noqa: E402
    build_skill_request,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="P1008 governed AnySearch one-search smoke")
    parser.add_argument("--owner-authorized-one-search", action="store_true")
    parser.add_argument("--issuance-receipt-id", required=True)
    parser.add_argument("--report-key", required=True)
    parser.add_argument("--revision", required=True, type=int)
    parser.add_argument("--event-reference", required=True)
    parser.add_argument("--trigger-decision-id", required=True)
    parser.add_argument("--query", required=True)
    args = parser.parse_args()
    if not args.owner_authorized_one_search:
        parser.error("--owner-authorized-one-search is required")
    capability = periodic_report.load_validated_research_skill_trigger_capability(
        ROOT,
        issuance_receipt_id=args.issuance_receipt_id,
        report_key=args.report_key,
        revision=args.revision,
        event_reference=args.event_reference,
        trigger_decision_id=args.trigger_decision_id,
    )
    request = build_skill_request(
        validated_trigger=capability,
        report_key=args.report_key,
        revision=args.revision,
        event_reference=args.event_reference,
        command="SEARCH",
        query=args.query,
    )
    envelope = execute_governed_search(
        capability, request, allow_anonymous=True
    )
    path = write_staging_output(envelope, ROOT / "runtime" / "anysearch_staging")
    print(json.dumps({"status": envelope["status"], "candidate_count": len(envelope["candidates"]), "staging_path": str(path), "actionable": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
