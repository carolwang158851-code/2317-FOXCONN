# P1008 Research Plugin Skeleton

Phase 1B is a controlled, local-only implementation of the frozen P1008
Research Governance Contract v1.0.

## Scope

- Verify the frozen contract root and local references.
- Read authority-listed CSV and approved runtime JSON snapshots.
- Validate events, append test-only JSONL ledgers, rebuild projections, and
  replay them deterministically.
- Expose an isolated loopback-only `GET /api/research-plugin/status` test
  endpoint.

## Non-scope

- No OpenAI package, API key, model call, tracing, agent, or tool.
- No Launcher or existing App server integration.
- No formal CSV, rule manifest, Runtime SQLite, warroom runtime, report,
  schedule, position, trade, HOLD, MIDR, or IC mutation.
- No write under the package workspace. Ledger tests use a temporary root
  outside the repository that mirrors contract-relative paths.

## Local verification

```powershell
python -m unittest discover -s modules/p1008_research_plugin/tests -p "test_*.py" -v
python modules/p1008_research_plugin/src/p1008_research_plugin/shadow_runtime.py --check
```

The implementation uses only the Python standard library. Its schema checker
implements the deterministic subset needed by the Phase 1B status contract;
it does not claim to replace a complete Draft 2020-12 validator.

## Ledger limitation

The frozen hash chain detects modified records, invalid sequence, unknown
events, and partial JSONL truncation. A complete valid suffix deletion cannot
be detected after restart without a separately frozen external tail anchor.
Phase 1B does not invent that authority. Tests requiring a known record count
pass the expected count explicitly and surface the limitation for future
contract review.
