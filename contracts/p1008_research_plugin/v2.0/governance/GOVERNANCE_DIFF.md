# Governance Diff: v1.0 to v2.0

## Unchanged authority

- All v1 research schemas, evidence rules, source gates, ledgers, and API
  contracts remain unchanged.
- `actionable=false`, no formal CSV write, no rule enablement, no HOLD or MIDR
  change, no report publication, and no trade remain permanent boundaries.
- Models, agents, Codex, and tools do not become governance authorities.

## Added authority

| Area | v1.0 | v2.0 addition |
|---|---|---|
| Complete suffix deletion | Known detection gap | External Tail Anchor and independent receipt contract |
| Witness trust | Not defined | L0-L4 model; only L3/L4 may claim rollback detection |
| Recovery state | Hash-chain validation | Six explicit fail-closed anchor states |
| Governance lineage | Contract files and Git evidence | Append-only Governance Ledger event catalog |
| Governance replay | Not defined | Disposable deterministic governance projection |
| Governance actors | Application governance principle | Direct actors restricted to OWNER and SYSTEM |
| Contract evolution | Versioning rule | Events for freeze, acceptance, binding, validation, rollback, and deprecation |

## Explicitly not added

- No witness provider, connector, credentials, network transport, or key.
- No Runtime implementation, Python, Launcher, SQLite, CSV, API, or scheduler.
- No OpenAI SDK, model call, agent orchestration, or Phase 2 enablement.

## Compatibility classification

The change is an additive governance overlay. It is breaking only for a future
implementation that chooses to claim v2 conformance without implementing the
required verified external anchor and Governance Ledger replay behavior. The
existing v1-only skeleton remains valid as v1-only and must not claim v2.
