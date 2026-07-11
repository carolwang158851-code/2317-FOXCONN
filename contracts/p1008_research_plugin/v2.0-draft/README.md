# P1008 Research Governance Contract v2.0-draft

Status: `DRAFT_NOT_AUTHORITY`

This draft adds two governance capabilities without modifying the accepted
v1.0 Contract:

1. External Tail Anchor receipts for detecting complete valid suffix deletion
   or ledger rollback.
2. A Research Governance Ledger for replaying Contract, Policy, Schema,
   Architecture Review, phase authorization, implementation, validation,
   rollback, and deprecation lineage.

## Authority boundary

- The accepted v1.0 root remains
  `3370C4DBD6B564E2200D051AC07C8507442C130ADE64D770621107FA09D2924D`.
- Nothing in this draft changes v1.0 behavior, schemas, policies, APIs, or
  implementation.
- This directory has no freeze manifest and is not executable authority.
- Runtime implementation, witness connector selection, credentials, network
  access, Launcher integration, and OpenAI remain unauthorized.

## Tail-deletion claim

A local hash file, local HMAC, DPAPI-protected file, or second local ledger
cannot prove rollback resistance because a privileged actor can roll back the
ledger and local anchor together. Production rollback detection requires:

- an `EXTERNAL_APPEND_ONLY` witness, or
- a `HARDWARE_MONOTONIC` witness,

with a verified signature, strictly increasing counter, receipt hash chain,
and independent retention.

Other witness classes may be used for tests or operational checkpoints but
must not be reported as solving tail deletion.

## Commit and recovery model

```text
validate event
  -> append + fsync ledger record
  -> create immutable anchor candidate
  -> obtain independent witness receipt
  -> verify signature/counter/receipt chain/anchor hash
  -> allow governance replay
```

The replay states are `MATCHED`, `UNANCHORED_TAIL`,
`LEDGER_ROLLBACK_DETECTED`, `DIVERGED`, `WITNESS_UNAVAILABLE`, and
`NOT_INITIALIZED`. Only `MATCHED` permits normal governance projection.

## Governance recursion boundary

The Governance Ledger is protected by the External Tail Anchor. The witness
receipt is independently retained and is not another event inside the same
ledger; this avoids using the ledger as its own rollback authority.

## Phase 2 gate

Phase 2 remains blocked until this draft is independently validated,
hash-frozen, Owner-accepted, implemented under a separate TargetFiles approval,
tested with an approved L3/L4 witness, and bound to a Git commit. OpenAI
Runtime still requires a separate Phase 2 authorization.
