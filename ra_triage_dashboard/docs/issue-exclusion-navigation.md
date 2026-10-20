# Issue exclusion entry and review shortcuts

Issue validity belongs to the Case / Issue. A model error remains scoped to its Run.
The sidebar therefore groups Issue exclusion under Case labeling. Its existing
read-only visibility is preserved; Case labeling and summary remain writer-only,
and assignment administration remains admin-only.

During identity resolution, restricted menu entries are visible inert placeholders.
Only server-confirmed identity enables them. Failed/denied resolution hides them;
no cached role grants access. The public exclusion entry remains available.

Review details offer an Issue-level exclusion link outside the model review card.
It opens a new tab at `trail-attribute-update?tab=issue&exclude_issue=<id>` without
inheriting a Run. The route fills an empty row or appends a missing Issue, preserving
existing notes and rows. It neither previews nor commits automatically. The original
Review page retains its draft and task context. Existing Trail preview, explicit
confirmation, idempotency, audit and readback are unchanged. This is entry-point
integration, not a new canonical Issue-validity schema or a change to dataset scope.

Shift+R opens the Run-review status picker; 1/2/3 choose Pending/In progress/Completed
only while it is open. Typing, composition, modifiers, read-only and disabled states
are excluded. Selecting a status never submits. R continues to refresh; existing
arrow/Escape handling applies. K cannot toggle the hidden legacy Review exclusion
control; visible Case-labeling exclusion controls retain their existing shortcut.

Validation: Node behavior tests cover permission resolution, keyboard scope and
hidden controls, additive/idempotent exclusion preparation, and no automatic writer
calls. Frontend contracts cover sidebar ownership and synchronized cache versions.
