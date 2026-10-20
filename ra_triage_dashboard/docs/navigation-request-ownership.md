# Async page ownership

A pending read is not a navigation request. Filtering, background refresh,
startup completion and task hydration may update only the view that initiated
them. Every showPage commit advances pageNavigationEpoch. capturePageContext
records the epoch, page and URL; isPageContextCurrent rejects work from an older
visit, including leaving and returning to an identical URL. Same-page query
changes also invalidate response paint/navigation. showPage commits the target
URL before dispatching page loaders, so they capture the correct new route. Run metadata checks the
navigation epoch, selected Run and baselines, while allowing unrelated text
filters to change during its request.

The former reloadReviewGallery unconditionally called showPage("review") after
waiting for its list/facets. A slow response could therefore pull a user out of
Case labeling or labeling summary. Debounced filters, pagination, task-context
URL replacement, history/detail restoration and polling follow the same ownership
rule now. Case-labeling/summary route writers do not rewrite another page's URL.
Delayed responses cannot clear a newer editor or its unsaved data.

Bootstrap yields to newer navigation and does not replay the initial route over
user filters. It always starts collaboration polling in finally, including when
it yields early. Labeling summary now awaits server identity before checking
writer access, matching Case labeling; a slow identity lookup is not a denial.
Confirmed missing permission still follows the existing guarded fallback.

navigation_races.cjs uses actual classic-script functions and controllable
promises/timers. It reproduces the old Review filter redirect against6a677ad and
checks delayed filtering, navigation round trips, list/pagination/polling,
task-context URL writes, bootstrap, slow allowed/denied identity and labeling
entry/summary responses. Existing source contracts and task/revocation behavior
checks also remain required. No API, database, task membership or stored review
semantics change in this frontend fix.
