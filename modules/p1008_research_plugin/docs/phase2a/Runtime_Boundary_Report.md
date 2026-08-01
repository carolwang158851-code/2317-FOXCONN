# Runtime Boundary Report

Result: `PASS`

## Deterministic rejects

The runtime rejects trading and authority commands including BUY, SELL, LONG,
SHORT, TARGET PRICE, ENABLE, DISABLE, APPROVE, COMMIT, UPDATE, WRITE, and
DELETE. It also rejects prompt-injection patterns before prompt construction.

## State boundaries

- `actionable` must be false at output, claim, evidence, and knowledge-gap level.
- No formal CSV, SQLite, Ledger, Projection, Governance, HOLD, MIDR, IC, rule,
  report, trade, position, notification, or scheduler effect is available.
- Default artifact mode is `MEMORY_ONLY`.
- Test artifact materialization requires an explicit temporary root outside the
  package and is removed by the test harness.

## Configuration boundary

Any attempt to enable OpenAI, network, production, another provider, another
capability, tools, or persistent artifact mode raises a deterministic error.
