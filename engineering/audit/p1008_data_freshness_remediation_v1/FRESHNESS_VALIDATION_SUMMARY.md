# P1008 Data Freshness Validation Summary v1

## Closed predecessor

- CLEANUP_PHASE: `P1008 Data Reconciliation & KPI Stack Cleanup v1`
- CLEANUP_STATUS: `CLOSED / PASS`
- CLEANUP_HEAD: `505e8dbd70fea92befa827851e90413d21753e56`
- CLEANUP_BASELINE: `214e7bf8363b36b30c67707849ba1ecb4cc9e297`

## Freshness snapshot

- daily_price_latest: formal `2026-08-11`; official candidate `2026-08-27`
- market_activity_latest: formal `2026-08-11`; official candidate `2026-08-27`
- pb_latest: formal `2.069 @ 2026-08-11`; candidate `1.982 @ 2026-08-27`
- quarterly_latest: canonical `2026Q1`; `2026Q2 OWNER_REVIEW_ONLY`
- fx_latest: formal sidecar `2026-07-27`; candidate `2026-08-27`
- macro_latest: formal sidecar `2026-07-10`; candidate `2026-08-27`
- ai_evidence_latest: official IR review evidence `2026-08-12`; canonical consumer remains `2026Q1`

## Dataset disposition

- updated_datasets: `daily_price_candidate, market_activity_candidate, PB_candidate, FX_candidate, macro_candidate`
- unchanged_expected_datasets: `quarterly_financials, macro_events, canonical_AI_industry_evidence`
- stale_source_count: `0` required datasets after approved fallback evaluation
- stale_updater_count: `0`
- stale_pipeline_count: `0`
- stale_derived_count: `0`
- owner_review_required_count: `5` (`daily_price`, `market_activity`, `PB`, `FX`, `macro`)
- owner_review_only_count: `2` (`FY2026Q2`, `AI/industry evidence`)
- observation_only_count: `1` (`macro events`)

## Execution evidence

- Daily BAT dry-run: `DRY_RUN_READY`, 12 dates detected, 12 candidate dates added, one TWSE HTTP call, `actionable=false`.
- Launcher `update-data`: `SUCCEEDED`; daily price `UPDATED`; market activity `UPDATED`; freshness `PASS_CANDIDATE_OVERLAY`; `formalCsvModified=false`; errors `0`; warnings `0`.
- Macro source support: required `7/7`; VIX, WTI, TWD/USD, DXY and US10Y have traceable existing approved sources; Fed policy rate uses the existing stable-series carry rule.
- Formal data mutation: `0 files`.

## Validation gates

- focused_updater_launcher_and_audit_tests: `49/49 PASS`
- existing_reconciliation_market_and_launcher_tests: `48/48 PASS`
- baseline_differential: predecessor `48/48 PASS`; freshness branch `48/48 PASS`; introduced failures `0`
- old_UI_load: `PASS`; console errors `0`
- new_UI_load: `PASS`; six IC cards present; N/A used for unavailable scores; console errors `0`
- PB reproducibility: `252.0 / 127.12 = 1.982` at display precision
- source/as_of propagation: `PASS`
- FX source ownership: `PASS`
- Macro source ownership: `PASS`
- cross-source fallback: `0`
- fabricated fallback: `0`
- NaN rendered: `0`
- undefined rendered: `0`
- introduced_regression: `0`

## Final status

`PASS_WITH_OWNER_REVIEW_REQUIRED`

Current candidates are traceable and the existing one-click update path works. Formal promotion remains an explicit Owner action and was not performed in this phase.
