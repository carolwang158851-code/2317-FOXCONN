from __future__ import annotations

import sys
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.plugin_module.contracts import ExecutionStep, PluginId, RunType
from p1008_research_plugin.plugin_module.router import PluginRouter, RouteSignals


class Phase3BPluginRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = PluginRouter()

    def assert_calls(self, run_type: RunType, signals: RouteSignals, **expected: int) -> None:
        plan = self.router.route(run_type, signals)
        for step in ExecutionStep:
            self.assertEqual(plan.calls_for(step), expected.get(step.value, 0), step.value)
            self.assertLessEqual(plan.calls_for(step), 1)
        self.assertFalse(plan.actionable)
        self.assertTrue(plan.manual_shadow)

    def test_daily_without_material_delta_only_scans_web(self) -> None:
        self.assert_calls(
            RunType.DAILY,
            RouteSignals(),
            WEB_SEARCH=1,
        )

    def test_daily_conditionally_routes_analytics_banking_and_one_synthesis(self) -> None:
        plan = self.router.route(
            RunType.DAILY,
            RouteSignals(
                material_delta=True,
                numeric_anomaly=True,
                major_transaction=True,
                financial_numbers=True,
            ),
        )
        self.assertEqual(
            plan.required_packets,
            [PluginId.WEB_SEARCH, PluginId.DATA_ANALYTICS, PluginId.INVESTMENT_BANKING],
        )
        self.assert_calls(
            RunType.DAILY,
            RouteSignals(
                material_delta=True,
                numeric_anomaly=True,
                major_transaction=True,
                financial_numbers=True,
            ),
            WEB_SEARCH=1,
            DATA_ANALYTICS=1,
            INVESTMENT_BANKING=1,
            OPENAI_SYNTHESIS=1,
        )

    def test_monthly_revenue_matrix(self) -> None:
        self.assert_calls(
            RunType.MONTHLY_REVENUE,
            RouteSignals(material_delta=True, financial_numbers=True),
            WEB_SEARCH=1,
            DATA_ANALYTICS=1,
            OPENAI_SYNTHESIS=1,
        )

    def test_quarterly_earnings_matrix(self) -> None:
        self.assert_calls(
            RunType.QUARTERLY_EARNINGS,
            RouteSignals(material_delta=True, earnings_event=True, financial_numbers=True),
            WEB_SEARCH=1,
            DATA_ANALYTICS=1,
            INVESTMENT_BANKING=1,
            OPENAI_SYNTHESIS=1,
        )

    def test_major_event_routes_analytics_only_for_financial_numbers(self) -> None:
        self.assert_calls(
            RunType.MAJOR_EVENT,
            RouteSignals(material_delta=True, major_transaction=True),
            WEB_SEARCH=1,
            INVESTMENT_BANKING=1,
            OPENAI_SYNTHESIS=1,
        )
        self.assert_calls(
            RunType.MAJOR_EVENT,
            RouteSignals(
                material_delta=True,
                major_transaction=True,
                financial_numbers=True,
            ),
            WEB_SEARCH=1,
            DATA_ANALYTICS=1,
            INVESTMENT_BANKING=1,
            OPENAI_SYNTHESIS=1,
        )

    def test_canva_is_never_routed_for_research(self) -> None:
        for run_type in RunType:
            with self.subTest(run_type=run_type):
                plan = self.router.route(
                    run_type,
                    RouteSignals(
                        material_delta=True,
                        numeric_anomaly=True,
                        major_transaction=True,
                        financial_numbers=True,
                    ),
                )
                self.assertEqual(plan.calls_for(ExecutionStep.CANVA), 0)


if __name__ == "__main__":
    unittest.main()
