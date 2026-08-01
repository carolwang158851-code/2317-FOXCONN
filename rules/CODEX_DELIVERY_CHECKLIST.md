# Codex 交付包說明文件
# 版本：v1.0 | 日期：2026-06-06 | 制定：Office Agent
# 適用範圍：退休存股戰情室 Phase 1~3 所有任務

---

## 文件定位

```
本文件是「退休存股戰情室」Codex 執行任務的強制性交付標準。
每次交給 Codex 任務時，必須同時附上本文件。

優先層級：
  SKILL_v12.md（規則手冊）         ← 最高優先，定義投資邏輯
  CODEX_DELIVERY_CHECKLIST.md      ← 本文件，定義交付標準
  TASK_PHASE1_UI_OPTIMIZATION.md   ← 任務規格，定義具體工作
  數據庫CSV（v8/daily/macro）      ← 數據來源，唯讀

衝突處理原則：
  若本文件與任務單有衝突 → 以本文件為準
  若本文件與SKILL_v12.md有衝突 → 以SKILL_v12.md為準
```

---

## 第1章：必讀文件清單（每次任務必附）

```yaml
MandatoryFiles:
  規則手冊:
    - SKILL_v12.md              # 投資邏輯規則（PART A~Y）
  交付標準:
    - CODEX_DELIVERY_CHECKLIST.md  # 本文件
  任務規格:
    - TASK_PHASE1_UI_OPTIMIZATION.md  # Phase 1 任務單
  數據庫（唯讀）:
    - 2317_master_v8.csv        # 季度數據（50欄，21列）
    - 2317_daily_price.csv      # 每日PB（1,346筆）
    - macro_snapshot.csv        # 總經快照（18欄）
    - macro_event_observations.csv # 事件/黑天鵝旁路觀察（Actionable=false）
    - fx_trend_observations.csv # 匯率趨勢旁路觀察（Actionable=false）
    - 2317_DATA_GOVERNANCE_SPEC.md  # 數據治理規格

ForbiddenFiles（禁止使用）:
  - fundamentals_COMPLETE.financials_rebuilt.csv
  - fundamentals_COMPLETE.enriched.csv
  - 04A_FIELD_MAPPING_WORKING_v1.csv
  - 任何版本號低於 v8 的 2317_master_*.csv
```

---

## 第2章：通用限制（所有任務強制遵守）

以下限制適用於 Phase 1~3 所有任務，無例外：

### 2.1 UI 限制

```
✅ 允許：
  - 新增 HTML 元素（tooltip、badge、卡片、按鈕）
  - 新增 CSS class（不得覆蓋現有 class）
  - 新增 JavaScript 函數（不得修改現有函數）
  - 新增獨立 Tab/分頁（P1-003 已核准）

❌ 禁止：
  - 修改現有 CSS 樣式（class 名稱或屬性值）
  - 刪除任何現有 HTML 元素或功能
  - 修改現有 JavaScript 函數邏輯
  - 隨意更改 UI 架構（需 Owner 另行核准）
```

### 2.2 數據限制

```
✅ 允許：
  - 讀取 CSV 數據用於顯示
  - 計算衍生指標用於展示

❌ 禁止：
  - 自動寫入或修改任何 CSV 檔案
  - 使用 ForbiddenFiles 中的舊版數據
  - 用預設值填充缺失欄位（缺值就是缺值）
  - 偽造或估算未經 Owner 核准的數據
```

### 2.3 規則限制

```
❌ 永久禁止啟用（9條，來自 2317_master_v8.csv header）：
  STRONG_ADD / GROWTH_BUY_LINE_145 / EPS_GROWTH_QUALIFIED（舊版）
  ROE_BLOCK（舊版）/ ROE_ADD_QUALIFIED（舊版）
  PB_UNDERVALUE（舊版）/ PB_OVERHEAT / DIVIDEND_TRAP（舊版）/ SELL_ALL

✅ 已核准啟用（Owner 核准，2026-06-03）：
  ROE_BLOCK / ROE_ADD_QUALIFIED（新版，基於ROE_TTM_Pct計算近似值）
  DIVIDEND_TRAP（新版，基於計算payoutRatio）
  OperatingMarginFloor（門檻2.8%）
  EPS_GROWTH_QUALIFIED（EPS_YoY>=15% + ROE>=10% + PB<1.5x）
  PB_UNDERVALUE（PB_daily<1.0x + ROE>=8% + 無黑天鵝）
  STRONG_ADD前置條件（PB<1.25x + ROE>=10% + EPS_YoY>=15% + ROIC>10%）
```

### 2.4 Alert 限制

```
所有 Alert / 燈號 / 警示必須標示：
  actionable: false

含義：戰情室只提示，不自動執行任何交易或數據寫入動作。
決策者（Owner）負責所有最終決策。
```

### 2.5 黑天鵝標注限制

```
黑天鵝標注流程：
  Step 1：系統輔助判定（PART W.5 三類型檢查）→ 輸出建議
  Step 2：Owner 確認建議內容
  Step 3：Owner 手動寫入 CSV（系統不得自動寫入）

禁止：系統自動將 BlackSwanFlag 寫入任何 CSV
```

### 2.6 旁路觀察 CSV 限制

```text
本次核准的例外只限 P1008 BAT / tools 流程：
  - P1008_1_UPDATE_DATA.bat 可產生 staging/*_candidate.csv 與 runtime snapshot。
  - P1008_3_OWNER_PUBLISH_CSV.bat 經 Owner gate 後才可 append data/macro_event_observations.csv 與 data/fx_trend_observations.csv。

旁路 CSV 規則：
  - 不得擴欄 macro_snapshot.csv。
  - macro_event_observations.csv 只接受 Owner 事件輸入或核准公開來源掃描到的事件；無來源證據不得臆測新聞。
  - fx_trend_observations.csv 缺 JPY_USD 或 BOJ_Rate 時必須標示觀察缺欄。
  - SourceTier 必須標明官方、公開市場、媒體、Owner 註記或未驗證；connector 狀態由來源 manifest / runtime health 記錄。
  - Actionable 永遠必須是 false。
  - BlackSwanLevel 僅可作 OBSERVE / WATCH / REVIEW_REQUIRED，不得輸出買賣。
```

### 2.7 固定新聞掃描與時間窗限制

```text
固定新聞掃描可以由 Windows Task Scheduler 呼叫 BAT，但仍屬 observation-only：
  - 排程掃描只可產生 staging/YYYY-MM-DD/macro_event_observations_candidate.csv。
  - 不得直接 append data/macro_event_observations.csv。
  - 不得直接修改 HOLD、主 IC、規則狀態或倉位。
  - 不得因單一未驗證媒體來源升級為 REVIEW_REQUIRED。
  - v2 crawler 可抓 enabled=true 且 connectorStatus=APPROVED 的公開來源；來源健康狀態必須寫入 runtime/warroom_news_scan_snapshot.json。
  - 鴻海 AI server 需求端不得只看 Apple/NVIDIA；應納入 CSP/AI demand watchlist，例如 Microsoft/Azure、AWS/Amazon、Google Cloud、Meta、Oracle、CoreWeave、OpenAI 等 Owner 核准公開來源。
  - CSP 來源只因公司名稱出現不得升級；必須同時具備 capex、AI data center、AI infrastructure、GB200/GB300、AI server、rack-scale、供應鏈中斷、關稅/制裁或鴻海直接關聯等明確觸發詞。

建議掃描時窗：
  - 08:10 開盤前：lookback 16h。
  - 12:30 盤中：lookback 6h。
  - 15:30 收盤後：lookback 8h。
  - 21:30 國際事件：lookback 12h。
  - 週末 / 週一戰報整理：lookback 7d。

事件保護：
  - OBSERVE：保留 7 天供戰報追蹤。
  - WATCH：首頁提示 3 天或直到 Owner ack。
  - REVIEW_REQUIRED：未 Owner ack 前不得自動過期，只能顯示 HOLD_UNDER_REVIEW / REVIEW_REQUIRED。
```

---

## 第3章：交付前自查清單（Codex 提交前必須逐項確認）

每次提交前，Codex 必須對照以下清單自查，並在 PR 中附上完成狀態：

### 3.1 通用限制遵守

```
□ 未修改任何現有 CSS class 或屬性值
□ 未刪除任何現有 HTML 元素或功能
□ 未修改任何現有 JavaScript 函數邏輯
□ 所有新增 Alert 已標示 actionable: false
□ 未使用 ForbiddenFiles 中的任何檔案
□ 未自動寫入或修改任何 CSV 檔案
□ 若涉及旁路 CSV，只產生 staging candidate 或經 Owner gate append，且未改 macro_snapshot.csv schema
□ 新聞/黑天鵝只作觀察或重審提示，未改 HOLD 主結論
□ 若涉及固定新聞掃描，已明確區分 6-12h 即時掃描、72h 主要判斷、7d 戰報稽核
□ 未啟用任何永久禁用規則（9條）
```

### 3.2 KPI 卡片（P1-001 適用）

```
□ 每個 KPI 旁有「公式」展開按鈕或 tooltip
□ 公式顯示格式正確（例：PB = 股價 ÷ BVPS）
□ 數據來源標示正確（2317_master_v8.csv v8.0 或對應檔案）
□ 品質徽章正確顯示（PRECISE/ESTIMATED/APPROX/USER_CURATED）
□ PB 卡片顯示：ADD線/BLOCK線/嚴格BLOCK線及對應股價
□ 訊號卡片顯示：9個Step判定結果及依據
```

### 3.3 HOLD/BLOCK/TRIM（P1-002 適用）

```
□ HOLD 分級正確顯示（SAFE/WATCH/RISK 三色）
□ HOLD 分級依據正確（PB區間 + 品質分）
□ HOLD_WATCH/RISK 時顯示追蹤清單（4項指標）
□ BLOCK 解除目標價正確計算並顯示
□ ADD 機會目標價正確計算並顯示
□ 距目標的百分比與金額差距正確顯示
□ 行動指引卡明確告知決策者下一步（不可只亮燈）
□ TRIM 三類觸發條件各自顯示觸發/未觸發 + 當前數值
```

### 3.4 總經燈號（P1-004 適用）

```
□ RiskLevel 三色正確顯示（NORMAL/CAUTION/SYSTEMIC）
□ 觸發條件列出（哪幾項指標超標）
□ 對訊號的影響正確說明（CAUTION→HOLD_WATCH等）
□ 10項核心指標數值與門檻正確顯示
□ macro_snapshot.csv 最後更新時間正確顯示
□ 超過7天未更新時顯示黃色警示
□ 7天計算基準：最後一筆數據的 Date 欄位（非檔案時間戳）
□ BLOCK線連動說明正確反映當前RiskLevel
```

### 3.5 DataBadge（P1-006 適用）

```
□ 每個 KPI 旁品質徽章顏色正確
  （藍=PRECISE / 黃=ESTIMATED / 橙=APPROX / 灰=USER_CURATED）
□ 規則啟用清單含 Owner 核准日期
□ 規則禁用清單含禁用原因（hover tooltip）
□ 缺欄位清單含影響規則與嚴重性（🔴🟡🟢）
□ 缺欄位清單含補齊行動指引
□ EffectiveDate 警示正確觸發（EstimatedEffectiveDate 標示）
```

### 3.6 報告匯出（P1-007 適用）

```
□ 每日報告包含所有必要欄位（日期/股價/PB/RiskLevel/訊號/KPI）
□ 季度報告包含所有必要欄位（含PART W/X/Y結果）
□ 每個 KPI 附公式與來源（不可只顯示數值）
□ 每個訊號附判定依據（不可只顯示燈號）
□ 報告頂部顯示數據版本與生成時間
□ 報告底部顯示免責聲明
□ @media print CSS 正確隱藏輸入控件
□ @media print CSS 正確展開所有折疊區塊
```

### 3.7 不可自動寫入（所有任務適用）

```
□ 確認程式中無任何自動寫入 CSV 的程式碼
□ 確認黑天鵝標注需 Owner 確認後才能寫入
□ 確認 macro_snapshot.csv 為唯讀（程式層保護已實作）
□ 確認 2317_master_v8.csv 為唯讀（程式層保護已實作）
□ 確認 2317_daily_price.csv 為唯讀（程式層保護已實作）
```

---

## 第4章：開發 SOP（5步驟）

### Step 1：分支策略

```
命名規則：feat/P1-{任務號}-{簡短描述}

範例：
  feat/P1-001-kpi-formula
  feat/P1-002-hold-block-evaluation
  feat/P1-003-pb-river-chart
  feat/P1-004-macro-risk-signal
  feat/P1-005-event-assessment
  feat/P1-006-databadge-complete
  feat/P1-007-printable-report

原則：
  - 每個任務一個獨立分支
  - 不得在同一分支混合多個任務
  - 分支從最新穩定版本切出
```

### Step 2：開發前確認

```
開發前必須確認：
  □ 已讀取 SKILL_v12.md 對應 PART（任務相關章節）
  □ 已讀取 TASK_PHASE1_UI_OPTIMIZATION.md 對應任務規格
  □ 已讀取本文件（CODEX_DELIVERY_CHECKLIST.md）
  □ 已確認數據庫版本（v8.0）
  □ 已確認目標檔案（index.optimized.main.html）存在且為最新版

禁止：
  - 未讀規格直接開始寫程式
  - 假設數據欄位存在（必須實際查詢CSV確認）
  - 假設現有函數行為（必須實際閱讀程式碼確認）
```

### Step 3：單元/整合測試

```
測試類型一：KPI 計算數值一致性測試
  → 見第5章測試規格

測試類型二：UI 行為測試
  → tooltip/展開按鈕正確觸發
  → 三色燈號正確顯示
  → 折疊/展開動作正確

測試類型三：唯讀保護測試
  → 見第6章唯讀保護機制
  → 嘗試寫入時應拋出錯誤

測試類型四：邊界條件測試
  → 缺值欄位：顯示「N/A」或「數據不足」，不得填預設值
  → macro_snapshot 超過7天：黃色警示正確觸發
  → RiskLevel=SYSTEMIC：BLOCK線正確調整為215元區間
```

### Step 4：Owner 驗收

```
提交 Demo 時必須包含：
  1. 模板A：變更說明（見第7章）
  2. 模板B：AcceptanceCriteria 對照表（見第7章）
  3. 模板C：交付前自查清單完成狀態（見第7章）

驗收流程：
  Codex 提交 → Owner 對照 AcceptanceCriteria → 確認OK → 進行下一任務
  Codex 提交 → Owner 發現問題 → 回饋給 Codex → 修正後重新提交

原則：
  - Owner 確認 OK 才進行下一任務
  - 不得連續生成多個任務，避免錯誤累積
  - 驗收記錄保存於任務單（更新 Status）
```

### Step 5：部署注意事項

```
上線前確認清單：
  □ 數據庫檔案為唯讀（程式層保護已實作）
  □ 不會被任何自動化流程覆寫
  □ Chart.js 已正確載入（P1-003 適用）
  □ @media print CSS 已測試（P1-007 適用）
  □ 所有 tooltip 在不同瀏覽器正確顯示
  □ 頁面載入時間可接受（新增圖表後需重新測試）

文件交付：
  □ 每個 PR 附「變更說明」（模板A）
  □ 每個 PR 附「AcceptanceCriteria 對照表」（模板B）
  □ 每個 PR 附「交付前自查清單」（模板C）
```

---

## 第5章：測試規格與驗證標準

### 5.1 KPI 計算數值一致性測試

以下測試案例基於 2317_master_v8.csv 2026Q1 數據，誤差容許值 < 0.01：

```yaml
TestCase_PB:
  輸入: 股價=165.5, BVPS=127.12
  公式: PB = 165.5 ÷ 127.12
  預期輸出: 1.302x
  誤差容許: < 0.01

TestCase_ROE_TTM:
  輸入: EPS_TTM=14.18, BVPS_avg=(127.12+118.45)/2=122.785
  公式: ROE_TTM = EPS_TTM ÷ BVPS_avg
  預期輸出: 11.55%（約）
  說明: 計算近似值，Owner已核准此數據品質

TestCase_ROIC:
  輸入: NOPAT_Annual=2216, InvestedCapital=17633
  公式: ROIC = 2216 ÷ 17633
  預期輸出: 12.57%
  誤差容許: < 0.01%

TestCase_NetDebtToEBITDA:
  輸入: NetDebt=164, EBITDA_Approx=1054
  公式: NetDebtToEBITDA = 164 ÷ 1054
  預期輸出: 0.16x
  狀態: LOW_LEVERAGE_SAFE

TestCase_OperatingMarginPct:
  輸入: OperatingIncome_Q=756, Revenue_Q=21295.9
  公式: OperatingMarginPct = 756 ÷ 21295.9 × 100
  預期輸出: 3.55%
  狀態: ABOVE_MINIMUM_FLOOR（>2.8%）

TestCase_DividendYield:
  輸入: CashDividend=7.2, 股價=165.5
  公式: DividendYield = 7.2 ÷ 165.5 × 100
  預期輸出: 4.35%
```

### 5.2 動態門檻計算測試（PART W）

```yaml
TestCase_ADD線:
  輸入: 滾動12季PB_QuarterEnd序列（2023Q2~2026Q1）
  計算: P25分位數
  預期輸出: 約1.16x（允許±0.05x，因分位數計算方式）
  對應股價: 約147元（BVPS=127.12 × 1.16）

TestCase_BLOCK線_NORMAL:
  輸入: RiskLevel=NORMAL, CSP_mult=1.10, FCF_mult=1.05
  計算: PART W.4 三取最寬鬆
  預期輸出: 約2.05x
  對應股價: 約261元

TestCase_BLOCK線_CAUTION:
  輸入: RiskLevel=CAUTION, CSP_mult=1.00
  預期輸出: 約1.78x（CSP_mult上限1.0）
  對應股價: 約226元

TestCase_BLOCK線_SYSTEMIC:
  輸入: RiskLevel=SYSTEMIC, CSP_mult=0.95
  預期輸出: 約1.69x
  對應股價: 約215元
```

### 5.3 RiskLevel 觸發測試（PART Y.3 版本D）

```yaml
TestCase_NORMAL:
  輸入: VIX=18, WTI=75, 台幣=30.5, Fed升息機率YE=30%
  預期輸出: RiskLevel=NORMAL
  對訊號影響: 無

TestCase_CAUTION_VIX:
  輸入: VIX=32（>30門檻）, 其他指標正常
  預期輸出: RiskLevel=CAUTION
  對訊號影響: holdingSignal強制降為HOLD_WATCH

TestCase_CAUTION_多指標:
  輸入: VIX=25, WTI=92（>90門檻）, Fed升息機率YE=55%（>50%門檻）
  預期輸出: RiskLevel=CAUTION（2項超標）
  對訊號影響: holdingSignal強制降為HOLD_WATCH

TestCase_SYSTEMIC:
  輸入: VIX=45（>40門檻）, WTI=105（>100門檻）
  預期輸出: RiskLevel=SYSTEMIC
  對訊號影響: holdingSignal強制降為HOLD_RISK, CSP_mult=0.95

TestCase_7天警示:
  輸入: macro_snapshot最後一筆Date=2026-05-28, 今日=2026-06-06
  計算: 今日 - 最後Date = 9天 > 7天
  預期輸出: 黃色警示顯示
  注意: 計算基準為Date欄位，非檔案時間戳
```

### 5.4 HOLD 分級測試（PART X）

```yaml
TestCase_HOLD_SAFE:
  輸入: PB=1.3x（<1.5x）, 品質分=85（>=80）, RiskLevel=NORMAL
  預期輸出: HOLD_SAFE（綠色）

TestCase_HOLD_WATCH_PB:
  輸入: PB=1.8x（1.5x~2.0x）, 品質分=85, RiskLevel=NORMAL
  預期輸出: HOLD_WATCH（黃色）
  追蹤清單: 應顯示4項指標

TestCase_HOLD_WATCH_CAUTION:
  輸入: PB=1.3x, 品質分=85, RiskLevel=CAUTION
  預期輸出: HOLD_WATCH（黃色，CAUTION強制）

TestCase_HOLD_RISK:
  輸入: PB=2.3x（>2.0x）或 RiskLevel=SYSTEMIC
  預期輸出: HOLD_RISK（紅色）
```

### 5.5 邊界條件測試

```yaml
TestCase_缺值處理:
  輸入: FCF_Annual_100M 欄位為空（2026Q1）
  預期輸出: 顯示「N/A（數據尚未公布）」
  禁止: 填入0或任何預設值

TestCase_唯讀保護:
  操作: 嘗試呼叫任何寫入CSV的函數
  預期輸出: 拋出錯誤「READONLY_VIOLATION: 不得寫入唯讀數據庫」
  禁止: 靜默失敗或繼續執行

TestCase_禁用規則:
  操作: 嘗試啟用 STRONG_ADD 規則
  預期輸出: 拋出錯誤「FORBIDDEN_RULE: STRONG_ADD 為永久禁用規則」
  禁止: 靜默忽略或繼續執行
```

---

## 第6章：唯讀保護機制

### 6.1 程式層保護（必須實作）

Codex 在 index.optimized.main.html 中必須實作以下保護機制：

```javascript
// ============================================================
// 唯讀保護機制 v1.0
// 退休存股戰情室 — 所有數據庫為唯讀，禁止自動寫入
// ============================================================

const READONLY_FILES = [
  '2317_master_v8.csv',
  '2317_daily_price.csv',
  'macro_snapshot.csv',
  '2317_DATA_GOVERNANCE_SPEC.md'
];

const FORBIDDEN_RULES = [
  'STRONG_ADD',
  'GROWTH_BUY_LINE_145',
  'PB_OVERHEAT',
  'SELL_ALL'
  // 完整清單見 2317_master_v8.csv header forbiddenRules
];

/**
 * 唯讀保護檢查
 * 在任何寫入操作前呼叫此函數
 * @param {string} targetFile - 目標檔案名稱
 * @throws {Error} 若目標為唯讀檔案
 */
function checkReadOnly(targetFile) {
  if (READONLY_FILES.some(f => targetFile.includes(f))) {
    throw new Error(
      `READONLY_VIOLATION: 不得寫入唯讀數據庫 [${targetFile}]。` +
      `數據更新需由 Owner 手動執行。`
    );
  }
}

/**
 * 禁用規則保護檢查
 * 在任何規則啟用操作前呼叫此函數
 * @param {string} ruleName - 規則名稱
 * @throws {Error} 若規則為永久禁用
 */
function checkForbiddenRule(ruleName) {
  if (FORBIDDEN_RULES.includes(ruleName)) {
    throw new Error(
      `FORBIDDEN_RULE: [${ruleName}] 為永久禁用規則，` +
      `不得在未經 Owner 核准的情況下啟用。`
    );
  }
}

/**
 * 黑天鵝標注保護
 * 黑天鵝標注需 Owner 確認後才能寫入
 * 本函數只輸出建議，不執行寫入
 * @param {Object} eventData - 事件數據
 * @returns {Object} 建議內容（供 Owner 確認）
 */
function suggestBlackSwanFlag(eventData) {
  // 只返回建議，不寫入任何 CSV
  return {
    suggestion: true,
    requiresOwnerConfirmation: true,
    actionable: false,
    message: '以下為黑天鵝標注建議，需 Owner 確認後手動寫入 CSV',
    data: eventData
  };
}
```

### 6.2 macro_snapshot 更新時間檢查

```javascript
/**
 * 檢查 macro_snapshot.csv 是否超過7天未更新
 * 計算基準：最後一筆數據的 Date 欄位（非檔案時間戳）
 * @param {Array} macroData - macro_snapshot.csv 數據陣列
 * @returns {Object} 更新狀態
 */
function checkMacroSnapshotFreshness(macroData) {
  if (!macroData || macroData.length === 0) {
    return { fresh: false, daysSinceUpdate: null, warning: '數據為空' };
  }

  // 取最後一筆數據的 Date 欄位（非檔案時間戳）
  const lastEntry = macroData[macroData.length - 1];
  const lastDate = new Date(lastEntry.Date);
  const today = new Date();
  const daysDiff = Math.floor((today - lastDate) / (1000 * 60 * 60 * 24));

  return {
    fresh: daysDiff <= 7,
    daysSinceUpdate: daysDiff,
    lastUpdateDate: lastEntry.Date,
    warning: daysDiff > 7
      ? `⚠️ macro_snapshot.csv 已 ${daysDiff} 天未更新（最後更新：${lastEntry.Date}），請 Owner 手動更新`
      : null
  };
}
```

### 6.3 缺值處理規範

```javascript
/**
 * 安全取值函數
 * 缺值顯示 N/A，禁止填入預設值
 * @param {*} value - 欄位值
 * @param {string} fieldName - 欄位名稱（用於說明）
 * @returns {string} 顯示值
 */
function safeDisplayValue(value, fieldName = '') {
  if (value === null || value === undefined || value === '' || value === 'N/A') {
    // 特殊缺值說明
    const specialCases = {
      'FCF_Annual_100M': 'N/A（2026年數據尚未公布）',
      'EPS_YoY_Pct': 'N/A（缺前期數據）'
    };
    return specialCases[fieldName] || 'N/A';
  }
  return value;
}

// 禁止的做法（不得出現在程式碼中）：
// value || 0          ← 禁止：缺值填0
// value ?? 'unknown'  ← 禁止：缺值填預設字串
// value || defaultVal ← 禁止：任何形式的預設值填充
```

---

## 第7章：PR 標準化模板

### 模板A：變更說明

```markdown
## PR 變更說明

**任務ID**: TASK-2026-P1-{號碼}
**任務名稱**: {任務名稱}
**分支名稱**: feat/P1-{號碼}-{描述}
**提交日期**: {YYYY-MM-DD}

### 變更摘要
{簡短說明本次變更的主要內容，2~3句話}

### 新增功能
- {功能一}
- {功能二}

### 修改內容
- {修改項目一}（注意：僅新增，未修改現有功能）

### 未修改項目（確認）
- ✅ 現有 CSS 樣式未修改
- ✅ 現有 HTML 元素未刪除
- ✅ 現有 JavaScript 函數未修改

### 數據來源
- 主要數據：2317_master_v8.csv（v8.0）
- 每日數據：2317_daily_price.csv
- 總經數據：macro_snapshot.csv（如適用）

### 已知限制
{說明任何已知的限制或待後續任務處理的項目}

### 測試結果
{說明已執行的測試及結果，見模板B}
```

---

### 模板B：AcceptanceCriteria 對照表

```markdown
## AcceptanceCriteria 對照表

**任務ID**: TASK-2026-P1-{號碼}
**驗收日期**: {YYYY-MM-DD}

| # | 驗收標準 | 狀態 | 說明/截圖 |
|---|---------|------|---------|
| 1 | {AcceptanceCriteria 第1條} | ✅/❌/⚠️ | {說明} |
| 2 | {AcceptanceCriteria 第2條} | ✅/❌/⚠️ | {說明} |
| 3 | {AcceptanceCriteria 第3條} | ✅/❌/⚠️ | {說明} |

**狀態說明**：
- ✅ 完全符合
- ⚠️ 部分符合（說明差異）
- ❌ 未符合（說明原因）

**整體驗收結論**：
- [ ] 全部通過 → 可進行下一任務
- [ ] 部分通過 → 需修正後重新提交
- [ ] 未通過 → 退回重做

**Owner 確認簽核**：
Owner: ___________  日期: ___________
```

---

### 模板C：交付前自查清單（Codex 提交前填寫）

```markdown
## 交付前自查清單

**任務ID**: TASK-2026-P1-{號碼}
**自查日期**: {YYYY-MM-DD}
**自查人**: Codex

### 通用限制（所有任務）
- [ ] 未修改任何現有 CSS class 或屬性值
- [ ] 未刪除任何現有 HTML 元素或功能
- [ ] 未修改任何現有 JavaScript 函數邏輯
- [ ] 所有新增 Alert 已標示 actionable: false
- [ ] 未使用 ForbiddenFiles 中的任何檔案
- [ ] 未自動寫入或修改任何 CSV 檔案
- [ ] 旁路 CSV 僅由 staging candidate / Owner publish gate 處理，Actionable=false
- [ ] 未啟用任何永久禁用規則（9條）

### 唯讀保護（所有任務）
- [ ] checkReadOnly() 函數已實作
- [ ] checkForbiddenRule() 函數已實作
- [ ] 缺值使用 safeDisplayValue()，未填預設值
- [ ] 黑天鵝標注使用 suggestBlackSwanFlag()，未自動寫入

### 旁路 CSV / Market Intelligence（如適用）
- [ ] macro_snapshot.csv 仍維持 18 欄，未擴欄
- [ ] macro_event_observations.csv 欄位完整；無 Owner 輸入且無核准來源證據時不產生事件候選
- [ ] fx_trend_observations.csv 欄位完整，缺 JPY_USD / BOJ_Rate 時有觀察缺欄提示
- [ ] 首頁只顯示 FX / 黑天鵝觀察，不改 HOLD 主 IC
- [ ] 戰報可引用 FX 趨勢圖與事件反證表，但標示 observation-only
- [ ] Windows 排程或 BAT 只產生 staging candidate，不直接 append 正式 CSV
- [ ] OBSERVE / WATCH / REVIEW_REQUIRED 的有效期與 Owner ack 狀態已標示
- [ ] 單一未驗證媒體來源未被升級為 REVIEW_REQUIRED

### 任務專屬自查（勾選適用任務）

**P1-001 KPI卡片**：
- [ ] 每個KPI旁有公式展開按鈕/tooltip
- [ ] 品質徽章顏色正確（PRECISE藍/ESTIMATED黃/APPROX橙/USER_CURATED灰）
- [ ] PB卡片顯示三條門檻線及對應股價

**P1-002 HOLD/BLOCK/TRIM**：
- [ ] HOLD分級三色正確
- [ ] 行動指引卡明確告知下一步（非只亮燈）
- [ ] TRIM三類觸發條件各自顯示數值

**P1-003 圖表**：
- [ ] PB河流圖數據來源為 2317_daily_price.csv
- [ ] 動態門檻線數值正確（ADD/BLOCK/嚴格BLOCK）
- [ ] 黑天鵝事件標注正確（3個事件）
- [ ] 圖表不影響主程式訊號計算邏輯

**P1-004 總經燈號**：
- [ ] 7天警示計算基準為Date欄位（非檔案時間戳）
- [ ] RiskLevel對BLOCK線的影響正確說明

**P1-006 DataBadge**：
- [ ] 規則啟用清單含Owner核准日期
- [ ] 缺欄位清單含嚴重性標示

**P1-007 報告匯出**：
- [ ] @media print CSS已實作
- [ ] 列印時展開所有折疊區塊

### 測試結果摘要
| 測試類型 | 執行狀態 | 通過/失敗 |
|---------|---------|---------|
| KPI計算數值一致性 | {已執行/未執行} | {通過/失敗} |
| 動態門檻計算 | {已執行/未執行} | {通過/失敗} |
| RiskLevel觸發 | {已執行/未執行} | {通過/失敗} |
| HOLD分級 | {已執行/未執行} | {通過/失敗} |
| 邊界條件（缺值/唯讀/禁用規則） | {已執行/未執行} | {通過/失敗} |

### 自查結論
- [ ] 所有項目通過 → 可提交 PR
- [ ] 發現問題（說明）：___________
```

---

## 附錄：如何確保 Codex 遵循本文件

### 強制機制（程式層）

```
1. 唯讀保護寫入程式碼（第6章）
   → 任何寫入操作前自動檢查
   → 違反時拋出錯誤，不得靜默失敗

2. 禁用規則保護寫入程式碼（第6章）
   → 任何規則啟用前自動檢查
   → 違反時拋出錯誤

3. 缺值保護函數（第6章）
   → 統一使用 safeDisplayValue()
   → 禁止任何形式的預設值填充
```

### 流程機制（人工層）

```
1. 每次交給 Codex 任務時，必須同時附上本文件
   → 不附本文件 = 任務無效

2. Codex 提交前必須完成模板C自查
   → 未完成自查 = 不得提交PR

3. Owner 驗收前必須對照模板B
   → 未對照模板B = 不得進行下一任務

4. 發現違規立即停止
   → 任何違反通用限制的行為 → 立即停止，回報Owner
```

### 文件機制（規格層）

```
1. 本文件與 SKILL_v12.md 同級，列為必讀文件
2. 任務單（TASK_PHASE1_UI_OPTIMIZATION.md）每個任務末尾引用本文件
3. 版本更新時同步更新任務單中的引用版本號
4. 本文件變更需 Owner 核准（與 SKILL_v12.md 同等級別）
```

---

*文件版本：v1.0 | 2026-06-06 | 退休存股戰情室*
*下次審查：Phase 1 完成後（預計 Phase 2 開始前）*
## P1008 Launcher App Acceptance

- [ ] `P1008_APP.bat` is visible in the package root and opens `launcher.html`.
- [ ] `P1008_2_OPEN_WARROOM.bat --no-open` starts an app server that answers `GET /api/p1008/status`.
- [ ] `launcher.html` shows update-data, news-scan, report, review-package, Owner Formal Publish Gate, and guarded New UI entry controls.
- [ ] The New UI does not expose Launcher data update, pipeline log, or formal publish controls; it links back to Launcher for those workflows.
- [ ] `POST /api/p1008/run/default` runs `preflight -> update-data -> news-scan -> report -> refresh`.
- [ ] A second job submitted while one job is `RUNNING` returns a lock/409 response and does not start another pipeline.
- [ ] The app writes `runtime/p1008_app_state.json` with `jobId/status/startedAt/finishedAt/steps/formalCsvModified/errors/warnings/logPath`.
- [ ] Formal CSV SHA-256 hashes are unchanged after the Launcher default data pipeline.
- [ ] `POST /api/p1008/publish/formal` is available only in the isolated Owner gate, requires `OWNER_APPROVE_PUBLISH_YYYY-MM-DD`, and reuses `owner_publish_csv_v2.py`.
- [ ] After Owner formal publish succeeds, `warroom_news_scan_snapshot.json` and `warroom_event_review_state.json` clear `holdUnderReview`, `ownerReviewRequired`, and `ownerAckRequired`, set `formalSynced=true`, and Launcher gate changes to `READY_TO_ENTER_NEW_UI` without modifying HOLD main IC.
- [ ] Weekend / exchange-closed dates carry forward the latest formal trading-day Close/PB for Launcher/New UI display with `MARKET_CLOSED_CARRY_FORWARD`, but do not append a weekend `daily_price` formal row.
- [ ] Macro connector/source failures may carry forward the latest formal CSV value for runtime observation with `CONNECTOR_SOURCE_UNAVAILABLE_CARRY_FORWARD`, but still block formal publish until a traceable current source is available.
- [ ] Data update engine tries Python HTTPS first and fixed Windows `Invoke-WebRequest` fallback second for approved public data URLs; fallback does not bypass firewall policy and does not weaken formal publish requirements.
- [ ] Launcher displays server network context; if the App server is started from Codex network sandbox, connector health is not accepted as Owner network validation.
- [ ] Launcher and New UI distinguish formal publish `Readiness >= 95%` from six-IC decision/observation scores; runtime carry-forward values must not satisfy formal CSV publish.
- [ ] Owner publish review blocks macro candidates when required current sources for VIX, WTI, TWD/USD, US10Y, or DXY are unavailable, even if runtime carries forward latest formal CSV values.
- [ ] `DRY_RUN.json` and runtime snapshot include `macroSourceHealth`, `macroSourceSummary`, and `marketProxyManifest`; Launcher renders the macro source health table in decision language.
- [ ] Fed_Rate may be marked as a slow-moving policy-rate carry-forward only when sourced from existing formal CSV and must still be periodically rechecked; it must not hide missing VIX/WTI/TWD/USD/US10Y/DXY sources.
- [ ] Alpaca is allowed as a formal market data source for the exact instrument it quotes; ETF proxy data such as VIXY, USO, UUP, IEF/TLT may be published only as proxy indicators or sidecar fields, not as direct replacements for VIX, WTI, DXY, or US10Y original macro fields.
- [ ] CME FedWatch remains `CONNECTOR_PENDING`; FRED Fed rates may update Fed_Rate but must not be used as a substitute for market-implied FedWatch probability.
- [ ] Launcher default data update never calls formal publish, never accepts arbitrary shell commands, never changes HOLD, and never enables KEEP_DISABLED.
- [ ] News scan uses network only when a manifest source has `enabled=true`, `requiresNetwork=true`, and `connectorStatus=APPROVED`; otherwise it runs no-network and records a warning.
- [ ] Launcher shows news crawler v2 `networkSummary`, per-source `sourceHealth`, discovered/accepted counts, and connector error type when available.
- [ ] Launcher shows crawler success rate in decision language, e.g. `13/16` or `0/16`; `0/16` is explained as Python connector/source failure for the current App server session, not proof that news does not exist.
- [ ] Launcher crawler success rate excludes local `OWNER_NOTE` / `Owner manual event input`; only `requiresNetwork=true` sources are counted in the denominator.
- [ ] If crawler source success rate is below 70%, the news scan is not treated as complete; if it is 0%, Owner must check proxy/firewall, server launch context, or browser-mode dependencies before relying on it.
- [ ] `P1008_APP.bat` opens Launcher through an Edge/Chrome app-style fullscreen window when available, appends `fs=1`, and the opener rejects stale App server versions or Codex network-sandbox servers before reuse.
- [ ] Launcher, New UI, reports, report viewer, and SOP preserve `p1008_immersive_mode` / `fs=1` across internal navigation; generated reports must not contain `requestFullscreen()`.
- [ ] `P1008_2_OPEN_WARROOM.bat` / `p1008_open_warroom.py` supports `--fresh`; without `--fresh`, it may reuse an existing healthy server but should not be the primary decision-maker entry.
- [ ] Yahoo Finance is documented as macro/market fallback only, not as a formal news crawler source.
- [ ] P/B multiple and BVPS are labeled separately; a value such as `1.975` is P/B multiple, while `127.xx` is BVPS.
- [ ] `docs/README_START_HERE.md`, `docs/APP_WORKFLOW.md`, `docs/GIT_VERSIONING.md`, and `docs/FOLDER_LAYOUT.md` are present and linked from the root README/SOP.
- [ ] SOP and `docs/GIT_VERSIONING.md` state that the baseline commit is performed manually inside `CODEX_P1008_PACKAGE` only after Owner acceptance, and that Git commit is not Owner publish.

## P1008 Scheduled News Scan v2 Acceptance

- [ ] `P1008_4_NEWS_SCAN.bat --dry-run --no-network` creates `staging/YYYY-MM-DD/NEWS_SCAN.json`, `NEWS_SCAN.md`, and `runtime/warroom_news_scan_snapshot.json`.
- [ ] `P1008_4_NEWS_SCAN.bat --dry-run --allow-network` fetches only manifest sources with `enabled=true`, `requiresNetwork=true`, and `connectorStatus=APPROVED`.
- [ ] Runtime snapshot records `toolVersion=warroom_news_scanner_v2`, `networkSummary`, `sourceHealth`, and optional dependency status for `feedparser`, `trafilatura`, and `playwright`.
- [ ] Source manifest uses durable homepage/category/RSS/sitemap paths as primary discovery routes; fragile site-search URLs are auxiliary only.
- [ ] `deprecatedUrlPatterns` blocks known stale paths such as Cnyes `search/all?keyword=...`; URL build tests confirm no stale search URL is fetched.
- [ ] Hon Hai official source points to the current `zh-tw` latest-news / IR paths, not the old blank English press release path.
- [ ] Cnyes source points to current category pages and `search?q=...`, not the old `search/all?keyword=...` path.
- [ ] No-event scans do not fabricate news and do not add an empty candidate to Owner publish pending files.
- [ ] Event candidates keep the existing `macro_event_observations.csv` schema and every row has `Actionable=false`.
- [ ] Source tiers are limited to `OFFICIAL / PUBLIC_MARKET / MEDIA / OWNER_NOTE / UNVERIFIED`.
- [ ] A single `MEDIA` source cannot exceed `WATCH`; `UNVERIFIED` cannot exceed `OBSERVE`.
- [ ] `REVIEW_REQUIRED` requires official confirmation or multi-source corroboration plus direct Hon Hai relevance, CSP capex / AI data center demand, GB200/GB300/AI server linkage, supply-chain disruption, macro/FX/rate stress, tariff/export-control/sanction, or other explicit market-impact trigger.
- [ ] AI server revenue news coverage includes CSP/AI demand watchlist sources, not only Apple/NVIDIA, and generic navigation/search pages are filtered out of event candidates.
- [ ] RSS/Atom, sitemap, site-search HTML, basic HTML extraction, and browser-mode fallback failures degrade gracefully without crashing the pipeline.
- [ ] UI reads `runtime/warroom_news_scan_snapshot.json` and may display `HOLD_UNDER_REVIEW`, but HOLD main IC, formal CSV, and KEEP_DISABLED rules remain unchanged.
- [ ] `P1008_4_REGISTER_NEWS_SCHEDULE.bat` previews by default; Windows Task Scheduler is changed only with `--register` after Owner approval.

## P1008 三方案閉環驗收

- [ ] `P1008_5_GENERATE_REPORTS.bat --date YYYY-MM-DD --period daily` 可產生 `reports/generated/P1008_DAILY_REPORT_YYYYMMDD.md`、`.html`、`reports/P1008_REPORT_MANIFEST.json` 與 `runtime/warroom_report_manifest.json`。
- [ ] 戰報產生流程會讀取正式 CSV、FX 旁路 CSV、事件旁路 CSV、NEWS_SCAN 與 Owner publish review 狀態，但不修改任何正式 CSV。
- [ ] `runtime/warroom_event_review_state.json` 會在新聞掃描或戰報產生後存在，並以 `actionable=false` 記錄待 Owner ack 的 `WATCH / REVIEW_REQUIRED` 事件。
- [ ] 首頁是唯一啟動窗口：6 大系統卡片只保留摘要；只有 HOLD 主 IC、Owner 待決、REVIEW_REQUIRED 控制項可捲動到舊 UI 明細錨點。
- [ ] 舊 UI 明細錨點存在：`p2-concept-board`、`warroom-market-intelligence`、`warroom-sidecar-observations`、`owner-publish-panel`、`data-governance-panel`。
- [ ] `reports.html` 與 `report_viewer.html` 會在 manifest 存在時讀取 `reports/P1008_REPORT_MANIFEST.json`，不存在時 fallback 到原靜態研報索引。
- [ ] 最新戰報卡會透過 `report_viewer.html?id=...` 開啟產生的戰報，且所有戰報產物維持 `actionable:false`。
- [ ] 任一實作步驟不得擴欄 `macro_snapshot.csv`、不得啟用 `KEEP_DISABLED`、不得自動改 HOLD、不得繞過 Owner publish gate。
