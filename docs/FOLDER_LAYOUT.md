# P1008 資料夾歸屬

## 根目錄：決策者 launcher 層

根目錄只應放決策者可直接雙擊的入口與主要 HTML。

保留在根目錄的原因：

- Windows 使用者最容易找到。
- 舊 SOP、排程、Owner 流程已有引用。
- BAT 搬入子資料夾會增加路徑問題與相容風險。

主要入口：

- `P1008_APP.bat`：決策者主入口。
- `launcher.html`：資料更新、Owner review、正式 CSV publish gate 的 App 中控頁。
- `P1008_START_HERE.bat`：備援選單。
- `P1008_1_UPDATE_DATA.bat` 到 `P1008_5_GENERATE_REPORTS.bat`：進階維運與舊流程備援。
- `index_p1008_v7.html`：新 UI 決策摘要，不承擔資料更新與 publish gate。

## docs：操作與治理文件

- `docs/README_START_HERE.md`：決策者操作入口。
- `docs/APP_WORKFLOW.md`：Launcher 自動化工作流。
- `docs/GIT_VERSIONING.md`：Git 工作樹與 commit 原則。
- `docs/FOLDER_LAYOUT.md`：本檔。

## tools：技術工具

- App server、launcher、資料抓取、新聞掃描、戰報產生器。
- 不建議決策者直接操作。

## data：正式資料與資料 manifest

- 正式 CSV。
- CSV authority manifest。
- 新聞來源 manifest。

## runtime / staging / logs：每日產物

- `runtime/`：首頁與 App 即時狀態。
- `staging/`：候選 CSV、dry-run、news scan report。
- `logs/`：App/BAT/tool log。
- 這些預設不進 Git。

## reports / rules

- `reports/`：研報、KPI guide、戰報標準、產生後戰報索引。
- `rules/`：Codex/Owner 規則、驗收清單、執行守門規則。

## 原則

決策者日常只看根目錄 `P1008_APP.bat`、`launcher.html` 與新 UI；維運者看 `docs/`；Codex/工程維護看 `tools/`、`rules/`、`data/`。
