# P1008 External Discovery Provider Contract v1.0

## Purpose and status

This additive contract governs a future external discovery provider. It is
provider-neutral and does not install, execute, configure, or promote any
provider. Until a separate Owner authorization names an approved governed
provider identity and runtime scope, every provider remains `SHADOW`,
`DISCOVERY`, non-actionable, and non-authoritative.

An accepted isolated Shadow validation is evidence about that exact artifact
only. It is not a governed-production approval, a supply-chain pin, an
integration authorization, or permission to make another network request.

## Immutable provider identity and provenance

Each governed provider identity must contain all of the following immutable
fields: `provider_id`, vendor, provider repository or distribution source,
release version, immutable source revision, artifact SHA-256, acquisition
timestamp, and the exact allowed endpoint identities. The source revision and
artifact digest, not a mutable tag or display name, are the supply-chain
identity. A request and its receipt must carry that complete identity; secrets
and query text are never identity fields.

The approved identity must be kept distinct from any Shadow identity. A Shadow
identity may be recorded as validation evidence only and must never be
substituted for, merged with, or silently synchronized into a governed pin.

## Identity mismatch and repin control

Any mismatch among the configured identity, installed artifact, request,
receipt, response provenance, or approved endpoint fails closed before a
network request, retry, fallback, discovery write, evidence promotion, or
authority write. A mutable upstream tag, a new ZIP, or a successful Shadow
test does not override a pin.

A provider repin is a governance-contract and supply-chain change. It requires
separate, explicit Owner authorization that identifies the old and proposed
identities. Before that authorization is effective, the change record must
include migration and compatibility impact, capability delta, regression scope
and results, endpoint and secret-boundary review, and an approved rollback
plan. Rollback restores only the previously approved immutable identity after
its artifact is re-verified; it is never automatic and never rotates a secret.

## Capability, secret, network, and write boundaries

Capabilities are deny-by-default and must be individually allowlisted by the
approved provider contract. Local file input, batch/file expansion, arbitrary
URL extraction, provider-side registration, key creation or rotation,
automatic retry, fallback, persistence, publication, and state mutation are
prohibited unless separately governed and authorized. A provider request may
contain only the minimal public discovery input approved for that request.

An approved secret is process-scoped and ephemeral. It may be supplied only by
the authorized runtime mechanism, never by command arguments, prompts, source
control, receipts, logs, configuration files, or provider-registration flows.
No component may persist, display, derive, rotate, or auto-register a secret.

Each governed identity policy binds exactly one `credential_mode`:
`CREDENTIALS_REQUIRED`, `CREDENTIALS_OPTIONAL`, or `ANONYMOUS_ONLY`. In
`CREDENTIALS_REQUIRED` mode, a missing secret, invalid secret, or secret-loading
failure is `FAIL_CLOSED`, and anonymous downgrade is prohibited. In
`CREDENTIALS_OPTIONAL` mode, anonymous execution is allowed only when it is
explicitly part of the Owner-authorized governed identity policy; an
authentication failure must not silently downgrade to anonymous execution. In
`ANONYMOUS_ONLY` mode, no secret may be loaded or transmitted.

Network access is deny-by-default. A governed request may contact only the
identity-bound endpoint allowlist, only after its authorization gates pass, and
only for the approved attempt count. Unexpected endpoints, redirects outside
the allowlist, unapproved retries, or any filesystem/authority/core-view write
fail closed. A missing required provider runtime or unavailable required
provider capability also fails closed before any network or write operation. A
discovery staging or ledger write, if later authorized, must be non-actionable,
separately receipt-bound, and cannot modify authority data.

## Discovery semantics and promotion evidence

External provider output is `DISCOVERY` only. It cannot confirm a fact, assign
an authority tier, satisfy authority confirmation, change the Core View,
generate or publish a report, or write authority data. Promotion requires
independent validation under the report-governance contract and does not occur
inside a provider adapter.

Before a provider can move from Shadow to governed production, the record must
contain: immutable identity and artifact verification; isolated validation
evidence; capability, secret, endpoint, and write-boundary tests; regression
evidence for mismatch fail-closed behavior; a migration/rollback assessment;
and governed evidence for coverage, precision, source quality,
duplication/noise, validation behavior, failure behavior, and output
provenance. Every evidence dimension is mandatory. Connectivity success and
search or retrieval success are individually and jointly insufficient for
promotion. The record must also contain separate Owner authorization naming the
exact promotion scope. Absent any item, the provider remains Shadow and
stopped.

The machine-verifiable minimum invariants are frozen in
`policies/external_discovery_provider_policy.json`. The policy and this document
must agree; a mismatch fails closed and blocks acceptance.
