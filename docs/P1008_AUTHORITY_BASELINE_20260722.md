# P1008 Authority Baseline — 2026-07-22

Scope ID: `P1008-AUTHORITY-BASELINE-20260722`

This change establishes a committed, traceable authority baseline for the existing official cash-flow evidence and the daily-price series through 2026-07-20. It does not change P/S, UI, reports, skills, plugins, rules, decision state, or runtime SQLite.

## Permitted source workspace files

| Source path | Source Git state | Source SHA-256 |
| --- | --- | --- |
| `C:\Users\a2231\OneDrive\foxconn_dashboard\foxconn-system\CODEX_P1008_PACKAGE\data\2317_cash_flow_authority.csv` | untracked | `082ECA44A96A06F7DAE10DD33CBAF77C75DABA9B1B4DEA27B5B930F8CE8CD95C` |
| `C:\Users\a2231\OneDrive\foxconn_dashboard\foxconn-system\CODEX_P1008_PACKAGE\data\2317_daily_price.csv` | modified | `E0897D0F54E697A379D69847088BAA9D5E447CA8F9E3B088005BCEABB8BB049B` |
| `C:\Users\a2231\OneDrive\foxconn_dashboard\foxconn-system\CODEX_P1008_PACKAGE\data\CSV_AUTHORITY_MANIFEST.json` | modified | `91355D632A2645970068B770264561C81F50728341A8E394AA2782ABF412E015` |

## Daily-price reconciliation

- Starting committed authority: 104 rows through 2026-07-10; SHA-256 `3329E871C997E983D3C279996F426736BD0A288ACF2769552C964F1AE6CF8ED1`.
- Promoted authority: 111 weekday-only rows through 2026-07-20.
- Removed from the previous committed baseline after official remediation: `2026-06-19`, `2026-06-20`, `2026-07-05`, `2026-07-10`.
- Added official rows: `2026-06-22`, `2026-07-01`, `2026-07-02`, `2026-07-03`, `2026-07-09`, `2026-07-13`, `2026-07-14`, `2026-07-15`, `2026-07-16`, `2026-07-17`, `2026-07-20`.
- Corrected official closes/PB values: `2026-06-23`, `2026-06-24`, `2026-06-25`, `2026-06-26`, `2026-06-29`.
- Excluded `2026-07-19`: Sunday and `PUBLIC_MARKET_DATA`, so it is not formal price authority.
- Excluded `2026-07-21`: outside the Owner-approved 2026-07-20 cutoff.
- Verified cutoff row: 2026-07-20, Close 234.5, PB 1.845, `OFFICIAL_TWSE_A1`, `OK`.

## Cash-flow authority

The two-row authority covers 2025Q1 and 2026Q1. For 2026Q1, official inputs reconcile to core FCF of -32,557,191 thousand TWD (-325.57191 hundred-million TWD) and FCF after intangible capex of -32,857,332 thousand TWD. The source report URL, pages 10–11, document SHA-256, verification status, and `actionable=false` are retained.

## Integrity boundary

- Start SHA: `150f98ad4ae48cecf58334ac2ae995828aba601a`.
- Promoted cash-flow authority SHA-256: `D530DDFEC89766CA931876CF79AAFD732D47BB0B66FA882B7DADE9EE338F6BFF`.
- Promoted daily-price authority SHA-256: `C197FB30B017934D62F8015265DE0C2D909E702C6EDCC94313423A072911010F`.
- Authority manifest SHA-256 changed from legacy `8BA304C36C224F1F8ADF78CB871A8200FDA0656BD5824801330EAF6EAF855847` to current `8E15782AB300EDB1F17F5043CBAC1B888EFA7F1A2FD9CBB8B43814429949C953`.
- Only the two authority CSVs, their manifest, the deterministic authority test, and this change record are in scope.
- `RULE_STATUS_MANIFEST.json`, `NEWS_SCAN_SOURCE_MANIFEST.json`, Runtime SQLite/WAL/SHM, HOLD/MIDR/MRD, other formal CSVs, scheduler configuration, P/S, UI, reports, skills, and plugins are unchanged.
- No network market-data fetch, OpenAI API, Web Search, Canva, or trading action was performed.
