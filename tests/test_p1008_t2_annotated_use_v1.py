from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import p1008_t2_annotated_use_v1 as t2


SOURCE_PATH = (
    ROOT
    / "contracts"
    / "p1008_t2_annotated_use"
    / "v1.0"
    / "fixtures"
    / "P1008_DERIVED_KPI_CANDIDATE_V1.t2.synthetic.json"
)
CONTRACT_DIR = ROOT / "contracts" / "p1008_t2_annotated_use" / "v1.0"
LIMITATIONS = ["TEST_ONLY estimated BVPS is not a directly disclosed company value."]
SENSITIVITY_NOTES = "TEST_ONLY bounds vary the synthetic estimated BVPS denominator."
CREATED_AT = "2026-09-18T08:00:00Z"
APPROVED_AT = "2026-09-18T09:00:00Z"
RECORDED_AT = "2026-09-19T00:00:00Z"
OFFICIAL_HASH = "A" * 64


def load_source() -> dict:
    return json.loads(SOURCE_PATH.read_text(encoding="utf-8"))


def build_candidate(source: dict | None = None) -> dict:
    return t2.build_t2_research_candidate(
        source or load_source(),
        limitations=LIMITATIONS,
        sensitivity_notes=SENSITIVITY_NOTES,
        created_at=CREATED_AT,
    )


def approve(candidate: dict, scopes: tuple[str, ...] = ("REPORT_KPI_TABLE", "RESEARCH_APPENDIX")) -> dict:
    phrase = t2.required_owner_approval_phrase(candidate, scopes)
    return t2.create_owner_annotated_use_approval(
        candidate,
        approved_use_scope=scopes,
        approved_at=APPROVED_AT,
        approval_phrase=phrase,
    )


class T2SourceValidationTests(unittest.TestCase):
    def test_01_valid_candidate_passes(self) -> None:
        result = t2.validate_t2_source_candidate(
            load_source(), limitations=LIMITATIONS, sensitivity_notes=SENSITIVITY_NOTES
        )
        self.assertEqual("PASS", result.status)
        self.assertEqual("1.905", result.recomputed_point_estimate)

    def test_02_missing_assumptions_rejected(self) -> None:
        source = load_source()
        source["assumptions"] = []
        source["assumption_count"] = 0
        result = t2.validate_t2_source_candidate(source, limitations=LIMITATIONS, sensitivity_notes=SENSITIVITY_NOTES)
        self.assertEqual("FAIL", result.status)

    def test_03_missing_confidence_rejected(self) -> None:
        source = load_source()
        source.pop("confidence")
        result = t2.validate_t2_source_candidate(source, limitations=LIMITATIONS, sensitivity_notes=SENSITIVITY_NOTES)
        self.assertEqual("FAIL", result.status)

    def test_04_missing_limitations_rejected(self) -> None:
        result = t2.validate_t2_source_candidate(load_source(), limitations=[], sensitivity_notes=SENSITIVITY_NOTES)
        self.assertIn("limitations are required", result.errors)

    def test_05_missing_range_method_rejected(self) -> None:
        source = load_source()
        source["sensitivity_range"]["method"] = ""
        result = t2.validate_t2_source_candidate(source, limitations=LIMITATIONS, sensitivity_notes=SENSITIVITY_NOTES)
        self.assertEqual("FAIL", result.status)

    def test_06_t1_candidate_rejected(self) -> None:
        source = load_source()
        source["data_tier"] = t2.T1
        result = t2.validate_t2_source_candidate(source, limitations=LIMITATIONS, sensitivity_notes=SENSITIVITY_NOTES)
        self.assertEqual("FAIL", result.status)

    def test_07_claims_official_rejected(self) -> None:
        result = t2.validate_t2_source_candidate(
            load_source(), limitations=LIMITATIONS, sensitivity_notes=SENSITIVITY_NOTES, claims_official=True
        )
        self.assertIn("T2 cannot claim to be official or directly disclosed", result.errors)

    def test_08_t4_ancestry_rejected(self) -> None:
        source = load_source()
        source["input_source_tiers"][1] = t2.T4
        result = t2.validate_t2_source_candidate(source, limitations=LIMITATIONS, sensitivity_notes=SENSITIVITY_NOTES)
        self.assertIn("T4 scenario ancestry cannot represent a historical T2 estimate", result.errors)

    def test_09_bad_hash_rejected(self) -> None:
        source = load_source()
        source["input_hashes"][0] = "bad"
        result = t2.validate_t2_source_candidate(source, limitations=LIMITATIONS, sensitivity_notes=SENSITIVITY_NOTES)
        self.assertEqual("FAIL", result.status)

    def test_10_ambiguous_period_rejected(self) -> None:
        source = load_source()
        source["period_alignment_rule"] = "MIXED"
        result = t2.validate_t2_source_candidate(source, limitations=LIMITATIONS, sensitivity_notes=SENSITIVITY_NOTES)
        self.assertIn("period basis is ambiguous", result.errors)

    def test_11_ambiguous_denominator_rejected(self) -> None:
        source = load_source()
        source["denominator_definition"] = "UNKNOWN"
        result = t2.validate_t2_source_candidate(source, limitations=LIMITATIONS, sensitivity_notes=SENSITIVITY_NOTES)
        self.assertIn("denominator basis is ambiguous", result.errors)

    def test_12_out_of_range_point_rejected(self) -> None:
        source = load_source()
        source["sensitivity_range"]["low"] = "2.000"
        result = t2.validate_t2_source_candidate(source, limitations=LIMITATIONS, sensitivity_notes=SENSITIVITY_NOTES)
        self.assertIn("point estimate must fall within estimate bounds", result.errors)

    def test_13_unexpected_source_field_rejected(self) -> None:
        source = load_source()
        source["formal_authority"] = False
        result = t2.validate_t2_source_candidate(source, limitations=LIMITATIONS, sensitivity_notes=SENSITIVITY_NOTES)
        self.assertTrue(any("unsupported fields" in error for error in result.errors))

    def test_14_semantic_substitution_rejected(self) -> None:
        result = t2.validate_t2_source_candidate(
            load_source(), limitations=LIMITATIONS, sensitivity_notes=SENSITIVITY_NOTES,
            estimated_semantic_name="AI_REVENUE_SHARE",
        )
        self.assertIn("semantic substitution is forbidden", result.errors)

    def test_15_cloud_share_is_not_ai_revenue(self) -> None:
        self.assertFalse(t2.semantic_substitution_allowed("CLOUD_REVENUE_SHARE", "AI_REVENUE_SHARE"))

    def test_16_same_semantic_name_is_allowed(self) -> None:
        self.assertTrue(t2.semantic_substitution_allowed("price_to_book_multiple", "PRICE_TO_BOOK_MULTIPLE"))

    def test_17_high_confidence_completed_t2_rejected(self) -> None:
        source = load_source()
        source["confidence"] = "HIGH"
        result = t2.validate_t2_source_candidate(source, limitations=LIMITATIONS, sensitivity_notes=SENSITIVITY_NOTES)
        self.assertEqual("FAIL", result.status)


class CandidateAndApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate = build_candidate()

    def test_18_candidate_exact_envelope_valid(self) -> None:
        t2.validate_t2_research_candidate(self.candidate)
        self.assertEqual(set(t2.T2_CANDIDATE_FIELDS), set(self.candidate))

    def test_19_candidate_is_research_only(self) -> None:
        self.assertTrue(self.candidate["research_only"])
        self.assertFalse(self.candidate["formal_authority"])

    def test_20_candidate_formal_authority_true_rejected(self) -> None:
        self.candidate["formal_authority"] = True
        with self.assertRaises(t2.T2AnnotatedUseError):
            t2.validate_t2_research_candidate(self.candidate)

    def test_21_candidate_formal_scoring_true_rejected(self) -> None:
        self.candidate["formal_scoring_eligible"] = True
        with self.assertRaises(t2.T2AnnotatedUseError):
            t2.validate_t2_research_candidate(self.candidate)

    def test_22_candidate_actionable_true_rejected(self) -> None:
        self.candidate["actionable"] = True
        with self.assertRaises(t2.T2AnnotatedUseError):
            t2.validate_t2_research_candidate(self.candidate)

    def test_23_extra_candidate_field_rejected(self) -> None:
        self.candidate["unapproved_fact"] = True
        with self.assertRaises(t2.T2AnnotatedUseError):
            t2.validate_t2_research_candidate(self.candidate)

    def test_24_approval_does_not_mutate_candidate(self) -> None:
        before = copy.deepcopy(self.candidate)
        approve(self.candidate)
        self.assertEqual(before, self.candidate)

    def test_25_wrong_approval_phrase_rejected(self) -> None:
        with self.assertRaises(t2.T2AnnotatedUseError):
            t2.create_owner_annotated_use_approval(
                self.candidate, approved_use_scope=("RESEARCH_APPENDIX",), approved_at=APPROVED_AT,
                approval_phrase="OWNER_APPROVE_T2_ANNOTATED_USE wrong",
            )

    def test_26_approval_hash_binds_candidate(self) -> None:
        approval = approve(self.candidate)
        self.assertEqual(t2._candidate_hash(self.candidate), approval["candidate_hash"])

    def test_27_modified_candidate_invalidates_approval(self) -> None:
        approval = approve(self.candidate)
        self.candidate["point_estimate"] = "1.906"
        with self.assertRaises(t2.T2AnnotatedUseError):
            t2.validate_owner_approval(self.candidate, approval, required_scope="REPORT_KPI_TABLE")

    def test_28_modified_approval_value_rejected(self) -> None:
        approval = approve(self.candidate)
        approval["point_estimate"] = "9.999"
        with self.assertRaisesRegex(t2.T2AnnotatedUseError, "binding mismatch"):
            t2.validate_owner_approval(self.candidate, approval, required_scope="REPORT_KPI_TABLE")

    def test_29_unapproved_scope_rejected(self) -> None:
        approval = approve(self.candidate, ("RESEARCH_APPENDIX",))
        with self.assertRaises(t2.T2AnnotatedUseError):
            t2.validate_owner_approval(self.candidate, approval, required_scope="REPORT_MAIN_TEXT")

    def test_30_unknown_scope_rejected(self) -> None:
        with self.assertRaises(t2.T2AnnotatedUseError):
            t2.required_owner_approval_phrase(self.candidate, ("PRODUCTION_UI",))

    def test_31_dashboard_scope_not_wired(self) -> None:
        with self.assertRaisesRegex(t2.T2AnnotatedUseError, "NOT_WIRED"):
            t2.required_owner_approval_phrase(self.candidate, ("RESEARCH_DASHBOARD_DISPLAY",))

    def test_32_scopes_are_not_automatically_expanded(self) -> None:
        approval = approve(self.candidate, ("RESEARCH_APPENDIX",))
        self.assertEqual(["RESEARCH_APPENDIX"], approval["approved_use_scope"])

    def test_33_low_confidence_main_scope_policy_undefined(self) -> None:
        source = load_source()
        source["confidence"] = "LOW"
        candidate = build_candidate(source)
        phrase = t2.required_owner_approval_phrase(candidate, ("REPORT_MAIN_TEXT",))
        with self.assertRaisesRegex(t2.T2AnnotatedUseError, "UNDEFINED"):
            t2.create_owner_annotated_use_approval(
                candidate, approved_use_scope=("REPORT_MAIN_TEXT",), approved_at=APPROVED_AT,
                approval_phrase=phrase,
            )

    def test_34_low_confidence_appendix_can_be_explicitly_approved(self) -> None:
        source = load_source()
        source["confidence"] = "LOW"
        candidate = build_candidate(source)
        self.assertEqual("Owner", approve(candidate, ("RESEARCH_APPENDIX",))["approved_by"])


class DisplayReconciliationAndGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate = build_candidate()
        self.approval = approve(self.candidate)

    def test_35_unapproved_candidate_cannot_compile(self) -> None:
        with self.assertRaises(t2.T2AnnotatedUseError):
            t2.compile_annotated_display(self.candidate, {}, use_scope="REPORT_KPI_TABLE")

    def test_36_display_says_estimate(self) -> None:
        display = t2.compile_annotated_display(self.candidate, self.approval, use_scope="REPORT_KPI_TABLE")
        self.assertIn("推估", display["display_text_zh"])

    def test_37_display_says_not_directly_disclosed(self) -> None:
        display = t2.compile_annotated_display(self.candidate, self.approval, use_scope="REPORT_KPI_TABLE")
        self.assertIn("非公司直接揭露", display["display_text_zh"])

    def test_38_display_contains_confidence(self) -> None:
        display = t2.compile_annotated_display(self.candidate, self.approval, use_scope="REPORT_KPI_TABLE")
        self.assertIn("信心：中", display["display_text_zh"])

    def test_39_display_contains_range(self) -> None:
        display = t2.compile_annotated_display(self.candidate, self.approval, use_scope="REPORT_KPI_TABLE")
        self.assertIn("1.800–2.050", display["display_text_zh"])

    def test_40_display_contains_basis_and_assumptions(self) -> None:
        display = t2.compile_annotated_display(self.candidate, self.approval, use_scope="REPORT_KPI_TABLE")
        self.assertIn("基礎/假設", display["display_text_zh"])

    def test_41_t0_supersedes_t2_canonical_display(self) -> None:
        reconciliation = t2.reconcile_with_official(
            self.candidate, replacement_data_tier=t2.T0, replacement_value="1.910",
            replacement_source_id="TEST-OFFICIAL-PB", replacement_source_hash=OFFICIAL_HASH,
            recorded_at=RECORDED_AT,
        )
        display = t2.select_canonical_display(
            self.candidate, self.approval, use_scope="REPORT_KPI_TABLE", reconciliation=reconciliation
        )
        self.assertEqual("CANONICAL_T0_T1_SUPERSEDES_T2", display["display_state"])
        self.assertEqual(t2.T0, display["data_tier"])

    def test_42_t1_supersedes_t2_canonical_display(self) -> None:
        reconciliation = t2.reconcile_with_official(
            self.candidate, replacement_data_tier=t2.T1, replacement_value="1.911",
            replacement_source_id="TEST-EXACT-PB", replacement_source_hash=OFFICIAL_HASH,
            recorded_at=RECORDED_AT, state="RECONCILED",
        )
        display = t2.select_canonical_display(
            self.candidate, self.approval, use_scope="REPORT_KPI_TABLE", reconciliation=reconciliation
        )
        self.assertEqual(t2.T1, display["data_tier"])

    def test_43_t2_lineage_retained_after_replacement(self) -> None:
        reconciliation = t2.reconcile_with_official(
            self.candidate, replacement_data_tier=t2.T0, replacement_value="1.910",
            replacement_source_id="TEST-OFFICIAL-PB", replacement_source_hash=OFFICIAL_HASH,
            recorded_at=RECORDED_AT,
        )
        self.assertTrue(reconciliation["estimate_lineage_retained"])

    def test_44_t2_cannot_replace_t2(self) -> None:
        with self.assertRaises(t2.T2AnnotatedUseError):
            t2.reconcile_with_official(
                self.candidate, replacement_data_tier=t2.T2, replacement_value="1.910",
                replacement_source_id="TEST", replacement_source_hash=OFFICIAL_HASH,
                recorded_at=RECORDED_AT,
            )

    def test_45_rejected_estimate_not_displayed(self) -> None:
        reconciliation = t2.reject_estimate(self.candidate, reason="TEST_ONLY invalidated input", recorded_at=RECORDED_AT)
        display = t2.select_canonical_display(
            self.candidate, self.approval, use_scope="REPORT_KPI_TABLE", reconciliation=reconciliation
        )
        self.assertEqual("T2_ESTIMATE_REJECTED", display["display_state"])

    def test_46_scoring_guard_excludes_t2(self) -> None:
        self.assertEqual("EXCLUDED_T2_RESEARCH_ONLY", t2.assert_t2_excluded_from_formal_scoring(self.candidate))

    def test_47_scoring_guard_fails_on_mutation(self) -> None:
        self.candidate["production_scoring_enabled"] = True
        with self.assertRaises(t2.T2AnnotatedUseError):
            t2.assert_t2_excluded_from_formal_scoring(self.candidate)

    def test_48_publish_guard_excludes_t2(self) -> None:
        self.assertEqual("EXCLUDED_T2_RESEARCH_ONLY", t2.assert_t2_excluded_from_formal_publish(self.candidate))


class AuditSchemaAndDeterminismTests(unittest.TestCase):
    def test_49_roic_partial_estimate_eligible(self) -> None:
        audit = t2.current_kpi_t2_audit()
        self.assertEqual("ELIGIBLE", audit["ROIC_T2_STATUS"])
        self.assertIn("部分營運投入資本ROIC（推估）", audit["ROIC_T2_REQUIRED_LABEL"])

    def test_50_precise_roic_insufficient_inputs(self) -> None:
        self.assertEqual("INSUFFICIENT_INPUTS", t2.current_kpi_t2_audit()["ROIC_PRECISE_T2_STATUS"])

    def test_51_industry_ai_not_eligible(self) -> None:
        self.assertEqual("NOT_ELIGIBLE", t2.current_kpi_t2_audit()["INDUSTRY_AI_T2_STATUS"])

    def test_52_positioning_not_eligible(self) -> None:
        self.assertEqual("NOT_ELIGIBLE", t2.current_kpi_t2_audit()["POSITIONING_T2_STATUS"])

    def test_53_macro_not_eligible(self) -> None:
        self.assertEqual("NOT_ELIGIBLE", t2.current_kpi_t2_audit()["MACRO_T2_STATUS"])

    def test_54_candidate_build_is_deterministic(self) -> None:
        self.assertEqual(build_candidate(), build_candidate())

    def test_55_approval_build_is_deterministic(self) -> None:
        candidate = build_candidate()
        self.assertEqual(approve(candidate), approve(candidate))

    def test_56_policy_has_all_four_reconciliation_states(self) -> None:
        policy = json.loads((CONTRACT_DIR / "P1008_T2_ANNOTATED_USE_POLICY_V1.json").read_text(encoding="utf-8"))
        self.assertEqual(set(t2.RECONCILIATION_STATES), set(policy["reconciliation_states"]))

    def test_57_candidate_schema_required_matches_adapter(self) -> None:
        schema = json.loads((CONTRACT_DIR / "P1008_T2_RESEARCH_CANDIDATE_V1.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(t2.T2_CANDIDATE_FIELDS), set(schema["required"]))

    def test_58_t1_tool_is_unchanged_inherited_copy(self) -> None:
        expected = "4925FDA816CDC529A70E850850C898033C2C593DCDF2940803C0815B63B9B508"
        actual = hashlib.sha256((TOOLS / "p1008_t1_derived_kpi_bridge_v1.py").read_bytes()).hexdigest().upper()
        self.assertEqual(expected, actual)

    def test_59_policy_has_no_production_wiring(self) -> None:
        policy = json.loads((CONTRACT_DIR / "P1008_T2_ANNOTATED_USE_POLICY_V1.json").read_text(encoding="utf-8"))
        self.assertEqual("NONE", policy["production_wiring"])

    def test_60_approval_phrase_binds_scopes_in_canonical_order(self) -> None:
        candidate = build_candidate()
        phrase = t2.required_owner_approval_phrase(candidate, ("RESEARCH_APPENDIX", "REPORT_MAIN_TEXT"))
        self.assertTrue(phrase.endswith("SCOPES REPORT_MAIN_TEXT,RESEARCH_APPENDIX"))

    def test_61_checked_in_candidate_matches_adapter(self) -> None:
        checked = json.loads((CONTRACT_DIR / "fixtures" / "P1008_T2_RESEARCH_CANDIDATE_V1.synthetic.json").read_text(encoding="utf-8"))
        self.assertEqual(build_candidate(), checked)

    def test_62_checked_in_approval_matches_owner_gate(self) -> None:
        candidate = build_candidate()
        checked = json.loads((CONTRACT_DIR / "fixtures" / "P1008_T2_ANNOTATED_USE_APPROVAL_V1.synthetic.json").read_text(encoding="utf-8"))
        self.assertEqual(approve(candidate), checked)

    def test_63_checked_in_display_matches_formatter(self) -> None:
        candidate = build_candidate()
        approval = approve(candidate)
        expected = t2.compile_annotated_display(candidate, approval, use_scope="REPORT_KPI_TABLE")
        checked = json.loads((CONTRACT_DIR / "fixtures" / "P1008_T2_ANNOTATED_DISPLAY_V1.synthetic.json").read_text(encoding="utf-8"))
        self.assertEqual(expected, checked)

    def test_64_checked_in_reconciliation_matches_adapter(self) -> None:
        candidate = build_candidate()
        expected = t2.reconcile_with_official(
            candidate, replacement_data_tier=t2.T0, replacement_value="1.910",
            replacement_source_id="TEST-OFFICIAL-PB", replacement_source_hash=OFFICIAL_HASH,
            recorded_at=RECORDED_AT,
        )
        checked = json.loads((CONTRACT_DIR / "fixtures" / "P1008_T2_RECONCILIATION_V1.synthetic.json").read_text(encoding="utf-8"))
        self.assertEqual(expected, checked)


if __name__ == "__main__":
    unittest.main()
