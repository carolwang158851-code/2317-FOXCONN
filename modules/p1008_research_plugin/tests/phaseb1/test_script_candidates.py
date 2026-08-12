from __future__ import annotations

import re
import unittest
from pathlib import Path

try:
    from .helpers import PACKAGE_ROOT, fixture_pipeline, scratch
except ImportError:  # direct discovery with phaseb1 as the start directory
    from helpers import PACKAGE_ROOT, fixture_pipeline, scratch

from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline
from p1008_research_plugin.reporting.script_builder import ScriptBuilder, ScriptInputError


class PhaseB1ScriptCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with scratch("script-valid-") as output:
            result = fixture_pipeline(output).run_all(output_base=output)
            cls.report = result["report"]

    def test_script_generator_rejects_raw_csv_path(self) -> None:
        with self.assertRaises(ScriptInputError):
            ScriptBuilder().longform(PACKAGE_ROOT / "data" / "2317_daily_price.csv")  # type: ignore[arg-type]

    def test_longform_has_evidence_transmission_unknowns_and_next_validation(self) -> None:
        text = ScriptBuilder().longform(self.report)
        for required in ("已驗證的新證據", "從營收到投資意義", "替代解釋", "反方證據", "下一個驗證點"):
            self.assertIn(required, text)
        self.assertIn("actionable=false", text)
        self.assertIn("畫面合規字卡（不口播）", text)

    def test_shorts_has_all_timed_segments(self) -> None:
        text = ScriptBuilder().shorts_75s(self.report)
        for segment in ("0–5秒", "5–15秒", "15–35秒", "35–50秒", "50–65秒", "65–75秒"):
            self.assertIn(segment, text)

    def test_scripts_have_no_automatic_buy_sell_language(self) -> None:
        combined = ScriptBuilder().longform(self.report) + ScriptBuilder().shorts_75s(self.report)
        self.assertIsNone(re.search(r"\b(?:BUY|SELL)\b", combined, re.IGNORECASE))
        self.assertNotIn("立即買進", combined)
        self.assertNotIn("立即賣出", combined)

    def test_scripts_are_repeatable(self) -> None:
        builder = ScriptBuilder()
        self.assertEqual(builder.longform(self.report), builder.longform(self.report))
        self.assertEqual(builder.shorts_75s(self.report), builder.shorts_75s(self.report))


if __name__ == "__main__":
    unittest.main()
