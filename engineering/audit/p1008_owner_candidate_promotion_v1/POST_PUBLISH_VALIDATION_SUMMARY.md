# P1008 Post-Publish Validation Summary v1

## Final decision

`PASS`

P1008 Data Freshness Remediation v1 is `CLOSED / PASS`. Formal data is current through `2026-08-27` where applicable. The principal score collision remains correctly attributed to overlapping UI-derived scoring and legacy fallback/hardcoded values. Report generation is downstream and was not the source of War Room KPI truth.

## Integrity gates

| Gate | Evidence | Result |
|---|---|---|
| Daily price | 139 rows, latest 2026-08-27, no duplicate date, exact 12-row suffix | PASS |
| Market activity | 89 rows, latest 2026-08-27, no duplicate date, exact 12-row suffix | PASS |
| Daily/market atomicity | Both advanced from 2026-08-11 to 2026-08-27 in one rollback-guarded transaction | PASS |
| PB | `252 / 127.12`, 2026Q1, stored 1.982 | PASS |
| FX | 13 rows, latest 2026-08-27, `Actionable=false`, US10Y source date retained as 2026-08-26 | PASS |
| Macro | 40 rows, latest 2026-08-27, VIX/WTI ownership retained | PASS |
| Manifest | Every modified data file hash, size, row count, and latest date synchronized | PASS |
| Historical immutability | Prior formal ranges preserved; only authorized suffix/row appended | PASS |
| Master/Q2 | Master hash unchanged; 2026Q1 canonical; Q2 Owner-review only | PASS |
| AI semantic guard | 40% historical L3 only; 51% cloud/networking, not AI | PASS |

## Launcher idempotency

### First normal update-data run

- Job: `20260827-230143-update-data`
- Status: `SUCCEEDED`
- Daily price: `NO_NEW_DATA`
- Market activity: `NO_NEW_MARKET_ACTIVITY`
- Authority freshness: `PASS / FORMAL_AUTHORITY`
- Owner publish required by freshness validator: `false`
- Formal CSV modified: `false`

### Second normal update-data run

- Job: `20260827-230505-update-data`
- Status: `SUCCEEDED`
- Daily price: `NO_NEW_DATA`
- Market activity: `NO_NEW_MARKET_ACTIVITY`
- Authority freshness: `PASS / FORMAL_AUTHORITY`
- Owner publish required by freshness validator: `false`
- Formal CSV modified: `false`
- All five formal file hashes remained unchanged between runs.

### Final manifest-normalization verification

- Job: `20260827-232248-update-data`.
- Status: `SUCCEEDED`.
- Daily price: `NO_NEW_DATA`.
- Market activity: `NO_NEW_MARKET_ACTIVITY`.
- Authority freshness: `PASS / FORMAL_AUTHORITY`.
- Formal CSV modified: `false`.
- Canonical UTF-8/LF manifest hash remained `92813936E828C7E4740F0781EC8AC010D901F0CF811F36BCC71054460B280C73`.

Runtime fetch can still stage same-date observation candidates when a source value changes later in the day. These candidates remain review-only, are rejected as duplicate formal keys, and do not alter the formal-authority freshness result or any formal CSV.

## UI validation

### New UI v24

- Existing six-card structure unchanged.
- All six numeric IC scores remain `N/A / 未提供正式分數`.
- Current Close: `252.0`.
- Current PB: `1.982x（推算）`.
- BVPS: `127.12`; period `2026Q1`.
- USD/TWD: FX sidecar only; VIX: Macro only; DXY: FX sidecar only.
- No browser-side score resurrection or cross-source fill.
- `NaN=0`, `undefined=0`, console error `=0`.

### Old UI

- Existing five-dimension model retained without redesign.
- Current Close: `252.00`.
- Current PB: `1.982x`.
- AI revenue share remains `N/A`; no 40% or 51% resurrection.
- `NaN=0`, `undefined=0`, console error `=0`.

## Report pipeline

- Report governance and authority-read tests passed.
- Trigger decision remained `NO_MATERIAL_CHANGE`.
- Default Launcher update does not run the report generator.
- No tracked report, report manifest, or `latest_report.html` changed.
- Report generated: `NO` (expected).
- Report write-back to War Room: `NO`.

## Tests

- Focused publication, update, freshness, reconciliation, source-ownership, report-trigger, and report-governance suite: `123 tests`.
- Passed: `123`.
- Failed: `0`.
- Errors: `0`.
- Introduced regression: `0`.

## Closure

- Data Reconciliation Cleanup v1: `CLOSED / PASS`, head `505e8dbd70fea92befa827851e90413d21753e56`.
- Data Freshness Remediation v1 implementation: `03594ef01e510e2e9cd179f1076cb6dbdcd896c5`.
- Owner promotion: `PASS`.
- Formal data horizon: `2026-08-27` where applicable.
- Rollback required: `NO`.
- Push: `NO`.
- Merge: `NO`.
