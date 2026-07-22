# P1008 Authority Governance Amendment — 2026-07-22

Owner authorization: `P1008-AUTHORITY-GOVERNANCE-AMENDMENT-20260722`

## Versioned authority baseline

| Attribute | Legacy baseline | Current baseline |
| --- | --- | --- |
| Version | `PHASE_2A_FROZEN` | `P1008_AUTHORITY_2026-07-20_V1` |
| Verified files | 5 | 6 |
| Manifest SHA-256 | `8BA304C36C224F1F8ADF78CB871A8200FDA0656BD5824801330EAF6EAF855847` | `8E15782AB300EDB1F17F5043CBAC1B888EFA7F1A2FD9CBB8B43814429949C953` |
| Added path | — | `data/2317_cash_flow_authority.csv` |
| Price cutoff | 2026-07-10 | 2026-07-20 |
| Cash-flow cutoff | — | 2026Q1 |

The legacy SHA is retained in a dedicated fixture as historical freeze evidence. Runtime reads remain fail-closed: the adapter accepts only the exact five-path legacy set or exact six-path current set, validates declared CSV schemas where available, and verifies each file hash. An unknown seventh path, a missing cash-flow file, a hidden ungoverned sixth file under the legacy version, or a cash-flow hash mismatch is rejected.

## Resolved governance conflicts

1. `test_hash_governed_paths_are_exactly_lf_pinned` derives the expected set from the authority manifest. `.gitattributes` now pins the exact cash-flow path and the version fixture with LF; no glob was introduced and no prior path was removed.
2. `test_no_non_target_baseline_changed_by_temp_ledger` previously pinned only the legacy manifest SHA. It now pins the current SHA while a separate version test preserves and verifies the legacy SHA.
3. `test_rule_digest_and_keep_disabled_boundary` previously asserted five files. The adapter now assigns a semantic baseline version, enforces an exact allowlist for that version, and reports six verified current files only after path, declared schema, and hash checks pass.

## Reason and rollback

Reason: the official Hon Hai 2026Q1 cash-flow authority became a sixth governed input. Leaving it outside the exact path contract would make FCF evidence untraceable; accepting arbitrary manifest expansion would weaken the deny-by-default boundary.

Rollback: revert the authority baseline commit to start SHA `150f98ad4ae48cecf58334ac2ae995828aba601a`. Restore manifest SHA `8BA304C36C224F1F8ADF78CB871A8200FDA0656BD5824801330EAF6EAF855847`; do not mutate RULE, HOLD, MIDR, MRD, Runtime SQLite, or other formal CSV files.

All outputs remain `actionable=false`. No OpenAI API, Web Search, Canva, scheduler, trading, or decision-state behavior is introduced.
