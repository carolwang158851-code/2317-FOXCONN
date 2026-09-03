from __future__ import annotations

import copy
import json
import os
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

try:
    from .helpers import PACKAGE_ROOT, SRC_ROOT  # noqa: F401
except ImportError:
    from helpers import PACKAGE_ROOT, SRC_ROOT  # noqa: F401

from p1008_research_plugin.analysis.numeric_claim_lineage import (
    NumericClaimLineageError,
    validate_working_capital_qoq_lineage,
    working_capital_qoq_lineage,
)
from p1008_research_plugin.reporting.report_validator import ReportValidator
from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline


class EditorialNumericClaimLineageTests(unittest.TestCase):
    SOURCE_ID = "IR-EVIDENCE-EE53AFE9517E1D666F0A"
    SOURCE_SHA = "F014BE750095543B35ED2D482C0CF7A40B4A448167796F8AC4560AB928E609C5"
    BALANCE = {
        "accountsReceivableNetMillionTwd": "1385237",
        "inventoryMillionTwd": "1370073",
        "accountsPayableMillionTwd": "1527523",
        "q1": {
            "accountsReceivableNetMillionTwd": "1166008",
            "inventoryMillionTwd": "1209878",
            "accountsPayableMillionTwd": "1322837",
        },
    }

    def lineage(self):
        return working_capital_qoq_lineage(
            self.BALANCE, source_evidence_ids=[self.SOURCE_ID],
            source_document_sha256=self.SOURCE_SHA, source_page="8",
        )

    def validate(self, payload):
        return validate_working_capital_qoq_lineage(
            payload, expected_source_ids=[self.SOURCE_ID],
            expected_source_sha256=self.SOURCE_SHA, expected_source_page="8",
        )

    def test_exact_174738_claim_is_supported_without_rounding(self):
        result = self.lineage()
        self.assertEqual(result["value"], "174738")
        self.assertEqual(result["unit"], "新台幣百萬元")
        self.assertEqual(result["q1NetWorkingCapitalProxyMillionTwd"], "1053049")
        self.assertEqual(result["q2NetWorkingCapitalProxyMillionTwd"], "1227787")
        self.assertEqual(result["normalization"], "DECIMAL_EXACT_NO_ROUNDING")

    def test_altered_claim_value_fails_closed(self):
        payload = self.lineage()
        payload["value"] = "174739"
        with self.assertRaisesRegex(NumericClaimLineageError, "VALUE_MISMATCH"):
            self.validate(payload)

    def test_wrong_unit_fails_closed(self):
        payload = self.lineage()
        payload["unit"] = "新台幣千元"
        with self.assertRaisesRegex(NumericClaimLineageError, "UNIT_INVALID"):
            self.validate(payload)

    def test_missing_citation_fails_closed(self):
        payload = self.lineage()
        payload["sourceEvidenceIds"] = []
        with self.assertRaisesRegex(NumericClaimLineageError, "CITATION_REQUIRED"):
            self.validate(payload)

    def test_tampered_source_input_fails_closed(self):
        payload = copy.deepcopy(self.lineage())
        payload["inputs"]["q2InventoryMillionTwd"] = "1370074"
        with self.assertRaisesRegex(NumericClaimLineageError, "VALUE_MISMATCH"):
            self.validate(payload)

    def test_serialized_lineage_supports_editorial_numeric_claim(self):
        lineage = self.lineage()
        analysis_text = json.dumps({"workingCapitalQoqIncrease": lineage}, ensure_ascii=False)
        report_text = "三項淨額仍增加174,738百萬元。"
        self.assertEqual(
            ReportValidator._numbers(report_text) - ReportValidator._numbers(analysis_text),
            set(),
        )

    def test_altered_editorial_claim_remains_unsupported(self):
        lineage = self.lineage()
        analysis_text = json.dumps({"workingCapitalQoqIncrease": lineage}, ensure_ascii=False)
        report_text = "三項淨額仍增加174,739百萬元。"
        self.assertEqual(
            ReportValidator._numbers(report_text) - ReportValidator._numbers(analysis_text),
            {"174739"},
        )

    def test_deterministic_q2_report_editorial_validation(self):
        configured = os.environ.get("P1008_GOVERNED_EVIDENCE_ROOT", "").strip()
        if not configured:
            self.skipTest("governed F014 compatibility root not supplied")
        evidence_root = Path(configured).resolve()
        trigger_path = evidence_root / "report_trigger/latest_decision.json"
        integration_path = evidence_root / "research_plugin/latest_content_integration.json"
        if not trigger_path.is_file() or not integration_path.is_file():
            self.skipTest("governed F014 compatibility artifacts unavailable")
        trigger = json.loads(trigger_path.read_text(encoding="utf-8"))
        lineage = {
            "reportKey": trigger["report_key"], "revision": trigger["revision"],
            "eventType": trigger["event_type"], "canonicalEventId": trigger["canonical_event_id"],
            "triggerDecisionId": trigger["decision_id"],
            "triggerReceiptSha256": trigger["canonical_sha256"],
            "evidenceIds": trigger["qualifying_evidence_ids"],
            "authorityCutoffs": trigger["authority_cutoffs"], "actionable": False,
        }
        output = PACKAGE_ROOT / "runtime/report_production/test_scratch" / f"q2-editorial-{uuid4().hex}"
        output.mkdir(parents=True)
        try:
            pipeline = PhaseB1Pipeline(PACKAGE_ROOT, governed_evidence_root=evidence_root)
            analysis_result = pipeline.build_analysis(output_base=output, trigger_lineage=lineage)
            report_result = pipeline.build_report(
                run_id=analysis_result["run_id"], output_base=output, trigger_lineage=lineage,
            )
            run_root = Path(report_result["run_root"])
            editorial = json.loads((run_root / "editorial_validation.json").read_text(encoding="utf-8"))
            sections = {item.section_id: item.body_zh for item in report_result["report"].sections}
            derived = report_result["analysis"].quarterly_earnings.enterprise_value_analytics[
                "workingCapitalQoqIncrease"
            ]
            self.assertEqual(editorial["status"], "PASS")
            self.assertTrue(editorial["unsupportedNumericClaimsAbsent"])
            self.assertIn("174,738百萬元", sections["WORKING_CAPITAL_CAPITAL_REQUIREMENT"])
            self.assertEqual(derived["value"], "174738")
            self.assertEqual(derived["sourceDocumentSha256"], self.SOURCE_SHA)
            self.assertEqual(derived["sourceEvidenceIds"], [self.SOURCE_ID])
        finally:
            shutil.rmtree(output, ignore_errors=False)


if __name__ == "__main__":
    unittest.main()
