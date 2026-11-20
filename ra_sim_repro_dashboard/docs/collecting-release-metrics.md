# Collection progress and frozen evaluation results

The overview must not treat coverage within an old frozen execution as coverage
of a release's latest observed population. On2026-11-15 the1106 overview still
presented Job49750139's one-Issue publication from2026-11-10 as100% full-version
metrics, while the latest observation held751Issues (598automatic,153manual)
and remained collecting. The original execution and approval remain valid audit
evidence for that frozen population; they are not full-release completion.

`business_population.scope_for_batch` reads local snapshots and observation state
without upstream calls or writes. It resolves the original complete source through
the batch's population hash. Native execution plans intentionally keep only Issue
ID/type/GT, so the original source supplies version/time identity. Unique Issue ID,
type, version, timestamp and verified period boundaries must agree with the latest
collection; explicit partial/acceptance sources cannot publish full-version KPIs.
GT-only changes remain governed by the existing label-cycle audit. A count-only
match or an any-old-batch change flag is insufficient evidence.

An incomplete, changed or invalid population returns pending scope data. Current
summary, history/comparison, snapshot metrics and simulation board share the guard.
`business_collection` on the summary and `collection_scope` on comparison items
separate collected counts from prior evaluated counts. Pending comparison rows keep
the release axis and table entry, but percentage and TP/FP/FN values are null; missing
results are never interpreted as zero or untriggered. The overview displays current
collection status/counts, automatic/manual splits and prior frozen-result count in
Chinese and English. No arbitrary minimum sample count replaces completeness.

Past, closed releases with valid original full-source evidence retain their published
cutoff as explicitly labeled historical frozen-population metrics. Their latest
population change is not concealed; neither the current business version nor a
collecting/stale/invalid population may use this historical display path.

Independent ordinary Shuyi revisions use their own verified report/date population
and retain their final override. AutoTriage's separate profile/fallback is unchanged.
Read gates neither revoke historical approval nor launch/retry simulations, alter
labels, change collection mode or write database schema.

Local validation:404backend tests,103frontend tests and production build passed.
Synthetic browser checks covered1440px Chinese/light,390px English/dark and320px
English/light: pending status/counts, no1106metric point, retained release axis,
no page overflow,44px principal action. These are browser viewport checks, not real
phones or soft-keyboard tests. After the user explicitly authorized source transfer and deployment, candidate
read-only PostgreSQL replay confirmed751collected/598automatic/153manual/1prior
result for1106, pending full metrics, and retained all audited historical values.
Production promotion completed2026-11-15 02:16:45CST for sourcec9175473;
a follow-upae873c5a completed02:21:41CST so the header uses latest observation
time rather than the unrelated legacy snapshot date. Final cloud gate404passed,
frontend103passed, build and source/asset hash verification passed. All original
historical comparison values are unchanged; only explicit scope metadata is added.

The private release root is
`/volume/home/services/ra-sim/operations/1106-presentation-20261115/`:
`deployment.private.json`, `date-followup.json`, `release-manifest.json`,
`backend-tests-final.txt`, source backups and private readbacks. Runtime config
is byte-identical, PostgreSQL/Redis/web PIDs were retained, and the original set of
application processes was restored. No schema, labels, modes or task changes and
no deliberate new simulation or upstream refresh were performed. Full application
and tests were first reconciled from the actual deployed source on isolated branch
`codex/sim-1106-publication-20261115`; master and the unrelated main checkout were
not changed.

Reproduce locally with `frontend/tests/overview-collection-preview.html`, or:

```sh
cd ra_sim_repro_dashboard/backend
PYTHONPATH=../.. python -m pytest tests -q
cd ../frontend
npm run test:unit
npm run build
```


## Signed-in built-in-browser acceptance

On2026-11-15, the Codex in-app browser opened the user's original ordinary-basis
1106 URL. It showed751collected Issues (598automatic,153manual), one prior frozen
result and no1106KPI/line point. Both trends retain the1106axis label. The header
now shows the latest collection observation,2026-11-15 02:07:21CST.

Actual click acceptance found that the initial progress button entered the old
simulation-result view. Frontend follow-up5e2860ba, published02:29:49CST without
restarting services, now opens the road collection with issue_view=collection and
page1. It clears stale sample-date/result/detail filters while preserving valid
page size and global release range. The same behavior applies to pending table
rows. The existing simulation-result entry keeps its frozen-result meaning.

A real signed-in click opened751Issues/38pages at20per page; Next moved to page2,
and a full reload retained page2 and collection view. Returning to overview showed
the correct counts, pending KPIs and historical values. The accepted overview tab
was marked as a deliverable in the side browser. Evidence screenshot:
`/private/tmp/sim-1106-audit-20261115/accepted-overview.jpg`.
Final frontend gate103passed and build passed; actual served19assets matched the
navigation manifest. Backend source remainsae873c5a; frontend source5e2860ba.
The source/test/docs branch is pushed; documentation-only receipts need no restart.
