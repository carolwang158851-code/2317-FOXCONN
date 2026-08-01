# Phase 3A Architecture Report

Status: `IMPLEMENTED_VERIFIED`

## Objective

Phase 3A establishes a governed capability framework before any new research
provider or model is introduced. It proves that capabilities can be declared,
validated, enabled for a controlled shadow mode, disabled, assessed, replayed,
and retired without weakening the frozen Research Governance Contract.

## Architecture

```text
Capability manifests
        |
        v
Strict contract validation ---> Compatibility policy (v1/v2 roots)
        |
        v
Deny-by-default registry ---> Lifecycle policy ---> In-memory replay
        |                          |                     |
        v                          v                     v
Health assessment          Retirement review       Projection hash
        \__________________________|_____________________/
                                   v
                         Aggregate conformance
```

## Capability inventory

| Capability | Lifecycle | Execution | Provider |
|---|---|---|---|
| Echo Research | `SHADOW_ENABLED` | `MOCK_SHADOW` | Phase 2A mock only |
| Financial | `REGISTERED_DISABLED` | `DISABLED` | none |
| Macro | `REGISTERED_DISABLED` | `DISABLED` | none |
| News | `REGISTERED_DISABLED` | `DISABLED` | none |
| Deep Research | `REGISTERED_DISABLED` | `DISABLED` | none |
| Foreign Flow | `REGISTERED_DISABLED` | `DISABLED` | none |

## Authority boundaries

- Frozen v1 and v2 contract roots remain authoritative and unchanged.
- The registry is deny-by-default; an unknown capability cannot execute.
- No production lifecycle state exists.
- Shadow enablement, shadow disablement, and retirement require an Owner reference.
- Every manifest and framework projection fixes `actionable=false`.
- Replay is pure and in-memory; it writes no Ledger, SQLite, CSV, or runtime state.

## Explicit exclusions

No OpenAI SDK, API key, model call, network connector, provider implementation,
Launcher integration, Warroom integration, report generation, status API change,
scheduler, notification, trading instruction, or production enablement is included.

Phase 3A does not authorize Phase 2, a production runtime, or any new capability.
