# Native video loading restoration — 2026-10-23

## Full-quality target-first loading — 2026-11-03 / cache748

The existing short-GOP files retain exactly their current video quality. A second
**lossless container remux** (`-c copy`, no encoder) enables native MediaSource
loading of just the GOP containing t0 or a requested seek position. A small
private manifest contains the init bytes and segment byte/time ranges. Each
compressed sample SHA256, raw presentation timestamp and duration must match
its input before atomic publication. Raw `tfdt`/signed `trun` composition times
are used: ffprobe's fragmented-file reorder delay must not be subtracted again.
Three actual media clips additionally passed browser pixel-hash comparisons at
frame boundaries. Untagged SD/multiple-track/unsupported files stay native;
there is no reduced bitrate, resolution, frame rate or preview-quality UI.

The same indexed Issue/scope/provider/root checks run before both manifest and
fragment responses. `?stream=segments-v1` returns a verified manifest or prompt202
pending, never awaiting preparation. `?playback=segments-v1&fingerprint=...`
requires the matching ready manifest; stale/missing data is409, never substituted
with progressive bytes. Range responses retain native `FileResponse`, private
caching and nosniff. Original and `short-gop-v1` contracts remain available.

Only the selected source is requested. Its first Range contains the target GOP;
streaming appends permit decoding before the whole GOP finishes. There is one
active segment fetch. Obsolete seeks/source changes abort it; repeated seeks
within that GOP share it. Playing fetches bounded forward data; paused playback
keeps the two neighbors. Whole GOP eviction bounds the recent buffer, including
partially cancelled data. Hidden players suspend network fetching, so expanding
or switching views cannot leave a second video competing for bandwidth.
Manifest timeout, missing cache, unsupported codecs/MSE and invalid/failed ranges
fall back once to the existing progressive path with position, rate and current
Play/cancel intent. Blob URLs never replace canonical asset/source identity.
Default paused t0, source-switch submitted-frame protection, native same-source
seeks and stable geometry remain. No new toolbar/status row is introduced.

`VideoStreamCache` uses a disposable `video_stream` directory. Preparation is
bounded and nonblocking with per-input locks, atomic receipts, source/file
identity invalidation and a5GiB disk guard. The independent warmer mode uses
only ready copies of current indexed captures:

```bash
python3 ra_triage_dashboard/scripts/warm_video_playback.py \
  --segments --source-root /published/media_layouts \
  --playback-cache-root /data/video_playback --cache-root /data/video_stream \
  --workers 2 --watch --report /owned-worker/progress.json
```

The existing short-GOP encoder warmer is unchanged and must not be duplicated.
No new runtime dependency or database/schema change is required. At inventory,
14310 ready inputs totaled242.73GiB with525.29GiB free; stream copies add roughly
the same storage, not another encoding. Counts and runtime/worker identities are
dated observations recorded with release evidence.

Controlled cold-HTTP-cache startup, Play immediately after mount, Chromium151:
20Mbps/40ms,10 starts/clip, all30 starts below1s; per-clip p95 large BEV727ms,
current BEV463ms, closeup302ms (combined p95552ms). At2Mbps/150ms, baseline3 and
candidate5 starts/clip: p95 large BEV7232→3843ms, current4899→2603ms,
closeup1863→1085ms. These are local sample measurements, not global production
p95. Bandwidth below the video's unchanged bitrate can still cause buffering.
Cold/unprepared streams retain native performance until preparation completes.

```bash
NODE_PATH=/path/to/playwright/node_modules \
SEGMENT_NATIVE_ROOT=/tmp/existing-native-samples \
SEGMENT_STREAM_ROOT=/tmp/existing-fragments-and-indexes \
node ra_triage_dashboard/tests/video_segments_browser.cjs
```

The segment root contains `candidate-build.json` and `fragkey-{name}.mp4` for
`big`, `current`, `closeup`; native samples use `optimized-{name}.mp4`.
`video_startup_benchmark.cjs` accepts the same stream root as
`STARTUP_STREAM_ROOT`; omit it for the progressive baseline. Evidence lives in
`/private/tmp/manual-weak-network-20261103/`. Browser checks use isolated desktop
Chromium and the Codex sidebar; viewport tests are not physical-phone/Safari/iOS
acceptance. Final production identity and preparation progress belong in
CURRENT_HANDOFF and release receipts.

## Native same-source seeks and stable geometry — 2026-11-03 / cache747

The cache746 held-frame path copied a full-resolution video frame on every
left/right seek and waited for submitted-frame proof plus two paint boundaries.
The inline native video occupied its intrinsic grid row while the absolute
canvas used the bordered parent's slightly shorter padding box (438.1875px vs
437.3125px in the reproduced desktop case). Swapping those surfaces produced
the reported small zoom pulse. A trailing75ms debounce also deferred all native
seeks during faster arrow-key repeats.

Ordinary same-source seeks now retain the native video surface; no canvas
readback or additional frame-proof gate is needed. Discrete buttons/arrows
queue at0ms, so repeats can decode before release; slider input retains75ms
coalescing and its final change flush. Source replacement still holds one old
frame and confirms the target; a seek during that hold updates its target and
cancels obsolete proof. The inline video uses zero-minimum grid tracks and
min-width/height0 so intrinsic video/poster sizes cannot overflow its stable
viewport; video and cover fit the same content rectangle, including during
metadata resets or square/missing posters. Expanded zoom/pan keeps
the existing shared canvas. Default paused-t0, selected-source-only loading,
Play/Space/cancel, rate, source positions and the toolbar remain unchanged.

The compositor regression additionally compares cover/video geometry and uses
held/repeated real arrow keys in both directions, asserting decoded progress
before release and no same-source canvas. Local baseline/candidate checks use
the same prepared actual media,10 alternating paused1s jumps for each of BEV
and closeup per version. Fully buffered media deliberately isolates UI/decoder
overhead: measured p95 BEV255.1→128.7ms and closeup148.7→60.5ms; canvas copies
20→0. These20 samples/version do not establish production or weak-network p95.

```bash
NODE_PATH=/path/to/playwright/node_modules \
SEEK_SAMPLES=/tmp/local-prepared-clips \
SEEK_PLAYER_JS=/tmp/prior-detail-media.js \
SEEK_RESULT=/tmp/seek-before.json \
node ra_triage_dashboard/tests/video_seek_benchmark.cjs
```

Omit `SEEK_PLAYER_JS` for the current module. Default sample filenames are
`optimized-current.mp4` and `optimized-closeup.mp4`; override `SEEK_NAMES` and
`SEEK_COUNT` as needed. Automatic checks never prebuffer production media.
Evidence: `/private/tmp/video-seek-geometry-20261103/`; deployment identity and
actual browser coverage belong in its final release records.

## Submitted-frame confirmation — 2026-11-03 / cache746

The cache745 frame hold could be removed after `seeked`/`currentTime` plus two
animation frames without proving which frame had reached the compositor. Source
changes and explicit seeks now require a matching `requestVideoFrameCallback`
presentation timestamp before uncovering the native surface. Reject frame0,
the wrong t0/retained-position frame, and retired source/seek callbacks. A paused
decoder may submit its target before native readiness catches up: retain that
proof and reveal on the later ready event without needing a second paused frame.
Browsers lacking this API retain the guarded native-event/paint fallback.

Keep one canvas and at most one pending frame callback for a transition; cancel
callbacks on replacement/error/disposal. A switch before any frame has decoded
uses a neutral cover so its new t0 poster cannot impersonate a requested23s
frame. Default initial native posters and metadata/t0 positioning are unchanged;
there is no new initial visibility gate, loading row, timer wait or alternate
video preload. Only the selected source loads. Explicit Play/Space/cancel and
per-source position/rate retention remain.

The adversarial regression fails against cache745 when `seeked` arrives before
the submitted frame, including reverse seeks and stale callback generations.
Actual-shell compositor capture additionally checks pixel colors for original,
frame0,t0 and23s targets, plus request logs before any source switch. The manual
fixture test uses desktop Chromium, not a physical phone or Safari/iOS:

```bash
python3 ra_triage_dashboard/tests/make_video_frame_fixtures.py /tmp/video-frame-fixtures
NODE_PATH=/path/to/playwright/node_modules \
FRAME_TEST_DIR=/tmp/video-frame-fixtures \
node ra_triage_dashboard/tests/video_presented_frame_browser.cjs
```

The verifier needs Pillow in the diagnostic Python (`FRAME_PYTHON` overrides it).
`tests/video_startup_benchmark.cjs` accepts `STARTUP_PLAYER_JS` to compare the
prior exact module with the candidate under the same media/network settings.
Deployment identity, before/after timings, request/pixel records and browser
coverage limits belong in the release evidence, not a blanket no-regression or
global p95 promise. Evidence: `/private/tmp/video-frame-handoff-20261103/`.

## Short-GOP playback copies and stable source handoff — 2026-11-02 / cache745

Each new player still pauses at t0 until its own explicit Play. Native
`preload=metadata`, asynchronous Play/cancel, relative timeline, full duration,
source position/rate retention and the compact toolbar remain.

The player requests `?playback=short-gop-v1` through the same scoped/indexed asset
route. A verified disposable copy uses H264 CRF21, the original dimensions,
frame timestamps/count and duration, an IDR at t0, keyframe gaps of at most two
seconds and a front `moov` index. This is a lossy playback encode; the original
file, capture receipt and original URL without the query remain unchanged.
Every copy passes packet/timestamp/geometry/keyframe checks and complete decoding
before its receipt is published atomically. Cache identity includes the resolved
source path, inode, size and nanosecond mtime; stale, partial or escaped copies
are never served. Range support is still native `FileResponse`.

A cold/missing copy falls back immediately to the original without caching that
fallback response and schedules one bounded background worker (32 queued sources,
two encoder threads, low priority, disk-space guard). No encode is awaited by an
HTTP response. A separately owned `scripts/warm_video_playback.py` worker can
prebuild published media roots and watch for new captures; its per-source locks
coordinate with HTTP and it writes only disposable playback cache files. Normal
identity, dataset isolation and asset-root checks always precede cache lookup.

For source changes and explicit seeks only, retain the last decoded frame over
the native surface until metadata, target data and two compositor opportunities
are available. Generation/seek checks reject obsolete completions; repeated
source changes retain one snapshot, and disposal releases it. Initial startup
keeps the native poster/video with no positioning gate or extra status UI.

### Measurements and reproduction

Actual older clips commonly had keyframes only at0s and25s. One34.2MB BEV needed
19.1MB of dependent packets to decode t0 at20s. Under simulated20Mbps/40ms with
HTTP cache disabled and Play immediately after mount, its original measured
8.23–8.25s to the first advancing presented frame. A two-second-GOP experiment
measured p95=0.899s over20 starts. Four copies generated by the actual cache
builder (large BEV, current BEV, current closeup, Camera) then passed ten starts
each: per-clip p95=0.45–0.89s. The preliminary large-clip copy took6.85–7.36s
under2Mbps/150ms; weak-network startup is still constrained by required bytes.
One five-second t0-region quality comparison measured SSIM0.9974; this is sampled
quality evidence, not pixel identity or a whole-corpus quality guarantee.

These are desktop Chromium151 controlled-network measurements with actual
media, not a production RUM p95 or physical-phone/Safari/iOS result. Existing
uncached media retains its prior performance until a copy is prepared. The
published-media inventory contains roughly14,000MP4 files, including historical
copies; readiness and failures must be reported from the running warmer.

Run `tests/video_startup_benchmark.cjs` with local fixtures using:

```bash
NODE_PATH=/path/to/playwright/node_modules \
STARTUP_SAMPLES=/path/to/local/fixtures \
STARTUP_NAMES=optimized STARTUP_COUNT=20 \
STARTUP_MBPS=20 STARTUP_LATENCY=40 STARTUP_BUDGET_MS=1000 \
node ra_triage_dashboard/tests/video_startup_benchmark.cjs
```

For a before/after comparison use `STARTUP_NAMES=original,optimized` and omit
`STARTUP_BUDGET_MS`; the original is expected to exceed the budget. Evidence: `/private/tmp/manual-video-startup-20261102/`, including
benchmark JSON, media inspection,24 actual-shell viewport/language/theme checks,
streaming checks and Codex sidebar local acceptance. Sidebar source handoff was
observed with a two-second injected source delay: the held frame covered native
time0, then the correct closeup replaced it paused at the requested19s. Signed-in
production interaction remains unconfirmed because the production tab timed out.

## Explicit playback for each new video — 2026-11-02 / cache739

Every newly created inline or expanded player starts paused at t0, including
when the previous Case was playing. Remove the page-wide playback preference;
only the current player's Play button, video click or Space can request playback.
Returning from an image view also stays paused until another explicit Play.
Changing the source within an already active player retains that player's current
choice and position/rate. Preloading metadata/t0 data is independent of playback.

The native start hint, Range loading and immediate asynchronous Play/cancellation
remain. This supersedes the cross-Case preference in the historical candidates
below. The cache737 compact toolbar remains, with no extra status text or spacer.

## Compact toolbar correction — 2026-11-02 / cache737

Remove the extra Paused/Waiting/Buffering/Playing text and its reserved width
from the inline and expanded player. Playback feedback uses the existing
Play/Pause button and aria-pressed; the new status element, CSS and unused
translations are removed. Internal asynchronous intent/cancellation and all
t0/source/position/rate behavior remain unchanged.

Resource selection advertises the known t0/current position with a start-only
media fragment. This is a start-position hint, not a promise that the first HTTP
request skips the MP4 header. The browser first reads required header/index and
probe data, then uses Range to fetch the nearest decodable keyframe around the
target. It does not have to sequentially download the entire prefix or suffix.
The cache736 controlled trace includes an initial header/probe range followed
by a t0-region range, and begins playback while the final30% never arrives.
This correction does not introduce a new streaming format, keyframe layout or
measured latency improvement.

## Release candidate assembly — 2026-11-02 / cache736

The cache730/735 candidates below were assembled on the latest production master
`eacbf32fcd8ee114bd24674257a349f15c55d640` for release as cache736. The current
planning timeline callback, keyboard guards, compact panel typography and saved
Case-label/Review draft fixes are retained. No backend, schema, dependency or
writer-policy changes are included.

The exact assembled player passed 62 scoped tests, three video shortcut/time
checks, 12 navigation races, 24 player viewport/language/theme combinations and
the tail-withheld Range-streaming acceptance. Issue tag navigation separately
passed 24 combinations. Records are in
`reports/video_t0_streaming_20261102/release-candidate/` in the source checkout.
The public signed-in acceptance tab connection timed out; no production browser
interaction validation is claimed. Release outcome belongs to the standard
private deployment receipt and current operational handoff.

## Early t0 startup and progressive buffering — 2026-11-02 / cache735 candidate

The native MP4 player already uses byte ranges and does not wait for the entire
file. This update advertises the initial midpoint with a start-only `#t=...`
media fragment before resource selection. Source changes advertise the retained
position, including fractional seconds; the canonical asset/track values stay
unchanged. Poster refresh strips the fragment when matching the active source.

When that start position is known, the current owner's Play choice submits
native asynchronous `play()` immediately, including before metadata arrives.
There is no full-download, custom byte-fetch or `canplaythrough` gate. The
browser handles the index, nearest decodable keyframe, playable window and
ongoing buffering. A second Space or hiding/disposal cancels the request.
Metadata reconciles the exact position without restarting a native seek that
is already at the target. Missing duration and browsers without media-fragment
support retain the metadata-based midpoint/seek fallback. Initial Pause,
source position/rate retention, canonical source selection and `preload=metadata`
remain supported. Only the requested Case/player loads video.

Controlled Chromium151 streaming acceptance used the same local 40s H264 clip,
expanded to 7,519,675 bytes with valid AVC filler NAL units without changing
frames or keyframe spacing. Responses were limited to 320KiB/s and the final
30% of the file was withheld entirely. The player requested the t0 keyframe
region at byte 3,702,784 and reached `playing` at 3,247 ms. At the first playback
sample (20.207s), the buffer included 19.696–23.356s and only about 15% of the
total bytes had been transmitted; neither response had completed. Buffering
continued during playback. Source position/rate retention and cancelling
before t0 data arrived also passed, with no page JavaScript errors.

This verifies progressive playback while later bytes are unavailable. The native
control experiment already showed progressive Range playback and similar
startup time; no measured first-frame speedup is claimed. Index/probe bytes and
keyframe decoding still require time. Original MP4 bytes/layout, server media
lookup/Range responses and production media are unchanged.

Validation: 62 scoped frontend/media/route tests, three directly executed video
shortcut/time behavior tests, the video-performance regression and 12 navigation
race scenarios passed. The actual shell/player/dialog regression passed all 24
Review/Case Labeling × 320/390/1440px × Chinese/English × dark/light combinations.
All browser testing used desktop Chromium151 with local synthetic data/media;
no real phone, Safari/iOS or authenticated production validation is claimed.
Evidence and reproduction commands: `reports/video_t0_streaming_20261102/`.
The candidate remains local and has not been deployed or pushed.

## Playback choice and loading feedback — 2026-11-02 / cache730 candidate

The session starts paused at t0. An explicit Play/Pause choice is shared by
subsequent Cases, video sources and the expanded player; a page reload starts a
new paused session. System suspension does not overwrite that preference.
Opening the media dialog pauses the inline player; leaving a detail/page or
switching to images cancels pending startup, including before metadata arrives.
Closing the dialog releases its player. Only the visible playback owner resumes.

Space, the Play/Pause button and clicking the video update the requested state
immediately. Before metadata, Play queues playback after positioning at t0;
another Space cancels it. Repeat keydown does not toggle repeatedly. The existing
toolbar now shows localized Paused / Waiting to play / Buffering / Playing in a
fixed-width status slot, with no loading overlay or transient extra row. A
buffered seek reconciles actual playback even when no new `playing` event fires.

Source changes preserve the requested state rather than snapshotting native
`video.paused` during `load()`. Generation and attempt checks ignore superseded
play promises. Rapid source switches retain position/rate and the last playback
choice; late metadata cannot reverse a subsequent Pause. Inherited playback is
muted; a browser play rejection restores the Play action and uses existing
localized failure feedback without retrying automatically.

Controlled local Chromium151 reproduction with the same 40s H264 clip and an
injected1200ms HTTP response delay showed `play` at142ms with readyState0, then
`playing` at1348ms. The original UI already said Pause while the frame remained
still. Two immediate source changes then incorrectly left the player paused.
After the change, the same delay still produces actual video-data/decode waiting
(playing1332ms in that sample), with immediate waiting feedback; rapid source
changes resume playback correctly. These are local injected-delay observations,
not production timings or evidence of a main-thread stall. MP4 bytes, metadata
preload policy, server media lookup and Range serving are unchanged.

Regression receipts and previews: `reports/video_playback_intent_20261102/`.
Validation completed: 62 scoped frontend/media/route contract tests passed;
the video-performance regression, 12 navigation-race scenarios and shared Issue
tag regression passed. Actual H264 playback passed 24 desktop Chromium151
viewport combinations: Review and Case Labeling at 320/390/1440px, Chinese and
English, dark and light. With a 500ms injected response delay, checks covered
immediate feedback before metadata, cancelling pending playback, repeat-safe
Space handling in the logic regression, rapid source cancellation/resumption,
the next Case inheriting the explicit choice, runtime language changes, stable
toolbar height, mobile Play touch targets and no document overflow. Additional
dialog checks covered playback ownership, switching to/from images and
suspending startup before late metadata. No page JavaScript errors occurred.
The 320px English/light and 1440px Chinese/dark player screenshots were visually
inspected. Issue tag navigation separately passed 24 viewport/language/theme
combinations.

The candidate is local and has not been deployed. Browser acceptance uses desktop
Chromium viewports and local media; it does not claim real phone/keyboard or
authenticated production coverage.

The regression was introduced by `e249d10` (2026-10-23 00:38 +08:00), not the later Cron/full-filter queue fix. Its loading status subscribed to `loadstart`, `waiting`, and `seeking`. A status element with `flex: 1 0 100%` sat between the playback controls and timeline, forcing the timeline onto another row whenever loading or a seek started. The same change replaced full-frame posters with 640×360 Gallery thumbnails, visibly soft when enlarged.

Restore the native display behavior established by `878318a`:

- Ordinary loading, Case changes, and seeking do not display a status row. A warning/retry remains available after 12 seconds or a media error, after the timeline in DOM order.
- Use the nearest-t0 full BEV/Camera frame as the native poster when already resolved. The video-only route does not scan images or inject a thumbnail.
- Late image discovery updates the existing video's poster and source-option posters without reloading, seeking, or replacing the video node. Each video source uses its corresponding image kind.
- Keep native video visible, with `preload="metadata"`. Do not introduce a positioning overlay, blur, or decoded-frame visibility gate.
- Keep resource disposal, coalesced seeks, source position/rate retention, shared dropdowns, Cron improvements and the complete filtered labeling queue.

Static cache: `manual-triage-614`. No database or media-file changes.

Validation: full local suite 749 passed / 5 skipped after API/poster restoration; 34 targeted media/shortcut tests passed after the status-row correction. The behavioral regression also checks transient status hiding, warning order, source-correct posters, descriptor immutability, no reload on late images, retry and disposal.

Chromium acceptance uses the actual frontend with read-only synthetic APIs and a delayed/rate-limited 40-second H264 clip. At 1440px Chinese/dark, 390px English/light and 320px English/dark, actual video decoded at t0, native visibility/filter were unchanged, timeline offset and toolbar height matched before/after load, seeking showed no status, source switching retained time, and error retry stayed accessible. The screenshot-specific Case Labeling path also passed at 2048px Chinese/dark, including Case switching and seeks. All selects were enhanced by the shared component. No document overflow, JavaScript exceptions or business writes occurred. This is desktop browser viewport testing, not physical-device or iOS validation. Evidence is under `reports/video_native_loading_20261023/`.

Deployment status and exact runtime SHA are recorded in the release result and CURRENT_HANDOFF.md. This change preserves the newer Trail reconciliation fixes merged from master.
