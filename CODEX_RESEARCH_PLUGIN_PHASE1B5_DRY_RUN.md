# P1008 Research OS Phase 1B.5 Dry-Run

## 1. Approval and scope

Approval token:

`OWNER_APPROVE_P1008_PHASE1B5_CONTRACT_DESIGN_TARGETFILES`

This phase is contract design only. It defines the `v2.0-draft` External Tail Anchor and Research Governance Ledger contracts and their deterministic validation requirements.

Authorized in this phase:

- Record the accepted Phase 1B evidence.
- Define External Tail Anchor and independent witness receipt schemas.
- Define Governance Event, Ledger Record, and Projection schemas.
- Define deterministic policies, event catalog, ledger formats, validation rules, and the next implementation plan.
- Validate that the draft is internally consistent and remains within the approved TargetFiles.

Not authorized in this phase:

- Modifying any frozen `v1.0` contract, schema, policy, manifest, or conformance evidence.
- Implementing anchor, witness, governance ledger, projection, adapter, or status API runtime logic.
- Selecting or connecting an external witness provider.
- Installing or calling the OpenAI SDK, Agents SDK, models, or any network service.
- Modifying Launcher, App server, reports, formal CSV, runtime SQLite, rules, BAT files, schedules, or decision behavior.
- Enabling Phase 2.

## 2. Phase 1B acceptance anchor

Phase 1B is accepted against the following immutable comparison points:

| Item | Accepted value |
|---|---|
| Governed Git baseline | `efbf0b2ec1aaf25d1d4f9025fe4a04b0f336dce7` |
| Phase 1B implementation commit | `da8f1e286c5a3c2bb0c77fe176a277c3bbc6faa9` |
| Frozen v1 manifest SHA-256 | `5D213CB4360329FCC969164F559952A0F1545BFE8E53D5CFDFF014B9D5619773` |
| Frozen v1 contract root SHA-256 | `3370C4DBD6B564E2200D051AC07C8507442C130ADE64D770621107FA09D2924D` |
| Governance tests | 27 / 27 passed |
| Ledger replay smoke test | 8-ledger replay passed |
| OpenAI calls | 0 |

The machine-readable acceptance record is stored at `contracts/p1008_research_plugin/acceptance/v1.0/PHASE1B_ACCEPTANCE_RECORD.json`.

## 3. Threat model: valid tail deletion

The v1 hash chain detects mutation, insertion, and removal inside the retained ledger. It cannot prove that a fully valid suffix once existed if an attacker deletes that suffix and presents the earlier valid tail.

A second hash file beside the ledger does not solve this threat. An actor able to roll back the ledger can usually roll back the adjacent hash, HMAC, DPAPI blob, or local checkpoint as well. Therefore this draft separates two artifacts:

1. **Tail Anchor**: a deterministic statement of the ledger identity, version, terminal sequence, terminal record hash, prefix hash, previous receipt hash, epoch, timestamp, and nonce.
2. **Anchor Receipt**: an independently retained witness statement that binds the complete anchor payload to a strictly monotonic counter, prior receipt, witness identity, key, algorithm, and signature.

Only an independently retained `EXTERNAL_APPEND_ONLY` or `HARDWARE_MONOTONIC` receipt may claim production rollback detection. Local hashes and local authenticated checkpoints remain useful for development diagnostics but cannot claim rollback resistance.

## 4. External Tail Anchor contract

The draft defines the following deterministic commit sequence:

1. Validate the proposed ledger event and record.
2. Append the record and force durable local persistence.
3. Derive the Tail Anchor from the persisted ledger prefix.
4. Submit the complete anchor payload to an approved independent witness.
5. Verify the receipt signature, monotonic counter, prior receipt chain, and anchor payload hash.
6. Permit projection only after a verified qualifying receipt exists.

Recovery is fail-closed:

| Recovery state | Meaning | Projection permitted |
|---|---|---|
| `MATCHED` | Ledger tail, anchor, and qualifying receipt agree. | Yes |
| `UNANCHORED_TAIL` | Local ledger has records newer than the latest verified receipt. | No |
| `LEDGER_ROLLBACK_DETECTED` | Witness counter or receipt proves a newer retained state existed. | No |
| `DIVERGED` | Hashes, sequence, identity, or receipt chain disagree. | No |
| `WITNESS_UNAVAILABLE` | Independent state cannot be verified. | No |
| `NOT_INITIALIZED` | No accepted genesis and qualifying first receipt exist. | No |

No witness provider is selected by this design. Provider credentials, transport, retention, availability, signature verification, and failure handling require a later TargetFiles approval and provider qualification.

## 5. Research Governance Ledger contract

The Governance Ledger records the evolution of Contract, Policy, Schema, Architecture Review, phase authorization, implementation binding, validation, acceptance, rollback, and deprecation. It does not contain market decisions, trading instructions, or Warroom KPI actions.

Direct governance actors are limited to `OWNER` and deterministic `SYSTEM` processes operating under an Owner-authorized policy. OpenAI, Codex, models, agents, and tools cannot approve, freeze, authorize, accept, deprecate, or rewrite governance state. They may only produce non-authoritative candidate evidence for later Owner action.

The ledger is newline-delimited JSON using RFC 8785 canonicalization and SHA-256 chaining. Update, delete, truncate, and in-place correction are forbidden. Corrections require a new event. The governance projection is disposable and must be rebuilt from the externally anchored ledger.

The genesis event binds:

- the accepted frozen v1 contract root;
- the governed Git baseline commit;
- the Phase 1B implementation commit; and
- the first qualifying independent receipt.

The governance ledger is itself protected by the External Tail Anchor contract. Its independent witness receipt is retained outside the same ledger, preventing a recursive claim that the ledger alone proves its own completeness.

## 6. Deterministic governance boundaries

The contract requires application logic, not model judgment, to enforce:

- schema and event allowlists;
- actor authorization;
- canonical hashing and prior-record linkage;
- append-only semantics;
- external receipt qualification and monotonicity;
- fail-closed recovery states;
- deterministic replay and projection equality;
- prohibition of in-place v1 modification;
- prohibition of automatic Phase 2 or OpenAI enablement; and
- prohibition of Warroom decision, transaction, formal CSV, Launcher, or Runtime SQLite effects.

`Actionable` remains `false` throughout this contract layer.

## 7. Validation design

The draft validation catalog contains 20 deterministic checks covering:

- JSON parseability and Draft 2020-12 schema declarations;
- stable schema identifiers and closed object contracts;
- resolvable local references;
- frozen v1 hash preservation;
- explicit rejection of local-only rollback-resistance claims;
- complete receipt binding and strictly monotonic witness counters;
- fail-closed recovery behavior;
- Owner/System-only governance authority;
- append-only ledger semantics and deterministic replay;
- genesis binding to accepted v1 and Phase 1B evidence;
- non-authoritative model/tool candidates;
- no Warroom, formal CSV, Runtime SQLite, Launcher, App server, network, OpenAI, or Phase 2 side effects; and
- exact TargetFiles enforcement.

Static validation of this draft does not certify a witness implementation. Tail-deletion protection remains **designed but not operational** until an approved implementation passes external witness, rollback, crash-recovery, replay, and independent retention tests.

## 8. Approved TargetFiles

Only these 14 files belong to this phase:

1. `CODEX_RESEARCH_PLUGIN_PHASE1B5_DRY_RUN.md`
2. `contracts/p1008_research_plugin/acceptance/v1.0/PHASE1B_ACCEPTANCE_RECORD.json`
3. `contracts/p1008_research_plugin/v2.0-draft/README.md`
4. `contracts/p1008_research_plugin/v2.0-draft/schemas/tail_anchor.schema.json`
5. `contracts/p1008_research_plugin/v2.0-draft/schemas/anchor_receipt.schema.json`
6. `contracts/p1008_research_plugin/v2.0-draft/schemas/governance_event.schema.json`
7. `contracts/p1008_research_plugin/v2.0-draft/schemas/governance_ledger_record.schema.json`
8. `contracts/p1008_research_plugin/v2.0-draft/schemas/governance_projection.schema.json`
9. `contracts/p1008_research_plugin/v2.0-draft/policies/tail_anchor_policy.json`
10. `contracts/p1008_research_plugin/v2.0-draft/policies/governance_ledger_policy.json`
11. `contracts/p1008_research_plugin/v2.0-draft/events/governance_event_definitions.json`
12. `contracts/p1008_research_plugin/v2.0-draft/ledgers/governance_ledger_formats.json`
13. `contracts/p1008_research_plugin/v2.0-draft/validation/governance_validation_rules.json`
14. `contracts/p1008_research_plugin/planning/PHASE1B5_IMPLEMENTATION_PLAN.json`

Any change outside this list invalidates this phase's scope validation.

## 9. Exit decision and next gates

Phase 1B.5 contract design may be accepted only if all static checks pass, the 14-file boundary is preserved, and the frozen v1 hashes remain unchanged.

Acceptance of this draft does **not** authorize Runtime implementation. The next gate is a separate `v2.0` Contract Freeze authorization. Runtime TargetFiles, witness provider qualification, credentials, network transport, rollback tests, and Phase 2 OpenAI capability review each require separate approvals.

Suggested next approval after reviewing the validated draft:

`OWNER_APPROVE_P1008_PHASE1B5_V2_CONTRACT_FREEZE_TARGETFILES；請建立 v2.0 Contract Freeze manifest 與 conformance evidence，不實作 Runtime、不接 witness connector、不接 OpenAI。`

Until that approval is granted, the status remains:

- `v2.0-draft`: reviewable, not frozen;
- External Tail Anchor: contract only, not operational;
- Governance Ledger: contract only, not operational;
- OpenAI Runtime: disabled;
- Phase 2: blocked;
- Warroom behavior: unchanged.

## 10. Dry-Run validation result

Validation executed on 2026-07-11:

| Check | Result |
|---|---|
| Approved TargetFiles | PASS - exactly 14 files |
| JSON parsing | PASS - 12 JSON documents |
| JSON Schema declarations | PASS - 5 schemas use Draft 2020-12, stable draft IDs, and closed top-level objects |
| Local schema and contract references | PASS |
| Governance event catalog | PASS - 13 allowed and 10 forbidden events |
| Direct governance actors | PASS - `OWNER` and `SYSTEM` only |
| Rollback-resistance claim | PASS - only L3 `EXTERNAL_APPEND_ONLY` and L4 `HARDWARE_MONOTONIC` qualify |
| Recovery projection gate | PASS - only `MATCHED` permits projection |
| Governance ledger mutability | PASS - append-only; update, delete, and truncate forbidden |
| Runtime, network, credentials, Launcher, and OpenAI authorization | PASS - all disabled |
| Frozen v1 artifact verification | PASS - 43 / 43 artifacts |
| Frozen v1 root SHA-256 | PASS - `3370C4DBD6B564E2200D051AC07C8507442C130ADE64D770621107FA09D2924D` |
| Frozen v1 manifest SHA-256 | PASS - `5D213CB4360329FCC969164F559952A0F1545BFE8E53D5CFDFF014B9D5619773` |

The 11 files under `v2.0-draft` have the non-authoritative review digest:

`E9EEC7802D4ED8EDD94A3461937E9BCC52AB56A9DD94D7493B2FE9928632335C`

Construction: `SHA256(UTF8(join(sorted(relative_path + '|' + file_sha256), LF)))`.

This digest is for review reproducibility only. It is not a Contract Freeze root, does not make the draft authoritative, and does not prove external witness retention.
