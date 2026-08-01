# P1008 Research API Contract v1.0

`openapi.json` is the machine-readable authority for this interface. Phase 1A provides no server implementation.

## Read endpoints

- `GET /api/research-plugin/status`
- `GET /api/research-plugin/owner-review-queue`
- `GET /api/research-plugin/thesis/lineage`
- `GET /api/research-plugin/legacy-reuse-report`
- `GET /api/research-plugin/agenda`
- `GET /api/research-plugin/knowledge-gaps`
- `GET /api/research-plugin/research-debt`
- `GET /api/research-plugin/research-health`

Owner dispositions for agenda, gaps, debt, health and other queued research items use one append-only endpoint:

- `POST /api/research-plugin/owner-review/{review_item_id}/disposition`

This endpoint records a Plugin-owned review event. It cannot mutate or delete prior events and cannot apply an effective war-room change.

## Candidate-run endpoints

- `POST /api/research-plugin/run/daily`
- `POST /api/research-plugin/run/weekly`
- `POST /api/research-plugin/run/monthly`
- `POST /api/research-plugin/run/epistemic-review`

Run endpoints are manual, return a job id and share the core war-room job lock. They are not enabled in Phase 1A or Phase 1B.

## Thesis-candidate endpoints

- `POST /api/research-plugin/thesis/propose-change`
- `POST /api/research-plugin/thesis/owner-approve`
- `POST /api/research-plugin/thesis/owner-reject`

`owner-approve` records Owner disposition on a research candidate only. It never activates a thesis, changes effective weight, changes HOLD/MIDR, enables a rule, writes CSV or touches Runtime SQLite.

## Security and concurrency

- Bind only to `127.0.0.1`.
- POST requires JSON, same-origin request and ephemeral `X-P1008-Session` token.
- The token is not an OpenAI credential and must rotate on App server restart.
- A research job receives `409` while update, news scan, report generation, Owner publish or another research job holds the shared lock.

## Forbidden interface

No endpoint may contain or implement publish, buy, sell, add, trim, position change, rule enablement, formal CSV write, Runtime SQLite write, HOLD change or MIDR change.
