# Issue discussions

## Candidate: historical images and reliable replies (2026-11-04, cache758; not deployed)

### Investigation

The last read-only production inspection found build
`b90c0c1805f202f8c0bc1c4d6df95877cd7aa6cc` (cache755), PostgreSQL healthy.
Issue `cn37255025` has audit comment182 for label revision4136. That exact
revision has **one** `label_attachments` record, while the discussion API returned
**zero** images for it. The audit-comment creation path copies rationale text;
images stay with the original label revision. The renderer also previously
required a Markdown image placeholder, which these snapshots do not have.

The current production log contained three canonical comment POSTs for this
Issue, all HTTP200, without a corresponding comment-route traceback. This does
not identify the cause of the user's historical network failures. Code inspection
and local HTTP failure injection confirmed several unhandled failure modes:

- A lost/timeout response can follow a committed comment. Retrying previously
  created another comment and another notification, because writes had no stable
  request identity.
- Successful HTTP responses with invalid JSON were converted to `{}`. Accessing
  `result.comment` then raised a client error reported as a posting failure.
- Expired-login HTML redirects and explicit permission errors did not have a
  distinct recovery path. An exception updating the UI after a valid receipt was
  also reported as a posting failure.
- Chromium151 actually resent a POST seven times after a connection reset in
  the local fixture. Disabling a button alone cannot prevent those wire retries.

### Candidate behavior

Historical images are projected on reads by validating the exact revision ID,
Issue, baseline scope, verified actor/source, timestamp and complete audit body.
The shared provenance resolver uses that same validation. A later revision never
replaces an older comment's evidence. Files are not copied and human records are
not rewritten. Protected label images retain `/api/labeling/attachments/{id}`
and its existing writer/active-scope checks; read-only viewers see an access
explanation. Comment bodies append images without placeholders, render inline
images once, and use the existing image style and full-image links.

Canonical Issue POSTs accept `Idempotency-Key`. Migration060 adds
`review_comments.client_request_id` and `request_fingerprint`, plus a unique
Issue/normalized-author/request-ID index; SQLite initialization mirrors it.
The fingerprint binds text, reply parent and ordered normalized image hashes.
The transaction serializes keyed writes with an Issue row lock on PostgreSQL
and `BEGIN IMMEDIATE` on SQLite. Replays return the same current comment/tombstone
without a new outbox entry. Different content under the same key returns409.
Multipart replays remove only their newly normalized, uncommitted duplicate files.

`GET /api/cases/{issue_id}/discussion-submissions/{request_id}` requires the
existing verified writer permission and reads only the current actor's receipt;
successful responses are private/no-store. It neither posts nor delivers a
notification. After an ambiguous failure the client checks this endpoint with a
6s deadline. A saved comment recovers success. A404 permits **one application
retry** with the same key; wire retries by the browser use that key too. A failed
verification retains the draft, images and parent for a later manual check.
Explicit400/401/403/409 errors do not trigger automatic posting retries. Intent
comments retain their separate API and do not use this Issue retry protocol.

Invalid successful responses are rejected rather than treated as empty JSON;
network, timeout and observable login/permission failures have bilingual feedback.
A valid receipt followed by a UI exception shows “posted, reopen discussion” and
locks further posting in that dialog, preventing accidental resubmission.
Runtime language switches keep editor/image nodes and focus while refreshing
image titles/alt text, toolbar labels and submission access state.

### Validation and remaining gate

The focused Python gates passed **151 distinct tests**, with two PostgreSQL
tests skipped. Backend/ASGI tests cover exact historical image association, spoofed
revision references, same-actor receipt reads, conflicting keys, cross-connection
SQLite retries, one notification, tombstone replay and multipart duplicate-file
cleanup. Frontend contracts, syntax and existing discussion-scope behavior pass.
On the existing Python3.9 test environment, the legacy dispatcher constructor
test needs a separate fresh invocation because `asyncio.run` clears its loop;
that separate invocation passes. Production's Python runtime has not been changed.

Actual shell/modules/CSS and the real API client pass a local synthetic HTTP
Chromium151.0.7922.34 regression for reset connections,503, corrupt200 responses,
timeout,403/400, login redirects, bounded/manual retry, post-commit UI exceptions
and multipart retries. Twelve viewport/locale/theme combinations cover
320/390/1440px × zh/en × dark/light, image loading, no duplicate inline image,
English long feedback, runtime language changes, draft/reply/focus preservation
and no page overflow. The existing reply/IME/edit/delete browser suite also passes
twelve combinations. Representative screenshots were visually inspected. These
are desktop browser viewport tests, not physical-phone, Safari or soft-keyboard
acceptance. All writes and notifications in tests are synthetic/disposable.

The proposed remote PostgreSQL gate was **rejected by automatic approval review**
before execution: uploading a source/config archive and using sudo to create/drop
a database need explicit user authorization. No test payload was uploaded and no
remote database was created or migrated. The additive migration and PostgreSQL
cross-connection/image-binding tests are prepared but **not yet run**. Production
was last observed at cache755; this task performed no release, production
comment, DChat send, service restart or production schema change. Before release, reconcile this scoped
candidate with the latest live source and use the deployment migration/backup
workflow. Preserve the checkout's unrelated existing changes.

Run locally:

```sh
python -m pytest ra_triage_dashboard/tests/test_discussion_reliability.py -q
node ra_triage_dashboard/tests/discussion_scope.cjs
node ra_triage_dashboard/tests/discussion_reliability_browser.cjs
node ra_triage_dashboard/tests/discussion_submit_browser.cjs
```

Browser scripts accept `CHROMIUM_EXECUTABLE_PATH` for an existing installation;
the reliability script accepts `DISCUSSION_EVIDENCE_DIR` for screenshots/results.
An existing Playwright package must be available on `NODE_PATH`. PostgreSQL tests
only run with `DASHBOARD_TEST_POSTGRES_URL` pointing to an empty disposable DB.

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

### Release and production readback (2026-10-30)

Production `/manual` was promoted to
`faf34994acfe73fbe7a9baeaed2de89d6cdda348` (cache724) at
2026-10-30T10:32:20Z. The complete cloud gate passed **1202 tests, 8 skipped**
in 195.24s. Isolated SQLite gray passed. Before migration059, the release stopped
writes, created a fresh checksum-verified PostgreSQL dump, restored it into a
disposable database and matched every live table count; migration count advanced
58 to 59. The existing writer/Batch policies and disabled AutoTriage push were
preserved. Release receipt:
`/volume/home/workspace/ra_triage_dashboard_deploy/releases/20261030T102830Z-faf34994acfe/result.json`.

Read-only production postflight at 10:32:42Z confirmed exact-SHA healthy
PostgreSQL service, schema59, the new canonical discussion and mutation routes,
and eight served JS/CSS assets matching release bytes. The unified endpoint reads
both reported Issues, `cn36941385` and `cn37033077`; previously authorized test
comments153/154 remain unchanged, including their reply relationship. Protected
label-rationale metadata is present. Receipt:
`/volume/home/workspace/ra_triage_dashboard_deploy/operations/issue-discussion-20261030/receipt.json`.

The initial read-only postflight also had synthetic Chromium coverage and
5 integration tests against an empty disposable PostgreSQL fixture. Chrome
automation could not attach; whole-app accessibility reading was rejected to
avoid unrelated private tabs. The user then selected the Codex in-app browser
and explicitly approved the exact live test messages, edit and cleanup below.

### Signed-in production acceptance (2026-10-30, cache724)

The Codex in-app browser used verified SSO `jasperchen` and the original
cn37033077 Bot URL, including its Run and task parameters. No DChat conversation
was opened; the user elected to provide DChat client feedback. The dialog showed
one Issue thread, no view/destination selectors and no requirement to choose a
task or Run. The approved ordinary comment160 was posted at20:59:14 CST;
reply161 to160 was posted at21:03:43. Comment160 was edited at21:08:32, and its
updated text also appeared in the reply quote. A fresh Issue-only URL with no
task/Run parameters displayed the same persisted edit and reply.

Soft-deleting160 at21:12:46 kept its tombstone and reply161. Deleting161 at21:15:30
cleared that test body too. After a full page reload and reopening discussion,
both tombstones remained, and original comments157/158 were unchanged. Final
read-only verification at13:21:55Z confirmed versions160=3 and161=2, empty test
bodies, the preserved161→160 parent, and audit rows1/2/3 for the edit and two
deletions, all by verified jasperchen. New comments have case channel and empty
campaign/Run bindings; automatically retained baseline provenance is metadata,
not a discussion membership requirement.

The sole new notification was outbox122 for reply161, addressed to jasperchen
and sent once. No colleague was notified, and edit/delete created no additional
notifications. Client receipt in DChat was not independently observed. Private
before/post-reply/final receipts are under
`/volume/home/workspace/ra_triage_dashboard_deploy/operations/issue-discussion-live-qa-20261030/`.
This actual production UI acceptance covers desktop Chinese/dark in-app browser;
it does not add real-phone or soft-keyboard coverage. The cache722 result below
remains historical. The deployed runtime is still `faf34994acfe73fbe7a9baeaed2de89d6cdda348`;
recording these results does not require another deployment.

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
