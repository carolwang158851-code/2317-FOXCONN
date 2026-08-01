# P1008 黑天鵝事件與回測引擎邏輯

- 報告日期：2026-06-29
- 適用系統：P1008 Hon Hai 戰略決策戰情室
- 回測政策版本：P2-QREVIEW-2026Q1-v1
- 治理狀態：研究說明文件，僅供決策參考
- 執行狀態：actionable:false

## 核心結論

戰情室面對黑天鵝事件的目的不是預測下一個價格，也不是判斷最低點或最高點，而是用同一套標準化邏輯檢查：目前資料是否可靠、風險是否已經足以傷害存股資產、原本的持有理由是否失效，以及是否需要啟動人工重審。

每一次黑天鵝事件的總經數據不同，但戰情室標準只能有一套。標準邏輯必須用 YES / NO / Option 路徑逐關判斷，避免在恐慌、樂觀或資訊不完整時任意改變規則。

最終輸出仍維持 HOLD / actionable:false。若需要改變戰情室邏輯，必須在事件後期用正式資料、回測表與 Owner 核准流程修正，而不是在事件當下臨時改規則。

## 戰情室的黑天鵝判斷樹

```flowchart
root: START<黑天鵝或重大突發事件>
START -> DATA{Gate 0：正式資料鏈完整且新鮮?}
DATA --NO：臨時/缺欄--> OBSERVE(盤中觀察模式)
OBSERVE --Final--> WAIT[中文註記；等待 Owner 或正式 CSV；禁止發布正式結論]
DATA --YES：正式 CSV--> MACRO{Gate 1：SYSTEMIC 或 VIX>=40?}
MACRO --YES：極端市場--> THESIS{Gate 2：持有主論點失效?}
MACRO --NO：未達極端--> FUSE{PB>=1.923 或 VIX>25?}
FUSE --YES：啟動保護--> REVIEW_A(人工重審 EIP)
REVIEW_A --Final--> POST_A[維持 HOLD；T+1/T+5/T+20 檢討；actionable:false]
FUSE --NO：風險可控--> HOLD_A[維持原判讀；記錄理由；actionable:false]
THESIS --YES：主論點失效--> DEFENSE_A(資產防護優先)
DEFENSE_A --Final--> OWNER_A[升級 Review Panel；要求 Owner 決策；系統不下單]
THESIS --NO：主論點仍成立--> LIQUIDITY{Gate 3：資金/流動性風險惡化?}
LIQUIDITY --YES：惡化--> DEFENSE_B(資產防護優先)
DEFENSE_B --Final--> OWNER_B[升級 Review Panel；要求 Owner 決策；系統不下單]
LIQUIDITY --NO：可承受--> REVIEW_B(人工重審 EIP)
REVIEW_B --Final--> POST_B[維持 HOLD；T+1/T+5/T+20 檢討；actionable:false]
```

中文備註：流程圖是判斷標準，不是交易流程。每個 YES / NO / Option 都必須有資料證據或 Owner 決策紀錄支撐。

## 判斷原則

| 原則 | 標準 | 中文說明 |
|---|---|---|
| 不預測 | 不猜最低點、反彈幅度或事件結束時間 | 戰情室只檢查風險與論點是否失效 |
| 不臨時改規則 | 黑天鵝當下不新增未核准公式 | 避免恐慌時改出錯誤邏輯 |
| 先保護資產 | 若風險足以傷害存股資產，先升級重審 | 目的不是賺短線，而是避免重大誤判 |
| 資料分層 | 正式 CSV、runtime snapshot、staging candidate 分開判讀 | 臨時資料只能觀察，不可發布正式結論 |
| 事後修正 | 事件後用 T+1/T+5/T+20/季度檢討修正邏輯 | 讓戰情室在每次事件後變得更可靠 |

## Gate 0：資料可信度關卡

第一關不是看股價，而是看資料能不能用。

| 判斷問題 | YES | NO / Option |
|---|---|---|
| 正式 CSV 是否存在且通過 schema/hash? | 進入正式判讀 | 停留 runtime snapshot，標示「臨時即時快照」 |
| 主要欄位是否完整? | 可計算 PB、PE、品質分、DIMAS、MIDR/MRD | 不補假分數，只保留風險提醒 |
| 資料是否新鮮? | 可提升判讀信心 | 信心度受限，需中文註記 |
| Owner 是否核准發布? | 可 append 正式 CSV 並更新 manifest | 候選資料不可進正式鏈 |

中文備註：如果 Gate 0 不通過，後面的圖表再漂亮也只能是觀察，不是正式決策輸出。

## Gate 1：黑天鵝與總經風險關卡

目前主程式條件：

```formula
isBlackSwan = RiskLevel === "SYSTEMIC" 或 VIX >= 40.0
```

另有熔斷保護條件：

```formula
shouldFuse = currentPB >= 1.923 或 VIX > 25.0
```

判斷邏輯：

| 數據狀態 | 戰情室處理 | 中文說明 |
|---|---|---|
| SYSTEMIC 或 VIX>=40 | 顯示極端市場提示，重做心理與紀律評估 | 不沿用平靜市場下的判斷 |
| VIX>25 但未達 40 | 啟動熔斷保護與人工重審 | 高波動但不等於主論點失效 |
| PB>=1.923 | 估值安全邊際下降，要求重審 | 不是賣出指令 |
| RiskLevel=NORMAL 且 VIX 未升高 | 維持原判讀 | 仍需觀察資料新鮮度 |

## Gate 2：主論點是否失效

黑天鵝事件真正要檢查的是「原本持有理由是否被破壞」，不是股價有沒有跌。

| 判斷問題 | YES：主論點受損 | NO：主論點仍成立 |
|---|---|---|
| AI 伺服器需求是否被重大下修? | 升級 Review Panel，要求 Owner 判斷 | 保留中期觀察 |
| 毛利率或營益率假設是否失效? | 降低估值容忍度，要求回測重審 | 保留品質分判讀 |
| EPS / ROE 是否跌破支撐條件? | 動態 PB 門檻下修 | 維持原門檻但註記 |
| 公司財報或法說是否改變長期敘事? | 新政策版本不得沿用舊回測 | 沿用但需季度驗證 |

中文備註：股價下跌本身不是主論點失效；基本面、產業面、總經面與公司敘事共同改變，才需要修正戰情室標準。

## Gate 3：資產防護關卡

戰情室服務的是存股資產風險控管，不是短線預測。因此即使主論點未失效，只要風險足以造成永久性或長期傷害，也必須升級處理。

| 風險 | 判斷方向 | 處理邏輯 |
|---|---|---|
| 流動性風險 | 外資、成交量、信用或市場流動性惡化 | 提高重審等級，不自動交易 |
| 利率與折現率風險 | US_10Y、Fed 機率或 DXY 壓力升高 | DIMAS 加分，MIDR 保守折減 |
| 估值風險 | PB 高於阻斷參考線 | 禁止追價，維持 HOLD |
| 資料風險 | 臨時資料或 L3 推論佔比過高 | 降低判讀信心，要求 Owner 決策 |

## Fed 資料在黑天鵝邏輯中的使用邊界

黑天鵝與回測引擎會使用 Fed 相關欄位，但兩種 Fed 資料的性質不同：

| 欄位 | 戰情室定義 | 來源層級 | 黑天鵝邏輯用途 |
|---|---|---|---|
| Fed_Rate | FOMC 目標區間中位數 | FRED `DFEDTARU` / `DFEDTARL`，公式 `(上限 + 下限) / 2` | 判斷政策利率水準與折現率壓力 |
| Fed_Hike_Prob_YE | 年底升息機率 | CME FedWatch 市場隱含機率；connector 未穩定前可沿用正式 CSV 並標示 | 只提高重審頻率，不可單獨產生交易規則 |

中文備註：`Fed_Hike_Prob_YE` 不是 Fed 官方發布資料，也不是黑天鵝判斷的唯一依據。若 CME connector 失敗或沿用正式 CSV 最近值，UI 與報告必須標示中文註記，並維持 actionable:false。

## Gate 4：決策後檢討

黑天鵝事件不能只在當天判斷，必須在事件後期用資料檢查原決策是否仍合理。

| 時點 | 檢討問題 | 可能處理 |
|---|---|---|
| T+1 | 事件是否仍在擴大? 資料是否需要更新? | 更新 runtime snapshot，維持中文註記 |
| T+5 | 市場風險是否回落? VIX / US10Y / DXY 是否改善? | 調整 Review Panel 風險文字，不改正式規則 |
| T+20 | 基本面或產業需求是否出現新證據? | 準備季度重審材料 |
| 下一季財報 | EPS、ROE、OPM、AI_Revenue_Pct 是否支持原假設? | Owner 核准後修正門檻、權重、SOP 與回測 |

中文備註：事件後檢討不是推翻當時決策，而是檢查當時標準是否足以保護資產。

## 回測政策如何被黑天鵝考驗

目前回測政策：

| 欄位 | 值 |
|---|---|
| version | P2-QREVIEW-2026Q1-v1 |
| effectiveQuarter | 2026Q1 |
| status | OBSERVATION_ONLY |
| statusZh | 季度重審觀察版 |
| sourceZh | 2317_master_v9.csv / RULE_STATUS_MANIFEST / Owner quarterly review |

目前主程式列出的重審條件：

- 新一季財報正式 CSV 發布。
- 重大事件改變 AI 伺服器需求或毛利率假設。
- 總經風險升至 SYSTEMIC。
- Owner 核准新估值門檻或 KPI 權重。

中文備註：黑天鵝不是一次性事件，而是壓力測試。每次事件都會檢查目前門檻、權重、資料來源與回測邏輯是否仍能保護資產。

## 動態 PB 門檻仍只能是觀察

目前主程式先用 AI_Revenue_Pct 建立動態門檻：

```formula
addPb   = 1.10 + AI_Revenue_Pct * 0.005
blockPb = 1.60 + AI_Revenue_Pct * 0.015
```

再依獲利品質修正：

| 條件 | 修正 | 中文說明 |
|---|---|---|
| EPS YoY >= 10 且 ROE >= 11.5 | addPb +0.05、blockPb +0.05 | 獲利支撐較強，估值容忍度小幅提高 |
| EPS YoY < 0 或 ROE < 10 | addPb -0.05、blockPb -0.10 | 獲利轉弱，估值容忍度下降 |
| OPM < 3 | blockPb -0.05 | 營益率偏低，限制高估區間 |

門檻上下限：

| 門檻 | 下限 | 上限 |
|---|---:|---:|
| addPb | 0.95 | 1.55 |
| blockPb | 1.55 | 2.35 |

中文判讀：這些門檻只用來觀察歷史列和最新列是否落在合理區間，不會產生 BUY、SELL、TRIM 或 ADD 指令。

## 戰情室邏輯修正循環

```flowchart
root: EVENT<事件後正式檢討>
EVENT -> TEST{現行判斷是否保護資產?}
TEST --YES：風險被控制--> KEEP[維持政策版本；補充事件紀錄]
TEST --NO：誤判或保護不足--> ANALYZE{問題來自哪裡?}
ANALYZE --Option：資料缺口--> DATAFIX[新增欄位、connector 或中文資料註記]
ANALYZE --Option：門檻錯誤--> RULEFIX[提出門檻或權重修正案]
ANALYZE --Option：文字誤導--> UIWRITE[修正 UI / SOP / 研報解釋]
DATAFIX --Final--> OWNER_REVIEW[Owner 核准後更新 manifest、回測與 SOP]
RULEFIX --Final--> OWNER_REVIEW2[Owner 核准後更新政策版本與回測]
UIWRITE --Final--> OWNER_REVIEW3[Owner 核准後更新說明文件]
```

中文備註：戰情室是反覆修正的風險判讀系統，不是一次寫死的預測模型。

## 決策者應看什麼

1. 先確認資料狀態：正式 CSV、runtime snapshot、staging candidate 不可混用。
2. 再確認是否觸發 SYSTEMIC、VIX>=40、PB>=1.923 或 VIX>25。
3. 再檢查主論點是否失效，而不是只看股價波動。
4. 若主論點未失效但風險上升，輸出應是 HOLD / 重審 / actionable:false。
5. 事件後必須按 T+1、T+5、T+20、下一季財報檢討原決策是否仍合理。

本報告不提供買賣建議，不修改正式 CSV，不解除 KEEP_DISABLED。actionable:false。
