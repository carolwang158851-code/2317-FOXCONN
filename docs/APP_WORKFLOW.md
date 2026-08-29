# P1008 Launcher 自動化工作流

## G1 戰報觸發與候選產製

一般交易日執行「一鍵更新資料與資訊」時，News／Research 後會以最新、已驗證且
hash-bound 的研究整合結果評估 G1 Trigger。`NO_MATERIAL_CHANGE` 只更新 Launcher
狀態，不產生 Analysis、Report，也不追加研究庫。

季報或法說事件只有在正式公司／監管證據或既有 G1 合格交叉驗證成立時，才會成為
`TRIGGERED_INTERNAL_REPORT`。Owner 此後仍須手動依序啟動 Analysis Candidate 與
Report Candidate；兩者在伺服器端都會重驗相同 `report_key`、revision、decision 與
evidence lineage。Trigger 不等於 Publish；對外產製與發布仍須另一個 Owner approval，
且所有 runtime receipt 維持 `actionable=false`。

## 入口

決策者入口是根目錄的 `P1008_APP.bat`。它會呼叫 `P1008_2_OPEN_WARROOM.bat`，由 `tools/p1008_open_warroom.py` 啟動或重用本機 App server，預設開啟 `launcher.html`。日常使用會優先重用健康的 Launcher，避免多次雙擊後累積一堆 Python server；若維護者剛更新 server 程式碼，才手動加 `--fresh` 強制開新 session。

App server 只綁定 `127.0.0.1`，服務 Launcher、新 UI、研報庫、SOP，並提供固定白名單 API。

若 Launcher 顯示 `Codex 沙盒` 或 `Codex network sandbox` 警示，代表目前 localhost server 是從 Codex 工具環境啟動，可能繼承 `CODEX_SANDBOX_NETWORK_DISABLED=1`，造成新聞與總經 connector 顯示 `0/16` 或連線拒絕。Owner 驗收與日常使用應從 Windows 檔案總管直接雙擊 `P1008_APP.bat`，不要沿用 Codex 測試啟動的 localhost server。

## 三層分工

- `launcher.html`：資料更新、總經 / 新聞 / FX 審查、Owner formal publish gate。
- `index_p1008_v7.html`：新 UI 決策摘要與 6 大系統視野。
- 舊 UI 明細錨點：KPI、事件、FX、資料治理與戰報輸出檢視。

## 一鍵資料流程

Launcher 按「一鍵更新資料與資訊」後，App 會呼叫：

```text
POST /api/p1008/run/default
```

固定順序：

1. `preflight`：檢查必要工具、manifest、正式 CSV，建立 hash baseline。
2. `daily-price-authority`：呼叫 `P1008_1A_UPDATE_DAILY_PRICE.bat`，以驗證過的 TWSE month receipt 增量更新 Daily Price 與 manifest；兩檔必須原子更新，否則 rollback 並 fail closed。
3. `market-activity`：呼叫 `P1008_1B_UPDATE_MARKET_ACTIVITY.bat`，驗證 Daily Price Close 與同一份 TWSE receipt 後，原子 append Market Activity 與 manifest。
4. `authority-freshness`：檢查 TWSE 最新有效交易日、Daily Price 與 Market Activity 的日期連續性及一致性。
5. `update-data`：只有前三項全部成功後，才執行其他 Macro／FX staging candidate 與 runtime snapshot 更新。
6. `news-scan`：只有 authority chain 全部成功後，才產生新聞／事件 candidate 與逐來源 `networkSummary` / `sourceHealth`。
7. `validation/readiness`：重新整理 review package；只有上述 TWSE authority updater 可變更其限定的正式 CSV 與 manifest，其餘正式 authority 仍受 hash boundary 保護。

任一 Daily Price、Market Activity 或 freshness gate 失敗時，後續資料、新聞與 rolling brief 均不執行。`POST /api/p1008/run/report` 是分離的手動入口，不屬於 default job。

## Phase B1 手動分析／戰報候選

Launcher 另提供兩個不屬於一鍵資料流程的手動控制：

1. `POST /api/p1008/run/analysis-candidate`／「產生分析候選」：以七檔
   Authority、既有 Evidence Packet gates 與受控 MONTHLY_REVENUE fixture
   產生並驗證 `analysis_packet.json`。
2. `POST /api/p1008/run/report-candidate`／「產生戰報候選」：只有前一項
   Analysis gate 為 PASS 且 SHA 一致時，才產生 report、chart data、長篇與
   75 秒腳本候選。

Windows wrapper 是 `P1008_BUILD_ANALYSIS.bat` 與
`P1008_BUILD_REPORT.bat`；它們只鎖定 Bundled Python 3.12、設定套件路徑並
呼叫 `tools/p1008_build_analysis.py`／`tools/p1008_build_report.py`。所有業務
與安全規則均在 Python typed layers。產物只寫入
`runtime/report_production/<run_id>/`，不寫正式 CSV、Runtime SQLite、研報庫或
公開發布位置。OpenAI、Web Search、Deep Research、Canva、Gemini 與 YouTube
calls 均為 0，且所有候選 `actionable=false`。

## Phase A Authority Data Closure

- `warroom_daily_price_updater.py` 與 `warroom_market_activity_updater.py` 是限定範圍的正式 TWSE authority updater：只接受已驗證 receipt，並透過 `owner_publish_csv_v2.py` 原子更新對應 CSV 與 manifest。一般 staging candidate 仍須經 Owner gate。
- 日價 publisher 在最終寫入前會再次拒絕週六／週日、非
  `OFFICIAL_TWSE_*` 或 `OWNER_APPROVED` 來源、無效／零值 Close、PB 不一致及衝突
  Date。相同 Date 且完整列一致時視為 idempotent，不重複追加。
- `2026-07-19` 非法日價列只能先建立 remediation preview；正式移除必須輸入
  `OWNER_APPROVE_REMOVE_INVALID_DAILY_PRICE_2026-07-19`，並使用 backup、journal、
  atomic replace 與 rollback。本次 Phase A closure 不執行正式移除。
- `Hon_Hai_Rev_YoY` 的文字值不得當作數字或 0。無可追溯數值來源時，remediation
  candidate 留空並列為資料缺口，等待 Owner gate。
- 每個 TWSE authority step 只能變更其對應 CSV 與 `CSV_AUTHORITY_MANIFEST.json`；非 `UPDATED` 狀態不得變更任何正式檔。Macro、FX 與 News candidate 建立前後，正式 CSV 與 manifest hash 必須完全不變。

若候選日期是週末或交易所休市日，Launcher / 新 UI 會沿用最近正式交易日的 2317 Close/PB 供畫面連續，並標示 `MARKET_CLOSED_CARRY_FORWARD`。此列不 append 到正式 `2317_daily_price.csv`，正式 publish 只會處理已生成且通過 readiness 的候選 CSV。

總經資料來源採多層 fallback：FRED / TWSE / 央行 / 交易所等官方或準官方 connector 優先，Stooq 等公開市場資料次之，Yahoo Finance 只能作最後備援。若本次 connector/source 未取得但正式 CSV 有最近值，可沿用作 runtime 觀察，並標示 `CONNECTOR_SOURCE_UNAVAILABLE_CARRY_FORWARD`；這種沿用值不得讓正式 publish gate 自動通過。

資料更新引擎的網路層以 Python HTTPS 為第一路徑；若 Python connector 被公司 proxy / TLS / firewall 擋住，`warroom_data_fetcher_v2.py` 會用固定的 Windows PowerShell `Invoke-WebRequest` 再嘗試一次，走系統網路/proxy 設定。此 fallback 只用於讀取 Owner-approved 公開資料 URL，不繞過公司防火牆，也不放寬正式發布 gate。若資料仍只能沿用正式 CSV 最近值，Launcher 可顯示觀察值，但 Owner publish 仍會因缺少本次可追溯來源而阻擋。

Launcher 必須顯示 `macroSourceHealth` 逐欄來源健康表，讓 Owner 看到每個總經欄位的狀態、來源日期、來源 URL、是否支持正式發布。Fed_Rate 是慢變政策利率，正式 CSV 沿用可支持本次候選但仍需定期複核；VIX、WTI、TWD/USD、US10Y、DXY 若只剩 carry-forward，必須阻擋正式 CSV 發布。Alpaca 可作正式市場資料源；若抓取的是 VIXY、USO、UUP、IEF/TLT 等 ETF，正式性只適用於該 ETF 報價本身，可發布到代理指標或旁路 CSV，但不得直接填入 VIX、WTI、DXY、US10Y 等不同語義的原始總經欄位。

新聞掃描 v2 不是只在失敗時 block。它會對 Owner-approved observation sources 執行 RSS/Atom、sitemap、站內搜尋頁或 HTML 抽取，來源包含鴻海/MOPS 官方來源、台灣財經媒體、NVIDIA/Apple，以及 CSP/AI demand watchlist：Microsoft/Azure、AWS/Amazon、Google Cloud、Meta、Oracle、CoreWeave、OpenAI 等公開頁。判定重點不是只看品牌名稱，而是 `CSP_CAPEX_DEMAND`、AI data center、GB200/GB300/Blackwell、AI server、rack-scale、供應鏈中斷或鴻海直接關聯。若 Python HTTPS 被 proxy/防火牆拒絕，runtime 會記錄 `CONNECTION_REFUSED`、timeout、DNS、proxy/TLS 等錯誤；若 Playwright 可用，v2 可嘗試 Edge/Chrome browser-mode fallback，但不得繞過公司網路政策。

Launcher 必須把 crawler 成功率用人話顯示，例如 `13/16` 或 `0/16`。`0/16` 代表本次 App server 的 Python connector 沒有取得外網資料，不代表新聞不存在，也不代表瀏覽器或 Yahoo 網頁不可用。成功率低於 70% 時，新聞掃描不得視為完整；0% 時先檢查 proxy/firewall、server 啟動方式或 browser-mode 依賴。

若 Owner 已多次雙擊 `P1008_APP.bat` 但仍固定顯示 `0/16`，先看 Launcher 是否標示 `Codex 沙盒`。若是，請關閉該 localhost server，改從 Windows 檔案總管直接啟動。若不是沙盒，才優先確認本機 proxy/firewall、browser-mode 依賴與來源 manifest。`P1008_APP.bat` 日常會重用健康 server；若剛更新 server 程式碼或懷疑舊 server 卡住，維護者可手動執行 `P1008_APP.bat --fresh`。啟動器預設掃描 `8767-8899`，避免舊的 `8767-8787` 全被占用時直接失敗。

Yahoo Finance 只可作總經/市場資料最後 fallback，不是新聞 crawler 的正式來源。新聞來源以 `data/NEWS_SCAN_SOURCE_MANIFEST.json` 中 Owner 核准來源為準。

## 新聞來源 URL 維護規則

新聞來源不得只依賴容易改版的舊站內搜尋 URL。每個重要媒體來源至少要有一個首頁、分類頁、RSS/Atom 或 sitemap 作主路徑，站內 search URL 只能作輔助。

`data/NEWS_SCAN_SOURCE_MANIFEST.json` 的 `deprecatedUrlPatterns` 會列出已知失效或不應再使用的 URL pattern；`warroom_news_scanner_v2.py` 會在 URL build 階段直接略過這些路徑。鉅亨網目前以 `https://news.cnyes.com/news/cat/tw_stock` 等分類頁為主，`https://news.cnyes.com/search?q=...` 為輔，不再使用舊的 `search/all?keyword=...`。鴻海官方來源以中文站「最新消息」與 IR 月營收報告頁為主，不再使用舊的 English press release 空白頁。

Launcher 的 crawler 成功率只計算 `requiresNetwork=true` 的網路來源；`Owner manual event input` 是本地 Owner 輸入，不列入 `0/16` 或 `13/16` 分母。

`Readiness 95%` 是正式 CSV 發布門檻，不是新 UI 六大 IC 的投資分數。新 UI 可用 runtime carry-forward 值呈現觀察與重審提示，但只要 VIX、WTI、TWD/USD、US10Y、DXY 等 required source 沒有本次可追溯來源，Launcher Owner publish gate 仍必須阻擋。

自動化範圍分三層：`P1008_APP.bat` 只是手動開啟 Launcher；Launcher 的一鍵資料流程也是手動按鈕；只有 Owner 明確執行 `P1008_4_REGISTER_NEWS_SCHEDULE.bat --register` 後，Windows Task Scheduler 才會在 08:10、12:30、15:30、21:30 自動跑新聞掃描。排程只產生 observation-only staging/runtime，不發布正式 CSV。

## Owner Formal Publish Gate

正式 CSV publish 可在 Launcher 內完成，但必須符合下列條件：

- `GET /api/p1008/review-package` 顯示 readiness 通過。
- 候選 CSV schema、重複列、缺欄、來源層級、`Actionable=false` 檢查通過。
- 休市日 daily price 沿用不等於新交易日正式收盤價；macro_snapshot 的核心總經 connector/source 未取得仍會阻擋正式發布。
- Launcher 顯示的 PB 應寫成 P/B 倍數；BVPS 要另列。例：收盤價 251、BVPS 127.12 時，P/B 約 1.975。
- Owner 在 Launcher 輸入強確認字串：`OWNER_APPROVE_PUBLISH_YYYY-MM-DD`。
- Launcher 呼叫 `POST /api/p1008/publish/formal`，server 只執行既有 `owner_publish_csv_v2.py` gate。

`P1008_3_OWNER_PUBLISH_CSV.bat` 保留為備援路徑，不再是唯一入口。

## API

| API | 用途 | 安全邊界 |
| --- | --- | --- |
| `GET /api/p1008/status` | 讀取任務、步驟、Launcher gate、Owner review、來源 manifest | 只讀 |
| `GET /api/p1008/review-package` | 讀取候選 CSV、readiness、總經/新聞/FX 待決與 publish phrase | 只讀 |
| `POST /api/p1008/run/default` | 執行完整一鍵資料流程 | 不 publish |
| `POST /api/p1008/run/update-data` | 只補跑資料更新 | 不 publish |
| `POST /api/p1008/run/news-scan` | 只補跑新聞掃描 v2，更新 source health | 未核准來源不連網 |
| `POST /api/p1008/run/official-ir-scan` | 只掃描固定核准的鴻海 IR／MOPS 官方來源並重評 G1 | 不更新 TWSE CSV、不產生 Analysis/Report、不發布 |
| `POST /api/p1008/run/report` | 只產生日報 | 不改正式 CSV |
| `POST /api/p1008/run/analysis-candidate` | 手動產生 Phase B1 MONTHLY_REVENUE Analysis 候選 | 不連網、不呼叫模型、runtime-only |
| `POST /api/p1008/run/report-candidate` | 從已驗證 Analysis 產生 Report 與腳本候選 | 不可繞過 Analysis gate、不發布 |
| `POST /api/p1008/publish/formal` | Owner 強確認後 append 正式 CSV | 只能呼叫既有 publish gate |
| `GET /api/p1008/log?jobId=...` | 讀取任務 log | 只讀 |

## Official IR evidence lifecycle

- Normal day: Official IR scan → `NO_CHANGE` → no report.
- Scheduled earnings date: Event Calendar → `EVENT_SCHEDULE_CONFIRMED` / `WATCH`; schedule alone never proves results and never triggers a report.
- Results PDF, quarterly report, results-specific official release, or matching 2317 MOPS filing: raw official bytes are receipt/hash-bound, validated by `ResearchContentOrchestrator`, then evaluated by the existing G1 runtime.
- A later transcript is supplemental evidence for the same fiscal-period report identity; an unchanged deterministic claim does not create a duplicate report or revision.
- Scan integrity and source coverage are separate: a temporary failure at one official endpoint remains visible as incomplete coverage, while independently receipt/hash-validated evidence from another official source continues into the existing G1 evaluation. Security, schema, receipt, or provenance failures remain fail closed for the affected evidence.
- Trigger != Analysis; Analysis != Report; Report != Publish. All candidate creation remains an explicit Owner action and publication remains separately gated.

## 跳轉規則

- 若一鍵資料流程成功、正式 CSV hash 未異常、沒有 candidate 或 Owner 待決，Launcher 自動進入新 UI。
- 若有 CSV candidate、總經/FX 缺欄、新聞 `WATCH / REVIEW_REQUIRED`、Owner ack 未完成或 readiness blocked，停留在 Launcher。
- 新 UI 的更新與 Owner publish 入口會導回 `launcher.html?stay=1`。

## 禁止事項

- 一鍵資料流程不得 publish。
- 不執行任意 shell command。
- 不改 HOLD 主 IC。
- 不啟用 KEEP_DISABLED 規則。
- 不讓新聞或 FX sidecar 直接變成買賣指令。
- 新聞 crawler 成功抓到公開來源不等於正式發布；單一媒體最高 `WATCH`，官方或多來源交叉驗證也必須同時具備鴻海直接事件、CSP capex / AI data center 需求、GB200/GB300/AI server、供應鏈中斷、關稅/制裁等明確觸發詞，才可進 `REVIEW_REQUIRED`。
