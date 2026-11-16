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

## 2026-11-16 follow-up

The metric overview/Issue board now requests `view=metrics`. This returns release
names and latest source counts directly from snapshot columns, without auditing
every ordinary simulation publication to build navigation options. Settings keep
the same release options; simulation pages and older clients retain the default
full catalogue. Startup prefetch and React use the same exact URL.

Aggregate metric reads calculate timing overlays without copying saved Issue
rows that they never return. Issue/detail projections still isolate their nested
row data. Source attribution reuses the fully validated label-resolution receipt
and membership flags for equal trigger/label pairs, preserving NULL, empty strings,
literal labels, mapping and source consistency checks.

Large execution receipts and legacy base selections are retained only within one
clean GET and reused by its nested audits. Every new request still checks the
existing database/configuration revision; worker/operational calls bypass the
memo. Failures, different Sessions and uncommitted changes cannot reuse it.
Explicit release validation reads only a snapshot ID before context loads its
payload. No TTL, invalidation policy, metric definition or persistent data changed.

Validation: 422 backend tests, 114 frontend tests, 13 deployment tests and the
production build passed. Three serial pairs of fresh-process read-only comparisons
had medians **1.8207s before / 1.2354s after** (32.1% reduction), with queries
**106 / 95**. All six complete responses had SHA256
`2a33a0687cfe27984675a3f04cf59f6cac2aa8fac4928322a4ba59eb24248495`.

Another three serial fresh-process pairs ran the three initial API handlers
concurrently, matching the 11-06 overview's release/profile/date URLs. Total
median was **2.5514s / 1.4762s** (42.1% reduction). Board median was
**1.2522s / 0.3622s**. The complete response sets matched after projecting the
intentionally slimmer navigation catalogue to its shared `release/source_count`
fields (SHA256 `6e9c5eee39f3f383d4c1442efcf0768c02a7778f49d82f0f255877ce5efcf2c1`).
Application caches were empty in every process; PostgreSQL/OS caches were not
flushed. These timings exclude browser download, rendering, SSO and gateway time.
Evidence/scripts remain in the service's `operations/cold-start-20261116/`.

Published `eba7ff3a` with a source-hash preflight, scoped backup and API-only
restart (4.3s). All other service PIDs and runtime/configuration bytes remained
unchanged. The existing HTTP entry's three initial requests took 2.9390s before
and 1.4554s after; this is one observed server-side HTTP pair, distinct from the
three controlled process pairs and from browser page-load time. The after read
was the first evaluation request after the API restart.

The complete live response set retained the normalized SHA256 above. Both pinned
10-30 revisions, their seven verified TE corrections, metrics, source/provider
data and audited execution hash were checked before/after and stayed identical.
No database migration, configuration change, label refresh or new simulation was
performed. Existing assets were retained for already-open tabs.
The existing direct/prefix-stripped HTTP contract passed for ordinary pages,
APIs and relative redirects. Served HTML and all 19 build files matched their
publication hashes; metric-board prefix variants and invalid-view rejection
were also verified.

This follow-up changes request/projection work only; no layout or visible text
was added. The in-app browser automation interface was unavailable for final
page interaction and viewport acceptance, so this release does not claim a new
authenticated browser or full page-load measurement. A browser-panel open was
queued for the existing AutoTriage overview URL.
