# P1008 Analysis Contract v1.0

This additive contract governs the deterministic Phase B1 `MONTHLY_REVENUE`
vertical slice. It does not modify any frozen Research Plugin contract.

## Responsibility

The Analysis Layer reads the seven-file Authority baseline through the
read-only Authority Adapter and consumes Evidence Packets only after the
existing Packet Gateway passes schema, freshness, source, route, and Evidence
ID gates. It produces one `analysis_packet.json`; it does not call a model,
search the web, publish formal data, write Runtime SQLite, or change rules.

## Status vocabularies

- Trend: `IMPROVING`, `STABLE`, `WATCH`, `WEAKENING`, `BROKEN`,
  `INSUFFICIENT_DATA`.
- Valuation: `DESCRIPTIVE_ONLY` is mandatory unless an Owner-approved
  valuation policy ID supplies explicit classification thresholds. Evaluative
  labels remain schema vocabulary but fail closed without that policy.
- Market regime: `AI_EUPHORIA`, `ETF_FOMO`, `EARNINGS_REASSESSMENT`,
  `BROAD_CORRECTION`, `PANIC`, `DIVIDEND_FOCUS`, `FUNDAMENTAL_DOWNTURN`,
  `RANGE_BOUND`, `INSUFFICIENT_DATA`.
- Event links: `VERIFIED`, `INFERRED`, `UNCONFIRMED`, `NOT_APPLICABLE`.
- Thesis: `IMPROVING`, `MAINTAINED`, `REVIEW_REQUIRED`.
- Confidence: categorical `HIGH`, `MEDIUM`, or `LOW`; numeric confidence is
  rejected because it implies unsupported precision.

Recent trailing 1/5/20-day returns are market context, not event reaction.
Event-window returns require a unique official publication date and complete
T-1/T+1/T+5 governed price observations; otherwise the event result is
`INSUFFICIENT_DATA`. Market-regime labels are derived from stored, evidence-ID
bound conditions rather than fixed narrative assignments.

Missing data maps to `INSUFFICIENT_DATA`, never zero. Volume describes market
activity only and cannot establish investor identity or intent. AI exposure is
not AI revenue unless explicit governed evidence defines it. Negative
quarterly FCF is a watch item, not proof of structural dividend danger.

Every material conclusion carries fact/inference identity, Evidence IDs,
source tier/date, cutoff, confidence, alternative explanation,
counterevidence, missing evidence, invalidation condition, and next validation
event. All outputs are `actionable=false`.
