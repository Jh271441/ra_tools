# Issue exclusion and review shortcuts

Issue validity belongs to the Case / Issue. A model error remains scoped to its Run.
The sidebar groups Issue exclusion under Case labeling. Its existing read-only
visibility is preserved; Case labeling and summary remain writer-only, and assignment
administration remains admin-only.

During identity resolution, restricted menu entries are visible inert placeholders.
Only server-confirmed identity enables them. Failed/denied resolution hides them;
no cached role grants access.

Combined Review restores the inline “排除此 Issue” checkbox immediately before the
Case label rationale/comment. There is no extra exclusion or Trail-sync row at the
top of Review. Trail synchronization remains available from the sidebar Issue
exclusion page, with preview and explicit confirmation required. Navigation and
ordinary Review submission never execute that writer.

Submission saves exclusion on the Case revision, alongside the required Case label;
the Run review remains unexcluded. Changing exclusion alone appends a new Case
revision instead of acknowledging the previous vote. Repeating an unchanged flag
acknowledges it, and combined idempotency includes explicitly provided exclusion.
Old clients omitting the flag preserve the existing Case value and their historical
request fingerprint. Task progress still counts each Issue once. The same behavior
applies to Case-only submissions without a Run.

The checkbox is disabled until Case context loads, restores exclusion from a separate
Case draft field, and uses K like the standalone Case-labeling control. Run-history
refresh and delayed Trail metadata cannot overwrite it. In model-only mode the Case
section remains hidden and K cannot change its control.

The status trigger places a compact Shift+R keycap before its chevron, matching
existing tag controls. Options show numbered keycaps on the right; status labels
never include shortcut prefixes. Shift+R opens Run-review status;1/2/3 select
Pending/In progress/Completed only while it is open. Typing, composition, modifiers,
read-only and disabled states are excluded. Selection never submits. R refresh and
existing arrow/Escape handling remain.

Validation covers permission resolution, keyboard scope, exclusion hydration and
local drafts, delayed Trail protection, append-only Case exclusion changes, old
client compatibility, idempotency and single-count task progress. Frontend contracts
cover sidebar ownership and synchronized cache versions.
