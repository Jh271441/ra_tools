# Run comparison input provenance

The comparison list keeps only paged output summaries and Run snapshots. Opening a
Case fetches `GET /api/model-run-comparison/cases/{issue_id}/inputs` with exactly
`baseline_run_id`, `candidate_run_id`, and the selected `baselines`. The existing
read-only identity policy applies. The database checks the Case's selected scope,
Run existence and each `(run_id, issue_id)` prediction; missing predictions remain
explicitly unavailable. No schema change, backfill or Run mutation is involved.

`prompt.source_type` is `actual_input`, `run_example`, `run_template`, or
`not_saved`. Per-prediction `prompt_text` / `actual_prompt` comes from saved
`model_extra` or `raw_json`; Run/Batch templates are separate `run_reference`
objects and are never rendered using today's template. Actual text includes its
saved serialization stage, declared and computed SHA-256, and hash agreement.
Run examples retain their example Case ID. Empty Reason is shown as
“未保存／未生成 Reason”; `reason_generated=false` is exposed as `not_generated`.

Per-Case input configuration is only labelled actual when explicitly recorded.
Run configuration remains reference. Media entries preserve order and recorded
time/pixel settings. `reference_sha256` hashes a saved file reference, not image
bytes; `content_sha256` is only a recorded content digest. Neither authorizes
serving a path. The current API exposes no inferred actual asset URL. Unverified
references show the asset/identity limitation, and the media dialog continues to
use indexed dashboard **参考媒体**. Credentials and server paths are redacted.

The comparison list also projects bounded auxiliary-input summaries from each
prediction's explicitly saved structured fields, falling back only to recognized
Routing / lane-change lines in the saved actual Case Prompt. It never infers use
from a Run name or template. Counts represent saved intent timepoints; missing
values remain missing. The list and Case dialog merge equal summaries and label
different summaries by Run. The `input_filter` query parameter is a versioned
JSON object with a Run scope (`candidate`, `baseline`, `either`), an axis relation
(`all`, `any`), and per-axis `any` / `all` / `none` label conditions. For `either`,
one Run must satisfy the complete expression.

The same projection retains exact per-frame values when the saved input has an
explicit offset mapping. Structured intent arrays align only to same-length
`image_inputs` offsets or saved input-config offsets. Saved Prompt probability
rows must contain their own `t=...s`; each axis uses that row's maximum saved
probability. The Run-comparison BEV/Camera dialog matches the current media
offset exactly and shows those values beside GT. It does not use nearest-frame
fallback or expand aggregate counts into invented frame labels.

Scene Tags use the same compatibility projection as reason analysis: the new Run's
latest Review wins, followed by the latest unbound Review, then the latest Review
from another Run. The selected annotation is returned with author, time, Run and
fallback source; revisions are never merged or rebound. An existing selected
Review with an empty Tag list stays empty.

Prompt diff uses bounded line LCS (1,000,000 cells and 200,000 combined characters),
paired modification lines with inline highlighting, collapsed equal blocks,
side-by-side/unified views and full text fallback. Config objects are recursively
key-sorted; arrays retain order. Text is HTML-escaped. The table lazy-loads only
current-page cached BEV thumbnails and opens full media only on user action.
The column contains only the clickable image (or 暂无 BEV fallback); reference
media provenance is shown in the media dialog title and thumbnail accessible label.
Case input and media requests independently ignore stale responses. Opening or
closing either dialog does not reload the list or change its route/scroll state.

## Source audit: 2026-09-08

Target baseline `99b1c499-d3bb-4bc3-b3e3-f011c7b475f1` (P0 无意图 ck330),
candidate `b3d96cc0-3198-49a4-b1ac-93da7dad2b12` (P0 双意图 ck350),
0508, F2P, page 2. Both archived source JSON files are original, not reconstructed.
Both top-level Prompts are rendered examples for **cn31799329**, before image-token
expansion. Original results already contain per-Case prompt and ordered image
references in `model_extra`, retained by import but previously absent from the
comparison API.

For **cn31958847**, baseline/candidate text lengths are 6863/7834 characters;
both saved Prompt SHA-256 values match recomputation:

- Baseline: `6c92469241e21bd225adab048cf0c63348cc9a5ac20dee1b24ce9399dd221ff9`
- Candidate: `3fd997b07e1fa1fcc472123d9b918260ab80413c8d9a8a04935fab12e662edb9`

Both record nine `image_inputs` with type, file reference, min_pixels and max_pixels.
They do not record per-image byte digests or timestamps in those entries. Timing
offsets are present in the separately labelled Run config and rendered Prompt.
Both explicitly record `reason_generated=false`, with forced-choice class-token
readout: Reason absence is in the source, not an import/display omission.

The Case overview shows reference BEV and saved Prompt diff above the two output
cards, so input context is visible immediately. Dedicated Prompt/config tabs
remain available. The list column has no duplicate media-preview button.

The compact header places tabs beside Case identity. Reference media stacks BEV
and Camera at t=0 (nearest recorded offset when exact zero is absent), with time
labels. Clicking each thumbnail opens that image mode, never video-first.
`/api/cases/{id}/media?kind=bev` skips camera/video and `kind=images` skips video;
these read the lightweight Issue identity, not full predictions/Reviews. A bounded
30-Case/30-second browser cache reuses image descriptors. Other media modes are
completed after the clicked image opens, with stale-response checks. Full image
transfer/decode is still subject to asset size and network latency.

Case overview layout: the top row pairs reference media on the left with both
Run output/Reason cards on the right; Prompt is full-width below. The dedicated
Prompt tab hides the top row for focused reading. Diff surfaces use theme tokens,
subtle added/deleted backgrounds and stronger inline marks. Alignment gaps remain
neutral, not falsely coloured as deletions. Provenance details remain expandable
with complete hashes while the default summary is compact.
