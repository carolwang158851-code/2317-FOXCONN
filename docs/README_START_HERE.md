# P1008 戰情室決策者入口

## 最短操作路徑

1. 雙擊根目錄的 `P1008_APP.bat`。
2. 瀏覽器會開啟 `launcher.html`。
3. 在 Launcher 按「一鍵更新資料與資訊」。
4. 若有 CSV candidate、總經/FX 缺欄或新聞待決，先在 Launcher 完成 Owner review / publish gate。
5. Launcher gate 通過後再進入新 UI，閱讀主 IC、6 大系統、最新戰報、研報庫與 SOP。

## 決策者不需要記住的 BAT

Launcher 已經整合下列流程：

- `P1008_1_UPDATE_DATA.bat` 的 staging/runtime 更新能力。
- `P1008_4_NEWS_SCAN.bat` 的 v2 觀察型新聞掃描能力，可抓取 Owner-approved 公開來源並回報逐來源 health。
- `P1008_5_GENERATE_REPORTS.bat` 的日報產生能力。
- `P1008_2_OPEN_WARROOM.bat` 的本機 App server 啟動能力。

仍需人工保留或高門檻確認的流程：

- Launcher `Owner Formal Publish Gate`：正式 CSV append 可由網頁卡片執行，但必須輸入 `OWNER_APPROVE_PUBLISH_YYYY-MM-DD`。
- `P1008_3_OWNER_PUBLISH_CSV.bat`：正式 CSV append 的備援路徑。
- `P1008_4_REGISTER_NEWS_SCHEDULE.bat`：只有 Owner 決定要建立 Windows 排程時才執行。
- Git baseline commit：Owner 驗收 Launcher、SOP/docs 與正式 CSV hash 後，才在 `CODEX_P1008_PACKAGE` 資料夾內手動執行；細節見 `docs/GIT_VERSIONING.md`。

## 根目錄檔案怎麼看

| 類型 | 位置 | 用途 |
| --- | --- | --- |
| 決策者入口 | `P1008_APP.bat` | 最推薦的 Launcher 啟動按鈕 |
| Launcher | `launcher.html` | 資料更新、Owner review、正式 CSV publish gate |
| 備援選單 | `P1008_START_HERE.bat` | 給進階使用者手動選擇流程 |
| 舊流程備援 | `P1008_1` 到 `P1008_5` BAT | 保留相容性與維運使用 |
| 操作文件 | `docs/` | 決策者與維運說明 |
| 系統規則 | `rules/` | Codex/Owner 規則與驗收清單 |
| 研報與戰報規格 | `reports/` | 研報庫、KPI guide、戰報標準 |
| 技術工具 | `tools/` | Python/CMD server、fetcher、scanner、report generator |

## 安全邊界

- 一鍵資料流程不會正式發布 CSV。
- 正式 CSV 發布只能由 Launcher 的 Owner Formal Publish Gate 或備援 BAT 完成。
- Launcher 一鍵資料流程不會改 HOLD 主 IC。
- Launcher 一鍵資料流程不會啟用 KEEP_DISABLED 規則。
- Launcher App 只允許白名單 API，不接受任意 shell command。
- 新聞來源必須在 `data/NEWS_SCAN_SOURCE_MANIFEST.json` 中 `enabled=true` 且 `connectorStatus=APPROVED` 才能連網；抓取成功仍只代表 observation，不代表正式 CSV 發布。

## 相關文件

- `docs/APP_WORKFLOW.md`：Launcher 自動化流程與 API。
- `docs/GIT_VERSIONING.md`：Git 工作樹、未 commit 狀態、提交時機。
- `docs/FOLDER_LAYOUT.md`：根目錄、docs、tools、data、runtime/staging/logs 的歸屬。
- `SOP_v4.html`：完整 SOP。
- `rules/CODEX_DELIVERY_CHECKLIST.md`：驗收清單。
