import csv
import importlib.util
import json
import unittest
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("audit", PACKAGE / "tools/p1008_kpi_reconciliation_audit.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(line for line in handle if not line.startswith("##")))


class KpiReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = audit.generate(PACKAGE)
        cls.out = PACKAGE / audit.OUTPUT_DIR
        cls.new_ui = (PACKAGE / "ui/P1008_WARROOM_COMMAND_CENTER_v24.html").read_text(encoding="utf-8")
        cls.old_source = (PACKAGE / "src/index_p1008_v7.source.html").read_text(encoding="utf-8")
        cls.old_bundle = (PACKAGE / "dist/index_p1008_v7.bundle.js").read_text(encoding="utf-8")
        report = (PACKAGE / "tools/warroom_periodic_report_v1.py").read_text(encoding="utf-8")
        cls.report_final = report[report.rfind("def build_report_markdown("):]

    def test_six_required_artifacts_exist(self):
        expected = {
            "KPI_INVENTORY.csv", "KPI_COLLISION_REPORT.csv", "STALE_ZOMBIE_REPORT.csv",
            "KPI_LINEAGE_MAP.json", "KPI_RECONCILIATION_SUMMARY.md",
            "BASELINE_REGRESSION_DIFF.md",
        }
        self.assertEqual(expected, {p.name for p in self.out.iterdir() if p.is_file()})

    def test_authority_files_hash_and_size_match(self):
        manifest = json.loads((PACKAGE / "data/CSV_AUTHORITY_MANIFEST.json").read_text(encoding="utf-8-sig"))
        for entry in manifest["authoritativeFiles"]:
            self.assertEqual(entry["sha256"], audit._sha(PACKAGE / entry["path"]))
            self.assertEqual(entry["fileSizeBytes"], (PACKAGE / entry["path"]).stat().st_size)

    def test_new_ui_six_scores_are_null(self):
        block = self.new_ui[self.new_ui.index("function buildSystems"):self.new_ui.index("function renderRightPanel")]
        self.assertEqual(6, block.count("score: null"))
        for name in ("fundScore", "valuationScore", "cashScore", "macroScore", "aiScore", "qualityScore"):
            self.assertNotIn(f"const {name}", block)
        self.assertEqual(6, block.count('state: "未提供正式分數"'))

    def test_new_ui_keeps_canonical_evidence_without_cross_source_fallback(self):
        block = self.new_ui[self.new_ui.index("function buildSystems"):self.new_ui.index("function renderRightPanel")]
        for token in (
            "const bvps = toNumber(daily.BVPS_ref)", "const pb = toNumber(daily.PB_daily)",
            "const promoted = quarterly?.canonicalPromotion || {}", "toNumber(promoted.roe.value)", "const us10y = toNumber(fx.US_10Y_Yield)",
            "const vix = toNumber(macro.VIX)", "const dxy = toNumber(fx.DXY)",
            "cashDividend / close * 100",
        ):
            self.assertIn(token, block)
        self.assertNotIn("|| toNumber(", block)
        self.assertNotIn("?? toNumber(", block)

    def test_new_ui_has_no_stale_placeholder_values(self):
        for token in ("2025-05-25", "2025-06-01", 'score: "78"', 'score: "59"', 'score: "87"'):
            self.assertNotIn(token, self.new_ui)

    def test_new_ui_english_judgements_have_been_removed(self):
        for token in ("未提供 canonical score", "FX observation", "different observation", "current authoritative KPI"):
            self.assertNotIn(token, self.new_ui)

    def test_old_ui_model_is_retained(self):
        self.assertIn("function calculateRadarPackage", self.old_source)
        self.assertIn("const fundScore = clampScore(quality)", self.old_source)
        self.assertIn("const valuationScore = Number.isFinite(currentPB)", self.old_source)

    def test_old_ui_rejects_approximate_roic_fallback(self):
        bad = "finiteNumber(row, 'ROIC_Precise_Pct') ?? finiteNumber(row, 'ROIC_Approx_Pct')"
        self.assertNotIn(bad, self.old_source)
        self.assertNotIn(bad, self.old_bundle)
        self.assertIn("recentMaster.map(row => finiteNumber(row, 'ROIC_Precise_Pct'))", self.old_source)

    def test_old_ui_ai_requires_denominator_and_authority(self):
        for text in (self.old_source, self.old_bundle):
            self.assertIn("function validatedAiRevenueShare", text)
            self.assertIn("AI_Revenue_Denominator", text)
            self.assertIn("allowedDenominators.has(denominator)", text)
            self.assertIn("authoritySupported ? value : null", text)

    def test_old_ui_missing_score_inputs_fail_closed(self):
        for text in (self.old_source, self.old_bundle):
            self.assertIn("blockPrice <= 0) return null", text)
            self.assertIn("score: null", text)
            self.assertNotIn("const trendScore = trend === 'RISING' ? 65 : (trend === 'DECLINING' ? 35 : 50)", text)
            self.assertNotIn("coreData?.vix) ? clampPercent(coreData.vix / 30 * 100) : 45", text)
            self.assertNotIn("coreData?.fedProb) ? clampPercent(coreData.fedProb) : 50", text)

    def test_old_ui_uses_formal_fx_sidecar_for_shared_fx_metrics(self):
        for text in (self.old_source, self.old_bundle):
            self.assertIn("const latestFormalFxTrend = validFxTrendCsv[validFxTrendCsv.length - 1] || null", text)
            self.assertIn("finiteNumber(latestFormalFxTrend, 'US_10Y_Yield')", text)
            self.assertIn("finiteNumber(latestFormalFxTrend, 'TWD_USD')", text)
            self.assertIn("finiteNumber(latestFormalFxTrend, 'DXY')", text)
            self.assertNotIn("finiteNumber(latestMac, 'TWD_USD')", text)
            self.assertNotIn("finiteNumber(latestMac, 'DXY')", text)

    def test_pb_formula_reproduces_authority_value(self):
        row = csv_rows(PACKAGE / "data/2317_daily_price.csv")[-1]
        self.assertEqual("2026-08-27", row["Date"])
        self.assertEqual("2026Q2", row["QuarterKey"])
        self.assertEqual(252.0, float(row["Close"]))
        self.assertEqual(136.02, float(row["BVPS_ref"]))
        self.assertEqual(1.853, float(row["PB_daily"]))
        self.assertEqual(float(row["PB_daily"]), round(float(row["Close"]) / float(row["BVPS_ref"]), 3))

    def test_roic_formula_reproduces_precise_value(self):
        rows = csv_rows(PACKAGE / "data/2317_master_v9.csv")
        self.assertEqual("N/A", rows[-1]["ROIC_Precise_Pct"])
        row = next(item for item in reversed(rows) if item["ROIC_Precise_Pct"] not in {"", "N/A"})
        actual = round(float(row["NOPAT_Annual_100M"]) / float(row["InvestedCapital_100M"]) * 100, 2)
        self.assertEqual(float(row["ROIC_Precise_Pct"]), actual)

    def test_fcf_formula_reproduces_authority_value(self):
        row = csv_rows(PACKAGE / "data/2317_cash_flow_authority.csv")[-1]
        actual = float(row["operating_cash_flow_thousand_ntd"]) - float(row["ppe_capex_thousand_ntd"])
        self.assertEqual(float(row["free_cash_flow_core_thousand_ntd"]), actual)
        self.assertEqual(float(row["free_cash_flow_core_100m_ntd"]), actual / 100000)

    def test_q2_is_promoted_without_inventing_ai_share(self):
        q2 = json.loads((PACKAGE / "modules/p1008_research_plugin/config/quarterly_earnings/FY2026_Q2.json").read_text(encoding="utf-8"))
        quarters = {row["Quarter"] for row in csv_rows(PACKAGE / "data/2317_master_v9.csv")}
        self.assertEqual("FY2026 Q2", q2["fiscalPeriod"])
        self.assertIn("2026Q2", quarters)
        self.assertEqual("PASS_WITH_ROIC_CONDITIONAL_PENDING", q2["canonicalPromotion"]["status"])
        self.assertEqual("NOT_DISCLOSED", q2["productMix"]["aiSpecificShareStatus"])
        self.assertIsNone(q2["productMix"]["aiSpecificRevenueSharePct"])

    def test_ai_40_is_not_confused_with_q2_cloud_share_51(self):
        rows = csv_rows(PACKAGE / "data/2317_master_v9.csv")
        master = next(row for row in rows if row["Quarter"] == "2026Q1")
        current = next(row for row in rows if row["Quarter"] == "2026Q2")
        q2 = json.loads((PACKAGE / "modules/p1008_research_plugin/config/quarterly_earnings/FY2026_Q2.json").read_text(encoding="utf-8"))
        self.assertEqual("40.0", master["AI_Revenue_Pct"])
        self.assertNotIn("AI_Revenue_Denominator", master)
        self.assertEqual("L3", master["DataSupportLevel"])
        self.assertEqual("N/A", current["AI_Revenue_Pct"])
        self.assertEqual("51", q2["productMix"]["cloudAndNetworkingRevenueSharePct"])

    def test_report_is_downstream_and_uses_same_sources(self):
        self.assertIn('bvps = finite_float(latest_daily, "BVPS_ref")', self.report_final)
        self.assertIn('latest_fx = latest(data.get("fxRows", []), "Date") or {}', self.report_final)
        self.assertIn('twd_usd = finite_float(latest_fx, "TWD_USD")', self.report_final)
        self.assertIn("cash_dividend / price * 100", self.report_final)
        self.assertNotIn('or finite_float(latest_master, "BVPS")', self.report_final)
        self.assertNotIn('twd_usd = finite_float(latest_macro, "TWD_USD")', self.report_final)

    def test_inventory_contract_and_classifications(self):
        with (self.out / "KPI_INVENTORY.csv").open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle); rows = list(reader)
        self.assertEqual(list(audit.INVENTORY_COLUMNS), reader.fieldnames)
        self.assertEqual(self.result["inventory"], len(rows))
        classes = {row["value_classification"] for row in rows}
        self.assertTrue({"OFFICIAL_REPORTED", "AUTHORITATIVE_SOURCE_REPORTED", "DERIVED_VERIFIED", "RESEARCH_ESTIMATE", "STALE", "UNVERIFIED", "INVALID"}.issubset(classes))

    def test_q2_inventory_preserves_field_specific_periods_and_pending_states(self):
        with (self.out / "KPI_INVENTORY.csv").open(encoding="utf-8", newline="") as handle:
            by_id = {row["metric_id"]: row for row in csv.DictReader(handle)}
        self.assertEqual("2026H1_OR_2026Q2_FIELD_SPECIFIC", by_id["FIN.ROE_H1"]["as_of_date"])
        self.assertIn("annualized=false", by_id["FIN.ROE_H1"]["notes"])
        self.assertEqual("OWNER_CONDITIONAL_PENDING", by_id["FIN.ROIC"]["value_classification"])
        self.assertEqual("INSUFFICIENT_DATA", by_id["FIN.ROIC"]["status"])
        self.assertEqual("INSUFFICIENT_DATA", by_id["MODEL5.CHIP"]["status"])
        for metric_id in ("FIN.OCF_H1", "FIN.CAPEX_H1", "FIN.FCF_H1"):
            self.assertEqual("OFFICIAL_REPORTED", by_id[metric_id]["value_classification"])
            self.assertIn("不是Q2單季", by_id[metric_id]["notes"])

    def test_six_ic_inventory_is_disabled_not_replaced(self):
        six = [row for row in audit.KPI_ROWS if row["semantic_layer"] == "SIX_IC"]
        self.assertEqual(6, len(six))
        self.assertTrue(all(row["status"] == "DISABLED_UI_ONLY_LEGACY" for row in six))
        self.assertTrue(all(row["source_path"] == "NO_CANONICAL_EXACT_SCORE" for row in six))

    def test_root_cause_wording_is_exact(self):
        summary = (self.out / "KPI_RECONCILIATION_SUMMARY.md").read_text(encoding="utf-8")
        lineage = json.loads((self.out / "KPI_LINEAGE_MAP.json").read_text(encoding="utf-8"))
        self.assertIn(audit.ROOT_CAUSE, summary)
        self.assertEqual(audit.ROOT_CAUSE, lineage["rootCause"])
        self.assertEqual("DOWNSTREAM_OUTPUT_ONLY", lineage["reportRole"])
        self.assertFalse(lineage["safety"]["reportsUpstream"])

    def test_no_unresolved_p0_and_no_introduced_regression(self):
        counts = self.result["counts"]
        self.assertEqual(0, counts["UNRESOLVED_P0"])
        self.assertEqual(0, counts["INTRODUCED_REGRESSION_COUNT"])
        self.assertEqual("PASS", counts["REPORT_UI_PARITY"])

    def test_actionable_and_formal_data_boundaries_are_unchanged(self):
        lineage = json.loads((self.out / "KPI_LINEAGE_MAP.json").read_text(encoding="utf-8"))
        self.assertFalse(lineage["safety"]["actionable"])
        self.assertFalse(lineage["safety"]["formalCsvModified"])
        self.assertFalse(lineage["safety"]["thresholdsModified"])


if __name__ == "__main__":
    unittest.main()
