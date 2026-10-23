# Independent Issue adjudication dialog

Issue adjudication opens from the result summary action in Case labeling. It no longer occupies the ordinary labeling form. Task adjudication keeps its existing task-scoped entry.

The dialog owns its output and rationale independently of ordinary labels, drafts and images. Source votes are expandable. The shared select enhancement, bilingual rendering and responsive dialog styles are reused. Close/reopen and language changes preserve unsaved input; saving locks fields and prevents duplicate submissions. Source fingerprint and prior decision ID retain the existing optimistic concurrency contract. Unresolved task sources and insufficient roles fail closed.

A successful save refreshes only the current Issue result summary. It neither clears ordinary form drafts nor navigates after a late response. Failed saves retain input. No backend, schema or notification changes.

Validation: 14 focused frontend/behavior tests passed. Actual frontend modules against synthetic local data exercised independent payload, failed save/retry, ordinary draft retention, Escape/outside close, language switching and expanded sources. Browser viewports: 1440px Chinese/dark, 390px and 320px English/light. No signed-in production write or physical-device/soft-keyboard test was performed. Exact-SHA cloud release validation is recorded separately.
