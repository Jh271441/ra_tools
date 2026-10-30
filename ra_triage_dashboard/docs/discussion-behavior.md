# Issue discussions

## Current contract (cache724)

Comments belong to an Issue and are shared across task, labeling, Model Review,
analysis and Bot entry points. No task, Run or baseline selection is needed to
post or reply. The dialog has one conversation and no view/destination selectors.
Existing task/Run/legacy comments appear together, preserving their original IDs,
authors, text, timestamps, attachments, source metadata and reply references.
New messages use the Issue channel with no task or Run binding; a reply may target
any non-deleted comment under that Issue. Cross-Issue replies are rejected.

The canonical API is `GET/POST /api/cases/{issue_id}/discussion`, with image
uploads at `/discussion-with-attachments`. Production writes use the existing
verified SSO writer/admin policy and same-origin markers. Intent discussion keeps
its separate dataset/Case identity. Task management permissions are unchanged.

A Bot link may include task/Run parameters as navigation context. Background URL
normalization, filter changes and page-epoch bookkeeping cannot block a comment
for the same Issue. An actual switch to another Issue preserves the draft and
blocks stale submission. Reopening/closing a dialog still rejects its late results.

Verified authors can edit/delete their ordinary comments; administrators can
manage other authors’ ordinary comments. Automatic label-rationale records stay
read-only. Version checks reject conflicting saves. Delete keeps a tombstone,
audit and existing replies, hides text/images and rejects new replies to the
deleted comment. Edits/deletes create no new notifications and cancel obsolete
pending/retry deliveries; already sent/in-flight messages cannot be recalled.
See [API and storage details](dchat-mention-architecture.md#comment-editing-and-deletion-cache724).
Migration059 is additive and mirrored in SQLite. Source-channel unification is
a read/write projection change and does not rewrite production comment rows.

Validation uses synthetic API/Chromium data and an empty disposable PostgreSQL
fixture. It covers old task/Run comments, cross-source replies, missing/closed
source tasks, Bot route normalization, exact-comment focus, refresh/history,
ownership/conflicts, audit/tombstones, notification cancellation and independent
drafts. Viewports320/390/1440, zh/en and dark/light are covered; this is desktop
Chromium viewport testing, not real-device/soft-keyboard acceptance.

## Historical releases

The records below describe earlier versions. Their task/Run ownership contracts
are superseded by the current Issue-only contract above.

### Comment submission and reply clicks (2026-10-30, released cache722)

The user's follow-up that replies fail more often exposed an additional cause.
Replying automatically inserts an @mention. On textarea blur, the shared mention
composer used to remove its entire status row. The native modal then recenters
between pointerdown and pointerup: a 1280px Chromium reproduction moved the Post
button up 9.5px and dropped the click near its lower edge (zero requests), while
the same click without a mention produced one request and no movement. This
explains why reply/mention-heavy flows are more exposed; it does not establish
the cause of every historical failure. The earlier cache721 candidate missed it.

Closing the mention popup now hides only the floating list, retaining the status
row and its layout. IME composition uses the same layout-preserving behavior.
The real browser regression holds the pointer down across blur before releasing
on both Post and another Reply action. Targets stay in place in 12 combinations.
Autocomplete selection, Escape, cancellation and composition remain covered,
including Chromium CDP composition in the discussion editor. Delayed blur cleanup
also checks whether the same input has regained focus before dismissing a popup.

Other reply-path fixes: auto @ is limited to enabled directory users (the server
already derives the notification recipient from reply_to_id); switching/cancelling
replaces/removes an untouched automatic prefix and preserves authored text. Reply
from Markdown preview returns to the editor. Attachment validation now reports
inside the modal in both languages. Hung text posts abort after 30s, uploads after
180s, with no automatic retry. The draft and reply target remain, and the message
asks users to check the discussion first because a lost response can follow a
committed post. No schema, backend policy or notification delivery changes.

A background URL serializer can add or reorder display filters after the dialog
opens. Comparing the full URL made a visible, enabled Post comment button return
without issuing a request. Dialog ownership now compares the page epoch and the
Issue/Run/task/dataset route scope. Display filters may change; navigation, closing,
reopening and actual scope changes still invalidate old operations.

Submission feedback is inside the native modal. The old page-level toast was
behind the modal's top layer, so users could not see validation/network failures.
Pending submission shows Posting, prevents duplicate requests and locks draft
editing. Failure retains the text, attachments and original reply destination;
success clears the draft and restores the prior destination. Actual stale scope
gets an explicit explanation and keeps the draft. Feedback uses existing bilingual
spans, semantic theme colors and shared dialog styles. The phone submit target is
48px. Existing permissions, persistence and notification routing remain unchanged.

Before-change Chromium reproduction recorded zero POSTs after adding a display
filter despite an enabled button, and a failed request with its toast outside the
open modal and no inline feedback. After-change validation: 90 focused tests plus
6 subtests, the existing deferred-request Node tests, and 12 Chromium viewport
combinations (320/390/1440px, zh/en, dark/light). Browser tests cover pending and
duplicate submits, reply success, visible failures, draft/reply retry, runtime
language switching, and rejection of Issue/Run/task/dataset changes. Responses are
synthetic; no business comments or DChat messages are sent. This is desktop
headless Chromium viewport testing, not a real phone/soft-keyboard or production
SSO test. Run:

```sh
node ra_triage_dashboard/tests/discussion_scope.cjs
node ra_triage_dashboard/tests/discussion_submit_browser.cjs
```

Production release `dc4fe1eff70f55379d63ff3cb5ac3452fc8e71e6` passed the complete
cloud gate (1180 passed, 7 skipped in 169.11s), isolated SQLite gray, and exact-SHA
PostgreSQL health/policy checks. Release receipt:
`/volume/home/workspace/ra_triage_dashboard_deploy/releases/20261030T092002Z-dc4fe1eff70f/result.json`.
Five served JS/CSS assets match the release bytes. No migrations, dependencies or
identity/writer-policy changes were made.

After explicit authorization of the exact test messages, signed-in macOS Chrome
accepted one ordinary Issue comment and one reply with `@jasperchen` on
`cn36941385`. Native clicks held the mouse down across editor blur (100/150ms).
Success feedback, cleared editor, restored destination, and both records after
browser refresh/reopen were observed. Readback found exactly one each: comments
153/154, with 154 replying to 153; count rose from 3 to 5. The sole notification
row is for comment154, recipient `jasperchen`, status `sent`; no other colleague
was notified. Self mentions intentionally notify the author under the existing
backend contract. These two clearly marked acceptance records remain with user
authorization. This production acceptance covered desktop Chinese/dark Chrome;
phone viewport and other language/theme coverage remains the synthetic check
above, not a real-device claim. Verification receipt:
`/volume/home/workspace/ra_triage_dashboard_deploy/operations/comment-submit-20261030/receipt.json`.

Each dialog owns its asynchronous reads/submissions by object identity plus page
epoch and route scope. Reopening the same Issue in another task/Run, closing or navigating
rejects stale effects. Failed reads disable posting and allow retry without losing
the draft. Pending submission disables duplicate requests. A late successful old
submission does not clear a new dialog's draft. Shared discussion counts must not
overwrite Run-review comment counts.

The canonical comment task ID is authoritative; old labeling helper links are
optional read metadata. Both entries must find existing task comments without
rewriting them. Labeling discussion accepts current eligible combined-review tasks
already returned by its task picker. DB membership, dataset and active-task checks
remain authoritative, including replies and attachments.

Notification ownership remains derived from the stored comment destination.
Navigation provenance is a separate read-only projection: a verified label-mention
audit comment is matched to its exact label revision (body, actor, scope and
transaction timestamp), then to its unique combined-submission receipt. Replies
inherit that original source through their same-scope parent chain. Task membership,
later acknowledgements and current/latest tasks never determine the source.

New notifications hyperlink the Issue ID to the Workbench detail in the same
dataset/Run/task context, without auto-opening discussion. For combined review,
the bilingual Source value opens the original task's Review Gallery, retaining
Run/task/dataset with comparison=all and no Issue or discussion target. Other
Source values retain their discussion entry. View comment opens
Review with the original Run/task and `channel=case`, so it opens the shared Issue
discussion, not the model-Run discussion; the exact comment is highlighted. URL
canonicalization retains that target only while Issue/Run/task/dataset stay the same.
Task context in the dialog still requires the selected Case's server assignment.
Closed/missing original entries fall back to Issue discussion while retaining the
combined-review source label. Ordinary Issue labeling/discussion still returns to
case-labeling, task comments to task detail, and model-review comments to Review.
Standalone Issue comments without validated label-audit ancestry are not inferred
to be combined-review comments merely because they were posted from Review.
The runtime injects dataset IDs from the registry; URLs must use UI dataset IDs
(such as0508), never database scope names that the picker would discard.
Already-sent notifications are not replayed. Explicit directory-approved self
mentions retain their reminder behavior. QA must not send actual messages or
submit business comments. Original comments, attachments, review versions and
label revisions are preserved; no schema or data repair is required.

Regression evidence: tests/discussion_scope.cjs executes real dialog functions with
deferred requests; tests/test_discussion_scope.py checks cross-entry storage,
eligible combined task posts/replies, old task read-only state, existing admin
guard, notification scope and self reminders without network sends.

Source-routing release (2026-10-29 20:04:50 CST): deployed
`7bfb4ea46d1816e50cad1967b7adb5de8dd702c0`, cache715. Exact-SHA cloud suite:
1142 passed, 7 skipped; isolated SQLite gray and production policy/health gates
passed. Read-only postflight verified the actual three link targets from comment117,
deployed Python modules, shell/cache and four static assets against the release.
Bot credentials remained ready; historical outboxes were not replayed.
Receipt: `/volume/home/workspace/ra_triage_dashboard_deploy/releases/20261029T120125Z-7bfb4ea46d18/result.json`.
`test_comment_source.py` checks exact
receipt attribution, inherited replies, spoof/cycle/scope guards, unavailable-task
fallback and mocked delivery/idempotency. `comment_source_browser.cjs` exercises
actual routing/discussion modules with synthetic read-only API data at 1440, 390
and 320px, Chinese/English and dark/light themes (12 combinations), exact comment
highlighting, shared selectors and refresh/back history. This is headless Chromium
viewport testing. After merging current production features, 80 focused tests and
the same 12 browser combinations passed. The in-app production browser connection
timed out; production SSO and real-device/soft-keyboard validation remain unverified.


## Notification configuration during deployment

Credential-file references are persistent runtime state. rebase_env must preserve
the DChat credential file, database URL file and trusted-ingress token file while
rebasing versioned source/config files. A clean release checkout never contains
the ignored BotUser credential file. Production smoke checks the existing
api/status notification credentials.ready value whenever OpenAPI delivery is
enabled, with no test message. Explicit repair preflight may inspect a known
broken old service; new promotion must pass the strict gate.

The 2026-10-21 incident had two terminal failures: comments86/87, notices38/39,
both to jasperchen, caused by an unreadable credential file in the release tree.
The original same-owner0600 canonical credential file remained valid. Restore
its existing reference without credential rotation, value disclosure or access
expansion. Do not reset failed/sent rows or resend any message without explicit
user instructions. Keep notification audit rows intact.
