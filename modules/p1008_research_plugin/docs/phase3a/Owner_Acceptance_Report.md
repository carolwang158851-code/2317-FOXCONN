# Phase 3A Owner Acceptance Report

Authorization basis: Owner instruction to proceed with Phase 3A as a governed
capability framework before any production research capability.

Status: `TARGETFILES_VERIFIED`

## Accepted scope

- Capability manifest and contract validation
- Deny-by-default registry
- Enable/disable lifecycle policy
- Deterministic health, compatibility, retirement, replay, and conformance
- Echo Research retained as the sole mock-shadow capability
- Five future capabilities registered but disabled

## TargetFiles

The following 45 paths are the complete and exclusive Phase 3A change set,
relative to `modules/p1008_research_plugin/`:

```text
config/phase3a/capability.schema.json
config/phase3a/capability_registry.json
config/phase3a/capability_lifecycle_policy.json
config/phase3a/capability_health_policy.json
config/phase3a/capability_compatibility_policy.json
config/phase3a/capability_retirement_policy.json
config/phase3a/manifests/echo_research.json
config/phase3a/manifests/financial.json
config/phase3a/manifests/macro.json
config/phase3a/manifests/news.json
config/phase3a/manifests/deep_research.json
config/phase3a/manifests/foreign_flow.json
src/p1008_research_plugin/capabilities/__init__.py
src/p1008_research_plugin/capabilities/versioning.py
src/p1008_research_plugin/capabilities/manifest.py
src/p1008_research_plugin/capabilities/contract.py
src/p1008_research_plugin/capabilities/registry.py
src/p1008_research_plugin/capabilities/policy.py
src/p1008_research_plugin/capabilities/lifecycle.py
src/p1008_research_plugin/capabilities/health.py
src/p1008_research_plugin/capabilities/retirement.py
src/p1008_research_plugin/capabilities/compatibility.py
src/p1008_research_plugin/capabilities/replay.py
src/p1008_research_plugin/capabilities/conformance.py
src/p1008_research_plugin/capabilities/framework.py
tests/phase3a/__init__.py
tests/phase3a/replay_events.json
tests/phase3a/registry_expected.json
tests/phase3a/test_manifest_contract.py
tests/phase3a/test_registry_policy.py
tests/phase3a/test_lifecycle_replay.py
tests/phase3a/test_health_compatibility.py
tests/phase3a/test_phase3a_governance.py
tests/phase3a/test_phase3a_golden.py
docs/phase3a/Phase3A_Architecture_Report.md
docs/phase3a/Capability_Manifest_Specification.md
docs/phase3a/Capability_Contract_Specification.md
docs/phase3a/Capability_Lifecycle_Policy.md
docs/phase3a/Capability_Health_Specification.md
docs/phase3a/Capability_Retirement_Policy.md
docs/phase3a/Capability_Compatibility_Report.md
docs/phase3a/Capability_Replay_Report.md
docs/phase3a/Capability_Conformance_Report.md
docs/phase3a/Owner_Acceptance_Report.md
docs/phase3a/Phase3A_Closure_Report.md
```

## Non-authorized scope

No changes are authorized to frozen v1/v2 contracts, Phase 2A runtime,
Launcher, Warroom, status APIs, formal CSV, SQLite, Ledgers, reports, scheduler,
network connectors, OpenAI SDK/configuration, or production execution.

This report accepts only the listed TargetFiles and does not authorize a future
phase or a new capability implementation.
