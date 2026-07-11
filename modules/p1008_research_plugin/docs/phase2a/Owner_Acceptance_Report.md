# Phase 2A Owner Acceptance Report

Authorization:

`OWNER_APPROVE_P1008_PHASE2A_GOVERNED_OPENAI_RUNTIME_TARGETFILES`

Acceptance status: `PHASE_2A_MOCK_FOUNDATION_ACCEPTED_PRODUCTION_DISABLED`

## Accepted capability

One governed `EchoResearchCapability`, provider-neutral client interface,
typed output, deterministic gates, in-memory artifact envelope, and local mock
tests. This acceptance does not authorize a production OpenAI request.

## TargetFiles

Exactly 50 new files are authorized:

- `src/p1008_research_plugin/runtime/`: 11 files.
- `src/p1008_research_plugin/orchestrator/`: 4 files.
- `src/p1008_research_plugin/prompts/`: 3 files.
- `src/p1008_research_plugin/openai/`: 5 files.
- `src/p1008_research_plugin/validation/`: 4 files.
- `tests/unit/`: 4 files.
- `tests/integration/`: 2 files.
- `tests/governance/`: 2 files.
- `tests/golden_cases/`: 4 files.
- `docs/phase2a/`: 11 files.

All paths are relative to `modules/p1008_research_plugin/`. No pre-existing
file is a TargetFile.

```text
docs/phase2a/Artifact_Specification.md
docs/phase2a/Capability_Registry.md
docs/phase2a/Governance_Validation.md
docs/phase2a/OPENAI_RUNTIME_PRINCIPLES.md
docs/phase2a/OpenAI_Runtime_Specification.md
docs/phase2a/Owner_Acceptance_Report.md
docs/phase2a/Phase2A_Architecture_Report.md
docs/phase2a/Phase2A_Closure_Report.md
docs/phase2a/Prompt_Specification.md
docs/phase2a/Runtime_Boundary_Report.md
docs/phase2a/Typed_Output_Specification.md
src/p1008_research_plugin/openai/__init__.py
src/p1008_research_plugin/openai/client_interface.py
src/p1008_research_plugin/openai/model_registry.py
src/p1008_research_plugin/openai/response_adapter.py
src/p1008_research_plugin/openai/tool_registry.py
src/p1008_research_plugin/orchestrator/__init__.py
src/p1008_research_plugin/orchestrator/lifecycle.py
src/p1008_research_plugin/orchestrator/orchestrator.py
src/p1008_research_plugin/orchestrator/request_dispatcher.py
src/p1008_research_plugin/prompts/capability_prompt.md
src/p1008_research_plugin/prompts/runtime_rules.md
src/p1008_research_plugin/prompts/system_prompt.md
src/p1008_research_plugin/runtime/__init__.py
src/p1008_research_plugin/runtime/artifact_writer.py
src/p1008_research_plugin/runtime/capability_registry.py
src/p1008_research_plugin/runtime/context_builder.py
src/p1008_research_plugin/runtime/prompt_builder.py
src/p1008_research_plugin/runtime/runtime_config.py
src/p1008_research_plugin/runtime/runtime_guard.py
src/p1008_research_plugin/runtime/runtime_health.py
src/p1008_research_plugin/runtime/runtime_manager.py
src/p1008_research_plugin/runtime/runtime_validator.py
src/p1008_research_plugin/runtime/typed_output.py
src/p1008_research_plugin/validation/__init__.py
src/p1008_research_plugin/validation/boundary_validation.py
src/p1008_research_plugin/validation/prompt_validation.py
src/p1008_research_plugin/validation/schema_validation.py
tests/golden_cases/__init__.py
tests/golden_cases/echo_expected.json
tests/golden_cases/echo_input.json
tests/golden_cases/test_echo_golden.py
tests/governance/__init__.py
tests/governance/test_phase2a_boundaries.py
tests/integration/__init__.py
tests/integration/test_echo_pipeline.py
tests/unit/__init__.py
tests/unit/test_capability_registry.py
tests/unit/test_runtime_guard.py
tests/unit/test_typed_output.py
```

## Acceptance boundaries

- Production OpenAI, SDK, API key, network, and tools remain disabled.
- Deep Research, Financial, Macro, Foreign Flow, News, IC, and Decision Engine
  remain disabled.
- Launcher, Warroom, SQLite, CSV, Status API, Ledger, Projection, Governance,
  reporting, trading, notification, and scheduling remain unchanged.
- Every output remains `actionable=false`.
