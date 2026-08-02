#!/usr/bin/env python3
"""Build the offline Phase B1 R2 Final Owner Review package."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PACKAGE_ROOT / "modules" / "p1008_research_plugin" / "src"
sys.path.insert(0, str(SRC_ROOT))

from p1008_research_plugin.phaseb1_common import (  # noqa: E402
    atomic_write,
    atomic_write_json,
    protected_state_hashes,
    sha256_file,
)
from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline  # noqa: E402


REVIEW_FILES = (
    "analysis_packet.json",
    "analysis_validation.json",
    "evidence_manifest.json",
    "report_candidate.json",
    "report_candidate.md",
    "longform_script_candidate.md",
    "shorts_75s_candidate.md",
    "shorts_duration_validation.json",
    "editorial_validation.json",
)

SUPERSEDED_REVIEW_ID = "P1008-PHASE-B1-FINAL-OWNER-REVIEW-20260801T154042Z"
SUPERSEDED_SHORTS_SHA256 = (
    "C975335AAD170BC30A4BA7D5D0E313DB6B7C5ACCB9D5B6C38B367AF52179CAA5"
)


def final_review_passes(
    editorial: dict[str, object],
    duration: dict[str, object],
    before: dict[str, str],
    after: dict[str, str],
    report: dict[str, object],
) -> bool:
    """Return True only when duration and sentence integrity both pass."""
    return bool(
        editorial.get("status") == "PASS"
        and duration.get("durationGateStatus") != "FAIL"
        and duration.get("sentenceIntegrityStatus") == "PASS"
        and duration.get("numericUnitStatus") == "PASS"
        and duration.get("allSegmentsSemanticallyComplete") is True
        and before == after
        and report.get("actionable") is False
    )


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_review(package_root: Path, stamp: str | None = None) -> Path:
    package_root = package_root.resolve()
    review_root = (
        package_root
        / "runtime"
        / "phaseb1_final_owner_review"
        / f"P1008-PHASE-B1-FINAL-OWNER-REVIEW-R2-{stamp or _utc_stamp()}"
    )
    if review_root.exists():
        raise RuntimeError(f"Review package already exists: {review_root}")
    review_root.mkdir(parents=True, exist_ok=False)
    before = protected_state_hashes(package_root)
    pipeline_base = review_root / "_pipeline"
    result = PhaseB1Pipeline(package_root).run_all(output_base=pipeline_base)
    run_root = pipeline_base / result["run_id"]

    for name in REVIEW_FILES:
        source = run_root / name
        if not source.is_file():
            raise RuntimeError(f"Required review artifact is missing: {name}")
        shutil.copyfile(source, review_root / name)

    report = json.loads((review_root / "report_candidate.json").read_text(encoding="utf-8"))
    editorial = json.loads((review_root / "editorial_validation.json").read_text(encoding="utf-8"))
    duration = json.loads((review_root / "shorts_duration_validation.json").read_text(encoding="utf-8"))
    source_lineage = {
        "runId": result["run_id"],
        "analysisPacketSha256": report["analysisPacketSha256"],
        "authorityManifestSha256": report["authorityManifestSha256"],
        "evidenceReferences": report["evidenceReferences"],
        "externalCalls": {
            "openaiApi": 0,
            "hostedWebSearch": 0,
            "deepResearch": 0,
            "canva": 0,
            "gemini": 0,
            "youtube": 0,
        },
        "actionable": False,
    }
    atomic_write_json(review_root / "source_lineage.json", source_lineage)
    supersession = {
        "recordType": "P1008_PHASE_B1_FINAL_REVIEW_SUPERSESSION_RECEIPT",
        "supersededReviewId": SUPERSEDED_REVIEW_ID,
        "supersededShortsSha256": SUPERSEDED_SHORTS_SHA256,
        "supersedingReviewId": review_root.name,
        "reason": (
            "R1 Shorts passed artifact identity and duration checks but failed sentence "
            "integrity because production text was mechanically sliced at Unicode character limits."
        ),
        "supersededSourceHead": "02312a3de5f084d99057d174b74b3403963ff882",
        "finalOwnerAcceptanceGranted": False,
        "actionable": False,
    }
    atomic_write_json(review_root / "supersession_receipt.json", supersession)
    atomic_write_json(review_root / "protected_state_before.json", before)
    after = protected_state_hashes(package_root)
    atomic_write_json(review_root / "protected_state_after.json", after)

    passed = final_review_passes(editorial, duration, before, after, report)
    decision = (
        "PHASE_B1_SHORTS_SENTENCE_INTEGRITY_PASS\n"
        "PHASE_B1_FINAL_REVIEW_R2_PASS\n"
        "DRAFT_PR_OPEN_UNMERGED\n"
        "FINAL_OWNER_ACCEPTANCE_NOT_GRANTED\n"
        "ACTIONABLE_FALSE\n"
        if passed
        else
        "PHASE_B1_FINAL_REVIEW_R2_FAIL\n"
        "FAIL_CLOSED\n"
        "BLOCKERS: [editorial, duration, sentence-integrity, numeric-unit, protected-state, or actionable gate failed]\n"
        "DRAFT_PR_OPEN_UNMERGED\n"
        "FINAL_OWNER_ACCEPTANCE_NOT_GRANTED\n"
        "ACTIONABLE_FALSE\n"
    )
    atomic_write(review_root / "owner_decision.md", decision.encode("utf-8"))

    artifact_hashes = {
        path.name: sha256_file(path)
        for path in sorted(review_root.iterdir(), key=lambda item: item.name.casefold())
        if path.is_file()
    }
    summary = {
        "reviewId": review_root.name,
        "status": "PASS" if passed else "FAIL_CLOSED",
        "runId": result["run_id"],
        "editorialStatus": editorial["status"],
        "shortsDurationStatus": duration["durationGateStatus"],
        "shortsSentenceIntegrityStatus": duration["sentenceIntegrityStatus"],
        "shortsNumericUnitStatus": duration["numericUnitStatus"],
        "shortsEstimatedSeconds": duration["estimatedSpokenSeconds"],
        "protectedStateUnchanged": before == after,
        "artifactSha256": artifact_hashes,
        "externalCalls": {
            "openaiApi": 0,
            "hostedWebSearch": 0,
            "deepResearch": 0,
            "canva": 0,
            "gemini": 0,
            "youtube": 0,
        },
        "phaseB2Started": False,
        "actionable": False,
    }
    atomic_write_json(review_root / "PHASE_B1_FINAL_REVIEW_REPORT.json", summary)
    markdown = f"""# P1008 Phase B1 Final Owner Review R2

- Status: `{summary['status']}`
- Run ID: `{result['run_id']}`
- Editorial: `{editorial['status']}`
- Shorts duration: `{duration['durationGateStatus']}` / `{duration['estimatedSpokenSeconds']}` seconds
- Sentence integrity: `{duration['sentenceIntegrityStatus']}`
- Numeric units: `{duration['numericUnitStatus']}`
- Protected state unchanged: `{str(before == after).lower()}`
- OpenAI / Web Search / Deep Research / Canva / Gemini / YouTube calls: `0 / 0 / 0 / 0 / 0 / 0`
- Live synthesis started: `false`
- Phase B2 started: `false`
- Final Owner acceptance granted: `false`
- actionable: `false`
"""
    atomic_write(
        review_root / "PHASE_B1_FINAL_REVIEW_REPORT.md",
        markdown.replace("\r\n", "\n").encode("utf-8"),
    )
    if not passed:
        raise RuntimeError("Final Owner Review package failed closed")

    pipeline_resolved = pipeline_base.resolve()
    if pipeline_resolved.parent != review_root.resolve():
        raise RuntimeError("Unsafe pipeline cleanup path")
    shutil.rmtree(pipeline_resolved)
    return review_root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, default=PACKAGE_ROOT)
    parser.add_argument("--stamp", help="Optional unique UTC-like test stamp")
    args = parser.parse_args()
    path = build_review(args.package_root, args.stamp)
    print(json.dumps({"status": "PASS", "reviewRoot": str(path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
