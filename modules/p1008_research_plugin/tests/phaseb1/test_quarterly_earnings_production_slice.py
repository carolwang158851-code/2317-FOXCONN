from __future__ import annotations

import json
import os
import shutil
import unittest
from pathlib import Path

import pdfplumber

try:
    from .helpers import PACKAGE_ROOT, SRC_ROOT, scratch
except ImportError:
    from helpers import PACKAGE_ROOT, SRC_ROOT, scratch

from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline
from p1008_research_plugin.quarterly_earnings import (
    QuarterlyEarningsPacket,
    QuarterlyEarningsPacketError,
)
from p1008_research_plugin.reporting.report_contracts import (
    QUARTERLY_EARNINGS_SECTION_IDS,
)
from p1008_research_plugin.reporting import template_governance


class QuarterlyEarningsProductionSliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        evidence_root = Path(os.environ.get("P1008_GOVERNED_EVIDENCE_ROOT", PACKAGE_ROOT / "runtime")).resolve()
        trigger_path = evidence_root / "report_trigger/latest_decision.json"
        integration_path = evidence_root / "research_plugin/latest_content_integration.json"
        if not trigger_path.is_file() or not integration_path.is_file():
            raise unittest.SkipTest("real FY2026 Q2 acceptance runtime is unavailable")
        cls.evidence_root = evidence_root
        cls.trigger = json.loads(trigger_path.read_text(encoding="utf-8"))
        cls.lineage = {
            "reportKey": cls.trigger["report_key"],
            "revision": cls.trigger["revision"],
            "eventType": cls.trigger["event_type"],
            "canonicalEventId": cls.trigger["canonical_event_id"],
            "triggerDecisionId": cls.trigger["decision_id"],
            "triggerReceiptSha256": cls.trigger["canonical_sha256"],
            "evidenceIds": cls.trigger["qualifying_evidence_ids"],
            "authorityCutoffs": cls.trigger["authority_cutoffs"],
            "actionable": False,
        }

    def test_real_q2_evidence_reaches_owner_review_with_html_and_pdf(self) -> None:
        with scratch("quarterly-real-") as output:
            pipeline = PhaseB1Pipeline(
                PACKAGE_ROOT, governed_evidence_root=self.evidence_root
            )
            result = pipeline.build_analysis(output_base=output, trigger_lineage=self.lineage)
            report = pipeline.build_report(run_id=result["run_id"], output_base=output, trigger_lineage=self.lineage)
            run_root = Path(report["run_root"])
            manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
            owner = json.loads((run_root / "owner_review.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["state"], "REPORT_CANDIDATE_READY")
            self.assertEqual(manifest["eventType"], "QUARTERLY_EARNINGS")
            self.assertEqual(owner["status"], "OWNER_REVIEW_REQUIRED")
            self.assertFalse(owner["publishAuthorized"])
            self.assertFalse(owner["publication"])
            self.assertEqual(len(report["report"].sections), 24)
            self.assertFalse(report["report"].actionable)
            self.assertTrue((run_root / "report_candidate.html").is_file())
            self.assertTrue((run_root / "report_candidate.pdf").is_file())
            self.assertEqual(tuple(item.section_id for item in report["report"].sections), QUARTERLY_EARNINGS_SECTION_IDS)
            quarterly = report["analysis"].quarterly_earnings
            self.assertIsNotNone(quarterly)
            self.assertEqual(quarterly.source_hash, "F014BE750095543B35ED2D482C0CF7A40B4A448167796F8AC4560AB928E609C5")
            self.assertEqual(quarterly.cash_flow_status, "OFFICIAL_RESULTS_H1_NOT_STANDALONE_Q2")
            self.assertEqual(quarterly.apple_iphone_exposure_status, "REVIEW_REQUIRED")
            for signal in quarterly.governance_signals:
                template_governance.validate_result_item(signal)
            governed = manifest["governedEvidence"]
            self.assertEqual(governed["mode"], "EXTERNAL_GOVERNED_READ_ONLY")
            self.assertEqual(governed["root"], str(self.evidence_root))
            self.assertEqual(governed["raw_artifact_sha256"], quarterly.source_hash)
            self.assertEqual(manifest["templateGovernance"]["templateVersion"], "1.4.1")
            self.assertEqual(
                manifest["templateGovernance"]["skillModes"],
                {
                    "OFFICIAL_IR": "CALLABLE_RUNTIME",
                    "DATA_ANALYTICS": "SKILL_GUIDED_ONLY",
                    "INVESTMENT_BANKING": "UNAVAILABLE",
                    "ANYSEARCH": "CALLABLE_RUNTIME",
                    "OPENAI_EDITORIAL": "CALLABLE_RUNTIME",
                    "CANVA": "CALLABLE_RUNTIME",
                },
            )
            self.assertEqual(manifest["templateGovernance"]["tasksDispatched"], 5)
            self.assertEqual(len(manifest["templateGovernance"]["taskEnvelopes"]), 5)

            sections = {item.section_id: item.body_zh for item in report["report"].sections}
            self.assertIn("推導Q2 CFO", sections["EXECUTIVE_SUMMARY"])
            self.assertIn("估值安全性沒有改善", sections["EXECUTIVE_SUMMARY"])
            self.assertIn("第三個3", sections["GOVERNANCE_COMMITMENT_EXECUTION"])
            self.assertIn("26.67個百分點", sections["OPERATING_LEVERAGE"])
            self.assertIn("營業費用淨額代理值", sections["OPERATING_LEVERAGE"])
            self.assertIn("受治理ROIC", sections["CAPITAL_EFFICIENCY"])
            self.assertIn("不是0或下降", sections["CAPITAL_EFFICIENCY"])
            self.assertIn("CFO／歸母淨利警示代理值", sections["EARNINGS_TO_CASH_QUALITY"])
            self.assertIn("不是同口徑標準現金轉化率", sections["EARNINGS_TO_CASH_QUALITY"])
            self.assertIn("AI是營收驅動", sections["AI_SERVER_CLOUD_NETWORKING"])
            self.assertIn("AI特定營業利益", sections["AI_SERVER_CLOUD_NETWORKING"])
            self.assertNotIn("AI已證明能擴大營收與營業利益", sections["AI_SERVER_CLOUD_NETWORKING"])
            self.assertIn("鴻海官方2025Q4 basic EPS 3.23元", sections["VALUATION"])
            self.assertIn("合計15.21元", sections["VALUATION"])
            self.assertIn("17.29倍", sections["VALUATION"])
            self.assertIn("2025H2 EPS為7.40元", sections["VALUATION"])
            self.assertIn("受治理直接BVPS 127.12元", sections["VALUATION"])
            self.assertIn("P/B不能脫離ROE判讀", sections["VALUATION"])
            self.assertIn("不判定2.069倍便宜或昂貴", sections["VALUATION"])
            for forbidden in ("BUY", "SELL", "ADD", "TRIM", "TARGET PRICE", "目標價"):
                self.assertNotIn(forbidden, sections["VALUATION"])

            charts = json.loads((run_root / "chart_data.json").read_text(encoding="utf-8"))
            self.assertEqual(len(charts), 12)
            self.assertEqual(
                {item["chartId"] for item in charts},
                {
                    "growth_quality_divergence",
                    "margin_divergence_8q", "operating_cost_absorption_8q",
                    "profit_pass_through_evidence_gap", "cash_quality_evidence",
                    "working_capital_3period", "capex_intensity_limited",
                    "capital_validation_status", "roe_equity_compounding",
                    "strategy_scorecard_3plus3",
                    "valuation_matrix", "ai_growth_quality",
                },
            )
            margin = next(item for item in charts if item["chartId"] == "margin_divergence_8q")
            self.assertEqual(len(margin["labels"]), 8)
            growth = next(item for item in charts if item["chartId"] == "growth_quality_divergence")
            self.assertEqual(len(growth["labels"]), 8)
            self.assertEqual(len(growth["series"]), 3)
            self.assertEqual({item["unit"] for item in growth["series"]}, {"指數（首季=100）"})
            self.assertNotIn("歸屬淨利", json.dumps(growth, ensure_ascii=False))

            cash = next(item for item in charts if item["chartId"] == "cash_quality_evidence")
            self.assertEqual(cash["visualizationType"], "QUANTITATIVE_CHART")
            self.assertEqual(cash["labels"], ["2026Q1", "2026Q2（H1減Q1推導）"])

            capital = next(item for item in charts if item["chartId"] == "capital_validation_status")
            self.assertEqual(capital["visualizationType"], "QUANTITATIVE_CHART")
            self.assertEqual(capital["signal"], "WHITE")
            self.assertEqual(capital["series"][0]["labelZh"], "ROIC")

            roe = next(item for item in charts if item["chartId"] == "roe_equity_compounding")
            self.assertEqual(roe["visualizationType"], "QUANTITATIVE_CHART")
            self.assertEqual(roe["series"][0]["unit"], "新台幣元")

            ai = next(item for item in charts if item["chartId"] == "ai_growth_quality")
            ai_status = dict(zip(ai["labels"], ai["series"][0]["values"]))
            self.assertEqual(ai_status["營收驅動"], "SUPPORTED")
            self.assertEqual(ai_status["公司整體營業利益方向"], "PARTIALLY_PROVEN_HIGH_CONFIDENCE_INFERENCE")
            self.assertEqual(ai_status["AI特定營業利益金額"], "UNPROVEN_SPECIFIC_AMOUNT")
            self.assertEqual(ai_status["資本效率"], "UNPROVEN")
            self.assertEqual(ai_status["現金轉化"], "UNPROVEN")

            valuation_chart = next(item for item in charts if item["chartId"] == "valuation_matrix")
            self.assertEqual(valuation_chart["visualizationType"], "SCENARIO_MATRIX")
            self.assertEqual(set(valuation_chart["series"][0]["values"]), {"Forward P/E", "P/B", "Dividend Yield"})

            html_text = (run_root / "report_candidate.html").read_text(encoding="utf-8")
            self.assertEqual(html_text.count("data-visible-group="), 12)
            self.assertGreaterEqual(html_text.count("<figure"), 12)
            self.assertGreaterEqual(html_text.count("<table"), 8)
            self.assertIn('data-visualization-type="QUANTITATIVE_CHART"', html_text)
            self.assertIn('data-visualization-type="STATUS_MATRIX"', html_text)
            self.assertGreaterEqual(html_text.count('class="actual-chart'), 6)
            self.assertGreaterEqual(html_text.count("<polyline"), 5)
            self.assertIn('data-visualization-type="QUANTITATIVE_CHART"', html_text)
            self.assertIn("26.67個百分點", html_text)
            self.assertIn("前瞻本益比情境矩陣", html_text)
            self.assertIn("股價淨值比情境矩陣", html_text)
            self.assertIn("股息殖利率情境矩陣", html_text)
            self.assertIn("財報公布前收盤價：<strong>263元</strong>", html_text)
            self.assertNotIn("WEAK_VERIFIED", html_text)
            self.assertNotIn("UNSUPPORTED_VERIFIED", html_text)
            for code in ("PARTIALLY_PROVEN", "INSUFFICIENT_DATA", "SUPPORTED_MANAGEMENT_GUIDANCE"):
                self.assertNotIn(code, html_text)
            self.assertIn("部分證實", html_text)
            self.assertIn("資料不足", html_text)

            chart_bytes = (run_root / "chart_data.json").read_bytes()
            owner_bytes = (run_root / "owner_review.json").read_bytes()
            self.assertNotEqual(chart_bytes, owner_bytes)
            self.assertIsInstance(json.loads(chart_bytes), list)
            self.assertIsInstance(json.loads(owner_bytes), dict)

            skills = json.loads((run_root / "skill_execution_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(skills["taskEnvelopesDispatched"], 5)
            self.assertEqual(len(skills["realSkillReceipts"]), 1)
            self.assertEqual(skills["realSkillReceipts"][0]["skill"], "OFFICIAL_IR")
            self.assertFalse(skills["openaiEditorialExecuted"])
            self.assertIn("OPENAI_EDITORIAL_NOT_AUTHORIZED_NOT_EXECUTED", skills["explicitBlockers"])
            self.assertIn("ANYSEARCH", skills["callableRuntimeNotExecuted"])
            self.assertIn("OPENAI_EDITORIAL", skills["callableRuntimeNotExecuted"])
            self.assertNotIn("skill_receipt", json.dumps(skills["skillGuidedOnlyTasks"]))

            with pdfplumber.open(run_root / "report_candidate.pdf") as pdf:
                self.assertGreaterEqual(len(pdf.pages), 5)
                vector_count = sum(
                    len(page.lines) + len(page.rects) + len(page.curves)
                    for page in pdf.pages
                )
                self.assertGreater(vector_count, 60)
                pdf_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                self.assertNotIn("□", pdf_text)
                self.assertNotIn("≈", pdf_text)

            self.assertFalse(owner["publishAuthorized"])
            self.assertEqual(owner["status"], "OWNER_REVIEW_REQUIRED")
            self.assertTrue(owner["ownerReviewRequired"])
            self.assertEqual(owner["templateVersion"], "1.4.1")

    def test_missing_external_governed_evidence_root_fails_closed(self) -> None:
        with scratch("quarterly-missing-evidence-root-") as root:
            missing = root / "missing-governed-runtime"
            with self.assertRaisesRegex(QuarterlyEarningsPacketError, "GOVERNED_EVIDENCE_ROOT_MISSING"):
                QuarterlyEarningsPacket(
                    PACKAGE_ROOT, self.lineage, governed_evidence_root=missing
                )

    def test_raw_pdf_hash_drift_fails_closed(self) -> None:
        with scratch("quarterly-hash-drift-") as root:
            package = root / "package"
            shutil.copytree(PACKAGE_ROOT / "data", package / "data")
            shutil.copytree(PACKAGE_ROOT / "contracts", package / "contracts")
            shutil.copytree(PACKAGE_ROOT / "rules", package / "rules")
            config_source = PACKAGE_ROOT / QuarterlyEarningsPacket.CONFIG_REL
            config_target = package / QuarterlyEarningsPacket.CONFIG_REL
            config_target.parent.mkdir(parents=True)
            shutil.copy2(config_source, config_target)
            evidence_root = Path(os.environ.get("P1008_GOVERNED_EVIDENCE_ROOT", PACKAGE_ROOT / "runtime")).resolve()
            integration_source = evidence_root / "research_plugin" / "latest_content_integration.json"
            integration_target = package / QuarterlyEarningsPacket.INTEGRATION_REL
            integration_target.parent.mkdir(parents=True)
            shutil.copy2(integration_source, integration_target)
            trigger_source = evidence_root / "report_trigger" / "latest_decision.json"
            trigger_target = package / "runtime" / "report_trigger" / "latest_decision.json"
            trigger_target.parent.mkdir(parents=True)
            shutil.copy2(trigger_source, trigger_target)
            event = json.loads(integration_source.read_text(encoding="utf-8"))["validated_event_evidence"][0]
            for key in ("receipt_path", "raw_artifact_path"):
                relative = Path(event["provenance"][key])
                target = package / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(evidence_root / relative.relative_to("runtime"), target)
            (package / event["provenance"]["raw_artifact_path"]).write_bytes(b"%PDF-drift")
            with self.assertRaisesRegex(QuarterlyEarningsPacketError, "RAW_HASH_MISMATCH"):
                QuarterlyEarningsPacket(
                    package, self.lineage, governed_evidence_root=package / "runtime"
                )


if __name__ == "__main__":
    unittest.main()
