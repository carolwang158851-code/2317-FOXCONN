# TASK_DAILY_WARROOM_UPDATE.md
# 每日戰情室更新任務規則
# 版本：v1.5-approved | 日期：2026-07-03
# 狀態：APPROVED_MARKET_INTELLIGENCE_OBSERVATION / 已核准市場情報觀察模組

---

## 一、文件定位

本文件定義「每日收盤後戰情室更新 Dry-Run」與「MARKET INTELLIGENCE 總經環境與市場情報觀察模組」的核准流程。

**中文狀態**：已核准每日收盤後自動抓取候選資料與臨時快照；已核准 MARKET INTELLIGENCE 作為每日收盤後與盤中觀察模組；不是正式 CSV 自動發布規則。

本文件不得覆寫或優先於下列文件：

1. `RULE_STATUS_MANIFEST.json`
2. `2317_DATA_GOVERNANCE_SPEC.md`
3. `EXECUTION_GUARD.md`
4. `AGENT.MD`
5. `SKILL_v12.md`
6. `OWNER_APPROVALS_P1008.md`

若本文件與上述文件衝突，以上述文件及較新的 Owner 核准紀錄為準。

---

## 二、Owner 核准邊界

Owner 第 92 項核准的是「重寫／降級本文件」。Owner 於 2026-06-28 另行核准每日收盤後 Dry-Run 規則：可自動抓取候選資料、產生 staging candidate 與 runtime snapshot，但不是核准 MIDR/EVA 啟用，也不是核准正式 CSV 寫入。Owner 於 2026-06-29 核准 MARKET INTELLIGENCE 作為每日收盤後與盤中觀察模組；它只影響風險提醒與重審提示，不啟用任何交易規則。

```yaml
ApprovalItem: 92 + 2026-06-28 DailyCloseDryRunApproval + 2026-06-29 MarketIntelligenceObservationApproval + 2026-07-03 ScheduledNewsScanObservationApproval
ApprovalScope: DailyCloseDryRunCandidateGeneration + MarketIntelligenceObservation + ScheduledNewsScanObservation
DailyCloseFetchAllowed: true
RecommendedRunWindowTST: "15:30-16:30 after TWSE close"
ScheduledNewsScanAllowed: true
ScheduledNewsScanWindowsTST:
  - "08:10 pre-open, lookback 16h"
  - "12:30 intraday, lookback 6h"
  - "15:30 post-close, lookback 8h"
  - "21:30 international/Fed/FX, lookback 12h"
  - "weekend or Monday report audit, lookback 7d"
MarketIntelligenceAllowed: true
MarketIntelligenceDataInputs:
  - runtime/warroom_realtime_snapshot.json
  - staging macro candidate
  - data/macro_snapshot.csv append-only baseline
  - staging macro event candidate
  - data/macro_event_observations.csv observation-only sidecar
  - data/fx_trend_observations.csv observation-only sidecar
MarketIntelligenceUiStatusRequired: true
MarketIntelligenceDecisionImpact: "risk_reminder_and_review_prompt_only"
RuleEnablementChange: false
FormalCsvWriteAllowed: false
FormalMacroCsvWriteMode: "append_only_after_owner_approval"
RuntimeSqliteWriteAllowed: false
RuntimeSnapshotWriteAllowed: true
UiKpiDriverAllowed: "runtime snapshot display only"
ModelDecisionDriverAllowed: false
AutoApprovalAllowed: false
Actionable: false
StatusZh: 已核准每日收盤後Dry-Run、市場情報觀察與固定新聞掃描觀察；正式CSV仍需Owner核准發布
```

---

## 三、禁止事項

本任務執行時一律禁止：

```text
1. 禁止自動寫入任何正式 CSV。
2. 禁止寫入 Runtime SQLite。
3. 禁止修改 UI、KPI、公式註冊表、規則狀態或回測設定。
4. 禁止繞過 RULE_STATUS_MANIFEST.json 的 OBSERVATION_ONLY 或 KEEP_DISABLED。
5. 禁止使用本文件啟用 MIDR、EVA、TRIM、ADD、BLOCK、SELL 或 SELL_ALL。
6. 禁止輸出「立即買入」、「立即賣出」、「必須加碼」、「必須減碼」等可執行指令。
7. 禁止把研究文件中的數值直接當作 CSV_AUTHORITY。
8. 禁止靜默 fallback；主要來源失敗時必須顯示中文狀態與阻擋原因。
9. 禁止追加或修改 `warroom_research_report_2026.md`，除非另有 Owner 明確核准。
10. 禁止宣稱本文件可凌駕既有治理文件。
11. 禁止讓固定新聞掃描直接 append 正式 CSV 或改變 HOLD / 主 IC。
12. 禁止因單一未驗證媒體來源自動升級為 REVIEW_REQUIRED。
```

---

## 四、允許事項

每日收盤後自動更新只允許產出候選文件、檢查清單與臨時快照：

```text
1. 讀取已核准正式 CSV 與已核准 Evidence Package。
2. 查詢或引用外部資料時，保存來源、時間、URL、摘要與中文狀態。
3. 建立 Dry-Run 報告，列出候選數據、缺漏、衝突、逾期與不可用欄位。
4. 建立候選 CSV 建議行，但只能放在 output 或 staging，不得寫入 data。
5. 建立候選研究報告草稿，但需標記 RESEARCH_DRAFT / 研究草稿。
6. 對每個數值標示 Evidence ID 或 `UNVERIFIED / 未驗證`。
7. 對每個推論標示依據、反證條件、失效條件與可信度。
8. 所有報告都必須標示 `actionable:false / 僅供參考`。
9. 允許更新 `runtime/warroom_realtime_snapshot.json` 供 UI 顯示臨時即時快照。
10. UI 顯示 runtime snapshot 時必須標示「臨時即時快照，尚未核准發布」。
11. 允許 Windows Task Scheduler 呼叫 BAT 執行固定新聞掃描，但只能產生 staging event candidate 與 dry-run 註記。
12. 允許首頁顯示 `OBSERVE / WATCH / REVIEW_REQUIRED` 或 `HOLD_UNDER_REVIEW` 重審提示，但必須維持 `actionable:false`。
```

### 4.1 每日收盤後資料分層

| 資料層 | 更新方式 | 可用於 UI | 可寫正式 CSV | 中文狀態 |
|---|---|---:|---:|---|
| runtime snapshot | 每日收盤後自動產生 | 是 | 否 | 臨時即時快照，尚未核准發布 |
| staging candidate | 每日收盤後自動產生 | 可供檢查 | 否 | 候選資料，待 Owner 核准 |
| `2317_daily_price.csv` | append-only 候選發布後人工升版 | 是 | 需核准 | 正式日價格 CSV |
| `macro_snapshot.csv` | append-only 候選發布後人工升版 | 是 | 需核准 | 正式總經快照 CSV |
| `macro_event_observations.csv` | 固定新聞掃描或 Owner 輸入產生候選，Owner gate 後 append | 是，僅提示 | 需核准 | 事件 / 黑天鵝旁路觀察 |
| `fx_trend_observations.csv` | FX 趨勢候選，Owner gate 後 append | 是，僅提示 | 需核准 | FX 趨勢旁路觀察 |
| `2317_master_v9.csv` | 季報、股利或重大修正後才升版 | 是 | 需核准 | 正式季度主檔 CSV |

### 4.2 MARKET INTELLIGENCE 核准用途

```text
1. 可作為每日收盤後與盤中觀察模組。
2. 可讀取 runtime snapshot、staging macro candidate 與 macro_snapshot.csv append-only baseline。
3. UI 必須標示中文資料狀態，例如「臨時即時快照，尚未核准發布」或「正式 macro CSV 待 Owner 核准」。
4. 正式 macro_snapshot.csv 僅能 append，不得修改歷史列。
5. 正式 macro_snapshot.csv 發布必須經 Owner 核准並更新 SHA-256 / manifest。
6. MARKET INTELLIGENCE 只影響風險提醒、失效條件、信心度註記與重審提示。
7. MARKET INTELLIGENCE 不啟用任何 TRIM、ADD、BLOCK、SELL 或倉位調整規則。
8. 全部輸出維持 actionable:false。
```

### 4.4 固定新聞掃描核准用途

```text
1. 固定新聞掃描的目的，是保護事件與定期戰報之間的時間差。
2. 建議由 Windows Task Scheduler 呼叫 BAT；BAT 可固定跑，但只能產生 staging/YYYY-MM-DD/macro_event_observations_candidate.csv。
3. 排程掃描不直接 append data/macro_event_observations.csv，不改 HOLD，不啟用 KEEP_DISABLED 規則。
4. 即時保護使用 6-12 小時 lookback；主要判斷使用 72 小時降噪；週/月戰報使用 7 天防漏網。
5. OBSERVE 保留 7 天供戰報追蹤；WATCH 首頁提示 3 天或直到 Owner ack；REVIEW_REQUIRED 未 Owner ack 前不得自動過期。
6. 單一未驗證媒體來源只能 OBSERVE；多來源、官方來源或直接影響鴻海營運 / 供應鏈 / FX / 利率假設時，才可升級 WATCH 或 REVIEW_REQUIRED。
7. DRY_RUN.json 必須列出來源層級、lookback window、EvidenceStatus、RiskTag、BlackSwanLevel、Owner ack 狀態與 Actionable=false。
```

### 4.3 判讀信心度自動提升規則

```text
1. 判讀信心度不是資料正確率，也不是模型能力分數。
2. 判讀信心度代表「本次系統結論可被決策者採用作為參考的程度」。
3. 信心度可因正式 CSV hash/manifest 通過、資料新鮮、欄位完整、一致性良好而自動提升。
4. 信心度必須因 runtime snapshot、STALE_DATA、欄位缺失、異常列、SYSTEMIC 風險而自動扣分或封頂。
5. OBSERVATION_ONLY 或 runtime 模式下，信心度可以顯示，但不得解除正式報告限制。
6. 信心度只影響報告註記、風險提醒與重審提示，不啟用交易規則。
7. UI 必須用中文揭露信心度加減分依據。
```

---

## 五、每日 Dry-Run 輸出契約

每次 Dry-Run 至少輸出下列文件：

```text
output/daily-warroom/YYYY-MM-DD/DRY_RUN.json
output/daily-warroom/YYYY-MM-DD/VALIDATION_REPORT.md
output/daily-warroom/YYYY-MM-DD/CANDIDATE_REPORT.md
output/daily-warroom/YYYY-MM-DD/SOURCE_STATUS.md
```

### 5.1 DRY_RUN.json 必備欄位

```json
{
  "taskId": "DAILY_WARROOM_UPDATE_DRY_RUN",
  "asOfDate": "YYYY-MM-DD",
  "status": "DRY_RUN_ONLY",
  "statusZh": "僅供Dry-Run，未發布",
  "actionable": false,
  "formalCsvWriteAllowed": false,
  "runtimeSqliteWriteAllowed": false,
  "ruleEnablementChange": false,
  "sourceStatus": [],
  "candidateRows": [],
  "blockingIssues": [],
  "ownerApprovalRequired": true
}
```

### 5.2 VALIDATION_REPORT.md 必備內容

```text
1. 中文執行摘要
2. 正式資料雜湊
3. 來源狀態與中文備註
4. 缺漏資料
5. 資料衝突
6. 逾期或不新鮮資料
7. 未驗證推論
8. 阻擋發布原因
9. Owner 待決策項目
```

---

## 六、資料來源規則

每日更新不得把「網頁搜尋結果」直接升格為正式資料。

| 類型 | 可用方式 | 中文狀態 |
|---|---|---|
| 官方來源 | 可建立 Evidence 候選 | 官方候選資料，待驗證 |
| 市場資料 | 只可交叉驗證或補充敘事 | 市場參考資料，非正式權威 |
| 媒體報導 | 只可作事件脈絡 | 新聞脈絡，非正式數據 |
| Owner 輸入 | 可作假設或觀點 | Owner觀點，需標示 |
| 研究報告 | 可作推論來源 | 研究推論，需驗證 |

若主要來源不可用，輸出：

```text
SOURCE_UNAVAILABLE / 主要來源不可用
處理方式：停止正式發布，只產生Dry-Run缺口報告。
```

---

## 七、MIDR / EVA / 謙遜設計狀態

```yaml
MIDR:
  status: OBSERVATION_ONLY
  statusZh: 僅供觀察，不得啟用正式訊號
  canCalculateResearchScore: true
  canDriveDecision: false

EVA:
  status: RESEARCH_HYPOTHESIS
  statusZh: 研究假設，不得啟用正式警示
  canCalculateResearchCheck: true
  canDriveDecision: false

HumilityDesign:
  status: REPORTING_CONCEPT
  statusZh: 報告概念，可提示不確定性，不得自動降級訊號或調整持股
  canDisplayUncertainty: true
  canDriveDecision: false
```

任何 MIDR、EVA、TRIM、ADD、BLOCK、SELL 相關內容都必須走 Formula Registry、完整回測、Owner Approval 與中文狀態標示後，才能討論是否升格。

---

## 八、候選報告格式

```markdown
# 每日戰情室更新 Dry-Run

日期：YYYY-MM-DD
狀態：DRY_RUN_ONLY / 僅供Dry-Run，未發布
actionable: false / 僅供參考

## 一、資料狀態

| 指標 | 候選值 | Evidence ID | 狀態 | 中文備註 |
|---|---:|---|---|---|

## 二、資料缺口與衝突

| 類型 | 說明 | 影響 | 處理 |
|---|---|---|---|

## 三、研究推論

| 推論 | 依據 | 反證條件 | 失效條件 | 可信度 |
|---|---|---|---|---|

## 四、Owner 待決策

| 項目 | 選項 | 理由 | 風險 |
|---|---|---|---|

## 五、發布限制

本報告未經 Owner 核准，不得寫入正式 CSV、Runtime SQLite、UI、KPI 或規則。
```

---

## 九、正式 CSV 發布升格條件

每日 Dry-Run 若要把候選資料升格為正式 CSV，至少需要另案核准：

1. staging candidate 通過 schema、欄位、日期、重複列、單位與缺值檢查。
2. 每個候選數值具備 Evidence ID 或明確標示 `UNVERIFIED / 未驗證`。
3. 來源優先序符合 TWSE / MOPS / 公司公告優先原則。
4. Owner 核准候選數值、中文備註與發布範圍。
5. publisher 更新正式 CSV、SHA-256 與 manifest。
6. UI 顯示正式資料日期、hash/manifest 狀態與中文註記。
7. 明確確認仍維持 `actionable:false`，不自動交易、不改變持股。

---

## 十、版本紀錄

| 版本 | 日期 | 狀態 | 變更 |
|---|---|---|---|
| v1.1 | 2026-06-26 | RETIRED_DRAFT / 已退役草案 | 原文件含自動核准、繞過 OBSERVATION_ONLY、缺失 SOP 引用與版本混用 |
| v1.2-draft | 2026-06-27 | DRAFT_DRY_RUN_ONLY / 草案，僅限Dry-Run | 依 Owner 第 92 項核准重寫並降級 |
| v1.3-approved | 2026-06-28 | APPROVED_DAILY_CLOSE_DRY_RUN / 已核准每日收盤後Dry-Run | Owner 核准每日收盤後自動抓取候選資料與 runtime snapshot；正式 CSV 仍需核准發布 |
| v1.4-approved | 2026-06-29 | APPROVED_MARKET_INTELLIGENCE_OBSERVATION / 已核准市場情報觀察模組 | Owner 核准 MARKET INTELLIGENCE 作為每日收盤後與盤中觀察模組；只影響風險提醒與重審提示，維持 actionable:false |

---

`actionable:false / 僅供參考，不會自動交易、改變持股、寫入正式資料或啟用規則。`
# P1008 Scheduled News Scan v1 Addendum

Implementation entrypoints:
- `P1008_4_NEWS_SCAN.bat --dry-run --no-network` runs the observation-only scanner.
- `tools/warroom_news_scanner_v1.py` writes `NEWS_SCAN.json`, `NEWS_SCAN.md`, and `runtime/warroom_news_scan_snapshot.json`.
- `data/NEWS_SCAN_SOURCE_MANIFEST.json` controls approved source tiers and connector status.
- `P1008_4_REGISTER_NEWS_SCHEDULE.bat` previews Windows Task Scheduler jobs by default; `--register` is required and must be Owner-approved.

Operational boundaries:
- No-event scans must not fabricate news and must not create pending formal CSV work.
- `REVIEW_REQUIRED` may show `HOLD_UNDER_REVIEW` in the homepage, but the main HOLD IC, formal CSV files, and KEEP_DISABLED rules remain unchanged.
- Official, public-market, and media connectors remain `CONNECTOR_PENDING` until separately approved.
