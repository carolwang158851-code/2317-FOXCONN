# P1008 戰情室 Research Plugin Module

## Codex Execution Architecture Specification v1.0

**文件目的：**
在不重構、不取代、不繞過既有 P1008 戰情室的前提下，建立一個模組化的研究外掛：

`P1008 Research Plugin Module`

本模組負責：

* OpenAI 結構化研究
* Evidence Matrix
* Investment Committee
* Thesis Evolution
* Decision Memory
* Epistemic Validation Layer
* Outcome Interpretation Layer
* Thesis Lineage
* Legacy Thesis Reuse Guard
* 日報、週報、月報研究候選輸出

本模組不負責：

* 投資決策
* 自動加碼、減碼、買進、賣出
* 修改正式 CSV
* 修改 Runtime SQLite
* 修改 MIDR、HOLD 或任何正式裁決
* 啟用 disabled、KEEP_DISABLED 或 OBSERVATION_ONLY 規則
* 繞過 Warroom Gate 或 Owner Gate

所有輸出永久遵守：

```text
actionable=false
no_auto_trade=true
no_formal_csv_write=true
no_rule_enablement=true
```

---

# 1. 最高架構原則

## 1.1 系統角色

```text
OpenAI Platform
= Research Brain

Codex
= Engineering and Orchestration

Research Plugin
= Research Candidate Generator

P1008 War Room
= Governance Authority

Owner
= Decision Authority
```

## 1.2 不可違反的架構規則

```text
War Room is the System of Governance.

Research Plugin is an extension module,
not a replacement architecture.

Codex builds and validates the system,
but does not determine investment conclusions.

OpenAI produces research candidates,
but does not create effective decisions.

Owner is the only final decision authority.
```

## 1.3 第一條實作限制

```text
The Research Plugin SHALL NOT replace, refactor,
or bypass the existing P1008 War Room architecture,
CSV Authority, Runtime pipeline, Owner Gate,
Launcher workflow, report generator, or rule manifest.
```

---

# 2. 執行模式

本任務必須遵守以下五階段：

```text
Step 1 Repository Audit
Step 2 Dry-Run Architecture Report
Step 3 Owner Approval
Step 4 Controlled Implementation
Step 5 Verification and Closure Report
```

Codex 在 Step 2 完成後必須停止。

未收到 Owner 明確核准前，不得進入正式修改。

---

# 3. 模組目錄

不得重構既有目錄。新增以下獨立模組：

```text
modules/
└── p1008_research_plugin/
    ├── AGENTS.md
    ├── plugin.manifest.json
    ├── README.md
    │
    ├── config/
    │   ├── plugin_policy.json
    │   ├── capability_registry.json
    │   ├── source_policy.json
    │   ├── token_budget.json
    │   └── research_schedule.json
    │
    ├── schemas/
    │   ├── common_output.schema.json
    │   ├── claim.schema.json
    │   ├── evidence.schema.json
    │   ├── evidence_matrix.schema.json
    │   ├── decision_memory.schema.json
    │   ├── interpretation.schema.json
    │   ├── inference_chain.schema.json
    │   ├── thesis_event.schema.json
    │   ├── thesis_lineage.schema.json
    │   ├── epistemic_review.schema.json
    │   ├── gate_result.schema.json
    │   └── report_candidate.schema.json
    │
    ├── core/
    │   ├── orchestrator.py
    │   ├── context_builder.py
    │   ├── source_loader.py
    │   ├── source_gate.py
    │   ├── structured_output_client.py
    │   ├── token_budget_guard.py
    │   ├── artifact_store.py
    │   └── plugin_status.py
    │
    ├── capabilities/
    │   ├── financial/
    │   ├── deep_research/
    │   ├── macro/
    │   ├── foreign_flow/
    │   ├── valuation/
    │   └── evidence/
    │
    ├── reasoning/
    │   ├── evidence_matrix_builder.py
    │   ├── investment_committee.py
    │   ├── consensus_calculator.py
    │   ├── thesis_evolution.py
    │   └── research_quality.py
    │
    ├── epistemic/
    │   ├── decision_memory.py
    │   ├── outcome_interpreter.py
    │   ├── inference_chain_ledger.py
    │   ├── failure_localizer.py
    │   ├── thesis_quarantine.py
    │   ├── sub_thesis_protector.py
    │   ├── replacement_sandbox.py
    │   ├── legacy_reuse_guard.py
    │   └── epistemic_review.py
    │
    ├── gates/
    │   ├── anti_fantasy_guard.py
    │   ├── evidence_gate.py
    │   ├── thesis_usage_gate.py
    │   ├── warroom_adapter_gate.py
    │   └── owner_gate_builder.py
    │
    ├── reports/
    │   ├── daily_compiler.py
    │   ├── weekly_compiler.py
    │   ├── monthly_compiler.py
    │   └── canva_payload_builder.py
    │
    ├── adapters/
    │   ├── p1008_input_adapter.py
    │   ├── launcher_status_adapter.py
    │   ├── report_manifest_adapter.py
    │   └── owner_review_adapter.py
    │
    └── tests/
        ├── unit/
        ├── integration/
        ├── governance/
        ├── regression/
        ├── golden_cases/
        └── fixtures/
```

---

# 4. Plugin Manifest

建立：

```text
modules/p1008_research_plugin/plugin.manifest.json
```

內容至少包含：

```json
{
  "plugin_id": "p1008_research_plugin",
  "version": "1.0.0",
  "plugin_type": "research_extension",
  "host_system": "P1008_WAR_ROOM",
  "authority_level": "external_research_candidate",
  "actionable": false,
  "can_write_formal_csv": false,
  "can_modify_runtime_sqlite": false,
  "can_change_rules": false,
  "can_change_midr": false,
  "can_change_hold": false,
  "can_publish": false,
  "requires_warroom_gate": true,
  "requires_owner_gate": true,
  "supported_hooks": [
    "after_data_update",
    "after_news_scan",
    "before_report_compile",
    "weekly_research_review",
    "monthly_thesis_review"
  ]
}
```

Plugin 啟動時必須驗證此 manifest。

若任一治理欄位缺失，plugin 應拒絕執行。

---

# 5. 資料邊界

## 5.1 可讀取資料

Plugin 僅可讀取：

```text
正式 CSV
旁路 CSV
runtime snapshot JSON
news scan snapshot
event review state
report manifests
既有研究報告
Owner-approved Knowledge Base
```

## 5.2 不可寫入資料

Plugin 不可寫入：

```text
正式 CSV
既有 Runtime SQLite
RULE_STATUS_MANIFEST
MIDR 結論
HOLD 主 IC
既有規則設定
正式發布 manifest
```

## 5.3 Plugin 自有輸出區

所有輸出只能寫入：

```text
staging/research_plugin/YYYY-MM-DD/
runtime/research_plugin/YYYY-MM-DD/
reports/generated/research_plugin/
logs/research_plugin/
```

建議採用 JSON／JSONL append-only。

Phase 1 不使用資料庫，不新增 SQLite。

---

# 6. 核心 Capability

V1 只實作六項，避免過度耗費 token：

```text
Financial Capability
Deep Research Capability
Macro Capability
Foreign Flow Capability
Valuation Capability
Evidence Capability
```

暫不實作：

```text
Knowledge Graph
Plugin Marketplace
自動模型權重學習
自動 Thesis 修改
自動交易回測
全量每日 IC 辯論
```

---

# 7. 通用輸出契約

每個 Capability 必須使用 Structured Output，禁止自由格式作為系統資料來源。

```json
{
  "skill_name": "",
  "run_id": "",
  "run_date": "YYYY-MM-DD",
  "symbol": "2317.TW",
  "actionable": false,
  "status": "completed|insufficient_data|owner_review_required|rejected",
  "claims": [],
  "evidence": [],
  "counter_evidence": [],
  "confidence": "high|medium|low|insufficient_data",
  "data_quality_notes": [],
  "owner_review_required": [],
  "rejected_claims": [],
  "sources": [],
  "no_auto_trade": true,
  "no_formal_csv_write": true,
  "no_rule_enablement": true
}
```

硬性驗證：

```text
每個 claim 至少一個 evidence_id
每個 evidence 必須有 source_id
每個 source 必須有 as_of_date
缺資料不得產生精準結論
L4 不得進主結論
單一媒體不得升級為正式研究依據
```

---

# 8. 日報執行流程

每日戰前日報執行：

```text
1. Read-only 載入最新資料
2. Source Gate
3. Freshness Check
4. Context Builder
5. Token Budget Guard
6. 執行必要 Capability
7. Evidence Matrix Builder
8. Anti-Fantasy Guard
9. Thesis Relevance Check
10. Due Decision Memory Review
11. Legacy Thesis Reuse Guard
12. Warroom Adapter Gate
13. Daily Report Candidate
14. Owner Review Queue
```

日報輸出：

```text
financial_analysis.json
macro_analysis.json
foreign_flow_analysis.json
valuation_analysis.json
deep_research_analysis.json
evidence_matrix.json
legacy_reuse_guard_report.json
daily_report_candidate.json
owner_review_queue.json
plugin_run_manifest.json
```

日報不可每日執行完整四輪 IC。

日報 IC 僅在下列條件觸發：

```text
重大財報
重大法說
重大 AI／CSP 事件
Thesis Status 可能改變
RQS 明顯下降
核心反證出現
Owner 手動要求
```

---

# 9. 週報執行流程

每週執行：

```text
1. 彙整五個交易日 Evidence Matrix
2. 檢查 persistent / intermittent / resolved risks
3. 執行 Investment Committee Round 1–4
4. 計算 WCS
5. 更新 Thesis Evolution Candidate
6. 執行 Outcome Interpretation Review
7. 驗證到期 Decision Memory
8. 更新 Inference Chain Ledger
9. 執行 Epistemic Review
10. 產生 Weekly Report Candidate
```

週報重點：

```text
本週哪些壓力是單日雜音
哪些風險具持續性
哪些假設表面成立
哪些因果機制真正成立
哪些判斷被混淆因素抵消
哪些 Thesis 需要提高舉證標準
```

---

# 10. 月報執行流程

每月執行：

```text
1. 彙整週報與 Decision Memory
2. Thesis Lineage 差異分析
3. 長期推論鏈有效性檢查
4. Failure Localization
5. Sub-thesis Survival Check
6. Quarantine / Retirement Candidate
7. Replacement Thesis Sandbox
8. Legacy Reuse Audit
9. Owner Gate Proposal
10. Monthly Thesis Review Candidate
```

月報不能自動：

```text
退役 Thesis
恢復 Thesis
改變 Thesis 權重
啟用替代 Thesis
```

只能提出 proposal。

---

# 11. Epistemic Validation Layer

本層目的：

```text
驗證推理，不驗證交易
校準機制，不校準加減碼
挑戰 Thesis，不自動修改 Thesis
記錄 Interpretation，不把 Interpretation 當 Fact
```

## 11.1 五層結果驗證

每一筆 Decision Memory 必須拆成：

```text
Observation Validation
Hypothesis Surface Validation
Mechanism Validation
Decision Relevance Validation
Learning Validation
```

禁止使用單一：

```text
correct=true
wrong=false
```

應使用：

```text
supported
partially_supported
refuted
confounded
insufficient_data
unresolved
```

---

# 12. Outcome Interpretation Layer

建立：

```text
epistemic/outcome_interpreter.py
```

輸出至少包含：

```json
{
  "interpretation_id": "",
  "linked_decision_record": "",
  "original_hypothesis": "",
  "original_mechanism_chain": [],
  "surface_result": "",
  "causal_result": "",
  "alternative_explanations": [],
  "confounders": [],
  "causal_validity": "supported|partially_supported|refuted|confounded|insufficient_data",
  "learning_action": "preserve|lower_weight_candidate|quarantine_candidate|no_learning",
  "do_not_learn": [],
  "warroom_admissibility": "owner_review_required",
  "actionable": false
}
```

## 12.1 防止事後合理化

只有原 Decision Memory 中事前登記的 hypothesis 和 mechanism 可以被標示為已驗證。

事後提出的解釋只能標示：

```text
post_hoc_candidate
```

不得升級為因果結論。

---

# 13. Inference Chain Ledger

建立 append-only：

```text
runtime/research_plugin/inference_chain_ledger.jsonl
```

每條推論鏈包含：

```text
Observation
Hypothesis
Mechanism
Interpretation
Research Status
Report Conclusion
Later Validation
```

每個節點獨立驗證。

禁止用最終股價結果一次判斷整條鏈正確或錯誤。

---

# 14. Thesis Lineage

建立：

```text
runtime/research_plugin/thesis_lineage.json
```

Thesis 永不刪除，只能：

```text
ACTIVE
WATCHED
CHALLENGED
QUARANTINED
DEPRECATED
RETIRED
RESTORED
REPLACED
```

每次變更必須新增 ThesisEvent，不得覆蓋歷史。

---

# 15. Retired but Historically Valid

新增狀態：

```text
RETIRED_BUT_HISTORICALLY_VALID
```

代表：

```text
過去特定期間或條件下曾有效，
但目前不得直接支撐新的主結論。
```

每筆需包含：

```json
{
  "valid_from": "",
  "valid_to": "",
  "valid_context": [],
  "invalid_context": [],
  "allowed_usage": [
    "historical_context",
    "appendix",
    "past_report_explanation"
  ],
  "blocked_usage": [
    "daily_main_conclusion",
    "THESIS_STRONG",
    "valuation_upgrade",
    "holding_safety_conclusion"
  ],
  "requires_new_evidence_for_reactivation": true,
  "requires_owner_gate": true
}
```

---

# 16. Legacy Thesis Reuse Guard

所有 Capability 與 Report Compiler 輸出前，必須執行：

```text
legacy_reuse_guard.py
```

檢查：

```text
是否引用 RETIRED Thesis
是否引用 DEPRECATED Thesis
是否引用 QUARANTINED Thesis
是否把歷史有效論點當成當前有效
是否把舊論點改寫後重新包裝
是否缺少新的 evidence_id
是否未標示 historical_context
```

處理規則：

```text
舊 Thesis 進主結論 → REJECT
舊 Thesis 支撐 THESIS_STRONG → REJECT
舊 Thesis 作歷史背景 → ALLOW
舊 Thesis 加新證據要求復活 → OWNER_REVIEW_REQUIRED
```

---

# 17. Thesis Failure Localization

核心 Thesis 被挑戰時，必須先拆解因果鏈。

例如：

```text
CSP CapEx
→ AI Server Orders
→ Revenue
→ Margin
→ EPS
→ Valuation
→ Price
```

每個 link 獨立標示：

```text
supported
challenged
refuted
confounded
insufficient_data
```

禁止：

```text
股價未上漲，因此 AI Server Thesis 全部錯誤
```

允許：

```text
Revenue link 仍有效
Margin conversion link 失效
Valuation re-rating link 未被支持
```

---

# 18. Thesis Quarantine

核心 Thesis 不可直接刪除。

狀態流程：

```text
ACTIVE
→ WATCHED
→ CHALLENGED
→ QUARANTINED
→ DEPRECATED / RESTORED / RETIRED
```

Quarantine 期間：

```text
不可支撐主結論
不可提高 Research Status
不可提高估值信心
可保留於 observation
可進 appendix
可等待後續資料驗證
```

---

# 19. Replacement Thesis Sandbox

替代 Thesis 不得直接取代舊 Thesis。

流程：

```text
candidate
→ sandbox
→ evidence accumulation
→ IC challenge
→ Warroom review
→ Owner approval
→ active
```

新 Thesis 必須回答：

```text
它修正了舊 Thesis 哪個錯誤？
它是否只是舊 Thesis 的反向偏誤？
它保留哪些有效子假設？
它需要哪些新證據？
它在什麼條件下失效？
```

---

# 20. Thesis 權重治理

禁止 OpenAI 自動修改有效權重。

分三層：

```json
{
  "current_effective_weight": 0.75,
  "suggested_weight": 0.45,
  "review_weight": null,
  "effective_weight": 0.75,
  "requires_owner_approval": true
}
```

權限：

```text
OpenAI → suggested_weight
War Room → review_weight
Owner → effective_weight
```

---

# 21. Owner Gate 檢查點

核心 Thesis 修正、退役、復活或替換前必須通過：

```text
1. Failure Scope Check
2. Evidence Sufficiency Check
3. Counter-evidence Check
4. Sub-thesis Survival Check
5. Confounder Check
6. Replacement Bias Check
7. Legacy Reuse Policy Check
8. Blast Radius Check
9. Delayed Activation Check
10. Rollback Check
```

Owner 必須批准：

```text
退役什麼
保留什麼
隔離什麼
可如何引用
何時生效
如何回滾
```

---

# 22. API Namespace

所有 API 必須使用獨立 namespace：

```text
GET  /api/research-plugin/status
POST /api/research-plugin/run/daily
POST /api/research-plugin/run/weekly
POST /api/research-plugin/run/monthly
POST /api/research-plugin/run/epistemic-review
GET  /api/research-plugin/owner-review-queue
POST /api/research-plugin/thesis/propose-change
POST /api/research-plugin/thesis/owner-approve
POST /api/research-plugin/thesis/owner-reject
GET  /api/research-plugin/thesis/lineage
GET  /api/research-plugin/legacy-reuse-report
```

任何 API 均不得呼叫正式 publish endpoint。

---

# 23. Launcher 整合

Launcher 只新增一個獨立區塊：

```text
OpenAI Research Plugin
```

顯示：

```text
Plugin Status
Last Successful Run
Data Freshness
Research Quality Score
Token Usage
Evidence Gate Result
Legacy Reuse Violations
Owner Review Queue
Thesis Status Candidate
Epistemic Review Status
```

允許按鈕：

```text
Run Daily Research
Run Weekly Review
Run Monthly Thesis Review
Open Owner Review Queue
View Thesis Lineage
```

禁止按鈕：

```text
Buy
Sell
Add
Trim
Auto Publish
Enable Rule
Change Position
```

---

# 24. Token 與成本控制

建立：

```text
config/token_budget.json
```

策略：

## 24.1 每日

```text
只讀取有變更的資料
只跑必要 Capability
不跑完整 IC
不重新研究未變動長期議題
不傳送整個 Knowledge Base
```

## 24.2 每週

```text
執行 IC
驗證到期 Decision Memory
更新 Thesis Evolution Candidate
```

## 24.3 每月或重大事件

```text
才啟用深度研究
才執行完整 Thesis Review
才執行 Replacement Sandbox Review
```

## 24.4 Context 原則

```text
Static instructions first
Stable schemas second
Cached knowledge excerpts third
Dynamic market data last
```

## 24.5 Budget Guard

任何 Capability 超過設定 token budget：

```text
停止執行
輸出 token_budget_exceeded
不得自動擴大預算
進 Owner Review Queue
```

---

# 25. Research Quality Score

RQS 僅衡量研究品質，不代表投資信號。

建議：

```text
Evidence Quality       25%
Source Reliability     20%
Coverage               15%
Counter Evidence       15%
Reasoning Quality      10%
Freshness              10%
Historical Calibration 5%
```

規則：

```text
RQS < 60
→ DATA_INSUFFICIENT

RQS 60–79
→ RESEARCH_QUALITY_WARNING

RQS >= 80
→ research candidate may proceed to Warroom Gate
```

WCS 不應直接作為 RQS 的正負方向分數。

IC 分歧本身不代表研究品質低。

應評估：

```text
辯論完整度
證據引用率
反證覆蓋率
未解決疑慮揭露度
```

---

# 26. 測試要求

## 26.1 Governance Tests

必須測試：

```text
actionable=true → rejected
正式 CSV write → blocked
Runtime SQLite write → blocked
rule enablement → blocked
MIDR modification → blocked
HOLD modification → blocked
publish endpoint call → blocked
```

## 26.2 Evidence Tests

```text
claim 無 evidence → rejected
evidence 無 source → rejected
source 無日期 → warning / blocked
L4 進主結論 → rejected
單一媒體升級正式結論 → rejected
```

## 26.3 Epistemic Tests

```text
表面結果成立但因果失效
混淆因素抵消結果
事後解釋冒充事前 hypothesis
單一案例要求修改 Thesis
有效子假設被過度刪除
反向 Thesis 確認偏誤
```

## 26.4 Legacy Reuse Tests

```text
RETIRED Thesis 進主文 → fail
DEPRECATED Thesis 支撐 THESIS_STRONG → fail
歷史 Thesis 進 appendix → pass
舊 Thesis 有新證據但未 Owner Gate → owner_review_required
改寫舊句子規避 ID 檢查 → semantic match fail
```

## 26.5 Golden Cases

至少建立以下固定案例：

```text
地緣政治事件成立，但鴻海未下跌
US10Y 上升，但 AI 營收抵消估值壓力
營收上升，但毛利率未改善
外資賣超，但公司基本面未變
舊 Thesis 退役後被報告重新引用
單一財報數據要求恢復 quarantined Thesis
```

---

# 27. Shadow Mode

Plugin 正式接入前，至少完成 Shadow Mode。

Shadow Mode 規則：

```text
只產生候選輸出
不影響正式報告
不顯示為戰情室正式結論
不修改正式資料
由 Owner 人工比對既有報告
```

建議驗收條件：

```text
連續 20 個執行日
零 formal CSV write
零 actionable=true
零 disabled rule activation
零 retired thesis 主文誤用
100% claims 有 evidence_id
100% rejected claims 只進 appendix
所有 Thesis 變更皆有 Owner Gate
```

---

# 28. Phase 實作順序

## Phase 0：Repository Audit

只讀取並輸出：

```text
現有目錄
現有 API
現有 Launcher hooks
現有 report generator
現有 manifest
現有 CSV authority
可能衝突點
預計新增檔案
預計修改檔案
```

不得修改。

## Phase 1：Plugin Skeleton

建立：

```text
manifest
schemas
config
artifact store
status endpoint
read-only input adapter
```

## Phase 2：Research Core

建立：

```text
Financial
Macro
Foreign Flow
Valuation
Deep Research
Evidence Matrix
Anti-Fantasy Guard
```

## Phase 3：Epistemic Layer

建立：

```text
Decision Memory
Outcome Interpretation
Inference Chain Ledger
Failure Localization
Thesis Lineage
Legacy Reuse Guard
```

## Phase 4：Reasoning and Reports

建立：

```text
IC
WCS
Thesis Evolution Candidate
Daily / Weekly / Monthly Compiler
Owner Review Queue
```

## Phase 5：Launcher Adapter

只新增研究區塊，不修改原 Launcher 主流程。

## Phase 6：Testing and Shadow Mode

完成治理測試、Golden Cases 與 Shadow Mode。

---

# 29. Codex 最終交付物

Codex 必須交付：

```text
1. Architecture Audit Report
2. File Change Plan
3. Dry-Run Diff
4. Plugin Manifest
5. JSON Schemas
6. Capability Registry
7. Source Policy
8. Token Budget Policy
9. Plugin Runtime
10. Epistemic Validation Layer
11. Legacy Thesis Reuse Guard
12. Tests and Golden Cases
13. Shadow Mode Report
14. Owner Acceptance Checklist
15. Rollback Instructions
16. Closure Report
```

---

# 30. Codex 禁止事項

永久禁止：

```text
不得重構既有 P1008 戰情室
不得修改正式 CSV
不得修改 Runtime SQLite
不得修改 HOLD 主 IC
不得修改 MIDR 裁決
不得啟用 disabled / KEEP_DISABLED 規則
不得產生 Buy / Sell / Add / Trim 指令
不得讓 Plugin 自動發布正式報告
不得讓 OpenAI 自動修改 Thesis Library
不得刪除歷史 Thesis
不得讓 retired Thesis 未經 Gate 復活
不得將市場結果等同因果驗證
不得以股價漲跌判定研究正確或錯誤
```

---

# 31. 最終驗收原則

```text
Observation is not Interpretation.
Interpretation is not Causality.
Causality is not Decision.
Decision belongs to Owner.
```

```text
Localize failure before modifying thesis.
Preserve valid sub-hypotheses before retiring core thesis.
Quarantine before replacement.
Old thesis cannot return as authority without new evidence.
Effective learning requires Owner approval.
```

---

# 32. Codex 第一輪任務

請先執行 Phase 0，完成只讀架構稽核。

輸出：

```text
CODEX_RESEARCH_PLUGIN_DRY_RUN.md
```

內容必須包含：

```text
A. 現有戰情室架構摘要
B. 不可修改的治理邊界
C. Plugin 接入點
D. 新增檔案清單
E. 必須修改的既有檔案清單
F. 每個修改的必要性
G. 潛在衝突
H. Token 與成本估算
I. Shadow Mode 計畫
J. Rollback 計畫
K. 驗收測試矩陣
```

完成後停止。

不得開始修改程式。

等待 Owner 明確核准。
