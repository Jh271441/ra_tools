# Problem and task discussions

The dialog separates **Show discussions** from **Post in**. Viewing all comments
does not select a combined posting destination. New messages default to issue
discussion; the author may explicitly choose the current task when available.

- Issue discussion is shared for the same dataset and Issue across tasks.
- Current task discussion belongs to that task and Issue. Other task history is
  a read-only reference; a closed/replaced task cannot receive new task messages.
- Review batch discussion belongs to one Issue and selected model Run. These
  records remain independent from shared Issue labels and task discussion.
- The existing server policies stay in force: labeling discussion requires a
  verified writer/admin; task-page task posts remain admin-only. This change does
  not expand task-page posting access. Task management remains admin-only.

Viewing scope filters actual rows, preserving the draft and posting destination.
Replies lock to the original destination. Cancelling or finishing a reply restores
the prior posting destination and unlocks the selector. Reopening clears the lock.
No silent task adoption occurs for a taskless reply. Enter inserts a newline;
Ctrl/Cmd+Enter submits, respecting composition and mention picker handling.

Each dialog owns its asynchronous reads/submissions by object identity plus page
epoch/URL. Reopening the same Issue in another task/Run, closing or navigating
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
