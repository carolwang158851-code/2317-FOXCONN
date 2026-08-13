from __future__ import annotations

import json
import os
import shutil
import unittest
from pathlib import Path

try:
    from .helpers import PACKAGE_ROOT, SRC_ROOT, scratch
except ImportError:
    from helpers import PACKAGE_ROOT, SRC_ROOT, scratch

from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline
from p1008_research_plugin.quarterly_earnings import (
    QuarterlyEarningsPacket,
    QuarterlyEarningsPacketError,
)
from p1008_research_plugin.reporting.report_contracts import (
    QUARTERLY_EARNINGS_SECTION_IDS,
)


class QuarterlyEarningsProductionSliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        evidence_root = Path(os.environ.get("P1008_GOVERNED_EVIDENCE_ROOT", PACKAGE_ROOT / "runtime")).resolve()
        trigger_path = evidence_root / "report_trigger/latest_decision.json"
        integration_path = evidence_root / "research_plugin/latest_content_integration.json"
        if not trigger_path.is_file() or not integration_path.is_file():
            raise unittest.SkipTest("real FY2026 Q2 acceptance runtime is unavailable")
        cls.evidence_root = evidence_root
        cls.trigger = json.loads(trigger_path.read_text(encoding="utf-8"))
        cls.lineage = {
            "reportKey": cls.trigger["report_key"],
            "revision": cls.trigger["revision"],
            "eventType": cls.trigger["event_type"],
            "canonicalEventId": cls.trigger["canonical_event_id"],
            "triggerDecisionId": cls.trigger["decision_id"],
            "triggerReceiptSha256": cls.trigger["canonical_sha256"],
            "evidenceIds": cls.trigger["qualifying_evidence_ids"],
            "authorityCutoffs": cls.trigger["authority_cutoffs"],
            "actionable": False,
        }

    def test_real_q2_evidence_reaches_owner_review_with_html_and_pdf(self) -> None:
        with scratch("quarterly-real-") as output:
            pipeline = PhaseB1Pipeline(
                PACKAGE_ROOT, governed_evidence_root=self.evidence_root
            )
            result = pipeline.build_analysis(output_base=output, trigger_lineage=self.lineage)
            report = pipeline.build_report(run_id=result["run_id"], output_base=output, trigger_lineage=self.lineage)
            run_root = Path(report["run_root"])
            manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
            owner = json.loads((run_root / "owner_review.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["state"], "REPORT_CANDIDATE_READY")
            self.assertEqual(manifest["eventType"], "QUARTERLY_EARNINGS")
            self.assertEqual(owner["status"], "OWNER_REVIEW_REQUIRED")
            self.assertFalse(owner["publishAuthorized"])
            self.assertTrue((run_root / "report_candidate.html").is_file())
            self.assertTrue((run_root / "report_candidate.pdf").is_file())
            self.assertEqual(tuple(item.section_id for item in report["report"].sections), QUARTERLY_EARNINGS_SECTION_IDS)
            quarterly = report["analysis"].quarterly_earnings
            self.assertIsNotNone(quarterly)
            self.assertEqual(quarterly.source_hash, "F014BE750095543B35ED2D482C0CF7A40B4A448167796F8AC4560AB928E609C5")
            self.assertEqual(quarterly.cash_flow_status, "OFFICIAL_RESULTS_H1_NOT_STANDALONE_Q2")
            self.assertEqual(quarterly.apple_iphone_exposure_status, "REVIEW_REQUIRED")
            governed = manifest["governedEvidence"]
            self.assertEqual(governed["mode"], "EXTERNAL_GOVERNED_READ_ONLY")
            self.assertEqual(governed["root"], str(self.evidence_root))
            self.assertEqual(governed["raw_artifact_sha256"], quarterly.source_hash)

    def test_missing_external_governed_evidence_root_fails_closed(self) -> None:
        with scratch("quarterly-missing-evidence-root-") as root:
            missing = root / "missing-governed-runtime"
            with self.assertRaisesRegex(QuarterlyEarningsPacketError, "GOVERNED_EVIDENCE_ROOT_MISSING"):
                QuarterlyEarningsPacket(
                    PACKAGE_ROOT, self.lineage, governed_evidence_root=missing
                )

    def test_raw_pdf_hash_drift_fails_closed(self) -> None:
        with scratch("quarterly-hash-drift-") as root:
            package = root / "package"
            shutil.copytree(PACKAGE_ROOT / "data", package / "data")
            shutil.copytree(PACKAGE_ROOT / "contracts", package / "contracts")
            shutil.copytree(PACKAGE_ROOT / "rules", package / "rules")
            config_source = PACKAGE_ROOT / QuarterlyEarningsPacket.CONFIG_REL
            config_target = package / QuarterlyEarningsPacket.CONFIG_REL
            config_target.parent.mkdir(parents=True)
            shutil.copy2(config_source, config_target)
            evidence_root = Path(os.environ.get("P1008_GOVERNED_EVIDENCE_ROOT", PACKAGE_ROOT / "runtime")).resolve()
            integration_source = evidence_root / "research_plugin" / "latest_content_integration.json"
            integration_target = package / QuarterlyEarningsPacket.INTEGRATION_REL
            integration_target.parent.mkdir(parents=True)
            shutil.copy2(integration_source, integration_target)
            trigger_source = evidence_root / "report_trigger" / "latest_decision.json"
            trigger_target = package / "runtime" / "report_trigger" / "latest_decision.json"
            trigger_target.parent.mkdir(parents=True)
            shutil.copy2(trigger_source, trigger_target)
            event = json.loads(integration_source.read_text(encoding="utf-8"))["validated_event_evidence"][0]
            for key in ("receipt_path", "raw_artifact_path"):
                relative = Path(event["provenance"][key])
                target = package / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(evidence_root / relative.relative_to("runtime"), target)
            (package / event["provenance"]["raw_artifact_path"]).write_bytes(b"%PDF-drift")
            with self.assertRaisesRegex(QuarterlyEarningsPacketError, "RAW_HASH_MISMATCH"):
                QuarterlyEarningsPacket(
                    package, self.lineage, governed_evidence_root=package / "runtime"
                )


if __name__ == "__main__":
    unittest.main()
