from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import mock_open, patch


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from p1008_derived_kpi_candidate_v1 import validate_candidate  # noqa: E402
from p1008_t1_derived_kpi_bridge_v1 import (  # noqa: E402
    ADAPTER_VERSION,
    ROIC_AVAILABLE_INPUTS,
    T1BridgeError,
    adapt_t1_candidate,
    canonical_json_bytes,
    domain_route,
    roic_bridge_status,
    sha256_bytes,
    validate_t1_eligibility,
    write_bundle,
)


FIXTURE = (
    ROOT
    / "contracts"
    / "p1008_derived_kpi_candidate"
    / "v1.0"
    / "P1008_DERIVED_KPI_CANDIDATE_V1.sample.json"
)
CREATED_AT = "2026-09-27T00:00:00Z"

BASELINE_HASHES = {
    "data/CSV_AUTHORITY_MANIFEST.json": "4306D225FDFF0F48AEDEA6C758E7B76EAA5F9FB7735C9FFDB5E9823D75FE465F",
    "data/2317_master_v9.csv": "E623CA082F2A080613C33F4155BA8006646E30D6A517DE926AF6108062F84D48",
    "data/2317_cash_flow_authority.csv": "082ECA44A96A06F7DAE10DD33CBAF77C75DABA9B1B4DEA27B5B930F8CE8CD95C",
    "data/2317_daily_price.csv": "91EEBDB6BC6FD0E85CA2BF537056CAF941246F13412417EDFAE96B16D6DD02D1",
    "data/2317_daily_market_activity.csv": "747D4C3BFA40C239B9E2EBB4F39D695F88F186020D19DE310B57CD3D8D432F01",
    "data/macro_snapshot.csv": "6BD02B0894139D00D881FF53A6EEEEED404DED21EC782CF54F716665EB25123B",
    "data/macro_event_observations.csv": "4A8E1D8079D9E1F9F210222C5383DD69AF17B2F731A2AA5D38485BC07277A64F",
    "data/fx_trend_observations.csv": "4F16E86F09F5B9594407084081C81E4D95853DDD30EA3C24B9D9815AAB0F02E6",
    "launcher.html": "AFC27FE6440A2DEFE446DB4519B586EFA56474B922A3901A84ABA3FF90DF8150",
    "index_p1008_v7.html": "1C10D011BB061FFC43C97877EA3BD8DFD7C24C2DEFF87C4465CD625FB0E7A76D",
    "ui/P1008_WARROOM_COMMAND_CENTER_v24.html": "66711C40B5D053ACEA785A180DA9DFC1EBBDFD98E2DC1B91988B051E75F44163",
    "tools/owner_publish_csv_v2.py": "9FA584A2F76B931CCB2DDBB32B16F112AAC7B7A3CCD4FEC05111C1D57213E8BB",
}


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class T1DerivedKpiBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def changed(self, **changes):
        candidate = copy.deepcopy(self.source)
        candidate.update(changes)
        return candidate

    def assertRejected(self, candidate, fragment: str) -> None:  # noqa: N802
        result = validate_t1_eligibility(candidate)
        self.assertEqual("FAIL", result.status)
        self.assertIn(fragment.lower(), " ".join(result.errors).lower())
        with self.assertRaises(T1BridgeError):
            adapt_t1_candidate(candidate, created_at=CREATED_AT)

    # 1
    def test_valid_synthetic_t1_crosses_bridge(self):
        bundle = adapt_t1_candidate(self.source, created_at=CREATED_AT)
        self.assertTrue(bundle.candidate_id.startswith("WR-T1-"))
        self.assertEqual("PASS", bundle.receipt()["validation_status"])
        self.assertTrue(bundle.envelope()["synthetic_fixture"])

    # 2-4 and unknown
    def test_t2_rejected(self):
        self.assertRejected(self.changed(data_tier="T2_ESTIMATED_DERIVED"), "not bridge-eligible")

    def test_t3_rejected(self):
        self.assertRejected(self.changed(data_tier="T3_EXTERNAL_CROSSCHECK"), "not bridge-eligible")

    def test_t4_rejected(self):
        self.assertRejected(self.changed(data_tier="T4_MODEL_SCENARIO"), "not bridge-eligible")

    def test_unknown_tier_rejected(self):
        self.assertRejected(self.changed(data_tier="T9_UNKNOWN"), "unknown or missing")

    # 5-8 plus source locator and formula expression
    def test_missing_formula_rejected(self):
        candidate = self.changed()
        del candidate["formula_id"]
        self.assertRejected(candidate, "formula_id")

    def test_missing_formula_version_rejected(self):
        self.assertRejected(self.changed(formula_version=""), "formula_version")

    def test_missing_formula_expression_rejected(self):
        self.assertRejected(self.changed(formula_expression=""), "formula_expression")

    def test_missing_source_id_rejected(self):
        self.assertRejected(self.changed(input_source_ids=[]), "source ids")

    def test_missing_source_locator_rejected(self):
        self.assertRejected(self.changed(input_source_locators=[]), "source locators")

    def test_missing_hash_rejected(self):
        self.assertRejected(self.changed(input_hashes=[]), "input hashes")

    # 9-18
    def test_period_mismatch_rejected(self):
        self.assertRejected(self.changed(input_periods=["2026-09-17", "2026-09-18"]), "period mismatch")

    def test_unit_mismatch_rejected(self):
        self.assertRejected(self.changed(input_units=["TWD_PER_SHARE", "USD_PER_SHARE"]), "unit mismatch")

    def test_denominator_ambiguity_rejected(self):
        self.assertRejected(self.changed(denominator_definition="N/A"), "denominator")

    def test_undeclared_assumption_rejected(self):
        self.assertRejected(self.changed(assumptions=["estimated input"], assumption_count=1), "assumption")

    def test_recomputation_mismatch_rejected(self):
        self.assertRejected(self.changed(value="2.001"), "recomputation mismatch")

    def test_proxy_substitution_rejected(self):
        self.assertRejected(self.changed(proxy_metric_used=True), "proxy")

    def test_carry_forward_rejected(self):
        candidate = self.changed()
        candidate["derivation_trace"].append("PREVIOUS_PERIOD_CARRY")
        self.assertRejected(candidate, "carry")

    def test_silent_imputation_rejected(self):
        candidate = self.changed()
        candidate["derivation_trace"].append("SILENT_FILL")
        self.assertRejected(candidate, "silent_fill")

    def test_semantic_mismatch_rejected(self):
        self.assertRejected(self.changed(semantic_match_status="MISMATCH"), "semantic")

    def test_actionable_true_rejected(self):
        self.assertRejected(self.changed(actionable=True), "actionable")

    def test_publication_true_rejected(self):
        self.assertRejected(self.changed(publication=True), "publication")

    def test_t2_ancestry_rejected(self):
        self.assertRejected(
            self.changed(input_source_tiers=["T0_DIRECT_OFFICIAL", "T2_ESTIMATED_DERIVED"]),
            "ancestry",
        )

    def test_input_contract_extension_rejected(self):
        self.assertRejected(self.changed(candidate_owner="PLUGIN"), "unsupported fields")

    # 19-21
    def test_incomplete_roic_remains_data_gap(self):
        status = roic_bridge_status(ROIC_AVAILABLE_INPUTS)
        self.assertEqual("DATA_GAP", status["ROIC_CURRENT_STATUS"])
        self.assertFalse(status["candidate_allowed"])
        self.assertIn("InterestBearingDebt_100M", status["ROIC_MISSING_INPUTS"])

    def test_missing_twse_positioning_does_not_trigger_substitute(self):
        self.assertEqual("RAW_SOURCE_REMEDIATION_REQUIRED", domain_route("POSITIONING"))

    def test_direct_macro_observation_is_not_rederived(self):
        self.assertEqual(
            "DIRECT_OBSERVATION_USE_REQUIRED",
            domain_route("MACRO", direct_observation_exists=True),
        )

    def test_industry_ai_real_candidate_not_fabricated(self):
        self.assertEqual("NO_ELIGIBLE_CURRENT_NUMERIC_KPI", domain_route("INDUSTRY_AI"))

    # 22-23 and 28
    def test_owner_changes_plugin_to_war_room_only_through_adapter(self):
        self.assertNotIn("candidate_owner", self.source)
        envelope = adapt_t1_candidate(self.source, created_at=CREATED_AT).envelope()
        self.assertEqual("WAR_ROOM", envelope["candidate_owner"])
        self.assertEqual("PLUGIN_DERIVED_T1", envelope["origin"])

    def test_formal_authority_remains_false(self):
        envelope = adapt_t1_candidate(self.source, created_at=CREATED_AT).envelope()
        self.assertFalse(envelope["formal_authority"])

    def test_scoring_remains_disabled(self):
        envelope = adapt_t1_candidate(self.source, created_at=CREATED_AT).envelope()
        self.assertFalse(envelope["production_scoring_enabled"])

    def test_output_is_owner_review_only(self):
        envelope = adapt_t1_candidate(self.source, created_at=CREATED_AT).envelope()
        self.assertTrue(envelope["owner_review_required"])
        self.assertFalse(envelope["actionable"])
        self.assertFalse(envelope["publication"])

    # 24-27: immutable baseline hashes include formal CSV, manifest, Launcher and UI.
    def test_formal_csv_files_unchanged(self):
        for rel in (
            "data/2317_master_v9.csv",
            "data/2317_cash_flow_authority.csv",
            "data/2317_daily_price.csv",
            "data/2317_daily_market_activity.csv",
            "data/macro_snapshot.csv",
            "data/macro_event_observations.csv",
            "data/fx_trend_observations.csv",
        ):
            self.assertEqual(BASELINE_HASHES[rel], file_sha(ROOT / rel), rel)

    def test_csv_authority_manifest_unchanged(self):
        rel = "data/CSV_AUTHORITY_MANIFEST.json"
        self.assertEqual(BASELINE_HASHES[rel], file_sha(ROOT / rel))

    def test_launcher_unchanged(self):
        rel = "launcher.html"
        self.assertEqual(BASELINE_HASHES[rel], file_sha(ROOT / rel))

    def test_ui_entrypoints_unchanged(self):
        for rel in ("index_p1008_v7.html", "ui/P1008_WARROOM_COMMAND_CENTER_v24.html"):
            self.assertEqual(BASELINE_HASHES[rel], file_sha(ROOT / rel), rel)

    def test_formal_publisher_unchanged(self):
        rel = "tools/owner_publish_csv_v2.py"
        self.assertEqual(BASELINE_HASHES[rel], file_sha(ROOT / rel))

    # 29
    def test_completed_input_contract_focused_regression_passes(self):
        self.assertEqual([], validate_candidate(self.source))

    # 30 and component-level deterministic/provenance checks.
    def test_hash_proof_deterministic(self):
        first = adapt_t1_candidate(self.source, created_at=CREATED_AT)
        second = adapt_t1_candidate(copy.deepcopy(self.source), created_at=CREATED_AT)
        self.assertEqual(first, second)

    def test_source_candidate_hash_binds_canonical_input(self):
        bundle = adapt_t1_candidate(self.source, created_at=CREATED_AT)
        expected = sha256_bytes(canonical_json_bytes(self.source))
        self.assertEqual(expected, bundle.envelope()["source_candidate_hash"])
        self.assertEqual(expected, bundle.manifest()["source_candidate_sha256"])

    def test_receipt_hash_binds_exact_receipt_bytes(self):
        bundle = adapt_t1_candidate(self.source, created_at=CREATED_AT)
        expected = sha256_bytes(bundle.receipt_bytes)
        self.assertEqual(expected, bundle.envelope()["validation_receipt_hash"])
        self.assertEqual(expected, bundle.manifest()["validation_receipt_sha256"])

    def test_manifest_hash_binds_exact_candidate_bytes(self):
        bundle = adapt_t1_candidate(self.source, created_at=CREATED_AT)
        self.assertEqual(
            sha256_bytes(bundle.envelope_bytes), bundle.manifest()["candidate_sha256"]
        )

    def test_adapter_provenance_is_bound(self):
        bundle = adapt_t1_candidate(self.source, created_at=CREATED_AT)
        self.assertEqual(ADAPTER_VERSION, bundle.envelope()["adapter_version"])
        self.assertRegex(bundle.envelope()["adapter_hash"], r"^[A-F0-9]{64}$")

    def test_emitted_objects_match_declared_schema_field_sets(self):
        bundle = adapt_t1_candidate(self.source, created_at=CREATED_AT)
        contract_root = ROOT / "contracts" / "p1008_t1_derived_kpi_bridge" / "v1.0"
        pairs = (
            ("P1008_T1_WAR_ROOM_CANDIDATE_V1.schema.json", bundle.envelope()),
            ("P1008_T1_VALIDATION_RECEIPT_V1.schema.json", bundle.receipt()),
            ("P1008_T1_BRIDGE_MANIFEST_V1.schema.json", bundle.manifest()),
        )
        for filename, payload in pairs:
            schema = json.loads((contract_root / filename).read_text(encoding="utf-8"))
            self.assertFalse(schema["additionalProperties"], filename)
            self.assertEqual(set(schema["required"]), set(payload), filename)
            self.assertEqual(set(schema["properties"]), set(payload), filename)

    def test_checked_in_synthetic_bundle_matches_deterministic_adapter(self):
        bundle = adapt_t1_candidate(self.source, created_at=CREATED_AT)
        fixture_root = (
            ROOT / "contracts" / "p1008_t1_derived_kpi_bridge" / "v1.0" / "fixtures"
        )
        expected = {
            "P1008_T1_WAR_ROOM_CANDIDATE_V1.synthetic.json": bundle.envelope_bytes,
            "P1008_T1_VALIDATION_RECEIPT_V1.synthetic.json": bundle.receipt_bytes,
            "P1008_T1_BRIDGE_MANIFEST_V1.synthetic.json": bundle.manifest_bytes,
        }
        for filename, payload in expected.items():
            self.assertEqual(payload, (fixture_root / filename).read_bytes(), filename)

    def test_bundle_dataclass_is_frozen(self):
        bundle = adapt_t1_candidate(self.source, created_at=CREATED_AT)
        with self.assertRaises(FrozenInstanceError):
            bundle.candidate_id = "changed"

    def test_invalid_created_at_rejected(self):
        with self.assertRaisesRegex(T1BridgeError, "created_at"):
            adapt_t1_candidate(self.source, created_at="2026-09-27")

    def test_writer_refuses_formal_data_destination(self):
        bundle = adapt_t1_candidate(self.source, created_at=CREATED_AT)
        with self.assertRaisesRegex(T1BridgeError, "isolated staging root"):
            write_bundle(bundle, output_root=ROOT / "data", repository_root=ROOT)

    def test_writer_is_once_only_for_immutable_identity(self):
        bundle = adapt_t1_candidate(self.source, created_at=CREATED_AT)
        output_root = ROOT / "staging" / "t1_derived_kpi_candidates"
        with patch("pathlib.Path.mkdir") as mkdir, patch(
            "pathlib.Path.open", mock_open()
        ) as opened:
            paths = write_bundle(bundle, output_root=output_root, repository_root=ROOT)
            mkdir.assert_called_once_with(parents=True, exist_ok=False)
            self.assertEqual(3, opened.call_count)
            self.assertEqual(3, len(paths))
        with patch("pathlib.Path.mkdir", side_effect=FileExistsError):
            with self.assertRaises(FileExistsError):
                write_bundle(bundle, output_root=output_root, repository_root=ROOT)


if __name__ == "__main__":
    unittest.main()
