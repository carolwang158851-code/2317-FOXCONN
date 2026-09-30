from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "p1008_derived_kpi_candidate_v1.py"
SPEC = importlib.util.spec_from_file_location("p1008_derived_kpi_candidate_v1", MODULE_PATH)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)

SAMPLE_PATH = ROOT / "contracts" / "p1008_derived_kpi_candidate" / "v1.0" / "P1008_DERIVED_KPI_CANDIDATE_V1.sample.json"
POLICY_PATH = ROOT / "contracts" / "p1008_derived_kpi_candidate" / "v1.0" / "P1008_DERIVED_KPI_CONSUMER_POLICY_V1.json"

EXPECTED_PROTECTED_HASHES = {
    "data/2317_master_v9.csv": "E623CA082F2A080613C33F4155BA8006646E30D6A517DE926AF6108062F84D48",
    "data/2317_daily_price.csv": "E39E364C528F353E350A6591C0C55EE55EA2FF862958B157860BD98EC98BA368",
    "data/2317_daily_market_activity.csv": "3E4D7B55446D6B167FE1BC1B0B44419A95EF311E775C14A422EBB67563E9585B",
    "data/2317_cash_flow_authority.csv": "082ECA44A96A06F7DAE10DD33CBAF77C75DABA9B1B4DEA27B5B930F8CE8CD95C",
    "data/macro_snapshot.csv": "7F635FDDD88D4321384DA89C20B2E07C4504A4EB14D25FA98B181994E941202F",
    "data/macro_event_observations.csv": "EBFD5CD6C327557A99803908FE468E16514C2546E36D8D1B2FF928442DFF4565",
    "data/fx_trend_observations.csv": "F629CE510E3881CA0FA61D4A03CC30452B18BA7EB9855A92C1FA23163C1803BC",
    "data/CSV_AUTHORITY_MANIFEST.json": "449EC025AC93CDC034AB4512183BF85BC1F80F38525C57B1782DBB85945ADC9F",
}


def sample() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def valid_t2() -> dict:
    candidate = sample()
    candidate["candidate_id"] = "TEST-ONLY-PB-T2"
    candidate["data_tier"] = validator.T2
    candidate["derivation_method"] = "ESTIMATED_WITH_DECLARED_ASSUMPTIONS"
    candidate["assumptions"] = ["Synthetic fixture assumes the stored BVPS is the applicable period denominator."]
    candidate["assumption_count"] = 1
    candidate["sensitivity_range"] = {
        "low": "1.900", "high": "2.100", "unit": "MULTIPLE", "method": "TEST_ONLY_INPUT_RANGE"
    }
    candidate["confidence"] = "MEDIUM"
    return candidate


class DerivedKpiCandidateContractTests(unittest.TestCase):
    def assert_invalid(self, candidate: dict, phrase: str) -> None:
        errors = validator.validate_candidate(candidate)
        self.assertTrue(errors, "candidate unexpectedly validated")
        self.assertIn(phrase, " | ".join(errors))

    def test_01_t0_direct_remains_preferred(self) -> None:
        result = validator.resolve_required_kpi(
            t0_value="12.34", t1_candidate=sample(), t2_candidate=valid_t2(), t3_evidence_available=True
        )
        self.assertEqual(result.selected_tier, validator.T0)
        self.assertEqual(result.trace, ("CHECK_T0_DIRECT_OFFICIAL",))

    def test_02_missing_t0_triggers_derivability_check(self) -> None:
        result = validator.resolve_required_kpi(
            t0_value=None, t1_candidate=sample(), t2_candidate=None, t3_evidence_available=False
        )
        self.assertEqual(result.selected_tier, validator.T1)
        self.assertIn("CHECK_T1_EXACT_DERIVABILITY", result.trace)

    def test_03_valid_t1_derivation_is_accepted_as_candidate(self) -> None:
        self.assertEqual(validator.validate_candidate(sample()), [])
        result = validator.resolve_required_kpi(
            t0_value=None, t1_candidate=sample(), t2_candidate=None, t3_evidence_available=False
        )
        self.assertEqual(result.status, "CANDIDATE_READY")

    def test_04_t1_requires_all_input_hashes(self) -> None:
        candidate = sample()
        candidate["input_hashes"][0] = ""
        self.assert_invalid(candidate, "input_hashes[0]")

    def test_05_t1_rejects_period_mismatch(self) -> None:
        candidate = sample()
        candidate["input_periods"][1] = "2026-06-30"
        self.assert_invalid(candidate, "input period mismatch")

    def test_06_t1_rejects_unit_mismatch(self) -> None:
        candidate = sample()
        candidate["input_units"][1] = "TWD_TOTAL"
        self.assert_invalid(candidate, "unit mismatch")

    def test_07_t1_rejects_denominator_ambiguity(self) -> None:
        candidate = sample()
        candidate["denominator_definition"] = "N/A"
        self.assert_invalid(candidate, "denominator_definition")

    def test_08_t2_requires_assumptions(self) -> None:
        candidate = valid_t2()
        candidate["assumptions"] = []
        candidate["assumption_count"] = 0
        self.assert_invalid(candidate, "T2 requires at least one explicit assumption")

    def test_09_t2_cannot_label_itself_t1(self) -> None:
        candidate = valid_t2()
        candidate["data_tier"] = validator.T1
        self.assert_invalid(candidate, "T1 cannot use an estimated derivation method")

    def test_10_t3_cannot_overwrite_t0_or_t1(self) -> None:
        direct = validator.resolve_required_kpi(
            t0_value="1", t1_candidate=sample(), t2_candidate=None, t3_evidence_available=True
        )
        self.assertEqual(direct.selected_tier, validator.T0)
        candidate = sample()
        candidate["data_tier"] = validator.T3
        self.assert_invalid(candidate, "T3/T4 cannot impersonate")

    def test_11_qualitative_evidence_cannot_become_numeric_kpi(self) -> None:
        self.assertFalse(validator.evidence_can_be_numeric_candidate(
            source_semantic="AI_INFRASTRUCTURE_OUTLOOK",
            target_semantic="AI_INFRASTRUCTURE_OUTLOOK",
            evidence_kind="QUALITATIVE",
        ))

    def test_12_cloud_networking_share_cannot_become_ai_revenue_share(self) -> None:
        self.assertFalse(validator.evidence_can_be_numeric_candidate(
            source_semantic="CLOUD_AND_NETWORKING_REVENUE_SHARE",
            target_semantic="AI_REVENUE_SHARE",
            evidence_kind="DIRECT_NUMERIC",
        ))

    def test_13_event_count_cannot_become_ai_kpi(self) -> None:
        self.assertFalse(validator.evidence_can_be_numeric_candidate(
            source_semantic="AI_EVENT_COUNT",
            target_semantic="AI_INFRASTRUCTURE_DEMAND_EXPOSURE",
            evidence_kind="NEWS_EVENT_COUNT",
        ))

    def test_14_exhausted_derivability_ends_in_null(self) -> None:
        result = validator.resolve_required_kpi(
            t0_value=None, t1_candidate=None, t2_candidate=None, t3_evidence_available=True
        )
        self.assertEqual(result.status, validator.DATA_MISSING)
        self.assertEqual(result.trace[-1], validator.DATA_MISSING)

    def test_15_candidate_validation_cannot_modify_formal_csv(self) -> None:
        before = validator.protected_hashes(ROOT)
        validator.validate_or_raise(sample())
        after = validator.protected_hashes(ROOT)
        for path in before:
            if path.endswith("CSV_AUTHORITY_MANIFEST.json"):
                continue
            self.assertEqual(before[path], after[path], path)

    def test_16_candidate_validation_cannot_modify_authority_manifest(self) -> None:
        before = validator.sha256_file(ROOT / "data/CSV_AUTHORITY_MANIFEST.json")
        validator.validate_or_raise(sample())
        after = validator.sha256_file(ROOT / "data/CSV_AUTHORITY_MANIFEST.json")
        self.assertEqual(before, after)

    def test_17_actionable_remains_false(self) -> None:
        candidate = sample()
        candidate["actionable"] = True
        self.assert_invalid(candidate, "actionable must be false")

    def test_18_production_scoring_remains_disabled(self) -> None:
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        self.assertFalse(policy["production_scoring_enabled"])
        candidate = sample()
        candidate["production_scoring_enabled"] = True
        self.assert_invalid(candidate, "production scoring must remain disabled")

    def test_19_current_formal_authority_hashes_remain_unchanged(self) -> None:
        self.assertEqual(validator.protected_hashes(ROOT), EXPECTED_PROTECTED_HASHES)

    def test_20_deterministic_recomputation_reproduces_t1_value(self) -> None:
        self.assertEqual(validator.recompute(sample()), Decimal("2.000"))

    def test_21_missing_formula_id_is_rejected(self) -> None:
        candidate = sample()
        del candidate["formula_id"]
        self.assert_invalid(candidate, "missing required field: formula_id")

    def test_22_missing_input_lineage_is_rejected(self) -> None:
        candidate = sample()
        candidate["input_source_ids"] = []
        self.assert_invalid(candidate, "input lineage arrays")

    def test_23_semantic_mismatch_is_rejected(self) -> None:
        candidate = sample()
        candidate["semantic_match_status"] = "MISMATCH"
        self.assert_invalid(candidate, "semantic mismatch")

    def test_24_proxy_relabel_is_rejected(self) -> None:
        candidate = sample()
        candidate["proxy_metric_used"] = True
        candidate["proxy_relabelled_as_direct"] = True
        self.assert_invalid(candidate, "proxy metric relabeling")

    def test_25_non_finite_value_is_rejected(self) -> None:
        candidate = sample()
        candidate["value"] = float("nan")
        self.assert_invalid(candidate, "value must be finite")

    def test_26_publication_true_without_owner_authorization_is_rejected(self) -> None:
        candidate = sample()
        candidate["publication"] = True
        self.assert_invalid(candidate, "publication=true requires explicit Owner authorization")

    def test_27_undeclared_assumption_is_rejected(self) -> None:
        candidate = valid_t2()
        candidate["assumption_count"] = 0
        self.assert_invalid(candidate, "assumption_count")

    def test_28_valid_t2_is_research_candidate_only(self) -> None:
        candidate = valid_t2()
        self.assertEqual(validator.validate_candidate(candidate), [])
        result = validator.resolve_required_kpi(
            t0_value=None, t1_candidate=None, t2_candidate=candidate, t3_evidence_available=False
        )
        self.assertEqual(result.status, "RESEARCH_CANDIDATE_ONLY")
        self.assertEqual(result.selected_tier, validator.T2)

    def test_29_t2_cannot_claim_high_confidence(self) -> None:
        candidate = valid_t2()
        candidate["confidence"] = "HIGH"
        self.assert_invalid(candidate, "T2 confidence must be lower")

    def test_30_formula_expression_must_bind_both_inputs(self) -> None:
        candidate = sample()
        candidate["formula_expression"] = "TEST_CLOSE_TWD / UNKNOWN"
        self.assert_invalid(candidate, "formula_expression does not bind both")

    def test_31_misaligned_input_arrays_fail_closed_without_exception(self) -> None:
        candidate = sample()
        candidate["input_units"] = []
        self.assert_invalid(candidate, "input lineage arrays")


if __name__ == "__main__":
    unittest.main()
