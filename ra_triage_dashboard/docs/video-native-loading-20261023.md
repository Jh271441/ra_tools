# Native video loading restoration — 2026-10-23

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
