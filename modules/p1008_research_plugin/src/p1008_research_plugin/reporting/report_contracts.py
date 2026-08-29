"""Typed contract for Phase B1 report and chart candidates."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

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


MONTHLY_REVENUE_SECTION_IDS = (
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

QUARTERLY_EARNINGS_SECTION_IDS = (
    "REPORT_IDENTITY_AND_CUTOFF",
    "EXECUTIVE_SUMMARY",
    "GOVERNANCE_COMMITMENT_EXECUTION",
    "Q2_FINANCIAL_SUMMARY",
    "GROWTH_QUALITY",
    "OPERATING_LEVERAGE",
    "MARGIN_QUALITY",
    "EARNINGS_TO_CASH_QUALITY",
    "WORKING_CAPITAL_CAPITAL_REQUIREMENT",
    "CAPITAL_EFFICIENCY",
    "ROE_DUPONT_INTERPRETATION",
    "PROFIT_PASS_THROUGH",
    "AI_SERVER_CLOUD_NETWORKING",
    "GOVERNANCE_TARGET_VS_ACTUAL",
    "VALUATION",
    "HOLDING_THESIS",
    "NEW_MONEY_VALUATION_CONTEXT",
    "GREEN_SIGNALS",
    "NON_GREEN_DEEP_REVIEW",
    "COUNTEREVIDENCE_LIMITATIONS",
    "INVALIDATION_CONDITIONS",
    "NEXT_VALIDATION_DATE_AND_EVENT",
    "RETIREMENT_CASHFLOW_IMPLICATION",
    "ACTIONABLE_FALSE_DISCLAIMER",
)

QUARTERLY_VISIBLE_GROUPS = (
    ("投資與企業價值結論", ("REPORT_IDENTITY_AND_CUTOFF", "EXECUTIVE_SUMMARY", "HOLDING_THESIS")),
    ("本季真正改變了什麼", ("Q2_FINANCIAL_SUMMARY",)),
    ("3+3戰略落地與價值轉化", ("GOVERNANCE_COMMITMENT_EXECUTION", "GREEN_SIGNALS")),
    ("成長品質與產品組合", ("GROWTH_QUALITY",)),
    ("營運槓桿與費用吸收", ("OPERATING_LEVERAGE",)),
    ("利潤率與獲利傳導", ("MARGIN_QUALITY", "PROFIT_PASS_THROUGH")),
    ("營運資金與現金轉化", ("WORKING_CAPITAL_CAPITAL_REQUIREMENT", "EARNINGS_TO_CASH_QUALITY")),
    ("資本效率與ROIC", ("CAPITAL_EFFICIENCY",)),
    ("ROE、股東權益與每股淨值複利", ("ROE_DUPONT_INTERPRETATION",)),
    ("AI成長品質與價值轉化", ("AI_SERVER_CLOUD_NETWORKING",)),
    ("估值、P/B、股利與新資金情境", ("VALUATION", "NEW_MONEY_VALUATION_CONTEXT")),
    ("治理、企業價值與退休任務總結", ("GOVERNANCE_TARGET_VS_ACTUAL", "NON_GREEN_DEEP_REVIEW", "COUNTEREVIDENCE_LIMITATIONS", "INVALIDATION_CONDITIONS", "NEXT_VALIDATION_DATE_AND_EVENT", "RETIREMENT_CASHFLOW_IMPLICATION", "ACTIONABLE_FALSE_DISCLAIMER")),
)

REQUIRED_SECTION_IDS = MONTHLY_REVENUE_SECTION_IDS


def required_section_ids(event_type: str) -> tuple[str, ...]:
    if event_type == "QUARTERLY_EARNINGS":
        return QUARTERLY_EARNINGS_SECTION_IDS
    return MONTHLY_REVENUE_SECTION_IDS


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
    event_type: Literal["MONTHLY_REVENUE", "QUARTERLY_EARNINGS"]
    generated_at_utc: datetime
    report_contract_version: Literal["1.0"] = "1.0"
    analysis_packet_sha256: Sha256
    authority_manifest_sha256: Sha256
    primary_investor_question: NonEmpty
    thesis_state: OverallThesis
    evidence_bound_facts: list[NonEmpty] = Field(min_length=1)
    evidence_references: list[EvidenceReference] = Field(min_length=1)
    sections: list[ReportSection] = Field(min_length=20, max_length=24)
    actionable: Literal[False]

    @model_validator(mode="after")
    def sections_are_complete_and_ordered(self) -> "ReportCandidate":
        actual = tuple(section.section_id for section in self.sections)
        if actual != required_section_ids(self.event_type):
            raise ValueError("report sections do not match the approved Phase B1 order")
        known = {reference.evidence_id for reference in self.evidence_references}
        for section in self.sections:
            if not set(section.evidence_ids).issubset(known):
                raise ValueError(f"section cites unknown evidence: {section.section_id}")
        return self


class EditorialExecutionAuthorization(StrictModel):
    """One-run Owner authorization required before live editorial dispatch."""

    record_type: Literal["P1008_EDITORIAL_EXECUTION_AUTHORIZATION"] = (
        "P1008_EDITORIAL_EXECUTION_AUTHORIZATION"
    )
    run_id: NonEmpty
    task_id: Literal["WAR_REPORT_EDITORIAL_SYNTHESIS"] = (
        "WAR_REPORT_EDITORIAL_SYNTHESIS"
    )
    template_id: NonEmpty
    template_version: NonEmpty
    model: Literal["gpt-5.6-sol"]
    max_calls: Literal[1] = 1
    fallback_allowed: Literal[False] = False
    web_search_allowed: Literal[False] = False
    publication: Literal[False] = False
    actionable: Literal[False] = False
    owner_review_required: Literal[True] = True
    owner_authorized: Literal[True]
    authorization_reference: NonEmpty


class ModelProvenance(StrictModel):
    """Typed materialization of the existing report-governance provenance contract."""

    model_provenance_id: NonEmpty
    model_surface: Literal["OPENAI_AGENTS_SDK", "DETERMINISTIC_TEST_DOUBLE"]
    model_identifier: Literal["gpt-5.6-sol"]
    input_receipt_ids: list[NonEmpty] = Field(min_length=1)
    output_artifact_hash: Sha256
    started_at_utc: datetime
    completed_at_utc: datetime
    status: Literal["EXECUTED_LIVE", "EXECUTED_TEST_DOUBLE"]
    usage_metadata: dict[str, Any] | None = None
    billing_metadata: None = None
    model_change_did_not_modify_runtime_configuration: Literal[True] = True
    project_runtime_model_allowlist_unchanged: Literal[True] = True
    actionable: Literal[False] = False

    @model_validator(mode="after")
    def timestamps_are_ordered(self) -> "ModelProvenance":
        if self.started_at_utc.utcoffset() is None or self.completed_at_utc.utcoffset() is None:
            raise ValueError("editorial provenance timestamps must be timezone-aware")
        if self.completed_at_utc < self.started_at_utc:
            raise ValueError("editorial completion precedes start")
        return self


class EditorialGovernance(StrictModel):
    actionable: Literal[False] = False
    publication: Literal[False] = False
    owner_review_required: Literal[True] = True


class EditorialResultEnvelope(StrictModel):
    """Receipt-backed result around the existing ReportCandidate contract."""

    schema_version: Literal["1.0"] = "1.0"
    run_id: NonEmpty
    task_id: Literal["WAR_REPORT_EDITORIAL_SYNTHESIS"] = (
        "WAR_REPORT_EDITORIAL_SYNTHESIS"
    )
    template_id: NonEmpty
    template_version: NonEmpty
    input_research_pack_sha256: Sha256
    editorial_text: NonEmpty
    editorial_output_sha256: Sha256
    report_candidate: ReportCandidate
    model_provenance: ModelProvenance
    provider_response_id: NonEmpty | None
    governance: EditorialGovernance
    execution_status: Literal["EXECUTED_LIVE", "EXECUTED_TEST_DOUBLE"]
    validation_status: Literal["PASS"]

    @model_validator(mode="after")
    def receipt_binds_exact_output(self) -> "EditorialResultEnvelope":
        from ..phaseb1_common import canonical_json_bytes, sha256_bytes

        if self.run_id != self.report_candidate.run_id:
            raise ValueError("editorial result run identity mismatch")
        if self.input_research_pack_sha256 != self.report_candidate.analysis_packet_sha256:
            raise ValueError("editorial input research-pack hash mismatch")
        actual_output_sha = sha256_bytes(
            canonical_json_bytes(
                self.report_candidate.model_dump(mode="json", by_alias=True)
            )
        )
        if self.editorial_output_sha256 != actual_output_sha:
            raise ValueError("editorial output hash mismatch")
        expected_text = "\n\n".join(
            f"{section.title_zh}\n{section.body_zh}"
            for section in self.report_candidate.sections
        )
        if self.editorial_text != expected_text:
            raise ValueError("editorial text does not match the governed report candidate")
        if (
            self.execution_status == "EXECUTED_LIVE"
            and not self.provider_response_id
        ):
            raise ValueError("live editorial receipt requires a provider response ID")
        if (
            self.execution_status == "EXECUTED_LIVE"
            and self.model_provenance.model_surface != "OPENAI_AGENTS_SDK"
        ):
            raise ValueError("live editorial receipt requires OpenAI Agents SDK provenance")
        if self.model_provenance.output_artifact_hash != self.editorial_output_sha256:
            raise ValueError("model provenance output hash mismatch")
        if self.model_provenance.status != self.execution_status:
            raise ValueError("model provenance execution status mismatch")
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
    observation_zh: NonEmpty
    interpretation_zh: NonEmpty
    p1008_implication_zh: NonEmpty
    strategic_implication_zh: NonEmpty = "本圖不單獨改變長期策略判斷。"
    enterprise_value_implication_zh: NonEmpty = "需與獲利、資本及現金證據共同判讀。"
    next_checkpoint_zh: NonEmpty = "下一個正式財務揭露。"
    visualization_type: Literal[
        "QUANTITATIVE_CHART", "EVIDENCE_TABLE", "STATUS_MATRIX", "SCENARIO_MATRIX"
    ] = "QUANTITATIVE_CHART"
    signal: Literal["GREEN", "YELLOW", "RED", "WHITE"]
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
    sentence_completeness_passed: bool
    numeric_units_preserved: bool
    spoken_technical_codes_absent: bool
    balanced_punctuation_passed: bool
    no_mechanical_truncation: bool
    all_segments_semantically_complete: bool
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
    segment_integrity: dict[NonEmpty, bool]
    sentence_integrity_status: Literal["PASS", "FAIL"]
    numeric_unit_status: Literal["PASS", "FAIL"]
    sentence_completeness_passed: bool
    numeric_units_preserved: bool
    spoken_technical_codes_absent: bool
    balanced_punctuation_passed: bool
    no_mechanical_truncation: bool
    all_segments_semantically_complete: bool
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
