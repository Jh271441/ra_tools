# Manual S5 Run Collections smoke report

Recorded: 2026-09-22 (Asia/Shanghai)

## Scope and current state

This is an isolated manual S5 experiment, not a production release. The feature branch is
`codex/run-collections-s5`; the S5 source and current remote source receipt are
`1f2b4e0cbc43fdb552ed375aa6e911759bdb35d`.

The S5 app is healthy on loopback `127.0.0.1:8786/manual-s5`. It uses the dedicated
PostgreSQL database `manual_s5_smoke_20260922_runcollections`, with migration 47 and
5,415 Issues after the full cloud test suite. The API status reports PostgreSQL with
`persistent_data=false`. Anonymous session status is read-only (`can_write=false`);
Batch prediction, AutoTriage push, and D-Chat notifications are disabled.

Production remained on `0.0.0.0:8785`, PID 10634, build
`5fdc41ba8b0215170a8307237762e1ed50a9aaf2`. A read-only database query found 4,046
Issues and 43 migrations in `ra_triage_dashboard`. S5 uses its own database and did not
run a production deployment, merge, or PR.

## Product and performance checks

- The full cloud pytest suite passed at `9883724`: 565 passed, 1 skipped, in 44.12 s.
  Later commits through `1f2b4e0` only changed the S5 setup/recovery scripts.
- The recovery path was exercised: exact frozen S4 source `bf745129e4e7359db3631c18ee60da3e20ab74f2`
  was restored on loopback 8786 using an S5-owned copy of the pre-S5 S4 database, then
  the S5 switch script returned the service to the pinned S5 SHA. Current health and
  source receipt both report `1f2b4e0`.
- Browser preflight covered the Run Comparison workbench with a 5,000-Issue context,
  multi-run columns and paging, metrics/confusion controls, model-review state, the
  pairwise-save control, and the export route under `/manual-s5`. This used a local SSH
  tunnel to the S5 service, which remained bound to remote loopback 8786; no public
  browser listener was opened.
- The 5,000-Issue × 2-Run PostgreSQL benchmark completed in about 2,824.5 ms. The
  prediction lookup plan used `Index Scan using idx_predictions_issue_run` (observed
  index-node time 0.019 ms).

## Database isolation and preservation

Read-only counts taken during final verification:

| Database | Issues | Migrations | Purpose |
| --- | ---: | ---: | --- |
| `manual_s3_smoke_20260921` | 413 | 44 | S3 fixture |
| `manual_s4_smoke_20260921` | 413 | 44 | Earlier S4 fixture |
| `manual_s4_smoke_20260921_campaign` | 413 | 46 | S4 Campaign fixture |
| `manual_s5_s4_restore_20260922` | 413 | 46 | S5-owned S4 restore copy |
| `manual_s5_smoke_20260922_runcollections` | 5,415 | 47 | Active S5 app database |
| `manual_s5_acceptance_20260922` | 5,415 | 47 | S5 acceptance database |
| `ra_triage_dashboard` | 4,046 | 43 | Production database |

The original S4 Campaign database was compared with its pre-S5 dump after recovery;
there were zero differing public tables.

### Recovery incident and fix

The first rollback rehearsal launched a mutable S4 source tree whose bootstrap changed
the S4 fixture's `issues` and `dashboard_change_revision` tables. We detected this,
restored the original S4 fixture from the pre-S5 dump, and verified that all public
tables matched the snapshot. Production was not involved. The recovery scripts were
then hardened to launch the exact frozen S4 commit and use the S5-owned
`manual_s5_s4_restore_20260922` database copy. That corrected recovery path was
exercised before leaving S5 on 8786.

## Host observations

During the read-only production health check, `/health` reported `ok=true` and the
expected production build, while its `deployment_mode` field read `development`.
The S5 API status also reported 98.3% volume use (about 131 GB free). No production
configuration or storage change was made as part of this isolated S5 task.
