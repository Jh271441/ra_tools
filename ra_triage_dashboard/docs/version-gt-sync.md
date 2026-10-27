# Version dataset GT synchronization

Version selectors now resolve to the original source scopes of their registered
members, including incremental version scopes that have no file-backed baseline.
The existing authoritative Trail reader and atomic snapshot writer are reused.

- Synchronize each complete original source, not a filtered page or target subset.
- Preserve Issue source scopes, frozen references, human labels/reviews,
  assignments and immutable model predictions. Trail remains read-only.
- Preserve the configured source allowlist. Unknown sources fail closed.
- Require complete responses and unchanged membership before applying a snapshot.
  Retrying unchanged input reuses the immutable snapshot.
- New incremental members invalidate freshness even within the periodic interval.
- Empty/unmapped authoritative values remain missing; never substitute TE or model
  predictions for GT.
- The UI shows only the selected dataset's source status. Missing GT is not a
  model mismatch: comparison shows the existing neutral N/A state.

Validation covers source aliases, partial responses, concurrent membership changes,
snapshot replay, lock release, configured allowlists and the frontend comparison
and status-selection behavior. Local full suite: 1023 passed, 14 skipped before
the final lock regression; final focused suite: 69 passed. Responsive checks use
the actual UI with synthetic read-only data, not production submissions.

## Release verification

Released as `2021f5a114835ce1454ec1104f038ef517e27c06` with frontend cache684.
Exact-SHA cloud tests: 1031 passed, 7 skipped. Isolated gray and production
PostgreSQL health checks passed; four served static resources matched the release.
The existing scheduled worker completed the new sources successfully. Remaining
unmapped authoritative values were checked separately, not coerced into GT.
Production browser navigation timed out; signed-in visual verification is not
claimed. Local UI checks covered 1440px Chinese/dark and 320/390px English/light.
