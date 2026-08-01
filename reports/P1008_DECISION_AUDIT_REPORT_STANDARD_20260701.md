# P1008 戰報輸出標準：持股風險與決策邏輯稽核

- 報告日期：2026-07-01
- 適用系統：P1008 Hon Hai 戰略決策戰情室
- 文件定位：週/月戰報輸出標準
- 治理狀態：研報產品化規格，供 SOP 與研報庫引用
- 執行狀態：actionable:false

## 核心結論

P1008 戰報的目的不是預測股價，也不是把戰情室數據整理成漂亮圖表。每次戰報都應該回答一個更重要的問題：

**目前持股風險是否仍可承受，且戰情室原本的決策邏輯是否仍然有效？**

因此，戰報是「持股風險與決策邏輯稽核報告」。主程式負責即時診斷，戰報負責定期檢查診斷邏輯有沒有被新財報、新總經環境、產業變化或黑天鵝事件挑戰。

## 戰報必答五問

| 問題 | 判讀目的 | 必要證據 |
|---|---|---|
| 1. 目前持股風險是否比上一期升高？ | 確認風險方向，不只看單日股價 | PB、PE、VIX、US10Y、DXY、資料品質 |
| 2. 現行 HOLD / 觀察邏輯是否仍被數據支持？ | 檢查原本持有理由是否仍成立 | EPS、ROE、ROIC、OPM、AI 營收占比 |
| 3. 哪些 KPI 或總經條件正在挑戰原本判斷？ | 找出風險惡化來源 | KPI 變化、總經五要素、反證清單 |
| 4. 若發生黑天鵝或財報惡化，現有規則是否能及時重審？ | 檢查決策樹與保護機制是否有效 | 黑天鵝 Gate、熔斷條件、Owner 重審紀錄 |
| 5. 戰情室邏輯是否需要修正，還是只需維持觀察？ | 形成可執行的治理結論 | 規則命中矩陣、修正建議、資料狀態 |

中文備註：這五個問題是戰報的最低輸出契約。若任一問題沒有可追溯資料，戰報必須標示為觀察版，不得稱為正式戰報。

## 三層主結論

每份戰報開頭必須用三層結論呈現，不應讓決策者先閱讀大量圖表才找答案。

| 層級 | 允許值 | 中文說明 |
|---|---|---|
| 持股風險狀態 | 可承受 / 升高需觀察 / 需重審 | 回答資產風險是否正在惡化 |
| 決策邏輯狀態 | 有效 / 需監控 / 需修正 / 資料不足 | 回答戰情室原邏輯是否仍可靠 |
| Owner 動作 | 不變更 / 補資料 / 重審門檻 / 修正規則 | 回答人工治理下一步 |

### 輸出狀態碼

| 狀態碼 | 使用條件 | 報告輸出 |
|---|---|---|
| `LOGIC_VALID` | 資料鏈完整，主要 KPI 與原結論一致 | 維持原邏輯，列出支持證據 |
| `WATCH_REQUIRED` | 風險升高但尚未推翻主論點 | 提高觀察頻率，列出接近門檻的 KPI |
| `REVIEW_REQUIRED` | 關鍵風險或資料註記足以要求人工判斷 | 要求 Owner 重審，不自動修規則 |
| `REVISION_REQUIRED` | 回測、財報或黑天鵝檢討證明原規則不足 | 提出規則修正案，需 Owner 核准 |
| `DATA_BLOCKED` | 正式 CSV、schema、hash 或核心欄位不足 | 不輸出正式判斷，只能產生觀察版 |

中文備註：狀態碼是治理輸出，不是交易訊號。所有狀態仍維持 `actionable:false`。

## 戰報決策樹

```flowchart
root: START<本期戰報開始>
START -> DATA{正式 CSV 與 manifest 是否可用?}
DATA --NO：資料不足--> BLOCK(DATA_BLOCKED：觀察版戰報)
BLOCK --Final--> OWNER_DATA[Owner 補資料或重新發布；不得輸出正式判斷]
DATA --YES：資料鏈完整--> RISK{持股風險是否升高?}
RISK --NO：風險未升高--> LOGIC{HOLD / 觀察邏輯仍被支持?}
LOGIC --YES：仍支持--> VALID(LOGIC_VALID：維持原邏輯)
VALID --Final--> KEEP[保留目前規則；列支持證據；actionable:false]
LOGIC --NO：支持不足--> REVIEW(REVIEW_REQUIRED：Owner 重審)
REVIEW --Final--> OWNER_REVIEW[檢查假設、門檻與反證；不自動交易]
RISK --YES：風險升高--> THESIS{持股主論點是否受損?}
THESIS --NO：主論點未失效--> WATCH(WATCH_REQUIRED：提高觀察)
WATCH --Final--> WATCH_LIST[列接近門檻 KPI；設定下期追蹤]
THESIS --YES：主論點受損--> RULE{現行規則是否足以保護資產?}
RULE --YES：規則足夠--> REVIEW2(REVIEW_REQUIRED：人工重審)
RULE --NO：規則不足--> REVISION(REVISION_REQUIRED：提出修正案)
REVISION --Final--> OWNER_RULE[Owner 核准後才能改 KPI 權重、門檻或資料源]
```

中文備註：此流程圖是戰報撰寫與治理流程，不是下單流程。戰報只指出是否需要維持、觀察、重審或修正邏輯。

## 六大診斷系統

戰報應像體檢報告一樣，把數據先歸入診斷系統，再匯總成結論。

| 診斷系統 | 主要 KPI | 報告要回答 |
|---|---|---|
| 基本面健康 | EPS、ROE、ROIC、OPM、營收動能 | 公司獲利能力是否仍支撐原持股理由？ |
| 估值壓力 | PB、PE、河流圖、MRD、MIDR | 估值是否已讓安全邊際變薄？ |
| 股利與現金流 | 現金股利、殖利率、自由現金流 | 持有期間的現金流防禦力是否足夠？ |
| 總經與匯率 | USD/TWD、DXY、VIX、US10Y、Fed、油價、JPY/USD、Fed/BOJ 利差、FX sidecar | 外部環境是否要求提高重審頻率？ |
| 產業與 AI 動能 | AI 營收占比、CSP Capex、產業需求、法人預期 | 成長敘事是否仍支持中期判斷？ |
| 資料可信度 | 正式 CSV、runtime、staging、manifest、中文註記 | 本期結論能否被正式資料鏈支撐？ |

中文備註：`MIDR / MRD` 只能作為估值壓力系統的輔助證據，不可成為戰報主標題或三層主結論。戰報主文應使用決策者可理解的語言，例如「估值偏離觀察：未出現明顯超跌，統計分數偏謹慎」。詳細數值、權重、公式、門檻與來源層級放在附錄或稽核明細，並維持 `actionable:false`。

## 圖文輸出規格

| 圖表 | 用途 | 不可取代的結論 |
|---|---|---|
| 綜合診斷雷達圖 | 顯示六大診斷系統強弱 | 哪個系統拖累總結論 |
| PB / PE 河流圖 | 顯示估值區間與歷史位置 | 目前是否不適合追價 |
| KPI 變化瀑布圖 | 說明判讀信心上升或下降來源 | 哪些 KPI 改變本期結論 |
| FX 趨勢圖 | 呈現 TWD/USD、DXY、JPY/USD、Fed/BOJ 利差與 FX 壓力 | 匯率壓力是否只需觀察、或需要 Owner 重審 |
| 規則命中矩陣 | 檢查 KEEP_DISABLED、重審門檻、黑天鵝 Gate | 哪些規則已觸發或接近觸發 |
| 事件反證表 | 列出新聞、黑天鵝、地緣政治、Fed/CPI/油價事件 | 哪些證據正在挑戰主論點，且是否僅為 OBSERVE / WATCH / REVIEW_REQUIRED |
| Owner 待決表 | 彙整人工核准、補資料、修規則事項 | 下一步誰要決定什麼 |

中文備註：圖表不是裝飾。每張圖都必須直接支撐一個文字結論，並附資料日期、來源層級與 `actionable:false`。

## 戰報章節模板

每份週/月戰報應維持下列順序：

1. 本期稽核結論
2. 持股風險體檢
3. 決策邏輯檢查
4. 反證與黑天鵝測試
5. 修正建議清單
6. Owner 待決事項
7. 附錄：CSV 日期、Evidence ID、公式、資料狀態中文註記

反證與黑天鵝測試章節必須優先引用 `macro_event_observations.csv`；匯率章節可引用 `fx_trend_observations.csv` 生成 FX 趨勢圖。兩者都屬旁路觀察資料，不等於正式 `macro_snapshot.csv`，不得直接改 HOLD 或輸出買賣。

### 事件時間差保護

戰報不是第一道事件防線。固定新聞掃描與首頁提示負責即時保護，戰報負責檢查是否有漏網或未結案事件。

| 檢查項 | 最低要求 |
|---|---|
| 即時事件回看 | 彙整最近 6-12 小時掃描出的候選事件，標示是否已進首頁提示。 |
| 72 小時重大性檢查 | 對最近 72 小時 `WATCH / REVIEW_REQUIRED` 事件檢查多來源、官方來源、市場佐證與鴻海直接關聯。 |
| 7 天防漏網檢查 | 對最近 7 天事件建立反證表，列出未 Owner ack、已 stale、已解除、需重審四種狀態。 |
| Owner ack | `REVIEW_REQUIRED` 未被 Owner ack 前，不得在戰報中視為解除；只能列為 Owner 待決事項。 |

若首頁曾顯示 `HOLD_UNDER_REVIEW`，本期戰報必須回答三件事：事件是否解除、是否已反映在 KPI / FX / 市場資料、原 HOLD 邏輯是否仍有效。沒有完成這三項，戰報狀態不得標示 `LOGIC_VALID`。

每個章節都應採用同一個寫法：

```formula
結論 -> 證據 -> 解讀 -> 限制 -> Owner 動作
```

| 欄位 | 說明 |
|---|---|
| 結論 | 一句話說明本章判斷 |
| 證據 | CSV 欄位、Evidence ID、資料日期 |
| 解讀 | 為什麼這個數據會影響持股風險或決策邏輯 |
| 限制 | 沿用值、L3 推論、runtime snapshot 或資料缺口 |
| Owner 動作 | 不變更、補資料、重審門檻或修正規則 |

### 附錄最低內容

若本期使用 `MIDR / MRD` 作為估值風險輔助觀察，附錄至少需列出：

| 項目 | 必填內容 |
|---|---|
| MRD | 分數、觸發訊號、是否顯示超跌、中文判讀 |
| MIDR | 總分、權重、各維度貢獻、門檻區間 |
| 資料來源 | 正式 CSV 衍生、runtime 觀察、或人工註記 |
| 限制 | 僅供估值風險觀察，不產生加碼、減碼或賣出指令 |
| Owner 動作 | 是否提高重審頻率、是否需要修公式或補資料 |

## 正式版與觀察版邊界

| 報告版本 | 使用資料 | 標題要求 | 可輸出內容 |
|---|---|---|---|
| 正式戰報 | 正式 CSV、通過 manifest/hash、Owner 已核准 | 可標示正式戰報 | 可給出 `LOGIC_VALID`、`WATCH_REQUIRED`、`REVIEW_REQUIRED` |
| 觀察版戰報 | runtime snapshot、staging candidate、沿用欄位較多 | 必須標示觀察版 | 只能提示風險與待補資料 |
| 修正建議稿 | 事件後檢討或回測發現規則不足 | 必須標示需 Owner 核准 | 可提出 `REVISION_REQUIRED`，但不可直接改規則 |

中文備註：runtime snapshot 可以提升即時觀察能力，但不能直接提升為正式戰報結論。

## 最低驗收標準

一份合格戰報必須同時滿足：

- 首屏可看出持股風險狀態、決策邏輯狀態與 Owner 動作。
- 五個必答問題都有明確答案。
- 每個修正建議都能追溯到 KPI、CSV 欄位或 Evidence ID。
- 圖表都有中文標題、資料日期、來源與用途。
- 反證表必須存在，不能只列支持證據。
- 資料狀態必須中文標示，包含正式 CSV、runtime、staging、沿用欄位。
- 所有輸出維持 `actionable:false`，不產生交易指令。

## 與主戰情室分工

| 系統 | 角色 | 主要輸出 |
|---|---|---|
| 主戰情室 UI | 即時診斷與資料狀態監控 | 今天結論、KPI、圖表、資料新鮮度 |
| 週/月戰報 | 決策邏輯稽核 | 持股風險、邏輯有效性、修正建議 |
| SOP | 操作規則 | 何時更新資料、何時發布 CSV、何時出正式戰報 |
| 研報庫 | 歷史留存與產品化閱讀 | 可追溯報告、流程圖、公式與版本紀錄 |

中文備註：主戰情室不是把所有研究報告塞進首頁；主程式應保持即時診斷，戰報才負責深度說明與邏輯修正檢討。
# P1008 Scheduled News Scan v1 Addendum

Weekly and monthly warroom reports must include the scheduled news scan audit when `runtime/warroom_news_scan_snapshot.json` exists.

- 6-12h protection: cite `NEWS_SCAN.json` for immediate `WATCH / REVIEW_REQUIRED` items and state whether the homepage showed `HOLD_UNDER_REVIEW`.
- 72h denoise: verify official source, multi-source corroboration, market confirmation, and direct Hon Hai or supply-chain relevance before treating an event as material.
- 7d report audit: list unresolved `OBSERVE / WATCH / REVIEW_REQUIRED` events as a counter-evidence table.
- Boundary: news scan rows are observation-only and can never output buy/sell instructions or change the formal HOLD conclusion.

## 定期戰報產生器 v1 契約

`P1008_5_GENERATE_REPORTS.bat --date YYYY-MM-DD --period daily|weekly|monthly` 是已核准的本機靜態戰報產生器。每份戰報至少必須納入：

- 正式 CSV 快照：最新每日股價、總經快照與 master KPI。
- 觀察型旁路 CSV：`fx_trend_observations.csv` 與 `macro_event_observations.csv`。
- 即時保護狀態：`runtime/warroom_news_scan_snapshot.json`。
- Owner 治理狀態：`runtime/warroom_event_review_state.json`，以及可取得時的最新 Owner publish review log。
- 圖表 / 表格：PB/Price 趨勢資料、FX 趨勢表、事件反證表、72h 重大性檢查、7d 未結案事件回顧。

產生器會寫入 `reports/P1008_REPORT_MANIFEST.json` 與 `runtime/warroom_report_manifest.json`；首頁、`reports.html` 與 `report_viewer.html` 以該 manifest 顯示最新日報、週報、月報。

強制邊界：產生的戰報一律為 `actionable:false`，不得修改正式 CSV、不得擴欄 `macro_snapshot.csv`、不得啟用 `KEEP_DISABLED`、不得改變 HOLD。若仍有未 ack 的 `REVIEW_REQUIRED` 事件，戰報狀態必須維持重審導向，並回答事件是否解除、KPI / FX / 市場資料是否已反映該事件、原 HOLD 邏輯是否仍有效。
