# P1008 Phase B1 Analysis and Report Production MVP

## Scope

Phase B1 supports one deterministic event: `MONTHLY_REVENUE`. Its vertical
slice is:

```text
seven-file Authority baseline
→ existing Evidence Packet / official-source gates
→ Analysis v1.0
→ Report Production v1.0
→ long-form and 75-second script candidates
```

No model, network, search, Canva, Gemini, YouTube, scheduler, publisher, or
formal-data writer participates in this slice.

## Layer responsibilities

- Authority: the existing `AuthorityAdapter` verifies the manifest, exact
  seven-file set, bytes, and declared schema. It remains read-only.
- Evidence: the existing `PacketGateway` verifies typed packets, route limits,
  staleness, Evidence IDs, HTTPS locators, and Hon Hai/MOPS official monthly
  revenue sources.
- Analysis: calculates documented comparisons from governed Authority values,
  labels fact versus inference, represents missing data as
  `INSUFFICIENT_DATA`, keeps valuation `DESCRIPTIVE_ONLY` without an approved
  threshold policy, derives event windows from official publication dates,
  stores evidence-bound regime conditions, and emits one typed packet.
- Report Production: formats the validated analysis into twenty ordered
  sections. It cannot read raw CSV/news or change conclusions, Evidence IDs,
  evidence-bound numbers, thesis state, or Authority identity.
- Media scripts: read only a validated `ReportCandidate`; raw CSV/evidence
  paths are rejected. Shorts store a deterministic duration validation and
  keep `actionable=false` in a non-spoken compliance card.

## Evidence lineage

The deterministic fixture reuses the official evidence from approved Shadow
run `P3B-MONTHLY-REVENUE-20260716-LIVE-20260716T034008557264Z-A75FB4F7`:

- `E-DA-MONTHLY-202606-OFFICIAL`
- `E-WEB-MONTHLY-202606-OFFICIAL`
- Hon Hai announcement `/latest-news/2076`
- Hon Hai monthly investor-relations table

The fixture performs no live retrieval. It records fixed timestamps and a
stable deterministic Run ID. Authority-derived statements use explicit
`AUTH-*` Evidence IDs tied to manifest hashes.

## Manual Launcher procedure

1. Open `P1008_APP.bat`.
2. Press **產生分析候選**. The result must be
   `ANALYSIS_CANDIDATE_READY` and show its Run ID/output path.
3. Press **產生戰報候選**. It uses the same Run ID and refuses to proceed if
   Analysis validation is absent or stale.
4. Review files under `runtime/report_production/<run_id>/`.

For the R1 content gate, the offline command below creates one immutable
runtime review package containing analysis/report candidates, editorial and
Shorts-duration validations, evidence lineage, protected-state snapshots, and
the Owner decision marker:

```text
python tools/p1008_build_phaseb1_final_review.py --package-root .
```

These controls are not part of **一鍵更新資料與資訊**. They create no formal
report, database row, scheduled task, or public artifact.

## Fail-closed behavior

Missing/extra/drifted Authority, stale or unsupported evidence, conflicting
official values, unknown vocabularies, missing epistemic fields, Analysis
bypass, report conclusion drift, script raw-input access, non-false
`actionable`, protected-state drift, overwrite, and output outside the runtime
root all stop the run.

## Known limitations and Phase B2 boundary

This MVP supports only governed `MONTHLY_REVENUE` inputs. Event dates,
Evidence IDs, authority identities, periods, and next validation periods are
derived from validated evidence and current manifests; a second offline case
guards against date leakage. PB percentile covers only the current Authority
window, no Owner-approved valuation threshold policy exists, and
benchmark-adjusted return remains unavailable. Market psychology is explicit
inference. Live synthesis, additional event types, video rendering,
Canva/Gemini, scheduling, and publishing require separate Owner authorization
and are not started.

All outputs remain `actionable=false`.
