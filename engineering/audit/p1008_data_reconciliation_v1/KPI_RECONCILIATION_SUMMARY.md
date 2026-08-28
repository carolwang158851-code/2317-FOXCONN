# P1008 KPI Reconciliation Summary

## Result

- Baseline: `214e7bf8363b36b30c67707849ba1ecb4cc9e297`
- TOTAL_KPI: `34`
- ACTIVE: `24`
- DISABLED_UI_ONLY_LEGACY: `6`
- DUPLICATE: `1`
- SEMANTIC_COLLISION: `1`
- STALE: `6`
- ZOMBIE: `5`
- HARDCODED: `3`
- LEGACY: `6`
- REVIEW_REQUIRED: `0`
- FIXED: `6`
- UNRESOLVED_P0: `0`
- DERIVED_VERIFIED_COUNT: `3`
- AUTHORITATIVE_SOURCE_REPORTED_COUNT: `9`
- UNVERIFIED_COUNT: `1`
- REPORT_UI_PARITY: `PASS`
- INTRODUCED_REGRESSION_COUNT: `0`
- Formal CSV modified: `false`; thresholds modified: `false`; actionable changed: `false`.
- UI structure changed: `false`; publication performed: `false`.

## Root cause

The principal score collision was caused by overlapping UI-derived scoring and legacy fallback/hardcoded values. Report generation is downstream and was not the source of War Room KPI truth.

戰報只讀取同一正式資料與觀察旁路並產生下游輸出；戰報是否存在，不影響戰情室 KPI 的有效性。

## Data reconciliation

- PB：正式來源最新 `2026-08-11`，Close `263.0`、BVPS_ref `127.12`、PB `2.069x`，公式可重現；來源較目前日期舊，故明示日期而不假裝即時。
- FY2026 Q2：官方結果設定存在但仍為 Owner-review-only 候選，尚未升格 master v9；正式季度權威仍是 `2026Q1`。
- ROE/ROIC：ROE `11.52%` 依Owner權威CSV；ROIC `12.57%` 可由 `2216/17633*100` 重現，且不以近似值補缺。
- 現金流：2026Q1核心FCF `-325.57191` 億元可由OCF減PPE capex重現；殖利率另以股利/正式Close計算。
- AI：`40%` 缺分母且為L3，只保留歷史觀察並退出目前五維分數；Q2 `51%` 是雲端網通占比，不是AI占比。
- Macro/FX：最新分別為 `2026-07-10`、`2026-07-27`，保留各自日期且不跨檔補值。

## KPI cleanup

- 新UI六張卡片保留，六個沒有正式精確來源的數值分數均為 `N/A`。
- 舊UI五維模型保留；只修正輸入：ROIC不近似、AI需分母/權威、籌碼與總經缺值回傳N/A。
- 正式KPI、可重現衍生值及歷史趨勢保留。

## Report/UI parity

- Close/PB/BVPS來自正式daily price；ROE/EPS/股利來自master v9；殖利率公式一致。
- USD/TWD、DXY、US10Y來自FX觀察；VIX/WTI來自macro。報表是下游且不回寫分數。

## Regression and governance

- 詳見 `BASELINE_REGRESSION_DIFF.md`；目前 `INTRODUCED_REGRESSION_COUNT=0`。
- 未修改正式CSV、manifest、規則、閾值或結論；未重設UI、未新增模型、未發布。
