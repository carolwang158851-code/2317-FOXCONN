# P1008 Research Governance Contract v2.0

Status: `FROZEN_OWNER_ACCEPTED`

This authoritative additive Contract extends the immutable v1.0 Research
Governance Contract with two governance capabilities:

1. External Tail Anchor receipts for detecting complete valid suffix deletion
   or ledger rollback.
2. A Research Governance Ledger for replaying Contract, Policy, Schema,
   Architecture Review, phase authorization, implementation, validation,
   rollback, and deprecation lineage.

## Normative dependency

v2.0 is a governance overlay, not an in-place replacement of v1.0. The
normative v1.0 dependency is identified by root hash:

`3370C4DBD6B564E2200D051AC07C8507442C130ADE64D770621107FA09D2924D`

All v1.0 schemas, policies, APIs, events, ledgers, and permanent Warroom
boundaries remain unchanged. A conforming future implementation must load the
accepted v1.0 Contract and then apply this v2.0 governance overlay.

## Authority boundary

- Files listed in `contract.manifest.json` are frozen authority.
- The manifest, freeze record, conformance evidence, and Owner acceptance bind
  the frozen root but are excluded from that root to avoid circular hashing.
- Runtime implementation, external witness selection, credentials, network,
  Launcher integration, SQLite, CSV, Status API changes, and OpenAI remain
  unauthorized.
- Phase 2 remains disabled.

## Tail-deletion claim

A local hash file, local HMAC, DPAPI-protected file, or second local ledger
cannot prove rollback resistance because a privileged actor can roll back the
ledger and local anchor together. Production rollback detection requires:

- an `EXTERNAL_APPEND_ONLY` witness, or
- a `HARDWARE_MONOTONIC` witness,

with a verified signature, strictly increasing counter, receipt hash chain,
and independent retention. This Contract defines that requirement; it does not
claim that a witness is currently connected.

## Recovery and projection

The recovery states are `MATCHED`, `UNANCHORED_TAIL`,
`LEDGER_ROLLBACK_DETECTED`, `DIVERGED`, `WITNESS_UNAVAILABLE`, and
`NOT_INITIALIZED`. Only `MATCHED` permits normal governance projection.

## Governance recursion boundary

The Governance Ledger is protected by the External Tail Anchor. The witness
receipt is independently retained and is not another event inside the same
ledger. The ledger cannot prove its own completeness.

## Release boundary

This freeze is ready for Architecture Release Candidate review. It does not
authorize Phase 1C runtime implementation or Phase 2 OpenAI capability.
