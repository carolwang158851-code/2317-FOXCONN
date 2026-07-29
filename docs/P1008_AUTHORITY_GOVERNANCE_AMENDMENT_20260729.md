# P1008 Final Integration Authority Governance Amendment — 2026-07-29

Scope ID: `P1008-FINAL-INTEGRATION-RECONCILIATION-20260729`

This amendment reconciles the completed Phase A authority-data closure with the
previously verified Cash Flow governance from Draft PR #4. It is not a new
Phase A implementation and does not start Phase B.

## Integrated seven-file baseline

The active baseline contains exactly:

1. `data/2317_master_v9.csv`
2. `data/2317_daily_price.csv`
3. `data/2317_daily_market_activity.csv`
4. `data/2317_cash_flow_authority.csv`
5. `data/macro_snapshot.csv`
6. `data/macro_event_observations.csv`
7. `data/fx_trend_observations.csv`

The adapter rejects a missing listed file, a hash mismatch, a hidden
cash-flow authority, and any unknown eighth authority path. The prior five-file
legacy, Cash Flow six-file, and Phase A closure six-file definitions remain
versioned historical evidence; they are not rewritten as the active baseline.

## Selective PR #4 reconciliation

Only the official two-row Cash Flow CSV, schema/hash/formula governance,
read-only adapter support, baseline fixture, fail-closed negative tests, and
this governance explanation are carried forward. PR #4's older Daily Price
CSV, authority manifest, cutoffs, and authority hashes are explicitly excluded.

The active Cash Flow cutoff is `2026Q1`. Each row retains the Hon Hai report
URL, pages, source document SHA-256, official verification status, transparent
FCF formulas, and `actionable=false`.

## Receipt and evidence continuity

The Stage 1, Stage 2A, Stage 2B, and Final Phase A Closure receipts are
historical records and remain unchanged. The approved Macro Row Identity
evidence is committed byte-for-byte under
`contracts/p1008_research_plugin/acceptance/v1.1/evidence/`.

The new Final Integration Amendment Receipt references the prior Final Closure
Receipt, committed Row Identity evidence, integrated authority manifest, and
all seven current authority file hashes without overwriting the historical
receipt chain.

## Boundaries

- Candidate-first Launcher behavior remains unchanged.
- Automatic formal CSV publication and automatic report generation remain off.
- RULE, HOLD, MIDR, MRD, Runtime SQLite, schedules, models, and API keys are
  unchanged.
- OpenAI, Web Search, and Canva calls are zero.
- All outputs remain `actionable=false`.
