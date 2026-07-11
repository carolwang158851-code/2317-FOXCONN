# Capability Health Specification

Status: `PHASE3A_DETERMINISTIC`

Capability health measures governance readiness, not investment quality,
provider uptime, model accuracy, or production availability.

## Required checks

- manifest validity
- capability contract validity
- boundary enforcement
- typed output declaration
- deterministic replay
- protected-file integrity

## States

| State | Score | Meaning |
|---|---:|---|
| `HEALTHY` | 100 | All governance checks pass |
| `DEGRADED` | 80 | A non-critical governance check is incomplete |
| `BLOCKED` | 0 | A required or boundary check fails |

A `HEALTHY` result does not authorize production execution. The health policy
explicitly forbids a production-health claim, and all outputs remain
`actionable=false`.
