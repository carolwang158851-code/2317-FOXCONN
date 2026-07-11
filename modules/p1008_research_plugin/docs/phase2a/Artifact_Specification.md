# Artifact Specification

## Envelope

Each validated output produces an immutable in-memory envelope containing:

- deterministic artifact id;
- logical locator under `runtime/research_plugin/artifacts/`;
- SHA-256 of canonical typed output;
- copied typed payload;
- `persisted=false`;
- `actionable=false`.

The logical locator describes a future governed store and is not written in
Phase 2A. `write_test_only()` is restricted to an explicit sandbox outside the
package. Integration tests use a temporary directory and delete it on exit.

No artifact can update Runtime, Ledger, Projection, Governance, Status API, or
Warroom state.
