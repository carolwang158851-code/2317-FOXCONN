"""Executable P1008 war-report template governance.

This is deliberately a contract adapter over the existing trigger, evidence and
report packet lineages.  It does not route research, render a second report, or
write authority state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..phaseb1_common import canonical_json_bytes, sha256_bytes


TEMPLATE_ID = "P1008_WAR_REPORT_ENTERPRISE_VALUE"
TEMPLATE_VERSION = "1.0"
MISSION_CONTEXT = "RETIREMENT_CASHFLOW_SAFETY"
SKILL_MODES = frozenset({"CALLABLE_RUNTIME", "SKILL_GUIDED_ONLY", "UNAVAILABLE"})
SIGNALS = frozenset({"GREEN", "YELLOW", "RED", "WHITE"})

GREEN_REQUIRED = frozenset({"source_of_advantage", "durability", "capital_requirement", "competitor_replicability", "cash_conversion", "invalidation_condition", "next_checkpoint"})
NON_GREEN_REQUIRED = frozenset({"root_cause", "counterevidence", "enterprise_value_impact", "retirement_mission_impact", "clear_condition", "deterioration_condition", "next_checkpoint"})
WHITE_REQUIRED = frozenset({"missing_data", "why_it_matters", "acquisition_path", "next_calculation", "next_checkpoint"})


class TemplateGovernanceError(ValueError):
    pass


def template_hash() -> str:
    return sha256_bytes(canonical_json_bytes({
        "templateId": TEMPLATE_ID, "templateVersion": TEMPLATE_VERSION,
        "missionContext": MISSION_CONTEXT, "greenRequired": sorted(GREEN_REQUIRED),
        "nonGreenRequired": sorted(NON_GREEN_REQUIRED), "whiteRequired": sorted(WHITE_REQUIRED),
    }))


def build_task_envelope(*, run_id: str, task_id: str, event: str, period: str,
                        authority_cutoff: str, research_question: str,
                        required_inputs: list[str], required_analysis: list[str],
                        required_output: list[str], prohibited_actions: list[str]) -> dict[str, Any]:
    if not all(isinstance(x, str) and x for x in (run_id, task_id, event, period, authority_cutoff, research_question)):
        raise TemplateGovernanceError("TASK_ENVELOPE_IDENTITY_REQUIRED")
    if event != "QUARTERLY_EARNINGS":
        raise TemplateGovernanceError("TEMPLATE_EVENT_UNSUPPORTED")
    payload = {
        "run_id": run_id, "task_id": task_id, "template_id": TEMPLATE_ID,
        "template_version": TEMPLATE_VERSION, "template_hash": template_hash(),
        "event": event, "period": period, "authority_cutoff": authority_cutoff,
        "research_question": research_question, "required_inputs": list(required_inputs),
        "required_analysis": list(required_analysis), "required_output": list(required_output),
        "prohibited_actions": list(prohibited_actions), "mission_context": MISSION_CONTEXT,
        "actionable": False,
    }
    payload["task_envelope_hash"] = sha256_bytes(canonical_json_bytes(payload))
    return payload


def validate_result_item(item: Mapping[str, Any]) -> dict[str, Any]:
    signal = item.get("signal")
    if signal not in SIGNALS or item.get("actionable") is not False:
        raise TemplateGovernanceError("RESULT_SIGNAL_OR_ACTIONABILITY_INVALID")
    required = WHITE_REQUIRED if signal == "WHITE" else GREEN_REQUIRED if signal == "GREEN" else NON_GREEN_REQUIRED
    missing = sorted(key for key in required if not isinstance(item.get(key), str) or not item[key].strip())
    if missing:
        raise TemplateGovernanceError("RESULT_TEMPLATE_FIELDS_MISSING:" + ",".join(missing))
    mode = item.get("skill_mode")
    if mode not in SKILL_MODES:
        raise TemplateGovernanceError("SKILL_MODE_INVALID")
    if mode == "CALLABLE_RUNTIME" and not item.get("skill_receipt"):
        raise TemplateGovernanceError("CALLABLE_RUNTIME_RECEIPT_REQUIRED")
    if mode == "SKILL_GUIDED_ONLY" and item.get("skill_receipt"):
        raise TemplateGovernanceError("SKILL_GUIDED_ONLY_MUST_NOT_CLAIM_RUNTIME_RECEIPT")
    return dict(item)


def validate_packet(*, envelope: Mapping[str, Any], result_items: list[Mapping[str, Any]],
                    validation_status: str) -> dict[str, Any]:
    if envelope.get("template_hash") != template_hash() or envelope.get("actionable") is not False:
        raise TemplateGovernanceError("TEMPLATE_ENVELOPE_INVALID")
    if validation_status not in {"PARTIAL_RESEARCH_CANDIDATE", "OWNER_REVIEW_REQUIRED", "FULLY_VALIDATED"}:
        raise TemplateGovernanceError("VALIDATION_STATUS_INVALID")
    validated = [validate_result_item(item) for item in result_items]
    return {"templateId": TEMPLATE_ID, "templateVersion": TEMPLATE_VERSION,
            "templateHash": template_hash(), "taskCount": 1, "resultCount": len(validated),
            "validationStatus": validation_status, "actionable": False}
