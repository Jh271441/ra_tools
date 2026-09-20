# S2 GT / Label snapshot rehearsal (local design)

This document is a release preparation recipe. It is not an instruction to
connect to production from a developer workstation.

## Disposable PostgreSQL restore

1. From `cloud_server`, create a custom-format logical backup with the existing
   Dashboard backup script and verify its checksum and `pg_restore --list` output.
2. Restore the dump into a newly created disposable PostgreSQL 14 database owned
   by the test role. Keep the production database URL and physical data path out
   of logs and shell history.
3. Record public table counts and the migration count before applying 043.
4. Restore the dump into a second disposable database, apply migration 043, and
   compare public table counts, migration count, and `dashboard_change_revision`.
5. Run the snapshot backfill tool once without `--apply` and compare the
   non-sensitive scope/member/coverage report. Run it with `--apply` twice; the
   second run must reuse every content-identical snapshot.
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
9. Record all comparisons, stop the disposable databases, remove their data and
   credentials, and retain only the non-sensitive result summary.

## Rollback boundary

Migration 043 is additive. Before a production release, the deployer must create
and verify a backup and run the disposable restore checks. Application rollback
can return to the prior SHA while retaining the new snapshot tables and facts;
no old application may be assumed to understand the new tables. Snapshot rows and
active pointers are never deleted as rollback cleanup. A later forward migration
must reconcile any pointer/overlay state rather than rewriting history.
