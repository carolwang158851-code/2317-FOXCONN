# Contract Freeze Record

- Contract: `P1008_RESEARCH_GOVERNANCE_CONTRACT`
- Version: `1.0`
- Phase: `1A_RESEARCH_CONTRACT_LAYER`
- Freeze status: `FROZEN_PENDING_OWNER_ACCEPTANCE`
- Implementation status: `NOT_STARTED`
- OpenAI calls: `DISABLED`
- Actionable: `false`

## Frozen scope

1. All schemas under `schemas/`.
2. All policies under `policies/`.
3. Event names and transition rules under `events/`.
4. Ledger record and append-only rules under `ledgers/`.
5. API paths, request/response shapes and forbidden endpoints under `api/`.
6. Governance validation criteria under `validation/`.

## Change control

- No frozen file may be edited in place after Owner acceptance.
- Clarifications that change semantics require `v1.1`; breaking changes require `v2.0`.
- A new version must include migration impact, compatibility notes and Owner approval.
- Runtime implementation bugs are fixed in implementation code; they do not silently change the contract.
- Owner acceptance of v1.0 does not authorize Phase 1B implementation or OpenAI use.

## Model independence

The contract does not name a required OpenAI model. A future Agents SDK implementation must map typed outputs to these schemas and must pass deterministic post-model validation. Changing model or SDK cannot weaken governance fields, source requirements, evidence linkage, write boundaries or Owner gates.

## Acceptance phrase

```text
OWNER_ACCEPT_P1008_RESEARCH_CONTRACT_V1.0
```

