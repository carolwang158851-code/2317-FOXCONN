# P1008 Research Governance Contract Freeze Record

- Contract: `P1008_RESEARCH_GOVERNANCE_CONTRACT`
- Version: `2.0`
- Phase: `PHASE_1C_V2_CONTRACT_FREEZE`
- Freeze status: `FROZEN_OWNER_ACCEPTED`
- Contract form: `ADDITIVE_GOVERNANCE_OVERLAY`
- Root artifacts: `16`
- Root SHA-256: `E056357A8A63A15BCF9FDC286BEE0BDB56E043AF26F4DDCD5624FDB3707BD782`
- Manifest SHA-256: `2686D044714E435CB4C1E63CB26B3BB555190F9A5BD21FE2C9439473DA998BE6`
- Runtime implementation: `NOT_AUTHORIZED`
- OpenAI: `DISABLED`
- Phase 2: `DISABLED`
- Actionable: `false`

## Normative dependency

The immutable v1.0 Contract remains a normative dependency:

- v1 root: `3370C4DBD6B564E2200D051AC07C8507442C130ADE64D770621107FA09D2924D`
- v1 manifest SHA-256: `5D213CB4360329FCC969164F559952A0F1545BFE8E53D5CFDFF014B9D5619773`

v2.0 adds governance authority and does not replace v1.0 artifacts in place.

## Frozen scope

The 16 files listed in `contract.manifest.json` are the root artifacts. The
manifest, this freeze record, conformance evidence, and Owner acceptance bind
the root but are excluded from it to avoid circular hashing.

## Change control

- Frozen v2.0 root artifacts must not be edited in place.
- Non-breaking semantic changes require a new `v2.x` Contract.
- Breaking changes require a new major Contract.
- Implementation defects are corrected in implementation code and cannot
  silently redefine this Contract.
- A future Runtime must load the accepted v1.0 authority before applying this
  v2.0 governance overlay.

## Authorization boundary

This freeze does not authorize Runtime, Python, witness connectors, network,
credentials, OpenAI, Launcher, Status API changes, SQLite, CSV, rule changes,
report publication, trading, or Phase 2.

## Owner approval token

`OWNER_APPROVE_P1008_PHASE1C_V2_CONTRACT_FREEZE_TARGETFILES`

## Exit state

The v2.0 Contract is authoritative and ready for Architecture Release
Candidate review. Architecture review does not itself authorize implementation.
