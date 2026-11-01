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
Text follows the player's intended timeline position (including initial t0 and
queued seeks) independently of video metadata, buffering, decoding or errors.
Available text is never hidden while waiting for a video frame.
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
Plain G toggles the visible player's panel, including expanded media; its button
and the shared shortcut guide show G. Its keycap reuses the same shared styling
as the RA Event T badge. Text inputs, IME, held/repeated keys,
modifier combinations, open pickers and unrelated dialogs retain their behavior.

Object ID uses only the explicit safe-integer API field. Missing/unrecognized
values are shown as not provided; the UI never derives object type or identity
from a constraint-ID token. Original text is rendered verbatim with textContent;
debug values are not separately projected into the panel.

## Extraction contract

`GET /api/cases/{issue_id}/planning-constraints?offset_ms=0` first queries saved
text by Issue ID and publish timestamp. It returns the same bounded window used
by the player. `timestamp_ms=<absolute publish time>` is also supported instead
of `offset_ms`; the response includes `query_timestamp_ms` and `matched_frame`
(latest publish at/before that time, maximum age150ms, or null).
Supplying both time parameters, invalid IDs, or offsets beyond ±60s is rejected.
Clients cannot provide filesystem paths, trips or replacement anchors.

The historical index supplies the verified saved result's trip/t0 even if the
Issue has no video/capture. The Issue must still exist in the ordinary or
registered-reference lookup; this does not create a writable Case. Indexed hits
do not scan media, read Bags, start workers, or depend on a Model Run. On a true
miss, the existing media capture remains required for bounded lazy extraction.
The endpoint does not write labels, GT, Runs or Trail.

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

## Saved text index

`data_dir/planning_constraints/history.sqlite3` is a derived immutable SQLite
snapshot, separate from the lazy JSON cache and production PostgreSQL. Its
`frames` primary key `(issue_id,timestamp_ms)` provides an indexed range query;
each request opens the file read-only and returns at most1000 frames/2MiB.
No source JSON tree or whole SQLite file is parsed on the request path.
Snapshot schema/extractor/source checks fail closed; a damaged snapshot does not
trigger an automatic Bag download. Existing callers with a known capture also
require an exact trip/anchor match. The archive keeps result SHA, membership SHA,
version, original coverage bounds, source status, gaps and error count alongside
verbatim frame fields. `read_source=historical_index` identifies this read path.

Build from saved results only, in an independent staging directory:

```bash
python3 ra_triage_dashboard/scripts/index_planning_constraints.py \
  --source-root /trusted/task-root \
  --expected-membership-sha256 <membership.json-file-SHA256> \
  --output /independent/staging/history.sqlite3
```

Repeat `--source-root` to include other full memberships (omit the single-file
SHA pin when combining different manifests). The importer checks all members,
result/capture identity, extractor version, exact frozen40s window, ordered real
frames, state/counts, t0 causal alignment and recomputed gaps. Missing results,
conflicting copies, changed input files and invalid records abort without
replacing a prior index. SQLite integrity/count checks and a result-SHA ledger
precede atomic replacement; the output is bounded to2GiB. Preserve source JSON
and reports. Verify the staged snapshot before atomically installing the file
at the fixed data-dir path; retain the previous snapshot outside the lazy cache.
Rebuild with the full intended source set when importing later saved results.
The importer has no scheduler, network, Bag reader or collector side effects.

An indexed `partial_source` or `failed` result remains partial/failed in response
metadata, even when some text is usable. Recorded holes return no matching
frame, and never start lazy extraction inside that saved window. Unresolved and
no-constraint frames retain their states/raw text. Index import completion does
not establish that original source collection or final source audit is complete.

## Bounded lazy lifecycle (true misses)

No request on case first paint. Opening requests the current8s bucket with200ms
overlap on either side. While open and playing, at most one adjacent window warms.
Closing/disposal aborts polling; stale responses cannot update another case. Cache
is per player (max32 windows). Server responses are no-store to intermediaries.

Server has one worker at a time plus a cross-process flock, no unbounded queue.
Worker timeout120s, file limit512MiB, address space4GiB, minimum free disk2GiB;
no changes to runtime dependencies. Limits bound an individual process/file, not
an aggregate cgroup. Failed reads back off60s. Source bags and logs are temporary;
shutdown/timeout terminates the owned worker group before scratch cleanup. Small
Lazy JSON facts persist under data_dir/planning_constraints, keyed by extractor
version, Issue, trip, anchor and bucket. Retain at most2048 entries/64MiB (newest
first); deleting these derived caches is recoverable by extraction. No shared media
or planning bag cache or historical text index is deleted. Uncached Bag reads take seconds;
uncached fast seeking or accelerated playback may need to pause for loading.

## Verification

Pure extractor/service tests cover raw traffic-light ID + Object0/brake-1,
primitive/search precedence, missing/ambiguous selection, out-of-range index,
singleflight, bucket boundaries, cache identity, backoff, low disk and timeout cleanup.
API tests bind facts to the Issue's media anchor and reject invalid offsets.
Index/API tests cover exact raw/Object0, publish-time/no-lookahead selection,
partial/failed holes without retries, independent registry-only text, conflicting
identity/time parameters, malformed snapshots, atomic import failure and cold fallback.
Node tests cover causal/time-tolerance matching and frontend lifecycle contracts.
`tests/fixtures/planning-constraint.html` uses actual UI modules with explicitly
synthetic API/video for browser interaction checks; never use it as production data.
Five retained real planning bags (198 messages) were read on cloud; traffic lights
and object IDs retain their raw forms. An actual8.4s lazy worker window returned84
messages with the existing Voyager runtime and resource limits. No model inference.
