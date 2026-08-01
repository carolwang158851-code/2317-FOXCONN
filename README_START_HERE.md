# P1008 戰情室入口

決策者日常只需要雙擊根目錄的 `P1008_APP.bat`。

它會開啟 `launcher.html`。Launcher 負責資料更新、總經 / 新聞 / FX 審查、Owner formal publish gate，通過後再進入新 UI 決策摘要。一鍵資料流程不會正式發布 CSV、不會改 HOLD 主 IC，也不會啟用 KEEP_DISABLED 規則。

## 根目錄保留哪些檔案

| 檔案 | 角色 |
| --- | --- |
| `P1008_APP.bat` | 決策者主入口，開啟 Launcher App |
| `P1008_START_HERE.bat` | 備援選單 |
| `P1008_1_UPDATE_DATA.bat` 到 `P1008_5_GENERATE_REPORTS.bat` | 舊流程與進階維運備援 |
| `launcher.html` | Launcher 中控台：更新、審查、Owner publish gate |
| `SOP_v4.html` | 完整操作 SOP |
| `index_p1008_v7.html` | 新 UI 決策摘要，由 Launcher gate 通過後進入 |
| `reports.html`、`report_viewer.html` | 研報庫與報告閱讀器 |

根目錄 BAT 是 launcher 層；真正技術腳本集中在 `tools/`。這樣保留 Windows 雙擊與舊路徑相容性，同時避免決策者進入工具資料夾操作。

## 詳細文件

- `docs/README_START_HERE.md`：決策者操作入口。
- `docs/APP_WORKFLOW.md`：Launcher 自動化工作流。
- `docs/GIT_VERSIONING.md`：Git 工作樹、未 commit 狀態與提交時機。
- `docs/FOLDER_LAYOUT.md`：資料夾歸屬與整理原則。
- `rules/CODEX_DELIVERY_CHECKLIST.md`：交付驗收清單。

## 正式發布提醒

一鍵資料流程不做正式 CSV append。若要把 staging candidate 升格成正式 CSV，Owner 可在 Launcher 的 `Owner Formal Publish Gate` 輸入強確認字串發布；`P1008_3_OWNER_PUBLISH_CSV.bat` 保留為備援。

Owner 驗收後若要建立第一個 Git baseline，請在 `CODEX_P1008_PACKAGE` 資料夾內依 `docs/GIT_VERSIONING.md` 操作；不要在上一層 `foxconn-system` 建立 P1008 baseline commit。
