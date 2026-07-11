# KB_CONSISTENCY_AUDITOR.md
# KnownConflicts 知識庫矛盾稽核機制
# 版本：v1.1.0 | 建立日期：2026-06-25 | 更新日期：2026-06-26 | 狀態：ACTIVE

---

## 一、設計目的

KnownConflicts 知識庫隨時間累積歷史決策，可能出現四類一致性風險：

| 代碼 | 矛盾類型 | 嚴重程度 | 發生頻率 | 可偵測性 |
|:---:|:-------:|:-------:|:-------:|:-------:|
| R1 | 直接矛盾（同一衝突對，相反決策） | CRITICAL | 中 | 高（精確比對） |
| R2 | 傳遞矛盾（A>B>C>A 循環優先） | HIGH | 低 | 中（圖遍歷） |
| R3 | 情境漂移（決策情境已過時） | HIGH | 高 | 低（語義理解） |
| R4 | 範圍侵蝕（NARROW_SCOPE 累積 = ALL_TASKS） | MEDIUM | 中 | 中（集合運算） |

**核心原則**：知識庫不是只能追加的日誌，必須支援版本快照、決策溯源、版本回滾。

---

## 二、稽核觸發時機

### 2.1 定期稽核（月度，自動）
- 每月第一個交易日執行
- 稽核範圍：所有 status=ACTIVE 的記錄
- 輸出：稽核報告 + 健康度評分

### 2.2 即時稽核（事件驅動，自動）
觸發條件（任一滿足）：
- 新增 KnownConflicts 記錄時
- 例外文件數量變更時
- 市場情境重大變化（RiskLevel 升級、PB 跨越關鍵門檻）

### 2.3 手動稽核（Owner 要求）
- Owner 輸入「執行知識庫稽核」
- 立即執行完整四類矛盾偵測

---

## 三、四類矛盾偵測演算法

### 3.1 R1 直接矛盾偵測（精確比對）

```
演算法：
1. 建立索引：(newException, existingException) → [所有相關記錄]
   （衝突對以排序後的 tuple 為 key，確保 A↔B = B↔A）
2. 對每個衝突對，檢查是否同時存在 THIS_WINS 和 OTHER_WINS
3. 若存在 → 標記為 R1_DIRECT 矛盾

處理規則：
- 保留較新決策（decidedAt 較晚者）
- 退役較舊決策（標記為 SUPERSEDED）
- 自動執行，無需 Owner 確認
```

### 3.2 R2 傳遞矛盾偵測（有向圖環路）

```
演算法：
1. 建立優先順序有向圖：
   THIS_WINS → winner 指向 loser（winner 優先於 loser）
   OTHER_WINS → existing 指向 new
2. 對圖中每個節點執行 DFS 環路偵測
3. 若發現環路 → 標記為 R2_TRANSITIVE 矛盾，輸出循環路徑

處理規則：
- 輸出循環路徑給 Owner 審核
- 建議審查循環中最新的決策
- 需要 Owner 確認後才能修改
```

### 3.3 R3 情境漂移偵測（情境快照比對）

```
演算法：
對每筆 ACTIVE 記錄，比較 context_snapshot 與當前情境：

漂移觸發條件（任一滿足）：
  條件 A：MIDR 從 ADD/HOLD 漂移至 BLOCK/STRONG_BLOCK
  條件 B：RiskLevel 從 NORMAL 漂移至 CAUTION/SYSTEMIC
  條件 C：PB 跨越關鍵門檻（BLOCK線 1.924x / OVERHEAT線 2.115x）
  條件 D：決策日期超過 90 天且無 expiryDate 設定

處理規則：
- 標記為 CONTEXT_STALE
- 觸發 Owner 重新確認（不自動退役）
- Owner 可選擇：確認仍適用（展延）/ 修改決策 / 退役
```

### 3.4 R4 範圍侵蝕偵測（集合覆蓋率）

```
演算法：
1. 收集所有 ACTIVE 且 resolution=NARROW_SCOPE 的記錄
2. 提取每筆記錄的 narrowScopeTarget 集合
3. 計算覆蓋率 = |已覆蓋任務類型| / |所有已知任務類型|

警示閾值：
  覆蓋率 ≥ 100% → 🔴 範圍侵蝕（建議合併為 ALL_TASKS）
  覆蓋率 ≥ 75%  → 🟡 範圍侵蝕警告（監控）
  覆蓋率 < 75%  → ✅ 正常

處理規則：
- 100% 時：建議合併為單一 ALL_TASKS 決策，退役個別記錄
- 需要 Owner 確認後執行合併
```

---

## 四、健康度評分公式（完整版 v1.1）

### 4.1 設計原則

健康度評分反映三個核心維度：
1. **矛盾嚴重程度**：CRITICAL > HIGH > MEDIUM，扣分權重不同
2. **可偵測性修正**：可精確偵測的矛盾（R1/R4）扣分較重；需語義理解的（R3）扣分較輕但累積效應大
3. **時效性懲罰**：PENDING_REVIEW 超時未處理，代表 Owner 認知負擔積壓

### 4.2 各類矛盾扣分細則

**R1 直接矛盾（CRITICAL，可精確偵測）**
```
R1_扣分 = min(R1數量 × 20, 60)  ← 上限60分

理由：同一衝突對出現相反決策，Codex 完全無法自動複用
範例：R1=1 → -20分 | R1=2 → -40分 | R1=3+ → -60分（上限）
```

**R2 傳遞矛盾（HIGH，需圖遍歷偵測）**
```
R2_扣分 = min(R2循環數 × 15, 45)  ← 上限45分

理由：優先順序形成環狀，Codex 推理可能陷入無限循環
範例：R2=1 → -15分 | R2=2 → -30分 | R2=3+ → -45分（上限）
```

**R3 情境漂移（HIGH 嚴重程度，累進扣分）**
```
R3_扣分 = 累進計算（非線性）：
  第 1~2 個：每個 -5 分
  第 3~5 個：每個 -8 分（累積效應加重）
  第 6 個起：每個 -12 分（大量漂移代表系統性問題）

理由：單一 R3 影響有限，但大量 R3 代表知識庫與現實嚴重脫節
範例：R3=1 → -5分 | R3=3 → -18分 | R3=5 → -34分 | R3=8 → -70分
```

**R4 範圍侵蝕（MEDIUM，集合運算偵測）**
```
R4_扣分 = min(侵蝕率% × 0.10, 10)  ← 上限10分

理由：R4 是漸進式問題，不像 R1/R2 那樣立即造成錯誤
範例：侵蝕率50% → -5分 | 侵蝕率75% → -7.5分 | 侵蝕率100% → -10分
```

**時效性懲罰**
```
時效性懲罰 = min(PENDING_REVIEW超過7天筆數 × 3, 15)  ← 上限15分

理由：Owner 長期未回應，系統處於不確定狀態
```

**複合風險加成懲罰（新增）**
```
若 R1 ≥ 1 AND R3 ≥ 3，額外扣 10 分

理由：直接矛盾 + 大量情境漂移同時存在，修復難度非線性上升
```

### 4.3 完整計算公式

```
健康度 = max(100 - R1扣分 - R2扣分 - R3扣分 - R4扣分 - 時效性懲罰 - 複合懲罰, 0)

其中：
  R1扣分 = min(R1數量 × 20, 60)
  R2扣分 = min(R2循環數 × 15, 45)
  R3扣分 = 累進計算（1~2個×5，3~5個×8，6+個×12）
  R4扣分 = min(侵蝕率% × 0.10, 10)
  時效性懲罰 = min(超時筆數 × 3, 15)
  複合懲罰 = 10（若 R1≥1 且 R3≥3，否則 0）
```

### 4.4 健康等級分類

```
┌──────────────────────────────────────────────────────────────────┐
│  健康等級  │ 分數範圍 │ 顏色 │ 狀態說明                          │
├──────────────────────────────────────────────────────────────────┤
│  GREEN     │ 85~100  │ 🟢   │ 健康，Codex 可正常自動複用        │
│  YELLOW    │ 70~84   │ 🟡   │ 警戒，建議 Owner 月底前審核       │
│  ORANGE    │ 50~69   │ 🟠   │ 危險，觸發 Owner 緊急審核         │
│  RED       │ 0~49    │ 🔴   │ 崩潰，暫停自動複用                │
└──────────────────────────────────────────────────────────────────┘

目標：每次稽核後健康度 ≥ 85 分（GREEN）
警戒：健康度 < 70 分 → 觸發 Owner 緊急審核
崩潰：健康度 < 50 分 → 暫停知識庫自動複用
```

### 4.5 強制人工介入閾值條件

以下任一條件觸發，**立即暫停知識庫自動複用**：

```
條件1：健康度 < 50 分（RED 等級）
  → 知識庫整體可靠性不足，不可信任自動複用

條件2：R1 ≥ 3（三個以上直接矛盾）
  → 即使總分 ≥ 50，直接矛盾過多代表系統性邏輯錯誤

條件3：R1 ≥ 1 且 R2 ≥ 2（直接矛盾 + 多個循環）
  → 複合型邏輯錯誤，Codex 推理路徑完全不可信

條件4：PENDING_REVIEW 超過 14 天未處理（任一筆）
  → Owner 長期未回應，系統處於不確定狀態超過合理期限

觸發後的強制動作：
  1. 輸出 🔴 CRITICAL ALERT：知識庫已暫停自動複用
  2. 列出所有需要 Owner 處理的項目清單
  3. 等待 Owner 確認後才恢復自動複用
  4. 記錄暫停時間與恢復時間至稽核日誌
```

### 4.6 健康度計算範例

```
範例一：本次稽核（2026-06-25，10筆記錄）
  R1=1, R2=2, R3=5, R4=100%, PENDING_OVERDUE=0

  R1扣分：min(1×20, 60) = 20
  R2扣分：min(2×15, 45) = 30
  R3扣分：5+5+8+8+8 = 34
  R4扣分：min(100×0.10, 10) = 10
  時效性：min(0×3, 15) = 0
  複合懲罰：R1≥1 AND R3≥3 → 10
  健康度：max(100-20-30-34-10-0-10, 0) = 0 分 → 🔴 RED
  → 觸發強制人工介入（R1≥1 且 R2≥2）

範例二：稽核後修復（退役R1，修復R2，R3降至1，R4合併）
  R1=0, R2=0, R3=1, R4=0%, PENDING_OVERDUE=0

  健康度：100-0-0-5-0-0-0 = 95 分 → 🟢 GREEN

範例三：一般運作狀態
  R1=0, R2=1, R3=2, R4=50%, PENDING_OVERDUE=1

  R1扣分：0
  R2扣分：15
  R3扣分：5+5 = 10
  R4扣分：5
  時效性：3
  複合懲罰：不觸發（R1=0）
  健康度：100-0-15-10-5-3-0 = 67 分 → 🟠 ORANGE（需緊急審核）
```

---

## 五、版本化管理架構

### 5.1 三層結構

```
Layer 1：ACTIVE 工作層
  檔案：KnownConflicts_ACTIVE.yaml
  內容：只包含 status=ACTIVE 的記錄
  規則：Codex 執行時只讀取此層；每次稽核後自動更新

Layer 2：ARCHIVE 歷史層
  檔案：KnownConflicts_ARCHIVE_v{N}.yaml
  內容：status=RETIRED / SUPERSEDED / MERGED / ORPHANED 的記錄
  規則：唯讀，不可修改；保留退役原因、退役日期、繼承者 ID

Layer 3：SNAPSHOT 快照層
  檔案：KnownConflicts_SNAPSHOT_{YYYY-MM-DD}.yaml
  內容：稽核當下所有記錄的完整快照（含 ACTIVE + RETIRED）
  規則：每次月度稽核時建立；用於回滾與審計追蹤
```

### 5.2 版本號規則（Semantic Versioning）

```
格式：v{MAJOR}.{MINOR}.{PATCH}

MAJOR 升版（手動，Owner 確認）：
  - 重大架構變更（新增矛盾類型偵測）
  - 超過 5 筆 CRITICAL 決策被退役
  - 例外文件總數超過上限（N=4）觸發重組

MINOR 升版（稽核時自動）：
  - 每次月度稽核完成後
  - 有新決策被加入或退役

PATCH 升版（即時，自動）：
  - 單筆記錄的 status 變更
  - 新增 KnownConflicts 記錄
```

### 5.3 版本間差異追蹤（Diff）

每次 MINOR 升版時，自動產生 diff 報告，記錄：
- 新增記錄數
- 退役記錄數（含退役原因）
- 情境更新數（R3 漂移觸發）
- 合併記錄數（R4 侵蝕修復）
- 健康度變化（稽核前 → 稽核後）

---

## 六、退役狀態機

### 6.1 五種退役觸發條件

```
T1 時間到期：expiryDate 到期 → PENDING_REVIEW → Owner 確認 → RETIRED
T2 情境漂移：R3 偵測觸發 → CONTEXT_STALE → Owner 確認 → RETIRED / ACTIVE（展延）
T3 被取代：  R1 偵測觸發 → SUPERSEDED（立即，無需確認）
T4 範圍合併：R4 偵測觸發 → MERGED（Owner 確認後執行）
T5 例外退役：對應例外文件廢棄 → ORPHANED → RETIRED
```

### 6.2 退役記錄格式（完整溯源）

```yaml
- conflictId: CONFLICT_001
  # ... 原始欄位 ...

  # 退役資訊（稽核時自動填入）
  status: SUPERSEDED
  retiredAt: 2026-06-25
  retiredBy: AUDIT_R1_DIRECT        # 稽核機制代碼
  retiredReason: "直接矛盾：被 CONFLICT_002（2026-09-20）取代"
  supersededBy: CONFLICT_002        # 繼承者 ID
  retentionPolicy: KEEP_2_YEARS     # 保留期限
  archiveLocation: KnownConflicts_ARCHIVE_v1.3.0.yaml
```

### 6.3 保留期限政策

| 退役狀態 | 保留期限 | 原因 |
|:-------:|:-------:|:---:|
| SUPERSEDED | 2 年 | 可能需要回滾 |
| CONTEXT_STALE | 1 年 | 情境記錄有參考價值 |
| MERGED | 6 個月 | 合併後確認無誤即可清除 |
| ORPHANED | 3 個月 | 確認無依賴後清除 |

**自動清除條件**：保留期限到期 AND 無任何 ACTIVE 記錄引用此退役記錄
→ 移入 COLD_ARCHIVE（壓縮存儲，不再載入記憶體）

---

## 七、稽核報告輸出格式

```markdown
## KnownConflicts 稽核報告
稽核日期：{YYYY-MM-DD}
知識庫版本：v{MAJOR}.{MINOR}.{PATCH}
記錄總數：{N} 條（ACTIVE: {A}，RETIRED: {R}）

### 健康度評分：{score}/100

### 發現問題
| 類型 | 嚴重程度 | 數量 | 建議行動 |
|:---:|:-------:|:---:|:-------:|
| R1 直接矛盾 | CRITICAL | {n} | 自動退役較舊記錄 |
| R2 傳遞矛盾 | HIGH | {n} | Owner 審核循環路徑 |
| R3 情境漂移 | HIGH | {n} | Owner 重新確認 |
| R4 範圍侵蝕 | MEDIUM | {n} | 建議合併 |

### 建議行動清單
1. [R1] RETIRE {conflictId}，KEEP {conflictId}
2. [R2] 審查循環：{A} → {B} → {C} → {A}
3. [R3] 重新確認：{conflictId}（情境漂移：{drift_items}）
4. [R4] 合併 NARROW_SCOPE 記錄為 ALL_TASKS

### 下次稽核：{next_audit_date}
actionable: false — 最終決策由 Owner 負責
```

---

## 八、與現有文件的協作關係

```
EXCEPTION_CONFLICT_DETECTOR.md
  → 新增例外時偵測衝突，計算分數（0/1/10/100）
  → 觸發 Owner 審核流程
  → 決策結果寫入 KnownConflicts

OWNER_DECISION_TREE.md
  → 引導 Owner 做出衝突決策
  → 決策結果回寫 KnownConflicts.KnownConflicts 欄位

KB_CONSISTENCY_AUDITOR.md（本文件）
  → 定期掃描 KnownConflicts 的歷史一致性
  → 偵測四類矛盾（R1/R2/R3/R4）
  → 管理版本化與退役機制
  → 輸出健康度評分

三者形成完整的知識庫生命週期管理：
  新增 → 偵測 → 決策 → 記錄 → 稽核 → 退役
```

---

## 九、執行 SOP（Codex 操作指引）

### 月度稽核執行步驟

```
Step 1：讀取 KnownConflicts_ACTIVE.yaml
Step 2：取得當前情境快照（RiskLevel / PB / MIDR / VIX）
Step 3：執行 R1 直接矛盾偵測（精確比對）
Step 4：執行 R2 傳遞矛盾偵測（DFS 環路）
Step 5：執行 R3 情境漂移偵測（快照比對）
Step 6：執行 R4 範圍侵蝕偵測（集合覆蓋率）
Step 7：計算健康度評分
Step 8：產生稽核報告
Step 9：執行自動修復（R1 SUPERSEDED、R4 MERGED）
Step 10：觸發 Owner 審核（R2 循環、R3 漂移）
Step 11：更新 KnownConflicts_ACTIVE.yaml
Step 12：建立 SNAPSHOT 快照
Step 13：升版（MINOR +1）
```

### 禁止事項

```
❌ 禁止直接刪除任何 KnownConflicts 記錄（必須走退役流程）
❌ 禁止修改 ARCHIVE 層的記錄（唯讀）
❌ 禁止在健康度 < 50 分時自動複用歷史決策
❌ 禁止跳過 Owner 確認直接執行 R2/R3 修復
```

---

## 十、版本歷史

| 版本 | 日期 | 變更說明 |
|:---:|:---:|:-------:|
| v1.0.0 | 2026-06-25 | 初始建立，包含 R1/R2/R3/R4 四類偵測 |
| v1.1.0 | 2026-06-26 | 健康度評分完整版：累進扣分、GREEN/YELLOW/ORANGE/RED等級、強制人工介入閾值 |

---

> **actionable: false — 最終決策由 Owner 負責**
> 本文件為 Codex 執行指引，所有稽核結果僅供參考，Owner 保有最終決策權。
