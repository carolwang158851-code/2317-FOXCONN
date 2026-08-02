from __future__ import annotations

import json
import unittest

from pydantic import ValidationError

try:
    from .helpers import PACKAGE_ROOT, fixture, scratch
except ImportError:  # direct discovery with phaseb1 as the start directory
    from helpers import PACKAGE_ROOT, fixture, scratch

from p1008_research_plugin.phaseb1_common import sha256_file
from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline, PhaseB1PipelineError
from p1008_research_plugin.reporting.report_contracts import ReportCandidate
from p1008_research_plugin.reporting.report_validator import ReportValidationError, ReportValidator


class PhaseB1ReportProductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with scratch("report-valid-") as output:
            result = PhaseB1Pipeline(PACKAGE_ROOT).run_all(output_base=output)
            cls.analysis = result["analysis"]
            cls.report = result["report"]

    def test_complete_report_has_twenty_sections_and_actionable_false(self) -> None:
        self.assertEqual(len(self.report.sections), 20)
        self.assertFalse(self.report.actionable)
        self.assertEqual(self.report.report_contract_version, "1.0")
        self.assertIn("營收", self.report.primary_investor_question)

    def test_report_cannot_bypass_analysis_validation(self) -> None:
        payload = self.report.model_dump(mode="json", by_alias=True)
        payload["analysisPacketSha256"] = "0" * 64
        with self.assertRaises(ReportValidationError):
            ReportValidator().validate(ReportCandidate.model_validate(payload), self.analysis)

    def test_report_cannot_change_evidence_bound_number(self) -> None:
        payload = self.report.model_dump(mode="json", by_alias=True)
        payload["evidenceBoundFacts"][0] = payload["evidenceBoundFacts"][0].replace("52.11", "99.99")
        with self.assertRaises(ReportValidationError):
            ReportValidator().validate(ReportCandidate.model_validate(payload), self.analysis)

    def test_report_cannot_change_thesis_state(self) -> None:
        payload = self.report.model_dump(mode="json", by_alias=True)
        payload["thesisState"] = "REVIEW_REQUIRED"
        with self.assertRaises(ReportValidationError):
            ReportValidator().validate(ReportCandidate.model_validate(payload), self.analysis)

    def test_missing_actionable_false_fails_schema(self) -> None:
        payload = self.report.model_dump(mode="json", by_alias=True)
        payload.pop("actionable")
        with self.assertRaises(ValidationError):
            ReportCandidate.model_validate(payload)

    def test_report_requires_prior_analysis_artifacts(self) -> None:
        with scratch("no-analysis-") as output:
            pipeline = PhaseB1Pipeline(PACKAGE_ROOT)
            with self.assertRaises(PhaseB1PipelineError):
                pipeline.build_report(
                    run_id=pipeline.deterministic_run_id(fixture()),
                    output_base=output,
                )

    def test_report_rejects_drifted_validated_evidence_manifest(self) -> None:
        with scratch("evidence-drift-") as output:
            pipeline = PhaseB1Pipeline(PACKAGE_ROOT)
            result = pipeline.build_analysis(output_base=output)
            evidence_path = output / result["run_id"] / "evidence_manifest.json"
            payload = json.loads(evidence_path.read_text(encoding="utf-8"))
            payload["sourceLocators"].append("https://www.honhai.com/unapproved-drift")
            evidence_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaises(PhaseB1PipelineError):
                pipeline.build_report(run_id=result["run_id"], output_base=output)

    def test_deterministic_outputs_match_across_fresh_roots(self) -> None:
        with scratch("replay-a-") as first, scratch("replay-b-") as second:
            first_result = PhaseB1Pipeline(PACKAGE_ROOT).run_all(output_base=first)
            second_result = PhaseB1Pipeline(PACKAGE_ROOT).run_all(output_base=second)
            for name in (
                "analysis_packet.json",
                "report_candidate.json",
                "report_candidate.md",
                "shorts_75s_candidate.md",
            ):
                self.assertEqual(
                    (first / first_result["run_id"] / name).read_bytes(),
                    (second / second_result["run_id"] / name).read_bytes(),
                )

    def test_fixture_output_hashes_match(self) -> None:
        with scratch("hash-golden-") as output:
            result = PhaseB1Pipeline(PACKAGE_ROOT).run_all(output_base=output)
            run_root = output / result["run_id"]
            expected = fixture()["expectedOutputSha256"]
            for name, digest in expected.items():
                with self.subTest(name=name):
                    self.assertEqual(sha256_file(run_root / name), digest)

    def test_run_manifest_records_zero_external_calls(self) -> None:
        with scratch("zero-calls-") as output:
            result = PhaseB1Pipeline(PACKAGE_ROOT).run_all(output_base=output)
            manifest = json.loads((output / result["run_id"] / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(set(manifest["externalCalls"].values()), {0})
            self.assertFalse(manifest["actionable"])


if __name__ == "__main__":
    unittest.main()
