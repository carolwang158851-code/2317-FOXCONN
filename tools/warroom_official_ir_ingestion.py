#!/usr/bin/env python3
"""Run one governed Official-IR-only scan and persist existing integration state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--period", help="FYyyyy-Qn, for a controlled smoke")
    args = parser.parse_args()
    root = Path(args.package_root).resolve()
    module_src = root / "modules" / "p1008_research_plugin" / "src"
    for value in (str(module_src), str(root / "tools")):
        if value not in sys.path:
            sys.path.insert(0, value)
    from p1008_research_plugin.adapters.official_ir_evidence_adapter import (  # noqa: PLC0415
        OfficialIREvidenceAdapter,
        OfficialIREvidenceError,
    )
    from p1008_research_plugin.orchestrator.research_content_integration import (  # noqa: PLC0415
        ResearchContentIntegrationError,
        ResearchContentOrchestrator,
    )
    import warroom_report_trigger_runtime as trigger_runtime  # noqa: PLC0415

    period = None
    if args.period:
        try:
            year, quarter = args.period.upper().replace("FY", "").split("-Q", 1)
            period = (int(year), int(quarter))
        except (ValueError, TypeError):
            print(json.dumps({"status": "FAIL_CLOSED", "error": "INVALID_PERIOD", "actionable": False}))
            return 20
    try:
        scan = OfficialIREvidenceAdapter(root).scan(target_period=period)
        if scan.get("scan_integrity_valid") is not True or scan.get("status") == "FAIL_CLOSED":
            print(json.dumps(scan, ensure_ascii=False, sort_keys=True))
            return 20
        integration = ResearchContentOrchestrator(root).integrate_official_ir(scan)
        sealed = trigger_runtime.persist_integration_result(root, integration)
        output = {
            **scan,
            "integration_receipt_sha256": sealed["canonical_sha256"],
            "g1_validation": integration["evidence"]["cross_validation"]["validation_status"],
            "g1_decision": integration["report_trigger_decision"]["decision"],
        }
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0
    except (OfficialIREvidenceError, ResearchContentIntegrationError, trigger_runtime.RuntimeTriggerError, OSError) as exc:
        print(json.dumps({"status": "FAIL_CLOSED", "error": str(exc), "actionable": False}, ensure_ascii=False, sort_keys=True))
        return 20


if __name__ == "__main__":
    raise SystemExit(main())
