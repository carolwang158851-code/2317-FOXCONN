# Prompt Specification

## Prompt files

- `system_prompt.md`: non-authority and epistemic rules.
- `runtime_rules.md`: Phase 2A capability and persistence boundaries.
- `capability_prompt.md`: Echo-only behavior.

## Role isolation

System, runtime, and capability instructions occupy separate system messages.
Normalized request content is serialized into one user message and is never
concatenated into system instructions.

## Required principles

The prompt validator requires explicit statements that the provider is not the
authority or decision maker, unknown remains unknown, output is typed, and
actionable is always false.

Prompt injection is rejected before prompt construction. Prompt text is local,
versioned source and no remote prompt registry is used.
