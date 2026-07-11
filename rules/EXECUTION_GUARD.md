# EXECUTION_GUARD — 退休存股戰情室 Codex 執行護欄

**用途**：Codex 在每次任務中必須遵守的執行流程護欄。  
**強制性**：本文件與 SKILL.md 同等強制，不得跳過任何步驟。  
**適用時機**：收到任務單（TASK_TEMPLATE）後，正式寫程式碼前。

---

## 執行流程總覽

```
Step 1：任務單驗證
    ↓
Step 2：Dry-Run 預覽（輸出給 Owner 審閱）
    ↓
Step 3：Owner 確認（等待回覆）
    ↓
Step 4：正式執行
    ↓
Step 5：結案報告（輸出給 Owner 驗收）
```

> ⚠️ **Step 2 → Step 3 是強制等待點。**  
> Codex 不得在未收到 Owner 確認前跳到 Step 4。  
> 唯一例外：Owner 在任務單中明確填寫 `AutoApprove: true`（見下方說明）。

---

## Step 1：任務單驗證

Codex 收到任務後，必須先驗證任務單格式是否完整。

### 1.1 必填欄位檢查

```
□ TaskId 已填寫
□ TaskDate 已填寫
□ Phase 已填寫（Phase 1 / 2 / 3 / 4 / 5 / 其他）
□ TargetFiles 已填寫（至少一個檔案）
□ TaskDescription 已填寫（非空白）
□ Deliverables 已填寫（至少一項）
□ RuleEnablementChange 已填寫（true / false）
□ BacktestChange 已填寫（true / false）
□ DataSourceContext.primary 已填寫
□ ManualOverrideUsed 已填寫（true / false）
```



```
任何必填欄位缺失 → 停止，輸出缺失欄位清單，等待 Owner 補充
邏輯一致性不符  → 停止，說明衝突點，等待 Owner 澄清
高度受限檔案出現在 TargetFiles → 停止，要求 Owner 提供書面核准證明
```

### 1.4 EffectiveDate 版本化與 Lookahead 例外處理

```
背景：EstimatedEffectiveDate 為估算值，若實際公布日晚於估算日，
      回測結果可能存在 look-ahead bias，需標注並處理。

規則：
  ① EstimatedEffectiveDate 必填，用於回測過濾
  ② 若發現「實際公布日 > EstimatedEffectiveDate」：
     → 回測結果標注 LOOKAHEAD_RISK_DETECTED
     → 受影響日期區間列入 Audit Log
     → 輸出 WARNING：「回測區間 [startDate~endDate] 使用估算
        EffectiveDate，實際公布日為 [actualDate]，結果僅供參考」
     → 不得自動重跑回測（需 Owner 核准）
  ③ EffectiveDate 變更必須版本化記錄（寫入 audit_log.json）：
     { timestamp, field: "EstimatedEffectiveDate",
       quarter, oldValue, newValue, reason, affectedBacktestRange }
  ④ 觸發 STOP-6 的條件（新增）：
     → 程式碼使用 QuarterEndDate 直接對齊（非 EstimatedEffectiveDate）
     → 程式碼使用未來才公布的財報數字

Codex 實作：
  // 正確：使用 EstimatedEffectiveDate 過濾
  const available = csv.filter(r => r.EstimatedEffectiveDate <= backtestDate);
  // 若實際公布日晚於估算日，標注警告
  if (actualPublishDate > estimatedEffectiveDate) {
    output.lookaheadWarning = {
      status: 'LOOKAHEAD_RISK_DETECTED',
      affectedRange: [estimatedEffectiveDate, actualPublishDate],
      message: '回測結果僅供參考，需Owner確認後重跑'
    };
  }
```

---

## Step 2：Dry-Run 預覽

任務單驗證通過後，Codex 必須輸出以下 Dry-Run 報告，**不得直接開始寫程式碼**。

### 2.1 Dry-Run 報告格式

```markdown
## Dry-Run 預覽報告
TaskId: [任務編號]

### 我打算修改的檔案
- [檔案名稱]：[說明將做什麼修改]

### 我不會修改的檔案
- [列出所有 ForbiddenFiles 和其他唯讀檔案]
- 2317_master_v8.csv（唯讀，只能讀取數據）
- 2317_daily_price.csv（唯讀，只能讀取每日PB）
- SKILL_v12.md（唯讀，規格文件）
- 2317_DATA_GOVERNANCE_SPEC.md（唯讀）

### 我打算新增 / 修改的程式碼區塊
[列出每個主要變更的摘要，例如：]
1. 新增 DATA_SOURCE_REGISTRY 物件（約 40 行）
2. 修改 DataBadge 渲染函式，新增 USER_CURATED_WEB_DATA 分支
3. 新增 Field Manifest 物件（約 30 行）
4. 新增資料來源總覽卡 UI 元件

### 我不會做的事
- 不修改 Backtest 相關程式碼
- 不啟用任何目前 disabled 的規則
- 不修改 CSS 樣式（依任務單限制）

### 規則啟用狀態確認
以下規則在本次任務後仍維持 disabled：
- STRONG_ADD：KEEP_DISABLED
- 成長買進線 1.45x：KEEP_DISABLED
- ROE_BLOCK / ROE_ADD_QUALIFIED：KEEP_DISABLED
- PB_UNDERVALUE / PB_OVERHEAT：KEEP_DISABLED
- DIVIDEND_TRAP：KEEP_DISABLED
- EPS_GROWTH_QUALIFIED：KEEP_DISABLED

### 資料來源標示確認
本次任務使用的資料來源：USER_CURATED_WEB_DATA
所有相關輸出將標示此來源，不會升格為 CSV_AUTHORITY

### 潛在風險提示（自動生成清單）
[Codex 必須自動掃描以下項目，有任何一項為「是」則列出：]
- [ ] TaskDescription 有模糊詞（「等」「之類」「類似」）→ 說明我的解讀
- [ ] TargetFiles 涉及 UI 架構變更 → 確認 Owner 已核准
- [ ] 任務涉及 EstimatedEffectiveDate → 確認版本化規則已遵守
- [ ] 任務涉及 Backtest → 確認不使用未來資訊
- [ ] 任務涉及缺失欄位 → 確認走 DATA_MISSING 路徑
- [ ] 任務涉及 DataBadge → 確認保留舊有標示邏輯
- [ ] 任務涉及 disabledRules → 確認狀態不變

⚠️ 若上述任何一項為「是」且非空，即使 AutoApprove: true 也不得自動執行。

### 缺欄位補齊行動清單（建議三：新增）
[若任務完成後仍有缺欄位，自動列出：]
| 缺失欄位 | 影響規則 | 負責人 | 建議補齊方式 |
|---------|---------|--------|------------|
| [欄位名] | [規則名] | Owner | [補齊方式] |

### 等待 Owner 確認
請回覆「確認執行」或提出修改意見。
```

### 2.2 Dry-Run 的強制要求

```
✅ 必須列出每個將被修改的函式 / 物件名稱
✅ 必須列出新增程式碼的大致行數估計
✅ 必須明確列出「不會做的事」
✅ 必須確認規則啟用狀態不變
✅ 若有任何模糊點，必須在「潛在風險提示」中說明

❌ 不得在 Dry-Run 中直接輸出完整程式碼
❌ 不得在 Dry-Run 中實際修改任何檔案
```

---

## Step 3：Owner 確認

### 3.1 等待確認的規則

```
Codex 必須等待 Owner 明確回覆以下其中一種：

A. 「確認執行」或「OK」或「go ahead」→ 進入 Step 4
B. 修改意見 → Codex 更新 Dry-Run 報告，重新等待確認
C. 「取消」→ 任務終止，輸出取消記錄
```

### 3.2 AutoApprove 例外

若 Owner 在任務單中明確填寫：

```yaml
AutoApprove: true
AutoApproveCondition: "僅限 Phase 1 的 DATA_SOURCE_REGISTRY 新增，不涉及任何規則啟用"
```

則 Codex 可在 Dry-Run 輸出後，等待 **30 秒無回覆**即自動進入 Step 4。  
但以下情況即使有 `AutoApprove: true` 也**不得自動執行**：

```
❌ TargetFiles 包含任何 CSV 資料檔
❌ RuleEnablementChange: true
❌ BacktestChange: true
❌ Dry-Run 中有「潛在風險提示」且非空
❌ 任務涉及刪除現有功能
```

---

## Step 4：正式執行

### 4.1 執行中的即時規則

```javascript
// Codex 執行時必須遵守的即時規則

// 規則 1：只寫 TargetFiles
const allowedFiles = task.TargetFiles;
// 任何不在 allowedFiles 中的檔案，不得有任何寫入操作

// 規則 2：每修改一個函式，先確認不影響其他功能
// 若發現修改會影響 TargetFiles 以外的功能，立即停止並回報

// 規則 3：遇到規格文件未涵蓋的情況，立即停止
// 不得自行推斷「這應該是 Owner 想要的」

// 規則 4：遇到以下情況，立即停止並回報
const stopConditions = [
  '需要修改 ForbiddenFiles 才能完成任務',
  '需要啟用 disabled 規則才能完成任務',
  '發現任務說明與 SKILL.md 規格衝突',
  '發現任務說明與上游規格文件衝突',
  '程式碼邏輯需要使用未來資訊（look-ahead）',
  '需要假設缺失欄位存在才能完成任務',
];
```

### 4.2 執行中的禁止行為

```
❌ 不得在執行中途自行擴大修改範圍
❌ 不得因為「順手」而修改 TargetFiles 以外的檔案
❌ 不得在程式碼中硬編碼任何缺失欄位的預設值
❌ 不得在程式碼中將 disabled 規則的狀態改為 enabled
❌ 不得刪除現有的 DataBadge 標示邏輯
❌ 不得刪除現有的 disabledRules 輸出邏輯
❌ 不得將 USER_CURATED_WEB_DATA 的 trustLevel 設為 5（CSV_AUTHORITY 專屬）
❌ 不得使用 || 或 ?? 為缺失欄位提供預設值（defaultFill 禁止）
```

### 4.3 DefaultFill 程式碼掃描（執行前必做）

在正式寫入任何程式碼前，Codex 必須掃描自己產生的程式碼，
確認不含以下禁止模式：

```javascript
// 禁止模式清單（任何一項出現都必須觸發 STOP-3）
const FORBIDDEN_PATTERNS = [
  /data\.\w+\s*\|\|\s*\d+/,        // data.ROE || 10
  /data\.\w+\s*\?\?\s*\d+/,        // data.ROE ?? 10
  /\w+\s*=\s*\w+\s*\|\|\s*\d+/,   // val = data.ROE || 10
  /defaultValue\s*[:=]\s*\d+/,     // defaultValue: 10
  /fallback\s*[:=]\s*\d+/,         // fallback: 10
  /\.fill\(\d+\)/,                  // array.fill(0)
  /if\s*\(!\w+\)\s*\w+\s*=\s*\d+/, // if (!ROE) ROE = 10
];

// 正確做法：缺值必須走 DATA_MISSING 路徑
// CORRECT
if (!data.ROE) {
  return { signal: "HOLD", reasonCode: "ROE_MISSING" };
}

// WRONG - 觸發 STOP-3
if (!data.ROE) data.ROE = 10;
```

若掃描發現禁止模式，立即輸出：

```
🚨 STOP-3 DefaultFill Detected
Pattern: [發現的模式]
Location: [程式碼位置]
Required Action: Replace with DATA_MISSING path
```

### 4.3 手動覆寫的正確實作

```javascript
// ✅ 正確：手動覆寫必須標示來源
if (input.manualROE !== undefined) {
  data.ROE = input.manualROE;
  reasonCodes.push('MANUAL_OVERRIDE');
  dataBadge = 'MANUAL_OVERRIDE';
  // 必須在 UI 顯示「手動設定或推演模式」
}

// ❌ 錯誤：手動值默默覆蓋 CSV 權威資料
// ❌ 錯誤：手動推演結果被誤認為正式回測
// ❌ 錯誤：用手動覆寫掩蓋缺資料規格
// ❌ 錯誤：手動覆寫後不標示 MANUAL_OVERRIDE

// 手動覆寫的可接受用途：
const acceptableManualOverrideUsage = [
  '手動推演不同 ROE / EPS / PB / Tax / payoutRatio 情境',
  '暫時補足 API 無法取得的資料',
  '校正已知錯誤資料',
  '測試規格變動對訊號的影響',
];

// 手動覆寫的不可接受用途：
const unacceptableManualOverrideUsage = [
  '未標示手動來源就覆蓋正式資料',
  '讓手動值永久洗掉 CSV 權威資料',
  '讓手動推演結果被誤認為正式回測',
  '用手動覆寫掩蓋缺資料規格',
];
```

---

## Step 5：結案報告

任務完成後，Codex 必須輸出以下結案報告，**不得只說「完成了」**。

### 5.1 結案報告格式

```markdown
## 結案報告
TaskId: [任務編號]
CompletedAt: [完成時間]

### 實際修改的檔案
- [檔案名稱]：[說明實際做了什麼修改]

### 實際未修改的檔案
- [列出所有 ForbiddenFiles 和其他唯讀檔案，確認未被修改]

### 新增 / 修改的程式碼摘要
1. [函式 / 物件名稱]：[說明變更內容]
2. ...

### 規則啟用狀態確認（任務完成後）
以下規則在本次任務後仍維持 disabled：
- STRONG_ADD：KEEP_DISABLED ✓
- 成長買進線 1.45x：KEEP_DISABLED ✓
- ROE_BLOCK / ROE_ADD_QUALIFIED：KEEP_DISABLED ✓
- PB_UNDERVALUE / PB_OVERHEAT：KEEP_DISABLED ✓
- DIVIDEND_TRAP：KEEP_DISABLED ✓
- EPS_GROWTH_QUALIFIED：KEEP_DISABLED ✓

### 資料來源標示確認
本次任務使用的資料來源：USER_CURATED_WEB_DATA ✓
未升格為 CSV_AUTHORITY ✓



### 驗收建議
[說明 Owner 如何驗收，對應任務單中的 AcceptanceCriteria]
1. [驗收步驟 1]
2. [驗收步驟 2]

### 已知限制與後續建議
[若有任何未完成的部分或建議的後續步驟]
- [說明]

### Phase 進度更新
當前 Phase：[Phase 1 / 2 / 3 / 4 / 5]
本次任務完成後的 Phase 狀態：[說明]
下一步建議：[說明]
```

### 5.2 結案報告的強制要求

```
✅ 必須明確列出「實際修改的檔案」與「實際未修改的檔案」
✅ 必須確認所有 disabled 規則仍維持 disabled
✅ 必須列出任務完成後仍缺少的欄位
✅ 必須提供具體的驗收建議
✅ 必須更新 Phase 進度

❌ 不得只說「任務完成」而不提供詳細報告
❌ 不得在結案報告中宣稱「所有規則已啟用」
❌ 不得在結案報告中宣稱「資料已完整」（若缺欄位仍存在）
```

---

## 緊急停止條件

以下任何情況發生時，Codex 必須**立即停止所有操作**，輸出緊急停止報告，等待 Owner 指示：

```
🚨 STOP-1：發現需要修改 ForbiddenFiles 才能完成任務
🚨 STOP-2：發現任務說明要求啟用 disabled 規則，但任務單中 RuleEnablementChange: false
🚨 STOP-3：發現程式碼邏輯需要假設缺失欄位存在
🚨 STOP-4：發現修改會影響 Backtest 邏輯，但任務單中 BacktestChange: false
🚨 STOP-5：發現任務說明與 SKILL.md 或上游規格文件有直接衝突
🚨 STOP-6：發現需要使用未來資訊（look-ahead bias）才能完成任務
🚨 STOP-7：發現任務單中的 TargetFiles 包含高度受限 CSV 檔案
```

### 緊急停止報告格式

```markdown
## 🚨 緊急停止報告
TaskId: [任務編號]
StopCode: [STOP-1 到 STOP-7]
StopReason: [說明觸發停止的具體原因]
CurrentState: [說明目前已完成了什麼、尚未執行什麼]
RequiredOwnerAction: [說明需要 Owner 做什麼才能繼續]
```

---

## 文件使用方式

每次給 Codex 任務時，同時提供以下三份文件：

```
1. SKILL.md          ← 規則與規格
2. TASK_TEMPLATE.md  ← 任務輸入格式（Owner 填寫後提供）
3. EXECUTION_GUARD.md ← 執行流程護欄（本文件）
```

Codex 必須按照以下順序處理：

```
讀取 SKILL.md → 讀取 EXECUTION_GUARD.md → 讀取任務單
→ Step 1 驗證 → Step 2 Dry-Run → Step 3 等待確認
→ Step 4 執行 → Step 5 結案報告
```

---

*本文件由 Office Agent 依據專案規格文件整理制定。*
*v2.1 更新（2026-06-05）：*
*  - 新增 1.4：EffectiveDate 版本化與 Lookahead 例外處理（建議一）*
*  - 更新 Dry-Run 報告：新增潛在風險自動掃描清單（建議二）*
*  - 更新 Dry-Run 報告：新增缺欄位補齊行動清單（建議三）*
*  - 更新結案報告：缺欄位狀態改為表格化 + UI 回饋一致性規則（建議三）*
*  - 新增數據庫唯讀保護（2317_master_v8.csv / 2317_daily_price.csv / macro_snapshot.csv）*
*如規格文件更新，本文件應同步修訂。*