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
- Empty/unmapped authoritative values remain outside canonical GT; never substitute
  TE or model predictions for GT.
- The UI shows only the selected dataset's source status. Missing GT is not a
  model mismatch: comparison shows the existing neutral N/A state.

Validation covers source aliases, partial responses, concurrent membership changes,
snapshot replay, lock release, configured allowlists and the frontend comparison
and status-selection behavior. Local full suite: 1023 passed, 14 skipped before
the final lock regression; final focused suite: 69 passed. Responsive checks use
the actual UI with synthetic read-only data, not production submissions.

## Original Trail values

Review preserves `out_of_scope` and `未接起` verbatim in the GT badge and shared
GT multi-select, including URL restoration, mixed selections and pagination.
These are observations, not additional classifier categories: canonical GT stays
empty, comparison stays N/A, and three-class metrics/labels remain unchanged.

For sparse sources, the authoritative reader saves recognized original values in
immutable snapshot metadata. Reads use only the active local snapshot and return
the current Issue's `gt_raw_label`, not the full source observation map. A raw-only
change produces a new content hash; identical refreshes are idempotent. Complete
responses, source membership checks and atomic application still apply. A later
canonical value takes precedence; a later empty observation clears stale raw data.

Existing sparse snapshots without the observation marker are refreshed through the
normal GT worker. This does not write Trail, change exclusions, alter assignments
or rewrite frozen references. No schema migration is required.

## Release verification

Released as `2021f5a114835ce1454ec1104f038ef517e27c06` with frontend cache684.
Exact-SHA cloud tests: 1031 passed, 7 skipped. Isolated gray and production
PostgreSQL health checks passed; four served static resources matched the release.
The existing scheduled worker completed the new sources successfully. Remaining
unmapped authoritative values were checked separately, not coerced into GT.
Production browser navigation timed out; signed-in visual verification is not
claimed. Local UI checks covered 1440px Chinese/dark and 320/390px English/light.
