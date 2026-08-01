\---

name: retirement-warroom-codex-agent

description: >

&#x20; 退休存股戰情室專案的 Codex 執行 Skill v12。

&#x20; 涵蓋主程式優化任務的完整執行規範、資料治理守則、

&#x20; 訊號系統規則、欄位契約、Phase 工程階段指引，

&#x20; 以及防跑偏自我檢查機制。

&#x20; 適用於所有協助本專案的 AI Coding Agent。

\---



\# 退休存股戰情室 — Codex Agent Skill v12



\## 使用方式



每次給 Codex 任務時，將本 SKILL.md 連同任務說明一起提供。

Codex 必須在開始寫任何程式碼前，完整閱讀本文件。



\---



\## PART A：最高原則（不得跳過）



\### A.1 三條鐵律



1\. 不得幻想資料 — 缺欄位就是缺欄位，不得用預設值填充，不得偽造歷史序列。

2\. 不得自行啟用規則 — 規則啟用狀態由規格文件決定，disabled 就是 disabled。

3\. 不得越界修改 — 每次任務只能修改被明確指定的檔案。



\### A.2 系統定位



本系統是「退休存股與長期複利決策輔助系統」，不是短線交易工具。

HOLD 是系統預設狀態，不是失敗訊號。

不因單日股價下跌觸發 SELL。

不因單一稅碼或稅務事件直接觸發 SELL\_ALL。



\### A.3 Codex 的角色



Codex 是「執行工具」，不是「決策者」。

規格文件未明確授權的事項，Codex 一律停下來詢問，不得自行推斷執行。



\---



\## PART B：主程式架構邊界



\### B.1 主程式應包含



即時看板、資料來源 DataBadge、欄位支援度、目前訊號、

停用規則、缺欄位提醒、研報庫入口、SOP 入口、Backtest 入口摘要



\### B.2 主程式不得包含



完整研報全文、完整 SOP 全文、大量長篇說明文章、

研報 catalog 維護邏輯、SOP catalog 維護邏輯、過於龐大的完整回測系統



\### B.3 各模組修改權限



| 模組 | Codex 可修改？ | 說明 |

|---|---|---|

| index.optimized.main.html | 僅限被明確指定的任務 | UI架構變更需Owner另行核准 |

| reports.html / report\_viewer.html | 僅限被明確指定的任務 | |

| SOP.html / sop\_viewer.html | 僅限被明確指定的任務 | |

| Backtest 引擎 | 需獨立核准 | |

| \*\*2317\_master\_v8.csv\*\* | \*\*唯讀，禁止寫入\*\* | Owner建立的現行數據庫 |

| \*\*2317\_daily\_price.csv\*\* | \*\*唯讀，禁止寫入\*\* | Owner建立的每日PB雙表 |

| \*\*SKILL\_v12.md\*\* | \*\*唯讀，禁止寫入\*\* | 只有Owner可修改 |

| \*\*2317\_DATA\_GOVERNANCE\_SPEC.md\*\* | \*\*唯讀，禁止寫入\*\* | 只有Owner可修改 |

| \*\*macro\_snapshot.csv\*\* | \*\*唯讀，禁止寫入\*\* | 總經快照，只有Owner可更新 |

| fundamentals\_COMPLETE.financials\_rebuilt.csv | 禁止，需 Owner 書面核准 | 舊版數據庫，禁止使用 |

| fundamentals\_COMPLETE.enriched.csv | 禁止，需 Owner 書面核准 | 舊版數據庫，禁止使用 |

| 04A\_FIELD\_MAPPING\_WORKING\_v1.csv | 禁止，需 Owner 書面核准 | 舊版mapping，禁止使用 |



\*\*數據庫架構說明（Codex 必須了解）：\*\*

```

【現行數據庫（v8，Owner建立）】唯讀

&#x20; 2317\_master\_v8.csv      → 季度主數據庫（50欄，21列）

&#x20; 2317\_daily\_price.csv    → 每日PB雙表（1,346筆）



【舊版數據庫】禁止使用

&#x20; fundamentals\_COMPLETE.financials\_rebuilt.csv

&#x20; fundamentals\_COMPLETE.enriched.csv

&#x20; 04A\_FIELD\_MAPPING\_WORKING\_v1.csv



【規格文件】唯讀，只有Owner可修改

&#x20; SKILL\_v12.md / 2317\_DATA\_GOVERNANCE\_SPEC.md

&#x20; EXECUTION\_GUARD.md / TASK\_TEMPLATE.md

```



\---



\## PART C：資料來源系統



\### C.1 DATA\_SOURCE\_REGISTRY



```javascript

const DATA\_SOURCE\_REGISTRY = {

&#x20; CSV\_AUTHORITY:         { label: "正式 CSV 權威資料",    trustLevel: 5, canTriggerOfficialRules: true },

&#x20; USER\_CURATED\_WEB\_DATA: { label: "使用者查核網路資料",   trustLevel: 4, canTriggerOfficialRules: "conditional" },

&#x20; EMBEDDED\_CSV:          { label: "內嵌備援資料",         trustLevel: 3, canTriggerOfficialRules: "limited" },

&#x20; API\_REALTIME:          { label: "即時 API 補充資料",    trustLevel: 3, canTriggerOfficialRules: "limited" },

&#x20; MANUAL\_OVERRIDE:       { label: "手動覆寫推演",         trustLevel: 2, canTriggerOfficialRules: false },

&#x20; SANDBOX\_MODE:          { label: "沙盒展示資料",         trustLevel: 1, canTriggerOfficialRules: false },

&#x20; DATA\_MISSING:          { label: "資料缺失",             trustLevel: 0, canTriggerOfficialRules: false },

&#x20; DATA\_INVALID:          { label: "異常資料",             trustLevel: 0, canTriggerOfficialRules: false },

};

```



\### C.2 USER\_CURATED\_WEB\_DATA 重要原則



可信，但要標來源、標版本、標欄位、標規則啟用狀態。

不能讓使用者誤以為所有相關規則已完整自動化、已經通過回測、

或已具備完整 effectiveDate 管線。



\### C.3 已知資料集（2317 鴻海）



```

sourceType: USER\_CURATED\_WEB\_DATA

label: 2021-2026 實盤大數據與籌碼矩陣

companyCode: 2317

dataFile: 2317\_master\_v8.csv

dataFileVersion: v8.0

officialRuleStatus: CONDITIONAL

```



\---



\## PART D：欄位契約（Field Manifest）v12 已同步 2317\_master\_v8.csv



\### D.1 可用欄位



| 欄位名稱 | 用途 | 狀態 | 備註 |

|---|---|---|---|

| Quarter | 季度對齊 | 可用 | |

| QuarterEndDate | 季末日期 | 可用 | |

| EstimatedEffectiveDate | Backtest 時間防護 | 可用 | 估算值，非 MOPS 驗證 |

| Revenue\_Q\_100M | 財報矩陣/TaxRev | 可用 | 億元 |

| GrossMarginPct | 毛利率觀測 | 可用 | % |

| OperatingIncome\_Q\_100M | ROIC 計算基礎 | 可用 | 億元 |

| TaxExpense\_Q\_1M | 稅務模型 | 可用 | 百萬元 |

| TaxRev\_Pct | Tax Z 核心輸入 | 可用 | % |

| TaxRevMean\_Pct | Tax Z 基準均值 | 可用 | 0.6848% |

| TaxRevStd\_Pct | Tax Z 基準標準差 | 可用 | 0.1974% |

| TaxZ | Tax Z-Score | 可用 | 計算值 |

| TaxZ\_Status | Tax Z 分類 | 可用 | |

| EPS\_Q | 單季 EPS | 可用 | 元/股 |

| EPS\_YoY\_Pct | EPS 年增率 | 可用 | 2021Q1起（含2020基期） |

| EPS\_TTM | 近四季EPS合計 | 可用 | 滾動計算 |

| BVPS | 每股淨值 | 可用 | 元/股 |

| QuarterEndClose | 季末收盤價 | 可用 | 快照，非每日 |

| CloseAdjusted | 還原權值收盤價 | 可用 | 加回已發放股息 |

| ROE\_Annual\_Pct | 年度 ROE | 可用 | Goodinfo年報 |

| ROE\_TTM\_Pct | 近四季滾動 ROE | 可用 | EPS\_TTM/平均BVPS |

| PB\_QuarterEnd | 季末 PB | 可用 | Close/BVPS快照 |

| PB\_Adjusted | 還原權值 PB | 可用 | CloseAdj/BVPS |

| PB\_Zone | PB 估值區間 | 可用 | CHEAP/FAIR/EXPENSIVE |

| ROE\_Signal | ROE 訊號 | 可用 | 基於ROE\_TTM |

| payoutRatio\_Pct | 配息率 | 可用 | 計算值（非直接財報） |

| CashDividend | 年度現金股利 | 可用 | 依財報年度 |

| DividendYield\_Pct | 殖利率 | 可用 | 股利/季末收盤 |

| FCF\_Annual\_100M | 年度自由現金流 | 可用 | 年度數據，無季度 |

| MarketCap\_100M | 季末市值 | 可用 | 收盤×140億股 |

| FCFYield\_Annual\_Pct | FCF殖利率年度 | 可用 | FCF/市值 |

| ROIC\_Approx\_Pct | 投入資本報酬率近似 | 可用 | 簡化公式，觀測用 |

| ROIC\_Precise\_Pct | 精確ROIC | 可用 | NOPAT\_Annual/InvestedCapital |

| NOPAT\_Annual\_100M | 年化NOPAT | 可用 | v7新增 |

| InvestedCapital\_100M | 投入資本 | 可用 | Debt+Equity-Cash |

| Cash\_100M | 現金 | 可用 | |

| InterestBearingDebt\_100M | 有息負債 | 可用 | |

| NetDebt\_100M | 淨負債 | 可用 | |

| NetDebtStatus | 淨負債狀態 | 可用 | |

| EBITDA\_Approx\_100M | EBITDA近似值 | 可用 | OpInc+實際D\&A（v8修正） |

| DA\_Est\_100M | 折舊攤銷實際值 | 可用 | 年報實際值÷4（v8修正） |

| NetDebtToEBITDA\_Approx | 淨負債/EBITDA近似 | 可用 | 觀測用 |

| NetDebtToEBITDA\_Status | 槓桿狀態分類 | 可用 | NET\_CASH/LOW\_SAFE/MODERATE/HIGH |

| OperatingMarginPct | 營業利益率 | 可用 | 精確計算 |

| OperatingMarginStatus | 營業利益率狀態 | 可用 | 觀測用 |

| BlackSwanFlag | 黑天鵝標注 | 可用 | 人工標注 |

| BlackSwanNote | 黑天鵝說明 | 可用 | 人工標注 |



\### D.2 每日價格雙表（2317\_daily\_price.csv）



```

欄位：Date, Close, QuarterKey, BVPS\_ref, PB\_daily, DataQuality, LookaheadGuard

用途：PB\_UNDERVALUE 規則（已啟用）

規則：BVPS 使用 EstimatedEffectiveDate 防護（無 look-ahead bias）

整合：用 QuarterKey JOIN 2317\_master\_v9.csv

警告：不得合併進季度 CSV

```



\### D.2b 外資持股欄位（2317\_master\_v9.csv 新增，2026-06-08）



```

欄位名稱              用途                    數據品質

ForeignHoldRatio\_Pct  外資持股比例（%）        ESTIMATED（年度插值）

ForeignHoldChange\_Pct 季度變化（%）            ESTIMATED（年度插值）

ForeignHoldTrend      趨勢標籤                 ESTIMATED（年度插值）



趨勢定義：

&#x20; RISING   = 季度變化 > +0.5%（外資回流）

&#x20; STABLE   = 季度變化 -0.5%\~+0.5%（外資穩定）

&#x20; DECLINING = 季度變化 < -0.5%（外資出貨）



數據來源：

&#x20; 年度數據：Goodinfo 股東持股結構（官方年報）

&#x20; 季度數據：年度數據線性插值

&#x20; 2026Q1：MoneyDJ 實際數據（34.76%）



使用限制：

&#x20; 僅作為「估值溫度計」輔助指標

&#x20; 不觸發任何買賣訊號（actionable: false）

&#x20; 必須搭配基本面+總經面使用（見 PART Z.7）

&#x20; 趨勢比水位更重要（見 PART Z.7 歷史驗證）



數據版本：2317\_master\_v9.csv（53欄，21列）

注意：v9 取代 v8，Codex 應使用 v9 版本

```



\### D.3 仍缺少的欄位（Codex 不得假裝存在）



```

欄位               | 禁止行為                    | 升級路徑

\------------------|-----------------------------|-----------------

ROE\_quarterly     | 禁止：季度ROE正式規則        | 補入季度財報ROE

payoutRatio\_direct| 禁止：計算值當直接財報        | 從財報驗證

effectiveDate\_mops| 必須標示LOOKAHEAD\_RISK       | 從MOPS驗證

FCF\_quarterly     | 禁止：季度FCF規則            | 補入季度OCF/Capex

```



\---



\## PART E：訊號系統規則



\### E.1 合法訊號清單（不得自創）



```

HOLD / BUY / ADD / STRONG\_ADD / HOLD\_PREMIUM

TRIM / SELL / SELL\_ALL / BLOCK

```



\### E.2 訊號語意



| 訊號 | 語意 | 常見錯誤 |

|---|---|---|

| HOLD | 繼續持有領息，不新增資金 | 不得解讀為看空 |

| BLOCK | 禁止投入新資金 / 禁止接刀，持股繼續持有 | 不得等同 SELL |

| SELL | 結構性惡化，退出或大幅降低核心持股 | 不得因單日股價下跌觸發 |

| SELL\_ALL | 極端風險處置 | v1 不作日常訊號 |

| TRIM | 風險再平衡，不是看壞公司 | 不得等同清倉 |

| STRONG\_ADD | 基本面極佳時加速複利投入 | 缺資料時不得假裝觸發 |



\### E.3 訊號優先序



```

1.資料有效性 2.Hard Block 3.股息與基本面安全

4.ROE與EPS品質 5.Tax Z 6.PB估值 7.籌碼防衛

8.季節性Beta Volume 9.最終訊號輸出

```



\### E.4 新資金 vs 既有持股分流



```javascript

output.newMoneySignal = "BLOCK";  // BUY / ADD / STRONG\_ADD / BLOCK

output.holdingSignal  = "HOLD";   // HOLD / HOLD\_PREMIUM / TRIM / SELL / SELL\_ALL

```



\---



\## PART F：規則啟用狀態



\### F.1 目前可啟用（觀測 / 候選）



```

Tax/Rev 觀測：可啟用

Tax Z 候選模型：可候選啟用

EPS 折算提示：可候選啟用

毛利率穩定度觀測：可啟用

籌碼防衛提示：可啟用為提示

Liquidity Warning：可啟用為提示

```



\### F.2 規則啟用狀態總表（v12 更新）



```

規則                          | 狀態            | 原因

\------------------------------|-----------------|------------------------------------------

STRONG\_ADD                    | ✅ 前置條件已核准| 條件：PB<1.25x AND ROE>=10% AND EPS\_YoY>=15% AND ROIC>10%

&#x20;                             |                 | Owner已核准（2026-06-03）

&#x20;                             |                 | 回測：觸發3季，1Q均值+20.9%，勝率67%

&#x20;                             |                 | 注意：條件全部同時成立才觸發，缺一不可

成長買進線 1.45x              | KEEP\_DISABLED   | 需 PB 每日序列正式啟用後再評估

EPS\_GROWTH\_QUALIFIED          | ✅ ENABLED      | Owner已核准（2026-06-03）

&#x20;                             |                 | 條件：EPS\_YoY>=15% 且 ROE\_TTM>=10% 且 PB<1.5x

&#x20;                             |                 | 作為ADD加分條件，不作獨立買進訊號

&#x20;                             |                 | 黑天鵝季度自動排除，每年年末重新回測

PB\_UNDERVALUE                 | ✅ ENABLED      | Owner已核准（2026-06-03）

&#x20;                             |                 | 條件：PB\_daily < 1.0x 且 ROE\_TTM >= 8% 且 無黑天鵝

&#x20;                             |                 | 回測：觸發5季，1Q均值+10.4%，勝率80%，2Q均值+26.4%

&#x20;                             |                 | 數據來源：2317\_daily\_price.csv（每日PB）

ROE\_BLOCK / ROE\_ADD\_QUALIFIED | ✅ ENABLED      | Owner已核准（2026-06-03）

&#x20;                             |                 | 基於ROE\_TTM\_Pct（EPS\_TTM÷平均BVPS），接受計算近似值

DIVIDEND\_TRAP                 | ✅ ENABLED      | Owner已核准（2026-06-03）

&#x20;                             |                 | 基於計算payoutRatio（股利÷EPS），接受非直接財報欄位

PB\_OVERHEAT                   | KEEP\_DISABLED   | 樣本僅1季，統計不足；改為BLOCK新資金觀測訊號

SELL\_ALL                      | KEEP\_DISABLED   | 不應由單一事件觸發

```



注意：即使 Owner 核准了 mapping patch，也不代表核准了上述規則的啟用。



\---



\## PART G：資料治理規則



\### G.1 缺資料的正確處理



```javascript

// 正確

if (!data.ROE) {

&#x20; signal = 'HOLD';

&#x20; reasonCodes.push('DATA\_MISSING');

&#x20; disabledRules.push('ROE\_BLOCK');

&#x20; return;

}

// 絕對禁止

if (!data.ROE) data.ROE = 10;

```



\### G.2 缺資料不得產生更積極的訊號



```

缺 ROE → 不得升級為 ADD 或 STRONG\_ADD

缺 EPS growth → 不得啟用成長買進線或 STRONG\_ADD

缺 payoutRatio → 不得啟用配息陷阱，但必須標示股息安全性未檢查

缺 Tax Z → 不得假設稅務安全，必須標示 Tax Z 未檢查

缺 BVPS/PB → 不得輸出以 PB 為核心依據的 BUY/ADD/TRIM/HOLD\_PREMIUM

```



\### G.3 Backtest 禁止使用未來資訊



```javascript

// 正確

const availableData = csv.filter(row => row.effectiveDate <= backtestDate);

// 禁止：使用 quarterEndDate 直接對齊

// 禁止：使用未來才公布的財報數字

```



\### G.4 Tax Z 調整流程（9 步驟）



```javascript

function applyTaxZAdjustment(rawEPS, taxZ) {

&#x20; if (taxZ < 1) return rawEPS;

&#x20; if (taxZ >= 1 \&\& taxZ < 2) { reasonCodes.push('TAX\_DRAG\_LIGHT'); return rawEPS \* 0.95; }

&#x20; else { reasonCodes.push('TAX\_DRAG\_STRUCTURAL'); return rawEPS \* 0.85; }

&#x20; // Step7: 產生 adjusted EPS

&#x20; // Step8: 重新計算 EPS growth / PEG

&#x20; // Step9: 再判斷訊號

&#x20; // 禁止：Tax Z 高就直接 SELL

}

```



\### G.5 手動覆寫規則（MANUAL\_OVERRIDE）



```javascript

// 正確：手動覆寫必須標示來源

if (input.manualROE !== undefined) {

&#x20; data.ROE = input.manualROE;

&#x20; reasonCodes.push('MANUAL\_OVERRIDE');

&#x20; dataBadge = 'MANUAL\_OVERRIDE';

}

// 禁止：手動值默默覆蓋 CSV 權威資料

// 禁止：手動推演被誤認為正式回測

```



\---



\## PART H：決策輸出格式



\### H.1 主程式第一階段輸出



```javascript

{

&#x20; dataStatus: "PARTIAL\_BUT\_TRUSTED",

&#x20; dataSource: "USER\_CURATED\_WEB\_DATA",

&#x20; newMoneySignal: "HOLD\_OR\_WAIT",

&#x20; holdingSignal: "HOLD",

&#x20; taxStatus: "TAX\_DRAG\_CANDIDATE",

&#x20; liquidityStatus: "LIQUIDITY\_OBSERVATION",

&#x20; disabledRules: \["PB\_OVERHEAT","SELL\_ALL","成長買進線1.45x"],

&#x20; enabledRules:  \["ROE\_BLOCK","ROE\_ADD\_QUALIFIED","DIVIDEND\_TRAP",

&#x20;                 "EPS\_GROWTH\_QUALIFIED","PB\_UNDERVALUE","STRONG\_ADD\_前置條件"],

&#x20; reasonCodes: \["USER\_CURATED\_WEB\_DATA","TAX\_REV\_AVAILABLE","EPS\_AVAILABLE"]

}

```



\### H.2 Backtest 輸出規格（缺一不可）



```

date, signal, newMoneySignal, holdingSignal,

enabledRules, disabledRules, disabledReasons, reasonCodes,

dataSupportLevel, dataSource, lookaheadRisk,

missingFields, officialRulesUsed, researchRulesExcluded

```



\---



\## PART I：Reason Code 標準（不得自創）



```

DATA\_MISSING / DATA\_INVALID / LOOKAHEAD\_RISK

ROE\_BLOCK / ROE\_ADD\_QUALIFIED / ROE\_STRONG\_QUALIFIED

EPS\_GROWTH\_QUALIFIED / DIVIDEND\_TRAP

TAX\_DRAG\_LIGHT / TAX\_DRAG\_STRUCTURAL / TAX\_DRAG\_STRUCTURAL\_VERIFIED

PILLAR\_TWO\_REGULATORY\_CHANGE

PB\_UNDERVALUE / PB\_GROWTH\_PREMIUM / PB\_OVERHEAT / PB\_PREMIUM\_HOLD

PEG\_OVERHEAT / LIQUIDITY\_WARNING

SEASONAL\_DOWNGRADE / SEASONAL\_CAUTION / SEASONAL\_FAVORABLE

VOLUME\_DIVERGENCE / VOLUME\_BREAKOUT / BETA\_POSITION\_LIMIT

MANUAL\_OVERRIDE / CSV\_AUTHORITY / SANDBOX\_MODE

USER\_CURATED\_WEB\_DATA / TAX\_REV\_AVAILABLE / EPS\_AVAILABLE

LIQUIDITY\_DATA\_AVAILABLE / PB\_MISSING / ROE\_MISSING / PAYOUT\_RATIO\_MISSING

DIVIDEND\_GROWTH / BLACK\_SWAN\_EXCLUDED

```



\---



\## PART J：版本邊界（不得混用）



\### J.1 v1 正式採用規則



```

HOLD 預設狀態 / PB 25th=1.25x / PB 75th=1.95x

成長條件下買進線可放寬至 1.45x（條件性）

ROE<8%:BLOCK / ROE>=10%:ADD資格 / ROE>=11.5%:STRONG\_ADD資格

EPS growth>=15%：成長溢價資格

payoutRatio<50% 且 EPS growth<15%：配息陷阱,BLOCK

Tax Z>=2：結構性稅基侵蝕,需EPS haircut

```



\### J.2 v1.5 候選規則（不得進正式判定）



```

AI Auto-Rerating:1.40/2.15 / Hyper-Growth Override

Beta控倉 / Volume breakout / 季節性降級

```



\### J.3 v2 研究版規則（不得進 v1 正式判定）



```

Forward ROE PB mapping / Relative PB / 同業PB

AI純度 / FCF / Debt/EBITDA / 完整股息可持續性模型

```



\---



\## PART K：工程階段指引



```

Phase 1：資料防偽與來源標示（只改 index.optimized.main.html）

Phase 2：研報庫資料匯入主程式

Phase 3：Tax/Rev 與 Liquidity Warning 初版上線

Phase 4：主程式減脂

Phase 5：補齊 v1 正式決策欄位（PB/ROE/EPS growth/payoutRatio/CashDividend/effectiveDate）

```



\---



\## PART L：UI 卡片設計規範



```

L.1 資料來源總覽卡：顯示 USER\_CURATED\_WEB\_DATA、可用欄位、不可用欄位、目前正式狀態

L.2 規則啟用狀態卡：正式可用/候選可用/停用 三區分類

L.3 缺欄位提醒卡：列出仍需補的欄位清單

L.4 決策者行動指引卡：每個DISABLED規則附上啟用路徑，不只亮燈

```



\---



\## PART M：執行前自我檢查清單



```

□ 我是否清楚本次任務允許修改哪些檔案？

□ 我是否確認本次任務不涉及規則啟用？

□ 我是否確認本次任務不涉及 Backtest 修改？

□ 我是否確認本次任務不涉及 fundamentals CSV 修改？

□ 我是否確認本次任務不涉及 04A\_FIELD\_MAPPING\_WORKING\_v1.csv 寫入？

□ 我是否確認所有訊號名稱使用標準清單？

□ 我是否確認缺資料時採用保守降級，不假裝欄位存在？

□ 我是否確認 Backtest 不使用未來資訊？

□ 我是否確認 Reason Code 使用標準代碼？

□ 我是否確認新資金訊號與既有持股訊號已分流輸出？

□ 我是否確認 USER\_CURATED\_WEB\_DATA 已正確標示，不被誤認為 CSV\_AUTHORITY？

□ 我是否確認 Tax/Rev 異常不會直接觸發 SELL 或 SELL\_ALL？

□ 我是否確認籌碼資料不會單獨主導 BUY / ADD / SELL 決策？

□ 我是否確認本次修改符合「退休存股」定位？

□ 我是否確認 Tax Z 異常已查明原因（Pillar Two 新制=VERIFIED，不觸發 SELL）？

□ 我是否確認季節性勝率只作 UI 提示，不自動降級訊號？

□ 我是否確認現金流儀表板數據未被加減碼邏輯污染？

□ 我是否確認所有 Alert 都標示 actionable: false？

□ 我是否確認 preflight check 已通過？

□ 我是否確認黑天鵝季度（BlackSwanFlag != None）已自動排除相關規則計算？

```



如果任何一項無法確認，Codex 必須停下來詢問 Owner，不得自行推斷繼續執行。



\---



\## PART N：常見跑偏模式與防範



| 跑偏模式 | 防範方式 |

|---|---|

| 幻想欄位 | 缺欄位必須 DATA\_MISSING，停止該規則 |

| 規則自動升級 | 先查規則啟用狀態，disabled 就是 disabled |

| BLOCK 變 SELL | 嚴格區分 newMoneySignal 與 holdingSignal |

| PB 高就 SELL | PB 高只能觸發 HOLD\_PREMIUM 或 TRIM |

| Tax Z 高就 SELL | Tax Z 高先做 EPS haircut，再重新判斷訊號 |

| Tax/Rev 異常就 SELL | 只輸出 TAX\_DRAG\_CANDIDATE 提示，不直接賣出 |

| 籌碼主導長期決策 | 籌碼只作風險修飾，不單獨主導退休存股賣出 |

| 越界修改 | 每次任務只動被指定的檔案 |

| 研究版規則混入 v1 | v2 規則只能在研報庫，不進 v1 正式判定 |

| 沙盒當正式回測 | SANDBOX\_MODE 必須標示，不作正式判定 |

| USER\_CURATED 當 CSV\_AUTHORITY | 必須標示 USER\_CURATED\_WEB\_DATA，不得升格 |

| 主程式塞知識庫 | 主程式只保留操作架構、判定邏輯、資料狀態 |

| Alert 自動改訊號 | 所有 Alert 必須標示 actionable: false |

| 現金流影響訊號 | 現金流儀表板完全獨立，只讀不寫 |

| 黑天鵝污染規格 | BlackSwanFlag != None 的季度自動排除回歸計算 |

| 報告只亮燈DISABLED | 每個DISABLED規則必須附決策者行動指引 |



\---



\## PART O：目前核准狀態摘要



```

一般程式修改任務：Owner 在對話中明確指定 → Codex 可執行

CSV 資料寫入：需 Owner 明確書面核准 → 目前：NOT\_APPROVED

規則啟用：

&#x20; ROE\_BLOCK / ROE\_ADD\_QUALIFIED → ✅ ENABLED（Owner核准 2026-06-03）

&#x20; DIVIDEND\_TRAP                 → ✅ ENABLED（Owner核准 2026-06-03）

&#x20; OperatingMarginFloor 門檻     → ✅ 2.8%（Owner核准 2026-06-03）

&#x20; EPS\_GROWTH\_QUALIFIED          → ✅ ENABLED（Owner核准 2026-06-03）

&#x20; PB\_UNDERVALUE                 → ✅ ENABLED（Owner核准 2026-06-03）

&#x20; STRONG\_ADD前置條件            → ✅ ENABLED（Owner核准 2026-06-03）

&#x20; PB\_OVERHEAT / 成長買進線1.45x → KEEP\_DISABLED

Backtest 修改：需獨立核准 → 目前：SAFE\_TO\_MODIFY\_BACKTEST\_NO

effectiveDate mapping patch（04A）：需 Owner 明確核准+備份+rollback

&#x20; → 目前：REQUEST\_PREPARED\_NOT\_GRANTED，Scope 鎖定：2317\_SAMPLE\_ONLY

```



數據欄位可用性 vs 規則啟用對照：



| 欄位 | 有數據 | 規則啟用 | 原因 |

|---|---|---|---|

| ROE\_Annual\_Pct | 是 | 否 | 年度數字，非季度 |

| ROE\_TTM\_Pct | 是 | ✅ 是 | Owner核准 2026-06-03 |

| PB\_Adjusted | 是 | 否 | 季末快照，非每日序列 |

| PB\_daily | 是 | ✅ 是 | 每日price.csv已建立 |

| payoutRatio\_Pct | 是 | ✅ 是 | Owner核准 2026-06-03 |

| ROIC\_Precise\_Pct | 是 | 觀測 | 年度稅率近似，SPEC\_ONLY |

| DividendYield\_Pct | 是 | 觀測 | 展示用 |

| EPS\_TTM | 是 | 觀測 | 展示用 |



\---



\## PART P：上游規格文件優先序



```

本 SKILL.md（執行層守則）

&#x20;   ↑

退休存股戰情室主程式優化計畫書 v1.0（工程階段指引）

&#x20;   ↑

02\_SPEC\_DECISION\_LOGIC\_v1.md（加減碼邏輯唯一真相來源）

&#x20;   ↑

03\_DATA\_SUPPORT\_MATRIX\_v1.md（資料支援度矩陣）

&#x20;   ↑

01\_PROJECT\_ANCHOR\_退休存股戰情室\_v1.md（專案北極星）

```



規格衝突時，以上游文件為準。本 SKILL.md 不得覆蓋上游規格。



\---



\## PART Q：Tax Z 雙軌基準（Pillar Two 新制後）



\### Q.1 背景



2025Q4 鴻海因 OECD Pillar Two 全球最低稅負制（BEPS 2.0）正式上路，

加上遞延所得稅負債一次性調整與中國子公司盈餘匯回，

導致 Tax/Rev 結構性上移至 1.099%（Z=2.10）。

此為已驗證的法規性事件，不代表本業惡化。



\### Q.2 雙軌基準



```

歷史基準（適用 2021Q1\~2024Q4 回測）：mean=0.620%, std=0.170%

新制基準（適用 2025Q1 起觀測）：mean=0.850%, std=0.150%（暫定）

```



\### Q.3 Codex 實作規則



```javascript

// 2025Q4 是已驗證的法規性事件

if (quarter === "2025Q4" \&\& taxZ >= 2) {

&#x20; taxZStatus = "TAX\_DRAG\_STRUCTURAL\_VERIFIED";

&#x20; reasonCodes.push("PILLAR\_TWO\_REGULATORY\_CHANGE");

&#x20; // 不觸發 SELL 或 BLOCK

}

// 2026 年起 EPS 預估必須納入新稅率（24\~26%），不得用舊稅率（\~20%）

```



\---



\## PART R：季節性勝率整合規則



\### R.1 鴻海歷史月份勝率



```

1月:10%(RED) 2月:50%(YELLOW) 3月:80%(GREEN) 4月:50%(YELLOW)

5月:70%(GREEN) 6月:70%(GREEN) 7月:50%(YELLOW) 8月:30%(RED)

9月:30%(RED) 10月:80%(GREEN) 11月:30%(RED) 12月:50%(YELLOW)

```



\### R.2 季節性規則（v1.5 候選，目前為觀測提示）



```javascript

{ code: 'SEASONAL\_CAUTION', severity: 'WARNING', actionable: false }

{ code: 'SEASONAL\_FAVORABLE', severity: 'INFO', actionable: false }

// 禁止：季節性直接降級訊號

// 禁止：因月份直接觸發 SELL

```



\---



\## PART S：退休現金流儀表板規格



\### S.1 定位



退休現金流儀表板是展示工具，不是決策輸入。

數據不得影響加減碼訊號，不得觸發任何規則。



\### S.2 股息歷史數據（USER\_CURATED\_WEB\_DATA）



```

2021:5.20 / 2022:5.30 / 2023:5.40 / 2024:5.80 / 2025:7.20

連續成長年數：5年 / OCF 2025：2,269億 / 覆蓋率：2.26x

```



\### S.3 禁止事項



```

禁止：現金流數據影響訊號

禁止：股息下降直接觸發 SELL

禁止：持股張數影響 PB 或 ROE 計算

禁止：儀表板數據與 Backtest 混用

```



\---



\## PART T：Alerts Engine 退休存股語意規則



\### T.1 可觸發的 Alert（觀測型，全部 actionable: false）



```

TAX\_DRAG\_CANDIDATE：taxZ>=1 且 <2

TAX\_DRAG\_STRUCTURAL\_VERIFIED：taxZ>=2 且已確認法規性事件

LIQUIDITY\_WATCH：外資持股比例<36%

SEASONAL\_CAUTION：低勝率月份（1,8,9,11月）

SEASONAL\_FAVORABLE：高勝率月份（3,5,6,10月）

DIVIDEND\_GROWTH：股息年增

PB\_UNDERVALUE\_ALERT：PB\_daily < 1.0x（加碼機會提示）

```



\### T.2 禁止觸發的 Alert



```

單日股價下跌 → 不得觸發任何 Alert

單季 EPS 下滑 → 不得直接觸發 SELL Alert

PB 偏高 → 不得觸發 SELL Alert（只能 HOLD\_PREMIUM）

Tax Z 高但原因已確認 → 標示 VERIFIED，不觸發 BLOCK

```



\### T.3 Alert 輸出格式



```javascript

{ code, severity, message, actionable: false, dataSource, reasonCodes, disabledRules }

```



\---



\## PART U：前端防護層規格



\### U.1 preflight Check



```javascript

// 檢查 ForbiddenFiles 未被包含在 TargetFiles

// 檢查 RuleEnablementChange===false 時不允許規則變更

// 檢查 BacktestChange===false 時不允許 Backtest 修改

// 任何檢查失敗 → 輸出對應 STOP 代碼，阻止執行

```



\### U.2 schemaEnforcer



```javascript

// ROE缺失 → 停用 ROE\_BLOCK, ROE\_ADD\_QUALIFIED, ROE\_STRONG\_QUALIFIED

// BVPS缺失 → 停用 PB\_UNDERVALUE（已啟用但缺數據時仍需停用）, PB\_OVERHEAT

// EPS\_growth缺失 → 停用 EPS\_GROWTH\_QUALIFIED（已啟用但缺數據時仍需停用）

// payoutRatio缺失 → 停用 DIVIDEND\_TRAP

// TaxZ缺失 → 停用 TAX\_DRAG\_LIGHT, TAX\_DRAG\_STRUCTURAL

// BlackSwanFlag != None → 自動排除該季度相關規則計算

```



\### U.3 Audit Log 規格



```javascript

// 存入 audit\_log.json，不修改任何 CSV

// 記錄：timestamp, taskId, action, targetFiles,

//   ruleEnablementChange, ownerConfirmed,

//   disabledRules, missingFields, reasonCodes, dataSource

// 禁止：Audit Log 寫入任何 CSV 資料檔

// 禁止：Audit Log 修改規則啟用狀態

```



\---



\---



\## PART V：KPI 候選規格（SPEC\_ONLY\_NOT\_ENABLED）



\### V.0 重要聲明



```

以下三個 KPI 均為候選規格，狀態：SPEC\_ONLY\_NOT\_ENABLED

\- 不得啟用為正式規則

\- 不得修改 Backtest

\- 不得修改 fundamentals

\- 不得納入 04A effectiveDate patch

\- 不得觸發 STRONG\_ADD

啟用前必須完成：欄位可用性確認、公式一致性確認、產業門檻審查、Backtest 核准、Owner 明確核准

```



\### V.1 ROIC\_QUALITY\_GATE（資本效率品質門檻）



```

DataStatus: FIELDS\_AVAILABLE\_IN\_V7\_PENDING\_OWNER\_APPROVAL

回測結果：觸發6季，1Q差異-4.4%（落後指標，不建議獨立啟用）

建議：保留為動態門檻品質評分加分項（已在PART W實作）

```



\### V.2 NET\_DEBT\_EBITDA\_SAFETY\_GATE（淨負債對EBITDA安全門檻）



```

DataStatus: APPROX\_AVAILABLE（v8 D\&A已修正為年報實際值）

回測結果：全程觸發（鴻海財務安全），無區分度

建議：保留為財務安全底線守衛，背景監控用

2317觀測：全程NET\_CASH或LOW\_LEVERAGE\_SAFE，財務安全性優良

```



\### V.3 OPERATING\_MARGIN\_FLOOR（營業利益率底線）



```

門檻：2.8%（Owner核准 2026-06-03）

DataStatus: AVAILABLE

回測結果：觸發10季，1Q差異-4.3%（落後指標）

建議：保留為動態門檻品質評分加分項（已在PART W實作）

2317觀測：2024Q4起突破2.8%，AI伺服器業務貢獻明顯

```



\---



\## PART W：動態門檻框架（Dynamic Threshold Framework）



\### W.0 設計原則



```

核心精神：門檻不是人工拍板，是數據計算出來的

&#x20;        但最終確認權在 Owner，系統只是把計算過程透明化

&#x20;        讓決策有數據依據，不是憑感覺一刀切



解決三大問題：

&#x20; 1. 靜態門檻在AI轉型期過早觸發BLOCK → 滾動分位數自動調整

&#x20; 2. 2023年低PB黃金買點被錯過 → ADD線改為均值×0.85或PB<1.0x

&#x20; 3. CSP Capex縮減誤判為BLOCK → CSP信號只調高不調低

```



\### W.1 滾動12季PB分位數（核心工具）



```javascript

const window\_12q = last\_12\_quarters\_pb;  // 不含當季

const p25 = percentile(window\_12q, 0.25);

const p75 = percentile(window\_12q, 0.75);

const p90 = percentile(window\_12q, 0.90);



// 2026Q1 實際值：p25=1.04x  p75=1.63x  p90=1.78x

```



\### W.2 基本面品質評分（決定分位數寬鬆度）



```

評分項目（滿分120分，2026-06-08更新）：



基本面（115分）：

&#x20; EPS\_YoY > 10%          → +30分

&#x20; ROIC > 10%             → +25分

&#x20; OperatingMargin > 2.8% → +20分

&#x20; ROE\_TTM > 10%          → +15分

&#x20; NetDebt安全            → +10分（固定）

&#x20; OPM季度改善>0.1%       → +15分

&#x20; ROE YoY > 1%           → +10分



籌碼面輔助（+5分，來自Z.7）：

&#x20; ForeignHoldTrend = RISING   → +5分（外資回流）

&#x20; ForeignHoldTrend = STABLE   → +2分（外資穩定）

&#x20; ForeignHoldTrend = DECLINING → 0分（外資出貨）



注意：

&#x20; 籌碼面加分為輔助項目，不影響主要評分邏輯

&#x20; 數據來源：2317\_master\_v9.csv（ForeignHoldTrend欄位）

&#x20; 數據品質：ESTIMATED（年度插值，非精確季度數據）



品質分 → 分位數選擇：

&#x20; ≥ 90分：BLOCK線用P90（寬鬆版）

&#x20; ≥ 80分：BLOCK線用P75（標準版）

&#x20; ≥ 60分：BLOCK線用P75×0.95

&#x20; < 60分：BLOCK線用P75×0.90（嚴格版）

```



\### W.3 CSP AI Capex 產業錨（只調高不調低）



```

追蹤對象：Microsoft / Meta / Google / Amazon（4巨頭）



CSP\_Signal 判定：

&#x20; YoY > 20% → STRONG  → BLOCK線 × 1.10

&#x20; YoY > 5%  → STABLE  → BLOCK線 × 1.05

&#x20; YoY ≤ 5%  → WATCH   → 不調整，發出觀察警示



CSP FCF次年確認：

&#x20; 前一年FCF YoY > 15% → FCF\_GROWING → BLOCK線再 × 1.05

&#x20; 前一年FCF YoY > 0%  → FCF\_STABLE  → 不調整

&#x20; 前一年FCF YoY ≤ 0%  → FCF\_DECLINING → BLOCK線 × 0.95



2026Q1 CSP狀態：STRONG（平均YoY +58%）+ FCF\_GROWING（+22%）

```



\### W.4 ADD線計算（三取最寬鬆）



```javascript

const add\_line = Math.max(

&#x20;   p25 \* quality\_mult,

&#x20;   pb\_mean\_12q \* 0.85,

&#x20;   1.00  // PB<1.0x淨值以下必ADD

);

// 2026Q1：ADD線 = 1.16x（對應股價約147元）

```



\### W.5 黑天鵝過濾器



```

類型：

&#x20; VERIFIED\_REGULATORY → 排除TaxZ回歸，EPS不調整

&#x20; ONE\_TIME\_EVENT      → 排除EPS\_YoY回歸，降低權重50%

&#x20; EXTERNAL\_SHOCK      → 降低PB回歸權重50%



已標注事件：

&#x20; 2021Q1：ONE\_TIME\_EVENT（COVID低基期）

&#x20; 2025Q4：VERIFIED\_REGULATORY（Pillar Two BEPS2.0）

&#x20; 2026Q1：EXTERNAL\_SHOCK（美國關稅衝擊）

```



\### W.6 季度動態門檻 SOP（每季財報公布後執行）



```

Step 1：數據更新（新增最新季度到v8 CSV）

Step 2：品質評分（計算本季基本面品質分）

Step 3：滾動分位數更新（重新計算P25/P75/P90）

Step 4：CSP Capex確認（查詢4巨頭最新Capex YoY）

Step 5：黑天鵝檢查（本季是否有異常事件）

Step 6：門檻輸出（附計算依據，不是人工拍板）

Step 7：Owner確認（確認或調整，記錄日期）

```



\### W.7 2026Q1 動態門檻實際計算結果



```

品質分：120/115 → 寬鬆版（P90）

CSP：STRONG → BLOCK線×1.10

FCF：GROWING → BLOCK線×1.05



BLOCK線 = 1.78 × 1.10 × 1.05 = 2.05x（約261元）

嚴格BLOCK = 2.05 × 1.10 = 2.26x（約287元）

ADD線 = 1.16x（約147元）



今日309元，PB=2.43x → STRICT\_BLOCK 🔴

溢價 = +18.5%（AI題材溢價）

```



\### W.8 Codex 實作規範



```javascript

// 禁止：人工拍板固定門檻

// 正確：每季執行動態計算

function calcDynamicThreshold(quarterData, cspData) {

&#x20;   const window = last12Q(quarterData, 'PB');

&#x20;   const {p25, p75, p90} = percentiles(window);

&#x20;   const pb\_mean = mean(window);

&#x20;   const qs = qualityScore(quarterData.latest);

&#x20;   const {block\_base, strict\_base} = selectPercentile(qs, p75, p90);

&#x20;   const csp\_mult = cspMultiplier(cspData.capex\_yoy);

&#x20;   const fcf\_mult = fcfMultiplier(cspData.fcf\_yoy\_prev);

&#x20;   const block\_line  = block\_base  \* csp\_mult \* fcf\_mult;

&#x20;   const strict\_line = strict\_base \* csp\_mult \* fcf\_mult;

&#x20;   const add\_line    = Math.max(p25 \* qualityMult(qs), pb\_mean \* 0.85, 1.00);

&#x20;   return { add\_line, block\_line, strict\_line, pb\_mean };

}

// 禁止：CSP信號調低BLOCK線

// 禁止：黑天鵝季度污染長期基準

```



\### W.9 動態門檻 vs 靜態門檻回測比較



```

靜態門檻（v1原版）：ADD=0季  HOLD=13季  BLOCK=8季

動態門檻 v3（本框架）：ADD=2季  ADD/WATCH=5季  HOLD=10季  BLOCK=4季



改善：ADD機會識別+7季，誤判BLOCK減少50%

```



\---



\---



\## PART X：HOLD/BLOCK 後續評估與 TRIM 觸發機制



\### X.0 設計原則



```

核心問題：

&#x20; ADD 有回測驗證 ✅

&#x20; BLOCK 只有「禁止新資金」，沒有後續評估 ❌

&#x20; HOLD 只有「繼續持有」，沒有風險分級 ❌

&#x20; TRIM 觸發條件完全未定義 ❌



補強目標：

&#x20; 1. HOLD 分三級（SAFE/WATCH/RISK）

&#x20; 2. BLOCK 附解除條件與目標價

&#x20; 3. TRIM 明確觸發條件與減碼幅度

```



\---



\### X.1 HOLD 分級制度



```

HOLD\_SAFE（安心持有）

&#x20; 條件：PB\_daily < 1.5x 且 品質分 ≥ 80

&#x20; 語意：基本面強勁，持有無憂，等待ADD機會

&#x20; 提示：「基本面品質優良，持有領息，等待PB回到ADD線」

&#x20; 後續：每季確認品質分是否維持 ≥ 80



HOLD\_WATCH（觀察持有）

&#x20; 條件：PB\_daily 1.5\~2.0x 或 品質分 60\~79

&#x20; 語意：估值偏高或基本面轉弱，需密切追蹤

&#x20; 提示：「估值偏高或基本面轉弱，密切追蹤以下指標」

&#x20; 觸發升級：若EPS\_TTM連續2季下滑>10% → 評估TRIM\_LIGHT

&#x20; 觸發升級：若ROE\_TTM跌破9% → 評估TRIM\_LIGHT



HOLD\_RISK（高風險持有）

&#x20; 條件：PB\_daily > 2.0x 且 品質分 < 70

&#x20; 語意：估值過高且基本面轉弱，考慮部分減碼

&#x20; 提示：「估值過高且基本面轉弱，建議評估TRIM」

&#x20; 觸發升級：自動進入TRIM評估流程



今日（2026-06-03，PB=2.43x，品質分120）：

&#x20; → HOLD\_WATCH（PB偏高但基本面強勁，品質分120不觸發RISK）

```



\---



\### X.2 BLOCK 解除條件與目標價



```javascript

// 每次輸出BLOCK訊號時，必須同時輸出：

output.blockSignal = "BLOCK";

output.blockReason = "PB超出動態BLOCK線";

output.blockRelease = {

&#x20;   addTarget:    { pb: add\_line,    price: add\_line \* bvps },    // ADD機會目標

&#x20;   holdTarget:   { pb: block\_line,  price: block\_line \* bvps },  // BLOCK解除目標

&#x20;   currentPB:    pb\_today,

&#x20;   gapToHold:    ((pb\_today - block\_line) / block\_line \* 100).toFixed(1) + "%",

&#x20;   gapToAdd:     ((pb\_today - add\_line) / add\_line \* 100).toFixed(1) + "%",

};



// 今日（2026-06-03）實際輸出：

// blockRelease = {

//   addTarget:  { pb: 1.16x, price: 約147元 }

//   holdTarget: { pb: 2.05x, price: 約261元 }

//   currentPB:  2.43x

//   gapToHold:  +18.5%（距BLOCK解除線還有18.5%空間）

//   gapToAdd:   +109%（距ADD線還有109%空間）

// }

```



\---



\### X.3 TRIM 觸發條件與減碼幅度



```

【PART Z.6 前置確認（2026-06-08新增）】

執行TRIM評估前，必須先確認股息安全性：



&#x20; 股息安全（Z.2指標三全部滿足）：

&#x20;   payoutRatio < 70% 且 EPS\_YoY > 0%

&#x20;   且 ROE\_TTM > 8% 且 NetDebt安全

&#x20;   → TRIM評估降一級（TRIM\_HEAVY→TRIM\_LIGHT，TRIM\_LIGHT→可選擇）

&#x20;   → 語氣：「可考慮」而非「建議」



&#x20; 股息不安全（Z.2指標三任一不滿足）：

&#x20;   → TRIM評估維持原級或升一級

&#x20;   → 股息惡化 = 退休存股的核心賣出訊號



觸發類型一：財務惡化型（TRIM\_HEAVY，建議減碼20\~30%）

&#x20; 條件（任一）：

&#x20;   EPS\_TTM 連續2季下滑 > 10%

&#x20;   ROE\_TTM 跌破 8%（ROE\_BLOCK觸發）

&#x20;   OperatingMargin 跌破 2.0%（低於門檻）

&#x20;   ROIC\_Precise 跌破 8% 連續2季

&#x20; 股息安全時：降為 TRIM\_LIGHT（建議減碼10\~20%）

&#x20; 股息不安全時：維持 TRIM\_HEAVY（建議減碼20\~30%）



觸發類型二：估值過熱型（TRIM\_LIGHT，可選擇減碼5\~15%）

&#x20; 條件（任一）：

&#x20;   PB\_daily > 2.5x 且 CSP\_Signal 轉為 WATCH

&#x20;   PB\_daily > 3.0x（無論基本面）

&#x20;   PB溢價超出動態BLOCK線 > 30%

&#x20; 股息安全時：降為可選擇（若現金充足可不執行）

&#x20; 股息不安全時：維持 TRIM\_LIGHT（建議減碼10\~20%）

&#x20; 說明：「估值偏高但股息安全，若現金充足可繼續持有」



觸發類型三：黑天鵝未驗證型（TRIM\_HEAVY，建議減碼20\~30%）

&#x20; 條件（任一）：

&#x20;   Tax Z > 2.0 且 原因未驗證（非VERIFIED\_REGULATORY）

&#x20;   EPS\_YoY < -30% 且 非黑天鵝季度

&#x20;   NetDebtToEBITDA 突破 2.0x（由NET\_CASH急速惡化）

&#x20; 股息安全時：降為 TRIM\_LIGHT（建議減碼10\~20%）

&#x20; 股息不安全時：維持 TRIM\_HEAVY（建議減碼20\~30%）



重要原則：

&#x20; TRIM ≠ 清倉，最大減碼幅度建議不超過50%

&#x20; TRIM後持股仍繼續領息

&#x20; TRIM觸發後下季重新評估，若改善可停止TRIM

&#x20; 禁止：單日股價下跌觸發TRIM

&#x20; 禁止：PB偏高但基本面強勁且股息安全時強制TRIM

&#x20; 新增：股息安全性是TRIM評估的前置確認（Z.6規則一）

```



\---



\### X.4 完整訊號體系（v12 升級版）



```

加碼訊號：

&#x20; STRONG\_ADD  → 四條件全滿足（PB<1.25x+ROE≥10%+EPS\_YoY≥15%+ROIC>10%）

&#x20; ADD         → PB\_UNDERVALUE觸發（PB\_daily<1.0x+ROE\_TTM≥8%+無黑天鵝）

&#x20; ADD\_WATCH   → 接近ADD線（PB在ADD線±10%範圍），觀察中



持有訊號：

&#x20; HOLD\_SAFE   → 安心持有（PB<1.5x，品質分≥80）

&#x20; HOLD\_WATCH  → 觀察持有（PB 1.5\~2.0x 或品質分60\~79）

&#x20; HOLD\_RISK   → 高風險持有（PB>2.0x 且品質分<70）



封鎖訊號：

&#x20; BLOCK       → 禁止新資金（PB超出動態BLOCK線）

&#x20;               必須附：解除條件、ADD目標價、HOLD目標價

&#x20; BLOCK\_WAIT  → BLOCK中但基本面持續改善，等待回調



減碼訊號：

&#x20; TRIM\_LIGHT  → 輕度減碼10\~20%（估值過熱型）

&#x20; TRIM\_HEAVY  → 重度減碼20\~30%（財務惡化型或黑天鵝未驗證型）

&#x20; SELL        → 結構性惡化，大幅減碼（需Owner明確核准）

&#x20; SELL\_ALL    → 極端風險，清倉（永久KEEP\_DISABLED，需Owner特別核准）

```



\---



\### X.5 今日（2026-06-03）完整訊號輸出範例



```javascript

{

&#x20; date: "2026-06-03",

&#x20; price: 309,

&#x20; pb\_daily: 2.43,

&#x20; quality\_score: 120,

&#x20; csp\_signal: "STRONG",



&#x20; // 新資金訊號

&#x20; newMoneySignal: "BLOCK",

&#x20; blockRelease: {

&#x20;   holdTarget: { pb: 2.05, price: 261, desc: "BLOCK解除線" },

&#x20;   addTarget:  { pb: 1.16, price: 147, desc: "ADD機會線" },

&#x20;   gapToHold:  "+18.5%",

&#x20;   gapToAdd:   "+109%"

&#x20; },



&#x20; // 既有持股訊號

&#x20; holdingSignal: "HOLD\_WATCH",

&#x20; holdReason: "PB=2.43x偏高，但基本面品質120分強勁",

&#x20; holdWatchItems: \[

&#x20;   "追蹤EPS\_TTM是否連續下滑（目前14.18元，歷史新高）",

&#x20;   "追蹤ROE\_TTM是否跌破9%（目前11.56%，安全）",

&#x20;   "追蹤CSP Capex是否轉為WATCH（目前STRONG）",

&#x20;   "追蹤PB是否突破2.5x（目前2.43x，接近警戒）"

&#x20; ],



&#x20; // TRIM評估

&#x20; trimEvaluation: {

&#x20;   triggered: false,

&#x20;   reason: "基本面強勁，無TRIM觸發條件",

&#x20;   nextReview: "2026Q2財報公布後（約2026-08）"

&#x20; },



&#x20; // 退休存股核心建議

&#x20; retirementAdvice: "持有領息策略正確，不因股價高而動搖。等待PB回到261元以下再評估停止BLOCK，回到147元以下再評估加碼。"

}

```



\---



\### X.6 季度後續評估 SOP



```

每季財報公布後，除 PART W 動態門檻更新外，

額外執行 PART X 後續評估：



Step 1：HOLD 分級更新

&#x20; → 計算本季品質分

&#x20; → 確認 HOLD\_SAFE / HOLD\_WATCH / HOLD\_RISK



Step 2：BLOCK 解除條件更新

&#x20; → 用最新 BVPS 重新計算目標價

&#x20; → 輸出「距BLOCK解除還有XX%」



Step 3：TRIM 觸發檢查

&#x20; → 逐一檢查三類觸發條件

&#x20; → 若觸發：輸出 TRIM 類型與建議減碼幅度

&#x20; → 若未觸發：確認並記錄「本季無TRIM觸發」



Step 4：決策者行動指引

&#x20; → 明確告知：現在應該做什麼 / 不應該做什麼

&#x20; → 附上下次評估時間點

&#x20; → 禁止：只亮燈，不給行動指引

```



\---



\---



\## PART Y：總經風險監控框架（Macro Risk Framework）



\### Y.0 設計原則



```

核心問題：

&#x20; 基本面強勁（鴻海5月營收強勁）但股價跟著大盤重挫

&#x20; → 這不是鴻海的問題，是系統性風險

&#x20; → 戰情室必須區分「基本面訊號」與「總經噪音」



三層分類：

&#x20; 第一類：短期市場噪音 → 不影響任何訊號

&#x20; 第二類：中期總經壓力 → 提高警戒，動態門檻收緊

&#x20; 第三類：系統性風險   → 觸發評估流程，可能TRIM



退休存股核心原則：

&#x20; 總經波動是短期噪音，基本面才是長期錨

&#x20; 大盤跌X% ≠ 鴻海基本面惡化

&#x20; 持股領息策略在總經波動中最穩健

```



\---



\### Y.1 總經監控數據庫（10項核心指標）



```

指標              最新值(2026-06-05)  來源                    更新頻率  警戒門檻        危機門檻

─────────────────────────────────────────────────────────────────────────────────────────

台幣/美元匯率      31.475             中央銀行(cbc.gov.tw)    每日      >33            >35

VIX恐慌指數        21.51              CBOE(cboe.com)          即時      >30            >40

WTI原油($/桶)      95.96              EIA via FRED            每日      >100           >120

美國GDP成長率      待確認             BEA(bea.gov)            每季      <1%            <0%（衰退）

美國失業率         待確認             BLS(bls.gov)            每月      >5%            >7%

台股週跌幅         待確認             TWSE(twse.com.tw)       每日      >10%           >15%

CSP Capex YoY      +58%               Epoch AI/SEC財報        每季      <+5%           <0%

鴻海月營收YoY      強勁成長           公開資訊觀測站          每月      <0%            <-10%

聯準會利率         待確認             Fed(federalreserve.gov) 每6週     急升>1%        急升>2%

美元指數DXY        待確認             ICE/MarketWatch         即時      >105           >110

```



\---



\### Y.2 官方數據來源清單



```

台幣匯率：cbc.gov.tw（中央銀行，每日16:00更新）

VIX：    cboe.com/tradable-products/vix/（CBOE官方，即時）

WTI油價：fred.stlouisfed.org/series/DCOILWTICO（EIA via FRED，每日）

美國GDP：bea.gov（BEA，每季公布）

美國失業率：bls.gov（BLS，每月第一個週五）

聯準會利率：federalreserve.gov（Fed，每6週FOMC）

美元指數：marketwatch.com/investing/index/dxy（ICE，即時）

台股指數：twse.com.tw（TWSE，每日）

CSP Capex：epoch.ai/data-insights（每季財報後）

鴻海月營收：mops.twse.com.tw（公開資訊觀測站，每月10日前）

```



\---



\### Y.3 三層風險分類



```

第一類：短期市場噪音（不影響訊號）

&#x20; 特徵：

&#x20;   單日/單週大盤波動

&#x20;   美國單月經濟數據異常

&#x20;   油價短期波動（±10%以內）

&#x20;   地緣政治緊張但未升級

&#x20; 戰情室處理：

&#x20;   → 不觸發任何訊號變更

&#x20;   → 記錄為 MARKET\_NOISE，觀察中

&#x20;   → 持股繼續 HOLD，領息不動搖



第二類：中期總經壓力（提高警戒）

&#x20; 特徵：

&#x20;   美國連續3個月以上經濟數據惡化

&#x20;   聯準會政策急轉（快速升息/降息）

&#x20;   油價持續高位（>$100/桶超過3個月）

&#x20;   台幣貶值 5\~8%

&#x20;   VIX 持續在 25\~35 區間

&#x20; 戰情室處理：

&#x20;   → CSP\_Signal 可能轉為 WATCH（動態門檻不再放寬）

&#x20;   → HOLD\_WATCH 追蹤清單新增總經指標

&#x20;   → 不觸發 TRIM，但提高警戒

&#x20;   → 每週更新總經數據庫



第三類：系統性風險（觸發評估流程）

&#x20; 特徵（任3項成立）：

&#x20;   □ 大盤單週跌幅 > 15%

&#x20;   □ VIX > 40

&#x20;   □ 美國GDP連續2季負成長

&#x20;   □ CSP 4巨頭任2家削減Capex > 20%

&#x20;   □ 台幣單月貶值 > 8%

&#x20;   □ 鴻海EPS\_TTM連續2季下滑 > 10%

&#x20;   □ 台海軍事衝突升級

&#x20;   □ 聯準會單次升息 > 1%

&#x20;   □ WTI油價 > $120/桶超過1個月

&#x20; 戰情室處理：

&#x20;   → 觸發 Y.4 系統性風險評估流程

&#x20;   → 可能觸發 TRIM（需Owner核准）

```



\---



\### Y.4 系統性風險評估流程



```

Step 1：確認是否為系統性風險

&#x20; → 檢查 Y.3 第三類清單，任3項成立 → 確認



Step 2：評估鴻海是否直接受影響

&#x20; 直接影響（高度相關）：

&#x20;   AI Capex崩潰 → 直接衝擊AI伺服器業務

&#x20;   美中全面脫鉤 → 供應鏈重組風險

&#x20;   台海軍事衝突 → 生產基地風險

&#x20; 間接影響（中度相關）：

&#x20;   美國衰退 → 消費電子需求下降

&#x20;   油價暴漲 → 運輸成本上升

&#x20;   台幣大貶 → 進口成本上升



Step 3：基本面是否同步惡化？

&#x20; 若 EPS\_TTM 開始下滑 → 觸發 TRIM 評估

&#x20; 若 ROE\_TTM 跌破 9% → 觸發 TRIM\_LIGHT

&#x20; 若 CSP Capex 轉為 WATCH → 動態門檻收緊

&#x20; 若 鴻海月營收連續3月負成長 → 觸發 TRIM 評估



Step 4：訊號調整



&#x20; 情境A：系統性風險 + 基本面未惡化

&#x20;   newMoneySignal：BLOCK（維持）

&#x20;   holdingSignal：HOLD\_WATCH（升級警戒）

&#x20;   動態門檻：CSP調整係數降為1.0（不再放寬）

&#x20;   建議：持股不動，等待系統性風險解除



&#x20; 情境B：系統性風險 + 基本面開始惡化

&#x20;   newMoneySignal：BLOCK

&#x20;   holdingSignal：HOLD\_RISK → 評估TRIM\_LIGHT（10\~20%）

&#x20;   需Owner核准



&#x20; 情境C：系統性風險 + 基本面嚴重惡化

&#x20;   newMoneySignal：BLOCK

&#x20;   holdingSignal：TRIM\_HEAVY（20\~30%）

&#x20;   需Owner明確核准

&#x20;   保留核心持股，不清倉

```



\---



\### Y.5 總經數據庫更新 SOP



```

每日（Owner 5分鐘可完成）：

&#x20; □ 查詢台幣匯率（cbc.gov.tw）

&#x20; □ 查詢VIX（cboe.com）

&#x20; □ 查詢WTI油價（fred.stlouisfed.org）

&#x20; □ 更新 macro\_snapshot.csv



每週：

&#x20; □ 確認台股週跌幅

&#x20; □ 確認美元指數DXY

&#x20; □ 評估是否升級風險等級



每月：

&#x20; □ 確認美國失業率（每月第一個週五）

&#x20; □ 確認鴻海月營收（每月10日前）

&#x20; □ 更新總經風險評估報告



每季：

&#x20; □ 確認美國GDP成長率

&#x20; □ 確認CSP 4巨頭Capex（財報後）

&#x20; □ 執行 PART W 動態門檻更新

&#x20; □ 執行 PART X 後續評估

&#x20; □ 執行 PART Y 系統性風險評估

```



\---



\### Y.6 新增數據庫：macro\_snapshot.csv



```

建議新增輕量總經快照數據庫：



欄位：

&#x20; Date, TWD\_USD, VIX, WTI\_Oil, US\_GDP\_QoQ, US\_Unemployment,

&#x20; TAIEX\_Weekly\_Chg, CSP\_Capex\_Signal, Hon\_Hai\_Rev\_YoY,

&#x20; Fed\_Rate, DXY, RiskLevel, RiskNote



RiskLevel 值：

&#x20; NORMAL    → 第一類，無異常

&#x20; CAUTION   → 第二類，中期壓力

&#x20; SYSTEMIC  → 第三類，系統性風險



今日快照（2026-06-05）：

&#x20; TWD\_USD=31.475, VIX=21.51, WTI=95.96

&#x20; CSP\_Capex\_Signal=STRONG, Hon\_Hai\_Rev\_YoY=強勁成長

&#x20; RiskLevel=CAUTION（VIX緊張+WTI接近警戒）

&#x20; RiskNote=美國對伊朗軍事行動，油市相對穩定，非系統性危機

```



\---



\### Y.7 總經風險 vs 鴻海基本面交互矩陣



```

&#x20;                   鴻海基本面強勁    鴻海基本面轉弱

&#x20;                   ─────────────────────────────────

總經噪音（第一類）  HOLD\_SAFE ✅      HOLD\_WATCH 🟡

&#x20;                   持股領息，不動搖  追蹤基本面改善



中期壓力（第二類）  HOLD\_WATCH 🟡     HOLD\_RISK 🔴

&#x20;                   提高警戒，等回調  評估TRIM\_LIGHT



系統性風險（第三類）HOLD\_WATCH 🟡     TRIM\_HEAVY 🔴

&#x20;                   持股不動，等解除  20\~30%減碼

&#x20;                   動態門檻收緊      需Owner核准



今日（2026-06-05）：

&#x20; 總經：第二類（中期壓力）

&#x20; 鴻海基本面：強勁（5月營收強勁，6月展望上調）

&#x20; → 落在「中期壓力 + 基本面強勁」= HOLD\_WATCH 🟡

&#x20; → 持股繼續持有，等待總經壓力解除

&#x20; → 若股價跌至261元以下 → BLOCK解除，可評估新資金

```



\---



\*PART Y 新增（2026-06-05）：總經風險監控框架\*

\*觸發背景：鴻海5月營收強勁但台指期大跌，揭示總經風險評估缺口\*

\*數據來源：CBC/CBOE/EIA/BEA/BLS/Fed/TWSE/Epoch AI/MOPS（全部官方來源）\*

\*每季執行：配合PART W動態門檻更新同步執行\*



\*PART X 新增（2026-06-04）：HOLD/BLOCK後續評估與TRIM觸發機制\*

\*解決問題：BLOCK無後續評估、HOLD無風險分級、TRIM無觸發條件\*

\*今日狀態：HOLD\_WATCH（PB=2.43x偏高，品質120分強勁）\*

\*BLOCK解除目標：261元（PB=2.05x）/ ADD機會目標：147元（PB=1.16x）\*



\## PART Z：設計哲學核心框架（2026-06-08 新增）



\### Z.0 系統定位聲明（必讀）



```

本系統的核心目標：

&#x20; 「確保退休生活的現金流永遠不中斷，

&#x20;   而不是最大化報酬或精準預測市場。」



本系統不試圖：

&#x20; 「預測黑天鵝或規避所有損失。」



本系統的先天限制：

&#x20; 適用於正常市場環境與已知類型的極端事件。

&#x20; 在真正的黑天鵝事件中，系統建議的可靠性將大幅降低。

&#x20; 任何規則型系統在歷史從未發生過的事件面前都有先天限制。

```



\### Z.1 三層哲學整合框架



```

優先順序一（最重要）：股息現金流保護

&#x20; 核心問題：「我的退休生活需要多少現金流？」

&#x20; 目標指標：股息覆蓋率 >= 80%（股息/年度生活費）

&#x20; 行動原則：若股息受威脅，這才是真正的賣出訊號

&#x20; 哲學：「我持有鴻海是為了股息，不是為了股價」



優先順序二（次重要）：損失上限保護

&#x20; 核心問題：「我的生活費是否依賴賣股？」

&#x20; 目標指標：現金緩衝 >= 18個月生活費

&#x20; 行動原則：若現金緩衝不足，優先補充

&#x20; 哲學：「我的生活費不依賴賣股」



優先順序三（輔助）：PB訊號參考

&#x20; 核心問題：「現在的估值是否合理？」

&#x20; 目標指標：ADD/BLOCK/TRIM線（PART W）

&#x20; 行動原則：在股息安全和現金充足的前提下參考

&#x20; 哲學：「低估值是機會，不是恐慌」

```



\### Z.2 股息現金流核心指標



```

指標一：股息覆蓋率（Dividend Coverage Ratio）

&#x20; 公式：年度股息收入 / 年度生活費 × 100%

&#x20; 計算：持股張數 × CashDividend / 年度生活費

&#x20; 目標：>= 80%

&#x20; 警示：< 60% → 🔴 股息覆蓋不足，優先補充持股

&#x20; 顯示：「股息覆蓋率：73%（距目標-7%）」



指標二：現金緩衝月數（Cash Buffer Months）

&#x20; 公式：現金資產 / 月度生活費

&#x20; 目標：>= 18個月

&#x20; 警示：< 12個月 → 🔴 現金緩衝不足

&#x20; 顯示：「現金緩衝：22個月 ✅」



指標三：股息安全性評估（Dividend Safety）

&#x20; 評估項目：

&#x20;   payoutRatio < 70%    → ✅ 配息可持續

&#x20;   EPS\_YoY > 0%         → ✅ 獲利支撐股息

&#x20;   ROE\_TTM > 8%         → ✅ 資本效率支撐

&#x20;   NetDebt安全          → ✅ 財務不影響配息

&#x20; 警示：任一項不滿足 → 🟡 股息安全性需關注



指標四：反脆弱準備度（Antifragility Readiness）

&#x20; 定義：預備資金（等待黑天鵝加碼的子彈）

&#x20; 目標：退休總資產的 10\~15%

&#x20; 觸發條件：PB < ADD線 + VIX > 40

&#x20; 顯示：「反脆弱準備：12% ✅（黑天鵝子彈充足）」

```



\### Z.3 黑天鵝優雅降級機制



```

Level 1（系統正常）：

&#x20; 所有指標有效，規則正常運作

&#x20; → 系統主導，Owner確認



Level 2（部分數據失效）：

&#x20; macro\_snapshot過期 > 7天 / 財報延遲 > 45天

&#x20; → 系統降級，顯示警告，Owner主導



Level 3（黑天鵝初期）：

&#x20; VIX > 50 或 單日跌幅 > 10%

&#x20; → 系統暫停所有買賣建議

&#x20; → 只顯示：

&#x20;   「極端市場事件偵測

&#x20;    損失評估：持股跌幅X%，市值損失Y萬

&#x20;    現金緩衝：Z個月 ✅（生活不受影響）

&#x20;    股息：仍持續（預計X元/股）✅

&#x20;    建議：不操作，等待穩定

&#x20;    反脆弱機會：若PB跌至ADD線，啟動預備資金」



Level 4（黑天鵝嚴重期）：

&#x20; VIX > 70 或 市場停市

&#x20; → 系統完全關閉買賣建議

&#x20; → 只顯示：

&#x20;   「系統暫停，請確認：

&#x20;    1. 現金緩衝是否充足（生活費保障）

&#x20;    2. 股息是否仍持續（現金流保障）

&#x20;    3. 若兩者均OK，預設行為：不操作」

```



\### Z.4 系統先天限制聲明



```

本系統能處理：

&#x20; 「已知的未知」（Known Unknowns）

&#x20; → 我們知道可能發生，但不知道何時的事件

&#x20; → 例：升息循環、AI泡沫修正、VIX暴漲



本系統無法處理：

&#x20; 「未知的未知」（Unknown Unknowns）

&#x20; → 歷史從未發生過的事件

&#x20; → 例：台海衝突、全球金融系統崩潰、AI顛覆製造業



退休族的三層防護（不依賴系統）：

&#x20; 第一層：現金緩衝（18\~24個月生活費）

&#x20;   → 黑天鵝時不需要賣股，系統失效也無妨

&#x20; 第二層：股息現金流（穩定配息）

&#x20;   → 即使股價崩跌，現金流仍持續

&#x20; 第三層：預設行為規則（心理防護）

&#x20;   → 「若系統失效，預設行為：不操作」

&#x20;   → 「若市場崩跌>30%，預設行為：持有」

&#x20;   → 「若感到極度恐慌，預設行為：等24小時」



設計哲學的最終版本：

&#x20; 「退休存股的目標不是最大化報酬，

&#x20;   也不是最小化波動，

&#x20;   而是確保退休生活的現金流永遠不中斷。

&#x20;   股息是生命線，股價是參考。

&#x20;   系統的價值在於保護生命線，

&#x20;   而不是預測股價。」

```



\### Z.5 哲學轉換適應路徑（Owner 參考）



```

階段一：認知重構（第1\~3個月）

&#x20; 核心任務：計算「我需要多少股息才能退休」

&#x20; 具體行動：

&#x20;   計算年度生活費

&#x20;   計算目標股息覆蓋率（建議80%）

&#x20;   計算需要的持股規模

&#x20; 心理挑戰：「我習慣看股價，現在要看股息」

&#x20; 應對方式：每週只看股息覆蓋率，不看股價



階段二：結構調整（第4\~6個月）

&#x20; 核心任務：建立現金緩衝和預備資金

&#x20; 具體行動：

&#x20;   確保現金緩衝達到18個月

&#x20;   設立預備資金帳戶（10\~15%）

&#x20;   設定股息自動再投資

&#x20; 心理挑戰：「持有現金感覺在浪費機會」

&#x20; 應對方式：把現金緩衝視為「保險費」，不是「閒置資金」



階段三：系統整合（第7\~12個月）

&#x20; 核心任務：把PB訊號整合進新框架

&#x20; 具體行動：

&#x20;   PB訊號作為輔助（不是主導）

&#x20;   股息安全性作為主要決策依據

&#x20;   建立預設行為規則（黑天鵝時的行動清單）

&#x20; 心理挑戰：「系統說BLOCK但股價還在漲」

&#x20; 應對方式：「BLOCK是不加碼，不是賣出。股息仍持續。」



階段四：穩定執行（第13個月後）

&#x20; 核心任務：維持紀律，不被市場情緒影響

&#x20; 評估指標：

&#x20;   股息覆蓋率是否達標？

&#x20;   現金緩衝是否充足？

&#x20;   預備資金是否就位？

&#x20; 成功標準：

&#x20;   「無論股價漲跌，我的退休生活不受影響」

```



\---



\### Z.7 外資持股比例的正確定位（2026-06-08 新增）



```

核心原則：外資持股「趨勢」比「水位」更重要

&#x20;         不得單獨使用，必須搭配基本面+總經面



歷史驗證（2021\~2026回測）：

&#x20; 單一外資持股回測：勝率50%（等於丟銅板，無意義）

&#x20; 五維度綜合回測：ADD訊號勝率71%（有參考價值）



外資持股的真實邏輯（顛覆直覺）：

&#x20; 2021\~2022：外資持股51%→44%（高水位但持續下降）

&#x20;   → 外資在高持股時緩慢出貨，不是吸籌

&#x20;   → PB同期0.96\~1.16x（低估），但後1季平均僅+1.7%



&#x20; 2024Q1後：AI轉型被認可，PB從1.0x漲至1.8x

&#x20;   → 外資持股反而從40%降至33%（出貨！）

&#x20;   → 散戶追高，外資出貨，完美印證籌碼操作邏輯



&#x20; 2025Q2：外資持股35.8%（低水位）+ PB=1.07x（低估）

&#x20;   → 雙重低估，後1季+66.2%（最強買點）



四種情境解讀：

&#x20; 外資高水位+持續下降 → 🔴 出貨警示（最危險）

&#x20;   即使PB低，也要謹慎（外資仍在出貨中）



&#x20; 外資低水位+開始回升 → 🟢 吸籌訊號（最佳買點）

&#x20;   搭配PB低+基本面OK → 雙重低估確認



&#x20; 外資低水位+PB也低   → ✅ 雙重低估（強力確認）

&#x20;   歷史最強買點情境（+66.2%）



&#x20; 外資低水位+PB偏高   → ⚠️ 外資已出貨完畢

&#x20;   散戶接盤風險高（2025Q4案例：後跌-28.2%）



使用規則：

&#x20; 1. 外資持股僅作為「估值溫度計」輔助指標

&#x20; 2. 不觸發任何買賣訊號（actionable: false）

&#x20; 3. 必須搭配基本面（ROE/股息）+ 總經面（RiskLevel）

&#x20; 4. 趨勢（RISING/STABLE/DECLINING）比水位更重要

&#x20; 5. 數據品質：ESTIMATED（年度插值，非精確季度數據）



與品質分的整合（PART W.2）：

&#x20; ForeignHoldTrend = RISING   → +5分（外資回流）

&#x20; ForeignHoldTrend = STABLE   → +2分（外資穩定）

&#x20; ForeignHoldTrend = DECLINING → 0分（外資出貨）



數據來源：

&#x20; 年度數據：Goodinfo 股東持股結構（官方年報）

&#x20; 季度數據：年度數據線性插值

&#x20; 2026Q1：MoneyDJ 實際數據（34.76%）

&#x20; 數據版本：2317\_master\_v9.csv（53欄，21列）

```



\### Z.6 與現有 PART 的交互優先順序規則



```

規則一：股息安全性 > PB訊號（最重要）



&#x20; 若股息安全（Z.2指標三全部滿足）：

&#x20;   TRIM評估降一級（強制 → 可選擇）

&#x20;   HOLD\_RISK → HOLD\_WATCH（若品質分>=80）

&#x20;   賣出建議語氣：「可考慮」而非「建議」



&#x20; 若股息不安全（Z.2指標三任一不滿足）：

&#x20;   TRIM評估維持或升一級

&#x20;   股息惡化 = 優先於PB訊號的賣出觸發點

&#x20;   語氣：「股息安全性惡化，這才是退休存股的核心賣出訊號」



規則二：ADD確認需通過Z.2前置檢查



&#x20; ADD訊號觸發後，依序確認：

&#x20; ① 股息覆蓋率 >= 80%？

&#x20;    否 → ADD\_OPPORTUNITY（優先補充持股至覆蓋率達標）

&#x20;    是 → 繼續下一步

&#x20; ② 現金緩衝 >= 18個月？

&#x20;    否 → 不動用預備資金加碼

&#x20;    是 → 繼續下一步

&#x20; ③ 反脆弱準備度 >= 10%？

&#x20;    否 → 小額加碼（預算5%以內）

&#x20;    是 → ADD\_CONFIRMED（可動用預備資金加碼）



規則三：HOLD\_RISK觸發條件加入股息安全性



&#x20; 現有條件：PB>2.0x 且 品質分<70

&#x20; 修訂條件：PB>2.0x 且 品質分<70 且 股息安全性任一項不滿足



&#x20; 若 PB>2.0x 且 品質分<70 但 股息安全：

&#x20; → 維持 HOLD\_WATCH（不升級至HOLD\_RISK）

&#x20; → 說明：「估值偏高但股息安全，持有邏輯仍完整」



規則四：黑天鵝期間的優先順序



&#x20; 黑天鵝期間（Z.3 Level 3/4）：

&#x20; 所有 PART W/X 的買賣建議暫停

&#x20; 只執行 Z.2 的確認：

&#x20; ① 現金緩衝是否充足？（生活費保障）

&#x20; ② 股息是否仍持續？（現金流保障）

&#x20; ③ 若兩者均OK → 預設行為：不操作，等待穩定



規則五：賣出訊號的優先順序（明確化）



&#x20; 第一優先（Z.2新增）：股息安全性惡化

&#x20;   payoutRatio > 80% 且 EPS\_YoY < 0%

&#x20;   → 退休存股的核心賣出訊號



&#x20; 第二優先（X.3現有）：財務惡化型

&#x20;   EPS\_TTM連續2季下滑>10% 或 ROE\_TTM跌破8%



&#x20; 第三優先（X.3現有，降為可選）：估值過熱型

&#x20;   PB >= 嚴格BLOCK線

&#x20;   → 若股息安全且現金充足，可選擇不賣出

```



\---



\*PART Z 新增（2026-06-08）：股息現金流優先設計哲學\*

\*整合三種哲學框架：精準預測（輔助）+ 損失控制（保護）+ 股息現金流（核心）\*

\*系統先天限制聲明：適用於正常市場，黑天鵝時優雅降級\*



\---



\*本 SKILL.md v12 由 Office Agent 依據專案規格文件整理制定。\*

\*版本號統一為 v12（原 v1.2）。\*

\*數據庫同步至 2317\_master\_v8.csv（D\&A年報實際值修正）。\*

\*每日PB雙表：2317\_daily\_price.csv（1,346筆，含look-ahead防護）。\*

\*已核准規則（6項）：ROE\_BLOCK/ROE\_ADD\_QUALIFIED/DIVIDEND\_TRAP/\*

\*  OperatingMarginFloor(2.8%)/EPS\_GROWTH\_QUALIFIED/PB\_UNDERVALUE/STRONG\_ADD前置條件\*

\*新增 PART W：動態門檻框架（CSP Capex + 滾動分位數 + 品質評分）\*

\*新增 PART Z：股息現金流優先設計哲學（2026-06-08）\*

\*v12 數據庫架構更新（2026-06-04）：\*

\*  - PART B.3 模組修改權限表新增現行數據庫保護規則\*

\*  - 2317\_master\_v8.csv / 2317\_daily\_price.csv → 唯讀，禁止Codex寫入\*

\*  - SKILL\_v12.md / 2317\_DATA\_GOVERNANCE\_SPEC.md → 唯讀，只有Owner可修改\*

\*  - 舊版數據庫（fundamentals\_COMPLETE.\*）→ 禁止使用，標注為舊版\*

\*  - 新增數據庫架構說明（現行v8 / 舊版 / 規格文件三層分類）\*

\*  - TASK\_TEMPLATE.md 同步更新（v2.0，新增ReadOnlyFiles概念）\*

\*  - EXECUTION\_GUARD.md 同步更新（新增新版數據庫唯讀保護）\*

\*如規格文件更新，本文件應同步修訂。\*

---

## PART AA：總經面動態提升優化機制（2026-06-13 新增）

### AA.0 優化背景

基於三大歷史事件回測（COVID 2020 / 俄烏 2022 / 關稅 2026），
發現原有總經面觸發機制存在四個系統性缺陷，本 PART 提供改進規則。

---

### AA.1 改進一：VIX 單日暴漲早期預警

```
問題：VIX 突破閾值時，股價已跌 5~10%（VIX 是落後指標）
改進：加入「VIX 單日暴漲 > 20%」早期預警機制

觸發條件：
  VIX_DailyChange_Pct > 20%
  → 觸發 VIX_SURGE_ALERT

VIX_SURGE_ALERT 規則：
  ① 總經面權重：當前值 + 5%（臨時提升）
  ② 顯示警示：「⚡ VIX 單日暴漲 XX%，市場情緒急劇惡化」
  ③ 禁止新資金投入（即使 PB 未達 BLOCK 線）
  ④ 啟動「多指標確認模式」：等待 3 個交易日確認是否升級

確認邏輯（3 個交易日後）：
  IF VIX 仍 > 25 → 升級為 M1-A（CAUTION）
  IF VIX 回落 < 20 → 解除 VIX_SURGE_ALERT
  IF VIX > 35 → 直接升級為 M1-B（SYSTEMIC）

歷史驗證：
  2026-06-05：VIX 從 15 → 21.51（+43.4%）
  → 可在股價 309 元時發出警示（比現有機制早 3 天）

actionable: false
```

---

### AA.2 改進二：多指標同步回落才降級

```
問題：VIX 回落但 WTI/Fed 升息概率仍上升，系統過早降級
改進：降級條件改為「多指標同步回落」

從 SYSTEMIC 降至 CAUTION（需同時滿足）：
  ① VIX 回落至 < 30（連續 5 個交易日）
  ② 且 WTI 回落至 < $95（或未觸發 WTI 警戒）
  ③ 且 Fed_Hike_Prob_YE 未繼續上升

從 CAUTION 降至 STATIC（需同時滿足）：
  ① VIX 回落至 < 20（連續 5 個交易日）
  ② 且 CAUTION 觸發項目 ≤ 1 項
  ③ 且無新增觸發項目

特殊保護：
  IF 降級後 7 天內任一指標再次觸發
  → 立即重新升級（無冷卻期）

歷史驗證：
  2026-04-30：VIX 回落至 22，但 WTI 仍在上升
  → 新機制：WTI 未同步回落，維持 CAUTION

actionable: false
```

---

### AA.3 改進三：PB 過熱獨立警示（不依賴 VIX）

```
問題：VIX 低時系統認為環境正常，但 PB 可能已極度過熱
改進：心理面（PB 過熱）觸發獨立警示，不依賴 VIX

PB_OVERHEAT_ALERT 觸發條件：
  IF PB_daily > PB_STRICT_BLOCK（2.115x）
  → 無論 VIX 多低，立即顯示「估值過熱警示」

PB_OVERHEAT_ALERT 規則：
  ① 顯示警示：「🔴 PB=XX.XXx 超過嚴格 BLOCK 線，估值極度過熱」
  ② 禁止新資金投入（強制 BLOCK）
  ③ 啟動 TRIM 評估流程
  ④ 心理面維度分數強制設為 0
  ⑤ Decision Header 顯示橙色邊框警示

解除條件：
  PB_daily 回落至 < PB_BLOCK_LINE（1.923x）連續 3 個交易日

歷史驗證：
  2026-05-29：VIX=15（低），但 PB=2.27x（超過嚴格 BLOCK）
  → 新機制：在 289 元發出過熱警示

actionable: false
```

---

### AA.4 改進四：Fed 累計升息門檻降低

```
問題：Fed 累計升息 150bp 才觸發 M2-B，反應過慢
改進：降低觸發門檻，提前預警

新門檻（改進後）：
  M2-A（升息週期啟動）：
    ① Fed_Rate 單次升息 ≥ 25bp
    ② 且 Fed_Hike_Prob_YE > 40%（原 50%）
    ③ 且 US_10Y > 3.5%（原 4.0%）
    → 總經面：20% → 28%

  M2-B（激進升息期）：
    ① 累計升息 ≥ 75bp（原 100bp）
    ② 且 Fed_Hike_Prob_YE > 60%（原 70%）
    ③ 且 US_10Y > 4.0%（原 4.5%）
    → 總經面：20% → 38%

  M2-C（升息+衰退風險）：
    ① M2-B 條件成立
    ② 且 US_GDP_QoQ < 0%
    → 總經面：20% → 45%

歷史驗證：
  2022-06-15：Fed 累計升息 150bp，股價已跌 -8.3%
  → 新機制：累計 75bp 時（約 2022-05）即觸發 M2-B
  → 預計提前 4~6 週發出警示

actionable: false
```

---

### AA.5 統計誠實聲明

```
N=3 個事件，樣本極少
統計信心 < 50%
以上為探索性改進，非確認性規則
需累積更多事件才能提升信心
所有改進標示 actionable: false
```

*PART AA 新增於 2026-06-13*
*基於三大歷史事件回測（COVID 2020 / 俄烏 2022 / 關稅 2026）*

