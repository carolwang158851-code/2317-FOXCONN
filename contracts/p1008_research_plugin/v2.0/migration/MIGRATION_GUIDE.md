# P1008 Research Governance v1.0 to v2.0 Migration Guide

Status: `FUTURE_IMPLEMENTATION_GUIDE_ONLY`

This guide does not authorize or perform migration.

## Preconditions

1. Approve exact Runtime TargetFiles in a separate phase.
2. Select and qualify an L3 `EXTERNAL_APPEND_ONLY` or L4
   `HARDWARE_MONOTONIC` witness.
3. Approve connector, credential, retention, key rotation, outage, and recovery
   policies separately.
4. Keep OpenAI, Launcher, formal CSV, SQLite, and Warroom decision effects out
   of the migration scope.

## Required future sequence

1. Verify the accepted v1.0 manifest and root.
2. Verify the accepted v2.0 manifest, root, conformance evidence, and Owner
   acceptance.
3. Load v1.0 as the research-domain authority.
4. Load v2.0 as the additive governance overlay.
5. Create an Owner-authorized Governance Genesis event binding v1 root, v2
   root, Git baseline, Phase 1B implementation commit, and first qualifying
   witness receipt.
6. Build the Governance Projection only after anchor state is `MATCHED`.
7. Run rollback, suffix deletion, receipt rollback, divergence, outage,
   deterministic replay, and crash-recovery tests.
8. Bind the implementation and validation evidence through governance events.
9. Obtain separate Owner acceptance for the implementation.

## No automatic conversion

- Existing v1 ledgers are not rewritten or imported into the Governance
  Ledger.
- Existing Runtime snapshots are not upgraded by this freeze.
- Failure to obtain or verify a qualifying receipt leaves Research OS
  unavailable while preserving the core Warroom.
- A v1-only Runtime must continue reporting v1-only capability and cannot
  report v2 conformance.

## Rollback

Before implementation acceptance, rollback means disabling the new v2 Runtime
candidate and returning to the unchanged v1-only skeleton. Frozen v1 and v2
contract artifacts are never edited during rollback.
