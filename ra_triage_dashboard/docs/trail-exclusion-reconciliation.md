# Trail exclusion reconciliation and selected reason updates

The Review aggregate on `/manual/trail-attribute-update` has two views:

- **Local candidates** retains current canonical Case exclusion ownership, with legacy Review fallback only when there is no canonical decision. Users explicitly select eligible cases and an intent (`reason_only` or `exclude`).
- **Trail exclusion reconciliation** is read-only. It unions local candidates with verified historical snapshot membership, deduplicating baseline + Issue ID. Historical membership is never treated as current remote state. Historical-only rows show stored legacy/migrated evidence without turning Review notes into exclusion reasons or proposing local/remote adjudication.

The initial preview remains local (`probe_trail=false`). The compact status call asynchronously reads current Trail flags and reasons. Counts distinguish local scope, historical coverage, union size and confirmed/query coverage. Missing, expired, malformed or failed results cannot become pending writes. Empty local reasons preserve the existing remote text and omit the comment patch key.

`POST /api/trail-attribute-update/selection-preview` reconstructs a fresh explicit subset and records an actor-bound, ten-minute preview including intent, local revision fingerprint and exact remote owned fields. `selection-commit` rechecks identity, origin marker, write flags, local versions and remote state, persists audit before mutation, writes info only, and verifies readback. The old aggregate `/commit` delegates to this contract and requires a fresh selected preview; it cannot implicitly submit every pending row. Direct Issue-ID shielding retains its separate workflow and default note.

Selected writes do not create local annotations or notifications. For direct shielding's existing local follow-up, a canonical Case already excluded is reported as already present; a canonical false decision or synthetic Review ID is not overwritten. Trail and local follow-up outcomes remain distinct.

The external Trail API has no atomic compare-and-swap. A fresh read and process-local serialization prevent known stale submissions, but do not provide cross-client atomicity. Previews are process-local and expire across restart/worker changes, requiring a new preview. Durable audit uses the existing history table; no schema change.

Historical registries validate snapshot/subset membership and publish filenames, SHA-256 fingerprints and capture time. Unavailable/inconsistent sources fail to an explicit unavailable state, without suppressing local candidates. These snapshots define retrieval coverage, not a full live dataset scan.

Validation for this candidate: 766 cloud pytest tests passed, 5 skipped. Latest responsive UI visual acceptance is still pending because browser automatic approval reported exhausted tool usage. This document does not confirm deployment or production Trail writes.
