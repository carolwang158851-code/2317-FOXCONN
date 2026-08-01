# EXCEPTION_CONFLICT_DETECTOR.md
# 例外衝突自動偵測系統 — 設計規格與實作
# 版本：v1.0 | 日期：2026-06-25

---

## 設計哲學：為什麼不用傳統演算法？

```
Codex 是語言模型，不是規則引擎。
它無法「執行」衝突偵測演算法，只能「理解」衝突偵測規格。

正確的設計：
  不是讓 Codex 執行複雜演算法，
  而是設計一套「結構化規格語言（ESL）」，
  讓 Codex 能夠用自然語言推理來偵測衝突。

核心洞察：
  衝突偵測 = 語義比對問題
  語義比對 = Codex 最擅長的事
  因此：讓 Codex 做它最擅長的事，而非強迫它做它不擅長的事。
```

---

## 第一層：例外聲明語言（ESL）

每個例外文件必須在頭部包含標準化的 ESL 聲明區塊。

### ESL 聲明格式

```yaml
## ESL_DECLARATION_BEGIN
ExceptionId: [唯一識別碼]
Version: [版本號]
CreatedAt: [YYYY-MM-DD]
ExpiresAt: [YYYY-MM-DD 或 PERMANENT]
Priority: [1-10，數字越小優先級越高]

# 操作聲明（核心）
Operations:
  - id: OP_001
    target: [操作對象，例如：macro_snapshot.csv]
    action: [ALLOW / DENY / REQUIRE / OVERRIDE]
    condition: [觸發條件，可選]
    scope: [ALL_TASKS / THIS_TASK_ONLY / TASK_TYPE:xxx]

  - id: OP_002
    target: [操作對象]
    action: [ALLOW / DENY / REQUIRE / OVERRIDE]
    condition: [觸發條件，可選]
    scope: [ALL_TASKS / THIS_TASK_ONLY / TASK_TYPE:xxx]

# 已知衝突聲明（可選）
KnownConflicts:
  - with: [其他例外文件ID]
    resolution: [THIS_WINS / OTHER_WINS / OWNER_ARBITRATE]
    description: [衝突說明]

# 優先順序聲明
OverridesExceptions: [列表]
DeferToExceptions: [列表]
## ESL_DECLARATION_END
```

### 現有例外文件的 ESL 聲明範例

**TASK_DAILY_WARROOM_UPDATE 的 ESL 聲明**：

```yaml
## ESL_DECLARATION_BEGIN
ExceptionId: TASK_DAILY_WARROOM_UPDATE
Version: 1.0
CreatedAt: 2026-06-25
ExpiresAt: PERMANENT
Priority: 1

Operations:
  - id: OP_001
    target: MIDR_ENGINE
    action: OVERRIDE
    condition: ALWAYS
    scope: THIS_TASK_ONLY
    value: v2.3_WITH_HUMBLE_DESIGN_v1.1
    overrides: RULE_STATUS_MANIFEST.MIDR=OBSERVATION_ONLY

  - id: OP_002
    target: macro_snapshot.csv
    action: DENY
    condition: AUTO_WRITE
    scope: THIS_TASK_ONLY
    description: 禁止自動寫入，只允許輸出建議行

  - id: OP_003
    target: 2317_daily_price.csv
    action: DENY
    condition: AUTO_WRITE
    scope: THIS_TASK_ONLY
    description: 禁止自動寫入，只允許輸出建議行

  - id: OP_004
    target: warroom_research_report_2026.md
    action: ALLOW
    condition: APPEND_ONLY
    scope: THIS_TASK_ONLY

KnownConflicts: []
OverridesExceptions: []
DeferToExceptions: []
## ESL_DECLARATION_END
```

---

## 第二層：衝突偵測演算法（Codex 執行版）

### 演算法描述（自然語言版，供 Codex 理解）

```
當 Codex 收到「新增例外文件」的請求時，執行以下步驟：

STEP A：解析新例外文件的 ESL 聲明
  1. 找到 ## ESL_DECLARATION_BEGIN 和 ## ESL_DECLARATION_END 之間的內容
  2. 提取所有 Operations 條目
  3. 若沒有 ESL 聲明 → 觸發 STOP-E1（缺少必要聲明）

STEP B：載入所有現有例外文件的 ESL 聲明
  1. 讀取 EXCEPTION_REGISTRY.md 中的所有 ACTIVE 例外文件
  2. 提取每個文件的 Operations 條目
  3. 建立「現有操作清單」

STEP C：執行衝突比對（三種衝突類型）

  類型1：直接衝突（DIRECT_CONFLICT）
    條件：新例外的某個 Operation 與現有例外的某個 Operation
          針對「相同 target」有「相反 action」
    例：新例外 OP: target=macro_snapshot.csv, action=ALLOW_AUTO_WRITE
        現有例外 OP: target=macro_snapshot.csv, action=DENY_AUTO_WRITE
    → 嚴重程度：CRITICAL，必須停止

  類型2：範圍衝突（SCOPE_CONFLICT）
    條件：新例外的 scope=ALL_TASKS 覆蓋了現有例外的 scope=THIS_TASK_ONLY
    例：新例外 OP: target=CSV_WRITE, action=ALLOW, scope=ALL_TASKS
        現有例外 OP: target=CSV_WRITE, action=DENY, scope=THIS_TASK_ONLY
    → 嚴重程度：HIGH，需要 Owner 確認

  類型3：語義衝突（SEMANTIC_CONFLICT）
    條件：兩個 Operation 的 target 不同，但在執行時可能互相影響
    例：新例外 OP: target=MIDR_SIGNAL, action=OVERRIDE_TO_ADD
        現有例外 OP: target=UI_DISPLAY, action=MODIFY_CSS
        → 若 MIDR 訊號改變，UI 顯示邏輯可能不一致
    → 嚴重程度：MEDIUM，記錄警告

STEP D：計算衝突分數
  衝突分數 = CRITICAL×100 + HIGH×10 + MEDIUM×1
  
  閾值：
    分數 = 0：✅ 安全，可以新增
    分數 1~9：🟡 警戒，輸出警告後可繼續
    分數 10~99：🟠 危險，需要 Owner 確認
    分數 ≥ 100：🔴 停止，禁止新增，等待 Owner 解決

STEP E：輸出偵測報告
  格式見下方「衝突偵測報告格式」
```

### 演算法偽代碼（供技術參考）

```python
def detect_conflicts(new_exception_esl, existing_exceptions_esl_list):
    """
    輸入：新例外的 ESL 聲明，現有所有例外的 ESL 聲明列表
    輸出：衝突偵測報告
    """
    conflicts = []
    
    for existing in existing_exceptions_esl_list:
        for new_op in new_exception_esl.operations:
            for existing_op in existing.operations:
                
                # 類型1：直接衝突
                if (new_op.target == existing_op.target and
                    is_opposite_action(new_op.action, existing_op.action)):
                    conflicts.append({
                        'type': 'DIRECT_CONFLICT',
                        'severity': 'CRITICAL',
                        'new_op': new_op,
                        'existing_op': existing_op,
                        'existing_exception': existing.id
                    })
                
                # 類型2：範圍衝突
                elif (new_op.target == existing_op.target and
                      new_op.scope == 'ALL_TASKS' and
                      existing_op.scope == 'THIS_TASK_ONLY'):
                    conflicts.append({
                        'type': 'SCOPE_CONFLICT',
                        'severity': 'HIGH',
                        'new_op': new_op,
                        'existing_op': existing_op,
                        'existing_exception': existing.id
                    })
                
                # 類型3：語義衝突（需要 Codex 的語義理解）
                elif are_semantically_related(new_op.target, existing_op.target):
                    if could_conflict_at_runtime(new_op, existing_op):
                        conflicts.append({
                            'type': 'SEMANTIC_CONFLICT',
                            'severity': 'MEDIUM',
                            'new_op': new_op,
                            'existing_op': existing_op,
                            'existing_exception': existing.id
                        })
    
    # 計算衝突分數
    score = sum(
        100 if c['severity'] == 'CRITICAL' else
        10  if c['severity'] == 'HIGH' else
        1   for c in conflicts
    )
    
    return ConflictReport(conflicts=conflicts, score=score)


def is_opposite_action(action1, action2):
    """判斷兩個 action 是否相反"""
    opposites = {
        'ALLOW': ['DENY', 'FORBID'],
        'DENY': ['ALLOW', 'PERMIT'],
        'REQUIRE': ['DENY', 'OPTIONAL'],
        'OVERRIDE': ['KEEP_ORIGINAL'],
    }
    return action2 in opposites.get(action1, [])


def are_semantically_related(target1, target2):
    """
    判斷兩個 target 是否語義相關
    這是 Codex 最擅長的部分：語義理解
    
    例：
    - 'macro_snapshot.csv' 和 'CSV_WRITE' → 相關
    - 'MIDR_SIGNAL' 和 'UI_DISPLAY' → 相關（訊號影響顯示）
    - 'MIDR_ENGINE' 和 'CSS_STYLE' → 不相關
    """
    # Codex 用自然語言推理判斷
    pass
```

---

## 第三層：衝突偵測報告格式

### 標準報告格式

```markdown
## 🔍 例外衝突偵測報告
生成時間：[YYYY-MM-DD HH:MM]
新增例外：[ExceptionId]
偵測引擎：EXCEPTION_CONFLICT_DETECTOR v1.0

### 偵測摘要
衝突分數：[分數]
系統狀態：[✅安全 / 🟡警戒 / 🟠危險 / 🔴停止]
CRITICAL衝突：[數量]個
HIGH衝突：[數量]個
MEDIUM衝突：[數量]個

### 衝突詳情

#### [衝突編號]：[衝突類型] — [嚴重程度]
- 新例外操作：[ExceptionId] OP_[id]
  target: [目標]
  action: [動作]
  scope: [範圍]
- 現有例外操作：[ExceptionId] OP_[id]
  target: [目標]
  action: [動作]
  scope: [範圍]
- 衝突說明：[具體說明衝突的情境]
- 影響評估：[若不解決，會發生什麼]

### 建議解決方案
[針對每個 CRITICAL/HIGH 衝突，提供具體解決方案]

選項A：[解決方案A]
選項B：[解決方案B]

### 等待 Owner 決策
請回覆以下其中一項：
- 「選擇A」→ 採用解決方案A
- 「選擇B」→ 採用解決方案B
- 「取消新增」→ 放棄新增此例外文件
- 「自訂解決方案：[說明]」→ 採用自訂方案

actionable: false — 最終決策由Owner負責
```

### 實際範例：偵測到 CRITICAL 衝突

```markdown
## 🔍 例外衝突偵測報告
生成時間：2026-06-25 14:30
新增例外：TASK_MACRO_AUTO_WRITE
偵測引擎：EXCEPTION_CONFLICT_DETECTOR v1.0

### 偵測摘要
衝突分數：100
系統狀態：🔴 停止（禁止新增，等待Owner解決）
CRITICAL衝突：1個
HIGH衝突：0個
MEDIUM衝突：0個

### 衝突詳情

#### C001：DIRECT_CONFLICT — CRITICAL
- 新例外操作：TASK_MACRO_AUTO_WRITE OP_001
  target: macro_snapshot.csv
  action: ALLOW（允許自動寫入）
  scope: THIS_TASK_ONLY
- 現有例外操作：TASK_DAILY_WARROOM_UPDATE OP_002
  target: macro_snapshot.csv
  action: DENY（禁止自動寫入）
  scope: THIS_TASK_ONLY
- 衝突說明：
  兩個例外對 macro_snapshot.csv 的自動寫入有相反規定。
  當 Codex 執行每日更新任務時，若同時適用兩個例外，
  無法確定應該寫入還是不寫入。
- 影響評估：
  Codex 行為不確定，可能在不同執行時間產生不同結果。
  最壞情況：Codex 自動寫入了不應寫入的數據。

### 建議解決方案

選項A：修改 TASK_MACRO_AUTO_WRITE 的範圍
  將 scope 從 THIS_TASK_ONLY 改為 TASK_TYPE:MACRO_ONLY
  確保不與每日更新任務衝突

選項B：廢棄 TASK_DAILY_WARROOM_UPDATE 的 OP_002
  若 Owner 決定允許自動寫入，可移除禁止規則
  但需要確認這不會影響數據安全性

選項C：在 TASK_MACRO_AUTO_WRITE 中聲明優先順序
  明確聲明 DeferToExceptions: [TASK_DAILY_WARROOM_UPDATE]
  讓每日更新任務的禁止規則優先

### 等待 Owner 決策
請回覆：「選擇A」、「選擇B」、「選擇C」或「取消新增」

actionable: false — 最終決策由Owner負責
```

---

## 第四層：警示機制與 Owner 審核流程

### 警示等級與觸發條件

```
Level 0（靜默）：衝突分數 = 0
  → 直接允許新增，無需任何確認
  → 輸出：「✅ 衝突偵測通過，可以新增」

Level 1（資訊）：衝突分數 1~9（MEDIUM衝突）
  → 輸出警告，但允許繼續
  → 需要 Owner 閱讀警告後回覆「確認知悉」
  → 等待時間：30秒（AutoApprove 條件下）

Level 2（警戒）：衝突分數 10~99（HIGH衝突）
  → 輸出詳細衝突報告
  → 必須等待 Owner 明確選擇解決方案
  → 不得 AutoApprove
  → 等待時間：無限（直到 Owner 回覆）

Level 3（停止）：衝突分數 ≥ 100（CRITICAL衝突）
  → 觸發 STOP-E2（例外衝突停止）
  → 輸出完整衝突報告
  → 禁止新增例外文件
  → 必須等待 Owner 解決衝突後重新提交
```

### Owner 審核流程圖

```
新增例外請求
    ↓
STEP A：ESL 聲明驗證
    ├─ 無 ESL 聲明 → STOP-E1（缺少聲明）
    └─ 有 ESL 聲明 → 繼續
    ↓
STEP B：例外數量檢查
    ├─ 現有例外 ≥ 4個 → STOP-E3（超過上限）
    └─ 現有例外 < 4個 → 繼續
    ↓
STEP C：衝突偵測
    ├─ 分數 = 0 → ✅ 直接允許
    ├─ 分數 1~9 → Level 1 警告 → Owner 確認 → 允許
    ├─ 分數 10~99 → Level 2 警戒 → Owner 選擇方案 → 修改後重新偵測
    └─ 分數 ≥ 100 → Level 3 停止 → Owner 解決衝突 → 重新提交
    ↓
STEP D：優先順序驗證
    ├─ 有未聲明的衝突 → 要求補充 KnownConflicts
    └─ 優先順序完整 → 繼續
    ↓
STEP E：登記到 EXCEPTION_REGISTRY.md
    ↓
✅ 例外文件新增完成
```

---

## 第五層：EXCEPTION_REGISTRY.md 規格

```markdown
# EXCEPTION_REGISTRY.md
# 例外文件登記表
# 版本：v1.0 | 最後更新：[日期]

## 系統狀態
當前例外文件數：[N]/4
健康度評分：[分數]/100
最後偵測時間：[時間]

## 活躍例外文件

| 編號 | ExceptionId | 建立日期 | 到期日 | 優先級 | 衝突分數 | 狀態 |
|:---:|:----------:|:-------:|:-----:|:------:|:-------:|:---:|
| 1 | TASK_DAILY_WARROOM_UPDATE | 2026-06-25 | PERMANENT | 1 | 0 | ACTIVE |
| 2 | （空位） | — | — | — | — | — |
| 3 | （空位） | — | — | — | — | — |
| 4 | （空位） | — | — | — | — | — |

## 衝突矩陣（自動更新）

|  | TASK_DAILY_WARROOM_UPDATE |
|:---:|:---:|
| TASK_DAILY_WARROOM_UPDATE | — |

## 升級候選清單

| ExceptionId | 存在天數 | 引用次數 | 升級建議 |
|:----------:|:-------:|:-------:|:-------:|
| （無） | — | — | — |

## 廢棄歷史

| ExceptionId | 建立日期 | 廢棄日期 | 廢棄原因 |
|:----------:|:-------:|:-------:|:-------:|
| （無） | — | — | — |
```

---

## 第六層：Codex 執行指令（標準化提示）

當 Codex 收到「新增例外文件」請求時，必須執行以下標準化流程：

```
【例外衝突偵測執行指令】

收到新增例外文件請求時，依序執行：

1. 讀取新例外文件，找到 ESL_DECLARATION_BEGIN/END 區塊
   → 若無 ESL 聲明：輸出 STOP-E1，停止執行

2. 讀取 EXCEPTION_REGISTRY.md，取得所有 ACTIVE 例外文件清單
   → 若現有例外 ≥ 4個：輸出 STOP-E3，停止執行

3. 對每個現有例外文件，讀取其 ESL 聲明

4. 執行三類衝突比對：
   a. 直接衝突：相同 target + 相反 action → CRITICAL
   b. 範圍衝突：相同 target + 範圍不一致 → HIGH
   c. 語義衝突：語義相關的 target + 可能互相影響 → MEDIUM

5. 計算衝突分數：CRITICAL×100 + HIGH×10 + MEDIUM×1

6. 依分數輸出對應等級的偵測報告

7. 等待 Owner 決策（Level 2/3 必須等待，Level 0/1 可 AutoApprove）

8. Owner 確認後，更新 EXCEPTION_REGISTRY.md

注意：
- 所有輸出必須標注 actionable: false
- 不得在 Owner 確認前修改任何文件
- 偵測報告必須包含具體的解決方案選項
```

---

## 第七層：緊急停止代碼

```
STOP-E1：新例外文件缺少 ESL 聲明
  原因：無法進行衝突偵測
  處理：要求補充 ESL 聲明後重新提交

STOP-E2：偵測到 CRITICAL 衝突（分數 ≥ 100）
  原因：直接衝突，系統行為不確定
  處理：Owner 必須解決衝突後重新提交

STOP-E3：例外文件數量超過上限（≥ 4個）
  原因：超過安全閾值
  處理：Owner 必須先廢棄一個現有例外文件

STOP-E4：新例外文件缺少優先順序聲明
  原因：無法仲裁衝突
  處理：補充 Priority / OverridesExceptions / DeferToExceptions

STOP-E5：ESL 聲明格式錯誤
  原因：無法解析聲明
  處理：修正格式後重新提交
```

---

## 附錄：語義相關性判斷指南（供 Codex 參考）

```
以下 target 對被認為「語義相關」：

強相關（可能產生 SEMANTIC_CONFLICT）：
  - CSV_WRITE ↔ 任何 *.csv 文件
  - MIDR_SIGNAL ↔ UI_DISPLAY
  - MIDR_SIGNAL ↔ ALERT_OUTPUT
  - RULE_STATUS ↔ SIGNAL_CALCULATION
  - DATA_SOURCE ↔ BACKTEST_RESULT
  - MACRO_DATA ↔ RISK_LEVEL_CALCULATION

弱相關（通常不產生衝突）：
  - CSS_STYLE ↔ MIDR_ENGINE
  - HTML_LAYOUT ↔ CSV_WRITE
  - UI_ANIMATION ↔ DATA_CALCULATION

無關（不需要比對）：
  - 完全不同領域的操作
  - 例：字體設定 ↔ 數據庫操作
```

---

*EXCEPTION_CONFLICT_DETECTOR v1.0 | 2026-06-25 | 退休存股戰情室*
*本文件定義了例外衝突自動偵測系統的完整規格，供 Codex 執行時參考*
*actionable: false — 最終決策由Owner負責*