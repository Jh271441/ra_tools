# Review allocation access and context loading

Verified Dashboard writers and administrators may open task allocations, list
current/historical/My tasks, inspect progress and details, and use Review entry
links. For a verified task member, card entry carries that member’s assignee
filter; the own-task picker does the same. Analysis remains at the batch scope.
A copied link to a peer’s Issue does not transfer assignment ownership.
Both list/detail APIs require the existing writer identity helper. Viewers
and unverified identities remain denied. Bootstrap waits for session resolution;
it delegates admin user loading to the allocation loader so writers never request
that admin API. Creation, draft restoration and transfers remain admin-only on
both client and server. Historical allocations remain read-only.

Combined context loading exposes loading/error/ready states beside submission.
An error shows its cause and a Retry loading action. Submission stays disabled
until matching Issue/Run/Campaign/actor context is ready; tag changes cannot
re-enable it. Delayed loads and retries retain form edits/drafts and reject
responses belonging to another namespace or page visit. Ordinary task-free
submission retains its explicit empty Campaign namespace. No reassignment or
production submission is needed to validate this behavior.

Known non-assignees can submit a supplemental combined review from a peer's Issue
link. The Issue assignment must still match the task/Run/workflow before this is
allowed; absent/mismatched context fails explicitly. The UI says “任务外补充”,
keeps the task URL for browsing, and submits empty campaign_id/work_split_id into
the actor's ordinary review stream. Case votes remain shared. The original
assignee's head and the Campaign's assignment/progress remain unchanged.

The header preserves its compact desktop row with a bounded, shrinkable dataset
picker and five inline metrics. The established narrow-window fallback moves
metrics to a second row only below 1200px. GT metadata cannot shrink through its
own border. Video controls wrap according
to their actual card width; progress labels size to content and the slider can
shrink within its row. This preserves the older wrap-to-fit behavior without
relying only on viewport breakpoints.

The baseline picker groups the 10/15, 10/16 and 10/18 main/supplement scopes into
one daily choice with combined counts (33/112/90 at release). API/URL selections
still use their original IDs. Old partial-scope URLs retain their exact subset
and show a partial count; explicit All / Only this expands the daily union.
No stored GT scope, immutable Run, Campaign or annotation is migrated.
