# Typed Output Specification

The Phase 2A candidate has exactly these top-level fields:

```text
claims
evidence
counter_evidence
knowledge_gaps
sources
confidence
limitations
owner_review_required
actionable
```

Claims require non-empty evidence ids. Evidence requires registered source ids.
Missing evidence cannot be inferred or default-filled. Unsupported claims fail
validation and must be represented as knowledge gaps by a future authorized
capability. Confidence is limited to high, medium, low, or insufficient_data.

Unknown top-level or nested fields fail closed. `actionable` is always false.
Canonical JSON uses sorted keys, compact separators, UTF-8, and rejects NaN.
