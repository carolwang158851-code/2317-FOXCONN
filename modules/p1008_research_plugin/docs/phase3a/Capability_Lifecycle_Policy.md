# Capability Lifecycle Policy

Status: `ACTIVE_FOR_PHASE3A`

## States

`DRAFT -> REGISTERED_DISABLED -> VALIDATED_DISABLED -> SHADOW_ENABLED`

A shadow-enabled capability may return to `VALIDATED_DISABLED`. Registration,
validation, and shadow execution remain non-production states.

Retirement follows:

`REGISTERED_DISABLED | VALIDATED_DISABLED | SHADOW_ENABLED`
`-> RETIREMENT_PENDING -> RETIRED`

## Approval gates

| Event | Owner reference |
|---|---|
| Register | not required |
| Validate | not required |
| Shadow enable | required |
| Shadow disable | required |
| Retirement proposal | required |
| Retirement completion | required |

## Forbidden events

- `CAPABILITY_PRODUCTION_ENABLED`
- `CAPABILITY_AUTO_ENABLED`
- `CAPABILITY_MANIFEST_DELETED`
- `CAPABILITY_GOVERNANCE_BYPASSED`

The policy deliberately defines no production state. Adding one is a breaking
governance change requiring a future Owner-approved contract phase.
