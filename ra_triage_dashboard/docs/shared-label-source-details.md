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
