"""Strict Phase 3B contracts for evidence packets and report candidates."""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class RunType(str, Enum):
    DAILY = "DAILY"
    MONTHLY_REVENUE = "MONTHLY_REVENUE"
    QUARTERLY_EARNINGS = "QUARTERLY_EARNINGS"
    MAJOR_EVENT = "MAJOR_EVENT"


class PluginId(str, Enum):
    WEB_SEARCH = "WEB_SEARCH"
    DATA_ANALYTICS = "DATA_ANALYTICS"
    INVESTMENT_BANKING = "INVESTMENT_BANKING"


class ExecutionStep(str, Enum):
    WEB_SEARCH = "WEB_SEARCH"
    DATA_ANALYTICS = "DATA_ANALYTICS"
    INVESTMENT_BANKING = "INVESTMENT_BANKING"
    OPENAI_SYNTHESIS = "OPENAI_SYNTHESIS"
    CANVA = "CANVA"


class Sentiment(str, Enum):
    POSITIVE = "偏多"
    NEUTRAL = "中性"
    NEGATIVE = "偏空"


class Confidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class SourceLocator(StrictModel):
    source_id: NonEmptyString
    locator: NonEmptyString
    source_tier: NonEmptyString
    observed_at: datetime


class PacketSignals(StrictModel):
    material_delta: bool
    numeric_anomaly: bool
    data_quality_warning: bool
    major_transaction: bool
    earnings_event: bool
    capital_allocation_event: bool
    financial_numbers: bool


class EvidenceItem(StrictModel):
    evidence_id: NonEmptyString
    summary: NonEmptyString
    changed_fields: list[NonEmptyString]
    field_values: dict[NonEmptyString, NonEmptyString]
    investment_impact: NonEmptyString
    impact_direction: Sentiment
    confidence: Confidence
    catalysts: list[NonEmptyString]
    risks: list[NonEmptyString]
    source_locators: list[SourceLocator] = Field(min_length=1)
    data_quality_notes: list[NonEmptyString]

    @model_validator(mode="after")
    def values_cover_changed_fields(self) -> "EvidenceItem":
        if set(self.changed_fields) != set(self.field_values):
            raise ValueError("field_values must exactly cover changed_fields")
        return self


class EvidencePacket(StrictModel):
    packet_id: NonEmptyString
    plugin: PluginId
    supported_run_types: list[RunType] = Field(min_length=1)
    as_of_date: date
    expires_on: date
    signals: PacketSignals
    evidence: list[EvidenceItem]
    executor: Literal["CODEX_PLUGIN_EXECUTOR", "OPENAI_HOSTED_TOOL"]
    actionable: Literal[False]

    @model_validator(mode="after")
    def material_packets_have_evidence(self) -> "EvidencePacket":
        if self.expires_on < self.as_of_date:
            raise ValueError("packet expiry precedes packet as_of_date")
        if self.signals.material_delta and not self.evidence:
            raise ValueError("material packet requires evidence")
        return self


class BaselineSnapshot(StrictModel):
    as_of_date: date
    source_files: list[NonEmptyString] = Field(min_length=1)
    data: dict[NonEmptyString, Any]
    baseline_hash: Annotated[str, StringConstraints(pattern=r"^[A-F0-9]{64}$")]


class RoutePlan(StrictModel):
    run_type: RunType
    max_calls: dict[ExecutionStep, int]
    required_packets: list[PluginId]
    reason_codes: list[NonEmptyString]
    manual_shadow: Literal[True] = True
    actionable: Literal[False] = False

    def calls_for(self, step: ExecutionStep) -> int:
        return self.max_calls.get(step, 0)


class ValidatedEvidence(StrictModel):
    packets: list[EvidencePacket]
    evidence: list[EvidenceItem]
    material_delta: bool
    changed_fields: list[NonEmptyString]
    evidence_ids: list[NonEmptyString]
    data_quality_notes: list[NonEmptyString]


class PluginTrace(StrictModel):
    plugin: ExecutionStep
    status: Literal["PACKET_VALIDATED", "NOT_ROUTED", "MOCK_SYNTHESIZED", "LIVE_SYNTHESIZED"]
    call_count: int = Field(ge=0, le=1)
    evidence_ids: list[NonEmptyString]


class MetricImpact(StrictModel):
    baseline: dict[str, Any]
    new_evidence: list[NonEmptyString]
    investment_impact: NonEmptyString
    evidence_ids: list[NonEmptyString]


class MetricSynthesis(StrictModel):
    new_evidence: list[NonEmptyString]
    investment_impact: NonEmptyString


class FinancialBriefSynthesis(StrictModel):
    investment_impact: NonEmptyString
    revenue: MetricSynthesis
    eps: MetricSynthesis = Field(alias="EPS")
    margins: MetricSynthesis
    valuation: MetricSynthesis
    fx_impact: MetricSynthesis
    catalysts: list[NonEmptyString]
    risks: list[NonEmptyString]
    sentiment: Sentiment
    confidence: Confidence
    data_quality_notes: list[NonEmptyString]


class TokenUsage(StrictModel):
    source: Literal["NOT_CALLED", "DETERMINISTIC_ESTIMATE", "AGENTS_SDK"]
    model_id: NonEmptyString
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)

    @model_validator(mode="after")
    def total_matches_parts(self) -> "TokenUsage":
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("token total must equal input plus output")
        return self


class ToolUsage(StrictModel):
    tool: ExecutionStep
    mode: Literal["EXECUTOR_PACKET", "DETERMINISTIC_MOCK", "AGENTS_SDK", "NOT_ROUTED"]
    call_count: int = Field(ge=0, le=1)


class FinancialBriefReport(StrictModel):
    run_id: NonEmptyString
    run_type: RunType
    as_of_date: date
    baseline_hash: Annotated[str, StringConstraints(pattern=r"^[A-F0-9]{64}$")]
    plugin_trace: list[PluginTrace]
    war_room_baseline: dict[NonEmptyString, Any]
    new_evidence: list[EvidenceItem]
    investment_impact: NonEmptyString
    revenue: MetricImpact
    eps: MetricImpact = Field(alias="EPS")
    margins: MetricImpact
    valuation: MetricImpact
    fx_impact: MetricImpact
    catalysts: list[NonEmptyString]
    risks: list[NonEmptyString]
    sentiment: Sentiment
    confidence: Confidence
    changed_fields: list[NonEmptyString]
    change_evidence: dict[NonEmptyString, list[NonEmptyString]]
    evidence_ids: list[NonEmptyString]
    source_locators: list[SourceLocator]
    data_quality_notes: list[NonEmptyString]
    token_usage: TokenUsage
    tool_usage: list[ToolUsage]
    no_material_change: bool
    status: Literal["NO_MATERIAL_CHANGE", "MATERIAL_CHANGE_CANDIDATE"]
    synthesis_count: int = Field(ge=0, le=1)
    manual_shadow: Literal[True]
    actionable: Literal[False]

    @model_validator(mode="after")
    def enforce_evidence_and_observation_boundaries(self) -> "FinancialBriefReport":
        evidence_ids = [item.evidence_id for item in self.new_evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence identifiers must be unique")
        if set(evidence_ids) != set(self.evidence_ids):
            raise ValueError("evidence_ids must match new_evidence")
        expected_locators = {
            (locator.source_id, locator.locator)
            for item in self.new_evidence
            for locator in item.source_locators
        }
        actual_locators = {
            (locator.source_id, locator.locator) for locator in self.source_locators
        }
        if expected_locators != actual_locators:
            raise ValueError("source_locators must exactly match validated evidence")

        if self.no_material_change:
            if self.status != "NO_MATERIAL_CHANGE" or self.synthesis_count != 0:
                raise ValueError("no-material reports cannot synthesize")
            if self.changed_fields or self.change_evidence or self.evidence_ids:
                raise ValueError("no-material reports cannot claim changes")
        else:
            if self.status != "MATERIAL_CHANGE_CANDIDATE" or self.synthesis_count != 1:
                raise ValueError("material reports require exactly one synthesis")
            if not self.changed_fields or not self.evidence_ids:
                raise ValueError("material reports require evidence-bound changes")

        if set(self.changed_fields) != set(self.change_evidence):
            raise ValueError("every changed field must have an evidence binding")
        valid_ids = set(self.evidence_ids)
        for field_name, bound_ids in self.change_evidence.items():
            if not bound_ids or not set(bound_ids).issubset(valid_ids):
                raise ValueError(f"invalid evidence binding for {field_name}")

        narrative = " ".join(
            [self.investment_impact, *self.catalysts, *self.risks]
            + [item.investment_impact for item in self.new_evidence]
        )
        if re.search(r"\b(?:BUY|SELL|ADD|TRIM)\b", narrative, re.IGNORECASE):
            raise ValueError("trading instructions are forbidden")
        return self


def canonical_json_ready(model: BaseModel) -> dict[str, Any]:
    """Return the stable JSON form used by writers, prompts, and tests."""

    return model.model_dump(mode="json", by_alias=True)
