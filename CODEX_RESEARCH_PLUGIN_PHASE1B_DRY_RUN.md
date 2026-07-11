# P1008 Research Plugin Phase 1B Skeleton Dry-Run

- TaskId: `P1008-RPM-PHASE1B-DRYRUN-20260710`
- TaskDate: `2026-07-10`
- Contract: `P1008 Research Governance Contract v1.0`
- Frozen root hash: `3370C4DBD6B564E2200D051AC07C8507442C130ADE64D770621107FA09D2924D`
- Authorization: `DRY_RUN_AUTHORIZED`
- Implementation: `NOT_AUTHORIZED`
- OpenAI calls: `false`
- Launcher/App server integration: `false`
- Formal CSV / Runtime SQLite / rule writes: `false`
- Actionable: `false`

## 1. Executive Decision

本 Dry-Run 建議 **Go Phase 1B Plugin Skeleton Implementation，附前置條件**，但本文件本身不授權實作。

機器可讀驗證結論為 `GO_WITH_PREREQUISITES`，見 `contracts/p1008_research_plugin/planning/phase1b/v1.0/PHASE1B_DRY_RUN_VALIDATION.json`。

Phase 1B 只證明凍結契約可被工程化，不擴充或重寫 Contract，不建立研究結論，也不接 OpenAI。Skeleton 必須是一個可獨立測試、失敗時不影響既有戰情室的本機模組。

進入實作前仍有兩個必要 Gate：

1. 先在 `CODEX_P1008_PACKAGE` 建立可回復的 Git baseline commit。目前 Git 已初始化，但沒有 commit，現有檔案仍屬初始未追蹤狀態。
2. Owner 另行核准本 Dry-Run 的 TargetFiles、依賴與測試範圍。

## 2. 四項唯一目標

### 2.1 驗證 Contract 可以被實作

- 直接讀取凍結的 43 個 Contract artifacts，不複製、不修改 schema、policy、event 或 API contract。
- 啟動前重算 manifest root hash；不等於已接受的 root hash時，Skeleton 必須停止。
- 解決所有 `$ref`、ledger path、event catalog 與 state transition reference。
- Phase 1B 不得新增 schema、event type、API route 或 capability；缺少的契約需求只能回報 `BLOCKED_BY_GOVERNANCE`。

### 2.2 唯讀 Adapter 與 Status API

- Adapter 只接受 authority manifest 與固定 allowlist 路徑，不接受模型或 HTTP 參數傳入任意檔案路徑。
- CSV reader 必須跳過 `##` metadata header，再以真正欄名解析資料。
- Adapter 不提供 `write/update/delete/append/publish` 方法，也不持有 SQLite connection。
- Phase 1B 唯一對外 API 是 `GET /api/research-plugin/status`，綁定 `127.0.0.1` 且只供獨立測試 server 使用。
- Status payload 必須符合 frozen `plugin_status.schema.json`：`implementation_status=SKELETON`、`openai_enabled=false`、`actionable=false`。
- 不修改 `tools/p1008_app_server.py`，也不在 Launcher 顯示或觸發此 API。

### 2.3 Event -> Ledger -> Projection -> Replay 完整鏈路

```text
Validated command/fixture
  -> frozen event catalog validation
  -> research_os_event envelope
  -> append-only JSONL ledger record
  -> sequence + previous_hash + record_hash validation
  -> deterministic reducer/projector
  -> disposable projection snapshot
  -> process restart
  -> replay every ledger from genesis
  -> identical canonical projection hash
```

Ledger 是唯一 Plugin-owned state authority；Projection 只可刪除後重建，不得反向覆寫 ledger。Phase 1B 測試使用臨時目錄模擬 `runtime/research_plugin/` 相對路徑，不寫正式 runtime。

### 2.4 治理邊界保持不變

SDK guardrails 不是治理權威。Phase 1B 沒有 Agent，但仍先建立決定性的 Source、Freshness、Evidence、Anti-Fantasy、Thesis Usage、Legacy Reuse、Warroom Adapter 與 Owner Gate interface。所有 Gate 只讀 frozen policy 並輸出 `gate_result`；模型日後不能覆寫 Gate 結果。

## 3. Planned Module Boundary

實作核准後才建立：

```text
modules/p1008_research_plugin/
  README.md
  pyproject.toml
  src/p1008_research_plugin/
    contract_loader.py
    governance.py
    adapters/
      authority_adapter.py
      runtime_snapshot_adapter.py
    events/catalog.py
    ledgers/store.py
    projections/replay.py
    status/
      service.py
      server.py
    shadow_runtime.py
  tests/
    fixtures/
    test_contract_loader.py
    test_read_only_adapters.py
    test_event_catalog.py
    test_ledger_replay.py
    test_status_api.py
    test_governance_boundaries.py
```

`shadow_runtime.py` 在 Phase 1B 只是手動測試入口，不能排程、不能被 BAT 或 Launcher 呼叫、不能產生戰報。

## 4. Adapter Contract

### 4.1 Authority Adapter

輸入：

- `data/CSV_AUTHORITY_MANIFEST.json`
- manifest 明列的 `2317_master_v9.csv`、`2317_daily_price.csv`、`macro_snapshot.csv`、事件與 FX sidecar。

輸出：

- immutable Python records 或 JSON-compatible copies。
- source path、manifest hash、actual hash、schema/header 狀態與資料日期。
- 不對欄位做 DefaultFill，不把 observation-only sidecar 升格為正式 KPI。

拒絕：

- `..`、absolute path、symlink escape、manifest 未登錄檔案、hash mismatch、錯誤 schema、`2317_master_v10.csv`。

### 4.2 Runtime Snapshot Adapter

只讀 Owner 核准的 runtime JSON snapshot。禁止讀取 Runtime SQLite、任意 log、任意 staging candidate 或 Owner approval phrase。缺檔時回傳 `UNKNOWN/NOT_EVALUATED`，不得補猜。

## 5. Status API Contract

Phase 1B 只實作 frozen route：

```http
GET /api/research-plugin/status
```

最小 Skeleton response：

```json
{
  "contract_version": "1.0",
  "implementation_status": "SKELETON",
  "runtime_status": "IDLE",
  "last_successful_run": null,
  "data_freshness": "NOT_EVALUATED",
  "rqs": null,
  "rhs": null,
  "evidence_gate_result": "NOT_EVALUATED",
  "legacy_reuse_violation_count": 0,
  "owner_review_count": 0,
  "open_gap_count": 0,
  "overdue_debt_count": 0,
  "openai_enabled": false,
  "actionable": false
}
```

其餘 frozen API routes 在 Phase 1B 不綁定；不得自行發明簡化 route。Status server 掛掉、port 衝突或資料損毀都不能影響 Launcher 與核心戰情室。

## 6. Ledger and Projection Coverage

| Ledger | Aggregate | Phase 1B projection |
|---|---|---|
| `inference_chain` | RUN / CLAIM | run 狀態、claim 接受/拒絕與 evidence linkage |
| `decision_memory` | DECISION_MEMORY | review due queue，只重建候選記憶狀態 |
| `thesis_lineage` | THESIS / LEGACY_REUSE | thesis candidate lineage 與 reuse violation count |
| `research_agenda` | AGENDA | PROPOSED/ACTIVE/BLOCKED/ANSWERED/RETIRED |
| `knowledge_gap` | GAP | OPEN/INVESTIGATING/PARTIALLY_RESOLVED/RESOLVED/ACCEPTED_UNKNOWN/RETIRED |
| `research_debt` | DEBT | OPEN/WAITING_EVENT/WAITING_DATA/OVERDUE/RESOLVED/ACCEPTED_DEBT/RETIRED |
| `owner_review` | OWNER_REVIEW | pending/disposition history；不能執行正式變更 |
| `research_health` | HEALTH | 最新 RHS snapshot 與 HEALTHY/WATCH/DEGRADED |

34 個 allowed events 必須全部有 catalog 測試；8 個 forbidden events 必須全部被拒絕。Gap/Agenda/Debt 使用 frozen transition table；其他 aggregate 使用 event-type reducer，不能由輸入 payload 任意指定最終狀態。

## 7. Replay and Corruption Rules

- 每個 ledger sequence 從 1 開始且嚴格遞增。
- genesis previous hash 固定為 64 個 `0`。
- record hash 僅依 frozen `recordHashInput` 與 RFC 8785 compatible canonicalization 計算。
- replay 先驗證全部紀錄，再產生 projection；不得「跳過壞列繼續」。
- hash mismatch、缺列、重複 sequence、截斷、未知 event、非法 actor、非法 transition 都使 Plugin 進入 `UNAVAILABLE` 或 `BLOCKED_BY_GOVERNANCE`。
- 錯誤只停止 Plugin；核心 Warroom、Launcher、正式 CSV publish 與既有戰報流程繼續正常運作。

## 8. Test Matrix

| ID | Test | Pass condition |
|---|---|---|
| P1B-001 | Contract root | 43 artifacts 與 accepted root hash 完全一致 |
| P1B-002 | Contract references | schemas/events/ledgers/API refs 全部可解析，無擴充 |
| P1B-003 | CSV metadata | `##` 註解不被當成 CSV header |
| P1B-004 | Authority allowlist | 未登錄、path traversal、symlink escape 全部拒絕 |
| P1B-005 | Read-only surface | Adapter 無任何 mutating method，輸入檔 hash 不變 |
| P1B-006 | Event catalog | 34 allowed events 驗證；8 forbidden events 拒絕 |
| P1B-007 | Eight ledgers | 8 條獨立 sequence/hash chain 均可建立與驗證 |
| P1B-008 | State coverage | frozen transition table 每個合法狀態至少重播一次 |
| P1B-009 | Illegal transition | 每個 aggregate 至少一個非法跳轉被拒絕 |
| P1B-010 | Corruption | tamper、truncate、duplicate、unknown event 全部 fail closed |
| P1B-011 | Restart replay | restart 後 projection canonical hash 與原結果一致 |
| P1B-012 | Status schema | GET status 符合 frozen schema，未知欄位被拒絕 |
| P1B-013 | OpenAI boundary | import/call/token/model/tracing 均為 0；`openai_enabled=false` |
| P1B-014 | Warroom isolation | Launcher/App server/正式 CSV/規則/SQLite hash 全部不變 |
| P1B-015 | Failure isolation | Plugin 故障時核心 Warroom smoke test 仍通過 |

## 9. Baseline and Non-Target Hashes

本 Dry-Run 建立以下只讀 baseline；實作測試前後必須相同：

| Target | SHA-256 |
|---|---|
| Frozen Contract root | `3370C4DBD6B564E2200D051AC07C8507442C130ADE64D770621107FA09D2924D` |
| `contract.manifest.json` | `5D213CB4360329FCC969164F559952A0F1545BFE8E53D5CFDFF014B9D5619773` |
| `launcher.html` | `8BE1CAAAF3A516E02EA373D749FD3870CB756072D48A9038657B3BBCD7B540A5` |
| `tools/p1008_app_server.py` | `45C906977F42E416B532D3EF4C8909AE7AE07A618C7B62F5D515973B99A882A5` |
| `data/CSV_AUTHORITY_MANIFEST.json` | `23D8EB5774BBA764E24E9F80ABF0639CCC5B6C4E530905E3D59919D9CCD49392` |
| `rules/RULE_STATUS_MANIFEST.json` | `054DA1FDAF0C75BB27B56DF45B96F1CC1720558D44C700F1AB70AB0280A2FE5C` |
| Runtime SQLite | `76DB52F5F94EA43820D0661121D63EE476D35164272A3D4C068FE9DA436F6A19` |

正式 CSV individual hashes 由 `CSV_AUTHORITY_MANIFEST.json` 與既有 conformance suite逐檔核對，不能硬編碼成 Skeleton 的業務邏輯。

## 10. Dependencies and OpenAI Boundary

- Phase 1B 不安裝 `openai`、`openai-agents`，不讀 `OPENAI_API_KEY`，不建立 Agent、tool、handoff、trace 或 eval upload。
- 可使用 Python standard library 完成 Adapter、ledger、replay 與 loopback status server。
- Draft 2020-12 schema 的完整驗證若需要 `jsonschema`，必須在實作核准時固定版本並記錄 license/hash；不得因此引入 OpenAI SDK。
- Phase 1B 的 deterministic governance test 是應用層測試，不是 SDK guardrail test。

## 11. Stop Conditions

任一情況立即停止 Phase 1B 實作並回到 Owner review：

- 需要修改 frozen Contract 才能繼續。
- 需要修改 Launcher、App server、BAT、SOP 或戰報。
- 需要寫正式 CSV、Authority manifest、Rules、Runtime SQLite 或 `runtime/warroom_*`。
- 需要 OpenAI、外網、任意 shell、排程或交易能力。
- replay 無法完整重建狀態或 corrupted ledger 被容忍。
- Git baseline 尚未建立。

## 12. Owner Acceptance Gate

本 Dry-Run 已完成，但 Skeleton implementation 尚未授權。核准實作時，建議使用精確回覆：

```text
OWNER_APPROVE_P1008_PHASE1B_SKELETON_IMPLEMENTATION；僅實作唯讀 Adapter、Status API 與 Event/Ledger/Projection/Replay，不接 OpenAI、不整合 Launcher，先完成 Git baseline commit。
```

任何較廣泛的 `OK` 只解讀為同意設計方向，不授權 OpenAI、Launcher 整合或任何正式資料/決策變更。
