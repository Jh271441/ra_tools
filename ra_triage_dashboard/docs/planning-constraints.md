# Manual planning constraint

The inline Issue video toolbar has one compact Planning constraint button. Click
opens an upward, nonmodal, viewport-clamped panel. One primary card holds the
current dominant constraint ID, copy action and Object ID row. A collapsed Raw
text disclosure preserves the complete original string. Separate debug fields,
timestamps and source-path explanations are omitted. Escape, outside click
and the close button dismiss it; playback controls do not. Inline video sources
are in the existing upper shared media picker (including Camera102), not a second
bottom selector. Expanded media dialogs retain their existing source picker.

This is an Issue/media fact, not Model Run Reason. It follows video time and never
translates IDs into object categories. Object ID zero remains literal.
No matching frame, unresolved candidate, no dominant constraint, unavailable and
failed reads are distinct; none retain an old ID. Language and theme use existing
Workbench mechanisms. Mobile panels wrap identifiers and scroll within viewport.

The panel uses a wider desktop measure and a monospace constraint ID.
Narrow screens keep44px controls and a scrollable viewport-bound panel.
Opening moves focus into the nonmodal panel. Plain Left/Right from its controls
or opener use that player's existing seek buttons, then return focus to the
player, keeping the panel open and respecting the selected jump step. Escape
closes only this panel and restores its opener; arrows still seek from there.
Modified keys, IME and editable/select controls retain their native behavior.
An expanded player's panel stays inside its containing dialog's top layer.

Object ID uses only the explicit safe-integer API field. Missing/unrecognized
values are shown as not provided; the UI never derives object type or identity
from a constraint-ID token. Original text is rendered verbatim with textContent;
debug values are not separately projected into the panel.

## Extraction contract

`GET /api/cases/{issue_id}/planning-constraints?offset_ms=0` reads the Issue's
indexed media capture trip/timestamp; clients cannot provide filesystem paths or
arbitrary trips. Invalid IDs/offsets beyond ±60s are rejected. Missing media anchors
fail closed. The endpoint does not write labels, GT, Runs or Trail.

Source: `/planning/planning_debug`, Ares virtual field
`/studio_node/planning/speed_table_raw.dominantConstraint`.
Ported from Vitruvian **8c071689553ac88ecd60a3091946d3af09cf7301**,
`packages/studio-base/src/voyager-adaptor/adaptor/planning-new/speed-table-raw.ts`
and `ares-utils/modules/planning/index.ts`:

- First DECOUPLED_LANE_FOLLOW, otherwise DECOUPLED_FORWARD.
- Exactly one selected trajectory meta and matching candidate; selected speed_ix.
  Unlike Ares's first-meta fallback, absent/ambiguous selection is unresolved.
  This is the default selected candidate, not a user's manual Ares candidate override.
- Nonempty primitive_constraints wins, otherwise search_debug.constraints.
- Preserve raw unique_constraint_id, dominant_constraint_obj_id, gap-align result
  and earliest_brake_time_ix. Out-of-range dominant index yields Ares's
  `No dominant constraint.`; missing selection/field does not invent a constraint.

Video t0 retains the existing clip midpoint convention. Match the most recent
published planning message at or before capture_timestamp_ms + relative video
offset, with maximum age150ms; never look ahead or bridge a missing interval.
Metadata retains both publish and planning timestamps for alignment.

## Bounded lazy lifecycle

No request on case first paint. Opening requests the current8s bucket with200ms
overlap on either side. While open and playing, at most one adjacent window warms.
Closing/disposal aborts polling; stale responses cannot update another case. Cache
is per player (max32 windows). Server responses are no-store to intermediaries.

Server has one worker at a time plus a cross-process flock, no unbounded queue.
Worker timeout120s, file limit512MiB, address space4GiB, minimum free disk2GiB;
no changes to runtime dependencies. Limits bound an individual process/file, not
an aggregate cgroup. Failed reads back off60s. Source bags and logs are temporary;
shutdown/timeout terminates the owned worker group before scratch cleanup. Small
JSON facts alone persist under data_dir/planning_constraints, keyed by extractor
version, Issue, trip, anchor and bucket. Retain at most2048 entries/64MiB (newest
first); deleting these derived caches is recoverable by extraction. No shared media
or planning bag cache is deleted. Initial reads take seconds, not instant realtime;
uncached fast seeking or accelerated playback may need to pause for loading.

## Verification

Pure extractor/service tests cover raw traffic-light ID + Object0/brake-1,
primitive/search precedence, missing/ambiguous selection, out-of-range index,
singleflight, bucket boundaries, cache identity, backoff, low disk and timeout cleanup.
API tests bind facts to the Issue's media anchor and reject invalid offsets.
Node tests cover causal/time-tolerance matching and frontend lifecycle contracts.
`tests/fixtures/planning-constraint.html` uses actual UI modules with explicitly
synthetic API/video for browser interaction checks; never use it as production data.
Five retained real planning bags (198 messages) were read on cloud; traffic lights
and object IDs retain their raw forms. An actual8.4s lazy worker window returned84
messages with the existing Voyager runtime and resource limits. No model inference.
