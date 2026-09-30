from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

import p1008_kpi_supplement_v1 as supplement
from test_p1008_kpi_supplement_v1 import (
    request_t1,
    request_t2,
    t0,
    t1_record,
    t2_record,
    workspace_tempdir,
)


UI_PATH = ROOT / "ui/P1008_WARROOM_COMMAND_CENTER_v24.html"
SERVER_PATH = ROOT / "tools/p1008_app_server.py"
UI_TEXT = UI_PATH.read_text(encoding="utf-8")
SERVER_TEXT = SERVER_PATH.read_text(encoding="utf-8")


def digest(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest().upper()


def contract(resolution: supplement.Resolution, name: str = "Governed metric") -> dict:
    return supplement.resolution_to_ui_contract(
        resolution,
        as_of_date="2026-09-18",
        display_name=name,
    )


def extract_js_function(name: str) -> str:
    start = UI_TEXT.index(f"function {name}(")
    brace = UI_TEXT.index("{", start)
    depth = 0
    for index in range(brace, len(UI_TEXT)):
        if UI_TEXT[index] == "{":
            depth += 1
        elif UI_TEXT[index] == "}":
            depth -= 1
            if depth == 0:
                return UI_TEXT[start:index + 1]
    raise AssertionError(f"unterminated JavaScript function {name}")


def run_ui_binding(rows: list[dict]) -> dict:
    function_source = extract_js_function("applyResolvedKpiProjection")
    script = f"""
const toNumber = (value) => {{
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(String(value).replace(/[%,$x]/g, '').trim());
  return Number.isFinite(parsed) ? parsed : null;
}};
{function_source}
const metrics = {{ us10y: 4.1, vix: 18, dxy: 101, twdUsd: 31, wti: 70,
  aiSpecificShare: null, cloudNetworkSharePct: 41 }};
applyResolvedKpiProjection(metrics, {json.dumps({'metrics': rows}, ensure_ascii=False)});
process.stdout.write(JSON.stringify(metrics));
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


class UiProjectionContractTests(unittest.TestCase):
    def test_01_t0_contract_value(self):
        item = contract(supplement.resolve_kpi(request_t1(), t0_candidates=[t0()]))
        self.assertEqual("1.999", item["resolved_value"])

    def test_02_t0_contract_tier(self):
        item = contract(supplement.resolve_kpi(request_t1(), t0_candidates=[t0()]))
        self.assertEqual(supplement.T0, item["resolved_tier"])

    def test_03_t0_has_no_owner_approval_flag(self):
        item = contract(supplement.resolve_kpi(request_t1(), t0_candidates=[t0()]))
        self.assertFalse(item["owner_approved_for_annotated_use"])

    def test_04_t0_wins_over_t1_in_contract(self):
        got = supplement.resolve_kpi(request_t1(), t0_candidates=[t0()], supplement_records=[t1_record()])
        self.assertEqual(supplement.T0, contract(got)["resolved_tier"])

    def test_05_t0_wins_over_t2_in_contract(self):
        direct = t0(metric_id="TEST_ESTIMATED_PB_MULTIPLE")
        got = supplement.resolve_kpi(request_t2(), t0_candidates=[direct], supplement_records=[t2_record()])
        self.assertEqual(supplement.T0, contract(got)["resolved_tier"])

    def test_06_t1_contract_value(self):
        item = contract(supplement.resolve_kpi(request_t1(), supplement_records=[t1_record()]))
        self.assertEqual("2.000", item["resolved_value"])

    def test_07_t1_label(self):
        item = contract(supplement.resolve_kpi(request_t1(), supplement_records=[t1_record()]))
        self.assertEqual("精確推導", item["display_status"])

    def test_08_t1_provenance_label(self):
        item = contract(supplement.resolve_kpi(request_t1(), supplement_records=[t1_record()]))
        self.assertEqual("精確推導", item["provenance_label"])

    def test_09_t2_contract_value(self):
        item = contract(supplement.resolve_kpi(request_t2(), supplement_records=[t2_record()]))
        self.assertEqual("1.905", item["resolved_value"])

    def test_10_t2_label(self):
        item = contract(supplement.resolve_kpi(request_t2(), supplement_records=[t2_record()]))
        self.assertEqual("推估", item["display_status"])

    def test_11_t2_owner_approval_confirmed(self):
        item = contract(supplement.resolve_kpi(request_t2(), supplement_records=[t2_record()]))
        self.assertTrue(item["owner_approved_for_annotated_use"])

    def test_12_t2_confidence_preserved(self):
        item = contract(supplement.resolve_kpi(request_t2(), supplement_records=[t2_record()]))
        self.assertEqual("MEDIUM", item["confidence"])

    def test_13_t2_lower_bound_preserved(self):
        item = contract(supplement.resolve_kpi(request_t2(), supplement_records=[t2_record()]))
        self.assertEqual("1.800", item["estimate_lower_bound"])

    def test_14_t2_upper_bound_preserved(self):
        item = contract(supplement.resolve_kpi(request_t2(), supplement_records=[t2_record()]))
        self.assertEqual("2.050", item["estimate_upper_bound"])

    def test_15_missing_contract_is_null(self):
        item = contract(supplement.resolve_kpi(request_t1()))
        self.assertIsNone(item["resolved_value"])

    def test_16_missing_contract_status(self):
        item = contract(supplement.resolve_kpi(request_t1()))
        self.assertEqual("DATA_MISSING", item["resolved_tier"])

    def test_17_semantic_display_name_preserved(self):
        item = contract(supplement.resolve_kpi(request_t2(), supplement_records=[t2_record()]), "部分營運投入資本ROIC（推估）")
        self.assertEqual("部分營運投入資本ROIC（推估）", item["display_name"])

    def test_18_projection_is_not_actionable(self):
        self.assertFalse(contract(supplement.resolve_kpi(request_t1()))["actionable"])

    def test_19_projection_is_not_score_eligible(self):
        self.assertFalse(contract(supplement.resolve_kpi(request_t1()))["formal_scoring_eligible"])

    def test_20_as_of_date_preserved(self):
        self.assertEqual("2026-09-18", contract(supplement.resolve_kpi(request_t1()))["as_of_date"])


class BrowserConsumerTests(unittest.TestCase):
    def item(self, metric_id: str, tier: str, value: str | None, approved: bool = False) -> dict:
        return {
            "metric_id": metric_id,
            "display_name": metric_id,
            "period": "2026-09-18",
            "resolved_value": value,
            "unit": "PERCENT",
            "resolved_tier": tier,
            "display_status": "推估" if tier == supplement.T2 else "精確推導",
            "provenance_label": "test",
            "confidence": "MEDIUM",
            "estimate_lower_bound": "3.0",
            "estimate_upper_bound": "5.0",
            "owner_approved_for_annotated_use": approved,
            "as_of_date": "2026-09-18",
        }

    def test_21_t0_updates_existing_metric(self):
        got = run_ui_binding([self.item("US10Y", supplement.T0, "4.25")])
        self.assertEqual(4.25, got["us10y"])

    def test_22_t1_updates_existing_metric(self):
        got = run_ui_binding([self.item("VIX", supplement.T1, "19.5")])
        self.assertEqual(19.5, got["vix"])

    def test_23_approved_t2_updates_existing_metric(self):
        got = run_ui_binding([self.item("DXY", supplement.T2, "102.4", True)])
        self.assertEqual(102.4, got["dxy"])

    def test_24_unapproved_t2_does_not_update(self):
        got = run_ui_binding([self.item("DXY", supplement.T2, "102.4", False)])
        self.assertEqual(101, got["dxy"])

    def test_25_data_missing_does_not_fill(self):
        got = run_ui_binding([self.item("TWD_USD", supplement.DATA_MISSING, None)])
        self.assertEqual(31, got["twdUsd"])

    def test_26_invalid_number_does_not_fill(self):
        got = run_ui_binding([self.item("WTI", supplement.T1, "not-a-number")])
        self.assertEqual(70, got["wti"])

    def test_27_absent_projection_is_fail_open(self):
        got = run_ui_binding([])
        self.assertEqual(4.1, got["us10y"])

    def test_28_cloud_share_maps_only_to_cloud_field(self):
        got = run_ui_binding([self.item("CLOUD_NETWORKING_SHARE", supplement.T1, "47")])
        self.assertEqual(47, got["cloudNetworkSharePct"])
        self.assertIsNone(got["aiSpecificShare"])

    def test_29_direct_ai_maps_only_to_ai_field(self):
        got = run_ui_binding([self.item("FOXCONN_AI_REVENUE_SHARE", supplement.T1, "12")])
        self.assertEqual(12, got["aiSpecificShare"])
        self.assertEqual(41, got["cloudNetworkSharePct"])

    def test_30_partial_roic_is_not_renamed_or_mapped(self):
        got = run_ui_binding([self.item("PARTIAL_OPERATING_INVESTED_CAPITAL_ROIC", supplement.T2, "8", True)])
        self.assertNotIn("roic", got)

    def test_31_browser_has_no_resolver_call(self):
        self.assertNotIn("resolve_kpi", extract_js_function("applyResolvedKpiProjection"))

    def test_32_browser_has_no_tier_precedence_sort(self):
        source = extract_js_function("applyResolvedKpiProjection")
        self.assertNotIn("sort(", source)
        self.assertNotIn("T0_DIRECT_OFFICIAL >", source)

    def test_33_t1_annotation_uses_existing_status_field(self):
        self.assertIn("supplementStatus(metrics", UI_TEXT)
        self.assertIn("display_status", UI_TEXT)

    def test_34_t2_detail_uses_existing_note_field(self):
        self.assertIn("estimate_lower_bound", extract_js_function("supplementDetail"))
        self.assertIn("confidence", extract_js_function("supplementDetail"))

    def test_35_no_new_kpi_card_markup(self):
        self.assertNotIn("kpi-supplement-card", UI_TEXT)

    def test_36_existing_signal_count_remains_seven(self):
        renderer = extract_js_function("renderRightPanel")
        self.assertEqual(7, renderer.count("{ id:"))

    def test_37_app_state_prefers_existing_status_route(self):
        self.assertIn('fetchJson("api/p1008/status")', extract_js_function("fetchAppState"))

    def test_38_app_state_retains_runtime_fallback(self):
        self.assertIn('fetchJson("runtime/p1008_app_state.json")', extract_js_function("fetchAppState"))

    def test_39_scoring_functions_do_not_reference_supplements(self):
        start = UI_TEXT.index("const applyIcTones =")
        end = UI_TEXT.index("const formatDateTime =", start)
        self.assertNotIn("resolvedSupplements", UI_TEXT[start:end])

    def test_40_binding_occurs_after_system_assembly(self):
        assembly = UI_TEXT.index("const state = buildSystems(")
        binding = UI_TEXT.index("applyResolvedKpiProjection(state.metrics")
        scoring = UI_TEXT.index("applyIcTones(state.systems)", binding)
        self.assertLess(assembly, binding)
        self.assertLess(binding, scoring)


class ServerAndProtectionTests(unittest.TestCase):
    def test_41_server_snapshot_exposes_projection(self):
        self.assertIn('state["kpiSupplementProjection"]', SERVER_TEXT)

    def test_42_server_uses_canonical_projection_builder(self):
        self.assertIn("kpi_supplement.build_ui_projection", SERVER_TEXT)

    def test_43_projection_failure_returns_empty_metrics(self):
        with patch.object(supplement.SupplementStore, "load_all", side_effect=OSError("offline")):
            result = supplement.build_ui_projection(ROOT)
        self.assertEqual(("UNAVAILABLE", []), (result["status"], result["metrics"]))

    def test_44_empty_store_projection_is_ready(self):
        with workspace_tempdir() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/2317_master_v9.csv").write_text("Quarter\n", encoding="utf-8")
            (root / "data/macro_snapshot.csv").write_text("Date\n", encoding="utf-8")
            result = supplement.build_ui_projection(root)
        self.assertEqual(("READY", []), (result["status"], result["metrics"]))

    def test_45_manifest_hash_unchanged(self):
        self.assertEqual("449EC025AC93CDC034AB4512183BF85BC1F80F38525C57B1782DBB85945ADC9F", digest("data/CSV_AUTHORITY_MANIFEST.json"))

    def test_46_master_hash_unchanged(self):
        self.assertEqual("E623CA082F2A080613C33F4155BA8006646E30D6A517DE926AF6108062F84D48", digest("data/2317_master_v9.csv"))

    def test_47_daily_price_hash_unchanged(self):
        self.assertEqual("E39E364C528F353E350A6591C0C55EE55EA2FF862958B157860BD98EC98BA368", digest("data/2317_daily_price.csv"))

    def test_48_daily_activity_hash_unchanged(self):
        self.assertEqual("3E4D7B55446D6B167FE1BC1B0B44419A95EF311E775C14A422EBB67563E9585B", digest("data/2317_daily_market_activity.csv"))

    def test_49_macro_hash_unchanged(self):
        self.assertEqual("7F635FDDD88D4321384DA89C20B2E07C4504A4EB14D25FA98B181994E941202F", digest("data/macro_snapshot.csv"))

    def test_50_event_hash_unchanged(self):
        self.assertEqual("EBFD5CD6C327557A99803908FE468E16514C2546E36D8D1B2FF928442DFF4565", digest("data/macro_event_observations.csv"))

    def test_51_fx_hash_unchanged(self):
        self.assertEqual("F629CE510E3881CA0FA61D4A03CC30452B18BA7EB9855A92C1FA23163C1803BC", digest("data/fx_trend_observations.csv"))

    def test_52_publisher_hash_unchanged(self):
        self.assertEqual("9FA584A2F76B931CCB2DDBB32B16F112AAC7B7A3CCD4FEC05111C1D57213E8BB", digest("tools/owner_publish_csv_v2.py"))

    def test_53_formula_registry_hash_unchanged(self):
        self.assertEqual("F712A770DF5337AC7FC15549CA52079F6673A3CC5B6612ABDF8C794520787CA5", digest("contracts/p1008_formula_registry/v1.2/formula_registry.json"))

    def test_54_core_investment_ui_hash_unchanged(self):
        self.assertEqual("D722329A1C1F5AE648A150B642D4C4AB29B050C4FEDAAE159DD8C2C4F11F79DE", digest("src/index_p1008_v7.source.html"))

    def test_55_report_integration_still_calls_resolver(self):
        text = (ROOT / "tools/warroom_periodic_report_v1.py").read_text(encoding="utf-8")
        self.assertIn("kpi_supplement.resolve_from_store", text)


if __name__ == "__main__":
    unittest.main()
