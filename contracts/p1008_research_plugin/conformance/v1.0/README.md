# P1008 Research Contract Conformance Suite v1.0

This suite validates the frozen Research Governance Contract without changing
the frozen `v1.0/` directory or implementing the Research Plugin runtime.

## Required gates

1. Backward Compatibility Test
2. Ledger Replay Test
3. Deterministic Research Test
4. Contract Drift Monitor
5. OpenAI Capability Boundary Test

Run from the repository workspace:

```powershell
python CODEX_P1008_PACKAGE/contracts/p1008_research_plugin/conformance/v1.0/run_contract_tests.py --all
```

The runner uses only the Python standard library. It makes no network or
OpenAI API calls. Reports are written under `reports/`; no formal CSV, rule
manifest, Launcher file, Runtime SQLite database, or frozen contract artifact
is modified.

The deterministic gate checks are application-governance tests. SDK
guardrails are treated as defense in depth, not as the authority for Source,
Evidence, Anti-Fantasy, Legacy Reuse, Warroom Adapter, or Owner decisions.
