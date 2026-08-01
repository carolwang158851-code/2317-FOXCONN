# 2317 戰情室數據治理規格
# Data Governance Specification v1.0
# 適用於：index.optimized.main.html + Codex 執行層

---

## P1-1: EffectiveDate 驗證與 Lookahead Guard

### 規則定義

```javascript
// 每筆資料必須有 EstimatedEffectiveDate
// Backtest 或規則判斷只能使用 backtestDate >= EstimatedEffectiveDate 的資料

function getLookaheadSafeData(allData, backtestDate) {
  return allData.filter(row => {
    if (!row.EstimatedEffectiveDate) {
      console.warn(`LOOKAHEAD_RISK: ${row.Quarter} missing EffectiveDate`);
      return false; // 缺 EffectiveDate 的資料不得使用
    }
    return row.EstimatedEffectiveDate <= backtestDate;
  });
}

// 驗證規則
const EFFECTIVE_DATE_RULES = {
  REQUIRED: true,           // 必填
  FORMAT: "YYYY-MM-DD",     // 格式
  SOURCE: "ESTIMATED",      // 目前為估算值（非 MOPS 驗證）
  RISK_LEVEL: "LOW",        // 估算風險低（財報公布時間規律）
  MOPS_VERIFIED: false,     // 尚未從公開資訊觀測站驗證
};

// 目前 EstimatedEffectiveDate 對照表（估算基準：財報公布後次一交易日）
const EFFECTIVE_DATE_MAP = {
  "2021Q1": "2021-05-14", "2021Q2": "2021-08-13",
  "2021Q3": "2021-11-12", "2021Q4": "2022-03-16",
  "2022Q1": "2022-05-13", "2022Q2": "2022-08-12",
  "2022Q3": "2022-11-11", "2022Q4": "2023-03-15",
  "2023Q1": "2023-05-12", "2023Q2": "2023-08-11",
  "2023Q3": "2023-11-10", "2023Q4": "2024-03-14",
  "2024Q1": "2024-05-10", "2024Q2": "2024-08-09",
  "2024Q3": "2024-11-08", "2024Q4": "2025-03-16",
  "2025Q1": "2025-05-09", "2025Q2": "2025-08-08",
  "2025Q3": "2025-11-07", "2025Q4": "2026-03-16",
  "2026Q1": "2026-05-08",
};
```

### UI 顯示規範

```
每筆資料顯示：
  EstimatedEffectiveDate: 2021-05-14
  EffectiveDateSource: ESTIMATED (not MOPS verified)
  LookaheadRisk: LOW

Backtest 執行前必須顯示警示：
  "本回測使用估算 EffectiveDate，非 MOPS 驗證日期。
   結果僅供參考，不得作為正式交易依據。"
```

---

## P1-2: DataSource 與 SupportLevel 明確化（DataBadge）

### 資料來源等級定義

```javascript
const DATA_SOURCE_REGISTRY = {
  CSV_AUTHORITY: {
    label: "Official CSV Authority",
    trustLevel: 5,
    canTriggerOfficialRules: true,
    badgeColor: "#1a7f37",  // 綠色
    description: "正式歷史 CSV，可審計，可重建"
  },
  USER_CURATED_WEB_DATA: {
    label: "User-Verified Web Data",
    trustLevel: 4,
    canTriggerOfficialRules: "conditional",
    badgeColor: "#0969da",  // 藍色
    description: "使用者查核網路資料，可信但需標示版本與欄位"
  },
  EMBEDDED_CSV: {
    label: "Embedded Backup Data",
    trustLevel: 3,
    canTriggerOfficialRules: "limited",
    badgeColor: "#9a6700",  // 橙色
  },
  API_REALTIME: {
    label: "Real-time API",
    trustLevel: 3,
    canTriggerOfficialRules: "limited",
    badgeColor: "#9a6700",
  },
  MANUAL_OVERRIDE: {
    label: "Manual Override",
    trustLevel: 2,
    canTriggerOfficialRules: false,
    badgeColor: "#cf222e",  // 紅色
    description: "手動推演，必須標示，不得偽裝正式"
  },
  SANDBOX_MODE: {
    label: "Sandbox Display",
    trustLevel: 1,
    canTriggerOfficialRules: false,
    badgeColor: "#6e7781",  // 灰色
  },
  DATA_MISSING: {
    label: "Data Missing",
    trustLevel: 0,
    canTriggerOfficialRules: false,
    badgeColor: "#cf222e",
  }
};

// 目前 2317 數據庫狀態
const CURRENT_DATA_SOURCE = "USER_CURATED_WEB_DATA";
const CURRENT_SUPPORT_LEVEL = "L3";

// 禁止升格規則
function validateDataSource(source) {
  if (source === "USER_CURATED_WEB_DATA") {
    // 不得自動升格為 CSV_AUTHORITY
    return source;
  }
  return source;
}
```

### DataBadge UI 規範

```html
<!-- DataBadge 必須顯示在所有輸出的頂部 -->
<div class="data-badge">
  <span class="badge-source user-curated">USER_CURATED_WEB_DATA</span>
  <span class="badge-level">L3</span>
  <span class="badge-warning">⚠️ 非 CSV_AUTHORITY，規則條件性啟用</span>
</div>

<!-- 缺欄位必須紅色標示 -->
<div class="missing-fields">
  ❌ 缺少：PB_daily / ROE_quarterly / payoutRatio_direct / effectiveDate_verified
</div>
```

---

## P1-3: Disabled Rules 常數化與不可變保護

### 永久鎖定的規則（不得在程式碼中修改）

```javascript
// 這些常數必須在程式啟動時載入，不得在執行期間修改
Object.freeze({
  PERMANENTLY_DISABLED_RULES: [
    "STRONG_ADD",
    "GROWTH_BUY_LINE_145",
    "EPS_GROWTH_QUALIFIED",
    "ROE_BLOCK",           // 缺季度 ROE 欄位
    "ROE_ADD_QUALIFIED",   // 缺季度 ROE 欄位
    "PB_UNDERVALUE",       // 缺每日收盤價
    "PB_OVERHEAT",         // 缺每日收盤價
    "DIVIDEND_TRAP",       // payoutRatio 為計算值非直接財報
    "SELL_ALL",            // 退休存股不由單一事件觸發
  ],

  // 條件性可用（需 Owner 明確核准）
  CONDITIONAL_RULES: [
    "TAX_DRAG_LIGHT",
    "TAX_DRAG_STRUCTURAL",
    "LIQUIDITY_WARNING",
    "SEASONAL_CAUTION",
    "SEASONAL_FAVORABLE",
    "DIVIDEND_GROWTH",
  ],

  // 目前核准狀態
  RULE_APPROVAL_STATUS: {
    "STRONG_ADD": "KEEP_DISABLED",
    "GROWTH_BUY_LINE_145": "KEEP_DISABLED",
    "EPS_GROWTH_QUALIFIED": "KEEP_DISABLED",
    "TAX_DRAG_LIGHT": "OBSERVATION_ONLY",
    "TAX_DRAG_STRUCTURAL": "OBSERVATION_ONLY",
    "LIQUIDITY_WARNING": "OBSERVATION_ONLY",
  }
});

// 保護函式：任何嘗試啟用 disabled 規則的操作都會被攔截
function enableRule(ruleName) {
  if (PERMANENTLY_DISABLED_RULES.includes(ruleName)) {
    throw new Error(`STOP-2: Rule ${ruleName} is KEEP_DISABLED. Requires Owner approval.`);
  }
  // 繼續正常啟用流程
}
```

---

## P2-1: 欄位契約與 schemaEnforcer

### 欄位定義表

```javascript
const FIELD_CONTRACT = {
  // 必填欄位（缺少則停用相關規則）
  REQUIRED: {
    Quarter:                  { type: "string",  format: "YYYYQN",  example: "2021Q1" },
    QuarterEndDate:           { type: "date",    format: "YYYY-MM-DD" },
    EstimatedEffectiveDate:   { type: "date",    format: "YYYY-MM-DD" },
    EPS_Q:                    { type: "number",  unit: "TWD/share" },
    BVPS:                     { type: "number",  unit: "TWD/share" },
    TaxRev_Pct:               { type: "number",  unit: "%" },
    DataSource:               { type: "string",  enum: Object.keys(DATA_SOURCE_REGISTRY) },
    DataSupportLevel:         { type: "string",  enum: ["L0","L1","L2","L3","L4"] },
  },

  // 選填欄位（缺少時停用對應規則，但不阻止系統運行）
  OPTIONAL: {
    ROE_TTM_Pct:              { type: "number",  unit: "%",  missingAction: "DISABLE_ROE_RULES" },
    PB_Adjusted:              { type: "number",  unit: "x",  missingAction: "DISABLE_PB_RULES" },
    payoutRatio_Pct:          { type: "number",  unit: "%",  missingAction: "DISABLE_DIVIDEND_TRAP" },
    FCF_Annual_100M:          { type: "number",  unit: "100M TWD", missingAction: "DISABLE_FCF_RULES" },
    ROIC_Approx_Pct:          { type: "number",  unit: "%",  missingAction: "OBSERVATION_ONLY" },
  }
};

// schemaEnforcer：驗證資料並自動停用缺欄位的規則
function schemaEnforcer(row) {
  const missingFields = [];
  const disabledRules = [];
  const reasonCodes = [];

  // 檢查必填欄位
  for (const [field, spec] of Object.entries(FIELD_CONTRACT.REQUIRED)) {
    if (row[field] === undefined || row[field] === null || row[field] === "") {
      missingFields.push(field);
      reasonCodes.push(`${field}_MISSING`);
    }
  }

  // 檢查選填欄位並停用對應規則
  const ruleDisableMap = {
    "ROE_TTM_Pct":    ["ROE_BLOCK", "ROE_ADD_QUALIFIED", "ROE_STRONG_QUALIFIED"],
    "PB_Adjusted":    ["PB_UNDERVALUE", "PB_OVERHEAT", "PB_PREMIUM_HOLD"],
    "payoutRatio_Pct":["DIVIDEND_TRAP"],
    "FCF_Annual_100M":["FCF_SAFETY_CHECK"],
  };

  for (const [field, rules] of Object.entries(ruleDisableMap)) {
    if (!row[field] || row[field] === "") {
      disabledRules.push(...rules);
      reasonCodes.push(`${field}_MISSING`);
    }
  }

  return {
    valid: missingFields.length === 0,
    missingFields,
    disabledRules: [...new Set(disabledRules)],
    reasonCodes,
  };
}
```

---

## P2-2: 觀測型 Alerts Engine（只提示不動作）

### Alert 規則定義

```javascript
// 所有 Alert 必須標示 actionable: false
const ALERT_RULES = [
  {
    id: "TAX_DRAG_CANDIDATE",
    condition: (row) => row.TaxZ >= 1 && row.TaxZ < 2,
    severity: "WARNING",
    message: (row) => `Tax/Rev ${row.TaxRev_Pct}%，Z=${row.TaxZ}，稅務壓力上升，建議觀察`,
    actionable: false,
    affectedRules: [],  // 不停用任何規則，只提示
  },
  {
    id: "TAX_DRAG_STRUCTURAL_VERIFIED",
    condition: (row) => row.TaxZ_Status === "TAX_DRAG_STRUCTURAL_VERIFIED",
    severity: "INFO",
    message: () => "稅務異常已確認為 Pillar Two 法規性事件，非本業惡化",
    actionable: false,
    affectedRules: [],
  },
  {
    id: "LIQUIDITY_WATCH",
    condition: (row) => row.ForeignHoldingPct && row.ForeignHoldingPct < 36,
    severity: "WARNING",
    message: (row) => `外資持股 ${row.ForeignHoldingPct}%，低於 36% 警戒線`,
    actionable: false,
    affectedRules: [],
  },
  {
    id: "SEASONAL_CAUTION",
    condition: (row) => {
      const month = new Date(row.QuarterEndDate).getMonth() + 1;
      return [1, 8, 9, 11].includes(month);
    },
    severity: "INFO",
    message: () => "歷史低勝率月份，建議謹慎加碼",
    actionable: false,
    affectedRules: [],
  },
  {
    id: "SEASONAL_FAVORABLE",
    condition: (row) => {
      const month = new Date(row.QuarterEndDate).getMonth() + 1;
      return [3, 5, 6, 10].includes(month);
    },
    severity: "INFO",
    message: () => "歷史高勝率月份，順風順水",
    actionable: false,
    affectedRules: [],
  },
  {
    id: "DIVIDEND_GROWTH",
    condition: (row) => row.DividendYield_Pct && row.DividendYield_Pct > 0,
    severity: "INFO",
    message: (row) => `殖利率 ${row.DividendYield_Pct}%，退休現金流持續`,
    actionable: false,
    affectedRules: [],
  },
  {
    id: "ROE_IMPROVING",
    condition: (row) => row.ROE_TTM_Pct && row.ROE_TTM_Pct >= 11.5,
    severity: "INFO",
    message: (row) => `ROE_TTM ${row.ROE_TTM_Pct}%，接近 STRONG_ADD 門檻（需 Owner 核准）`,
    actionable: false,
    affectedRules: [],
  },
];

// Alert Engine 執行函式
function runAlertsEngine(row) {
  const alerts = [];
  for (const rule of ALERT_RULES) {
    try {
      if (rule.condition(row)) {
        alerts.push({
          code: rule.id,
          severity: rule.severity,
          message: rule.message(row),
          actionable: false,  // 永遠為 false
          dataSource: row.DataSource,
          quarter: row.Quarter,
        });
      }
    } catch (e) {
      // 欄位缺失時靜默跳過，不拋出錯誤
    }
  }
  return alerts;
}
```

---

## P3-1: 手動覆寫流程與 Audit Log

### 手動覆寫規範

```javascript
// 手動覆寫必須標示來源並記錄
function applyManualOverride(fieldName, originalValue, manualValue, reason) {
  // 驗證：不得覆寫 CSV_AUTHORITY 資料
  if (currentDataSource === "CSV_AUTHORITY") {
    throw new Error("STOP: Cannot override CSV_AUTHORITY data with manual values");
  }

  // 記錄覆寫
  const overrideRecord = {
    timestamp: new Date().toISOString(),
    field: fieldName,
    originalValue: originalValue,
    manualValue: manualValue,
    reason: reason,
    source: "MANUAL_OVERRIDE",
    ownerConfirmed: false,  // 需要 Owner 確認
  };

  // 寫入 Audit Log
  appendAuditLog(overrideRecord);

  return {
    value: manualValue,
    dataBadge: "MANUAL_OVERRIDE",
    reasonCode: "MANUAL_OVERRIDE",
    auditId: overrideRecord.timestamp,
  };
}

// Audit Log 格式（存入 audit_log.json，不修改任何 CSV）
const AUDIT_LOG_SCHEMA = {
  timestamp:           "ISO 8601 datetime",
  action:              "MANUAL_OVERRIDE | DRY_RUN_CONFIRMED | RULE_ENABLED | BACKTEST_RUN",
  quarter:             "YYYYQN or null",
  field:               "fieldName or null",
  originalValue:       "any",
  newValue:            "any",
  reason:              "string",
  ownerConfirmed:      "boolean",
  dataSource:          "DataSource enum",
  disabledRules:       "string[]",
  reasonCodes:         "string[]",
};
```

---

## P3-2: 前端 Dry-Run 流程與 Owner 確認

### Dry-Run 強制流程

```javascript
// 任何會影響規則狀態或資料的操作，必須先執行 Dry-Run
async function executeDryRun(task) {
  const dryRunReport = {
    taskId: task.TaskId,
    timestamp: new Date().toISOString(),
    plannedChanges: [],
    forbiddenFilesCheck: [],
    ruleEnablementCheck: [],
    missingFieldsCheck: [],
    risks: [],
  };

  // 1. 檢查 ForbiddenFiles
  const FORBIDDEN_FILES = [
    "fundamentals_COMPLETE.financials_rebuilt.csv",
    "fundamentals_COMPLETE.enriched.csv",
    "04A_FIELD_MAPPING_WORKING_v1.csv",
  ];
  for (const file of task.TargetFiles || []) {
    if (FORBIDDEN_FILES.includes(file)) {
      dryRunReport.forbiddenFilesCheck.push({
        file,
        status: "BLOCKED",
        code: "STOP-1",
      });
    }
  }

  // 2. 檢查規則啟用
  if (task.RuleEnablementChange === true) {
    for (const rule of task.RulesToEnable || []) {
      if (PERMANENTLY_DISABLED_RULES.includes(rule)) {
        dryRunReport.ruleEnablementCheck.push({
          rule,
          status: "BLOCKED",
          code: "STOP-2",
          message: `${rule} is KEEP_DISABLED. Requires separate Owner approval.`,
        });
      }
    }
  }

  // 3. 輸出 Dry-Run 報告（等待 Owner 確認）
  displayDryRunReport(dryRunReport);

  // 4. 等待 Owner 確認（強制等待點）
  const confirmed = await waitForOwnerConfirmation(dryRunReport);
  if (!confirmed) {
    throw new Error("DRY_RUN_NOT_CONFIRMED: Execution blocked");
  }

  // 5. 記錄確認到 Audit Log
  appendAuditLog({
    action: "DRY_RUN_CONFIRMED",
    taskId: task.TaskId,
    ownerConfirmed: true,
    timestamp: new Date().toISOString(),
  });

  return dryRunReport;
}
```

---

## 欄位完整性現況（2317 數據庫 v4）

| 欄位 | 狀態 | 支援規則 | 備註 |
|---|---|---|---|
| Quarter | ✅ 完整 | 所有規則 | |
| EstimatedEffectiveDate | ✅ 完整 | Backtest | 估算值，非 MOPS 驗證 |
| EPS_Q / EPS_TTM | ✅ 完整 | EPS 觀測 | |
| EPS_YoY_Pct | ✅ 完整（2021起） | EPS 成長觀測 | 2021Q1 低基期標示 |
| BVPS | ✅ 完整 | PB 計算基礎 | |
| ROE_TTM_Pct | ✅ 完整（2021起） | ROE 觀測 | 需 2020 BVPS 支撐 |
| TaxZ / TaxZ_Status | ✅ 完整 | Tax 觀測 | 2025Q4 已驗證 |
| PB_Adjusted | ✅ 完整 | PB 觀測 | 季末快照，非每日 |
| DividendYield_Pct | ✅ 完整 | 股息觀測 | |
| ROIC_Approx_Pct | ✅ 完整 | 效率觀測 | 簡化計算 |
| FCF_Annual_100M | ✅ 年度有 | FCF 觀測 | 缺季度序列 |
| payoutRatio_Pct | ⚠️ 計算值 | 配息陷阱 | 非直接財報欄位 |
| effectiveDate_verified | ❌ 缺 | Backtest 精確度 | 需 MOPS 驗證 |
| ROE_quarterly | ❌ 缺 | ROE 精確規則 | 目前用年度前填 |
| PB_daily | ❌ 缺 | PB 精確規則 | 目前用季末快照 |

---

## 風險補充與緩解措施

### RISK-1：資料漂移風險（Data Drift）

**風險描述：**
API 自動抓取股價若格式變動，會導致 PB_daily 計算錯誤，
進而影響 PB_Zone 判斷與相關規則觸發。

**緩解措施：**

```javascript
// ETL 健康檢查（每日執行）
function dailyETLHealthCheck(newData, expectedSchema) {
  const issues = [];

  // 1. Schema 驗證
  for (const [field, spec] of Object.entries(expectedSchema)) {
    if (newData[field] === undefined) {
      issues.push({ type: "SCHEMA_MISMATCH", field, severity: "ERROR" });
    }
    if (typeof newData[field] !== spec.type) {
      issues.push({ type: "TYPE_MISMATCH", field, expected: spec.type, actual: typeof newData[field] });
    }
  }

  // 2. 若有 schema mismatch，立即發出 DATA_INVALID alert 並暫停依賴規則
  if (issues.length > 0) {
    triggerAlert({
      code: "DATA_INVALID",
      severity: "ERROR",
      message: `ETL schema mismatch detected: ${issues.map(i => i.field).join(", ")}`,
      actionable: false,
      affectedRules: getAffectedRules(issues.map(i => i.field)),
    });

    // 暫停依賴該欄位的規則
    for (const issue of issues) {
      suspendRulesForField(issue.field);
    }

    return { healthy: false, issues };
  }

  return { healthy: true, issues: [] };
}

// 欄位與規則的依賴關係
function getAffectedRules(missingFields) {
  const ruleMap = {
    "QuarterEndClose": ["PB_UNDERVALUE", "PB_OVERHEAT", "PB_PREMIUM_HOLD"],
    "BVPS":            ["PB_UNDERVALUE", "PB_OVERHEAT"],
    "ROE_TTM_Pct":     ["ROE_BLOCK", "ROE_ADD_QUALIFIED", "ROE_STRONG_QUALIFIED"],
    "TaxRev_Pct":      ["TAX_DRAG_LIGHT", "TAX_DRAG_STRUCTURAL"],
  };
  const affected = new Set();
  for (const field of missingFields) {
    (ruleMap[field] || []).forEach(r => affected.add(r));
  }
  return [...affected];
}
```

---

### RISK-2：權限濫用風險（Authorization Abuse）

**風險描述：**
Owner 核准流程若被濫用（如單人自行核准），
會導致 STRONG_ADD 等規則被錯誤啟用，影響退休存股決策。

**緩解措施：**

```javascript
// 雙重確認機制（重要規則啟用需額外確認）
const HIGH_RISK_RULES = ["STRONG_ADD", "GROWTH_BUY_LINE_145", "EPS_GROWTH_QUALIFIED"];

async function approveRuleEnablement(ruleName, requesterId) {
  if (HIGH_RISK_RULES.includes(ruleName)) {
    // 高風險規則：需要在 UI 顯示明確警示並要求二次確認
    const confirmed = await showHighRiskConfirmDialog({
      rule: ruleName,
      warning: `⚠️ ${ruleName} 為高風險規則，啟用後將影響加減碼訊號。請確認已完成完整數據驗證。`,
      requireTyping: `CONFIRM_ENABLE_${ruleName}`,  // 需手動輸入確認文字
    });

    if (!confirmed) {
      throw new Error(`STOP-2: High-risk rule ${ruleName} approval cancelled`);
    }
  }

  // 強制記錄核准資訊到 Audit Log
  appendAuditLog({
    action: "RULE_ENABLED",
    rule: ruleName,
    requesterId: requesterId,
    approvedAt: new Date().toISOString(),
    approvalReason: await promptForReason(),  // 強制填寫核准理由
    ownerConfirmed: true,
  });
}

// UI 顯示核准者與時間（所有規則啟用記錄必須可查）
function displayRuleApprovalHistory(ruleName) {
  const history = getAuditLogByRule(ruleName);
  return history.map(entry => ({
    rule: entry.rule,
    approvedAt: entry.approvedAt,
    approvedBy: entry.requesterId,
    reason: entry.approvalReason,
  }));
}
```

---

### RISK-3：回測偏差風險（Backtest Look-ahead Bias）

**風險描述：**
EstimatedEffectiveDate 為估算值，若估算偏早，
回測仍可能使用當時尚未公布的財報數據，造成 look-ahead bias。

**緩解措施：**

```javascript
// 回測 UI 必須顯示明顯紅色警示
function renderBacktestWarning(backtestConfig) {
  const hasUnverifiedDates = backtestConfig.data.some(
    row => row.LookaheadRisk !== "VERIFIED"
  );

  if (hasUnverifiedDates) {
    return {
      warningLevel: "RED",
      message: "⚠️ 本回測使用估算 EffectiveDate（非 MOPS 驗證）。結果僅供參考，不得作為正式交易依據。",
      affectedQuarters: backtestConfig.data
        .filter(row => row.LookaheadRisk !== "VERIFIED")
        .map(row => row.Quarter),
    };
  }
  return null;
}

// 回測報告必須標註 lookaheadRisk 與受影響日期範圍
function generateBacktestReport(results, config) {
  return {
    ...results,
    dataQualityWarnings: {
      lookaheadRisk: "LOW_BUT_ESTIMATED",
      effectiveDateSource: "ESTIMATED_NOT_MOPS_VERIFIED",
      affectedDateRange: {
        start: config.data[0].EstimatedEffectiveDate,
        end: config.data[config.data.length - 1].EstimatedEffectiveDate,
      },
      disclaimer: "EstimatedEffectiveDate 基於財報公布慣例估算，" +
                  "實際公布日期可能有 1-3 個交易日誤差。" +
                  "建議從 MOPS 公開資訊觀測站驗證後再進行正式回測。",
    },
  };
}

// MOPS 驗證升級路徑
const MOPS_UPGRADE_CHECKLIST = [
  "從 MOPS 下載各季財報公布日期",
  "比對 EstimatedEffectiveDate 與實際公布日期",
  "若誤差 > 3 個交易日，更新 EstimatedEffectiveDate",
  "將 LookaheadRisk 從 LOW 升級為 VERIFIED",
  "重新執行回測並比較結果差異",
];
```

---

### RISK-4：自動化失靈風險（Auto-fill Hallucination）

**風險描述：**
Codex 或程式在無法取得欄位時，可能自動填入預設值（如 ROE=10），
導致規則被錯誤觸發，產生幻想訊號。

**緩解措施：**

```javascript
// 全域禁止 defaultFill 行為
const NO_DEFAULT_FILL_POLICY = Object.freeze({
  enabled: true,
  message: "FORBIDDEN: Never fill missing fields with default values",
  enforcement: "THROW_ERROR",  // 違反時拋出錯誤，不是靜默填值
});

// 所有欄位存取必須通過此函式
function getFieldValue(row, fieldName, options = {}) {
  const value = row[fieldName];

  // 嚴格禁止：不得使用 || 或 ?? 提供預設值
  if (value === undefined || value === null || value === "") {
    // 必走 DATA_MISSING 路徑
    const missingResult = {
      value: null,
      status: "DATA_MISSING",
      reasonCode: `${fieldName}_MISSING`,
      affectedRules: getAffectedRules([fieldName]),
    };

    // 觸發 Dry-Run 停止（若在執行期間）
    if (options.inExecution) {
      throw new Error(
        `STOP-3: Field ${fieldName} is missing. ` +
        `Affected rules: ${missingResult.affectedRules.join(", ")}. ` +
        `Cannot proceed without Owner confirmation.`
      );
    }

    return missingResult;
  }

  return { value, status: "OK" };
}

// 範例：正確的欄位存取方式
function calculateROESignal(row) {
  const roe = getFieldValue(row, "ROE_TTM_Pct", { inExecution: true });

  if (roe.status === "DATA_MISSING") {
    // 停用相關規則，輸出 DATA_MISSING
    return {
      signal: "HOLD",
      reasonCodes: [roe.reasonCode],
      disabledRules: roe.affectedRules,
    };
  }

  // 正常計算
  if (roe.value >= 11.5) return { signal: "ROE_STRONG_QUALIFIED" };
  if (roe.value >= 10.0) return { signal: "ROE_ADD_QUALIFIED" };
  if (roe.value >= 8.0)  return { signal: "ROE_BELOW_10" };
  return { signal: "ROE_BLOCK" };
}

// Codex 執行前的 defaultFill 掃描
function scanForDefaultFillPatterns(codeString) {
  const FORBIDDEN_PATTERNS = [
    /data\.\w+\s*\|\|\s*\d+/g,          // data.ROE || 10
    /data\.\w+\s*\?\?\s*\d+/g,          // data.ROE ?? 10
    /data\.\w+\s*=\s*data\.\w+\s*\|\|/, // data.ROE = data.ROE || 10
    /defaultValue\s*=\s*\d+/g,           // defaultValue = 10
    /fallback\s*=\s*\d+/g,               // fallback = 10
  ];

  const violations = [];
  for (const pattern of FORBIDDEN_PATTERNS) {
    const matches = codeString.match(pattern);
    if (matches) {
      violations.push({ pattern: pattern.toString(), matches });
    }
  }

  if (violations.length > 0) {
    throw new Error(
      `STOP: DefaultFill patterns detected in code:\n` +
      violations.map(v => `  ${v.matches.join(", ")}`).join("\n") +
      `\nAll missing fields MUST go through DATA_MISSING path.`
    );
  }

  return { clean: true };
}
```

---

## 風險矩陣總覽

| 風險 | 嚴重性 | 發生機率 | 緩解措施 | 殘餘風險 |
|---|---|---|---|---|
| RISK-1 資料漂移 | 高 | 中 | ETL 健康檢查 + DATA_INVALID alert | 低 |
| RISK-2 權限濫用 | 高 | 低 | 雙重確認 + Audit Log 強制記錄 | 極低 |
| RISK-3 回測偏差 | 中 | 高 | 紅色警示 + 報告標註 + MOPS 升級路徑 | 中（待 MOPS 驗證後降低）|
| RISK-4 自動填值 | 高 | 中 | 全域禁止 + 程式碼掃描 + STOP 機制 | 低 |

---

*本規格文件由 Office Agent 依據 SKILL.md v1.1、Copilot 補強建議與風險評估制定。*
*版本：v1.1 / 2026-06-02*