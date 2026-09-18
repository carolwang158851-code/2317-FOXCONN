# P1008 Formula Registry v1.0

This contract lineage records formula definitions, provenance, lifecycle state,
Owner decisions, backtest evidence, and implementation status independently.
It does not activate a formula, change a formal decision, or authorize an action.

Lifecycle classifications are `CURRENT_PRODUCTION`,
`OWNER_APPROVED_CANDIDATE`, `RESEARCH_ONLY`, `REJECTED`, and `LEGACY`.

The canonical registry is `formula_registry.json`. Owner decisions are durable
records under `acceptance/`; a candidate approval is not an activation receipt.
Every artifact governed by this version is hashed in `contract.manifest.json`.

For this version:

- `MIDR.RTM` remains the legacy fixed score of `0.1` at weight `0.10`.
- `RTM-0_TRUTHFUL_NEUTRAL` is Owner-approved as the preferred candidate but is
  not activated.
- `MIDR.MRD_WIRING` remains `DISPLAY_ONLY`.
- `MIDR.UD` is unchanged and protected from reinterpretation.
- All outputs remain `actionable=false` and `productionActivation=false`.

