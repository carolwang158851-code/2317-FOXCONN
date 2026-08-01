"""Typed Phase B1 analysis contract.

The models intentionally separate facts from inference and prohibit executable
advice.  JSON aliases are the public contract; Python attributes remain
snake_case for readability.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


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


class TrendStatus(str, Enum):
    IMPROVING = "IMPROVING"
    STABLE = "STABLE"
    WATCH = "WATCH"
    WEAKENING = "WEAKENING"
    BROKEN = "BROKEN"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ValuationStatus(str, Enum):
    DESCRIPTIVE_ONLY = "DESCRIPTIVE_ONLY"
    ATTRACTIVE = "ATTRACTIVE"
    FAIR = "FAIR"
    FAIR_TO_EXPENSIVE = "FAIR_TO_EXPENSIVE"
    EXPENSIVE = "EXPENSIVE"
    EXTREME = "EXTREME"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class MarketRegimeName(str, Enum):
    AI_EUPHORIA = "AI_EUPHORIA"
    ETF_FOMO = "ETF_FOMO"
    EARNINGS_REASSESSMENT = "EARNINGS_REASSESSMENT"
    BROAD_CORRECTION = "BROAD_CORRECTION"
    PANIC = "PANIC"
    DIVIDEND_FOCUS = "DIVIDEND_FOCUS"
    FUNDAMENTAL_DOWNTURN = "FUNDAMENTAL_DOWNTURN"
    RANGE_BOUND = "RANGE_BOUND"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class LinkStatus(str, Enum):
    VERIFIED = "VERIFIED"
    INFERRED = "INFERRED"
    UNCONFIRMED = "UNCONFIRMED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class OverallThesis(str, Enum):
    IMPROVING = "IMPROVING"
    MAINTAINED = "MAINTAINED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class NewMoneyView(str, Enum):
    ADD_ZONE = "ADD_ZONE"
    WAIT = "WAIT"
    BLOCK = "BLOCK"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ExistingHoldingView(str, Enum):
    HOLD = "HOLD"
    REVIEW = "REVIEW"
    TRIM_CANDIDATE = "TRIM_CANDIDATE"
    SELL_REVIEW = "SELL_REVIEW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class FactOrInference(str, Enum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"


class ConfidenceClass(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EventWindowStatus(str, Enum):
    CALCULATED = "CALCULATED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class MetricAssessment(StrictModel):
    value: str | None
    unit: NonEmpty
    period: NonEmpty
    status: TrendStatus
    evidence_ids: list[NonEmpty]
    limitations: list[NonEmpty]

    @model_validator(mode="after")
    def missing_is_insufficient(self) -> "MetricAssessment":
        if self.value is None and self.status is not TrendStatus.INSUFFICIENT_DATA:
            raise ValueError("missing metric values must be INSUFFICIENT_DATA")
        if self.value == "0" and self.limitations:
            raise ValueError("zero cannot stand in for missing data")
        return self


class FinancialTrend(StrictModel):
    revenue: MetricAssessment
    gross_margin: MetricAssessment
    operating_margin: MetricAssessment
    eps: MetricAssessment
    eps_ttm: MetricAssessment
    roe: MetricAssessment
    roic: MetricAssessment
    operating_cash_flow: MetricAssessment
    free_cash_flow: MetricAssessment
    dividend_safety: MetricAssessment
    balance_sheet_safety: MetricAssessment


class ValuationAnalysis(StrictModel):
    current_price: str
    current_pb: str
    governed_historical_pb_position: str
    roe_support: TrendStatus
    earnings_support: TrendStatus
    valuation_status: ValuationStatus
    valuation_policy_id: NonEmpty | None = None
    data_window: NonEmpty
    limitations: list[NonEmpty]

    @model_validator(mode="after")
    def unapproved_policy_is_descriptive_only(self) -> "ValuationAnalysis":
        evaluative = {
            ValuationStatus.ATTRACTIVE,
            ValuationStatus.FAIR,
            ValuationStatus.FAIR_TO_EXPENSIVE,
            ValuationStatus.EXPENSIVE,
            ValuationStatus.EXTREME,
        }
        if self.valuation_policy_id is None and self.valuation_status in evaluative:
            raise ValueError("evaluative valuation status requires an approved valuation policy")
        return self


class RecentPriceContext(StrictModel):
    return_windows: dict[NonEmpty, str]
    data_window: NonEmpty


class EventWindowReaction(StrictModel):
    status: EventWindowStatus
    publication_date: date | None
    return_windows: dict[NonEmpty, str]
    benchmark_adjusted_return: str | None
    limitations: list[NonEmpty]

    @model_validator(mode="after")
    def calculated_windows_require_a_date(self) -> "EventWindowReaction":
        if self.status is EventWindowStatus.CALCULATED:
            if self.publication_date is None or not self.return_windows:
                raise ValueError("calculated event windows require publication date and returns")
        elif self.return_windows:
            raise ValueError("insufficient event window cannot contain calculated returns")
        return self


class PriceAndMarketActivity(StrictModel):
    price_trend: TrendStatus
    recent_price_context: RecentPriceContext
    event_window_reaction: EventWindowReaction
    volume_trend: TrendStatus
    volume_percentile: str
    transaction_activity: str
    abnormal_activity_flag: bool
    data_limitations: list[NonEmpty]


class RegimeCondition(StrictModel):
    condition_id: NonEmpty
    description: NonEmpty
    result: Literal["PASS", "FAIL", "INSUFFICIENT_DATA"]
    evidence_ids: list[NonEmpty]


class MarketRegime(StrictModel):
    primary_regime: MarketRegimeName
    evidence_ids: list[NonEmpty]
    confidence: ConfidenceClass
    evaluated_conditions: list[RegimeCondition] = Field(min_length=1)
    alternative_regime: MarketRegimeName
    invalidation_condition: NonEmpty


class MarketPsychology(StrictModel):
    classification: Literal["INFERENCE"] = "INFERENCE"
    interpretation: NonEmpty
    evidence_basis: list[NonEmpty]
    alternative_explanation: NonEmpty
    counter_evidence: list[NonEmpty]
    confidence: ConfidenceClass
    invalidation_condition: NonEmpty


class EventImpactLink(StrictModel):
    from_node: NonEmpty
    to_node: NonEmpty
    status: LinkStatus
    explanation: NonEmpty
    evidence_ids: list[NonEmpty]


class ThesisScorecard(StrictModel):
    earnings_quality: TrendStatus
    ai_monetization: TrendStatus
    dividend_safety: TrendStatus
    balance_sheet: TrendStatus
    valuation: TrendStatus
    overall_thesis: OverallThesis
    evidence_ids: list[NonEmpty]


class InvestorViews(StrictModel):
    new_money_view: NewMoneyView
    existing_holding_view: ExistingHoldingView
    trim_review: Literal["NOT_TRIGGERED", "REVIEW_REQUIRED"]
    sell_review: Literal["NOT_TRIGGERED", "REVIEW_REQUIRED"]
    rationale: NonEmpty
    actionable: Literal[False]


class AudienceLens(StrictModel):
    lens_id: Literal[
        "ACCUMULATION_35_45",
        "RETIREMENT_TRANSITION_46_60",
        "RETIREMENT_INCOME_60_PLUS",
    ]
    narrative: NonEmpty
    decision_focus: NonEmpty
    non_personalized: Literal[True] = True


class MaterialConclusion(StrictModel):
    conclusion_id: NonEmpty
    statement: NonEmpty
    fact_or_inference: FactOrInference
    evidence_ids: list[NonEmpty] = Field(min_length=1)
    source_tier: NonEmpty
    source_date: NonEmpty
    data_cutoff: NonEmpty
    confidence: ConfidenceClass
    alternative_explanation: NonEmpty
    counter_evidence: list[NonEmpty]
    missing_evidence: list[NonEmpty]
    invalidation_condition: NonEmpty
    next_validation_event: NonEmpty


class AnalysisPacket(StrictModel):
    record_type: Literal["P1008_ANALYSIS_PACKET"] = "P1008_ANALYSIS_PACKET"
    run_id: NonEmpty
    event_type: Literal["MONTHLY_REVENUE"]
    generated_at_utc: datetime
    authority_manifest_sha256: Sha256
    authority_file_hashes: dict[NonEmpty, Sha256]
    authority_data_cutoffs: dict[NonEmpty, NonEmpty]
    analysis_contract_version: Literal["1.0"] = "1.0"
    input_evidence_hashes: dict[NonEmpty, Sha256]
    deterministic_mode: Literal[True] = True
    financial_trend: FinancialTrend
    valuation_analysis: ValuationAnalysis
    price_and_market_activity: PriceAndMarketActivity
    market_regime: MarketRegime
    market_psychology: MarketPsychology
    event_impact_chain: list[EventImpactLink] = Field(min_length=6)
    thesis_scorecard: ThesisScorecard
    investor_views: InvestorViews
    audience_lenses: list[AudienceLens] = Field(min_length=3, max_length=3)
    material_conclusions: list[MaterialConclusion] = Field(min_length=1)
    source_evidence_ids: list[NonEmpty] = Field(min_length=1)
    actionable: Literal[False]

    @model_validator(mode="after")
    def enforce_analysis_boundary(self) -> "AnalysisPacket":
        expected = {
            "ACCUMULATION_35_45",
            "RETIREMENT_TRANSITION_46_60",
            "RETIREMENT_INCOME_60_PLUS",
        }
        actual = {lens.lens_id for lens in self.audience_lenses}
        if actual != expected:
            raise ValueError("analysis packet requires exactly the three approved audience lenses")
        if self.generated_at_utc.utcoffset() is None or self.generated_at_utc.utcoffset().total_seconds() != 0:
            raise ValueError("generatedAtUtc must be timezone-aware UTC")
        evidence = set(self.source_evidence_ids)
        governed_groups = [
            self.market_regime.evidence_ids,
            self.market_psychology.evidence_basis,
            self.thesis_scorecard.evidence_ids,
            *[item.evidence_ids for item in self.event_impact_chain],
            *[item.evidence_ids for item in self.market_regime.evaluated_conditions],
        ]
        governed_groups.extend(
            getattr(self.financial_trend, name).evidence_ids
            for name in self.financial_trend.__class__.model_fields
        )
        if any(not set(group).issubset(evidence) for group in governed_groups):
            raise ValueError("analysis component cites unknown evidence")
        for conclusion in self.material_conclusions:
            if not set(conclusion.evidence_ids).issubset(evidence):
                raise ValueError("material conclusion cites unknown evidence")
        return self


class AnalysisGateResult(StrictModel):
    status: Literal["PASS", "FAIL_CLOSED"]
    analysis_packet_sha256: Sha256 | None
    errors: list[str]
    warnings: list[str]
    checked_at_utc: datetime
    actionable: Literal[False] = False


JsonObject = dict[str, Any]
