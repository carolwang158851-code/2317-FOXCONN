# Capability Contract Specification

Status: `PHASE3A_CONTRACT`

## Contract precedence

Implementation is subordinate to the frozen governance contracts. A capability
must satisfy its manifest, the registry, lifecycle policy, compatibility policy,
health policy, retirement policy, and both frozen contract roots before it can be
reported as conformant.

## Activation contract

1. Unknown capability IDs are denied.
2. Registration does not imply enablement.
3. Validation does not imply execution authority.
4. Shadow enablement requires an allowed transition and Owner reference.
5. Only `echo_research` may be `SHADOW_ENABLED` in Phase 3A.
6. Production enablement is undefined and explicitly forbidden.

## Output contract

Framework output is a deterministic snapshot containing registry state,
conformance, and explicit boundary flags. It must always report:

```json
{
  "runtime_integrated": false,
  "openai_production_enabled": false,
  "state_persisted": false,
  "actionable": false
}
```

## Side-effect contract

Phase 3A may read its own configuration and create in-memory projections. It may
not write formal CSV, SQLite, Ledger, Governance Ledger, runtime state, Launcher,
Warroom, reports, notifications, or external services.
