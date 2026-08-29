# 鴻海 2317 戰情室正式戰報生產指令 v1

## 1. 目的與邊界

本指令是既有 G1 事件治理、Phase B1 分析封包、Report Builder、Chart Builder、Validator 與 Viewer 的永久生產契約，不是另一套報告系統。正式戰報只接受 `MONTHLY_REVENUE`、`QUARTERLY_EARNINGS`、`MAJOR_EVENT` 三種經治理確認的事件。日曆經過、日常行情或一般新聞不得自行建立正式戰報；無有效事件時只更新觀察與證據狀態。

本流程的唯一正式產物是供 Owner 審閱的一份自包含 HTML。不得自動發布、不得以 PDF 或 ZIP 取代主產物，也不得將報告內容寫回財務資料層、RULE 或 Runtime SQLite。

## 2. 既有架構與不可替換母版

生產鏈固定為：

`G1 ReportTriggerDecision → 既有 evidence/research integration → Phase B1 analysis → existing Report Builder/Chart Builder → 本契約 adapter → existing Validator → Owner Review candidate`

母版為 `templates/HON_HAI_WAR_REPORT_MOTHER_V1.html`。它由 Owner 已驗證的 `HON_HAI_FY2026_Q2_ENTERPRISE_VALUE_WAR_REPORT.html`（SHA-256 `35BC300C3AD9D6783C8AD4F4BBDD850E51ED13065630DA6B361D3A2378C264B6`）抽取版型而成；只移除單次 Q2 內容並改為章節槽位。母版保留原 CSS、字型、1220px 報告寬度、sticky navigation、responsive 與 print CSS，並以 `<article class="report">` 為根節點。母版 SHA 不符、章節槽位不完整或外部資源依賴出現時停止。

## 3. 固定 11 章

章數、順序與標題不可變更：

1. 投資主題與核心判斷
2. 鑑往：經營與財務趨勢
3. 本季企業獲利分析
4. 三大財報與股東價值
5. 商業模式與競爭力
6. 外部戰情與未來獲利傳導
7. 3+3+3 與資本配置
8. 估值
9. 前瞻情境與投資判斷
10. 最後 SMART 總結
11. 正式附錄

`MAJOR_EVENT` 只改寫受事件影響的分析路徑；未受影響章節顯示「本次事件未改變原判斷」，但仍須保留全部 11 章。

## 4. 事件路由

### MONTHLY_REVENUE

必須有正式月營收發布。主要更新第 1、2、6、8、9、10、11 章；第 5 章只有在有新商業模式證據時更新。不得因月營收事件新造 CFO、FCF、ROIC、CCC、BVPS 或資產負債表數字；最新季度基線可保留，但必須標出期間。

### QUARTERLY_EARNINGS

必須有正式季報或法說資料，且更新全部 11 章。依資料可得性重算營收、毛利、營業利益、稅前淨利、歸屬母公司淨利、EPS、GM、OM、NM、營運資金、CCC、CFO、Capex、FCF、ROE、ROIC、Incremental ROIC、BVPS、股數與估值。第 4 章必須具有專門 FCF Conversion 分析。

### MAJOR_EVENT

必須先通過 G1 material-event governance。事件可為重大 AI Rack／ASIC／Consignment、Apple 或 NVIDIA 供應鏈、FX／關稅／政策、公司交易或資本配置。先建立因果影響路徑，再決定章節更新；不得盲目重寫全篇。

## 5. 輸入、優先序與歷史

每次生產必須分離五類輸入：正式財務基線、完整可比歷史、研究證據、目前市場快照、前一版報告狀態。資料優先序為：repository governed financial data、鴻海正式財報、正式法說／逐字稿／投資人資料、具聲譽市場資料、外部新聞。低層級資料不得覆寫高層級財務事實；新聞只屬證據。

歷史主資料固定為 `FULL_HISTORY`，保存 `ALL_AVAILABLE_COMPARABLE_HISTORY`，只允許追加確認觀察值。`RECENT_8Q` 與 `RECENT_12Q` 只能作次要視覺縮放，不得變更或取代完整序列。標籤擁擠時降低 tick-label 密度，不刪除觀察值。

## 6. 永久圖表與企業價值主軸

每次有效戰報以完整歷史重新產生：營收／毛利／營業利益、GM／OM、EPS、CFO／Capex／FCF、CCC／營運資金、ROIC、BVPS、股數／稀釋、P/S／P/E／P/B，以及資料足夠時的同業估值／資本效率。每張圖必須保存決策問題、期間、單位、來源 locator、公式／轉換、input SHA 與正文解讀。

完整季報的分析主軸固定為：營業利益品質、FCF Conversion、ROIC／Incremental ROIC、每股價值複利。因果鏈不可壓縮成單一獲利敘述：

`Revenue → Gross Profit → Opex → Operating Profit → Net Income → Working Capital → CFO → Capex → FCF → Invested Capital → ROIC → Incremental ROIC → EPS/BVPS/FCF per Share → Valuation`

## 7. FCF、Consignment、ROIC 與估值

季報第 4 章比較歷史 CFO、Capex、FCF 與前季、去年同期、前一完整年度及長期趨勢，並區分週期／時點壓力與結構性 FCF 惡化。缺少細部資料時不得虛構 Working Capital cash bridge。

Consignment 是待驗證假說，不是自動提高營業利益的因果。驗證鏈為：Consignment 增加 → 庫存／營運資金下降 → 資金需求下降 → 利息下降 → CFO／FCF 上升 → 投入資本下降 → ROIC 上升。

ROIC 口徑版本為 `ROIC_V1_NORMALIZED_OPERATING`：NOPAT＝Operating Profit×（1－normalized operating tax rate）；Invested Capital＝Operating Assets－Non-interest-bearing Operating Liabilities；ROIC＝NOPAT／Average Invested Capital；Incremental ROIC≈ΔNOPAT／ΔInvested Capital。季度、TTM、年度必須明確標示；缺少同口徑季度值時維持缺值，第三方 TTM 不得替代季度 ROIC。

估值固定連結 P/S、P/E、P/B、FCF、ROIC、ROE。Consignment 可能機械性縮小營收分母，必須區分 mechanical P/S expansion 與 genuine rerating；後者必須由 ROIC、FCF、ROE 與每股價值改善支持。敏感度不得稱為目標價。

## 8. 決策、前版比較與 SMART

每份正式戰報只輸出三個決策維度：

- Core Holding Thesis：維持／REVIEW／降級
- Add-on Capital Gate：通過／PARTIAL／尚未通過
- Thesis Downgrade Gate：尚未觸發／WATCH／TRIGGERED

不得建立未經 Owner 核准的總分或等第。每次必須列出前一版、目前狀態、改變內容、改變原因及下一個會改變判斷的證據。

SMART 狀態跨版本延續，每項保存 metric/thesis、current state、evidence、next verification condition、time horizon；至少涵蓋 OM、ROE、EPS、ASIC／Consignment、CFO／FCF、ROIC、P/S rerating、Apple／NVIDIA 長期風險、3+3+3 資本配置與每股價值複利。

## 9. 語言、版本與保存

正文使用台灣機構投資研究語體，保留 ROIC、FCF、ROE、EPS、BVPS、CCC、P/S、P/E、P/B、WACC、CFO、Capex 等標準縮寫。內部識別與工程狀態不得出現在正文；必要限制應翻成正常研究語言。

正式報告以 `report_key + revision` 定位。同一事件更正或 Owner 要求修改時新增 revision，不建立重複卡片；新 revision 記錄改了什麼、原因、資料變更及投資結論是否改變。季報與重大事件報告永久保留；月營收依既有 retention governance；日常觀察只進 evidence／observation history。

## 10. Runtime sequence 與停止條件

依序執行：resolve trigger、resolve report key、載入前版、驗證母版、載入財務基線與完整歷史、追加新觀察、資料驗證、允許的衍生計算、載入事件相關研究、企業價值因果分析、更新三維決策與 SMART、重畫累積圖、填入 11 章、輸出一份自包含 HTML、驗證、建立 Owner Review candidate、停止。

下列任一狀態必須停止：母版無法解析、財務基線完整性失敗、期間不明、公式口徑衝突、report_key 衝突、母版結構被破壞、圖表未嵌入、章數／順序變更、關鍵 KPI 衝突未解。不得以 best effort 產生正式報告。

## 11. Publication policy

Owner Review 永遠是終點。自動發布、公眾平台呼叫與自動產生交易指令均為 `false`。本契約本身不授權研究工具、模型、Canva、排程或資料發布。
