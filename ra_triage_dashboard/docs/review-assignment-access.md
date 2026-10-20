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

The former missing-context toast did not explain the failed read and offered no
recovery. The exact failed user URL is still needed to distinguish an assignment
mismatch from a failed network request; do not infer a role problem from that
message. Test fixtures cover both cases and successful writer context loading.

The existing narrow-header policy now follows the app-frame container width
(including resized sidebars), keeps five metrics on the second row, and prevents
GT metadata from shrinking through its own border. Video controls wrap according
to their actual card width; progress labels size to content and the slider can
shrink within its row. This preserves the older wrap-to-fit behavior without
relying only on viewport breakpoints.
