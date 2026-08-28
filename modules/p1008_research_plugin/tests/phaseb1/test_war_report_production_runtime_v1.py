from __future__ import annotations

import hashlib
import json
import os
import re
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
from p1008_research_plugin.analysis.quarterly_analysis_builder import valuation_time_basis_labels
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
        self.assertIn("Q2 ROIC候選16.46%未通過現金／負債來源口徑閘門", rendered)
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
        self.assertIn("Q2 ROIC候選16.46%未通過現金／負債來源口徑閘門", self.html)

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

    def test_r27_chapter_one_uses_two_stage_enterprise_value_spine(self) -> None:
        self.assertIn("企業價值第一階段已驗證，第二階段仍待驗證", self.html)
        self.assertIn("成長是否能轉成資本報酬與現金", self.html)
        for metric in ("營收", "毛利", "營業利益", "EPS", "CFO", "FCF", "CCC", "P/S", "P/E", "P/B"):
            self.assertIn(metric, self.html)

    def test_r28_profit_bridge_distinguishes_margin_and_expense_absorption(self) -> None:
        self.assertIn("2025Q2至2026Q2獲利橋", self.html)
        self.assertIn("毛利以下營業費用淨額代理值", self.html)
        self.assertIn("不是公司揭露的單一營業費用科目，也不是營業成本", self.html)
        self.assertIn("毛利率仍較去年同期下降21個基點", self.html)

    def test_r29_accounts_payable_cashflow_direction_is_correct(self) -> None:
        self.assertIn("應付帳款是融資抵銷，不是現金吸收", self.html)
        self.assertIn("提供供應商融資並抵銷部分占用", self.html)
        self.assertNotIn("應付帳款增加會吸收現金", self.html)

    def test_r30_fcf_uses_same_season_and_full_year_recovery_context(self) -> None:
        self.assertIn("2025H1 FCF為-552.75億元", self.html)
        self.assertIn("2025年前九個月擴大至-1,623.35億元", self.html)
        self.assertIn("全年則回升至530.89億元", self.html)
        self.assertIn("結構性風險尚未排除", self.html)

    def test_r31_roic_three_layers_remain_separate(self) -> None:
        for phrase in (
            "官方同口徑", "部分營運投入資本估算",
            "年化敏感度", "這不是官方同口徑ROIC",
        ):
            self.assertIn(phrase, self.html)
        self.assertIn("不能當作TTM或正式年度ROIC", self.html)

    def test_r32_capital_light_hypothesis_is_not_causality(self) -> None:
        self.assertIn("Consignment（客供料）仍是可驗證假說", self.html)
        self.assertIn("訊號互有支持與反證", self.html)
        self.assertIn("資本輕量化綜合判斷仍不確定", self.html)

    def test_r33_event_time_valuation_uses_actual_event_date(self) -> None:
        valuation = self.result["analysis"].quarterly_earnings.valuation_scenarios
        self.assertEqual(valuation["price"]["eventDate"], "2026-08-12")
        expected = valuation_time_basis_labels(valuation["price"]["date"], valuation["price"]["eventDate"])
        self.assertEqual(valuation["price"]["valuationContext"], expected["price_context"])
        self.assertEqual(valuation["price"]["readerLabel"], expected["reader_label"])
        known_post_event_case = valuation_time_basis_labels("2026-08-25", "2026-08-12")
        self.assertEqual(known_post_event_case["price_context"], "POST_EVENT_REPORT_CUTOFF_PRICE")
        self.assertEqual(known_post_event_case["reader_label"], "財報公布後報告截止日收盤價")

    def test_r34_eight_rule_label_is_consistent(self) -> None:
        rules = json.loads((Path(self.result["output_root"]) / "enterprise_value_rule_engine.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rules["rules"]), 8)
        self.assertIn("八項企業價值證據規則", self.html)
        self.assertNotIn("七維證據規則", self.html)

    def test_r35_reader_has_no_internal_enum_or_placeholder_leakage(self) -> None:
        for token in (
            "DECLARED_IN_", "INITIALIZED_BASELINE", "LOW_RESILIENCE",
            "ESTIMATE_ACTIVE", "Q_STANDALONE", "INSUFFICIENT_DATA",
        ):
            self.assertNotIn(token, self.html)
        self.assertNotIn("Owner", self.html)

    def test_r36_reader_has_no_database_precision(self) -> None:
        visible = re.sub(r"<(?:style|script)\\b[^>]*>.*?</(?:style|script)>", " ", self.html, flags=re.DOTALL | re.IGNORECASE)
        self.assertIsNone(re.search(r"(?<!\\d)\\d+\\.\\d{5,}(?!\\d)", visible))

    def test_r37_full_history_charts_use_only_three_specific_commentaries(self) -> None:
        charts = json.loads((Path(self.result["output_root"]) / "chart_data_full_history.json").read_text(encoding="utf-8"))
        full_history = [item for item in charts if item["chartId"].startswith("full_history_")]
        self.assertTrue(full_history)
        self.assertTrue(all(len(item["commentaryZh"]) == 3 for item in full_history))
        for item in full_history:
            start = self.html.index(f'data-chart-id="{item["chartId"]}"')
            end = self.html.index("</figure>", start)
            figure = self.html[start:end]
            self.assertNotIn("戰略含義：", figure)
            self.assertNotIn("下一驗證點：", figure)

    def test_r38_variant_and_counter_view_are_explicit(self) -> None:
        self.assertIn("兩種競爭解釋", self.html)
        self.assertIn("主解釋", self.html)
        self.assertIn("替代解釋", self.html)
        self.assertIn("Q3 CFO、毛利率與同口徑ROIC", self.html)

    def test_r39_smart_is_falsifiable_not_runtime_state_table(self) -> None:
        for heading in ("目前基線", "增強條件", "削弱條件", "下一觀察"):
            self.assertIn(heading, self.html)
        self.assertIn("2026全年FCF仍為負", self.html)
        self.assertNotIn("SMART-01", self.html)

    def test_r40_appendix_uses_reader_citations_and_collapsed_audit(self) -> None:
        self.assertIn("論文式來源索引", self.html)
        self.assertIn("<details><summary>技術稽核說明</summary>", self.html)
        self.assertIn("CSV與JSON只作可追溯資料定位", self.html)

    def test_r41_valuation_timepoints_and_chart_basis_are_explicit(self) -> None:
        valuation = self.result["analysis"].quarterly_earnings.valuation_scenarios["valuationTimeBasis"]
        self.assertEqual(valuation["preEventValuation"]["date"], "2026-08-11")
        self.assertEqual(valuation["postEventValuation"]["status"], "AVAILABLE")
        self.assertIn("本地正式行情已涵蓋事件後時點", self.html)
        self.assertIn("歷史季度序列只到2026Q1", self.html)
        self.assertIn("獨立尺度", self.html)

    def test_r42_chapter_four_exposes_evidence_and_limits_causality(self) -> None:
        for phrase in (
            "非現金項目", "資料未提供", "現有證據可確認營運資金是重要因素",
            "但不足以把全部 CFO 落差歸因於營運資金", "現金及約當現金",
            "淨現金", "權益總額（含非控制權益）", "90日研究情境",
        ):
            self.assertIn(phrase, self.html)

    def test_r43_smart_requires_durable_cash_per_share_and_valuation_confirmation(self) -> None:
        for phrase in (
            "後續累計CFO改善只算初步改善", "H2、全年或TTM現金轉化恢復",
            "每股價值", "FCF／相容加權平均股數", "估值第二階段", "形成再評價風險",
        ):
            self.assertIn(phrase, self.html)

    def test_r43a_cash_flow_keeps_official_h1_period_semantics(self) -> None:
        for phrase in ("2026H1 CFO", "-691.22億元", "2026H1 FCF", "-1500.09億元", "不是Q2單季現金流"):
            self.assertIn(phrase, self.html)

    def test_r44_editorial_has_no_machine_or_unsupported_forward_language(self) -> None:
        for forbidden in (
            "PERIOD_END_SHARE_COUNT", "PEER_VALUATION_CAPITAL_EFFICIENCY_HISTORY",
            "後續可望回收", "現金治理未通過", "資本治理待補",
        ):
            self.assertNotIn(forbidden, self.html)

    def test_r45_reader_stress_precision_and_equity_basis_are_consistent(self) -> None:
        self.assertIn("壓力情境韌性", self.html)
        self.assertIn("待驗證", self.html)
        self.assertNotIn("韌性偏低", self.html)
        self.assertIn("權益總額（含非控制權益）", self.html)
        self.assertIn("不得作為歸屬母公司ROE或BVPS分母", self.html)
        for raw in ("-72339.154", "45111.655", "-117450.809", "21875.585"):
            self.assertNotIn(raw, self.html)


if __name__ == "__main__":
    unittest.main()
