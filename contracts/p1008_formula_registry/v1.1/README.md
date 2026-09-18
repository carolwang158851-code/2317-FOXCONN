# P1008 Formula Registry v1.1

Version 1.1 is the additive RTM-0 production-activation revision of the
canonical `contracts/p1008_formula_registry/` lineage. The hash-governed v1.0
snapshot remains immutable and records candidate approval plus the superseded
`LEGACY_FIXED_0_1` production formula.

This revision activates only `RTM_0_TRUTHFUL_NEUTRAL`:

- RTM score is `0` because no current-period foreign-positioning numeric
  mapping has been separately approved.
- The zero is `NEUTRAL_ZERO_BY_GOVERNANCE`; it is not a fabricated or
  zero-filled foreign observation.
- RTM weight remains `0.10` and weighted raw contribution becomes `0`.
- Current-period fallback remains prohibited.
- MRD remains `MRD-M0 DISPLAY_ONLY`, UD is unchanged, MIDR remains
  `OBSERVATION_ONLY`, and `actionable=false`.

The activation receipt is under `acceptance/`. It distinguishes the earlier
candidate approval from this Owner-authorized production activation and leaves
the implementation commit reference pending.
