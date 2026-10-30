# Review IME input protection

Candidate on 2026-10-30, based on production `a3a6872b` / cache 717.
Cache 718 is prepared locally and has **not been deployed**.

## Evidence and scope

The user confirmed that Chinese input works in T3650's Chrome address bar and
other applications, while the Review text fields fail. Read-only host checks
found Ubuntu GNOME/X11, IBus 1.5.26, a live libpinyin engine and a registered
candidate-panel connection. No IBus restart or host configuration change occurred.

The actual production modules reproduce two keyboard conflicts: mention selection
consumes Enter during composition, and an IME Enter with keyCode 229 but
isComposing=false submits the form. Collaboration refresh also replaces a clean
focused form, including when focus begins during an in-flight detail read; an XIM
preedit does not have to produce committed text before that replacement occurs.
These are confirmed page defects. The user's original native candidate-window
failure has not been instrumented or reproduced directly on T3650.

## Contract

- Shared `text-input.js` recognizes the standard composition flag, keyCode/which
  229 and the text field's composition lifecycle. It loads before consumers.
- Review/Case/Discussion shortcuts yield to IME Enter, Escape, arrows and Tab.
  The mention popover hides during composition and updates after compositionend.
  Normal mention selection and separate desktop submit/newline keys still work.
- Background Review refresh keeps a focused text node before and after its read,
  including the media-loading fallback. Deferred clean refresh resumes after
  focus leaves the form; unsaved drafts and navigation ownership remain protected.
- Delayed combined-context hydration does not overwrite a focused rationale or
  model-review note. No label/Review/GT/Trail or identity policy changes.
- All existing controls, translations, responsive styles and mobile Enter behavior
  are reused. No visible strings, CSS or runtime dependencies are introduced.

## Validation

- 82 frontend contract tests, 24 existing Review shortcut behavior tests,
  3 label/review interaction tests, 4 mobile interaction tests and 4 base-path
  tests passed. The new unittest wraps `node tests/review_ime.cjs`.
- New behavior checks cover IME keys, lifecycle fallback, normal mention selection,
  desktop/mobile Enter, media-loading and in-flight refresh focus races, dirty
  draft retention and clean focusout resumption. The old production source fails
  the IME Enter regression when run with `IME_TEST_REF=origin/master` at the
  candidate's base revision.
- Existing video performance, navigation races (12 scenarios), combined context,
  background uploads and discussion-scope Node checks passed.
- `python3 ra_triage_dashboard/tests/review_ime_browser.py` uses the actual shell,
  modules, shared controls and styles with intercepted synthetic context data.
  Chromium 148.0.7778.96 passed 12 combinations: 320/390/1440px × zh/en × dark/light,
  both Review text fields, native browser composition via CDP, runtime language
  switching, no accidental submits, no JS errors and no page overflow. Mobile
  English/light and desktop Chinese/dark screenshots were visually inspected.
- Changed JS/Python syntax, diff whitespace and scoped secret checks passed.

Browser checks ran on macOS in an isolated headless browser. They are responsive
browser tests, not a real mobile-device test or a native Linux IBus test. The full
cloud suite, deployment gray gate and T3650 Chrome/IBus acceptance remain release
steps after explicit deployment authorization.
