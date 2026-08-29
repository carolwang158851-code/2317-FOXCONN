# P1008 Phase B1-OPS Launcher and Report Library Recovery

## Scope

This change repairs Launcher/report-library operations only. It does not start
Phase B1.5 or Phase B2, call an external model or research service, or mutate
formal authority, rules, decision state, or Runtime SQLite. Every generated
brief remains `actionable=false`.

## Reproduced stale-report cause

The default Launcher job previously ran Daily Price, Market Activity, and News
steps, then refreshed App state. It never invoked the periodic report generator
and did not own a separate rolling output. Consequently, data/news state could
advance while `reports/generated/latest_report.html` and the report-library
manifest remained at an older explicit report run.

## Current versus archived lifecycle

- The default Launcher job atomically overwrites
  `runtime/current_warroom_brief.json` and
  `reports/generated/latest_report.html`.
- Those rolling artifacts are not report cards and never append either archive
  manifest.
- Archive creation remains limited to explicit report work: weekly, monthly,
  quarterly earnings, major events, or an explicit Owner manual archive.
- The explicit periodic report generator writes a unique dated Markdown/HTML
  artifact and synchronizes both archive manifests. It no longer owns the
  rolling `latest_report.html` path.

## R2 tracked UI and first-run bootstrap

- The Command Center is tracked at
  `ui/P1008_WARROOM_COMMAND_CENTER_v24.html`; Launcher, legacy UI, report
  library, report viewer, SOP, and package preflight use this path only.
  Production navigation never depends on the git-ignored `output/` directory.
- The original local v24 source was copied byte-identically. Its provenance,
  source and destination SHA-256 values are recorded in the R2 tracked-UI
  source receipt.
- On a true first run, when both archive manifests are absent, Launcher creates
  the same versioned empty payload at both paths and records
  `REPORT_LIBRARY_BOOTSTRAPPED_EMPTY`. This creates no archive report or card.
- A single missing manifest, an invalid manifest, or a semantic mismatch is a
  fail-closed Owner-review condition. Launcher must not reconstruct history.

## Fail-closed identity and health checks

- A localhost server can be reused only when its resolved package root and Git
  HEAD exactly match the requested checkout.
- Server status publishes `resolvedPackageRoot`, `gitHead`,
  `authorityManifestSha256`, and a per-process `serverInstanceId`.
- The runtime and reports archive manifests must be semantically identical.
- The rolling JSON contains a canonical governed-content SHA-256 computed with
  the hash field excluded from its own preimage. The HTML embeds that same hash
  and must byte-match the deterministic rendering of the governed JSON.
- Any report-library health status other than `PASS` returns
  `REPORT_LIBRARY_FAIL_CLOSED`; Launcher disables both the New UI and Research
  Library links until identity is restored.
- Both missing manifests are `FIRST_RUN_UNINITIALIZED` and may be bootstrapped
  by one normal Launcher run. Partial loss, invalid JSON, or divergent
  manifests return `FAIL_CLOSED` and require Owner review rather than a fake
  Daily Report.
- `reports.html` and `report_viewer.html` reject unsupported interactive
  `file://` use instead of presenting stale content as current.

## R1 cutoff alignment

- The rolling payload preserves independent Daily Price and Market Activity
  cutoffs under `dataCutoffs`.
- `dataAlignmentStatus=ALIGNED` is allowed only when both cutoffs match.
- A missing or different Market Activity cutoff is `PARTIAL`; an older activity
  cutoff is additionally marked `marketActivityFreshness.status=STALE`.
- Every rendered price, valuation, volume, turnover, and transaction-count KPI
  displays the cutoff of its own authority source. No missing value is
  forward-filled or replaced with zero.

## External-call boundary

OpenAI API, Web Search, Deep Research, Canva, Gemini, and YouTube calls: `0`.
