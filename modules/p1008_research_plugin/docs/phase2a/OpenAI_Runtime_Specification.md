# OpenAI Runtime Specification

## Interface

`OpenAIClientInterface.generate()` accepts capability id, model id, normalized
context, and a role-separated prompt bundle. It returns a mapping candidate.
The interface contains no provider SDK types and does not own governance.

## Phase 2A implementation

- Provider: `phase2a-mock`
- Model: `phase2a-mock`
- API requests: `0`
- API key access: `0`
- Network access: disabled
- Tools: none
- Production runtime: disabled

`MockOpenAIClient` calls the deterministic Echo handler and increments an
in-memory mock-call counter. It cannot resolve another model or capability.

## Replacement boundary

A future provider adapter must remain behind the same interface and must not
weaken typed output, evidence, source, prompt, boundary, artifact, or Owner
gates. Adding an SDK, key, model, network path, or production configuration
requires a separate Owner authorization and TargetFiles review.
