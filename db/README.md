# P1008 SQLite 基礎設施

本目錄保存可重建的 Schema、forward-only Migration、維運工具與測試。

## 位置原則

- 正式運行資料庫：`%LOCALAPPDATA%\P1008\data\warroom.sqlite3`
- Migration：`db/migrations/`
- 不可變備份：`backups/sqlite/YYYY/MM/`
- 運行中的 SQLite、WAL 與 SHM 不得放在 OneDrive。
- 正式 CSV 維持唯讀；P2-01 不會匯入或修改任何 CSV。

## P2-01 範圍

- 八組核准核心資料表。
- `derived_metric_inputs`與`data_conflict_candidates`關聯表。
- `schema_migrations`、`migration_runs`、`pipeline_runs`。
- `backup_records`與`audit_logs`。
- Migration checksum、重複執行保護、單一 Writer、租約、WAL。
- SQLite Online Backup、雜湊驗證、完整性檢查與回復測試。

Release、Connector、KPI Registry、Evidence Package及AI Gateway不屬於P2-01。

## 指令

```powershell
python db/tools/p1008_db.py migrate
python db/tools/p1008_db.py status
python db/tools/p1008_db.py verify
python db/tools/p1008_db.py backup --reason OWNER_MANUAL
python -m unittest discover -s db/tests -v
```

所有命令輸出均包含`status`、`status_zh`與`status_note_zh`。

