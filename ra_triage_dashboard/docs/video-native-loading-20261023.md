# Native video loading restoration — 2026-10-23

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
