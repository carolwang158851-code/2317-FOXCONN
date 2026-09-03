"""Manual deterministic Phase B1 Report-candidate entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _report_runtime(event_type: str) -> str:
    return (
        "ENTERPRISE_VALUE_WAR_REPORT_V1"
        if event_type == "QUARTERLY_EARNINGS"
        else "PHASE_B1_LEGACY"
    )


def _analysis_run_id(package_root: Path, trigger_lineage: dict[str, object]) -> str:
    root = package_root / "runtime" / "report_production"
    matches: list[tuple[str, str]] = []
    if root.is_dir():
        for path in root.glob("*/run_manifest.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if (
                payload.get("state") == "ANALYSIS_CANDIDATE_READY"
                and payload.get("triggerLineage") == trigger_lineage
            ):
                matches.append((str(payload.get("generatedAtUtc") or ""), str(payload.get("runId") or "")))
    if not matches:
        raise RuntimeError("No validated Phase B1 Analysis candidate is available")
    return sorted(matches)[-1][1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a P1008 Phase B1 report candidate.")
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    package_root = args.package_root.resolve()
    sys.path.insert(0, str(package_root / "modules" / "p1008_research_plugin" / "src"))

    from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline
    import warroom_report_trigger_runtime as trigger_runtime
    import warroom_quarterly_report_completion as quarterly_completion

    try:
        evidence_root, _evidence_context = trigger_runtime.governed_evidence_root(package_root)
        trigger = trigger_runtime.require_valid_trigger(package_root)
        lineage = trigger_runtime.trigger_lineage(trigger)
        run_id = args.run_id or _analysis_run_id(package_root, lineage)
        result = PhaseB1Pipeline(package_root, governed_evidence_root=evidence_root).build_report(
            run_id=run_id,
            trigger_lineage=lineage,
            report_runtime=_report_runtime(trigger["event_type"]),
        )
        completion = None
        if trigger["event_type"] == "QUARTERLY_EARNINGS":
            completion = quarterly_completion.complete_quarterly_report(
                package_root, result
            )
            if completion.get("status") not in {
                "OWNER_REVIEW_REQUIRED", "IDEMPOTENT_REPLAY",
            }:
                raise RuntimeError(
                    "Quarterly governed completion failed: "
                    + str(completion.get("reason") or completion.get("status"))
                )
    except Exception as exc:  # noqa: BLE001 - CLI must return a precise fail-closed reason.
        print(json.dumps({"status": "FAIL_CLOSED", "error": str(exc), "actionable": False}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "status": (
                    completion["status"] if completion is not None
                    else "REPORT_CANDIDATE_READY"
                ),
                "runId": result["run_id"],
                "outputPath": result.get("candidate_output_root", result["run_root"]),
                "reportRuntime": result.get("report_runtime", "PHASE_B1_LEGACY"),
                "reportCandidateSha256": (
                    completion.get("reportCandidateSha256") if completion is not None
                    else result["report_json_sha256"]
                ),
                "reportCompletion": completion,
                "externalCalls": 0,
                "actionable": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
