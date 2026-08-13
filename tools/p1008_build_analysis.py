"""Manual deterministic Phase B1 Analysis-candidate entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a P1008 Phase B1 analysis candidate.")
    parser.add_argument("--package-root", type=Path, required=True)
    args = parser.parse_args()
    package_root = args.package_root.resolve()
    sys.path.insert(0, str(package_root / "modules" / "p1008_research_plugin" / "src"))

    from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline
    import warroom_report_trigger_runtime as trigger_runtime

    try:
        evidence_root, _evidence_context = trigger_runtime.governed_evidence_root(package_root)
        trigger = trigger_runtime.require_valid_trigger(package_root)
        # Routing is owned by the existing PluginRouter. Phase B1 accepts only
        # event modes with a governed input path.
        from p1008_research_plugin.plugin_module.contracts import RunType
        from p1008_research_plugin.plugin_module.router import PluginRouter, RouteSignals
        PluginRouter().route(RunType(trigger["event_type"]), RouteSignals(earnings_event=True))
        pipeline = PhaseB1Pipeline(package_root, governed_evidence_root=evidence_root)
        if trigger["event_type"] not in pipeline.SUPPORTED_EVENTS:
            raise RuntimeError(f"PHASE_B1_EVENT_UNSUPPORTED: {trigger['event_type']}")
        result = pipeline.build_analysis(
            trigger_lineage=trigger_runtime.trigger_lineage(trigger)
        )
    except Exception as exc:  # noqa: BLE001 - CLI must return a precise fail-closed reason.
        print(json.dumps({"status": "FAIL_CLOSED", "error": str(exc), "actionable": False}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "status": "ANALYSIS_CANDIDATE_READY",
                "runId": result["run_id"],
                "outputPath": result["run_root"],
                "analysisPacketSha256": result["analysis_sha256"],
                "externalCalls": 0,
                "actionable": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
