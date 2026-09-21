# Manual S1–S3 smoke report — 2026-09-21

## Result

The API/DB smoke completed with **11 PASS, 0 FAIL**. Follow-up CUA browser acceptance added one PASS; the overall result is **12 PASS, 0 FAIL, 0 NOT_RUN, and 1 OUT_OF_SCOPE**. The cloud test suite completed with **533 passed, 2 skipped** in 25.37 seconds.

Candidate branch: `codex/model-review-s3`  
Candidate SHA: `53c9e67cfc5b9a95ea81b89643808ef39520d8e3`

## Runtime and boundaries

| Service | Result |
|---|---|
| Smoke app | `127.0.0.1:8786/manual-s3`, build `53c9e67cfc5b9a95ea81b89643808ef39520d8e3`, PostgreSQL, 44 migrations |
| Production app | `:8785`, build remained `5fdc41ba8b0215170a8307237762e1ed50a9aaf2`; no production deploy, write, or migration was performed |
| Smoke persistence | `DASHBOARD_POSTGRES_PERSISTENT_DATA=false`; the smoke database is separate from the persistent app database and its backup schedule |
| External write flags | Trail sync/write, Batch prediction, AutoTriage push, and D-Chat notifications were disabled |

The smoke app used a subset-only baseline registry and `DASHBOARD_SEED_EXAMPLES_ENABLED=false`. The smoke database and report artifacts remain on cloud_server; the sampled Issue IDs and manifest were not copied to this workspace.

## Sampled scopes

The builder manifest SHA-256 is `5cf7180adce0369b18cb0fdd7fab1db579156cb48327814717bb937362846c6a`. The selected Issue-set SHA-256 is `45fe114d241a8cc86c6fea807452a71ec989ea354d9ca2cd802d474a0f0ed9ba`.

| Baseline | Source members | Hash sample | Pinned additions | Final sample |
|---|---:|---:|---:|---:|
| 0508 | 1,071 | 107 | 1 | 108 |
| 0206 | 1,326 | 133 | 0 | 133 |
| 0626 | 300 | 30 | 3 | 33 |
| 0522 | 100 | 10 | 0 | 10 |
| 0821 | 1,242 | 124 | 5 | 129 |
| **Total** | **4,039** | **404** | **9** | **413** |

All five sampled memberships matched their active GT snapshot membership hashes. The normalized GT mismatch count was zero.

## Verification matrix

| Area | Result | Evidence |
|---|---|---|
| S1 Run/reviewer isolation | PASS | API smoke confirmed distinct Run A/Run B heads, full detail audit history, and Run-scoped discussion isolation. In the browser's specified target Issue, the shared Label block matched across Runs; neither Run had a saved S3 head or discussion, and the human reason stayed blank with `pending` status in both |
| S2 unchanged snapshot reuse | PASS | Reused the active snapshot in all five scopes |
| S2 changed content and export reconciliation | PASS | Same content reused one snapshot; two changed contents produced new immutable snapshots; historical facts stayed unchanged; reconciliation returned `not_applied=1`, `matched=1`, `changed_again=1` |
| S2 conservative legacy backfill | PASS | Original preflight had 0 eligible and 80 ambiguous rows skipped. One marked synthetic row was eligible in dry-run and apply; repeat dry-run/apply reported it already migrated, and the repeat apply did not add a revision/head |
| S3 status and projections | PASS | Gallery and Reason Analysis each returned the filtered smoke row; CSV and XLSX included the Model Review status; all four status facets and reviewer identity counts were present; shadow comparison was `matched=1`, `different=0`, `new_only=5` |
| S3 write boundaries | PASS | No-Run Review and comment writes were both rejected with HTTP 400; shared Label/GT fields stayed outside Model Review |
| S3 binary attachment API | PASS | Multipart PNG upload linked to one Model Review revision; API read-back hash matched stored metadata; temporary row and file were removed |
| Interactive browser acceptance | PASS | Built-in browser verified the base path, five-dataset joint filter and 413-row result, pagination, Run A/B detail state, Model Review status options, Reason Analysis and export entries, GT update/reference display, HTTP 200 responses, and no console errors or SSO redirect |
| 5,000+ candidate probe | PASS | 9,040 total candidates across five scopes; page, keyset scan, EXPLAIN, and cleanup checks passed |
| Final database integrity | PASS | 413 Issues, 0 FK orphans, 0 references outside the selected set, 0 GT snapshot mismatches, and 0 remaining attachments, notification rows, or queued jobs |
| Verified SSO WorkSplit acceptance | OUT_OF_SCOPE | This is an identity/permission-specific S4 scenario. SSO remained disabled; no verified WorkSplit write was attempted |

## Browser acceptance details

The in-app browser reached `http://127.0.0.1:8786/manual-s3/review` with base path `/manual-s3` and the expected smoke build. All five dataset options were visible; selecting all five produced 413 rows, and Next moved the page from 1–20 to 21–40. The specified target Issue showed the same shared Label status (`GT 待复核`, one source) in both requested Runs. It had no saved S3 head or comments on either Run, so the human reason remained blank and status remained `pending`; the reviewer field showed the current unverified session identity. The displayed model prediction reason followed the selected Run.

The Model Review filter exposed `pending`, `in_progress`, `completed`, and `blocked_by_label`. The Reason Analysis page and CSV, XLSX, and GT update export entries were visible. The selected baseline's GT update time and shared Label reference were displayed. The captured page reload produced 57 HTTP 200 responses, no failed network requests, no console errors or warnings, and no SSO redirect. The viewport screenshot was visually inspected; no screenshot file was retained.

## Overview and facet counts

Overview and Model Review facets report different projections. Overview selects one effective Review per Issue and may fall back from the selected Run to unbound or prior-Run evidence. Model Review facets count current heads per reviewer on the exact selected Run. Their totals are therefore not expected to match.

| Run slot | Overview: effective Issue statuses | Facets: current heads |
|---|---|---|
| A | `in_progress=1`, `completed=1`, `blocked_by_label=1` | `pending=1`, `in_progress=3`, `completed=1`, `blocked_by_label=1` (6 heads) |
| B | `completed=3`, `blocked_by_label=1` | `completed=3` (3 heads) |

Run A has multiple reviewers with heads on some Issues, so the head facet is larger than the one-per-Issue projection. Run B's `blocked_by_label=1` comes from the Overview's prior-Run fallback; the strict Run B facet contains three completed heads. Do not use these two aggregates as an equality check.

## Performance probe

The probe restored the verified logical backup with SHA-256 `083a19ed8f05a713bb4ddeee187bab7ad04b60302894aa6b0820ffcd28872047` into a disposable clone. The original five scopes contained 4,039 candidates; 5,001 synthetic candidates were distributed round-robin across those scopes, for 9,040 total. The clone was dropped after the report was saved.

| Measurement | Result |
|---|---:|
| Insert 5,001 synthetic Issues | 1.496 s |
| First 100-item candidate page | 3.153 s |
| Full keyset scan | 9,040 rows in 23 batches, maximum batch 400; 21.124 s |
| `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` planning / execution | 2.052 ms / 2,404.354 ms; 100 rows returned |
| Probe rows after cleanup | 0; all five scope counts restored |

The plan used `issues_pkey`, `idx_annotations_work_split_author`, `idx_review_work_assignments_issue`, and `review_work_assignments_pkey`. It also used sequential scans for the small legacy annotation and work-split relations. The restored pre-S3 backup had no Model Review heads, so the separate `completed` status count was zero; the reported EXPLAIN measured the nonempty five-scope candidate page without a Review-status predicate. These timings are measurements of this smoke clone, not production SLOs.

The performance probe script was byte-identical in the final branch; later candidate commits only changed the smoke runner.

## Cloud artifacts and cleanup

Private cloud reports are stored under:

- Smoke report: `/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s3_smoke_20260921/s1-s3-smoke-report.json` (0600)
- Performance report: `/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s3_perf_20260921/performance-report.json` (0600; the performance database itself has been dropped)
- Backfill dry-run/apply receipts: `/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s3_smoke_20260921/backfill-synthetic-*.json` (0600)
- Verified source backup: `/volume/home/workspace/ra_triage_dashboard_data/postgres_backups/ra_triage_dashboard-20260921T045915Z.dump`

The smoke app remains available on loopback port 8786 for acceptance. After acceptance, stop only the smoke session and remove its disposable database and experiment directory:

```bash
tmux kill-session -t ra_triage_dashboard_s3_smoke
sudo -n -u postgres dropdb manual_s3_smoke_20260921
rm -rf /volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s3_smoke_20260921
rm -rf /volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s3_perf_20260921
```

Do not use those cleanup commands while the smoke app is still needed for acceptance.
