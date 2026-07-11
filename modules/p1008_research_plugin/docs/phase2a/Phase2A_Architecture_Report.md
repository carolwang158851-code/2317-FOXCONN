# Phase 2A Architecture Report

Status: `GOVERNED_MOCK_FOUNDATION_COMPLETE`

## Objective

Provide the smallest governed runtime foundation that can accept a research
request, build isolated context and prompts, invoke a replaceable provider
interface, validate typed output, and create a deterministic in-memory artifact.

## Execution path

```text
Research request
  -> Boundary validator
  -> Context builder
  -> Capability allowlist
  -> Frozen v1 + v2 contract verification
  -> Role-separated prompt builder
  -> phase2a-mock client interface
  -> Response adapter
  -> Typed/schema/evidence/source validation
  -> Boundary guard
  -> In-memory artifact envelope
  -> Owner review candidate
```

## Authority separation

- Governance contracts define authority and boundaries.
- Orchestrator coordinates one request and owns no durable state.
- Runtime executes deterministic gates.
- Mock provider supplies only the Echo candidate.
- Artifact envelope is non-authoritative and not persisted.
- Owner remains the only decision authority.

## Deliberately absent

No SDK, API key, network, production model, tool, database, ledger, projection,
Launcher, Warroom, report publication, notification, scheduler, or trading path
exists in Phase 2A.
