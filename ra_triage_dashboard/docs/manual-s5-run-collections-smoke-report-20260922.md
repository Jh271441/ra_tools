# Manual S5 Run Collections acceptance report

Recorded: 2026-09-22 (Asia/Shanghai)

## Final deployment

- Branch: `codex/run-collections-s5`
- Final pushed source: `3a72304a8fc999d47ea321cb8093b41bd0948b63`
- Isolated S5 service: `127.0.0.1:8786/manual-s5`
- Final `/health`: `ok=true`, exact build `3a72304a8fc999d47ea321cb8093b41bd0948b63`, base path `/manual-s5`.
- S5 API status: PostgreSQL, migration 48, `persistent_data=false`; Batch, AutoTriage push and D-Chat notifications are disabled.
- Anonymous session: `read_only=true`, `can_write=false`, `verified=false`, `is_admin=false`.
- Production was not released, merged or modified. Port 8785 stayed PID 10634, build
  `5fdc41ba8b0215170a8307237762e1ed50a9aaf2`.

## PASS/FAIL matrix

| Check | Result | Evidence |
| --- | --- | --- |
| Five-scope frozen Workset | PASS | Final PG acceptance used 4,039 Issues across 5 scopes; Workset `run-evaluation-workset-e68c1a4dc3f94a67bafa151399d5d9e5`, scope rows = 5. |
| Shared Labeling Campaign | PASS | Campaign `campaign-c2f2c28b52f04c10902d2fd841280f90`; exact per-scope member sets and GT snapshot references validated. |
| Per-Run Model Review Group | PASS | Group `campaign-group-4988c8331da14e7ea033b3586235b681`; 8 child Campaigns, one per frozen Run. |
| Shared label projection | PASS | Every paged item contains the frozen shared label projection (state, expected output, GT relation, method, source and hash). Changing mutable GT after freeze left the old reference hash and shared projection unchanged. |
| Official reference policy | PASS | GT uses five content-addressed snapshot IDs; resolved Label snapshot `label-result-63aa0b3355f91c2802d1107b987bd9a349b01ca2299a42ec76566453d39d04d0` was accepted as a formal reference. New `reference_type=run` requests are rejected; comparison Run remains only `comparison_reference_run_id`. |
| Compact paged detail | PASS | 4,039 Issues × 8 Runs, page size 50: 111,312 bytes. Public Workset/reference omit full Issue IDs and reference items; only the current page is returned. |
| Complete export | PASS | Export contains all 4,039 items and was 7,826,529 bytes. |
| Content idempotency | PASS | Repeating the same frozen content returned the same Evaluation ID `evaluation-8cba84f8-2ea8-4529-951e-fea55808eeb4`. |
| Metrics readability | PASS | Response exposes Workset count, valid reference count, pairwise-union denominator, per-Run supported coverage, absent/UNKNOWN counts and explicit union semantics. P2P/P2F/F2P/F2F transitions remained Run-comparison metadata. |
| Provenance | PASS | `workset_sha256=e8088ffdceb2d7fab78ebf2676d5ecef31a94199b5698f964304d263838a3eee`; `reference_sha256=a60686dc6a89f4f250f7ec84158438b58a8a23cd4a41827a5e014cbc1427834f`; `scoring_policy_sha256=fa0b81d23fa6472c10c8dd9c8f2866e7064ad19cb48b78b6c83d06d7944e1494`; `exclusion_sha256=c4c8372078a13f81abeffd973e02fffa15bf1ae0031b9e951300e4afc3d7b082`; `context_sha256=f82623751540ac4d4a62b1c75395bc39d8d7ff8ee6eaf2d24cf89e7c179398cc`. Export provenance lists Workset, scope snapshot IDs/hashes/counts, policy and exclusion hashes. |
| Read-only UI gating | PASS | Direct HTML/DOM contract check found the dedicated route, readonly note and hidden write controls; anonymous API session was read-only. |
| Hidden/grid CSS contract | PASS | Explicit `[hidden] { display:none !important; }` rules cover the Evaluation and dedicated page. |
| Dedicated route and URL restore | PASS | `/manual-s5/run-collections` serves `runCollectionsPage`, nav, manager, pairwise foldout and Label reference controls. Collection/revision/context/reference-run/page/query aliases are restored. |
| Full cloud suite | PASS | Final source `3a72304`: **571 passed, 1 skipped** in 63.05 seconds. |
| PostgreSQL query plan | PASS | `idx_predictions_issue_run` index scan; observed execution time 0.030 ms in final acceptance. |
| Production/S3/S4 preservation | PASS | Final read-only counts: S3 `413/44`; original S4 `413/44`; S4 Campaign `413/46`; S5-owned S4 restore `413/46`; active S5 `5415/48`; production `4046/43`. Public table-count comparison between original S4 Campaign DB and S5-owned restore: **0 differences across 69 tables**. |

## Final acceptance receipt

The isolated PG acceptance script used token `93b472f36c`, 4,039 Issues, 5 scopes and 8 Runs.
It completed in 53.025 seconds. It verified:

- immutable GT snapshots, shared projections and historical stability after later GT updates;
- exact Workset scope/member matching for shared Labeling and per-Run Model Review;
- exact context reuse;
- compact detail and full export;
- EXPLAIN index use;
- final collection, Evaluation, Campaign and Task Group IDs recorded above.

The separate Label snapshot acceptance used Workset
`workset-3ac38e92a0d94907b609ade90cec3909`; its resolved shared projection was
`state=resolved`, `method=single`, `gt_relation=matches_gt`.

## Recovery and browser note

The pinned recovery path was exercised after the final source update: exact frozen S4
`bf745129e4e7359db3631c18ee60da3e20ab74f2` restored on 8786, then the guarded switch
returned S5 at the exact final SHA. The first switch attempt exposed an obsolete migration-47
script gate; that gate was corrected to migration 48 before the final successful switch.

The CUA browser kernel was unavailable during the final pass, so the browser check used the
documented HTTP/DOM contract against the loopback service. It verified the final build,
dedicated route markers, read-only session and base-path-safe HTML; no public browser listener
was opened.
