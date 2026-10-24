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

## Issue-scoped exclusions (2026-10-25; not yet deployed)

The exclusion page scopes candidates by selected datasets and Issue IDs.
It no longer loads or offers a Model Run selector, model-prediction filter or
model-review-state filter. Legacy `run`, `model_label` and `review_status` URL
parameters do not restrict this page. Preview cache keys are dataset/view scoped;
selected write previews carry only explicit Issue IDs, intent and datasets.
Backend compatibility with Run-scoped API clients and historical source evidence
is retained. Current Case votes/decisions still override stale legacy Run flags.
No migration, automatic Trail write or writer-policy change is introduced.

The overview uses a narrow candidate-count card and wider Trail status summary.
At mobile widths it stacks using existing mobile.css rules. The decision dialog
summary uses two compact facts on desktop and one column below 640px; field and
status text are secondary, only the outcome uses semibold. Personal label cards
are unchanged.

## Optional Issue description (2026-10-25; not yet deployed)

Case-labeling detail presents the original Issue summary behind a default-collapsed
Scene description control. Expansion reveals the full escaped multiline source
text below the context controls. No summary yields no control. Same-Issue media
rerenders preserve expansion; another Issue starts closed. The control uses the
existing compact button, keyboard behavior, bilingual spans and mobile overrides.
