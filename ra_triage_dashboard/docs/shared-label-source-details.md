# Shared Issue label source details

The Review shared-label source dialog displays structured Issue tags for each
source revision, together with that revision’s expected output, author/time,
Case exclusion flag and label rationale. Use the existing tag catalog labels,
axis/group translations, badge colors and time formatter. Preserve unknown and
historical custom tags as readable fallback values; an empty tag list and missing
legacy details have distinct messages. User-authored text stays unchanged and
HTML-escaped.

Do not union tags across authors, source Cases or adjudication results. A result
revision is marked as such only for a resolved source. Original submission heads
and a separate adjudication result each retain their own tags and rationale.
The dialog stays read-only and keeps the existing navigation permissions.

The bounded shared projection adds tags and is_excluded to revision_summaries
from the already-loaded author heads and resolution result; no extra queries,
historical scan or business writes are needed. Decision source fingerprints,
GT resolution, review progress, task assignments and stored records are unchanged.

Use the existing dialog/chip components. Long tags wrap; source details stack
on phones and the content scrolls while Close remains reachable. Validate Chinese
and English, light/dark themes, desktop1440px and phone320/390px. Opening, closing
and changing language must preserve the unsaved Review draft.

The Review Issue-tag heading has a single fixed-label “标签汇总 / Label summary”
button using the same compact action style as Review history. Status and source
counts stay inside the dialog. Per-group draft counts remain visible; the global
draft count node stays hidden for existing update bindings, so it cannot widen
the heading as submissions accumulate. The heading reserves the right action
column even with longer English text.

Display provenance is returned separately as `label_source_contexts` on Issue
detail responses. Exact combined submission/acknowledgement revision links show
the task name and evaluation Run, including multiple tasks reusing one Issue
vote. Never infer task attribution from assignment membership or the current URL.
Raw IDs are available in collapsed Record details. Label/decision fingerprints,
stored records and task progress are unchanged by reading this metadata.

Model review retains its status selector. Current progress is Not started before
submission; the submission choice defaults to Completed. Persisted Needs review
and Completed choices are retained, including comment-free completion. Pending
legacy records are shown as Needs review without rewriting them. M opens the
shared status selector (1 Needs review / 2 Completed), Escape releases focus,
and P opens evaluation Run history. Comments remain optional.

Issue discussion uses D and label rationale uses E. Run review discussion uses
Shift+D and model reason uses Shift+E; discussion channels remain independent.
The Issue discussion reuses the existing image-comment endpoint. Label rationale
uses the shared mention composer and validates the notification directory before
writing. A newly appended label revision queues an Issue-discussion audit comment
and DChat outbox entries in the same transaction. Acknowledgements, rejected
stale writes and idempotency replays do not send duplicates. Outbox write failures
roll back both combined halves; ordinary model-review notification behavior stays
unchanged. No actual message is sent by the validation workflow.

In Review detail, L toggles Label summary; the button shows the existing compact
keycap and the shortcut guide includes it. Escape still dismisses the dialog.
Typing, composition, held keys and modified shortcuts do not trigger it; other
open dialogs remain in control. This read-only action preserves the form draft.

Tag and evidence panels follow their summary button width, clamped only at the
viewport boundary. Long labels wrap within that width; height uses available
viewport space and scrolling. Do not widen narrow group panels to a fixed floor.
Issue discussion carries an explicit matching Review task into the view selector,
including when viewing as a non-assignee. The posting destination remains Issue
discussion by default. No explicit task means no task inference and a clear
disabled-option explanation. Existing server permission/membership checks remain.


### Case rationale images

The Issue rationale editor accepts PNG/JPEG/WebP using Browse, paste or drop,
with the existing limit of four images, 8 MB each and 24 MB per submission.
Pending images use a separate Issue/Run/explicit-task/actor map; navigation and
language changes preserve that in-memory selection, while a page reload does not.
Only the successfully submitted snapshot is cleared; failures retain selections.
The image field uses the existing screenshot component, with compact phone
previews and 44px remove targets. Case images never enter model screenshots.

Multipart `combined-review-with-attachments` and
`case-label-from-review-with-attachments` use the existing `labeling-v1` marker,
request size guard, verified writer checks and normalized, root-confined storage.
Metadata is inserted with its label revision in the same database transaction as
the combined Run review. Images force a new label version even if text is equal.
The idempotency fingerprint includes content hashes, not temporary file IDs.
Unreferenced newly stored files are removed after conflict, rollback or replay;
committed files survive a response failure. Existing revisions are not modified.

Images belong to the submitted version. The current version's images are shown
in the editor and Label summary; older versions and their images remain in Issue
labeling history. Display metadata is separate from the label-state fingerprint,
and attachment links use the existing protected opaque labeling URL.
