# Review Run output selection

Review's gallery, detail summary and media overlay use the explicitly selected
Run. With no overlay selected, detail shows “未选 Run / No Run selected” and does
not promote a historical prediction into the current output. If a selected Run
has no prediction for an Issue, other Runs remain available only in Run history.
The team default and deliberate no-overlay selection are unchanged.

Pre-rule publication is a valid Run output. Explicit `prediction_source=pre_rule`
metadata identifies a rule hit; the UI shows its stored rule reason and identifies
`confidence_source=rule_constant` separately from model confidence. Direct metadata
and legacy nested `ra_stuck_auto_result_info.daily_auto_triage` are supported.
No inference or annotation write is triggered by rendering either form.

An available rule output does not establish the existence of a pure-model forward.
Evaluation references and comparison denominators must continue to use persisted
prediction provenance and execution receipts. A rule-only sample can be included
in published-output evaluation while remaining outside a pure-model comparison.

The model history dialog remains available with no Run selected. Language changes
relocalize the open history while retaining its scroll position. Media outside
Review retains its existing experiment-specific selection behavior.

Validation for the 2026-11-09 fix: 79 focused frontend/interaction checks passed.
Local, read-only Chromium 151 fixtures covered 36 combinations of 320/390/1440px,
Chinese/English, dark/light and no/matching/missing Run. Checks also covered rule
reasons, media selection, history language switching and Escape. These are browser
viewport tests, not physical phone or signed-in production acceptance.
