# P1008 Research Governance Contract v2.1 Candidate

Status: `OWNER_ACCEPTANCE_REQUIRED`

This non-breaking additive governance overlay carries the GFS-1 filesystem
policy delta without changing the immutable v1.0 Contract or the accepted
v2.0 governance overlay.

The candidate adds capability-bound package-relative write roots and explicit
fail-closed filesystem restrictions. It does not authorize Production
promotion, publication, trading, network access, OpenAI, Launcher changes,
formal CSV writes, or Production SQLite writes.

The candidate implementation routes Phase B1, War Report production, Ledger,
Official IR, AnySearch staging, Owner Communication, and common atomic writes
through the central authorizer. Final-review package construction is isolated
behind `MAINTENANCE_CAPABILITY`; its recursive delete is limited to the exact
run-owned `_pipeline` child.

## Normative dependencies

- v1.0 root: `3370C4DBD6B564E2200D051AC07C8507442C130ADE64D770621107FA09D2924D`
- v1.0 manifest SHA-256: `5D213CB4360329FCC969164F559952A0F1545BFE8E53D5CFDFF014B9D5619773`
- v2.0 root: `E056357A8A63A15BCF9FDC286BEE0BDB56E043AF26F4DDCD5624FDB3707BD782`
- v2.0 Git-LF manifest SHA-256: `6A1DFE54BA4FCA749C18FDA747969473A4903CF21001AAACA6078C6CC8FEB75F` (the accepted original hash is preserved by the approved line-ending errata)

The development implementation may validate this candidate for GFS-1R test
evidence. It remains non-authoritative until an Owner acceptance record binds
its final manifest and root hash.

Residual enforcement limits are documented rather than hidden: an unprivileged
Windows test process may be unable to create a real symlink, and filesystem
authorization cannot eliminate all check-to-use races against a concurrently
mutating privileged process.
