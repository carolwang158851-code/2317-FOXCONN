# OWNER_DECISION_TREE.md
# Owner 審核決策樹：衝突解決標準流程
# 版本：v1.0 | 日期：2026-06-25

---

## 使用說明

```
當 EXCEPTION_CONFLICT_DETECTOR 觸發 Owner 審核時，
依照本決策樹逐步回答問題，即可得到標準解法。

每個節點只問一個問題，回答「是/否」或選擇選項。
決策完成後，Codex 自動將結果回寫到 ESL 的 KnownConflicts 欄位。
```

---

## 決策樹主幹

```
收到衝突報告
    │
    ▼
【ROOT】衝突嚴重程度？
    ├─ CRITICAL（分數≥100）→ 【NODE_CRITICAL】
    ├─ HIGH（分數10~99）   → 【NODE_HIGH】
    └─ MEDIUM（分數1~9）   → 【NODE_MEDIUM】
```

---

## CRITICAL 衝突決策路徑

```
【NODE_CRITICAL】
問：兩個例外對同一操作有相反規定。哪個例外的規定更重要？
    │
    ├─ 新例外更重要（新規定應覆蓋舊規定）
    │      → ✅ 解法：THIS_WINS
    │
    ├─ 現有例外更重要（舊規定應保留）
    │      → ✅ 解法：OTHER_WINS
    │
    ├─ 兩者都需要，但適用範圍不同
    │      → 【NODE_SCOPE_SPLIT】
    │              │
    │              ├─ 按任務類型分割 → ✅ 解法：SCOPE_BY_TASK
    │              ├─ 按條件分割     → ✅ 解法：SCOPE_BY_CONDITION
    │              └─ 按優先順序分割 → ✅ 解法：PRIORITY_DECLARE
    │
    ├─ 需要合併成新規定
    │      → ✅ 解法：MERGE
    │
    └─ 其中一個例外應該廢棄
           → 【NODE_RETIRE】
                   │
                   ├─ 廢棄新例外（不新增）    → ✅ 解法：CANCEL_NEW
                   └─ 廢棄現有例外（先廢再增）→ ✅ 解法：RETIRE_EXISTING
```

---

## HIGH 衝突決策路徑

```
【NODE_HIGH】
問：新例外的 ALL_TASKS 範圍是否真的必要？
    │
    ├─ 是，確實需要影響所有任務
    │      → 【NODE_HIGH_CONFIRM】
    │              │
    │              ├─ 現有例外的 THIS_TASK_ONLY 仍然有效
    │              │      → ✅ 解法：OTHER_WINS
    │              ├─ 現有例外的 THIS_TASK_ONLY 已無效
    │              │      → ✅ 解法：THIS_WINS
    │              └─ 部分有效，需要合併
    │                     → ✅ 解法：MERGE
    │
    ├─ 否，只需要影響特定任務類型
    │      → ✅ 解法：NARROW_SCOPE
    │
    └─ 不確定，需要更多資訊
           → 【NODE_HIGH_CLARIFY】
                   │
                   ├─ 確認只需影響特定任務類型 → ✅ 解法：NARROW_SCOPE
                   └─ 確認需要影響所有任務     → 【NODE_HIGH_CONFIRM】
```

---

## MEDIUM 衝突決策路徑

```
【NODE_MEDIUM】
問：語義相關的操作在實際執行中會互相影響嗎？
    │
    ├─ 會發生，需要明確處理
    │      → 【NODE_MEDIUM_HANDLE】
    │              │
    │              ├─ 在新例外中明確聲明優先順序 → ✅ 解法：PRIORITY_DECLARE
    │              ├─ 修改新例外的操作範圍       → ✅ 解法：NARROW_SCOPE
    │              └─ 在兩個例外中都加入聲明     → ✅ 解法：ACKNOWLEDGE
    │
    ├─ 不會發生，可以忽略
    │      → ✅ 解法：ACKNOWLEDGE
    │
    └─ 不確定，先記錄觀察
           → ✅ 解法：MONITOR
```

---

## 標準解法庫（10種）

### 解法一：THIS_WINS（新例外優先）

```
適用：新例外的規定比現有例外更重要，應該覆蓋
風險：低（明確聲明優先順序）

ESL 回寫格式：
  KnownConflicts:
    - with: {現有例外ID}
      resolution: THIS_WINS
      description: "{說明為何新例外優先}"
      decidedAt: {YYYY-MM-DD}
      decidedBy: Owner

Codex 執行動作：
  1. 在新例外文件的 KnownConflicts 中加入上述聲明
  2. 在現有例外文件的 KnownConflicts 中加入對應聲明：
     resolution: DEFERS_TO_{新例外ID}
  3. 更新 EXCEPTION_REGISTRY.md 的衝突矩陣
```

### 解法二：OTHER_WINS（現有例外優先）

```
適用：現有例外的規定應該保留，新例外讓位
風險：低（明確聲明優先順序）

ESL 回寫格式：
  KnownConflicts:
    - with: {現有例外ID}
      resolution: OTHER_WINS
      description: "{說明為何現有例外優先}"
      decidedAt: {YYYY-MM-DD}
      decidedBy: Owner

Codex 執行動作：
  1. 在新例外文件的 KnownConflicts 中加入上述聲明
  2. 新例外的衝突操作在遇到現有例外時自動讓位
  3. 更新 EXCEPTION_REGISTRY.md 的衝突矩陣
```

### 解法三：MERGE（合併規定）

```
適用：兩個例外的規定都有道理，需要合併為一致的規定
風險：中（需要修改現有例外文件）

ESL 回寫格式：
  # 在兩個例外文件中都加入：
  KnownConflicts:
    - with: {另一個例外ID}
      resolution: MERGED
      description: "已合併為統一規定，見 OP_{合併後的操作ID}"
      decidedAt: {YYYY-MM-DD}
      decidedBy: Owner

Codex 執行動作：
  1. 修改兩個例外文件的 Operations，加入條件分支
  2. 在兩個文件的 KnownConflicts 中加入 MERGED 聲明
  3. 更新 EXCEPTION_REGISTRY.md
  注意：修改現有例外文件需要 Owner 額外確認（STOP-E6 前置檢查）
```

### 解法四：NARROW_SCOPE（縮小範圍）

```
適用：新例外的 ALL_TASKS 範圍過大，縮小為特定任務類型
風險：低（縮小影響範圍）

ESL 回寫格式：
  # 修改新例外的 Operations：
  Operations:
    - id: OP_001
      target: {目標}
      action: {動作}
      scope: TASK_TYPE:{具體任務類型}  # 從 ALL_TASKS 改為具體類型

Codex 執行動作：
  1. 修改新例外文件的 Operations.scope 欄位
  2. 重新執行衝突偵測（縮小範圍後應無衝突）
  3. 若仍有衝突，繼續決策樹
```

### 解法五：SCOPE_BY_TASK（按任務類型分割）

```
適用：兩個例外都需要，但應該分別適用於不同任務類型
風險：低

ESL 回寫格式：
  # 新例外加入任務類型限制：
  Operations:
    - id: OP_001
      scope: TASK_TYPE:{新例外適用的任務類型}
  
  KnownConflicts:
    - with: {現有例外ID}
      resolution: SCOPE_SPLIT_BY_TASK
      description: "按任務類型分割：新例外適用 {類型A}，現有例外適用 {類型B}"
      decidedAt: {YYYY-MM-DD}
      decidedBy: Owner
```

### 解法六：SCOPE_BY_CONDITION（按條件分割）

```
適用：兩個例外都需要，但應該在不同條件下觸發
風險：中（條件邏輯需要驗證）

ESL 回寫格式：
  Operations:
    - id: OP_001
      target: {目標}
      action: {動作}
      condition: "{具體觸發條件}"
      scope: THIS_TASK_ONLY
  
  KnownConflicts:
    - with: {現有例外ID}
      resolution: SCOPE_SPLIT_BY_CONDITION
      description: "按條件分割：新例外在 {條件A} 時觸發，現有例外在 {條件B} 時觸發"
      decidedAt: {YYYY-MM-DD}
      decidedBy: Owner
```

### 解法七：PRIORITY_DECLARE（聲明優先順序）

```
適用：兩個例外都保留，但明確聲明誰優先
風險：低（明確聲明）

ESL 回寫格式：
  # 在新例外文件中：
  Priority: {數字，越小越優先}
  OverridesExceptions:
    - {現有例外ID}  # 若新例外優先
  DeferToExceptions:
    - {現有例外ID}  # 若現有例外優先
  
  KnownConflicts:
    - with: {現有例外ID}
      resolution: PRIORITY_DECLARED
      description: "優先順序已明確聲明：{說明}"
      decidedAt: {YYYY-MM-DD}
      decidedBy: Owner
```

### 解法八：CANCEL_NEW（取消新增）

```
適用：新例外與現有例外衝突，且現有例外更重要，放棄新增
風險：無

ESL 回寫格式：無（不新增例外文件）

Codex 執行動作：
  1. 輸出取消記錄
  2. 不修改任何文件
  3. 在 EXCEPTION_REGISTRY.md 的「廢棄歷史」中記錄：
     | {新例外ID} | {日期} | {日期} | 衝突取消：與 {現有例外ID} 衝突 |
```

### 解法九：RETIRE_EXISTING（廢棄現有例外）

```
適用：現有例外已過時，新例外應該取代它
風險：中（廢棄現有規則可能影響其他任務）

ESL 回寫格式：
  # 更新 EXCEPTION_REGISTRY.md：
  | {現有例外ID} | {建立日期} | {今日} | 被 {新例外ID} 取代 |

Codex 執行動作：
  1. 將現有例外文件標記為 RETIRED
  2. 更新 EXCEPTION_REGISTRY.md
  3. 新增新例外文件（此時無衝突）
  注意：廢棄現有例外需要 Owner 額外確認（影響評估）
```

### 解法十：ACKNOWLEDGE / MONITOR（確認知悉 / 觀察監控）

```
適用：語義衝突已知，但可接受（ACKNOWLEDGE）或需要觀察（MONITOR）
風險：低（記錄在案）

ESL 回寫格式（兩個例外文件都需要更新）：
  KnownConflicts:
    - with: {另一個例外ID}
      resolution: ACKNOWLEDGED  # 或 MONITOR
      description: "{說明衝突內容與為何可接受}"
      decidedAt: {YYYY-MM-DD}
      decidedBy: Owner
      reviewDate: {下次審查日期，MONITOR 時必填}
```

---

## KnownConflicts 知識庫回寫規格

### 回寫觸發條件

```
每次 Owner 完成決策後，Codex 必須執行以下回寫：

1. 更新新例外文件的 KnownConflicts 欄位
2. 更新現有例外文件的 KnownConflicts 欄位（對稱記錄）
3. 更新 EXCEPTION_REGISTRY.md 的衝突矩陣
4. 輸出回寫確認報告
```

### 回寫格式標準

```yaml
KnownConflicts:
  - conflictId: CONFLICT_{新例外ID}_{現有例外ID}_{日期}
    with: {另一個例外ID}
    conflictType: DIRECT_CONFLICT | SCOPE_CONFLICT | SEMANTIC_CONFLICT
    severity: CRITICAL | HIGH | MEDIUM
    resolution: THIS_WINS | OTHER_WINS | MERGE | NARROW_SCOPE |
                SCOPE_BY_TASK | SCOPE_BY_CONDITION | PRIORITY_DECLARE |
                CANCEL_NEW | RETIRE_EXISTING | ACKNOWLEDGED | MONITOR
    description: "{具體說明衝突內容與解決方式}"
    decidedAt: {YYYY-MM-DD}
    decidedBy: Owner
    reviewDate: {YYYY-MM-DD，僅 MONITOR 時必填}
    autoResolved: false  # 所有衝突都需要 Owner 決策，不自動解決
```

### 知識庫累積效果

```
當 KnownConflicts 累積足夠多的記錄後，
Codex 可以在偵測到「已知衝突」時，
直接引用歷史決策，而不需要再次觸發 Owner 審核。

判斷「已知衝突」的條件：
  1. conflictType 相同
  2. target 相同
  3. action 相同
  4. 歷史決策的 resolution 不是 MONITOR（MONITOR 需要重新評估）

引用歷史決策時，Codex 輸出：
  「偵測到已知衝突（conflictId: {ID}），
   歷史決策為 {resolution}，
   自動套用歷史解法。
   若需要重新決策，請回覆「重新審核」。」
```

---

## Owner 審核的標準回覆格式

```
Owner 收到衝突報告後，只需回覆以下格式之一：

快速回覆（適用於明確情況）：
  「THIS_WINS」
  「OTHER_WINS」
  「CANCEL_NEW」
  「NARROW_SCOPE」
  「ACKNOWLEDGE」
  「MONITOR」

詳細回覆（適用於需要說明的情況）：
  「解法：THIS_WINS
   原因：新例外的每日更新需求比舊例外的限制更重要
   備注：舊例外的限制已過時」

重新審核（適用於不確定的情況）：
  「重新審核：我需要更多資訊
   問題：[具體問題]」
```

---

## 完整流程示範

### 情境：TASK_MACRO_AUTO_WRITE 與 TASK_DAILY_WARROOM_UPDATE 衝突

```
偵測報告：
  衝突分數：200（CRITICAL×2）
  C001：DIRECT_CONFLICT
    新例外 OP_001：macro_snapshot.csv, ALLOW_AUTO_WRITE
    現有例外 OP_002：macro_snapshot.csv, DENY_AUTO_WRITE

決策樹執行：
  ROOT → CRITICAL → NODE_CRITICAL
  問：哪個例外的規定更重要？

Owner 回覆：「OTHER_WINS，原因：每日更新任務禁止自動寫入是核心安全規定」

Codex 執行回寫：
  1. 在 TASK_MACRO_AUTO_WRITE 中加入：
     KnownConflicts:
       - conflictId: CONFLICT_MACRO_AUTO_WRITE_DAILY_WARROOM_20260625
         with: TASK_DAILY_WARROOM_UPDATE
         conflictType: DIRECT_CONFLICT
         severity: CRITICAL
         resolution: OTHER_WINS
         description: "每日更新任務的禁止自動寫入規定優先，MACRO_AUTO_WRITE讓位"
         decidedAt: 2026-06-25
         decidedBy: Owner
         autoResolved: false

  2. 在 TASK_DAILY_WARROOM_UPDATE 中加入：
     KnownConflicts:
       - conflictId: CONFLICT_MACRO_AUTO_WRITE_DAILY_WARROOM_20260625
         with: TASK_MACRO_AUTO_WRITE
         conflictType: DIRECT_CONFLICT
         severity: CRITICAL
         resolution: THIS_WINS
         description: "本例外的禁止自動寫入規定優先於MACRO_AUTO_WRITE"
         decidedAt: 2026-06-25
         decidedBy: Owner
         autoResolved: false

  3. 更新 EXCEPTION_REGISTRY.md 衝突矩陣：
     | TASK_DAILY_WARROOM_UPDATE | TASK_MACRO_AUTO_WRITE |
     | THIS_WINS（OP_002優先）   |                       |

輸出確認：
  ✅ 衝突已解決，KnownConflicts 已回寫
  ✅ EXCEPTION_REGISTRY.md 已更新
  ✅ 下次遇到相同衝突，將自動套用 OTHER_WINS 解法
  actionable: false — 最終決策由Owner負責
```

---

## 知識庫健康度指標

```
每季執行一次知識庫審查，輸出以下指標：

1. 累積衝突記錄數：{N}條
2. 已解決衝突：{N}條（THIS_WINS/OTHER_WINS/MERGE等）
3. 待觀察衝突（MONITOR）：{N}條
4. 超過 reviewDate 的 MONITOR 記錄：{N}條（需要重新評估）
5. 最常見衝突類型：{類型}（{N}次）
6. 最常見解法：{解法}（{N}次）

若「最常見衝突類型」出現超過3次，
建議升級為正式規則（策略B：更新 RULE_STATUS_MANIFEST）
```

---

*OWNER_DECISION_TREE v1.0 | 2026-06-25 | 退休存股戰情室*
*本文件定義了 Owner 審核衝突的標準決策流程與知識庫回寫規格*
*actionable: false — 最終決策由Owner負責*