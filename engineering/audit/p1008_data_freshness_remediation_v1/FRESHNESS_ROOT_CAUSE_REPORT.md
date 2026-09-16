# P1008 Data Freshness Root Cause Report v1

## Scope and closure boundary

The preceding `P1008 Data Reconciliation & KPI Stack Cleanup v1` is closed at `505e8dbd70fea92befa827851e90413d21753e56`. This phase only repairs existing data-update transport and wiring and records cadence-aware freshness. It does not redesign either UI, create a score, add a provider, promote FY2026Q2, publish formal CSV, or make reports an upstream dependency.

The principal score collision was caused by overlapping UI-derived scoring and legacy fallback/hardcoded values. Report generation is downstream and was not the source of War Room KPI truth.

## Root causes

### Daily price and market activity

The official TWSE updaters were operational, but `tools/p1008_update_daily_price.cmd` redirected output before ensuring that `logs/` existed. On a fresh or isolated checkout this produced a misleading zero exit path without running the updater. The wrapper now creates only the existing log directory before redirection.

The repaired BAT dry-run found 12 official trading dates after the formal 2026-08-11 row and validated both price and market activity through 2026-08-27. The Launcher update-data pipeline runs daily price, market activity, and authority freshness in that order and returned `PASS_CANDIDATE_OVERLAY`. Formal files remain at 2026-08-11 because publication is deliberately outside this phase.

### PB

PB was not independently refreshed because its daily date follows the formal price authority. The candidate is reproducible: `252.0 / 127.12 = 1.982` after display rounding. The applicable BVPS is the canonical 2026Q1 value; no FY2026Q2 or invented BVPS is used.

### FX and macro

The source registry and updater were already present. The failure was transport-specific: urllib/proxy routing returned connection refused, PowerShell also failed, while a verified direct TLS connection could reach the existing approved Yahoo and TWSE endpoints. The existing fetcher now attempts a verified Python HTTPS transport before the existing PowerShell fallback. It rejects non-HTTPS URLs, uses the platform trust store, preserves source dates, and does not add a provider.

The 2026-08-27 candidate contains current TWD/USD, DXY, JPY/USD, VIX and WTI observations; US10Y is sourced 2026-08-26. FRED remains unavailable and the reviewed Stooq paths return HTTP 404, so the pre-existing approved Yahoo fallback is used and disclosed. BOJ rate remains missing. USD/TWD, DXY and US10Y stay in the FX sidecar; VIX and WTI stay in macro. No cross-source fill was introduced.

### Quarterly and AI evidence

The canonical financial row remains 2026Q1 with ROE 11.52%, ROIC 12.57% and FCF -325.57191. A 2026Q2 official-IR review configuration exists with publication date 2026-08-12, but freshness does not authorize its promotion.

The historical 40% AI field remains L3 and denominator-unknown. The 51% FY2026Q2 disclosure is cloud-and-networking revenue share, not AI-specific share; the AI-specific field is explicitly null. These observations do not become a score or substitute KPI.

## Launcher result

One normal `update-data` job completed `SUCCEEDED` with zero errors and `formalCsvModified=false`. Daily price and market activity were `UPDATED` as candidates; freshness was `PASS_CANDIDATE_OVERLAY`; auxiliary macro/FX candidates were generated. The isolated worktree had no archived report runtime, so its navigation gate reported a missing rolling brief. That downstream report-library state is not used here to determine KPI validity and is not a data-freshness regression.

## Disposition

Result: `PASS_WITH_OWNER_REVIEW_REQUIRED`.

The existing authorized pipeline can retrieve current official/public observations and generate traceable candidates. Owner review is still required for formal CSV append and FY2026Q2 promotion. No publication, push, merge, UI redesign, score change, or report generation was performed.
