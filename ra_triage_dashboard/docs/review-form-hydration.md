# Review saved-label hydration

## Failure and data check

Issue `cn37174713` in Run `dd6cec49-3bf3-50b1-8872-dc86b02ffd13`
and Campaign `campaign-b08ff8f08a8144b6b64e0d81a34e99de` had a saved
Case revision with tag `u_turn` and its author's rationale. The production
read-only core API returned revision `3531`, with both assignment acknowledgements
complete. The empty form did not establish missing data.

The form initially used a model Review, whose Case tags and expected output are
deliberately empty. A separate asynchronous context read hydrated the Case vote.
Any restored draft or edit could skip that entire hydration, even when only the
model note changed. Full draft snapshots could then preserve the empty Case
fields. Foreground combined saves also relied on a later timestamp comparison to
retire drafts; server timestamps have whole-second precision.

## Form and draft contract

- Combined Review starts with the current author's saved Case revision from the
  existing core label projection, alongside the selected Run's own model Review.
  A peer's label or an adjudication must not become this author's edit head.
- New drafts carry `edited_fields`. Their full snapshots retain compatibility,
  but only edited fields overlay saved values. Legacy snapshots retain explicit
  values and clears because they do not identify which fields changed.
- Delayed/retried context reads hydrate fields independently. Editing the model
  note does not suppress Case tags/rationale; Case edits do not suppress model
  fields. Focused text and IME preedit remain protected. An unedited exclusion
  snapshot does not override the saved Case flag.
- Existing tag/evidence creation and selected-chip removal emit the normal form
  change event, so the shared components participate in draft tracking.
- A successful foreground submission clears only its matching draft snapshot.
  Edits made during the request remain drafts. Update the existing form and
  context in place; preserve media, input nodes and focus. Namespace, page,
  request-order, permission and optimistic-lock guards remain active.

## Verification

`tests/combined_review_hydration.cjs` reproduces the pre-fix failure, checks
independent hydration, intentional clears, focused text, saved-draft retirement,
edits during save and unrelated drafts retaining inherited tags. It is included
in `test_combined_review_linkage.py`.

`tests/combined_review_hydration_browser.py` loads actual shell/modules/styles
with synthetic API responses and performs no business writes. Coverage:
320/390/1440px × Chinese/English × dark/light, early model-note edits,
draft restoration, missing core projection, context failure/retry and intentional
tag/rationale clears. These are desktop Chromium viewport tests, not physical
phone, native keyboard or touch verification.

Focused existing Review contracts, shortcuts, draft scope, IME, navigation and
background-upload regressions are part of the accompanying local verification.
Local validation and release evidence are recorded in `reports/review_hydration_20261102/`.
