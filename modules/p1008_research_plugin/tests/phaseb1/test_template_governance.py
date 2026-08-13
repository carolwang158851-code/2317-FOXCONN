from __future__ import annotations

import unittest

from p1008_research_plugin.reporting import template_governance as tg


def envelope():
    return tg.build_task_envelope(run_id="P1008-Q2-TEST", task_id="FINANCIAL-DEEP-REVIEW", event="QUARTERLY_EARNINGS", period="2026Q2", authority_cutoff="2026-08-11", research_question="Q2 earnings quality", required_inputs=["official-results"], required_analysis=["cash-conversion"], required_output=["candidate"], prohibited_actions=["publish"])


def item(signal="GREEN", **changes):
    payload = {"signal": signal, "actionable": False, "skill_mode": "SKILL_GUIDED_ONLY",
               "source_of_advantage": "Official Q2 demand evidence", "durability": "EVIDENCE_BUILDING",
               "capital_requirement": "Capex remains material", "competitor_replicability": "Not proven",
               "cash_conversion": "H1 FCF is negative", "invalidation_condition": "Guidance reduction",
               "next_checkpoint": "FY2026 Q3", "root_cause": "Not yet quantified",
               "counterevidence": "Gross margin declined", "enterprise_value_impact": "Needs verification",
               "retirement_mission_impact": "Cash conversion remains key", "clear_condition": "FCF improves",
               "deterioration_condition": "FCF weakens", "missing_data": "Q2 ROIC", "why_it_matters": "Capital efficiency",
               "acquisition_path": "Official filing", "next_calculation": "Calculate ROIC"}
    payload.update(changes)
    return payload


class TemplateGovernanceTests(unittest.TestCase):
    def test_envelope_is_hash_bound_and_q2_only(self):
        one = envelope(); self.assertEqual(one["template_hash"], tg.template_hash())
        with self.assertRaisesRegex(tg.TemplateGovernanceError, "EVENT"):
            tg.build_task_envelope(run_id="R", task_id="T", event="DAILY", period="x", authority_cutoff="x", research_question="x", required_inputs=[], required_analysis=[], required_output=[], prohibited_actions=[])

    def test_green_requires_durability_fields(self):
        bad = item(); del bad["cash_conversion"]
        with self.assertRaisesRegex(tg.TemplateGovernanceError, "cash_conversion"):
            tg.validate_result_item(bad)

    def test_non_green_and_white_require_deep_review_fields(self):
        for signal, field in (("YELLOW", "counterevidence"), ("RED", "root_cause"), ("WHITE", "missing_data")):
            bad = item(signal); del bad[field]
            with self.assertRaises(tg.TemplateGovernanceError): tg.validate_result_item(bad)

    def test_skill_guided_cannot_claim_runtime_receipt(self):
        with self.assertRaisesRegex(tg.TemplateGovernanceError, "MUST_NOT"):
            tg.validate_result_item(item(skill_receipt="fake"))

    def test_packet_is_partial_and_actionable_false(self):
        result = tg.validate_packet(envelope=envelope(), result_items=[item("GREEN"), item("YELLOW")], validation_status="PARTIAL_RESEARCH_CANDIDATE")
        self.assertEqual(result["validationStatus"], "PARTIAL_RESEARCH_CANDIDATE")
        self.assertFalse(result["actionable"])


if __name__ == "__main__":
    unittest.main()
