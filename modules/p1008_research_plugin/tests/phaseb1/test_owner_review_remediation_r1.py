from __future__ import annotations

import copy
import json
import unittest

from pydantic import ValidationError

try:
    from .helpers import PACKAGE_ROOT, scratch, write_fixture
except ImportError:
    from helpers import PACKAGE_ROOT, scratch, write_fixture

from p1008_research_plugin.analysis.analysis_contracts import (
    AnalysisPacket,
    EventWindowStatus,
)
from p1008_research_plugin.analysis.analysis_validator import (
    AnalysisValidationError,
    AnalysisValidator,
)
from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline
from p1008_research_plugin.reporting.report_contracts import ReportCandidate
from p1008_research_plugin.reporting.report_validator import ReportValidator
from p1008_research_plugin.reporting.script_builder import (
    ScriptBuilder,
    ShortsDurationValidator,
)


ALT_FIXTURE = (
    PACKAGE_ROOT
    / "modules"
    / "p1008_research_plugin"
    / "tests"
    / "fixtures"
    / "phaseb1"
    / "monthly_revenue_fixture_alt_dates.json"
)
AUTHORIZATION_RECORD = (
    PACKAGE_ROOT
    / "contracts"
    / "p1008_report_production"
    / "acceptance"
    / "v1.0"
    / "PHASE_B1_OWNER_AUTHORIZATION_RECORD.json"
)


class PhaseB1OwnerReviewRemediationR1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with scratch("r1-valid-") as output:
            result = PhaseB1Pipeline(PACKAGE_ROOT).run_all(output_base=output)
            cls.analysis = result["analysis"]
            cls.report = result["report"]
        cls.evidence = PhaseB1Pipeline(PACKAGE_ROOT).load_inputs()[1]
        builder = ScriptBuilder()
        cls.longform = builder.longform(cls.report)
        cls.shorts = builder.shorts_75s(cls.report)
        cls.duration = ShortsDurationValidator.validate(cls.shorts)

    def test_ungoverned_pb_category_is_rejected(self) -> None:
        payload = self.analysis.model_dump(mode="json", by_alias=True)
        payload["valuationAnalysis"]["valuationStatus"] = "FAIR"
        payload["valuationAnalysis"]["valuationPolicyId"] = None
        with self.assertRaises(ValidationError):
            AnalysisPacket.model_validate(payload)

    def test_fixed_regime_assignment_is_rejected(self) -> None:
        payload = self.analysis.model_dump(mode="json", by_alias=True)
        payload["marketRegime"]["primaryRegime"] = "EARNINGS_REASSESSMENT"
        payload["marketRegime"]["evaluatedConditions"][0]["result"] = "FAIL"
        parsed = AnalysisPacket.model_validate(payload)
        with self.assertRaises(AnalysisValidationError):
            AnalysisValidator().validate(parsed, self.evidence)

    def test_numeric_confidence_is_rejected(self) -> None:
        payload = self.analysis.model_dump(mode="json", by_alias=True)
        payload["marketRegime"]["confidence"] = 0.8
        with self.assertRaises(ValidationError):
            AnalysisPacket.model_validate(payload)

    def test_trailing_twenty_day_return_is_not_event_reaction(self) -> None:
        recent = self.analysis.price_and_market_activity.recent_price_context
        event = self.analysis.price_and_market_activity.event_window_reaction
        self.assertIn("20D", recent.return_windows)
        self.assertNotIn("20D", event.return_windows)
        self.assertTrue(
            not event.return_windows
            or set(event.return_windows) == {"T-1_TO_T+1", "T-1_TO_T+5"}
        )

    def test_missing_unique_event_date_is_insufficient(self) -> None:
        payload = json.loads(
            (
                PACKAGE_ROOT
                / "modules/p1008_research_plugin/tests/fixtures/phaseb1/monthly_revenue_fixture.json"
            ).read_text(encoding="utf-8")
        )
        payload["packets"][1]["as_of_date"] = "2026-07-06"
        with scratch("r1-missing-event-date-") as root:
            pipeline = PhaseB1Pipeline(PACKAGE_ROOT, write_fixture(root, payload))
            with scratch("r1-missing-event-output-") as output:
                result = pipeline.run_all(output_base=output)
        reaction = result["analysis"].price_and_market_activity.event_window_reaction
        self.assertIs(reaction.status, EventWindowStatus.INSUFFICIENT_DATA)
        self.assertIsNone(reaction.publication_date)

    def test_second_fixture_has_no_date_or_evidence_identity_leakage(self) -> None:
        with scratch("r1-alt-") as output:
            result = PhaseB1Pipeline(PACKAGE_ROOT, ALT_FIXTURE).run_all(output_base=output)
            run_root = output / result["run_id"]
            combined = (run_root / "analysis_packet.json").read_text(encoding="utf-8") + (
                run_root / "report_candidate.json"
            ).read_text(encoding="utf-8")
        self.assertIn("20260612", result["run_id"])
        self.assertEqual(result["analysis"].financial_trend.revenue.period, "2026-05")
        self.assertEqual(
            result["analysis"].price_and_market_activity.event_window_reaction.publication_date.isoformat(),
            "2026-06-10",
        )
        self.assertIn("E-ALT-DA-MONTHLY-202605-OFFICIAL", combined)
        self.assertNotIn("2026-07-05", combined)
        self.assertNotIn("E-DA-MONTHLY-202606-OFFICIAL", combined)

    def test_unresolved_report_evidence_id_fails(self) -> None:
        payload = self.report.model_dump(mode="json", by_alias=True)
        payload["sections"][0]["evidenceIds"] = ["E-DOES-NOT-EXIST"]
        with self.assertRaises(ValidationError):
            ReportCandidate.model_validate(payload)

    def test_editorial_result_is_calculated_not_default_pass(self) -> None:
        sections = list(self.report.sections)
        sections[0] = sections[0].model_copy(
            update={"body_zh": "TODO placeholder 99.99%"}
        )
        changed = self.report.model_copy(update={"sections": sections})
        result = ReportValidator.editorial_result(
            changed, self.analysis, self.longform, self.shorts, self.duration
        )
        self.assertEqual(result.status, "FAIL")
        self.assertFalse(result.placeholders_absent)
        self.assertFalse(result.unsupported_numeric_claims_absent)

    def test_over_78_seconds_fails_duration_gate(self) -> None:
        script = "# 候選\n\n## 0–90秒\n" + ("長" * 400) + "\n"
        result = ShortsDurationValidator.validate(script)
        self.assertEqual(result.duration_gate_status, "FAIL")
        self.assertGreater(result.estimated_spoken_seconds, 78)

    def test_actionable_false_is_not_spoken(self) -> None:
        spoken = ShortsDurationValidator.spoken_text(self.shorts)
        self.assertNotIn("actionable=false", spoken.casefold())
        self.assertIn("actionable=false", self.shorts.casefold())
        self.assertIn(self.duration.duration_gate_status, {"PASS", "PASS_WITH_WARNING"})

    def test_authorization_record_cannot_represent_final_acceptance(self) -> None:
        record = json.loads(AUTHORIZATION_RECORD.read_text(encoding="utf-8"))
        self.assertTrue(record["implementationAuthorized"])
        self.assertFalse(record["finalAcceptanceGranted"])
        self.assertEqual(record["status"], "OWNER_AUTHORIZED_ADDITIVE_CHANGE")
        self.assertNotIn("acceptedBy", record)


if __name__ == "__main__":
    unittest.main()
