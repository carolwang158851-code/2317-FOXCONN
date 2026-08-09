# P1008 Report Governance Contract v1.0

This additive G1 contract defines deterministic evidence, trigger, core-view,
publication, model-provenance, threshold-policy, and decision-receipt records.
It neither creates a report nor changes formal authority, a research library,
runtime configuration, or external publication state.

`NO_MATERIAL_CHANGE` is explicitly non-generative: `reportGenerated`,
`archiveReportCreated`, and `libraryAppended` are all false.  The sole approved
formal trigger types are enumerated by the schema; `WEEKLY_SUMMARY` is absent.
Unknown event types fail closed.

Evidence identity is `source_id`, `source_type`, `source_locator`,
`source_tier`, and `source_hash`.  `source_url` is optional, so local and
non-URL authority can be represented. Tier 5 evidence cannot independently
meet the high-quality multi-source core-view criterion.

Core-view eligibility is distinct from a core-view change. Official
confirmation, two independent high-quality sources, financial reflection, or
thesis invalidation can make a proposal eligible; a change remains false until
explicit Owner approval is recorded.

Publication is denied by default. Even a fact-checked, Owner-approved record
can only be `APPROVED_NOT_EXECUTED`; G1-I1 has no external publication path.
Usage and billing metadata in model provenance are optional and never
estimated. Model provenance is operational metadata, not investment evidence.

Private-library eligibility is representable only when a material event is
confirmed, trigger validation passes, report validation passes, and the report
is non-actionable. G1-I1 always leaves `libraryAppended=false`. Stable
`report_key` plus positive integer `revision` represent successive versions of
one governed report family; no retention or upsert operation is implemented.

All cross-platform receipt identity uses the established canonical JSON
serialization in `phaseb1_common`: sorted keys, compact separators, UTF-8, LF,
and no NaN values. This contract does not set business thresholds. A threshold
is usable only when a supplied policy is explicitly Owner-approved.
