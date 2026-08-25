from __future__ import annotations

import hashlib
import json
import os
import unittest
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

try:
    from .helpers import PACKAGE_ROOT, SRC_ROOT
except ImportError:
    from helpers import PACKAGE_ROOT, SRC_ROOT

from p1008_research_plugin.phaseb1_common import protected_state_hashes
from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline
from p1008_research_plugin.reporting.war_report_production_contract import (
    WarReportContractError,
    append_full_history,
    chapter_identity,
    plan_trigger,
    recent_zoom,
    render_owner_review_candidate,
    resolve_quarterly_roic,
    validate_reader_html,
)
from p1008_research_plugin.reporting.war_report_production_runtime import (
    WarReportRuntimeError,
    _decision_state,
    _smart_state,
    build_financial_baseline,
    classify_fcf_conversion,
    derive_bvps_metric,
    run_war_report_production,
    validate_professional_reader_language,
)


EVIDENCE_ROOT = Path(
    os.environ.get(
        "P1008_GOVERNED_EVIDENCE_ROOT",
        r"C:\Users\a2231\OneDrive\foxconn_dashboard\foxconn-system\P1008_QUARTERLY_EARNINGS_PHASE_B1_PRODUCTION_SLICE_V1\runtime",
    )
).resolve()
SOURCE_MOTHER = Path.home() / "Downloads" / "HON_HAI_FY2026_Q2_ENTERPRISE_VALUE_WAR_REPORT.html"


class WarReportProductionRuntimeV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not EVIDENCE_ROOT.is_dir() or not SOURCE_MOTHER.is_file():
            raise AssertionError("governed local Q2 evidence or proven mother is unavailable")
        trigger = json.loads((EVIDENCE_ROOT / "report_trigger/latest_decision.json").read_text(encoding="utf-8"))
        cls.lineage = {
            "reportKey": trigger["report_key"], "revision": trigger["revision"],
            "eventType": trigger["event_type"], "canonicalEventId": trigger["canonical_event_id"],
            "triggerDecisionId": trigger["decision_id"], "triggerReceiptSha256": trigger["canonical_sha256"],
            "evidenceIds": trigger["qualifying_evidence_ids"], "authorityCutoffs": trigger["authority_cutoffs"],
            "actionable": False,
        }
        parent = PACKAGE_ROOT / "runtime" / "phaseb1_test_scratch"
        parent.mkdir(parents=True, exist_ok=True)
        cls.output = parent / f"war-report-runtime-v1-{uuid4().hex}"
        cls.output.mkdir(parents=False, exist_ok=False)
        cls.before = protected_state_hashes(PACKAGE_ROOT)
        cls.result = run_war_report_production(
            package_root=PACKAGE_ROOT, trigger_context=cls.lineage, output_base=cls.output,
            governed_evidence_root=EVIDENCE_ROOT, source_mother=SOURCE_MOTHER,
        )
        cls.after = protected_state_hashes(PACKAGE_ROOT)
        cls.html = Path(cls.result["output_html"]).read_text(encoding="utf-8")
        cls.audit = json.loads((Path(cls.result["output_root"]) / "chart_audit.json").read_text(encoding="utf-8"))

    def test_r1_no_material_change_produces_no_formal_report(self) -> None:
        result = run_war_report_production(package_root=PACKAGE_ROOT, trigger_context={"eventType": "NO_MATERIAL_CHANGE"})
        self.assertEqual(result["state"], "FORMAL_REPORT_REQUIRED_NO")
        self.assertFalse(result["formal_report_generated"])

    def test_r2_monthly_revenue_prohibits_quarterly_metric_fabrication(self) -> None:
        route = plan_trigger("MONTHLY_REVENUE")
        self.assertEqual(route["prohibited_new_quarterly_values"], ["CFO", "FCF", "ROIC", "CCC", "BVPS", "BALANCE_SHEET_VALUES"])

    def test_r3_quarterly_renders_exactly_eleven_chapters(self) -> None:
        self.assertEqual([item[0] for item in chapter_identity()], [f"s{i}" for i in range(1, 12)])
        self.assertEqual(sum(self.html.count(f'<section id="s{i}"') for i in range(1, 12)), 11)

    def test_r3a_launcher_pipeline_mode_materializes_enterprise_value_candidate(self) -> None:
        parent = PACKAGE_ROOT / "runtime" / "phaseb1_test_scratch"
        output = parent / f"launcher-enterprise-value-{uuid4().hex}"
        output.mkdir(parents=False, exist_ok=False)
        pipeline = PhaseB1Pipeline(PACKAGE_ROOT, governed_evidence_root=EVIDENCE_ROOT)
        analysis = pipeline.build_analysis(output_base=output, trigger_lineage=self.lineage)
        result = pipeline.build_report(
            run_id=analysis["run_id"],
            output_base=output,
            trigger_lineage=self.lineage,
            report_runtime="ENTERPRISE_VALUE_WAR_REPORT_V1",
        )
        report_root = Path(result["candidate_output_root"])
        rendered = (report_root / "war_report_candidate.html").read_text(encoding="utf-8")
        manifest = json.loads((Path(result["run_root"]) / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(result["report_runtime"], "ENTERPRISE_VALUE_WAR_REPORT_V1")
        self.assertEqual(manifest["reportRuntime"], "ENTERPRISE_VALUE_WAR_REPORT_V1")
        self.assertEqual(manifest["reportChapterCount"], 11)
        self.assertEqual(sum(rendered.count(f'<section id="s{i}"') for i in range(1, 12)), 11)
        self.assertIn("Q2 單季同口徑 ROIC 待補", rendered)
        self.assertTrue(result["protected_state_unchanged"])

    def test_r4_quarterly_requires_fcf_conversion(self) -> None:
        self.assertIn("FCF 轉化", self.html)
        broken = self.html.replace("FCF 轉化", "現金轉化", 1)
        self.assertNotIn("FCF 轉化", broken)

    def test_r5_major_event_uses_trigger_matrix(self) -> None:
        route = plan_trigger("MAJOR_EVENT", ("s5", "s8"))
        self.assertEqual(route["impacted_chapters"], ["s5", "s8"])
        self.assertIn("s2", route["unchanged_chapters"])

    def test_r6_full_history_returns_all_comparable_observations(self) -> None:
        profit = next(item for item in self.audit if item["CHART_ID"] == "full_history_profit_chain")
        self.assertEqual(profit["OBSERVATION_COUNT"], 22)
        self.assertEqual(profit["FULL_HISTORY"], "YES")
        self.assertEqual(profit["DROPPED_OBSERVATIONS"], 0)

    def test_r7_synthetic_q3_append_changes_n_to_n_plus_one(self) -> None:
        source = [{"period": f"2025Q{i}", "value": str(i)} for i in range(1, 5)]
        result = append_full_history(source, {"period": "2026Q1", "value": "5"})
        self.assertEqual(len(result), len(source) + 1)

    def test_r8_synthetic_append_preserves_previous_values(self) -> None:
        source = [{"period": "2025Q4", "value": "4"}, {"period": "2026Q1", "value": "5"}]
        snapshot = deepcopy(source)
        result = append_full_history(source, {"period": "2026Q2", "value": "6"})
        self.assertEqual(source, snapshot)
        self.assertEqual(result[:-1], snapshot)

    def test_r9_recent_eight_is_view_only(self) -> None:
        full = [{"period": f"P{i:02d}"} for i in range(13)]
        snapshot = deepcopy(full)
        self.assertEqual(len(recent_zoom(full, 8)), 8)
        self.assertEqual(full, snapshot)
        self.assertEqual(len(full), 13)

    def test_r10_production_history_not_deleted(self) -> None:
        self.assertEqual(self.before, self.after)

    def test_r11_q2_same_basis_roic_remains_missing(self) -> None:
        roic = resolve_quarterly_roic(official_same_basis_quarterly=None)
        self.assertIsNone(roic["value"])
        self.assertIn("Q2 單季同口徑 ROIC 待補", self.html)

    def test_r12_third_party_ttm_cannot_fill_quarterly_roic(self) -> None:
        self.assertIsNone(resolve_quarterly_roic(official_same_basis_quarterly=None, third_party_ttm=18.2)["value"])

    def test_r13_derived_bvps_is_labeled(self) -> None:
        metric = derive_bvps_metric(period="TEST", parent_equity="100", ordinary_shares="10", source=["TEST-SOURCE"])
        self.assertEqual(metric["direct_or_derived"], "DERIVED")
        self.assertEqual(metric["calculation_version"], "PARENT_EQUITY_DIVIDED_BY_PERIOD_END_ORDINARY_SHARES_V1")

    def test_r14_exact_working_capital_waterfall_not_fabricated(self) -> None:
        baseline = build_financial_baseline(self.result["analysis"])
        self.assertNotIn("Exact Working Capital Waterfall", {item["metric_name"] for item in baseline})

    def test_r15_consignment_remains_hypothesis_without_confirmation(self) -> None:
        self.assertIn("目前仍屬假說", self.html)
        self.assertIn("尚無完整財務證據確認", self.html)

    def test_r16_decision_engine_has_exactly_three_dimensions(self) -> None:
        state = json.loads((Path(self.result["output_root"]) / "decision_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["dimension_count"], 3)
        self.assertEqual(len(state["items"]), 3)
        self.assertIsNone(state["aggregate_numeric_score"])

    def test_r17_previous_current_decision_comparison(self) -> None:
        previous = {"decision": {"CORE_HOLDING_THESIS": "REVIEW"}}
        state = _decision_state(previous, self.result["report"])
        core = next(item for item in state["items"] if item["dimension"] == "CORE_HOLDING_THESIS")
        self.assertEqual(core["PREVIOUS_STATE"], "REVIEW")
        self.assertEqual(core["CURRENT_STATE"], "維持")

    def test_r18_smart_state_persists(self) -> None:
        first = _smart_state(None, self.result["report"])
        second = _smart_state({"smart": first}, self.result["report"])
        self.assertEqual([i["id"] for i in first["items"]], [i["id"] for i in second["items"]])
        self.assertTrue(all(not item["changed"] for item in second["items"]))

    def test_r19_reader_facing_internal_name_fails(self) -> None:
        injected = self.html.replace("<main>", "<main><p>P1008</p>", 1)
        self.assertNotEqual(injected, self.html)
        with self.assertRaisesRegex(WarReportRuntimeError, "READER_LANGUAGE_REJECTED"):
            validate_professional_reader_language(injected)

    def test_r20_reader_facing_data_gap_fails(self) -> None:
        with self.assertRaisesRegex(WarReportRuntimeError, "READER_LANGUAGE_REJECTED"):
            validate_professional_reader_language(self.html.replace("FCF 轉化", "DATA GAP", 1))

    def test_r21_unprofessional_phrases_fail(self) -> None:
        for phrase in ("企業價值有沒有壞掉", "撐出來", "沒看懂 AI"):
            with self.assertRaisesRegex(WarReportRuntimeError, "READER_LANGUAGE_REJECTED"):
                validate_professional_reader_language(self.html.replace("FCF 轉化", phrase, 1))

    def test_r22_standard_kpi_abbreviations_are_allowed(self) -> None:
        validate_professional_reader_language(self.html)
        for term in ("ROIC", "FCF", "EPS", "P/S"):
            self.assertIn(term, self.html)

    def test_r23_mother_template_order_change_fails(self) -> None:
        chapters = {item[0]: "<p>完整內容。</p>" for item in chapter_identity()}
        reversed_chapters = dict(reversed(list(chapters.items())))
        with self.assertRaisesRegex(WarReportContractError, "CHAPTER_COUNT_OR_ORDER_CHANGED"):
            render_owner_review_candidate(report_title="x", headline="x", deck="x", eyebrow="x", report_meta="x", chapter_html=reversed_chapters, footer="x")

    def test_r24_html_is_self_contained(self) -> None:
        validate_reader_html(self.html)
        self.assertNotRegex(self.html, r'<(?:script|link)[^>]+(?:src|href)="https?://')

    def test_r25_publication_remains_no(self) -> None:
        owner = json.loads((Path(self.result["output_root"]) / "owner_review.json").read_text(encoding="utf-8"))
        self.assertFalse(owner["publication"])
        self.assertFalse(owner["publishAuthorized"])

    def test_r26_real_q2_local_smoke_passes(self) -> None:
        self.assertEqual(self.result["state"], "REPORT_CANDIDATE_READY")
        self.assertEqual(self.result["owner_review_state"], "OWNER_REVIEW_REQUIRED")
        self.assertGreater(Path(self.result["output_html"]).stat().st_size, 10000)
        self.assertEqual(self.result["external_calls"], {"network": 0, "openai_api": 0, "canva": 0})


if __name__ == "__main__":
    unittest.main()
