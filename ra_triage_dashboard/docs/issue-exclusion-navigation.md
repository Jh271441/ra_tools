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

The status trigger places a compact keycap before its chevron, matching the
existing tag controls. Options show numbered keycaps on the right; neither the
selected status nor native option labels include shortcut prefixes.

Shift+R opens the Run-review status picker; 1/2/3 choose Pending/In progress/Completed
only while it is open. Typing, composition, modifiers, read-only and disabled states
are excluded. Selecting a status never submits. R continues to refresh; existing
arrow/Escape handling applies. K toggles the visible Issue exclusion control in combined mode; the Case vote
loads and saves the value, independently of the Run review. In model-only mode
the Case section stays hidden and K cannot change its control.

Validation: Node behavior tests cover permission resolution, keyboard scope and
hidden controls, additive/idempotent exclusion preparation, and no automatic writer
calls. Frontend contracts cover sidebar ownership and synchronized cache versions.


The combined Case section restores an inline “排除此 Issue” checkbox beneath the
label rationale. Submission saves this flag on the Case revision, alongside the
required Case label; the Run review remains unexcluded. Changing exclusion alone
appends a new Case revision instead of acknowledging the previous vote. Repeating
an unchanged flag acknowledges it, and combined idempotency includes explicitly
provided exclusion. Old clients omitting the flag preserve the existing Case value
and their historical request fingerprint. Task progress still counts each Issue
once. The same behavior applies to Case-only submissions without a Run.

The checkbox is disabled until its Case context loads, restores Case exclusion
from a separate draft field, and uses K like the existing Case-labeling control.
The separate link is explicitly named “同步排除到 Trail”; ordinary review submission
never invokes that writer. This restores the existing Case annotation semantics,
not an automatic global dataset removal or Trail synchronization.
