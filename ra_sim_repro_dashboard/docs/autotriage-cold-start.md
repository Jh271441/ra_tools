# AutoTriage cold-start reads

2026-11-15: the AutoTriage overview/Issue routes use a read-only evaluation
navigation catalogue instead of waiting for ordinary simulation KPI calculation.
Startup reads overlap the React/chunk download and are consumed once, only for
the exact URL and within 15 seconds. Explicit refreshes and mutations discard
startup receipts. A canonical URL reuses the board that established it; actual
navigation, profile changes, retries and later revision changes still refresh.
Profile editing data is fetched when settings opens.

The comparison read retains the existing source, target, preparation and lineage
audits, behavioral timing overlay and source distribution. It queries release
keys directly and omits board-only plans, starts, request state and execution
history. Approved targets avoid unrelated legacy target discovery. Timing ledgers
are filtered by release in SQL and still undergo schema/content-hash validation.
No cache invalidation rules, metric definitions, database schema or operational
submission behavior changed.

Validation: 416 backend tests, 114 frontend tests and the production build passed.
On the existing service database, six serial fresh-process, read-only transactions
compared live/candidate results. Three cold comparison runs had medians 2.1721s /
1.6721s (23.0% reduction); queries fell from 147 to 105. All six complete JSON
responses had SHA256
`0cae4759c8f122b52549fb2fe67ea4241fa467288a55bff1e8c4004ae3589d19`.
This measures application-cache cold computation; PostgreSQL/OS caches were not
flushed and the live service was not restarted for the baseline.

Before deployment, Codex IAB with browser HTTP cache disabled observed ordinary
versions waiting 9.751s, comparison 5.253s and the overview chunk starting at
6.098s. These browser/network observations are separate from the controlled
backend timings. Publication/acceptance evidence is retained under the configured
service's `operations/cold-start-20261115/` directory.

Published source: `a2413c03` (API/source/assets) plus `53eb0463` (active-catalogue
badge/assets). Only the API was restarted; runtime configuration stayed
byte-identical. The preflight detected a live-only ordinary simulation `release`
query alias; it was preserved with a regression test before publication.

IAB acceptance with the HTTP cache disabled observed the last initial API response
at 10.457s before / 3.420s after (one observed browser pair, affected by network and
server state). Comparison itself took 5.253s / 2.738s. The initial requests changed
from ordinary versions + board + profiles + comparison to evaluation versions +
board + comparison; chart code is preloaded. Both missing-date and missing-profile
entry URLs canonicalized without a duplicate board or comparison. The saved
10-30 KPIs remained 88.6% reproduction, 40.8% precision, 79.4% recall and 99.7%
coverage; 11-06 explicitly retained its saved-results fallback.

Responsive browser checks covered 1440px desktop, 320px English/dark and 390px
Chinese/light, including settings, a deliberately blocked catalogue GET and
successful retry. No page-level horizontal overflow was observed. These were
viewport checks, not physical-device/soft-keyboard tests. Language/theme, network
blocking, HTTP-cache override and viewport override were restored after testing.
The settings rule list loaded on opening; applying a different rule was not
performed in production because automatic approval review rejected that action
as potentially triggering recalculation. Profile transition/race behavior is
covered by the unit regressions. Acceptance screenshot and before/after resource
timings are retained alongside the service release evidence.
