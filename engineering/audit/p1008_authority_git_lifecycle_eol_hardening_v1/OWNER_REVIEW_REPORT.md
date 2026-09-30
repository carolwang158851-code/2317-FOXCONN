# P1008 Authority ↔ Git Lifecycle + Hash/EOL Hardening V1

## Result

Hardening B implements a read-only, fail-closed Authority/Git sync evaluator while preserving the separation between formal authority and Git canonical identity.

- Canonical base: `cd25bfa7961c0f17f1a652d973d54245b70da975`
- Canonical remote/ref: `github` / `refs/heads/main`
- Current observed status: `SYNCED`
- Formal authority files changed: `0`
- `.gitattributes` changed: `NO`
- Automatic Git commit/push: `NO / NO`

## Governance preflight

The specified authority root was read in the required order. It is the preserved operational/forensic worktree and was not modified.

| File | SHA-256 |
|---|---|
| `rules/AGENT.MD` | `29A14BC2C394699B9B181C45FA2B3756F7FB477011B7102C825B3388DB75DB7D` |
| `rules/SKILL_v12.md` | `8A89350EEBCF08C87C4F735A86294B0CB378360D718C32512A8E2B755B044A3C` |
| `rules/CODEX_DELIVERY_CHECKLIST.md` | `A1C0785BEE19D922D7BC95E2CB9CA9B1F4DDF99E799492C806E52E6EC2964FB7` |
| `SOP_v4.html` | `1620D1405397667CFFEF00D95DCA0B8C7D6ADB59FE3088248CACA28E795E221A` |

No blocking semantic conflict exists: the Owner authorization explicitly freezes hardening A as canonical, and implementation starts from direct-verified `github/main` at `cd25bfa…`.

## Identity model

Domain A keeps existing exact-byte SHA-256 authority semantics. Production entries use `authoritativeFiles[].sha256`; governed research-current-state entries use `nonAuthoritativeFiles[].currentSha256`; the manifest and Owner approval lineage govern the set. No normalization is introduced into formal validation.

Domain B uses `git hash-object --path <path> <file>` and compares the resulting attribute-aware blob OID with the same path in the direct-query canonical commit. Raw checkout SHA-256 is never presented as Git canonical identity.

The detailed eight-path audit is in `AUTHORITY_GIT_IDENTITY_MATRIX.json`.

## Lifecycle and integration

The evaluator returns only `SYNCED`, `PENDING`, or `BLOCKED`. `BLOCKED` is never converted into `PENDING`. `PENDING` leaves `formalAuthorityValid=true` and does not affect KPI eligibility, formulas, scoring, actionable state, or Owner publish success.

The existing app status infrastructure exposes explicit evaluation at `GET /api/p1008/authority-git-sync`. After a successful Owner formal publish job, the same read-only evaluation is recorded in app state without changing the publish result. The Owner publisher itself is unchanged and performs no automatic Git operation.

## EOL/hash determination

All governed paths already have explicit `text eol=lf`; current index and checkout forms are LF. Isolated repositories with `core.autocrlf=true` and `core.autocrlf=false` both preserve formal exact-byte validation and produce the same path-aware Git identity.

The historical manifest incident was reproduced exactly: CRLF raw SHA-256 `6E4D…B218` and LF raw SHA-256 `449E…ADC9F` differ, while semantic text and path-aware Git blob identity are equal. No `.gitattributes` change or Owner EOL policy decision is required.

## Mutation boundary

The evaluator has a read-only Git command allowlist (`remote`, `ls-remote`, `hash-object`, `ls-tree`) and explicitly rejects `add`, `commit`, `push`, `merge`, `rebase`, `reset`, `stash`, and `clean`. It writes neither authority files nor Git state.

## Acceptance

| Gate | Pre-commit result |
|---|---|
| New Authority/Git lifecycle | `10/10 PASS` |
| New EOL/hash determinism | `3/3 PASS` |
| Hardening-A canonical remote | `8/8 PASS` |
| Existing canonical governance | `9/9 PASS` |
| Authority | `41/41 PASS` |
| PR #33 targeted | `24/24 PASS` |
| KPI Supplement focused | `251/251 PASS` |
| Relevant regression | `57/57 PASS` |

The final local commit identity and post-commit rerun are reported to the Owner after the commit gate completes. No merge or push is authorized by this task.
