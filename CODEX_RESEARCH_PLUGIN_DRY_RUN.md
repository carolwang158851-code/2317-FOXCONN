# P1008 Research Plugin Dry-Run Architecture Report

- TaskId: `P1008-RPM-PHASE1B-DRYRUN-20260710`
- TaskDate: `2026-07-10`
- Specification: `P1008 戰情室 Research Plugin Module.md` v1.0
- Revision: `R4 - Phase 1B Plugin Skeleton Dry-Run`
- Current step: `Phase 1B Plugin Skeleton Dry-Run completed; no implementation started`
- Next gate: `Git baseline commit and separate Owner approval of Phase 1B implementation`
- RuleEnablementChange: `false`
- BacktestChange: `false`
- Formal CSV write: `false`
- Runtime SQLite write: `false`
- Actionable: `false`
- Status: `PHASE_1B_DRY_RUN_COMPLETED_IMPLEMENTATION_NOT_AUTHORIZED`

> Owner 已授權 Phase 1A 契約層。本輪只建立版本化 Research Governance Contract；不得建立 `modules/p1008_research_plugin/`、修改 Launcher/App server/報表、安裝 OpenAI SDK 或執行模型呼叫。Phase 1B 仍需獨立 Dry-Run 與 Owner 核准。

## Executive Decision Summary

建議核准方向為「獨立、唯讀、候選輸出、Shadow Mode 優先」的 P1008 內部研究模組。它不是 Codex Marketplace plugin，不使用 `.codex-plugin/plugin.json`，也不取代現有 Launcher、CSV Authority、App server、新聞掃描器、戰報生成器或 Owner Gate。

Owner R1 指示將本架構由單純 Research Plugin 提升為 `P1008 Research Operating System`。因此在 Phase 1 前插入 Phase 0.5，先完成四個長期研究治理模組的設計：Research Agenda Engine、Knowledge Gap Registry、Research Debt Tracker、Research Health Dashboard。四者必須形成可追溯閉環，讓未解問題不會在報告結束後消失，也不允許模型用推測填補未知。

Owner R2 進一步將原 Phase 1 拆為 Phase 1A/1B。Phase 1A 已把治理資產獨立凍結於 `contracts/p1008_research_plugin/v1.0/`；未來 Python、Agents SDK、模型或 UI 都只能實作契約，不能重新定義契約。

V1 建議採一個 OpenAI Agents SDK orchestrator，加上六個 schema-bound capability tools；不先建立六個可互相 handoff 的代理。模型只能接收 Source Gate 核准的唯讀資料，所有結果先通過 JSON Schema、Evidence Gate、Anti-Fantasy Guard、Legacy Reuse Guard 與 Warroom Adapter Gate，最後只能寫入 Research Plugin 自有目錄。

核心戰情室在 Research Plugin 失敗、超時、無 API key 或 token 超限時仍必須正常運作。Plugin 失敗只能輸出 `RESEARCH_PLUGIN_UNAVAILABLE` 或 `insufficient_data`，不得阻擋既有資料更新、新聞掃描、正式 CSV Owner publish 或既有戰報生成。

## A. Existing Architecture Integration Points

### A1. Current control flow

```text
P1008_APP.bat
  -> tools/p1008_open_warroom.py
  -> tools/p1008_app_server.py
  -> launcher.html

Launcher default pipeline
  -> preflight + formal CSV hash baseline
  -> warroom_data_fetcher_v2.py
  -> warroom_news_scanner_v2.py
  -> warroom_periodic_report_v1.py
  -> runtime/p1008_app_state.json refresh

Formal publish (isolated path)
  -> POST /api/p1008/publish/formal
  -> owner_publish_csv_v2.py
  -> exact Owner approval phrase
  -> append CSV + manifest/hash sync
```

### A2. Read-only integration surfaces

| Surface | Current file | Plugin use |
|---|---|---|
| Formal authority registry | `data/CSV_AUTHORITY_MANIFEST.json` | Resolve approved formal and observation-only inputs; verify SHA-256 before reading |
| Formal financial data | `data/2317_master_v9.csv` | Financial, valuation and foreign-flow context; `v10` is not authority and must not be selected by filename recency |
| Daily market data | `data/2317_daily_price.csv` | Price/PB context only |
| Macro snapshot | `data/macro_snapshot.csv` | Observation-only macro context; never treated as formal investment fact |
| Event sidecar | `data/macro_event_observations.csv` | Observation/counter-evidence input; `Actionable=false` |
| FX sidecar | `data/fx_trend_observations.csv` | Observation input; `Actionable=false` |
| Runtime data snapshot | `runtime/warroom_realtime_snapshot.json` | Latest staging/runtime context; freshness and formal-sync state must be retained |
| Runtime news snapshot | `runtime/warroom_news_scan_snapshot.json` | Event candidates, source health and review deadline |
| Event review state | `runtime/warroom_event_review_state.json` | Read pending/acknowledged review state; Plugin cannot clear it |
| Report manifest | `runtime/warroom_report_manifest.json` | Discover existing daily/weekly/monthly reports through manifest adapter |
| Existing reports | `reports/` and `reports/generated/` | Read-only context; no direct edits by capabilities |
| Rule status | `rules/RULE_STATUS_MANIFEST.json` | Validate all rule states and digest; never modify |
| Source registry | `data/NEWS_SCAN_SOURCE_MANIFEST.json` | Source tier and approval metadata; no new source becomes approved through model output |
| Runtime SQLite | `%LOCALAPPDATA%\P1008\data\warroom.sqlite3` | Forbidden in Phase 1 and read/write forbidden to Plugin V1 |

### A3. Hook mapping

| Requested hook | Safe mapping | Default in Shadow Mode |
|---|---|---|
| `after_data_update` | Register event only after update script exits successfully and formal CSV hashes remain unchanged | Disabled; manual Launcher trigger only |
| `after_news_scan` | Build a frozen context package after news snapshot is fully written | Disabled; manual Launcher trigger only |
| `before_report_compile` | Read a completed Research Plugin candidate through `report_manifest_adapter.py`; never import or patch report-generator internals | Disabled until Phase 4 acceptance |
| `weekly_research_review` | Explicit job endpoint and schedule config | Manual only |
| `monthly_thesis_review` | Explicit job endpoint and schedule config | Manual only |

Automatic hooks must be registered but `enabled=false` until Owner separately approves schedule, cost budget and Shadow Mode results.

### A4. Existing implementation risks

1. `tools/warroom_periodic_report_v1.py` currently has 3,088 lines and repeated active definitions, including five `build_report_markdown`, five `write_report_html` and three `build_report`. Python uses the last definition, so the Plugin must integrate through report manifests/artifacts rather than importing these internal functions.
2. The package Git repository has no initial commit. All files are currently untracked, so there is no reliable rollback baseline or diff attribution.
3. No package `pyproject.toml`, lock file or requirements file exists. `uv`, `openai-agents`, `openai`, `pydantic` and `jsonschema` are not installed in the checked environment.
4. Current Python is 3.14.6. The current official Agents SDK metadata supports Python 3.10+, including 3.14, but dependencies still must be installed into a module-local virtual environment and pinned.
5. No machine-readable Owner-approved Knowledge Base registry currently exists. The files `KB_CONSISTENCY_AUDITOR.md`, `OWNER_DECISION_TREE.md` and related SOPs are policies, not a validated knowledge-base data store.
6. Existing epistemic policies contain language such as automatic signal downgrade or 50% position reduction. Research Plugin governance overrides those phrases for this module: it may emit a proposal, but it cannot change signal, position, HOLD, MIDR or rule state.

## B. Non-Modifiable Boundaries

### B1. Files and systems that remain read-only

- `data/2317_master_v9.csv`
- `data/2317_daily_price.csv`
- `data/macro_snapshot.csv`
- `data/macro_event_observations.csv`
- `data/fx_trend_observations.csv`
- `data/CSV_AUTHORITY_MANIFEST.json`
- `data/NEWS_SCAN_SOURCE_MANIFEST.json`
- `rules/RULE_STATUS_MANIFEST.json`
- all existing `rules/*.md`
- existing `runtime/*.json`
- `%LOCALAPPDATA%\P1008\data\warroom.sqlite3`, WAL and SHM
- existing report files and manifests except through a separately approved adapter phase
- all MIDR, HOLD, new-money, holding and position conclusions

### B2. Hard runtime invariants

```text
actionable=false
no_auto_trade=true
no_formal_csv_write=true
no_rule_enablement=true
can_modify_runtime_sqlite=false
can_change_midr=false
can_change_hold=false
can_publish=false
```

The runtime must refuse startup if any field above is absent or has a different value in `plugin.manifest.json` or `plugin_policy.json`.

### B3. Write allowlist

Only these roots may be writable by Plugin code:

```text
staging/research_plugin/YYYY-MM-DD/
runtime/research_plugin/YYYY-MM-DD/
reports/generated/research_plugin/
logs/research_plugin/
```

All writes must pass a resolved-path allowlist check. Symlinks, `..`, alternate drive paths and case-insensitive Windows path aliases outside these roots must be rejected. Artifacts should be written atomically through a temporary file in the same allowed directory, then renamed. Append-only ledgers must include previous-record hash and current-record hash.

### B4. Source authority rules

- Authority must be resolved from `CSV_AUTHORITY_MANIFEST.json`, not from filename, modification time or model judgment.
- `2317_master_v10.csv` exists but is not listed as authoritative; Plugin must ignore it unless Owner updates the authority manifest in a separate process.
- `macro_snapshot.csv` remains `USER_CURATED_WEB_DATA / MARKET_INTELLIGENCE_OBSERVATION_ONLY`.
- Event and FX sidecars remain `OBSERVATION_ONLY_SIDECAR` with `Actionable=false`.
- A single media source may support an observation but cannot become formal research authority.
- Model-generated citations do not upgrade `SourceTier` or source approval.

## C. Plugin Phase Plan

### Phase 0 - completed by this document

- Audit architecture, APIs, manifests, CSV authority, runtime paths and report flow.
- Record baseline hashes and conflicts.
- Produce this Dry-Run only.

### Phase 0.5 - Research OS strengthening design (current revision)

Phase 0.5 是設計與資料契約關卡，不建立可執行 Plugin，也不呼叫 OpenAI。完成定義如下：

#### 0.5-A Research Agenda Engine

- 將 `rejected_claims`、未解反證、到期 Decision Memory、重大事件待驗證項目和 Owner 指派問題轉為研究議程。
- 每個議程必須有研究問題、來源、優先級、成功條件、需要的證據、下次檢視條件與 Owner 責任狀態。
- 議程只能提出研究工作，不能提出交易、倉位或正式規則變更。
- 議程不得因日報結束自動關閉；只能由新證據與明確 resolution event 關閉。

#### 0.5-B Knowledge Gap Registry

- 把「已知未知」保存為一級系統資料，不得只寫在報告註解。
- Gap 類型至少包含 `DATA / SOURCE / FRESHNESS / EVIDENCE / CAUSALITY / CONFLICT / CALIBRATION`。
- 每個 gap 必須指出阻擋哪些 claim、thesis、capability 或 report conclusion。
- Gap 未解除時，精準結論必須降級為 `insufficient_data` 或 `owner_review_required`；禁止 DefaultFill。
- 模型不得自行把 gap 標為已解決。

#### 0.5-C Research Debt Tracker

- 管理已被識別但尚未完成驗證的研究工作，包括等待財報、法說、CSP CapEx、營收轉換、毛利、現金流、匯率與事件後續確認。
- Debt 必須連到原始 gap、agenda、claim/thesis 與 due trigger，而不是只有模糊待辦文字。
- 到期不會自動改判斷，只會提高研究優先級、降低 Research Health 並進 Owner review queue。
- Debt 只能透過 evidence-backed resolution event 關閉；刪除或隱藏 overdue debt 禁止。

#### 0.5-D Research Health Dashboard

- 衡量研究系統本身的證據完整性、未知管理、研究債務、議程完成度、資料新鮮度與歷史校準。
- Research Health 與市場風險、績效、HOLD、六大 IC 分數及單次 RQS 分開計算。
- Health 降級只能限制 Research Plugin 主結論的可用性，不得改戰情室 HOLD、交易或正式 CSV。
- Dashboard 第一階段輸出 JSON 與 Launcher adapter payload；UI 實作仍留在 Phase 5。

#### Phase 0.5 completion gate

Phase 1 不得開始，直到以下項目全部由 Owner 接受：

- 四個模組的 schema、狀態機、事件型態與 ownership。
- Gap、agenda、debt 的建立、升級、解除與退役規則。
- Research Health 指標權重與門檻。
- append-only lineage、Owner review 與 rollback 規則。
- Research OS 不得直接影響 HOLD、MIDR、規則、正式 CSV 或 Runtime SQLite。

### Phase 1A - Research Contract Layer (completed and Owner-accepted)

- 23 JSON Schemas covering research outputs, epistemic records, Research OS, ledgers, status and API payloads.
- 9 frozen Policies covering governance, capabilities, sources, budgets, schedules, agenda, gaps, debt and health.
- Event catalog and state-transition definitions.
- 8 append-only JSONL ledger formats with SHA-256 hash-chain requirements.
- OpenAPI 3.1 contract with 16 routes and no publish/trading/position/rule endpoint.
- 16 governance validation checks and Contract Freeze manifest v1.0.
- No executable implementation, model call or war-room integration.

### Phase 1A.5 - Contract Conformance Gate (completed)

- Owner acceptance is recorded outside the frozen root and references root hash `3370C4DBD6B564E2200D051AC07C8507442C130ADE64D770621107FA09D2924D`.
- Backward Compatibility Test: PASS; five CSV contracts, eight existing App API routes, sixteen Research API routes and six capabilities remain compatible.
- Ledger Replay Test: PASS; ten records across three hash chains replay to the expected projections and a tampered record is rejected.
- Deterministic Research Test: PASS; repeated and reordered inputs produce hash `EAF91F044767A0E671713E29A0E3BAE0398123DBB9B6539E2BB8E3057C439248`, preserve known unknowns and never use DefaultFill.
- Contract Drift Monitor: PASS; all 43 frozen artifacts reproduce the accepted root hash. The same test is registered as a GitHub Actions CI workflow for use after the Git baseline is created.
- OpenAI Capability Boundary Test: PASS; six research capabilities, nine allow/deny cases, eight deterministic governance gates and eight secured POST operations were verified with zero OpenAI calls.
- SDK guardrails remain defense in depth. Source, Evidence, Anti-Fantasy, Legacy Reuse, Warroom Adapter and Owner gates remain deterministic application logic.
- Passing this gate authorizes neither Phase 1B code nor OpenAI calls. It only makes a separately reviewed Phase 1B Dry-Run eligible.

### Phase 1B - Plugin Skeleton

- Owner authorized preparation of the Phase 1B Dry-Run on 2026-07-10. The completed design is `CODEX_RESEARCH_PLUGIN_PHASE1B_DRY_RUN.md`; machine-readable scope is `contracts/p1008_research_plugin/planning/phase1b/v1.0/PHASE1B_IMPLEMENTATION_PLAN.json`.
- This authorization covers documentation only. `modules/p1008_research_plugin/` remains absent and implementation requires a separate Owner decision plus a Git baseline commit.
- Create `modules/p1008_research_plugin/` only after a new Dry-Run and Owner approval.
- Implement read-only adapter, artifact store, status API, governance tests and Shadow Runtime shell.
- Consume frozen v1.0 contracts; implementation code cannot redefine schemas/policies.
- Do not call OpenAI, generate reports, integrate Launcher or modify war-room flow.

### Phase 2 - Research core, controlled OpenAI integration

- Add module-local dependency metadata and virtual environment instructions.
- Use OpenAI Agents SDK with one orchestrator and six function tools.
- Use typed `output_type` plus independent JSON Schema validation.
- Do not give the model shell, filesystem, arbitrary HTTP, publish or database tools.
- In V1, Deep Research analyzes Source Gate-approved local evidence. Arbitrary hosted web search requires a separate Owner source-policy approval.
- Add Evidence Matrix, Anti-Fantasy Guard and Research Quality Score.

### Phase 3 - Epistemic layer

- Add Decision Memory candidates, Outcome Interpretation, Inference Chain Ledger, Failure Localization, Thesis Lineage and Legacy Reuse Guard.
- All state remains Plugin-owned and append-only.
- No effective thesis weight changes; only `suggested_weight` may be populated.

### Phase 4 - Research OS Runtime

- Implement Agenda Engine, Knowledge Gap Registry, Research Debt Tracker and Research Health projections from frozen ledgers.
- Add weekly IC/WCS and research report candidates inside Plugin-owned outputs only.
- Do not connect to the existing war-room report generator yet.

### Phase 5 - War Room Integration

- Add explicit App server adapter, Launcher status/manual controls and report-candidate adapter.
- Preserve the single-window workflow and all existing Owner gates.
- Do not add Buy, Sell, Add, Trim, Auto Publish, Enable Rule or Change Position controls.

### Phase 6 - Shadow Mode

- Run governance, integration, regression, golden-case and live-model Shadow Mode tests.
- Require at least 20 successful trading-day runs before any proposal to enable automatic schedules.

### Phase 7 - Production Acceptance

- Owner reviews Shadow Mode evidence, costs, failure behavior, data retention and rollback.
- Production acceptance remains candidate-research only and does not authorize trading, formal CSV writes or rule activation.

Each phase requires a new Dry-Run and Owner approval. Contract Freeze v1.0 acceptance authorizes no Phase 1B code or later OpenAI calls.

## D. Proposed Module Code Boundaries

### D1. OpenAI architecture

```text
P1008ResearchOrchestrator (one Agent)
  -> read-only function tools
     -> FinancialCapability
     -> DeepResearchCapability
     -> MacroCapability
     -> ForeignFlowCapability
     -> ValuationCapability
     -> EvidenceCapability
  -> Research OS control plane
     -> KnowledgeGapRegistry
     -> ResearchAgendaEngine
     -> ResearchDebtTracker
     -> ResearchHealthDashboard
  -> deterministic post-model gates
     -> schema validation
     -> evidence/source linkage
     -> freshness check
     -> anti-fantasy guard
     -> legacy thesis reuse guard
     -> warroom adapter gate
  -> Plugin-owned candidate artifacts
  -> Owner review queue
```

Agents SDK function tools are preferred because their inputs can be schema-bound and guarded. Agent-level output guardrails run on final output only, so the P1008 write boundary, source gate and evidence checks must also be deterministic application code. Hosted tools and handoffs must not be relied on for these governance guarantees.

### D1.1 Research OS closed loop

```text
Claim / Evidence / Counter-evidence / Decision Memory
  -> detect unresolved uncertainty
  -> Knowledge Gap Registry
  -> Research Agenda Engine
  -> unresolved past due trigger
  -> Research Debt Tracker
  -> Research Health Dashboard
  -> priority and admissibility feedback
  -> next research run
  -> new evidence-backed resolution event
  -> close or narrow gap/debt; preserve lineage
```

The loop controls research priority and admissibility only. It has no edge to formal CSV publish, rule activation, HOLD, MIDR or position decisions.

### D1.2 RQS versus Research Health

| Measure | Unit of analysis | Main question | Direct effect |
|---|---|---|---|
| Research Quality Score (RQS) | One research run/candidate | Is this specific output sufficiently supported? | Candidate may proceed to Warroom Gate or be downgraded |
| Research Health Score (RHS) | Longitudinal Research OS | Is the research system managing evidence, unknowns and debt responsibly over time? | Research Plugin availability/status only |

RQS must not be averaged into RHS as a substitute for gap/debt hygiene. RHS must not be displayed as a seventh investment IC.

### D2. Context contract

The model receives a frozen `ResearchContext` with:

- `run_id`, `run_date`, `symbol`
- authority-manifest version and verified hashes
- selected rows and explicit `as_of_date`
- source tier, source id and freshness state
- current rule statuses from the verified rule manifest
- due Owner reviews and permitted thesis records
- token budget and requested capabilities

It does not receive writable paths, API approval phrases, shell commands, SQLite handles, Owner credentials or full unrestricted repository access.

### D3. Error behavior

| Condition | Required result |
|---|---|
| Missing API key | `PLUGIN_NOT_CONFIGURED`; core war room continues |
| Model/network timeout | `insufficient_data`; no retry storm; core war room continues |
| Token budget exceeded | stop remaining capabilities; emit `token_budget_exceeded` |
| Schema invalid | reject artifact; retain raw response only in protected Plugin log if policy permits |
| Claim lacks evidence | move claim to `rejected_claims`; never enter main conclusion |
| Source lacks `as_of_date` | warning or rejection per source policy |
| L4/unknown source | appendix/observation only |
| Forbidden path write | hard failure, governance incident log, no fallback path |
| Rule/manifest digest mismatch | refuse Plugin run |

### D4. API contract clarifications

- All endpoints remain under `/api/research-plugin/` and are added to the existing fixed route table; no arbitrary command endpoint is permitted.
- Run endpoints return `202` with a job id, or `409` if any core/update/publish/research job already holds the shared lock.
- `thesis/propose-change` creates a candidate only.
- `thesis/owner-approve` records Owner disposition only inside Plugin-owned runtime. It must not modify formal rule manifests, HOLD, MIDR, CSV or SQLite. Effective deployment of an approved thesis remains a separate Warroom change task.
- There is no publish endpoint.
- CSRF-style local request protection should require same-origin `127.0.0.1`, JSON content type and a per-server session token for POST routes.

Phase 0.5 adds read-only Research OS views to the future namespace:

```text
GET /api/research-plugin/agenda
GET /api/research-plugin/knowledge-gaps
GET /api/research-plugin/research-debt
GET /api/research-plugin/research-health
```

No delete endpoint is permitted. Future Owner disposition endpoints may append resolution events inside Plugin-owned runtime only; they cannot mutate or erase prior events.

## E. File Change Plan and Risk

This table describes future controlled implementation. None of these files are created or modified in this Step 2.

### E1. New files

| Path/group | Approx. lines | Purpose | Risk |
|---|---:|---|---|
| `modules/p1008_research_plugin/AGENTS.md` | 120 | Module-specific authority and forbidden-action rules | Low |
| `plugin.manifest.json`, `README.md`, `pyproject.toml` | 220 | Identity, governance, dependency and run contract | Medium |
| `config/*.json` | 350 | Policy, capabilities, sources, token budgets and schedules; schedules disabled by default | Medium |
| `schemas/*.schema.json` | 1,200 | Strict structured output and gate schemas | Medium |
| `core/*.py` | 1,000 | Orchestration, context, source gates, token guard, artifact store and status | High |
| `capabilities/*` | 1,200 | Six schema-bound capability implementations | High |
| `reasoning/*.py` | 850 | Evidence Matrix, IC, WCS, thesis candidates and RQS | High |
| `epistemic/*.py` | 1,300 | Plugin-owned memory, lineage, failure localization and legacy guard | High |
| `research_os/*.py` | 900 | Agenda Engine, Gap Registry, Debt Tracker and Health Dashboard | Critical |
| `gates/*.py` | 700 | Deterministic governance enforcement | Critical |
| `reports/*.py` | 500 | Research candidate compilers and Canva payload | Medium |
| `adapters/*.py` | 500 | Read-only P1008 inputs and output/status adapters | Critical |
| `tests/**` | 2,000+ | Unit, integration, governance, regression and golden cases | Critical |

Phase 0.5 extends the requested directory plan with:

```text
modules/p1008_research_plugin/
├── research_os/
│   ├── research_agenda_engine.py
│   ├── knowledge_gap_registry.py
│   ├── research_debt_tracker.py
│   └── research_health_dashboard.py
├── schemas/
│   ├── research_agenda_item.schema.json
│   ├── knowledge_gap.schema.json
│   ├── research_debt.schema.json
│   ├── research_health_snapshot.schema.json
│   └── research_os_event.schema.json
└── config/
    ├── research_agenda_policy.json
    ├── knowledge_gap_policy.json
    ├── research_debt_policy.json
    └── research_health_policy.json
```

Plugin-owned append-only artifacts:

```text
runtime/research_plugin/research_os/research_agenda_events.jsonl
runtime/research_plugin/research_os/knowledge_gap_events.jsonl
runtime/research_plugin/research_os/research_debt_events.jsonl
runtime/research_plugin/research_os/health/YYYY-MM-DD.json
```

### E2. Existing files proposed for later modification

| Existing file | Phase | Planned change | Estimated change |
|---|---:|---|---:|
| `tools/p1008_app_server.py` | 1/5 | Import a narrow research API adapter, add explicit GET/POST routes, share global job lock; no publish access | 120-180 lines |
| `launcher.html` | 5 | Add Research Plugin card/status/manual controls; preserve existing single-window and Owner publish gate | 180-260 lines |
| `tools/warroom_periodic_report_v1.py` | 4 | At most read one validated candidate manifest through adapter; do not import internal research logic | 20-40 lines |
| `SOP_v4.html` | 5/6 | Explain manual/automatic status, costs, Shadow Mode, Owner review and failure behavior | 100-160 lines |
| `rules/CODEX_DELIVERY_CHECKLIST.md` | 6 | Add Research Plugin governance and acceptance checks | 70-110 lines |

Because existing rules documents are read-only for this task, any future change to a rules file needs an explicit TargetFiles list and separate Owner approval.

### E3. Phase 1A change summary

```text
Phase 1A:
  + contracts/p1008_research_plugin/v1.0/**
  ~ CODEX_RESEARCH_PLUGIN_DRY_RUN.md

Not created:
  - modules/p1008_research_plugin/**

Not modified:
  - launcher.html
  - tools/*.py
  - data/*.csv
  - runtime/*.json
  - rules/*
  - reports/*
  - Runtime SQLite
```

## F. Capability Input and Output Contracts

| Capability | Inputs | Output focus | Must reject/downgrade |
|---|---|---|---|
| Financial | authority-approved quarterly rows, EffectiveDate, data quality | profitability, EPS, cash flow, balance-sheet claims | look-ahead rows, unmanifested master files, missing evidence |
| Deep Research | approved reports, approved event/news evidence, thesis context | mechanism chains, counter-evidence, unresolved questions | arbitrary unsupported web claims, single-media authority upgrades |
| Macro | macro snapshot, FX sidecar, source health, freshness | macro pressure observations and causal uncertainty | stale/untraceable values as precise conclusions |
| Foreign Flow | approved foreign holding fields and official source metadata | trend and ownership-context claims | treating flow as causality or trade instruction |
| Valuation | Close, BVPS, PB, EPS, explicit as-of dates | valuation range observations and sensitivity | hidden default values, PB/PE confusion, price target/action |
| Evidence | all claims/sources/counter-evidence | Evidence Matrix, rejected claims and RQS inputs | orphan claims, orphan evidence, missing source date |

Common output must conform to `common_output.schema.json` and permanently include all four false/no-action governance fields.

### F1. Research OS contracts

#### Research Agenda Item

Required fields:

```text
agenda_id, title, research_question, origin_type, origin_id,
priority, status, required_evidence, success_criteria,
next_review_trigger, owner_review_required, created_at, updated_at,
actionable=false
```

Allowed states: `PROPOSED / ACTIVE / BLOCKED / ANSWERED / RETIRED`. `ANSWERED` requires linked resolution evidence; a report conclusion alone is insufficient.

#### Knowledge Gap

Required fields:

```text
gap_id, gap_type, statement, severity, blocks_claim_ids,
blocks_thesis_ids, blocks_capabilities, known_since,
resolution_requirements, status, owner_review_required,
no_precision_inference=true, actionable=false
```

Allowed states: `OPEN / INVESTIGATING / PARTIALLY_RESOLVED / RESOLVED / ACCEPTED_UNKNOWN / RETIRED`. Only `RESOLVED` removes the associated precision restriction.

#### Research Debt

Required fields:

```text
debt_id, source_gap_id, source_agenda_id, linked_claim_ids,
linked_thesis_ids, reason, due_trigger, due_at, age_days,
risk_weight, status, resolution_evidence_ids,
owner_review_required, actionable=false
```

Allowed states: `OPEN / WAITING_EVENT / WAITING_DATA / OVERDUE / RESOLVED / ACCEPTED_DEBT / RETIRED`. `ACCEPTED_DEBT` means Owner accepts continued uncertainty; it does not make the underlying claim true.

#### Research Health Snapshot

Required fields:

```text
snapshot_id, as_of_date, overall_score, health_state,
evidence_linkage_score, gap_hygiene_score, debt_hygiene_score,
agenda_execution_score, freshness_score, calibration_score,
open_gap_count, overdue_debt_count, blocked_agenda_count,
data_quality_notes, owner_review_required, actionable=false
```

Proposed deterministic weighting for Owner review:

| Component | Weight |
|---|---:|
| Evidence linkage | 25% |
| Knowledge gap hygiene | 20% |
| Research debt hygiene | 20% |
| Agenda execution | 15% |
| Source/data freshness | 10% |
| Historical calibration | 10% |

Proposed states: `HEALTHY >= 80`, `WATCH 60-79`, `DEGRADED < 60`. `DEGRADED` suppresses Plugin main research conclusions and requires Owner review, but does not block or modify the core war room.

## G. Test Matrix

### G1. Governance tests

| Test | Expected result |
|---|---|
| `actionable=true` in model output | Rejected; run marked governance failure |
| Attempt to write any formal CSV | Blocked before open/write |
| Attempt to write existing `runtime/*.json` | Blocked |
| Attempt to open Runtime SQLite in write mode | Blocked |
| Attempt to update `RULE_STATUS_MANIFEST.json` | Blocked |
| Attempt to change HOLD/MIDR/position | Blocked |
| Attempt to invoke formal publish API/helper | Blocked |
| Missing governance manifest field | Plugin refuses startup |
| Path traversal/symlink escape | Blocked |

### G2. Evidence and epistemic tests

- Every accepted claim has at least one existing `evidence_id`.
- Every evidence item has a valid `source_id` and `as_of_date`.
- Missing or future-dated source material cannot become a current conclusion.
- Surface outcome cannot validate a hypothesis without mechanism review.
- Correlation cannot be labeled causality.
- Retired/deprecated/quarantined thesis cannot enter daily main conclusion.
- Historically valid retired thesis is allowed only for historical context/appendix.
- Semantic aliases of retired thesis ids are also detected.
- Failure localization preserves supported sub-theses.

### G3. Integration and regression tests

- Core Launcher default pipeline succeeds with Plugin absent, disabled, timed out or misconfigured.
- Research job cannot run concurrently with update, news scan, report generation or Owner publish.
- Existing formal CSV and authority-manifest hashes remain unchanged after every Research Plugin run.
- Existing report manifest remains valid if no Plugin candidate exists.
- Existing Launcher gate logic remains unchanged by research status.
- Existing DB unit tests and data/news/report smoke tests remain green.
- Research API returns only JSON, no arbitrary file or shell surface.

### G4. Golden cases

1. AI server growth with margin pressure: preserve demand claim, challenge margin-to-EPS conversion.
2. US10Y rise with continued AI growth: separate valuation pressure from operating demand.
3. Share-price rise with weak fundamentals: reject price action as proof of thesis.
4. Revenue growth with cash-flow deterioration: identify conversion/mechanism risk.
5. Core thesis failure with valid sub-thesis: quarantine only failed scope.
6. New evidence resembles quarantined thesis: require new evidence and Owner Gate.

### G5. Research OS tests

- Unsupported claim creates a linked gap instead of a guessed value.
- The same semantic gap is deduplicated while preserving all origin links.
- A gap with missing resolution evidence cannot transition to `RESOLVED`.
- An active gap creates or updates one agenda item, not repeated daily duplicates.
- Agenda item past its due trigger creates/updates research debt and preserves agenda lineage.
- Overdue debt raises research priority and lowers RHS but never changes HOLD or an IC score.
- `ACCEPTED_UNKNOWN` and `ACCEPTED_DEBT` preserve uncertainty and Owner identity; they do not validate a claim.
- Health score is reproducible from the same event ledgers and policy version.
- RQS and RHS remain separate fields and cannot overwrite one another.
- Removing, rewriting or backdating a prior agenda/gap/debt event is rejected.
- Research OS dashboard is unavailable/degraded when ledgers fail validation; the core war room remains available.

## H. Token and Cost Control

### H1. Proposed default budgets

These are planning caps, not approved production values:

| Run | Input cap | Output cap | Model calls | Behavior at cap |
|---|---:|---:|---:|---|
| Daily | 45k tokens | 8k tokens | max 4 | Skip nonessential capabilities; emit budget warning |
| Weekly | 120k tokens | 24k tokens | max 12 | Stop IC rounds not yet started; preserve completed evidence |
| Monthly | 220k tokens | 40k tokens | max 20 | Stop replacement sandbox expansion; require Owner review |

### H2. Context order and reduction

1. Static governance instructions.
2. Stable schemas and capability contract.
3. Hash-verified approved knowledge excerpts.
4. Latest dynamic market/news data.

The context builder must select rows/sections deterministically, record omitted inputs and never silently summarize away counter-evidence. Daily runs do not execute full four-round IC unless a documented trigger is present.

Agenda, gap, debt and health maintenance is deterministic and should not consume model tokens by default. The model may propose a new gap or agenda item through structured output, but deduplication, state transitions, debt aging and health calculation are local policy functions.

### H3. OpenAI implementation controls

- Use typed Agents SDK `output_type` and Pydantic models, followed by repository JSON Schema validation.
- Start with one Agent and local read-only function tools; no SandboxAgent is needed because the model must not inspect arbitrary workspace files or run shell commands.
- Keep tracing disabled in Shadow Mode unless Owner approves what data may appear in platform traces. If enabled later, exclude sensitive data and persist only trace ids in Plugin logs.
- Before Phase 2 build/run, use the OpenAI API credential gate; never store or print `OPENAI_API_KEY`.
- Model name, SDK version, prompt version and token usage must be recorded in each run manifest.

Official references checked for this architecture:

- https://openai.github.io/openai-agents-python/agents/
- https://openai.github.io/openai-agents-python/tools/
- https://openai.github.io/openai-agents-python/guardrails/
- https://github.com/openai/openai-agents-python/blob/main/pyproject.toml

## I. Shadow Mode Plan

### I1. Entry criteria

- All governance tests pass.
- Formal CSV and rule hashes match authority manifests.
- Owner approves source policy, model, budget and retention policy.
- Launcher exposes Research status without changing any existing decision card.

### I2. Minimum run set

- At least 20 successful trading-day daily runs.
- At least 4 weekly review candidates.
- At least 1 monthly thesis review candidate.
- Include network/API failure, stale data, empty evidence and token-budget cases.

### I3. Acceptance metrics

| Metric | Required |
|---|---:|
| Formal CSV writes | 0 |
| Runtime SQLite writes | 0 |
| Rule enablements | 0 |
| HOLD/MIDR changes | 0 |
| `actionable=true` accepted | 0 |
| Accepted claims linked to evidence | 100% |
| Evidence linked to dated sources | 100% |
| Rejected/unsupported claims retained for audit | 100% |
| Thesis changes with Owner review requirement | 100% |
| Unresolved precision gaps represented in Gap Registry | 100% |
| Overdue agenda items represented as research debt | 100% |
| Research Health snapshots reproducible from ledgers | 100% |
| RQS/RHS field collisions | 0 |

No Shadow Mode result automatically activates schedules or production use.

## J. Rollback Plan

### J1. Required baseline before Phase 1

1. Owner accepts current war room behavior.
2. Create the first Git baseline commit inside `CODEX_P1008_PACKAGE`.
3. Record formal CSV, CSV authority and rule-manifest hashes.
4. Confirm Runtime SQLite backup and integrity separately; do not copy the live WAL database through OneDrive.

### J2. Rollback mechanism

- Disable all Research hooks in `research_schedule.json`.
- Remove/disable only `/api/research-plugin/*` route registrations and Launcher Research card.
- Keep Plugin artifacts for audit; do not merge them into core runtime.
- Remove the independent `modules/p1008_research_plugin/` directory only after artifact backup.
- Restore changed existing files from the accepted Git baseline or a dedicated feature commit.
- Verify formal CSV, authority manifest and rule manifest hashes still match.
- Run the original Launcher default pipeline with Plugin absent.

Rollback must never use `git reset --hard` against unreviewed Owner changes.

## K. Owner Acceptance Checklist

### K1. Architecture approval

- [ ] Confirm this is a P1008 internal extension, not a Codex Marketplace plugin.
- [ ] Confirm the one-Agent/six-tool V1 architecture.
- [ ] Confirm Plugin failure must not block the core war room.
- [ ] Confirm no unrestricted web, shell, database or filesystem tool is available to the model in V1.
- [ ] Confirm automatic hooks and schedules remain disabled during Shadow Mode.
- [ ] Confirm the Research OS loop is `Gap -> Agenda -> Debt -> Health -> next research run`.
- [ ] Confirm RQS measures one output while RHS measures longitudinal system health.

### K2. Data and governance approval

- [ ] Confirm `2317_master_v9.csv` is the current authority and unmanifested `v10` is ignored.
- [ ] Confirm macro/event/FX data remains observation-only.
- [ ] Confirm Plugin can write only its four dedicated roots.
- [ ] Confirm `thesis/owner-approve` records a candidate disposition only and does not deploy a thesis or change Warroom state.
- [ ] Confirm any existing epistemic instruction that implies automatic position/signal changes is non-executable inside this Plugin.

### K3. Engineering approval

- [ ] Create and accept a Git baseline commit before Phase 1.
- [ ] Approve module-local dependency metadata and virtual environment.
- [ ] Approve later edits to `p1008_app_server.py`; Launcher/report/SOP/rules changes require their own phase approvals.
- [ ] Approve test and Shadow Mode thresholds.
- [ ] Approve token/cost caps and trace-retention policy before live OpenAI calls.
- [ ] Accept the 23 schemas, 9 policies, event/state definitions, 8 ledger formats and OpenAPI contract as v1.0.
- [ ] Accept proposed RHS weights and `HEALTHY / WATCH / DEGRADED` thresholds, or require contract v1.1 changes.

### K4. Owner response

Contract Freeze v1.0 was accepted by Owner on 2026-07-10 with five mandatory pre-Phase-1B conformance conditions. All five conditions now PASS. The acceptance record is `contracts/p1008_research_plugin/acceptance/v1.0/OWNER_ACCEPTANCE_RECORD.json`; the latest evidence is `contracts/p1008_research_plugin/conformance/v1.0/reports/latest_test_report.json`.

This acceptance does not authorize implementation. A separate Owner response is still required after reviewing a Phase 1B Plugin Skeleton Dry-Run.

To accept Contract Freeze v1.0 and authorize preparation of a Phase 1B Dry-Run only, reply:

```text
OWNER_ACCEPT_P1008_RESEARCH_CONTRACT_V1.0；請提出 Phase 1B Plugin Skeleton Dry-Run，不授權程式實作或 OpenAI 模型呼叫。
```

Any broader `OK` will be interpreted only as acceptance of Contract v1.0 and permission to prepare the Phase 1B Dry-Run. It will not authorize code, dependencies, API/UI changes or model calls.

## Dry-Run Delivery Checklist

### Files changed in this step

- `CODEX_RESEARCH_PLUGIN_DRY_RUN.md`: Repository Audit, architecture, Phase 0.5 Research OS design, file plan, governance boundaries, test plan, Shadow Mode and rollback proposal.
- `contracts/p1008_research_plugin/v1.0/`: Phase 1A frozen schemas, policies, events, ledgers, API contract, validation evidence and hash manifest.
- `contracts/p1008_research_plugin/acceptance/v1.0/`: Owner acceptance record bound to the frozen root hash.
- `contracts/p1008_research_plugin/conformance/v1.0/`: test-only fixtures, standard-library conformance runner and PASS reports for the five mandatory gates.
- `.github/workflows/p1008-research-contract.yml`: CI entry point for the same drift and conformance suite after Git initialization.
- `CODEX_RESEARCH_PLUGIN_PHASE1B_DRY_RUN.md`: Phase 1B Adapter/API/ledger/replay design, target files, test matrix, baseline hashes and stop conditions.
- `contracts/p1008_research_plugin/acceptance/v1.0/PHASE1B_DRY_RUN_AUTHORIZATION.json`: Owner authorization limited to Dry-Run preparation.
- `contracts/p1008_research_plugin/planning/phase1b/v1.0/PHASE1B_IMPLEMENTATION_PLAN.json`: machine-readable implementation scope; implementation remains unauthorized.

### Files not changed

- All formal and observation CSV files.
- `CSV_AUTHORITY_MANIFEST.json` and `RULE_STATUS_MANIFEST.json`.
- Runtime JSON and Runtime SQLite.
- Launcher, App server, update/news/report/publish tools.
- Existing rules, SOP and reports.
- No `modules/` directory was created.
- No Plugin runtime, OpenAI client, Launcher adapter or report adapter was created. The only Python added is the isolated test-only conformance runner.

### Rule status confirmation

The verified `RULE_STATUS_MANIFEST.json` digest matches its declared SHA-256. All nine `KEEP_DISABLED` rules remain disabled; all observation rules remain non-actionable.

### Formal data integrity baseline

At audit time, all five entries in `CSV_AUTHORITY_MANIFEST.json` match their declared SHA-256 values. This Dry-Run does not modify them.

### Potential risk checklist

- [x] New API and Launcher architecture is proposed; separate Owner approval is required.
- [x] OpenAI dependency and token cost are proposed; separate Owner approval is required.
- [x] Existing epistemic wording conflicts with the Plugin no-decision boundary; Plugin policy must explicitly block execution.
- [x] Existing report generator has duplicate active definitions; adapter-only integration is required.
- [x] Git baseline is missing; Phase 1 must not start without one.
- [x] Approved Knowledge Base machine contract is missing; Phase 1 source policy must reject unregistered KB content.
- [x] Four Research OS modules require frozen schemas and policies before Phase 1.
- [x] RHS weights and thresholds are frozen and accepted under Contract v1.0.
- [x] Backward Compatibility, Ledger Replay, Deterministic Research, Contract Drift and OpenAI Capability Boundary tests all pass.
- [x] Current environment lacks a pinned Draft 2020-12 metaschema validator; Phase 1B must add valid/invalid fixture execution before Shadow Runtime.
- [ ] No Backtest change is proposed.
- [ ] No rule enablement is proposed.
- [ ] No formal CSV schema change is proposed.

### Missing prerequisite action list

| Missing prerequisite | Impact | Owner/engineer action |
|---|---|---|
| Git baseline commit | No reliable rollback/diff | Owner accepts baseline, then create initial commit in `CODEX_P1008_PACKAGE` |
| Module dependency manifest/lock | Build is not reproducible | Add module-local `pyproject.toml` and lock/install procedure in Phase 1/2 |
| OpenAI SDK and schema dependencies | No model/typed-output runtime | Install only after Phase 2 approval and credential gate |
| Machine-readable approved KB registry | Source Gate cannot distinguish approved KB | Define KB registry schema and seed only Owner-approved entries |
| Owner-approved model/budget/trace policy | Cost and retention unknown | Approve before live model calls |
| Phase 1B Dry-Run approval | Contract acceptance alone does not authorize implementation | Prepare a Phase 1B Dry-Run, then request a separate Owner decision |
| Pinned Draft 2020-12 validator | Phase 1B cannot execute schema fixtures | Add module dependency and valid/invalid fixture tests in Phase 1B |

## Mandatory Stop

Phase 1A Contract Layer is complete, hash-frozen and Owner-accepted. All five pre-Phase-1B conformance gates pass. The Phase 1B Plugin Skeleton Dry-Run is now complete, but no controlled implementation has started. Phase 1B implementation remains unauthorized until a Git baseline commit exists and Owner explicitly approves the Dry-Run target files and boundaries.
