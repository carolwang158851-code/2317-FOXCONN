# P1008 Current Contract Conformance v1.1

The v1.1 suite is an additive phase-routing layer. It does not modify or
reinterpret the frozen v1.0 contract. The phase is selected from the versioned
Owner acceptance record, never from a branch-name substring.

The phase-aware entrypoint performs two independent checks:

1. archive the accepted legacy commit, restore only the historical Windows
   worktree newline bytes explicitly recorded by v1.1 metadata, and run its
   unchanged v1.0 suite, where `modules/p1008_research_plugin` must be absent;
2. run this v1.1 suite against the current checkout, where the accepted module
   must exist and every read-only, non-actionable governance boundary remains
   enforced.

Both GitHub `push` and `pull_request` events use the same command:

```powershell
python contracts/p1008_research_plugin/conformance/run_phase_conformance.py --all --no-write-report
```

The runner is standard-library only and makes no OpenAI, Web Search, Canva, or
market-data network call. Unknown, missing, or contradictory phase metadata is
fail-closed.
