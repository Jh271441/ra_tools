# Task lifecycle visibility

Default task visibility excludes `superseded` and `cancelled`. Their assignments,
submissions, revisions, progress and lifecycle audit remain stored. This applies
to allocation batches, Campaign lists, current-user task discovery and the labeling
summary task selector. A single `task_lifecycle_where` predicate filters before
limits/pagination. Closed/draft tasks keep their existing visibility and read-only
behavior; they are not silently deleted or reactivated.

Task APIs accept `lifecycle=current` (default), `history` (superseded/cancelled),
`all`, or one explicit lifecycle. Supported endpoints:

- `/api/cases/work-splits`: administrator allocation list; `assigned_to_me=true`
  uses verified identity. Returned `metrics` aggregate exactly the returned scope;
  personal metrics count the current user's assignment slots.
- `/api/review-work-splits`: minimal task options; default/current options only
  allow ongoing review. Explicit history exposes read-only metadata/can_review=false.
- `/api/campaigns`: list counts and page content share the lifecycle predicate.
- `/api/labeling/tasks`: default task picker excludes terminal tasks; an explicit
  history filter can still read their task/progress metadata.

Allocation UI offers Current tasks / Historical tasks / All tasks and My tasks.
The same selection drives cards, metrics and pending/completed counts. It persists
in the URL (`lifecycle=history&assigned_to_me=true`) and is part of the list cache
key. Changing filters clears stale details and invalidates pending requests.

Historical cards display Superseded/Cancelled explicitly and offer audit/review
records plus read-only task detail. They have no Open Review/source-filter links,
reassignment controls or editable Issue links. Campaign audit detail likewise
keeps terminal Issue rows as text. Task-context lookup rejects inactive/read-only
tasks, while existing Case/model write guards remain authoritative. Explicit
historical detail reads query that exact split, independent of default list limits,
so progress never falls back to zero merely because the task is hidden by default.

Regression coverage checks current/history/all and personal filters, filtering
before limits, exact historical detail, preserved label/model revisions and audit,
summary task options, metrics, route persistence, cache changes and stale historical
UI payloads. No schema migration, physical deletion or constraint bypass is used.


The allocation heading keeps scope, My tasks and batch count on one compact
baseline on desktop, with wrapping and touch-sized controls on phones. The
unselected My tasks toggle is neutral; only its pressed state uses the accent
fill. Keep these rules in assignment-composer.css and final phone overrides in
mobile.css so the legacy heading-child grid rule cannot stack the toolbar.
