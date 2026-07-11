# P1008 Research Governance Contract v1.0

This directory is the frozen Phase 1A contract layer for the P1008 Research Operating System.

It contains only declarative contracts:

- JSON Schema definitions
- governance and operating policies
- event definitions
- append-only ledger formats
- OpenAPI 3.1 interface contract
- validation evidence and the freeze manifest

It contains no Python implementation, OpenAI client, Launcher integration, report integration, scheduler, database or executable runtime.

## Authority

The contracts define what a future implementation may do. Implementations cannot weaken these contracts. A contract change requires a new version directory, an impact report and Owner approval; frozen v1.0 files are immutable after acceptance.

## Permanent boundaries

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

## Phase boundary

Phase 1A does not create `modules/p1008_research_plugin/`. Phase 1B may create that implementation directory only after this contract freeze is accepted.

