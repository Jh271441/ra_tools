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

Validation: 416 backend tests, 113 frontend tests and the production build passed.
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
