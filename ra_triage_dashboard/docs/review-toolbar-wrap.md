# Review toolbar wrapping

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
