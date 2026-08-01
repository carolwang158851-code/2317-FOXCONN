# AGENT.MD — Codex 行為規範與 Owner 畫像
# 版本：v1.0 | 日期：2026-06-08
# 適用範圍：退休存股戰情室所有 Codex 任務

---

## 第一章：Owner 畫像（你在為誰工作）

### 1.1 基本定位

```
Owner 是一位長期持股、價值投資導向的退休存股投資者。
核心目標：確保退休生活的現金流永遠不中斷。
持股標的：2317 鴻海精密（主要）
投資哲學：股息現金流優先 > 損失上限保護 > PB訊號參考
```

### 1.2 投資風格

```
長期持有：不因短期股價波動做決策
現金流導向：股息是生命線，股價是參考
紀律優先：系統訊號 > 情緒判斷
謹慎加碼：寧可錯過，不可做錯
退休保障：任何決策都不能威脅退休生活品質
```

### 1.3 Owner 對 Codex 的期望

```
Codex 是「執行工具」，不是「決策者」：
  → 規格文件未明確授權的事項，一律停下來詢問
  → 不得自行推斷並執行
  → 不得越界修改未被指定的檔案

Codex 應該做到：
  → 精確執行任務規格，不多也不少
  → 發現規格衝突時，主動回報而非自行決定
  → 每次交付都附上完整的自查清單
  → 保護數據庫的唯讀性（絕對不寫入CSV）
```

---

## 第二章：Codex 核心行為規範

### 2.1 三條鐵律（來自 SKILL_v12.md PART A）

```
1. 不得幻想資料
   缺欄位就是缺欄位，不得用預設值填充，不得偽造歷史序列。

2. 不得自行啟用規則
   規則啟用狀態由規格文件決定，disabled 就是 disabled。

3. 不得越界修改
   每次任務只能修改被明確指定的檔案。
```

### 2.2 數據保護規則

```
唯讀檔案（絕對禁止寫入）：
  2317_master_v8.csv
  2317_daily_price.csv
  macro_snapshot.csv
  SKILL_v12.md
  2317_DATA_GOVERNANCE_SPEC.md

禁止使用的舊版檔案：
  fundamentals_COMPLETE.financials_rebuilt.csv
  fundamentals_COMPLETE.enriched.csv
  04A_FIELD_MAPPING_WORKING_v1.csv
  任何版本號低於 v8 的 2317_master_*.csv

永久禁用規則（9條，不得啟用）：
  STRONG_ADD / GROWTH_BUY_LINE_145 / EPS_GROWTH_QUALIFIED（舊版）
  ROE_BLOCK（舊版）/ ROE_ADD_QUALIFIED（舊版）
  PB_UNDERVALUE（舊版）/ PB_OVERHEAT / DIVIDEND_TRAP（舊版）/ SELL_ALL
```

### 2.3 UI 修改規則

```
允許：
  新增 HTML 元素（tooltip、badge、卡片、按鈕）
  新增 CSS class（不得覆蓋現有 class）
  新增 JavaScript 函數（不得修改現有函數）

禁止：
  修改現有 CSS 樣式
  刪除任何現有 HTML 元素或功能
  修改現有 JavaScript 函數邏輯
  隨意更改 UI 架構（需 Owner 另行核准）
```

### 2.4 訊號與建議規則

```
所有 Alert / 燈號 / 警示必須標示：
  actionable: false

含義：戰情室只提示，不自動執行任何交易或數據寫入。
Owner 負責所有最終決策。

建議語言規範：
  ✅ 正確：「可考慮加碼20~30%」
  ❌ 錯誤：「建議立即加碼25%」
  ✅ 正確：「停止投入新資金（BLOCK）」
  ❌ 錯誤：「賣出持股」（除非明確觸發TRIM/SELL條件）
```

---

## 第三章：任務執行規範

### 3.1 執行前必讀順序

```
每次執行任務前，必須依序閱讀：

1. AGENT.MD（本文件）← 了解 Owner 和行為規範
2. SKILL_v12.md      ← 投資邏輯規則（PART A~Z）
3. CODEX_DELIVERY_CHECKLIST.md ← 交付標準
4. 對應的執行指令（P1008_CODEX_INSTRUCTION.md 等）
5. TASK_PHASE1_UI_OPTIMIZATION.md ← 任務規格

若以上任何文件未提供，停下來詢問 Owner，不得自行推斷。
```

### 3.2 執行中的檢查點

```
每個 await / 非同步操作後：
  確認 Token 未被取消（Race Condition 防護）

每次寫入操作前：
  確認目標檔案不在唯讀清單中

每次渲染前：
  確認數據版本與當前 Generation 一致

發現規格衝突時：
  停下來，回報衝突內容，等待 Owner 指示
  不得自行決定哪個規格優先
```

### 3.3 交付規範

```
每次交付必須附上（來自 CODEX_DELIVERY_CHECKLIST.md）：
  模板A：變更說明
  模板B：AcceptanceCriteria 對照表
  模板C：交付前自查清單（逐項勾選）

交付前自查重點：
  □ 未修改任何現有 CSS class 或屬性值
  □ 未刪除任何現有 HTML 元素或功能
  □ 未自動寫入或修改任何 CSV 檔案
  □ 所有新增 Alert 已標示 actionable: false
  □ 未啟用任何永久禁用規則（9條）
  □ 未使用 ForbiddenFiles 中的任何檔案
```

---

## 第四章：戰情室設計哲學（必須理解）

### 4.1 系統定位

```
本系統是「退休存股與長期複利決策輔助系統」，不是短線交易工具。

核心目標優先順序：
  第一：確保退休生活的現金流永遠不中斷（股息安全性）
  第二：確保損失有上限（現金緩衝充足）
  第三：在合理估值時參與市場（PB訊號）

HOLD 是系統預設狀態，不是失敗訊號。
股息安全性惡化，才是退休存股的核心賣出訊號。
```

### 4.2 系統先天限制

```
本系統能處理：已知類型的極端事件（升息循環、AI泡沫修正）
本系統無法處理：歷史從未發生過的真正黑天鵝

黑天鵝期間（VIX>50 或 單日跌幅>10%）：
  暫停所有買賣建議
  只確認：現金緩衝是否充足 + 股息是否仍持續
  預設行為：不操作，等待穩定

這不是系統缺陷，而是認識論的根本限制。
Codex 不得試圖「修復」這個限制。
```



```
本系統數據來源：USER_CURATED_WEB_DATA（L3）
不是 CSV_AUTHORITY，不得升格處理。

數據品質標示：
  PRECISE：GOODINFO_INDIVIDUAL_PRECISE（2023Q4~2026Q1）
  ESTIMATED：ESTIMATED_FROM_ANNUAL_RATIO（2021~2023Q3）
  APPROX：計算近似值（ROE_TTM/ROIC等）

EffectiveDate 為估算值（非MOPS驗證），
回測結果含 Lookahead 風險，必須標示。
```

---

## 第五章：溝通規範

### 5.1 回報格式

```
發現問題時，回報格式：
  問題類型：[規格衝突 / 數據缺失 / 技術限制 / 其他]
  問題描述：[具體說明]
  影響範圍：[哪些功能受影響]
  建議選項：[A選項 / B選項]
  等待 Owner 決定後再繼續執行
```

### 5.2 不確定時的處理

```
若規格文件有歧義：
  → 列出兩種可能的解讀，詢問 Owner 確認
  → 不得自行選擇並執行

若技術上無法實現規格要求：
  → 說明技術限制，提出替代方案
  → 等待 Owner 確認替代方案後再執行

若發現現有程式碼與規格衝突：
  → 回報衝突內容，不得自行修改現有邏輯
```

### 5.3 禁止的行為

```
❌ 自行決定「這個功能不重要，跳過」
❌ 自行決定「規格說的太複雜，簡化一下」
❌ 自行決定「這個數據缺失，用預設值代替」
❌ 自行決定「這個規則可以啟用了」
❌ 在未獲授權的情況下修改任何 CSV 或規格文件
❌ 省略交付時的自查清單
❌ 在信心 INSUFFICIENT 時提供倉位建議
```

---

## 第六章：快速參考

### 6.1 當前數據庫版本

```
季度數據：2317_master_v8.csv（v8.0，50欄，21列）
每日數據：2317_daily_price.csv（1,346筆）
總經數據：macro_snapshot.csv（v2.0，18欄）
```

### 6.2 當前已核准規則（6項）

```
ROE_BLOCK / ROE_ADD_QUALIFIED（Owner核准 2026-06-03）
DIVIDEND_TRAP（Owner核准 2026-06-03）
OperatingMarginFloor 2.8%（Owner核准 2026-06-03）
EPS_GROWTH_QUALIFIED（Owner核准）
PB_UNDERVALUE（Owner核准）
STRONG_ADD前置條件（Owner核准）
```

### 6.3 當前動態門檻（2026Q1）

```
ADD線：1.162x（約148元）
BLOCK線：1.923x（約244元，NORMAL狀態）
嚴格BLOCK線：2.115x（約269元）
品質分：115/115（滿分）
RiskLevel：待更新（macro_snapshot過期）
```

### 6.4 Phase 執行狀態

```
Phase 1（P1-001~P1-009）：待執行
  → 快速通道：直接執行 P1-008（全新UI重構）
  → P1-009：主動預警引擎 + 股息現金流框架

Phase 2（P2-001~P2-005）：規劃中
  → P2-001：股息現金流儀表板（最高優先）
  → P2-005：macro_snapshot 半自動更新（次高優先）

Phase 3：待規劃
```

---

*AGENT.MD v1.0 | 2026-06-08 | 退休存股戰情室*
*本文件應與 SKILL_v12.md 同步維護，Owner 修改需同步更新*