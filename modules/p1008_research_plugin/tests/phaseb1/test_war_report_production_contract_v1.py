from __future__ import annotations

import copy
import hashlib
import unittest

from p1008_research_plugin.reporting import war_report_production_contract as contract


class WarReportProductionContractV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        contract.validate_contract()

    @staticmethod
    def chapters() -> dict[str, str]:
        return {
            chapter_id: f"<p>第{index}章完整研究內容，期間與來源均已標示。</p>"
            for index, (chapter_id, _) in enumerate(contract.chapter_identity(), 1)
        }

    def render(self, chapters: dict[str, str] | None = None) -> str:
        return contract.render_owner_review_candidate(
            report_title="鴻海企業價值戰報",
            headline="獲利品質改善，現金轉化仍待驗證",
            deck="本次只根據已驗證資料更新企業價值判斷。",
            eyebrow="鴻海精密 2317",
            report_meta="報告類型：季度財報｜供 Owner 審閱",
            chapter_html=chapters or self.chapters(),
            footer="鴻海企業價值研究｜供 Owner 審閱",
        )

    def test_a_monthly_revenue_does_not_fabricate_quarterly_metrics(self) -> None:
        plan = contract.plan_trigger("MONTHLY_REVENUE")
        self.assertEqual(
            set(plan["prohibited_new_quarterly_values"]),
            {"CFO", "FCF", "ROIC", "CCC", "BVPS", "BALANCE_SHEET_VALUES"},
        )

    def test_b_quarterly_earnings_requires_chapter_four_fcf(self) -> None:
        plan = contract.plan_trigger("QUARTERLY_EARNINGS")
        self.assertEqual(plan["chapters"]["s4"], "REQUIRED_UPDATE")
        self.assertIn("FCF_CONVERSION", plan["chapter_4_required_analyses"])

    def test_c_major_event_updates_impact_path_and_keeps_all_chapters(self) -> None:
        plan = contract.plan_trigger("MAJOR_EVENT", ["s5", "s4", "s8", "s9", "s10"])
        self.assertEqual(plan["impacted_chapters"], ["s5", "s4", "s8", "s9", "s10"])
        self.assertEqual(plan["render_chapters"], [f"s{i}" for i in range(1, 12)])
        self.assertIn("s2", plan["unchanged_chapters"])

    def test_d_full_history_is_not_truncated_to_eight_quarters(self) -> None:
        history = [{"period": f"202{year}Q{quarter}"} for year in range(3, 6) for quarter in range(1, 5)]
        result = contract.append_full_history(history, {"period": "2026Q1"})
        self.assertEqual(len(result), 13)
        self.assertEqual(result[0]["period"], "2023Q1")

    def test_e_appending_q3_preserves_q2_and_earlier(self) -> None:
        history = [{"period": "2025Q4", "revenue": 1}, {"period": "2026Q1", "revenue": 2}, {"period": "2026Q2", "revenue": 3}]
        before = copy.deepcopy(history)
        result = contract.append_full_history(history, {"period": "2026Q3", "revenue": 4})
        self.assertEqual(result[:-1], before)
        self.assertEqual(history, before)

    def test_f_recent_eight_quarter_zoom_does_not_mutate_full_history(self) -> None:
        history = [{"period": f"P{i}", "value": i} for i in range(12)]
        before = copy.deepcopy(history)
        zoom = contract.recent_zoom(history, 8)
        zoom[0]["value"] = 999
        self.assertEqual(history, before)
        self.assertEqual(len(zoom), 8)

    def test_g_missing_same_basis_quarterly_roic_remains_missing(self) -> None:
        result = contract.resolve_quarterly_roic(official_same_basis_quarterly=None)
        self.assertIsNone(result["value"])
        self.assertEqual(result["status"], "PENDING_OR_UNAVAILABLE")

    def test_h_third_party_ttm_roic_does_not_replace_quarterly(self) -> None:
        result = contract.resolve_quarterly_roic(
            official_same_basis_quarterly=None, third_party_ttm=12.92
        )
        self.assertIsNone(result["value"])
        self.assertEqual(result["basis"], "QUARTERLY")

    def test_i_reader_report_rejects_internal_project_identifier(self) -> None:
        chapters = self.chapters()
        chapters["s1"] = "<p>P1008 內部狀態。</p>"
        with self.assertRaisesRegex(contract.WarReportContractError, "INTERNAL_TERM_LEAK"):
            self.render(chapters)

    def test_j_reader_report_rejects_data_gap(self) -> None:
        chapters = self.chapters()
        chapters["s4"] = "<p>DATA GAP</p>"
        with self.assertRaisesRegex(contract.WarReportContractError, "INTERNAL_TERM_LEAK"):
            self.render(chapters)

    def test_k_report_rejects_changed_chapter_count_or_order(self) -> None:
        chapters = self.chapters()
        value = chapters.pop("s2")
        chapters["s2"] = value
        with self.assertRaisesRegex(contract.WarReportContractError, "CHAPTER_COUNT_OR_ORDER_CHANGED"):
            self.render(chapters)

    def test_l_renderer_uses_hash_bound_known_good_mother_template(self) -> None:
        template = contract.resolve_mother_template()
        expected = contract.load_contract()["template_contract"]
        self.assertEqual(
            hashlib.sha256(template.encode("utf-8")).hexdigest().upper(),
            expected["template_sha256"],
        )
        self.assertEqual(
            expected["proven_mother_source_sha256"],
            "35BC300C3AD9D6783C8AD4F4BBDD850E51ED13065630DA6B361D3A2378C264B6",
        )
        self.assertIn('<article class="report"', template)
        self.assertIn("position:sticky", template)
        self.assertIn("@media print", template)

    def test_l1_windows_crlf_normalizes_to_the_approved_lf_bytes(self) -> None:
        approved = b"first line\nsecond line\n"
        approved_sha = hashlib.sha256(approved).hexdigest().upper()
        self.assertEqual(
            contract._verified_template_bytes(
                approved.replace(b"\n", b"\r\n"), approved_sha
            ),
            approved,
        )

    def test_l2_non_line_ending_change_remains_fail_closed(self) -> None:
        approved = b"first line\nsecond line\n"
        approved_sha = hashlib.sha256(approved).hexdigest().upper()
        with self.assertRaisesRegex(
            contract.WarReportContractError, "MOTHER_TEMPLATE_HASH_MISMATCH"
        ):
            contract._verified_template_bytes(
                b"first line\r\nchanged line\r\n", approved_sha
            )

    def test_l3_lone_cr_is_not_accepted_as_portable_line_ending(self) -> None:
        approved = b"first line\nsecond line\n"
        approved_sha = hashlib.sha256(approved).hexdigest().upper()
        with self.assertRaisesRegex(
            contract.WarReportContractError, "MOTHER_TEMPLATE_HASH_MISMATCH"
        ):
            contract._verified_template_bytes(
                b"first line\rsecond line\r", approved_sha
            )

    def test_m_rendered_report_is_self_contained(self) -> None:
        rendered = self.render()
        contract.validate_reader_html(rendered)
        self.assertNotRegex(rendered, r'<(?:script|link)[^>]+(?:src|href)="https?://')
        self.assertNotIn("{{CHAPTER_", rendered)

    def test_n_no_report_is_auto_published(self) -> None:
        for trigger in ("MONTHLY_REVENUE", "QUARTERLY_EARNINGS"):
            plan = contract.plan_trigger(trigger)
            self.assertFalse(plan["automatic_publication"])
            self.assertTrue(plan["owner_review_required"])
        self.assertFalse(contract.load_contract()["publication_policy"]["automatic_publication"])

    def test_o_no_formal_report_without_valid_trigger(self) -> None:
        for trigger in (None, "DAILY", "NO_MATERIAL_CHANGE"):
            plan = contract.plan_trigger(trigger)
            self.assertFalse(plan["formal_report_generated"])
            self.assertEqual(plan["state"], "OBSERVATION_ONLY")


if __name__ == "__main__":
    unittest.main()
