# GT periodic freshness

2026-10-27 candidate; not deployed.

`ready` describes a usable successful snapshot, not unlimited freshness. The
periodic worker now compares every configured scope's `last_checked_at` against
`DASHBOARD_GT_SYNC_INTERVAL_SECONDS` (unchanged default: 1800 seconds).

- A successful unchanged read renews freshness; `last_applied_at` is not a timer.
- A ready sparse snapshot with zero valid labels is still fresh until expiry.
- Missing, malformed, timezone-less or future check timestamps require a read.
- A failed/uninitialized scope retries on the next existing worker tick; no tight
  retry loop. A running sync is skipped and the existing reservation lock remains.
- Startup delay, configured scopes, complete-membership checks, sparse label
  normalization, per-scope atomic snapshots and manual-sync API are unchanged.
- No GT write to Trail, no changes to human labels/Review/task assignments,
  baseline membership, Model Runs or media. Existing GT-export reconciliation
  still follows successful authoritative reads.

This change is independent of the unapproved Review decision UI preview. Do not
bundle that preview into a GT-only release. Full release still requires the
project's controlled exact-SHA test and deployment gates.

## Production manual observation

The user triggered the existing authenticated UI sync on 2026-10-27. Read-only
`/api/gt-sync-status` verification confirmed 0508, 0206, 0821,
0821-review-extra and 0821-trail-extra all ready by 11:03:15 CST, with zero
changes in each scope. Valid/member counts: 1071/1071, 1326/1326, 1214/1242,
250/250 and 480/513. The full0821 union remains1944/2005 (61 unmapped/empty).
Other configured scopes were not part of this manual request; their previous
timestamps/counters must not be reported as this run's result.

## Validation

GT-only export of HEAD plus the two backend changes and freshness tests:
997 passed,14 skipped (local dependencies/platform skips). The mixed working
tree also contains the unapproved Review decision adapter; its full run had
3 unrelated frontend test failures,995 passed,14 skipped. These are not hidden
or fixed by the GT change. No production code was released in this task.
