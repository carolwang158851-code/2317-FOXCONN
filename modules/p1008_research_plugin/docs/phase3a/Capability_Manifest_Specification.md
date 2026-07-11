# Capability Manifest Specification

Status: `PHASE3A_CONTRACT`

Each capability is declared in one JSON manifest validated by
`capability.schema.json` and the deterministic application validator.

## Required fields

| Field | Rule |
|---|---|
| `capability_id` | Stable lowercase identifier |
| `display_name` | Human-readable name |
| `version` | Semantic version `major.minor.patch` |
| `lifecycle_state` | State allowed by the Phase 3A lifecycle policy |
| `execution_mode` | `MOCK_SHADOW` or `DISABLED` in Phase 3A |
| `provider_id` | Required only for the approved Echo mock |
| `implementation_available` | Must be false for placeholders |
| `enabled` | Must match lifecycle and execution mode |
| `owner_approval_reference` | Required for shadow enablement |
| `allowed_operations` | Empty for disabled placeholders |
| `input_contract` | Declared input boundary |
| `output_contract` | Declared typed output boundary |
| `required_contract_roots` | Exact frozen v1 and v2 hashes |
| policy IDs | Must bind to approved Phase 3A policies |
| `actionable` | Must be boolean `false` |

## Deterministic rejection rules

The validator rejects unknown fields, missing fields, malformed versions,
incorrect contract roots, production modes, enabled placeholders, providers or
operations on disabled placeholders, and any `actionable` value other than false.

A manifest is a governance declaration, not proof that a provider exists and not
authorization to run a capability.
