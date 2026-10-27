# Review toolbar wrapping

## Restore the return label

Cache689 restores the original visible `← 返回筛选结果` / `← Back to gallery`.
The accessible purpose and return behavior are unchanged. Desktop media selection
can shrink before wrapping the group, preserving right alignment with the longer
English label. The group keeps a bounded flex basis so smaller panes can reflow;
tablet/mobile overrides remain unchanged.

45 local frontend contracts passed. IAB read-only fixture checked 1440px Chinese/
dark and English/light (one row), plus 320/390px English/light (full return label,
no visible horizontal overflow). This does not establish real playback or
signed-in production visual acceptance.

Released `14132e8280945a102ea2d5b15bec8f8245e0c86f` at 2026-10-27 23:20:32 CST.
Cloud: 1035 passed, 7 skipped; isolated gray and production health/policy passed.
Served form/CSS/loader match the release; restored label and cache689 verified.

## Right-aligned compact actions

Cache688 follows the final placement request: GT and Back stay at the left,
while media selection, Expand, API inference and Run history align to the right
edge of the detail content. Only the desktop action group's justification changes;
existing tablet/mobile overrides and compact single-row labels are preserved.
No dropdown, media, GT or submission behavior changes.

Local validation: 44 frontend contracts passed; syntax and diff checks passed.
IAB read-only fixture: 1440px Chinese/dark and English/light stay on one row,
with Run history aligned to the content edge. 320/390px English/light preserve
the mobile layout without visible horizontal overflow. No real playback or
signed-in production browser verification is claimed.

Released `fb73389e8ed9ee8a6b3f0d4b902b27297caede17` at 2026-10-27 22:18:35 CST.
Cloud: 1034 passed, 7 skipped. Isolated gray, production PostgreSQL health and
unchanged policy gates passed. Served CSS/loader match release; cache688 verified.

## Compact single-row follow-up

The user prefers a single desktop row, not a better-aligned wrapped row. Detail
now omits the non-comparable verdict entirely (including its empty wrapper),
while preserving both original GT and model badges. Canonical Match/Mismatch
display and classification/filter semantics are unchanged. The return action
uses Back/返回 with its full purpose in title and accessible name; Run history
uses a shorter visible label while retaining its full tooltip and shortcut.

Cache687: IAB 1440px Chinese/dark and English/light checked with out_of_scope,
Ares video, return, expand, inference and history all on one row. Phone320/390
retains the existing touch-safe layout rather than forcing a wide desktop row.
48 frontend/base-path tests and executed comparison-expression tests passed.
Released as `2aae213ea214358f20656497272ac10427eba151` at
2026-10-27 21:46:57 CST. Cloud suite: 1034 passed, 7 skipped; isolated gray and
production PostgreSQL health/policy gates passed. Served Review module and loader
match the release; shell cache687 verified. Browser acceptance used a read-only
fixture, not signed-in production or real video playback. No business-data changes.
The following section records the earlier CSS-only step, not the final design.

Long original GT values can make the detail action group wrap even when the
viewport exceeds the old narrow-desktop breakpoint: the sidebar and Review pane
also consume horizontal space. The base action group now uses start alignment,
so it stays continuous when it fits and starts at the left when it wraps. It no
longer strands media selection and actions at the right edge of a mostly empty row.

This is a CSS-only layout correction. Shared media dropdown, buttons, shortcuts,
mobile overrides, GT values, media loading and submission semantics are unchanged.
Frontend cache: 686.

Validation: 48 related frontend/base-path tests passed. IAB read-only fixture
checked long `out_of_scope` with Ares video selection at 1440px and 1920×1080
Chinese/dark, plus 320px and 390px English/light. Narrow desktop wraps left;
wide desktop stays on one row; mobile has no page-level horizontal overflow.
Dropdown opening and Escape were checked. Fixture media intentionally has no
playable video; this is toolbar/responsive acceptance, not video playback or
signed-in production visual acceptance.

Released as `6987309f570babbb9b5c6f06a10602a27c533723`, cache686.
Cloud full suite: 1034 passed, 7 skipped. Isolated gray and production PostgreSQL
health gates passed; no migration or business data mutation was part of the fix.
