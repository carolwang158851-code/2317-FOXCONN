# P1008 Git 工作樹與 commit 原則

## Canonical Git remote identity

P1008 的 canonical Git authority 固定為：

```text
P1008_CANONICAL_GIT_REMOTE = github
P1008_CANONICAL_MAIN_REF = refs/heads/main
origin = NON_AUTHORITATIVE_LOCAL_SIBLING
```

治理、recovery base、merge-base、ahead/behind、fast-forward eligibility 與
production push target 的判定，必須直接查詢
`git ls-remote github refs/heads/main`。`remote main`、`origin/main`、目前
branch upstream、remote HEAD、default remote 或 cached tracking ref 都不是充分的
canonical authority 證據。若 `github` 不存在或 direct query 失敗，必須
fail closed；不得 fallback 到 `origin`，也不得自動改 remote URL、upstream 或
remote 名稱。

## Formal Authority 與 Git lifecycle

`FORMAL_PUBLISH != GIT_COMMIT`。Owner Formal Publish Gate、正式 authority
檔案、`CSV_AUTHORITY_MANIFEST.json` 與核准 lineage 決定 formal authority；Git
不決定資料是否已成為正式 authority。

Authority/Git evaluator 只讀比較兩個身分域：formal authority 沿用 manifest
規定的 exact-byte SHA-256；Git canonical identity 使用 repository attribute-aware
的 `git hash-object --path` blob OID，並與 direct-query 得到的
`github:refs/heads/main` commit tree 比較。raw Windows checkout SHA-256、文字正規化
SHA-256 與 Git blob OID 不得互相替代。

- `SYNCED`：formal authority 有效且 canonical Git blobs 全部相符。
- `PENDING`：formal authority 有效，但 canonical Git 尚未記錄相同 blobs。這不會讓
  publish 失敗，也不改變 KPI、scoring 或 actionable。
- `BLOCKED`：formal authority 無效／不一致、canonical remote 無法安全查詢，或
  identity 無法安全判定。`BLOCKED` 不得降級為 `PENDING`。

Evaluator 與 Owner publisher 都不得自動執行 `git add/commit/push/merge/rebase/reset/stash/clean`。
CRLF/LF checkout 表示差異本身不構成 authority、governance 或 Git sync 狀態變更。

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
