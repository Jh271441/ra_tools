# Compact analysis scope help

The reason-analysis Review data scope field exposes guidance through an info
control on the right of its label, immediately above its picker, instead of a
persistent empty-task paragraph or a card-wide heading row. The bilingual explanation
distinguishes task discovery from the existence of Review records and explains
the combined-results versus task-submitted scope. Filtering and API contracts are
unchanged. Run comparison no longer renders its list of internal GT source scopes
and snapshot IDs; the API retains that metadata and the metrics are unchanged.

`bindUiInfoPopovers` in core-base owns the existing version-info interaction and
the new analysis help: pointer hover, keyboard focus, click/tap, Escape, outside
press, resize/scroll dismissal and visual-viewport bounds. Bindings are idempotent
across option refreshes. The analysis card uses the shared tooltip skin; mobile
info targets are 44px, and analysis filters reset desktop row placement below the
existing tablet breakpoint to avoid overlapping controls.

## Validation

- 74 frontend contract tests and the version frontend behavior test passed.
- Changed JS syntax and `git diff --check` passed.
- `tests/analysis_scope_info_browser.cjs` uses actual shell, shared components and
  rendering functions with synthetic read-only data, not production APIs.
  Chromium checks analysis/comparison at 320, 390 and 1440px, both languages and
  themes (24 combinations), info open/Escape/outside close, viewport bounds,
  mobile hit targets, absent legacy paragraphs and retained task selection after
  options become empty. No page errors or page-level horizontal overflow.
- These are local browser viewport tests, not physical phones, native simulators
  or signed-in production acceptance. Release gates and live verification are
  recorded by the deployment receipt.

## Release

Deployed `cff092f39f88db7af3ea460836038835ea578d48`, cache691, at
2026-10-28 11:38:05 CST. Cloud tests: 1043 passed, 7 skipped; isolated SQLite
gray and exact production SHA/PostgreSQL health passed. Served loader, core,
work-split, comparison and shared/mobile CSS match the commit. Production shell
contains the info panel and neither old paragraph. Receipt:
`/volume/home/workspace/ra_triage_dashboard_deploy/releases/20261028T033459Z-cff092f39f88/result.json`.
Chrome and IAB control both timed out, so signed-in production visual acceptance
is not claimed. No GT, Review, task, model-output or schema mutation.
