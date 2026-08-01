# Capability Retirement Policy

Status: `ACTIVE_FOR_PHASE3A`

Retirement is a governed lifecycle transition, not file deletion.

## Requirements

- An Owner approval reference is mandatory.
- Retirement first creates a review candidate.
- A candidate does not change runtime or registry state.
- Manifest deletion is prohibited.
- History and replay events must be preserved.
- Artifact hashes must remain available for audit.
- Retirement may not create production side effects.

## Rationale

Preserving the declaration and history allows a retired capability to remain
auditable and replayable. Reusing its identifier for unrelated behavior is not
allowed; a replacement capability must use a new manifest or an explicitly
approved compatible version.
