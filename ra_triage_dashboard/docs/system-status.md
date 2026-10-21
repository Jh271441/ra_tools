# System status

`/system-status` is a read-only diagnostic page. Service/database/backup health
is independent of dataset media coverage. No controls on this page change
permissions, migration policy, model publishing or capture execution.

## Media coverage

- Bind each provider to the members actually loaded at baseline registration.
  Intersect BEV manifest IDs, captured MP4 IDs and complete nine-frame Camera IDs
  with those members. Extra shared-cache IDs cannot inflate a dataset count.
- BEV and video counts are independent. Video status uses the same metadata,
  supported layouts and root-confined file resolution as the player; missing,
  malformed or escaping media never counts as ready. Duplicate captures count
  once per Issue. Coverage indexes have short single-flight caches.
- Both `complete` and `verified` layout receipts can finish the media lifecycle,
  only with full publication/verification, full scoped coverage and no capture
  errors. Missing media remains partial; a registration failure remains blocked.
  Full publication without a completed audit remains verifying.
- Each row displays member/BEV/video/Camera fractions and a readable state with
  missing counts. The media table spans the grid; on narrow screens only its
  labelled region scrolls horizontally. Other card values wrap instead of
  silently truncating. Missing statistics render an em dash, never fabricated0.
- `/api/status` and `/api/baselines` read a cheap process-local snapshot. A single
  daemon observer refreshes expired media counts off the request path. Initial
  reads report pending without counters; refreshing retains the last snapshot.
  Successful snapshots are fresh30 seconds; errors retain prior counts, report
  unavailable and back off15 seconds. No source scans were added to `/health`.
- Membership generation invalidation prevents old observers from publishing
  obsolete results. The current status page polls every2 seconds only while
  counting; request sequence plus page/URL/epoch checks discard old timers and
  responses. Navigation rebinds/cancels polling, including bootstrap's final
  same-page render. Ready/error snapshots stop polling.

## Other cards

Historical review data is informational and shows effective named read modes;
an empty migration-policy list shows the existing-record mode with a neutral
badge. It is never a hardcoded warning or a restriction on current review writes.
Backend policy/audit records remain unchanged.

The model gateway card says configured because configuration is the evidence
available there; it does not claim a successful model request. The dashboard
publication switch is explicitly separate from scheduled daily inference and
publication. Raw Trail connection diagnostics are available in a details control.

Regression checks: test_media_coverage.py, test_video_assets.py,
test_baseline_lifecycle.py, test_system_status.py and system_status_ui.cjs.
