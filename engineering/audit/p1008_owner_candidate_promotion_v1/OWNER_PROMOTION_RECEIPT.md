# P1008 Owner Candidate Promotion Receipt v1

## Authorization and lineage

- Owner authorization: `P1008 OWNER CANDIDATE PROMOTION + POST-PUBLISH VALIDATION V1 / APPROVED`
- Source phase: `P1008 Data Freshness Remediation v1`
- Source branch: `agent/p1008-data-freshness-remediation-v1`
- Source implementation head: `03594ef01e510e2e9cd179f1076cb6dbdcd896c5`
- Predecessor closure head: `505e8dbd70fea92befa827851e90413d21753e56`
- Promotion branch: `agent/p1008-data-freshness-owner-promotion-v1`
- Promotion commit: `SELF` (the atomic commit containing this receipt; resolve with `git rev-parse HEAD`)
- Publication timestamp: `2026-08-27T14:52:22Z`
- Actionable: `false`

## Promotion result

| Dataset | Prior latest | New latest | Rows promoted | Result |
|---|---:|---:|---:|---|
| `data/2317_daily_price.csv` | 2026-08-11 | 2026-08-27 | 12 | PASS |
| `data/2317_daily_market_activity.csv` | 2026-08-11 | 2026-08-27 | 12 | PASS |
| `data/fx_trend_observations.csv` | 2026-07-27 | 2026-08-27 | 1 | PASS |
| `data/macro_snapshot.csv` | 2026-07-10 | 2026-08-27 | 1 | PASS |

The daily-price and market-activity datasets were validated together and promoted under one outer rollback transaction. Their authorized trading-date suffix is `2026-08-12`, `08-13`, `08-14`, `08-17`, `08-18`, `08-19`, `08-20`, `08-21`, `08-24`, `08-25`, `08-26`, and `08-27`. Historical formal rows remained an exact semantic prefix.

## PB recomputation

- Date: `2026-08-27`
- Formal Close: `252.0`
- Canonical BVPS: `127.12`
- Canonical financial period: `2026Q1`
- Formula: `PB_daily = Close / BVPS_ref`
- Full calculation: `252.0 / 127.12 = 1.982378...`
- Stored/display value: `1.982x`
- Classification: `DERIVED_VERIFIED（推算且已驗證）`
- No Q2 BVPS was used and no static PB constant was introduced.

## Source-date preservation

- Stock close: `2026-08-27`, `TWSE_STOCK_DAY_OFFICIAL`
- VIX: `2026-08-27`, `YAHOO_FINANCE_VIX`
- WTI: `2026-08-27`, `YAHOO_FINANCE_WTI`
- TWD/USD: `2026-08-27`, `YAHOO_FINANCE_TWD_USD`
- DXY: `2026-08-27`, `YAHOO_FINANCE_DXY`
- US10Y: `2026-08-26`, `YAHOO_FINANCE_US10Y` (not rewritten to 2026-08-27)
- Fed rate: formal carry-forward; no fabricated source date
- BOJ rate and US-JP spread: remain missing

## Publication controls

- Existing Owner publishers were used; no replacement publisher was created.
- Publisher journals report `PUBLISHED`, `rollback_performed=false`.
- Final authority manifest hash: `92813936E828C7E4740F0781EC8AC010D901F0CF811F36BCC71054460B280C73` (canonical UTF-8/LF bytes).
- Manifest hash, byte length, row count, and latest-date metadata match the promoted files.
- Launcher update-data run 1: `SUCCEEDED`, formal CSV modified `false`, freshness `PASS`.
- Launcher update-data run 2: `SUCCEEDED`, formal CSV modified `false`, freshness `PASS`.
- Final post-normalization Launcher verification: job `20260827-232248-update-data`, `SUCCEEDED`, formal CSV modified `false`, freshness `PASS`; canonical manifest hash unchanged.
- Both runs reported daily price and market activity `NO_NEW_DATA`; no duplicate formal rows were created.
- The final verification run also reported daily price `NO_NEW_DATA` and market activity `NO_NEW_MARKET_ACTIVITY`.

## Scope boundaries

- `data/2317_master_v9.csv` is byte-identical to the source head (`0BB2FEC6FA3035AC642738BC12EA6959C81C8A79D5221E694BF780427051CF79`).
- Canonical financial period remains `2026Q1`; FY2026Q2 remains `OWNER_REVIEW_ONLY`.
- AI 40% remains historical L3 with unknown denominator and is not a current score input.
- 51% remains cloud-and-networking revenue share, not AI revenue share.
- Six-IC scores were not restored. No UI redesign, threshold change, actionable change, report generation, push, or merge occurred.

## Verification and rollback

- Affected automated tests: `123/123 PASS`.
- Browser validation: old UI and new UI show Close `252` and PB `1.982x`; six new-UI IC scores remain N/A; `NaN=0`, `undefined=0`, fabricated score fallback `=0`, console errors `=0`.
- Report authority/read and no-material-change governance: PASS; no report generated and no report file changed.
- Rollback backup was retained through all P0 checks.
- Rollback required: `NO`.
- Publication result: `PASS`.
