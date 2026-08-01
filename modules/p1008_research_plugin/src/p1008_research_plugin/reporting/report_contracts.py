"""Typed contract for Phase B1 report and chart candidates."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from ..analysis.analysis_contracts import OverallThesis


NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[A-F0-9]{64}$")]


def _camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


class StrictModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


REQUIRED_SECTION_IDS = (
    "REPORT_IDENTITY_AND_CUTOFF",
    "EXECUTIVE_JUDGMENT",
    "WHAT_CHANGED",
    "WHAT_DID_NOT_CHANGE",
    "FINANCIAL_TRANSMISSION",
    "EARNINGS_AND_MARGIN_QUALITY",
    "CASH_FLOW_AND_DIVIDEND_SAFETY",
    "VALUATION_INTERPRETATION",
    "PRICE_VOLUME_AND_MARKET_PSYCHOLOGY",
    "SUPPORTING_EVIDENCE",
    "ALTERNATIVE_EXPLANATION",
    "COUNTEREVIDENCE",
    "MISSING_EVIDENCE",
    "NEW_MONEY_VIEW",
    "EXISTING_HOLDING_VIEW",
    "THREE_AUDIENCE_LENSES",
    "INVALIDATION_CONDITIONS",
    "NEXT_VALIDATION_DATE_AND_EVENT",
    "DATA_LIMITATIONS",
    "ACTIONABLE_FALSE_DISCLAIMER",
)


class EvidenceReference(StrictModel):
    evidence_id: NonEmpty
    claim: NonEmpty
    source_tier: NonEmpty
    source_date: NonEmpty
    source_urls: list[NonEmpty]


class ReportSection(StrictModel):
    section_id: NonEmpty
    title_zh: NonEmpty
    body_zh: NonEmpty
    epistemic_class: Literal["FACT", "INFERENCE", "MIXED", "COMPLIANCE"]
    evidence_ids: list[NonEmpty]


class ReportCandidate(StrictModel):
    record_type: Literal["P1008_REPORT_CANDIDATE"] = "P1008_REPORT_CANDIDATE"
    run_id: NonEmpty
    event_type: Literal["MONTHLY_REVENUE"]
    generated_at_utc: datetime
    report_contract_version: Literal["1.0"] = "1.0"
    analysis_packet_sha256: Sha256
    authority_manifest_sha256: Sha256
    primary_investor_question: NonEmpty
    thesis_state: OverallThesis
    evidence_bound_facts: list[NonEmpty] = Field(min_length=1)
    evidence_references: list[EvidenceReference] = Field(min_length=1)
    sections: list[ReportSection] = Field(min_length=20, max_length=20)
    actionable: Literal[False]

    @model_validator(mode="after")
    def sections_are_complete_and_ordered(self) -> "ReportCandidate":
        actual = tuple(section.section_id for section in self.sections)
        if actual != REQUIRED_SECTION_IDS:
            raise ValueError("report sections do not match the approved Phase B1 order")
        known = {reference.evidence_id for reference in self.evidence_references}
        for section in self.sections:
            if not set(section.evidence_ids).issubset(known):
                raise ValueError(f"section cites unknown evidence: {section.section_id}")
        return self


class ChartSeries(StrictModel):
    label_zh: NonEmpty
    unit: NonEmpty
    values: list[str]


class ChartData(StrictModel):
    chart_id: NonEmpty
    title_zh: NonEmpty
    decision_question: NonEmpty
    period: NonEmpty
    source_evidence_ids: list[NonEmpty] = Field(min_length=1)
    labels: list[NonEmpty]
    series: list[ChartSeries] = Field(min_length=1)
    commentary_zh: list[NonEmpty] = Field(min_length=1)
    actionable: Literal[False]


class EditorialValidation(StrictModel):
    status: Literal["PASS", "FAIL"]
    report_candidate_sha256: Sha256 | None
    required_sections_present: bool
    all_evidence_ids_resolve: bool
    facts_and_inferences_separated: bool
    unsupported_numeric_claims_absent: bool
    forbidden_intent_claims_absent: bool
    placeholders_absent: bool
    duplicate_sections_absent: bool
    shorts_duration_passed: bool
    next_validation_evidence_bound: bool
    invalidation_condition_present: bool
    analysis_identity_preserved: bool
    scripts_read_validated_report_only: bool
    actionable_false_preserved: bool
    errors: list[str]
    actionable: Literal[False] = False


class ShortsDurationValidation(StrictModel):
    record_type: Literal["P1008_SHORTS_DURATION_VALIDATION"] = (
        "P1008_SHORTS_DURATION_VALIDATION"
    )
    speech_rate_assumption: NonEmpty
    spoken_characters_per_second: float = Field(gt=0)
    spoken_character_count: int = Field(ge=0)
    estimated_spoken_seconds: float = Field(ge=0)
    segment_character_counts: dict[NonEmpty, int]
    segment_estimated_seconds: dict[NonEmpty, float]
    duration_gate_status: Literal["PASS", "PASS_WITH_WARNING", "FAIL"]
    warnings: list[str]
    errors: list[str]
    actionable: Literal[False] = False


class ReportGateResult(StrictModel):
    status: Literal["PASS", "FAIL_CLOSED"]
    report_candidate_sha256: Sha256 | None
    errors: list[str]
    checked_at_utc: datetime
    actionable: Literal[False] = False
