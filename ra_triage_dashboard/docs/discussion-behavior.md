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

Notification links are derived from the stored comment destination: issue to
case-labeling, task to task detail, review batch to review. They retain the exact
comment and dataset/Run/task context and never guess a different destination.
Already-sent notifications are not replayed. Explicit directory-approved self
mentions retain their reminder behavior. QA must not send actual messages or
submit business comments. Original comments, attachments, review versions and
label revisions are preserved; no schema or data repair is required.

Regression evidence: tests/discussion_scope.cjs executes real dialog functions with
deferred requests; tests/test_discussion_scope.py checks cross-entry storage,
eligible combined task posts/replies, old task read-only state, existing admin
guard, notification scope and self reminders without network sends.


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
