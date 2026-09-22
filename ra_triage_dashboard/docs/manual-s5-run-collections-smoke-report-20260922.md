# Manual S5 Run Collections acceptance report

Recorded: 2026-09-22 (Asia/Shanghai)

## Final deployment

- Branch: `codex/run-collections-s5`
- Validated runtime source: `b5466899a2d405c4d82ebd0f913cd7201a1dc102`
- Isolated service: `127.0.0.1:8786/manual-s5`
- Active database: `manual_s5_smoke_v3_20260922`, built from the frozen S4
  fixture and migrated through PostgreSQL migration 49
- Final `/health`: `ok=true`, exact build and base path `/manual-s5`
- Anonymous session: `read_only=true`, `can_write=false`, `verified=false`,
  `is_admin=false`
- Batch, AutoTriage publish, Trail writers and DChat notifications are disabled
- Production was not released, merged or modified. Port 8785 remains build
  `5fdc41ba8b0215170a8307237762e1ed50a9aaf2`, migration 43 and healthy.

## Final gate matrix

| Check | Result | Evidence |
| --- | --- | --- |
| Full cloud suite | **PASS** | 575 passed, 1 skipped in 56.69 seconds. The PostgreSQL integration suite used a fresh disposable database and executed migration 49. |
| GT reference fail closed | **PASS** | An Evaluation request against a scope without an active GT snapshot was rejected. Mutable `issues.gt_label` was not promoted to an official reference. |
| Five-scope frozen Workset | **PASS** | 4,039 Issues across 5 scopes; Workset `run-evaluation-workset-443f2863b4374b8fb0bb5b838208eedb`, with five immutable scope rows. |
| Shared Labeling Campaign | **PASS** | Campaign `campaign-12130148f4a342448952f223bb0f040d` matched the complete multi-scope Workset and its per-scope GT references. |
| Per-Run Model Review Group | **PASS** | Group `campaign-group-1eea404255b34b2c840bbec026d0a40d` contains 8 independent child Campaigns. |
| GT and shared human Label separation | **PASS** | Issue `e863b48d1e-0-0000` froze GT reference `误触发` and shared human Label `正确触发`, state `resolved`, relation `differs_from_gt`, sourced from revision 1032. Later GT and Label updates did not change the old context. |
| Shared Label projection | **PASS** | The Evaluation freezes S1 states `none/pending/conflict/stale/resolved`, expected output, GT relation, method, task/revision/source summaries and content hash once per Issue. Run columns remain prediction/model-review only. |
| Multi-scope Label references | **PASS** | Five partial immutable Label result snapshots were created from the same multi-scope Workset, one per scope, and consumed by Evaluation `evaluation-4ec6bf15-c3c1-423d-9910-5b11da9f0fb5`. |
| Official reference policy | **PASS** | New formal contexts accept only GT or Label result snapshots. `reference_type=run` is rejected; `comparison_reference_run_id` is used only for transition analysis. |
| Context content idempotency | **PASS** | Two PostgreSQL connections concurrently requested identical content and both returned `evaluation-dd70cbbe-1e95-4519-81d0-0be9a9f66971`; the database contains one matching context hash. Transaction serialization races are retried from a fresh snapshot. |
| Pairwise shadow reconciliation | **PASS** | Established pairwise and S5 v1 union metrics agreed on total 4,039, both Runs' correct/accuracy/prediction counts, and transitions `P2P=0`, `P2F=2020`, `F2P=2019`, `F2F=0`. |
| Compact paged detail | **PASS** | 4,039 Issues × 8 Runs, page size 50: 109,240 bytes in the direct acceptance call and 100,954 bytes through HTTP. The response omits complete Issue/reference arrays. |
| Complete export | **PASS** | Full JSON export contains 4,039 items and measured 7,578,865 bytes. |
| Metrics readability | **PASS** | API/UI distinguish Workset count, valid-reference count, v1 pairwise-union denominator, supported coverage over all valid references, absent predictions and UNKNOWN outputs. |
| Provenance | **PASS** | Page and export expose Collection revision/hash, Workset ID/hash/scopes, every scope snapshot ID/hash/count, policy version/hash, exclusion version/hash and context hash. |
| Read-only UI gating | **PASS** | Anonymous users keep history, paging and export; create, rename, revision, freeze and Campaign actions are hidden or disabled with an explicit read-only message. |
| Dedicated workspace and URL restore | **PASS** | `/manual-s5/run-collections` hosts the complete manager; Pairwise keeps a collapsed shortcut. Collection/revision/context/reference Run/page/query restore from the URL. |
| Hidden/grid CSS contract | **PASS** | Explicit `display:none !important` rules cover hidden Evaluation and workspace elements. |
| PostgreSQL query plan | **PASS** | Prediction lookup used `idx_predictions_issue_run`; observed execution time was 0.016 ms. |
| Production/S3/S4 preservation | **PASS** | Production stayed `4046/43`; S3 and S4 fixtures were not used as S5 write targets. The final v3 database is independent and non-persistent. |

## Final acceptance receipt

The v3 acceptance used token `e863b48d1e`, 4,039 synthetic Issues, 5 scopes and
8 Runs. It completed in 58.643 seconds. The sanitized receipt is stored at:

`/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s5_smoke_v3_20260922/logs/s5-v3-acceptance-receipt.json`

The active v3 database contains the 413 inherited S4 smoke Issues plus the 4,039
acceptance Issues, for 4,452 total rows. The previous S5 database remains as
read-only evidence and is no longer connected to port 8786.

## Recovery and browser note

The frozen S4 build was restored as a guarded intermediate state before the final
8786 switch. The v3 switch then verified production identity, exact source,
migration 49, external writer gates and anonymous read-only access.

The CUA browser kernel remained unavailable during this final pass. HTTP and DOM
contract checks verified the dedicated route, read-only controls, base-path-safe
assets, compact Evaluation response, shared Label column and snapshot provenance.
No public browser listener was opened.
