# P1008 Historical Research Data Contract V1

This contract extends, but never rewrites, the verified production authority.

## Evidence classes

- `T0_DIRECT_OFFICIAL`: directly reported by Hon Hai, MOPS, TWSE, or another primary regulator.
- `T1_EXACT_DERIVED`: exact arithmetic from compatible T0 observations. Formula and input observation IDs are mandatory.
- `T2_ESTIMATED_DERIVED`: reproducible estimate with assumptions, uncertainty, bounds where calculable, confidence and limitations.
- `T3_EXTERNAL_CROSSCHECK`: external research cross-check. It cannot overwrite T0/T1 and conflicting observations are never averaged automatically.
- `T4_MODEL_SCENARIO`: forward assumption only. It is prohibited from historical-actual series.

The availability sequence is local governed source, official external source, T1 derivation, T2 estimate, T3 cross-check, then `UNAVAILABLE` only when none is defensible.

## Cash-flow period contract

Reported cumulative `Q1/H1/9M/FY` observations and standalone `Q1/Q2/Q3/Q4` observations remain separate. Standalone quarters may be T1 only when compatible cumulative statements can be subtracted. Capex is stored as a positive cash outflow and `FCF = CFO - Capex`.

## Share and per-share contracts

`PERIOD_END_SHARES` and `WEIGHTED_AVERAGE_SHARES` are different series.

`FCF_PER_SHARE_V1 = period FCF / compatible basic weighted-average ordinary shares`.

Denominator precedence is T0 official weighted-average shares, T1 exact-derived compatible shares, then T2 estimated weighted-average shares. A T2 denominator makes FCF/share no stronger than T2. Period-end shares are forbidden as the default FCF/share denominator.

`BVPS = period-end parent equity / period-end ordinary shares`; weighted-average shares are forbidden for BVPS.

Where reported basic EPS is rounded to two decimals, T2 weighted-average shares store the point estimate and bounds using the unrounded EPS interval `[E-0.005, E+0.005)`. Reader-facing output uses reasonable precision and the word `估算` or `推估`.

## Estimate reconciliation

An estimate is not deleted when an official value appears. The research layer preserves estimated value, official value, absolute and percentage differences, method and one of `ESTIMATE_ACTIVE`, `OFFICIAL_REPLACEMENT_AVAILABLE`, `RECONCILED`, or `ESTIMATE_REJECTED`. T0 becomes canonical only through explicit governed reconciliation.

## Decision and presentation boundaries

T0/T1 may support a decision transition when the existing decision contract is met. Uncorroborated T2 is limited to WATCH/PARTIAL/research direction. T3 is cross-check support and T4 is scenario only. No layer is actionable by itself.

Charts and the formal appendix preserve evidence class, basis and formulas. `CCC_GOVERNED` and `CCC_EST_V1` remain separate series. The appendix lists metric, period, displayed value, class, formula, inputs, sources, basis, assumptions, uncertainty, confidence, limitations and reconciliation status.

## Source acquisition and storage

Discovery uses the existing research integration where available. Primary documents, not search snippets, support T0 observations. The versioned source catalog stores locator, publisher, period, metric family and content hash. Raw downloaded documents remain transient under git-ignored runtime until a separately governed persistent archive is authorized.

Production CSV, manifest, RULE, SQLite, HOLD, MIDR and MRD are read-only to this research layer. Promotion from T2/T3 to T0 is never automatic.
