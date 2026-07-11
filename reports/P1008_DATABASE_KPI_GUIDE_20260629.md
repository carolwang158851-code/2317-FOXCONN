# P1008 數據庫架構與 KPI 說明

- 報告日期：2026-06-29
- 適用系統：P1008 Hon Hai 戰略決策戰情室
- 治理狀態：研究說明文件，僅供決策參考
- 執行狀態：actionable:false

## 核心結論

戰情室不是單一 CSV 圖表頁，而是「正式資料鏈、候選資料鏈、臨時快照、規則狀態、判讀模型」共同組成的決策輔助系統。正式判讀必須優先採用已核准的正式 CSV；盤中或臨時更新只能做觀察，不可直接覆寫正式資料。

本報告用目前主程式邏輯說明資料庫架構、KPI 計算方式與中文判讀標準。若未來程式公式調整，本報告也必須同步更新。

## 資料鏈分層

| 層級 | 代表檔案或來源 | 戰情室用途 | 是否可直接正式發布 | 中文狀態 |
|---|---|---|---|---|
| 正式 CSV | data/2317_master_v9.csv、data/2317_daily_price.csv、data/macro_snapshot.csv | 主畫面 KPI、估值、總經與品質判讀 | 可，但只能經 Owner publish 流程 | 正式資料 |
| 旁路觀察 CSV | data/macro_event_observations.csv、data/fx_trend_observations.csv | 新聞/黑天鵝、FX 趨勢、來源稽核與反證材料 | 可 append，但只能經 Owner publish 流程，且 Actionable=false | 觀察資料 |
| 權威清單 | data/CSV_AUTHORITY_MANIFEST.json、RULE_STATUS_MANIFEST | SHA-256、schema、規則狀態與 actionable:false 檢查 | 不直接作數據，但決定可信度 | 權威檢核 |
| 候選資料 | staging/YYYY-MM-DD/*_candidate.csv、DRY_RUN.json、DRY_RUN.md | 發布前檢查、缺欄提示、Owner 審核 | 不可直接當正式資料 | 發布候選 |
| 臨時快照 | runtime/runtime_snapshot.json | 盤中或臨時觀察、Market Intelligence | 不可覆寫正式 CSV | 臨時即時快照 |
| 使用者整理資料 | USER_CURATED_WEB_DATA / L3 | AI 營收占比、產業觀察、部分低頻總經資料 | 需中文註記與 Owner 核准 | 整理觀察 |

## append-only 的意思

正式 CSV 的「append-only」代表只能在 Owner 核准後新增日期或季度列，不允許 UI 按鈕或抓取器直接覆寫既有正式列。若發現既有列有錯，應走「歷史資料格式修正 / manifest 更新」流程，由 Owner 核准後留下原因、修正前後值與 hash 更新紀錄。

中文備註：這不是限制戰情室更新，而是防止臨時資料、網頁錯值或半成品候選檔污染正式判讀。

## 旁路 CSV 不等於正式 macro_snapshot

`macro_snapshot.csv` 維持 18 欄，負責正式 Market Intelligence 基準。新聞、黑天鵝、地緣政治、Fed/CPI/油價事件不再塞入 `RiskNote`，而是進入 `macro_event_observations.csv`；TWD/USD、DXY、JPY/USD、Fed/BOJ 利差與 FX 壓力趨勢進入 `fx_trend_observations.csv`。

旁路 CSV 的定位是「反證與重審提示」。首頁可以顯示最新 FX 趨勢與事件觀察，週/月戰報可以引用作事件反證表與 FX 趨勢圖，但它們不得改 HOLD 主 IC、不得啟用 KEEP_DISABLED 規則，也不得輸出買賣建議。所有旁路列的 `Actionable` 必須是 `false`。

## 新聞掃描時窗與資料判讀

固定新聞掃描的時窗分成三層，不能混用：

| 用途 | 建議時窗 | 資料定位 | 可否改正式判讀 |
|---|---:|---|---|
| 即時保護 | 6-12 小時 | 盤中、夜間、國際事件的 staging observation | 否，只能提示 |
| 主要判斷 | 72 小時 | 降低單一標題雜訊，檢查多來源與市場佐證 | 否，只能標示 WATCH / REVIEW_REQUIRED |
| 戰報稽核 | 7 天 | 事件反證表、未結案事件、Owner ack 追蹤 | 否，但可提出 Owner 重審或修正建議 |

事件分級不等於交易訊號：

- `OBSERVE`：單一來源、影響不明，保留 7 天供戰報追蹤。
- `WATCH`：多來源或可能影響鴻海供應鏈、AI server、Apple、匯率或利率，首頁提示 3 天或直到 Owner ack。
- `REVIEW_REQUIRED`：官方或多來源確認且直接影響營運、估值壓力或資料假設，首頁顯示 `HOLD_UNDER_REVIEW`，未 Owner ack 前不得自動過期。

中文備註：6-12 小時是保護決策者的即時提示窗；72 小時是重大性判斷的降噪窗；7 天是戰報防漏網窗。三者都不會讓旁路 CSV 升格為正式 `macro_snapshot.csv`。

## KPI 一：PB 估值

公式：

```formula
PB = 收盤價 Close / 每股淨值 BVPS
```

範例：

```formula
2026-06-25 Close 252.0 / BVPS 127.12 = 1.9824
三位小數顯示為 1.982
```

中文判讀：

- PB 用來回答「股價落在歷史估值帶的哪個位置」。
- PB 不是買賣指令；正式規則目前維持 KEEP_DISABLED。
- 若資料來自臨時快照，UI 必須顯示「臨時即時快照，尚未核准發布」。

## KPI 二：本益比 PE

公式：

```formula
PE = 收盤價 Close / TTM EPS
```

範例：

```formula
Close 248.5 / TTM EPS 14.15 = 17.56x
```

中文判讀：

- PE 只適合做相對趨勢觀察，不能單獨判斷便宜或昂貴。
- 若 EPS 來自估算或季報推導，需標示資料層級與中文備註。

## KPI 三：現金殖利率

公式：

```formula
現金殖利率 = CashDividend / Close * 100
```

範例：

```formula
CashDividend 7.17 / Close 248.5 * 100 = 2.89%
```

中文判讀：

- 殖利率會受股價變動影響，不能只看配息金額。
- 戰情室用殖利率與美國 10 年期殖利率比較，協助判斷資金吸引力。

## KPI 四：品質分

目前主程式公式：

```formula
ROE 分數  = min(ROE / 15 * 40, 40)
ROIC 分數 = min(ROIC / 15 * 40, 40)
OPM 分數  = min(OPM / 5 * 20, 20)
品質分    = round(ROE 分數 + ROIC 分數 + OPM 分數)
```

範例：

```formula
ROE 11.52%  -> 30.7 / 40
ROIC 13.70% -> 36.5 / 40
OPM 2.67%   -> 10.7 / 20
合計 77.9，四捨五入為 78/100
```

中文判讀：

- 品質分回答「獲利是否有足夠品質支撐估值」。
- 品質分不是股價目標價，也不是交易分數。
- 若 ROE、ROIC 或 OPM 任一缺失，品質分不可硬補假分數。

## KPI 五：DIMAS 總經風險 CAP

目前啟用的風險條件：

| 風險項 | 加分方向 | 中文意義 |
|---|---:|---|
| US_10Y_Yield | 越高加分越多 | 資金折現率壓力 |
| Fed_Hike_Prob_YE | 越高加分越多 | 聯準會政策壓力 |
| VIX | 越高加分越多 | 市場波動與恐慌壓力 |
| 股價距高估參考價 | 越高加分越多 | 估值安全邊際下降 |
| EPS YoY | 越低加分越多 | 成長支撐轉弱 |

中文判讀：

- CAP 越高，代表風險條件越多，不代表系統會自動賣出。
- 目前畫面沿用 CAP 風險刻度呈現；正式解讀應看中文級距：正常、低度觀察、謹慎觀察、高度謹慎、系統性風險。
- DIMAS 只影響風險提醒與重審提示，actionable:false。

Fed 欄位來源規則：

| 欄位 | 正式定義 | 來源規則 | 中文備註 |
|---|---|---|---|
| Fed_Rate | FOMC 目標區間中位數 | FRED `DFEDTARU` 與 `DFEDTARL`，公式 `(上限 + 下限) / 2` | 可作正式 macro 欄位；連線失敗才沿用正式 CSV 並註記 |
| Fed_Hike_Prob_YE | 年底升息機率 | CME FedWatch 市場隱含機率；connector 未穩定前可沿用正式 CSV | 不是 Fed 官方發布資料，只供風險觀察 |

中文備註：`Fed_Rate` 與 `Fed_Hike_Prob_YE` 不可混用。前者是官方目標利率區間中位數；後者是市場對年底政策路徑的隱含機率。

## KPI 六：MRD 市場反應偏差

MRD 用來觀察「市場是否過度反應或超跌」，目前條件包含：

- 最近 80 筆日資料距高點跌幅。
- 現金殖利率相對 US_10Y 的超額殖利率。
- 前季股價報酬。
- EPS YoY 是否提供基本面支撐。

中文判讀：

- MRD 高分代表可能有超跌觀察價值。
- 若股價本身已強勁上漲，MRD 不會放寬門檻。
- MRD 不產生加碼指令，只調整觀察門檻。
- UI 主畫面不得以 MRD 數值作主標題；主畫面只顯示中文結論，例如「估值偏離觀察：未出現明顯超跌」。
- MRD 分數、觸發訊號與公式拆解放在 UI 展開區；戰報則放在附錄或稽核明細。

## KPI 七：MIDR 均值回歸觀察

目前權重：

| 維度 | 權重 | 主程式來源 | 中文說明 |
|---|---:|---|---|
| YA 殖利率吸引力 | 20% | CashDividend、Close、US_10Y | 股息相對債券是否有吸引力 |
| VAL PB 相對估值 | 25% | PB 參考區間 | 估值是否接近高估或低估 |
| FRV 營收/獲利動能 | 20% | EPS YoY | 成長是否支撐估值 |
| RTM 籌碼/趨勢 | 10% | 外資趨勢或替代欄位 | 資金面方向 |
| MDR 總經折現率 | 25% | US_10Y、Fed 機率 | 折現率壓力 |

中文判讀：

- MIDR 小於 -0.25 為偏空觀察，小於 -0.15 為謹慎觀察，其餘為中性觀察。
- CAUTION 會套用 0.90 折減，SYSTEMIC 會套用 0.80 折減。
- MIDR 是觀察引擎，不是交易引擎。
- UI 主畫面不得以 MIDR 數值作主結論；主畫面只顯示「統計分數偏謹慎、需提高重審頻率」等決策語言。
- MIDR 總分、權重、各維度貢獻、門檻與資料來源放在 UI 展開區；戰報主文只寫解讀，數值放附錄。

### MIDR / MRD 顯示規則

| 使用位置 | 顯示方式 | 範例 |
|---|---|---|
| 戰情室主畫面 | 中文結論，不顯示工程標題 | 估值偏離觀察：未出現明顯超跌，統計分數偏謹慎 |
| UI 展開區 | 詳細數值、公式、門檻、來源層級 | MRD=16.5；MIDR=-0.240；actionable:false |
| 戰報主文 | 稽核解讀與 Owner 動作 | 不追價；維持 HOLD；下期重審 PB、ROE、US10Y、Fed 機率 |
| 戰報附錄 | 可追溯公式與明細 | MRD 訊號、MIDR 權重、資料來源、限制 |

中文備註：`MRD=16.5` 代表沒有明顯超跌，`MIDR=-0.240` 代表統計分數偏謹慎但未跌破偏空門檻。兩者只能支持「提高觀察與重審頻率」，不能支持加碼、減碼或賣出。

## KPI 八：五維度雷達與加權分

目前五維度：

| 維度 | 權重 | 分數來源 | 缺值處理 |
|---|---:|---|---|
| 基本面 | 35% | 品質分 | 缺值不補 |
| 產業面 | 25% | AI_Revenue_Pct / 50% 換算 | L3 整理資料需註記 |
| 籌碼面 | 5% | ForeignHoldChange 或 ForeignHoldTrend | 缺值不補 |
| 總經面 | 20% | 100 - DIMAS CAP * 8 | 缺值不補 |
| 估值面 | 15% | PB 參考區間換算 | 缺值不補 |

中文判讀：

- 雷達圖不是官方原始指標，而是模型分數。
- 若任一維度缺值，戰情室不得補假數據，應明確顯示資料不足。
- 加權分只用來說明綜合狀態，不會啟用交易規則。

2026-06-30 範例：

| DIMAS 條件 | 觸發 | CAP 加分 |
|---|---|---:|
| US_10Y_Yield = 4.372% | `>= 4.2%` | 2 |
| Fed_Hike_Prob_YE = 72.0% | `>= 70%` | 3 |
| VIX = 17.65 | 未達 18 | 0 |
| 股價距高估參考價 | 未達 5% | 0 |
| EPS YoY = 17.5% | `<= 25%` | 1 |
| 合計 | DIMAS CAP | 6 |

因此五維度的「總經面」推導分不是 Market Intelligence 的 56 分，而是：

```text
總經面 = 100 - DIMAS CAP * 8
       = 100 - 6 * 8
       = 52 分
```

中文備註：Market Intelligence 的總經壓力分是五個市場壓力因子加權；五維度雷達的總經面是 DIMAS CAP 反向換算，兩者用途不同，不能直接互相替代。

## KPI 九：判讀信心

目前主程式判讀信心來源：

| 構成 | 滿分 | 說明 |
|---|---:|---|
| 基礎分 | 18 | 系統最低可判讀基礎 |
| 權威檢核 | 34 | authority、rules、daily、macro 是否通過 |
| 新鮮度 | 24 | master、daily、macro 的資料日期狀態 |
| 欄位完整度 | 22 | PB、price、EPS、殖利率、ROE、US10Y、VIX、品質分 |
| 一致性 | 12 | 異常列越多扣分越多 |
| 扣分 | 依狀態 | runtime、發布阻斷、SYSTEMIC 風險 |

狀態上限：

| 資料狀態 | 信心上限 | 中文說明 |
|---|---:|---|
| READY 正式資料鏈完整 | 88 | 高信心，但仍保留人工審查空間 |
| RUNTIME_SNAPSHOT 臨時快照 | 72 | 可盤中觀察，但需註記 |
| STALE_DATA 過期資料 | 68 | 可回顧，但不可當正式新判讀 |
| INSUFFICIENT_DATA 資料不足 | 55 | 僅保留風險提醒 |

中文備註：上限 88 是設計保守值，代表即使正式資料鏈完整，戰情室仍不是自動決策或交易系統。

## 哪些是推論資料

| 欄位或模組 | 資料性質 | 是否官方原始值 | 中文備註 |
|---|---|---|---|
| AI_Revenue_Pct | USER_CURATED_WEB_DATA / L3 | 否 | 產業與法說資訊整理，需 Owner 接受 |
| Fed_Rate | FRED 官方序列推導欄位 | 是，FRED/FOMC 目標區間 | `DFEDTARU` 與 `DFEDTARL` 中位數 |
| Fed_Hike_Prob_YE | CME FedWatch 市場隱含機率 | 否 | 不是 Fed 官方發布資料；connector 未穩定時需標示沿用 |
| MIDR / MRD | 模型推論 | 否 | 由正式欄位推導，不是外部公告 |
| 五維度雷達分 | 模型推論 | 否 | 用於說明，不作交易 |
| 判讀信心 | 系統治理分數 | 否 | 反映資料鏈完整度與狀態 |

## 決策者閱讀順序

1. 先看資料狀態：正式資料、臨時快照、過期或資料不足。
2. 再看系統結論：HOLD、信心度與中文備註。
3. 再看證據清單：直接證據、推論、反向證據、失效條件。
4. 最後看 KPI 與圖表：確認結論是否由資料支持。

本報告不提供買賣建議，不改寫正式 CSV，不解除 KEEP_DISABLED。actionable:false。
# P1008 Scheduled News Scan v1 Addendum

`P1008_4_NEWS_SCAN.bat` and `tools/warroom_news_scanner_v1.py` add an observation-only event layer. The scanner writes `runtime/warroom_news_scan_snapshot.json` and, only when qualified events exist, `staging/YYYY-MM-DD/macro_event_observations_candidate.csv`.

This layer is not `macro_snapshot.csv`, not a KPI override, and not a decision engine. It may display `HOLD_UNDER_REVIEW` in the homepage when `REVIEW_REQUIRED` exists, but it must keep `Actionable=false`, must not change HOLD, and must not enable KEEP_DISABLED rules.

`data/NEWS_SCAN_SOURCE_MANIFEST.json` is the source registry. v1 allows local Owner/manual input and keeps official, public-market, and media network connectors as `CONNECTOR_PENDING` until separately approved.

## P1008 定期戰報 / UI Manifest 補充

`P1008_5_GENERATE_REPORTS.bat` 與 `tools/warroom_periodic_report_v1.py` 會從既有正式 CSV、旁路 CSV 與 runtime snapshot 產生本機戰報產物。產生器會寫入：

- `reports/generated/P1008_DAILY_REPORT_YYYYMMDD.md`
- `reports/generated/P1008_DAILY_REPORT_YYYYMMDD.html`
- `reports/P1008_REPORT_MANIFEST.json`
- `runtime/warroom_report_manifest.json`
- `runtime/warroom_event_review_state.json`

這些檔案是戰報與 runtime 治理輸出，不是正式 KPI 輸入。它們不得用來覆寫 `macro_snapshot.csv`、`2317_daily_price.csv`、`2317_master_v9.csv`、`macro_event_observations.csv` 或 `fx_trend_observations.csv`。

首頁整合規則：新 UI 是唯一啟動窗口。6 大系統卡片只在首頁內摘要資料；只有 HOLD 主 IC、事件 / FX 明細、Owner publish 與資料治理可透過固定舊 UI 錨點下鑽。最新戰報、SOP 與研報庫屬於 manifest-backed 導覽入口，維持 `actionable:false`。
