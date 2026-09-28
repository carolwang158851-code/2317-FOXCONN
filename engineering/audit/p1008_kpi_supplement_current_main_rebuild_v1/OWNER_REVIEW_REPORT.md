# P1008 KPI Supplement Current-Main Rebuild & Lineage Hash Repair V1

Status: `KPI_SUPPLEMENT_CURRENT_MAIN_REBUILD_READY_FOR_OWNER_MERGE_REVIEW`

## A. Governance

The required governance sources were read in the specified order before feature import. No blocking conflict was found.

| Order | File | SHA-256 |
|---:|---|---|
| 1 | `rules/AGENT.MD` | `29A14BC2C394699B9B181C45FA2B3756F7FB477011B7102C825B3388DB75DB7D` |
| 2 | `rules/SKILL_v12.md` | `8A89350EEBCF08C87C4F735A86294B0CB378360D718C32512A8E2B755B044A3C` |
| 3 | `rules/CODEX_DELIVERY_CHECKLIST.md` | `A1C0785BEE19D922D7BC95E2CB9CA9B1F4DDF99E799492C806E52E6EC2964FB7` |
| 4 | `SOP_v4.html` | `1620D1405397667CFFEF00D95DCA0B8C7D6ADB59FE3088248CACA28E795E221A` |

`GOVERNANCE_CONFLICTS = NONE`

## B. Current-main baseline

- Remote: `github/main`
- `BASE_HEAD = 449160ee19c5ae9f7050783f89c91dd4a537cdfc`
- Rebuild branch: `agent/p1008-kpi-supplement-current-main-rebuild-v1`
- Previous curated integration: `4182511bc12aff00bb03451cbca70585895f4f0d`
- Previous integration base: `2eaf4a726e66fa81818e80945d5b28b76b6572f0`
- Current main differs from the previous base only in `tools/owner_publish_csv_v2.py` and `tests/test_owner_publish_csv_trade_date.py`.
- The rebuild used the 34 paths in `MERGE_REQUIRED_FILES.json`, checked against `INTEGRATION_COMPONENT_MATRIX.json` and `INTEGRATED_FILE_MANIFEST.json`. Old audit artifacts were not imported.

## C. Publisher-hash failure analysis

`PUBLISHER_HASH_FAILURE_CLASS = STALE_TEST_BASELINE`

| Test | File | Expected before repair | Current-main hash | Why different |
|---|---|---|---|---|
| `test_52_publisher_hash_unchanged` | `tests/test_p1008_kpi_supplement_minimal_ui_binding_v1.py` | `1273A6F44BBF945A3442A9877FD68C285AD701672CAFD39BCE9A3150D972B101` | `9FA584A2F76B931CCB2DDBB32B16F112AAC7B7A3CCD4FEC05111C1D57213E8BB` | Test was authored before PR #33. |
| `test_47_publisher_hash_unchanged` | `tests/test_p1008_kpi_supplement_v1.py` | `1273A6F44BBF945A3442A9877FD68C285AD701672CAFD39BCE9A3150D972B101` | `9FA584A2F76B931CCB2DDBB32B16F112AAC7B7A3CCD4FEC05111C1D57213E8BB` | Test was authored before PR #33. |
| `test_formal_publisher_unchanged` | `tests/test_p1008_t1_derived_kpi_bridge_v1.py` | `1273A6F44BBF945A3442A9877FD68C285AD701672CAFD39BCE9A3150D972B101` | `9FA584A2F76B931CCB2DDBB32B16F112AAC7B7A3CCD4FEC05111C1D57213E8BB` | Test was authored before PR #33. |

History attributes the current publisher to PR #33 commits `934113d` and `48d8bbb`. The untouched current-main PR #33 suite passed 24/24 before import, and the same suite passed 24/24 after integration. Only the three strict expected hashes were repinned; the assertions were not weakened and `tools/owner_publish_csv_v2.py` was not modified.

## D. T1 lineage/hash contract

`T1_HASH_CONTRACT = MIXED`

| Field/artifact | Existing implementation | Contract class |
|---|---|---|
| Source/input candidate hash | `canonical_json_bytes`: UTF-8, sorted keys, compact separators, explicit final LF | `CANONICAL_CONTENT_HASH` |
| T1 envelope/candidate hash | SHA-256 of the fixed canonical envelope bytes | `CANONICAL_CONTENT_HASH` |
| Receipt and manifest hashes | SHA-256 of fixed canonical JSON bytes | `CANONICAL_CONTENT_HASH` |
| Adapter lineage hash | `sha256_file(..., rb)` over the exact adapter file bytes | `BYTE_IDENTITY_HASH` |
| Checked-in deterministic fixtures | Exact equality with canonical serialized bytes, including explicit LF | `BYTE_IDENTITY_HASH` of governed canonical serialization |

The contract is defined in code and tests; it is not `UNDEFINED`. Existing semantics were preserved. `OWNER_HASH_POLICY_DECISION_REQUIRED = NO`.

## E. Line-ending root cause

`T1_LINEAGE_ROOT_CAUSE = GIT_CHECKOUT_AUTOCRLF_ON_UNATTRIBUTED_HASH_GOVERNED_TEXT`

The curated Git blobs and source worktree were LF. The disposable final-sync worktree had `core.autocrlf=true`, and the new adapter/fixture paths were not listed in the repository's path-specific LF policy. Checkout therefore changed exact adapter bytes and exact fixture bytes to CRLF. The adapter byte hash then changed IDs and all downstream T2 objects. JSON values and functional content were otherwise unchanged; the fixture writer itself already emits canonical UTF-8 JSON with an explicit LF and does not use text-mode output.

The six failing tests were:

1. T1 checked-in synthetic bundle equality (three exact fixture files and adapter-bound IDs).
2. T2 inherited T1 adapter byte identity.
3. T2 checked-in candidate equality.
4. T2 checked-in approval equality.
5. T2 checked-in display equality.
6. T2 checked-in reconciliation equality.

Byte evidence from the failed disposable Windows checkout follows. `SOURCE_BRANCH_EOL` is LF for every row; `CURRENT_MAIN_EOL` is `NOT_PRESENT` because these paths did not exist on base main.

| File | Expected hash | Actual failed-checkout hash | Expected EOL | Actual EOL |
|---|---|---|---|---|
| `tools/p1008_t1_derived_kpi_bridge_v1.py` | `4925FDA816CDC529A70E850850C898033C2C593DCDF2940803C0815B63B9B508` | `842FA1FFD61ECE76218C60E4AE706F129042E1AA05E2A9CC29ECB6FF942C7352` | LF | CRLF |
| `contracts/p1008_t1_derived_kpi_bridge/v1.0/fixtures/P1008_T1_WAR_ROOM_CANDIDATE_V1.synthetic.json` | `22A0FD5097CF67FAEFEB3870994C270E3A6D4DF57DF13DCBB98E7F5FAA82089E` | `706EF247445A0D561AF8249293B51AA4076A41A0E5BEECB42257561058A0F81E` | LF | CRLF |
| `contracts/p1008_t1_derived_kpi_bridge/v1.0/fixtures/P1008_T1_VALIDATION_RECEIPT_V1.synthetic.json` | `B2BE30CF76310DDC56031E35A17AE68D9398F9919F43380A192A6BB5EDAEB77D` | `49CE41DD4657B24BC6F0E7DED4F44F54937D3E92D508904997F8DE6832699E58` | LF | CRLF |
| `contracts/p1008_t1_derived_kpi_bridge/v1.0/fixtures/P1008_T1_BRIDGE_MANIFEST_V1.synthetic.json` | `C9443F7D2C15A042D4F0EAC2C15EEFCBA2D21662EC72B9B28448468E52077834` | `AFC52293B0B4867861D072A989A2C3AE0B6682DE6810A0E086370AAF13864D4A` | LF | CRLF |
| `tools/p1008_t2_annotated_use_v1.py` | `643F507A8188AD134A00ABE86D2D5A8DC0C2C8A1A3B99C241588595FA98E0180` | `3E411F0CD69FAA7D9B9F4A2AACABC63C0FF61D60911343C0D3FAFB4B3D420E39` | LF | CRLF |
| `contracts/p1008_t2_annotated_use/v1.0/fixtures/P1008_T2_RESEARCH_CANDIDATE_V1.synthetic.json` | `E6D672461727983065CD07A56F3B318239118A7FA81163E7B89E2F009FDE9441` | `8F6F0401B66156B0AE0D327E70F8E046EDF269032021B1938A7AC2BDF34C62AC` | LF | CRLF |
| `contracts/p1008_t2_annotated_use/v1.0/fixtures/P1008_T2_ANNOTATED_USE_APPROVAL_V1.synthetic.json` | `C16DFC75DBF68348571DED37EED909D3DAADB360F85159625802A85C344C1406` | `E31F666A0D292C3D9033DF0B28E5E91B2A9A6BF476810ED6B3EA1BA05FDDFE30` | LF | CRLF |
| `contracts/p1008_t2_annotated_use/v1.0/fixtures/P1008_T2_ANNOTATED_DISPLAY_V1.synthetic.json` | `C4FA7517CF3B597A2FB63F601C3FEDBCD1C7D97DDB18CBFAD5CA9EB6E457401B` | `545E531FED5566EA2904A6C50114F63012CD9EB22BF8D2F67D240D3A789E6D53` | LF | CRLF |
| `contracts/p1008_t2_annotated_use/v1.0/fixtures/P1008_T2_RECONCILIATION_V1.synthetic.json` | `C8DDDFDA649B3435D1CBE825DB3B287A0DC88071D6F039D5D3F2E2AAF1379219` | `56C4F3A8224D74AA5968FBD2923A08318BB4E0A6D78DA305A893A685BE420D76` | LF | CRLF |

## F. Repair

The narrow repair adds explicit `text eol=lf` entries in `.gitattributes` for the two byte-hashed adapters and the eight deterministic T1/T2 fixture files. This uses the repository's already-established path-specific LF governance, makes checkout bytes independent of developer `core.autocrlf` and editor settings, preserves the committed bytes, and does not normalize data inside the hash functions.

No fixture values were changed or regenerated. Rebuild hashes are again `4925FDA8…` for T1 and `643F507A…` for T2, with zero CRLF sequences in all governed adapters/fixtures.

## G. Feature integration

`FEATURE_CAPABILITIES_COMPLETE = YES`

The exact 34-file required implementation is present: derived KPI contract/validator, T1 bridge, T2 validator and explicit Owner approval gate, KPI resolver, report binding, app-server projection, minimal UI binding, contracts, fixtures, and tests. No new feature or competing implementation was added.

Resolution order remains:

`T0_DIRECT_OFFICIAL > validated T1_EXACT_DERIVED > Owner-approved T2_ESTIMATED_DERIVED > NULL`

`CARRY_FORWARD_ALLOWED = NO`; `DEFAULT_FILL_ALLOWED = NO`; `PROXY_SUBSTITUTION_ALLOWED = NO`. T2 remains `formal_authority=false`, `formal_scoring_eligible=false`, and `actionable=false`.

## H. PR #33 preservation

`PR33_TARGETED_STATUS = PASS`

- Untouched current-main baseline: 24/24 PASS.
- Integrated pre-commit tree: 24/24 PASS.
- Dataset-scoped selection, candidate-date binding, and byte identity of unselected targets are covered by `tests.test_owner_publish_csv_trade_date`.
- Current Windows-checkout publisher SHA-256 remains `9FA584A2F76B931CCB2DDBB32B16F112AAC7B7A3CCD4FEC05111C1D57213E8BB`.

## I. Tests

Pre-commit gates:

| Gate | Result |
|---|---|
| Derived KPI + T1 + T2 + resolver + report/app-server/UI focused suite | 251/251 PASS |
| Relevant canonical/report-trigger/app-server/launcher regressions | 57/57 PASS |
| PR #33 targeted suite | 24/24 PASS |

The focused suite retains repeated-run deterministic tests and exact fixture-byte tests. It passed on this Windows checkout with the repository-level LF rules active.

## J. Protected hashes

Filter-aware SHA-256 comparison against the current-main checkout form passed for all protected files below.

| File | Before / after SHA-256 |
|---|---|
| `data/CSV_AUTHORITY_MANIFEST.json` | `4306D225FDFF0F48AEDEA6C758E7B76EAA5F9FB7735C9FFDB5E9823D75FE465F` |
| `data/2317_master_v9.csv` | `E623CA082F2A080613C33F4155BA8006646E30D6A517DE926AF6108062F84D48` |
| `data/2317_cash_flow_authority.csv` | `082ECA44A96A06F7DAE10DD33CBAF77C75DABA9B1B4DEA27B5B930F8CE8CD95C` |
| `data/2317_daily_price.csv` | `91EEBDB6BC6FD0E85CA2BF537056CAF941246F13412417EDFAE96B16D6DD02D1` |
| `data/2317_daily_market_activity.csv` | `747D4C3BFA40C239B9E2EBB4F39D695F88F186020D19DE310B57CD3D8D432F01` |
| `data/macro_snapshot.csv` | `6BD02B0894139D00D881FF53A6EEEEED404DED21EC782CF54F716665EB25123B` |
| `data/macro_event_observations.csv` | `4A8E1D8079D9E1F9F210222C5383DD69AF17B2F731A2AA5D38485BC07277A64F` |
| `data/fx_trend_observations.csv` | `4F16E86F09F5B9594407084081C81E4D95853DDD30EA3C24B9D9815AAB0F02E6` |
| `launcher.html` | `AFC27FE6440A2DEFE446DB4519B586EFA56474B922A3901A84ABA3FF90DF8150` |
| `index_p1008_v7.html` | `1C10D011BB061FFC43C97877EA3BD8DFD7C24C2DEFF87C4465CD625FB0E7A76D` |
| `tools/owner_publish_csv_v2.py` | `9FA584A2F76B931CCB2DDBB32B16F112AAC7B7A3CCD4FEC05111C1D57213E8BB` |

`PROTECTED_HASH_STATUS = PASS`. Formal CSV authority, authority manifest, publisher behavior, formal scoring inputs, formulas, weights, and core investment logic are unchanged. The existing command-center file receives only the approved minimal additive projection binding; UI architecture is unchanged.

## K. Exact diff

Expected final path count is 36:

- 34 governed feature paths from `MERGE_REQUIRED_FILES.json` (7 runtime, 14 contract, 13 test/fixture).
- `.gitattributes` for the narrow deterministic lineage repair.
- This owner review report.

There are 31 new feature files and 3 modified feature files (`tools/p1008_app_server.py`, `tools/warroom_periodic_report_v1.py`, and `ui/P1008_WARROOM_COMMAND_CENTER_v24.html`). The three publisher repins are inside new required test files. No prior audit bundle was copied. `UNEXPECTED_FILES = 0`.

## L. Commit

- Required message: `P1008: integrate KPI supplement on current main`
- Exactly one local integration commit is authorized after all gates pass.
- The commit SHA is intentionally reported in the external owner handoff because a file cannot contain the hash of the commit that contains that file.
- Merge: not executed and not authorized.
- Push: not executed.
- `ACTIONABLE = false`.
