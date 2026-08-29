from __future__ import annotations

import hashlib
import os
import unittest
from decimal import Decimal
from pathlib import Path

from p1008_research_plugin.reporting.owner_communication_estimation_amendment import (
    EXPECTED_PACK_SHA,
    HISTORICAL_ROIC,
    OwnerCommunicationEstimationAmendmentRenderer,
)


class OwnerCommunicationEstimationAmendmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = os.environ.get("P1008_V141_FINAL_ARTIFACT_ROOT")
        package = os.environ.get("P1008_PACKAGE_ROOT")
        if not source or not package:
            raise unittest.SkipTest("governed source and package roots are required")
        cls.source = Path(source).resolve()
        cls.master = Path(package).resolve() / "data" / "2317_master_v9.csv"
        cls.renderer = OwnerCommunicationEstimationAmendmentRenderer(cls.source, cls.master)
        cls.e = cls.renderer.estimate
        cls.md = cls.renderer.markdown()
        cls.html = cls.renderer.html().decode("utf-8")
        cls.combined = cls.md + cls.html

    def test_frozen_pack_and_historical_roic_are_unchanged(self) -> None:
        self.assertEqual(hashlib.sha256((self.source / "validated_research_pack.json").read_bytes()).hexdigest().upper(), EXPECTED_PACK_SHA)
        self.assertEqual(HISTORICAL_ROIC["2026Q1"], Decimal("12.57"))
        self.assertEqual(self.renderer.pack["quarterlyHistory"]["roicPct"][:7], [str(v) for v in HISTORICAL_ROIC.values()])

    def test_historical_method_is_reproducible_and_period_consistent(self) -> None:
        self.assertEqual((Decimal("2216") / Decimal("17633") * 100).quantize(Decimal("0.01")), Decimal("12.57"))
        self.assertIn("單季營業利益×（1－年度稅率）×4÷期末投入資本", self.combined)
        self.assertIn("沒有使用平均投入資本", self.combined)

    def test_effective_tax_and_nopat_proxy_are_full_precision_reproducible(self) -> None:
        expected_tax = Decimal("24810") / Decimal("94866") * 100
        expected_nopat = Decimal("94803") * (1 - Decimal("24810") / Decimal("94866"))
        self.assertEqual(self.e.effective_tax_pct, expected_tax)
        self.assertEqual(self.e.nopat_effective_million, expected_nopat)
        self.assertIn("約700.1億元", self.combined)

    def test_nopat_and_roic_are_estimates_not_official(self) -> None:
        self.assertIn("估算值", self.combined)
        self.assertIn("Q2方向偏改善，但不是正式值", self.combined)
        self.assertNotIn("Q2官方ROIC", self.combined)
        self.assertGreater(self.e.roic_base_pct, Decimal("12.57"))

    def test_sensitivity_is_observed_input_bound_and_has_no_fake_precision(self) -> None:
        self.assertEqual(self.e.invested_capital_range_low_100m, Decimal("15568"))
        self.assertEqual(self.e.invested_capital_range_high_100m, Decimal("17633"))
        for case in ("LOW", "BASE", "HIGH"):
            self.assertIn(case, self.md)
        self.assertIn("約15.8%（15.8%–17.8%）", self.combined)

    def test_capital_productivity_is_directional_and_incremental_roic_rejected(self) -> None:
        self.assertIn("Capital Productivity", self.combined)
        self.assertIn("方向性推論", self.combined)
        self.assertIn("本期不可靠", self.combined)
        self.assertIn("基準Δ投入資本＝0", self.combined)

    def test_kpi_table_has_nature_confidence_and_required_rows(self) -> None:
        for text in ("數據性質", "信心", "資本效率｜NOPAT", "資本效率｜ROIC", "資本效率｜Capital Productivity", "資本效率｜增量ROIC"):
            self.assertIn(text, self.combined)

    def test_three_appendices_and_step_calculations_exist(self) -> None:
        for heading in ("Appendix A｜企業價值KPI計算與估算", "Appendix B｜財務方法白話解釋", "Appendix C｜Technical Evidence"):
            self.assertIn(heading, self.combined)
        for term in ("NOPAT逐步計算", "有效稅率代理值", "ROIC方法與敏感度", "DuPont"):
            self.assertIn(term, self.combined)

    def test_roic_chart_visually_distinguishes_estimate(self) -> None:
        self.assertIn("2026Q2估算", self.html)
        self.assertIn("roic-estimate-chart", self.html)
        self.assertIn("stroke-dasharray", self.html)
        self.assertIn("金色空心／虛線＝估算", self.html)

    def test_governance_and_safety_language_remain(self) -> None:
        for text in ("actionable=false", "publication=false", "OWNER_REVIEW_REQUIRED=true", "不提供目標價"):
            self.assertIn(text, self.combined)
        for forbidden in ("買進", "賣出"):
            self.assertNotIn(forbidden, self.combined)


if __name__ == "__main__":
    unittest.main()
