from __future__ import annotations

import copy
import contextlib
import hashlib
import json
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import p1008_kpi_supplement_v1 as supplement
import p1008_t2_annotated_use_v1 as t2


T1_FIXTURE = ROOT / "contracts/p1008_derived_kpi_candidate/v1.0/P1008_DERIVED_KPI_CANDIDATE_V1.sample.json"
T2_FIXTURE = ROOT / "contracts/p1008_t2_annotated_use/v1.0/fixtures/P1008_T2_RESEARCH_CANDIDATE_V1.synthetic.json"
T2_APPROVAL = ROOT / "contracts/p1008_t2_annotated_use/v1.0/fixtures/P1008_T2_ANNOTATED_USE_APPROVAL_V1.synthetic.json"
H = "A" * 64


@contextlib.contextmanager
def workspace_tempdir():
    path = ROOT / "tests" / f".tmp-kpi-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield str(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def request_t1(**changes) -> supplement.KPIRequest:
    values = {
        "metric_id": "TEST_PB_MULTIPLE",
        "semantic_name": "PRICE_TO_BOOK_MULTIPLE",
        "period": "2026-09-18",
        "as_of_date": "2026-09-18",
        "unit": "MULTIPLE",
    }
    values.update(changes)
    return supplement.KPIRequest(**values)


def t0(**changes) -> dict:
    value = {
        "metric_id": "TEST_PB_MULTIPLE",
        "semantic_name": "PRICE_TO_BOOK_MULTIPLE",
        "period": "2026-09-18",
        "as_of_date": "2026-09-18",
        "source_effective_date": "2026-09-18",
        "value": "1.999",
        "unit": "MULTIPLE",
        "data_tier": supplement.T0,
        "validation_status": "PASS",
        "formal_authority": True,
        "source_ids": ["OFFICIAL"],
        "source_hashes": [H],
    }
    value.update(changes)
    return value


def t1_record(**changes) -> dict:
    candidate = load(T1_FIXTURE)
    value = {
        "schema_version": supplement.SCHEMA_VERSION,
        "candidate_id": candidate["candidate_id"],
        "candidate_hash": supplement._hash_object(candidate),
        "metric_id": candidate["metric_id"],
        "semantic_name": candidate["semantic_name"],
        "period": candidate["period"],
        "as_of_date": candidate["as_of_date"],
        "source_effective_date": candidate["as_of_date"],
        "value": candidate["value"],
        "unit": candidate["unit"],
        "data_tier": supplement.T1,
        "formula_id": candidate["formula_id"],
        "formula_version": candidate["formula_version"],
        "source_ids": candidate["input_source_ids"],
        "source_hashes": candidate["input_hashes"],
        "confidence": candidate["confidence"],
        "assumptions": [],
        "limitations": [],
        "range": None,
        "owner_approval_identity": None,
        "owner_approved_for_annotated_use": False,
        "validation_status": "PASS",
        "status": "ACTIVE",
        "created_at": "2026-09-18T10:00:00Z",
        "source_candidate": candidate,
        "owner_approval": None,
        "formal_authority": False,
        "formal_scoring_eligible": False,
        "actionable": False,
    }
    value.update(changes)
    return value


def request_t2(**changes) -> supplement.KPIRequest:
    values = {
        "metric_id": "TEST_ESTIMATED_PB_MULTIPLE",
        "semantic_name": "PRICE_TO_BOOK_MULTIPLE",
        "period": "2026-09-18",
        "as_of_date": "2026-09-18",
        "unit": "MULTIPLE",
    }
    values.update(changes)
    return supplement.KPIRequest(**values)


def t2_record(**changes) -> dict:
    candidate = load(T2_FIXTURE)
    approval = load(T2_APPROVAL)
    value = {
        "schema_version": supplement.SCHEMA_VERSION,
        "candidate_id": candidate["candidate_id"],
        "candidate_hash": supplement._hash_object(candidate),
        "metric_id": candidate["metric_id"],
        "semantic_name": candidate["semantic_name"],
        "period": candidate["period"],
        "as_of_date": candidate["as_of_date"],
        "source_effective_date": candidate["as_of_date"],
        "value": candidate["point_estimate"],
        "unit": candidate["unit"],
        "data_tier": supplement.T2,
        "formula_id": candidate["formula_id"],
        "formula_version": candidate["formula_version"],
        "source_ids": candidate["input_source_ids"],
        "source_hashes": candidate["input_hashes"],
        "confidence": candidate["confidence"],
        "assumptions": candidate["assumptions"],
        "limitations": candidate["limitations"],
        "range": {"lower": candidate["estimate_lower_bound"], "upper": candidate["estimate_upper_bound"]},
        "owner_approval_identity": approval["approval_id"],
        "owner_approved_for_annotated_use": True,
        "validation_status": "PASS",
        "status": "ACTIVE",
        "created_at": "2026-09-18T10:00:00Z",
        "source_candidate": candidate,
        "owner_approval": approval,
        "formal_authority": False,
        "formal_scoring_eligible": False,
        "actionable": False,
    }
    value.update(changes)
    return value


class ResolverPriorityTests(unittest.TestCase):
    def test_01_t0_wins_over_t1(self):
        got = supplement.resolve_kpi(request_t1(), t0_candidates=[t0()], supplement_records=[t1_record()])
        self.assertEqual(supplement.T0, got.resolved_tier)
        self.assertEqual("1.999", got.value)

    def test_02_t0_wins_over_t2(self):
        direct = t0(metric_id="TEST_ESTIMATED_PB_MULTIPLE", value="1.901")
        got = supplement.resolve_kpi(request_t2(), t0_candidates=[direct], supplement_records=[t2_record()])
        self.assertEqual(supplement.T0, got.resolved_tier)

    def test_03_t1_used_when_t0_absent(self):
        self.assertEqual(supplement.T1, supplement.resolve_kpi(request_t1(), supplement_records=[t1_record()]).resolved_tier)

    def test_04_approved_t2_used_when_t0_t1_absent(self):
        self.assertEqual(supplement.T2, supplement.resolve_kpi(request_t2(), supplement_records=[t2_record()]).resolved_tier)

    def test_05_unapproved_t2_rejected(self):
        record = t2_record(owner_approved_for_annotated_use=False)
        self.assertEqual(supplement.DATA_MISSING, supplement.resolve_kpi(request_t2(), supplement_records=[record]).resolved_tier)

    def test_06_t3_rejected(self):
        self.assertEqual(supplement.DATA_MISSING, supplement.resolve_kpi(request_t1(), supplement_records=[t1_record(data_tier=supplement.T3)]).resolved_tier)

    def test_07_t4_rejected(self):
        self.assertEqual(supplement.DATA_MISSING, supplement.resolve_kpi(request_t1(), supplement_records=[t1_record(data_tier=supplement.T4)]).resolved_tier)

    def test_08_stale_t1_rejected(self):
        self.assertEqual(supplement.DATA_MISSING, supplement.resolve_kpi(request_t1(period="2026-09-19", as_of_date="2026-09-19"), supplement_records=[t1_record()]).resolved_tier)

    def test_09_stale_t2_rejected(self):
        self.assertEqual(supplement.DATA_MISSING, supplement.resolve_kpi(request_t2(period="2026-09-19", as_of_date="2026-09-19"), supplement_records=[t2_record()]).resolved_tier)

    def test_10_wrong_period_rejected(self):
        self.assertIn("wrong/stale period", " ".join(supplement.resolve_kpi(request_t1(period="2026Q3"), supplement_records=[t1_record()]).block_reasons))

    def test_11_future_dated_t1_rejected(self):
        record = t1_record(as_of_date="2026-09-19", source_effective_date="2026-09-19")
        self.assertEqual(supplement.DATA_MISSING, supplement.resolve_kpi(request_t1(), supplement_records=[record]).resolved_tier)

    def test_12_future_dated_t2_rejected(self):
        record = t2_record(as_of_date="2026-09-19", source_effective_date="2026-09-19")
        self.assertEqual(supplement.DATA_MISSING, supplement.resolve_kpi(request_t2(), supplement_records=[record]).resolved_tier)

    def test_13_t1_recomputation_failure_rejected(self):
        record = t1_record()
        record["source_candidate"]["value"] = "2.001"
        record["value"] = "2.001"
        record["candidate_hash"] = supplement._hash_object(record["source_candidate"])
        got = supplement.resolve_kpi(request_t1(), supplement_records=[record])
        self.assertIn("recomputation", " ".join(got.block_reasons).lower())

    def test_14_t2_candidate_hash_mismatch_rejected(self):
        got = supplement.resolve_kpi(request_t2(), supplement_records=[t2_record(candidate_hash=H)])
        self.assertIn("candidate-hash mismatch", " ".join(got.block_reasons))

    def test_15_t2_approval_hash_mismatch_rejected(self):
        record = t2_record()
        record["owner_approval"]["candidate_hash"] = H
        got = supplement.resolve_kpi(request_t2(), supplement_records=[record])
        self.assertIn("approval", " ".join(got.block_reasons).lower())

    def test_16_semantic_substitution_rejected(self):
        record = t1_record(semantic_name="CLOUD_NETWORKING_SHARE")
        got = supplement.resolve_kpi(request_t1(), supplement_records=[record])
        self.assertIn("semantic substitution", " ".join(got.block_reasons))

    def test_17_proxy_substitution_rejected(self):
        record = t1_record()
        record["source_candidate"]["proxy_metric_used"] = True
        record["candidate_hash"] = supplement._hash_object(record["source_candidate"])
        got = supplement.resolve_kpi(request_t1(), supplement_records=[record])
        self.assertIn("proxy", " ".join(got.block_reasons).lower())

    def test_18_carry_forward_rejected(self):
        record = t1_record()
        record["source_candidate"]["derivation_trace"].append("CARRY_FORWARD")
        record["candidate_hash"] = supplement._hash_object(record["source_candidate"])
        got = supplement.resolve_kpi(request_t1(), supplement_records=[record])
        self.assertIn("carry", " ".join(got.block_reasons).lower())

    def test_19_default_fill_rejected(self):
        record = t1_record()
        record["source_candidate"]["derivation_trace"].append("DEFAULT_FILL")
        record["candidate_hash"] = supplement._hash_object(record["source_candidate"])
        got = supplement.resolve_kpi(request_t1(), supplement_records=[record])
        self.assertIn("default_fill", " ".join(got.block_reasons).lower())

    def test_20_null_when_no_value(self):
        got = supplement.resolve_kpi(request_t1())
        self.assertIsNone(got.value)
        self.assertEqual("DATA_MISSING", got.display_status)


class DisplayAndBoundaryTests(unittest.TestCase):
    def test_21_t1_annotation(self):
        self.assertEqual("精確推導", supplement.resolve_kpi(request_t1(), supplement_records=[t1_record()]).annotation_zh)

    def test_22_t2_annotation(self):
        self.assertEqual("推估", supplement.resolve_kpi(request_t2(), supplement_records=[t2_record()]).annotation_zh)

    def test_23_t2_confidence_preserved(self):
        self.assertEqual("MEDIUM", supplement.resolve_kpi(request_t2(), supplement_records=[t2_record()]).confidence)

    def test_24_t2_range_preserved(self):
        got = supplement.resolve_kpi(request_t2(), supplement_records=[t2_record()])
        self.assertEqual(("1.800", "2.050"), (got.range_lower, got.range_upper))

    def test_25_later_t0_supersedes_t1(self):
        first = supplement.resolve_kpi(request_t1(), supplement_records=[t1_record()])
        second = supplement.resolve_kpi(request_t1(), t0_candidates=[t0()], supplement_records=[t1_record()])
        self.assertEqual((supplement.T1, supplement.T0), (first.resolved_tier, second.resolved_tier))

    def test_26_later_t0_supersedes_t2(self):
        direct = t0(metric_id="TEST_ESTIMATED_PB_MULTIPLE")
        first = supplement.resolve_kpi(request_t2(), supplement_records=[t2_record()])
        second = supplement.resolve_kpi(request_t2(), t0_candidates=[direct], supplement_records=[t2_record()])
        self.assertEqual((supplement.T2, supplement.T0), (first.resolved_tier, second.resolved_tier))

    def test_27_t1_lineage_retained_after_supersession(self):
        got = supplement.resolve_kpi(request_t1(), t0_candidates=[t0()], supplement_records=[t1_record()])
        self.assertEqual(supplement.T1, got.eligible_lineage[0]["data_tier"])

    def test_28_t2_lineage_retained_after_supersession(self):
        direct = t0(metric_id="TEST_ESTIMATED_PB_MULTIPLE")
        got = supplement.resolve_kpi(request_t2(), t0_candidates=[direct], supplement_records=[t2_record()])
        self.assertEqual(supplement.T2, got.eligible_lineage[0]["data_tier"])

    def test_29_plugin_failure_falls_open_to_t0(self):
        with patch.object(supplement.SupplementStore, "load_all", side_effect=OSError("offline")):
            got = supplement.resolve_from_store(ROOT, request_t1(), t0_candidates=[t0()])
        self.assertEqual(supplement.T0, got.resolved_tier)

    def test_30_plugin_failure_falls_open_to_null(self):
        with patch.object(supplement.SupplementStore, "load_all", side_effect=OSError("offline")):
            got = supplement.resolve_from_store(ROOT, request_t1())
        self.assertEqual(supplement.DATA_MISSING, got.resolved_tier)

    def test_31_scoring_always_false(self):
        for got in (
            supplement.resolve_kpi(request_t1(), supplement_records=[t1_record()]),
            supplement.resolve_kpi(request_t2(), supplement_records=[t2_record()]),
        ):
            self.assertFalse(got.formal_scoring_eligible)
            self.assertFalse(got.actionable)

    def test_32_report_renders_t1_label(self):
        text = supplement.render_report_rows([supplement.resolve_kpi(request_t1(), supplement_records=[t1_record()])])
        self.assertIn("精確推導", text)

    def test_33_report_renders_t2_confidence_range(self):
        text = supplement.render_report_rows([supplement.resolve_kpi(request_t2(), supplement_records=[t2_record()])])
        self.assertIn("MEDIUM", text)
        self.assertIn("1.800–2.050", text)

    def test_34_unapproved_display_scope_rejected(self):
        got = supplement.resolve_kpi(
            request_t2(display_scope="REPORT_MAIN_TEXT"),
            supplement_records=[t2_record()],
        )
        self.assertEqual(supplement.DATA_MISSING, got.resolved_tier)

    def test_35_formal_authority_true_on_supplement_rejected(self):
        got = supplement.resolve_kpi(request_t1(), supplement_records=[t1_record(formal_authority=True)])
        self.assertEqual(supplement.DATA_MISSING, got.resolved_tier)

    def test_36_actionable_true_rejected(self):
        got = supplement.resolve_kpi(request_t1(), supplement_records=[t1_record(actionable=True)])
        self.assertEqual(supplement.DATA_MISSING, got.resolved_tier)

    def test_37_formal_scoring_true_rejected(self):
        got = supplement.resolve_kpi(request_t1(), supplement_records=[t1_record(formal_scoring_eligible=True)])
        self.assertEqual(supplement.DATA_MISSING, got.resolved_tier)

    def test_38_unit_mismatch_rejected(self):
        got = supplement.resolve_kpi(request_t1(unit="PERCENT"), supplement_records=[t1_record()])
        self.assertEqual(supplement.DATA_MISSING, got.resolved_tier)

    def test_39_exact_period_no_daily_carry(self):
        got = supplement.resolve_kpi(request_t1(period="2026-09-19", as_of_date="2026-09-19"), t0_candidates=[t0()])
        self.assertEqual(supplement.DATA_MISSING, got.resolved_tier)

    def test_40_t0_must_be_valid_formal(self):
        got = supplement.resolve_kpi(request_t1(), t0_candidates=[t0(formal_authority=False)])
        self.assertEqual(supplement.DATA_MISSING, got.resolved_tier)


class StoreAndProtectedArtifactTests(unittest.TestCase):
    def test_41_store_create_once_idempotent(self):
        with workspace_tempdir() as tmp:
            store = supplement.SupplementStore(tmp)
            first = store.put(t1_record())
            second = store.put(t1_record())
            self.assertEqual(first, second)

    def test_42_store_rejects_destructive_overwrite(self):
        with workspace_tempdir() as tmp:
            store = supplement.SupplementStore(tmp)
            record = t1_record()
            store.put(record)
            changed = copy.deepcopy(record)
            changed["confidence"] = "LOW"
            with self.assertRaises(supplement.ImmutableStoreError):
                store.put(changed)

    def test_43_store_corruption_is_non_blocking(self):
        with workspace_tempdir() as tmp:
            store = supplement.SupplementStore(tmp)
            bad = store.root / "bad.json"
            bad.parent.mkdir(parents=True)
            bad.write_text("{bad", encoding="utf-8")
            records, errors = store.load_all()
            self.assertEqual([], records)
            self.assertTrue(errors)

    def test_44_formal_csv_manifest_hash_unchanged(self):
        self.assertEqual("449EC025AC93CDC034AB4512183BF85BC1F80F38525C57B1782DBB85945ADC9F", hashlib.sha256((ROOT / "data/CSV_AUTHORITY_MANIFEST.json").read_bytes()).hexdigest().upper())

    def test_45_master_csv_hash_unchanged(self):
        self.assertEqual("E623CA082F2A080613C33F4155BA8006646E30D6A517DE926AF6108062F84D48", hashlib.sha256((ROOT / "data/2317_master_v9.csv").read_bytes()).hexdigest().upper())

    def test_46_macro_csv_hash_unchanged(self):
        self.assertEqual("7F635FDDD88D4321384DA89C20B2E07C4504A4EB14D25FA98B181994E941202F", hashlib.sha256((ROOT / "data/macro_snapshot.csv").read_bytes()).hexdigest().upper())

    def test_47_publisher_hash_unchanged(self):
        self.assertEqual("9FA584A2F76B931CCB2DDBB32B16F112AAC7B7A3CCD4FEC05111C1D57213E8BB", hashlib.sha256((ROOT / "tools/owner_publish_csv_v2.py").read_bytes()).hexdigest().upper())

    def test_48_scoring_and_ui_hash_unchanged(self):
        self.assertEqual("D722329A1C1F5AE648A150B642D4C4AB29B050C4FEDAAE159DD8C2C4F11F79DE", hashlib.sha256((ROOT / "src/index_p1008_v7.source.html").read_bytes()).hexdigest().upper())

    def test_49_launcher_hash_unchanged(self):
        self.assertEqual("AFC27FE6440A2DEFE446DB4519B586EFA56474B922A3901A84ABA3FF90DF8150", hashlib.sha256((ROOT / "launcher.html").read_bytes()).hexdigest().upper())

    def test_50_formula_registry_hash_unchanged(self):
        # Fixed governed identity uses exact HEAD blob bytes, not checkout EOL.
        expected = "2A6FF32E48608A122A2089588D1C73B56A89E2C48254FCC185B7F0F84C543314"
        path = "contracts/p1008_formula_registry/v1.2/formula_registry.json"
        blob = subprocess.run(
            ["git", "--no-optional-locks", "cat-file", "blob", f"HEAD:{path}"],
            cwd=ROOT, check=True, capture_output=True,
        ).stdout
        self.assertEqual(expected, hashlib.sha256(blob).hexdigest().upper())
        manifest = json.loads((ROOT / "contracts/p1008_formula_registry/v1.2/contract.manifest.json").read_text(encoding="utf-8"))
        pinned = next(item["sha256"] for item in manifest["artifacts"] if item["path"] == "formula_registry.json")
        self.assertEqual(expected, pinned)

    def test_51_report_adapter_rejects_declared_stale_fed_value(self):
        import warroom_periodic_report_v1 as periodic

        record = {
            "metric_id": "FED_RATE",
            "semantic_name": "FED_RATE",
            "period": "2026-09-19",
            "as_of_date": "2026-09-19",
            "source_effective_date": "2026-09-19",
            "unit": "PERCENT",
        }
        data = {
            "macroRows": [{
                "Date": "2026-09-19",
                "Fed_Rate": "3.625",
                "RiskNote": "連線失敗時沿用正式 CSV 最近值。",
            }]
        }
        self.assertIsNone(periodic._formal_t0_candidate(record, package_root=ROOT, data=data))

    def test_52_report_adapter_accepts_exact_current_us10y(self):
        import warroom_periodic_report_v1 as periodic

        record = {
            "metric_id": "US10Y",
            "semantic_name": "US10Y",
            "period": "2026-09-19",
            "as_of_date": "2026-09-19",
            "source_effective_date": "2026-09-19",
            "unit": "PERCENT",
        }
        data = {"macroRows": [{"Date": "2026-09-19", "US_10Y_Yield": "5.002"}]}
        direct = periodic._formal_t0_candidate(record, package_root=ROOT, data=data)
        self.assertEqual(supplement.T0, direct["data_tier"])
        self.assertEqual("5.002", direct["value"])


if __name__ == "__main__":
    unittest.main()
