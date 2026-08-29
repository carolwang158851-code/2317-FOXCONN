"""Deterministic frequency/event router for the manual Phase 3B shadow."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import ExecutionStep, PluginId, RoutePlan, RunType


@dataclass(frozen=True)
class RouteSignals:
    material_delta: bool = False
    numeric_anomaly: bool = False
    data_quality_warning: bool = False
    major_transaction: bool = False
    earnings_event: bool = False
    capital_allocation_event: bool = False
    financial_numbers: bool = False


class PluginRouter:
    """Return call ceilings; it never invokes a plugin or schedules a run."""

    def route(self, run_type: RunType | str, signals: RouteSignals) -> RoutePlan:
        normalized = RunType(run_type)
        calls = {step: 0 for step in ExecutionStep}
        calls[ExecutionStep.WEB_SEARCH] = 1
        required = [PluginId.WEB_SEARCH]
        reasons = ["WEB_SEARCH_DELTA_SCAN"]

        if normalized is RunType.DAILY:
            if signals.numeric_anomaly or signals.data_quality_warning:
                calls[ExecutionStep.DATA_ANALYTICS] = 1
                required.append(PluginId.DATA_ANALYTICS)
                reasons.append("DAILY_NUMERIC_OR_DATA_QUALITY_SIGNAL")
            if (
                signals.major_transaction
                or signals.earnings_event
                or signals.capital_allocation_event
            ):
                calls[ExecutionStep.INVESTMENT_BANKING] = 1
                required.append(PluginId.INVESTMENT_BANKING)
                reasons.append("DAILY_CORPORATE_FINANCE_SIGNAL")
            calls[ExecutionStep.OPENAI_SYNTHESIS] = int(signals.material_delta)
            reasons.append(
                "MATERIAL_DELTA" if signals.material_delta else "NO_MATERIAL_DELTA"
            )

        elif normalized is RunType.MONTHLY_REVENUE:
            calls[ExecutionStep.DATA_ANALYTICS] = 1
            calls[ExecutionStep.OPENAI_SYNTHESIS] = 1
            required.append(PluginId.DATA_ANALYTICS)
            reasons.extend(["MONTHLY_REVENUE_ANALYTICS_REQUIRED", "SYNTHESIS_REQUIRED"])

        elif normalized is RunType.QUARTERLY_EARNINGS:
            calls[ExecutionStep.DATA_ANALYTICS] = 1
            calls[ExecutionStep.INVESTMENT_BANKING] = 1
            calls[ExecutionStep.OPENAI_SYNTHESIS] = 1
            required.extend([PluginId.DATA_ANALYTICS, PluginId.INVESTMENT_BANKING])
            reasons.extend(
                [
                    "QUARTERLY_ANALYTICS_REQUIRED",
                    "QUARTERLY_BANKING_REVIEW_REQUIRED",
                    "SYNTHESIS_REQUIRED",
                ]
            )

        else:
            calls[ExecutionStep.INVESTMENT_BANKING] = 1
            calls[ExecutionStep.OPENAI_SYNTHESIS] = 1
            required.append(PluginId.INVESTMENT_BANKING)
            reasons.extend(["MAJOR_EVENT_BANKING_REVIEW_REQUIRED", "SYNTHESIS_REQUIRED"])
            if signals.financial_numbers:
                calls[ExecutionStep.DATA_ANALYTICS] = 1
                required.append(PluginId.DATA_ANALYTICS)
                reasons.append("MAJOR_EVENT_FINANCIAL_NUMBERS")

        return RoutePlan(
            run_type=normalized,
            max_calls=calls,
            required_packets=required,
            reason_codes=reasons,
            manual_shadow=True,
            actionable=False,
        )

    @staticmethod
    def route_editorial(
        *, task_type: str, owner_authorized: bool, live_enabled: bool,
        network_enabled: bool, model_id: str,
    ) -> dict[str, object]:
        """Fail-closed selection of the existing live client for one editorial task."""
        from ..runtime.runtime_config import PHASE3B_LIVE_MODEL_ID

        if task_type != "WAR_REPORT_EDITORIAL_SYNTHESIS":
            raise ValueError("Unsupported editorial task type")
        if not owner_authorized:
            raise ValueError("Editorial live execution requires Owner authorization")
        if not live_enabled:
            raise ValueError("Editorial live execution is disabled")
        if not network_enabled:
            raise ValueError("Editorial network execution is disabled")
        if model_id != PHASE3B_LIVE_MODEL_ID:
            raise ValueError("Editorial model is not approved")
        return {
            "taskType": task_type,
            "client": "LiveAgentsSdkClient",
            "model": model_id,
            "maxCalls": 1,
            "fallbackAllowed": False,
            "webSearchAllowed": False,
            "actionable": False,
        }
