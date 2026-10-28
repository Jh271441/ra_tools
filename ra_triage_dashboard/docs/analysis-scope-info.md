# Compact analysis scope help

The reason-analysis filter card exposes scope guidance through its top-right info
control instead of a persistent empty-task paragraph. The bilingual explanation
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
