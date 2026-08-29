from __future__ import annotations

import importlib.util
import inspect
import re
import unittest

try:
    from .helpers import PACKAGE_ROOT, fixture_pipeline, scratch
except ImportError:
    from helpers import PACKAGE_ROOT, fixture_pipeline, scratch

from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline
from p1008_research_plugin.reporting.report_validator import ReportValidator
from p1008_research_plugin.reporting.script_builder import (
    ScriptBuilder,
    ShortsDurationValidator,
)


def replace_segment(script: str, label: str, body: str) -> str:
    pattern = re.compile(
        rf"(^## {re.escape(label)}\s*$\n).*?(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    changed, count = pattern.subn(rf"\1{body}\n\n", script, count=1)
    if count != 1:
        raise AssertionError(f"segment not found: {label}")
    return changed


class PhaseB1ShortsSentenceIntegrityR2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with scratch("r2-valid-") as output:
            result = fixture_pipeline(output).run_all(output_base=output)
            cls.analysis = result["analysis"]
            cls.report = result["report"]
        cls.builder = ScriptBuilder()
        cls.longform = cls.builder.longform(cls.report)
        cls.shorts = cls.builder.shorts_75s(cls.report)
        cls.duration = ShortsDurationValidator.validate(cls.shorts)

    def test_long_sentence_is_not_mechanically_character_sliced(self) -> None:
        source = inspect.getsource(ScriptBuilder)
        self.assertNotIn("sentence[:limit]", source)
        sections = list(self.report.sections)
        changed_index = next(
            index for index, item in enumerate(sections) if item.section_id == "WHAT_CHANGED"
        )
        sections[changed_index] = sections[changed_index].model_copy(
            update={"body_zh": sections[changed_index].body_zh + ("完整補充事實" * 30) + "。"}
        )
        script = self.builder.shorts_75s(self.report.model_copy(update={"sections": sections}))
        validation = ShortsDurationValidator.validate(script)
        self.assertTrue(validation.no_mechanical_truncation)
        self.assertTrue(validation.all_segments_semantically_complete)

    def test_incomplete_suo_terminal_fails(self) -> None:
        result = ShortsDurationValidator.validate(
            replace_segment(self.shorts, "15–35秒", "本次證據只支持營收公告所。")
        )
        self.assertEqual(result.sentence_integrity_status, "FAIL")
        self.assertFalse(result.no_mechanical_truncation)

    def test_incomplete_he_terminal_fails(self) -> None:
        result = ShortsDurationValidator.validate(
            replace_segment(self.shorts, "65–75秒", "下一個正式驗證點公布後，屆時核。")
        )
        self.assertEqual(result.sentence_integrity_status, "FAIL")
        self.assertFalse(result.sentence_completeness_passed)

    def test_incomplete_conclusion_terminal_fails(self) -> None:
        result = ShortsDurationValidator.validate(
            replace_segment(self.shorts, "65–75秒", "若官方更正營收，立即撤回結。")
        )
        self.assertEqual(result.sentence_integrity_status, "FAIL")
        self.assertFalse(result.no_mechanical_truncation)

    def test_numeric_value_without_percent_or_unit_fails(self) -> None:
        result = ShortsDurationValidator.validate(
            replace_segment(
                self.shorts,
                "35–50秒",
                "公告後一個交易日的事件反應為0.62。市場方向仍待正式資料核對。",
            )
        )
        self.assertFalse(result.numeric_units_preserved)
        self.assertEqual(result.numeric_unit_status, "FAIL")

    def test_raw_event_window_code_fails_spoken_copy_gate(self) -> None:
        result = ShortsDurationValidator.validate(
            replace_segment(
                self.shorts,
                "35–50秒",
                "事件窗口T-1_TO_T+1=0.62%。這項結果只描述公告後價格反應。",
            )
        )
        self.assertFalse(result.spoken_technical_codes_absent)
        self.assertEqual(result.sentence_integrity_status, "FAIL")

    def test_sentence_safe_condensation_preserves_evidence_values(self) -> None:
        required = (
            "新台幣821,763百萬元",
            "年增百分之五十二點一一",
            "月減百分之四點三八",
            "負325.57191億元",
            "公告後一個交易日上漲百分之零點六二",
            "五個交易日後下跌百分之一點六六",
            "股價淨值比1.853倍",
            "研究分類為WAIT",
            "研究分類為HOLD",
        )
        for value in required:
            self.assertIn(value, self.shorts)
        self.assertNotIn("T-1_TO_T+1", self.shorts)
        self.assertNotIn("DESCRIPTIVE_ONLY", self.shorts)

    def test_complete_script_in_sixty_to_seventy_five_second_range_passes(self) -> None:
        self.assertGreaterEqual(self.duration.estimated_spoken_seconds, 60)
        self.assertLessEqual(self.duration.estimated_spoken_seconds, 75)
        self.assertEqual(self.duration.duration_gate_status, "PASS")
        self.assertEqual(self.duration.sentence_integrity_status, "PASS")
        self.assertEqual(self.duration.numeric_unit_status, "PASS")

    def test_duration_length_cannot_override_sentence_failure(self) -> None:
        malformed = self.shorts.replace("撤回本次結論。", "撤回本次結。")
        result = ShortsDurationValidator.validate(malformed)
        self.assertGreaterEqual(result.estimated_spoken_seconds, 60)
        self.assertLessEqual(result.estimated_spoken_seconds, 75)
        self.assertEqual(result.duration_gate_status, "FAIL")
        self.assertEqual(result.sentence_integrity_status, "FAIL")

    def test_editorial_fails_when_sentence_integrity_fails(self) -> None:
        malformed = self.shorts.replace("撤回本次結論。", "撤回本次結。")
        duration = ShortsDurationValidator.validate(malformed)
        result = ReportValidator.editorial_result(
            self.report, self.analysis, self.longform, malformed, duration
        )
        self.assertEqual(result.status, "FAIL")
        self.assertFalse(result.no_mechanical_truncation)
        self.assertFalse(result.all_segments_semantically_complete)
        self.assertTrue(result.errors)

    def test_final_review_package_cannot_pass_malformed_prose(self) -> None:
        malformed = self.shorts.replace("撤回本次結論。", "撤回本次結。")
        duration = ShortsDurationValidator.validate(malformed)
        editorial = ReportValidator.editorial_result(
            self.report, self.analysis, self.longform, malformed, duration
        )
        tool_path = PACKAGE_ROOT / "tools" / "p1008_build_phaseb1_final_review.py"
        spec = importlib.util.spec_from_file_location("p1008_phaseb1_r2_review_tool", tool_path)
        if spec is None or spec.loader is None:
            self.fail("unable to load Final Review builder")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        protected = {"authority": "UNCHANGED"}
        self.assertFalse(
            module.final_review_passes(
                editorial.model_dump(mode="json", by_alias=True),
                duration.model_dump(mode="json", by_alias=True),
                protected,
                protected,
                self.report.model_dump(mode="json", by_alias=True),
            )
        )


if __name__ == "__main__":
    unittest.main()
