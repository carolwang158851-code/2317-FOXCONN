"""Manual deterministic Phase B1 Report-candidate entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


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

    try:
        evidence_root, _evidence_context = trigger_runtime.governed_evidence_root(package_root)
        trigger = trigger_runtime.require_valid_trigger(package_root)
        lineage = trigger_runtime.trigger_lineage(trigger)
        run_id = args.run_id or _analysis_run_id(package_root, lineage)
        result = PhaseB1Pipeline(package_root, governed_evidence_root=evidence_root).build_report(
            run_id=run_id, trigger_lineage=lineage
        )
    except Exception as exc:  # noqa: BLE001 - CLI must return a precise fail-closed reason.
        print(json.dumps({"status": "FAIL_CLOSED", "error": str(exc), "actionable": False}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "status": "REPORT_CANDIDATE_READY",
                "runId": result["run_id"],
                "outputPath": result["run_root"],
                "reportCandidateSha256": result["report_json_sha256"],
                "externalCalls": 0,
                "actionable": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
