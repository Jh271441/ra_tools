# GT periodic freshness

Released 2026-10-27 11:19:45 CST as e6fa6737d9c3008296dc95d1cb10bae757922773.

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
or fixed by the GT change.

## Independent release

Rebased on the separately published0821 partition version ad4b424. Only the two
GT backend files, freshness tests and this document changed; frontend cache677,
No GT UI/mapping, partitions and source membership are unchanged.

Exact-SHA cloud suite:1010 passed,7 skipped. Gray18789 used isolated SQLite and
disabled GT/Trail/notification writers. Production verified PostgreSQL/schema58,
81 effective settings unchanged, health and exact frontend resource bytes.
Release receipt: `/volume/home/workspace/ra_triage_dashboard_deploy/releases/20261027T031536Z-e6fa6737d9c3/result.json`.

System-Python wrapper failed before switch because psycopg was unavailable;
resumed under the dedicated runtime with clean exact-SHA worktrees, unchanged
production PID/config and saved passing test log, then rechecked gray. No duplicate
full test run, schema change, notification replay or adjudication UI release.

Postrelease periodic worker completed all18 configured scopes at11:22:41 CST;
every scope reports ready/periodic and this cycle changed0 labels. This verifies
automatic remote reads resumed, not merely the enabled flag. It does not claim
observation of the next30-minute cycle.
