# P1008 Git 工作樹與 commit 原則

## 目前狀態代表什麼

`CODEX_P1008_PACKAGE` 已初始化成 Git 工作樹，但尚未 commit。

這代表 Git 已經可以追蹤檔案差異，但目前所有檔案仍是「未建立第一個版本快照」的狀態。

## 未 commit 的優點

- Owner 可以先檢查所有檔案與流程，再決定是否建立第一個基準版本。
- 不會把測試過程產生的暫時檔案誤提交。
- 可以先調整 `.gitignore`，確認 `logs/`、`runtime/`、`staging/`、`reports/generated/` 不進版本庫。
- 適合目前這種還在整合 UI、App、SOP、文件的階段。

## 未 commit 的缺點

- 還沒有穩定 baseline，無法用 Git 快速回到某個已核准版本。
- `git diff` 對初始未追蹤檔案的幫助有限，因為 Git 還沒有上一版可比較。
- 之後若多人或多工具同時修改，較難判斷哪些變更已經核准。
- 若 OneDrive 同步或人工誤刪，Git 還不能完整協助恢復。

## 建議 commit 時機

完成以下檢查後，建立第一個 commit：

- Launcher App 可啟動。
- `POST /api/p1008/run/default` 成功。
- 正式 CSV hash 未變。
- SOP、README、docs 已更新。
- `.gitignore` 已確認忽略每日產物。

## Baseline commit 操作位置與命令

baseline commit 必須在 P1008 package 資料夾內做：

```powershell
cd C:\Users\a2231\OneDrive\foxconn_dashboard\foxconn-system\CODEX_P1008_PACKAGE
```

不要在上一層 `foxconn-system` 做，否則 Git 邊界會混到其他專案資料。

建議操作順序：

```powershell
git status --short
git add .
git status --short
git commit -m "Baseline P1008 launcher warroom app"
git status --short
```

`git status --short` 的用途是讓 Owner 在 commit 前後都能確認哪些檔案被納入版本管理。因為 `.gitignore` 已排除 `logs/`、`runtime/`、`staging/`、`reports/generated/`、`output/` 與 cache，`git add .` 不應納入每日產物。

若 Git 顯示 `.git/index.lock`，先確認沒有其他 Git 指令、編輯器或 Codex 正在操作該資料夾。若確認是殘留鎖檔，再刪除 `CODEX_P1008_PACKAGE\.git\index.lock` 後重試。

## 不建議提交的內容

下列資料屬於每日產物或暫存，不應提交：

- `logs/`
- `runtime/`
- `staging/`
- `reports/generated/`
- `output/`
- `dist/` 不應忽略；`dist/index_p1008_v7.bundle.js` 需要被追蹤，因為首頁依賴它離線執行。
- Python `__pycache__/`

## 建議提交的內容

- `P1008_APP.bat`
- `P1008_START_HERE.bat`
- `P1008_*.bat`
- `SOP_v4.html`
- `README_START_HERE.md`
- `docs/*.md`
- `tools/*.py`
- `tools/*.cmd`
- `src/*.html`
- `dist/index_p1008_v7.bundle.js`
- `index_p1008_v7.html`
- `data/*.csv`
- `data/*.json`
- `rules/*.md`
- `reports/*.md`

## 實務原則

Git 是稽核與回復工具，不是 Owner publish gate。

即使 Git commit 完成，正式 CSV append、新聞 connector 啟用、排程註冊、HOLD 規則調整，仍必須走 Owner 核准。
