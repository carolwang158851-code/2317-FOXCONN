# Capability Replay Report

Status: `PASS`

## Scope

The replay engine applies ordered lifecycle events to an in-memory projection.
It verifies sequence continuity, transition validity, Owner references, and
deterministic projection hashing.

## Evidence

The fixture replays Echo Research through registration, validation, shadow
enablement, and shadow disablement. Repeating the same event stream produces the
same terminal projection and hash. A sequence gap is rejected.

## Boundaries

- no Event Ledger write
- no Governance Ledger write
- no SQLite or file state
- no runtime-manager invocation
- no capability/provider execution
- no OpenAI or network activity

Replay proves lifecycle reconstruction only. It does not replay market research
content or authorize a capability.
