# S2 GT / Label snapshot rehearsal (local design)

This document is a release preparation recipe. It is not an instruction to
connect to production from a developer workstation. The disposable PostgreSQL
rehearsal described below has not been run yet.

## Disposable PostgreSQL restore

1. Use a sanitized backup artifact already provisioned for testing, or create a
   deterministic fixture in a local disposable PostgreSQL database. Verify its
   checksum and `pg_restore --list` output. Do not connect to production to
   obtain rehearsal data.
2. Restore that artifact into two newly created disposable PostgreSQL 14
   databases owned by the test role.
3. Record public table counts and the migration count in both databases before
   applying 043 to one of them.
4. Apply migration 043 to the upgraded copy and compare public table counts,
   migration count, and `dashboard_change_revision` with the untouched copy.
5. Run the snapshot backfill tool once without `--apply` and compare the
   non-sensitive scope/member/coverage report. Source-file byte SHA and loader-
   derived Issue-membership SHA are separate checks; compare the five scope
   counts and hashes without printing per-Issue labels. Run it with `--apply`
   twice; the second run must reuse every content-identical snapshot.
6. For one strict and one sparse scope, compare active snapshot membership,
   `membership_sha256`, `content_sha256`, active pointer, `gt_sync_labels`, and
   `issues.gt_label`. Change one sparse source label to an unmapped value and
   verify the new snapshot stores an empty label and clears the current Issue
   cache.
7. Create a diagnostic Label result snapshot for a frozen Workset, compare item
   counts and source-link counts, then create a second snapshot after a new Label
   revision. The first snapshot must remain unchanged.
8. Exercise GT export preview/download/reconcile in the disposable database:
   `matched`, `not_applied`, and `changed_again` must be per-item and the batch
   summary must distinguish export/download from later Trail-value observation.
9. Run the PostgreSQL same-scope concurrency test with two independent Database
   instances/connections against the disposable database:
   `DASHBOARD_TEST_DISPOSABLE_POSTGRES_URL=<disposable-url> python3 -m unittest ra_triage_dashboard.tests.test_gt_snapshot_postgres_concurrency`.
   Start two sync writers together for one scope, then verify the active
   snapshot item, `issues.gt_label`, `gt_sync_labels`, and `gt_sync_state` all
   describe the same winning snapshot. The test deliberately leaves uniquely
   named fixture rows; discard the disposable database after the run.
10. Record all comparisons, stop the disposable databases, remove their data and
   credentials, and retain only the non-sensitive result summary.

## Rollback boundary

Migration 043 is additive. Before a production release, the deployer must create
and verify a backup and run the disposable restore checks. Application rollback
can return to the prior SHA while retaining the new snapshot tables and facts;
no old application may be assumed to understand the new tables. Snapshot rows and
active pointers are never deleted as rollback cleanup. A later forward migration
must reconcile any pointer/overlay state rather than rewriting history.
