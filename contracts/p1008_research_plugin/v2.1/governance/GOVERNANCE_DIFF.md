# v2.1 Candidate Governance Diff

The immutable v1.0 Contract and accepted v2.0 overlay are unchanged.

This candidate adds only the GFS-1 filesystem boundary:

- capability-to-root authorization for Research Plugin, Ledger, report,
  Official IR, AnySearch staging, generated report, and log outputs;
- package-relative containment and denial of sibling/external paths;
- hard denial of `.git`, Production data, UI, contracts, modules, inventory,
  archive, Launcher, Production SQLite, arbitrary Temp, and OneDrive roots;
- traversal and symlink/junction/reparse fail-closed behavior;
- repository lifecycle operations remain forbidden capabilities.
- Official IR and AnySearch writers use their exact runtime capabilities;
- Owner Communication output, copies, browser profile, and profile cleanup use
  one central capability with exact owned-child deletion;
- common atomic mkdir/replace/unlink operations re-authorize their targets;
- final-review construction is separated behind `MAINTENANCE_CAPABILITY`, and
  only its exact run-owned `_pipeline` child may be recursively removed.

No historical acceptance, receipt, root hash, conformance assertion, or
authority artifact is replaced. Owner acceptance is required before this
candidate can become authoritative or be promoted to Production.

Real Windows symlink creation remains privilege-dependent in tests. A
check-to-use race against a concurrently mutating privileged process remains a
residual operating-system risk; the implementation still fails closed on every
reparse point visible at authorization and immediately before atomic replace or
tree deletion.
