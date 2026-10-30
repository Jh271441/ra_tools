"""Task-local Ares Capture renderer: closer BEV in a disposable context.

Only replaces the authenticated layout response consumed by this browser.
The maintained Ares renderer still owns seeking, readiness, retries and encoding.
"""
import argparse
import os
import hashlib
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse, parse_qs, parse_qsl, urlencode, urlunparse

REPO = Path(os.environ.get("RA_BEV_CAPTURE_ROOT", "/volume/home/workspace/ra_auto_triage")).resolve()
sys.path.insert(0, str(REPO))
from ares_capture.renderers.playwright import PlaywrightRenderer
from vlm.bev.scripts.capture_ares_studio import build_parser, run

ROOT = Path(__file__).resolve().parent
LAYOUT_ID = "7f4b2d9f-1218-4cd4-a93d-0654603173b9"
VIEWER = "Voyager3DPanel!2olm9lp"
EXPECTED_SHA = "52272f85a2475d4637891947469fe8034b2d0272fccf22e96cd144c9169fea64"


class CloseupRenderer(PlaywrightRenderer):
    def __init__(self, options, distance, keep_panels, ego_forward_m):
        super().__init__(options)
        self.distance = distance
        self.keep_panels = keep_panels
        self.ego_forward_m = ego_forward_m
        self._contexts = set()
        self._overrides = []
        self._frame_observations = []
        self._last_seek_target = None

    def install_view(self, context):
        if context in self._contexts:
            return
        self._contexts.add(context)
        def route_layout(route):
            url = urlparse(route.request.url)
            if parse_qs(url.query).get("id") != [LAYOUT_ID]:
                route.continue_()
                return
            response = route.fetch()
            payload = response.json()
            if payload.get("code") != 0 or payload.get("data", {}).get("id") != LAYOUT_ID:
                raise RuntimeError("Unexpected authenticated layout response")
            raw = payload["data"]["layout"]
            original_sha = hashlib.sha256(raw.encode()).hexdigest()
            if original_sha != EXPECTED_SHA:
                raise RuntimeError("Source layout changed; inspect before overriding")
            layout = json.loads(raw)
            viewer = layout["configById"][VIEWER]
            view = viewer["viewBehaviorContextParams"]["viewPoint"]
            original_distance = view["visualCameraToTargetDistance"]
            # Ares follows current_pose * prev_inverse_pose. Recenter both
            # stored world points in that saved ego frame, retaining the
            # camera direction and all topic/overlay settings.
            matrix = view["prevInvertTransformMatrix"]
            rotation = [[matrix[j * 4 + i] for j in range(3)] for i in range(3)]
            for i in range(3):
                for j in range(3):
                    dot = sum(rotation[i][k] * rotation[j][k] for k in range(3))
                    if abs(dot - float(i == j)) > 1e-6:
                        raise RuntimeError("Saved follow transform is not rigid")
            original_center = view["viewCenter"]
            original_ego_offset = [sum(rotation[i][j] * original_center[j] for j in range(3))
                                   + matrix[12 + i] for i in range(3)]
            desired_offset = [self.ego_forward_m, 0.0, 0.0]
            local_delta = [desired_offset[i] - original_ego_offset[i] for i in range(3)]
            world_delta = [sum(rotation[i][j] * local_delta[i] for i in range(3)) for j in range(3)]
            for key in ("viewCenter", "cameraPosition"):
                view[key] = [view[key][j] + world_delta[j] for j in range(3)]
            view["visualCameraToTargetDistance"] = self.distance
            if not self.keep_panels:
                layout["layout"] = VIEWER
            patched = json.dumps(layout, ensure_ascii=False, separators=(",", ":"))
            payload["data"]["layout"] = patched
            record = dict(layout_id=LAYOUT_ID, viewer=VIEWER,
                          original_layout_sha256=original_sha,
                          rendered_layout_sha256=hashlib.sha256(patched.encode()).hexdigest(),
                          original_visual_distance=original_distance,
                          visual_distance=self.distance,
                          original_ego_target_offset_m=original_ego_offset,
                          ego_target_offset_m=desired_offset,
                          bev_only=not self.keep_panels, persisted_to_cloud=False)
            self._overrides.append(record)
            print("[Closeup view] " + json.dumps(record), flush=True)
            route.fulfill(response=response, json=payload)
        context.route("**/ares-home/layout/query_by_share/**", route_layout)

    def _capture_frames(self, context, issue_id, variant, run_dir):
        self.install_view(context)
        start = len(self._overrides)
        files, metadata = super()._capture_frames(context, issue_id, variant, run_dir)
        if len(self._overrides) <= start:
            raise RuntimeError("No verified view override applied to screenshot page")
        metadata["view_override"] = self._overrides[-1]
        return files, metadata

    def _capture_video(self, context, plan, variant, run_dir):
        self.install_view(context)
        start = len(self._overrides)
        frame_start = len(self._frame_observations)
        # Include genuine source context before the first requested frame.
        # The MP4 timestamps stay unchanged; no rendered frame is reused.
        url = urlparse(variant.video_url)
        query = dict(parse_qsl(url.query, keep_blank_values=True))
        data_start = int(query["ds.start"]) - 1000
        data_end = int(query["ds.end"]) + 1000
        query.update({"ds.start": str(data_start), "ds.end": str(data_end)})
        variant = replace(variant, video_url=urlunparse(url._replace(query=urlencode(query))))
        files, metadata = super()._capture_video(context, plan, variant, run_dir)
        if len(self._overrides) <= start:
            raise RuntimeError("No verified view override applied to video page")
        metadata["view_override"] = self._overrides[-1]
        metadata["per_frame_scene_gate"] = "canvas_present_and_no_missing_scene_message"
        metadata["source_context"] = {"padding_ms": 1000, "start_ms": data_start,
                                      "end_ms": data_end, "frame_timestamps_unchanged": True}
        metadata["paused_before_each_seek"] = True
        metadata["seek_commit_check"] = "blurred_actual_current_time_and_paused_before_screenshot"
        metadata["frame_observations"] = self._frame_observations[frame_start:]
        return files, metadata

    def _screenshot_png(self, page, output):
        if output.name.startswith("frame-"):
            # Ares can briefly hide its timeline mask before /pose paints at
            # the left boundary. Require a real scene for every encoded frame.
            scene_ready = page.evaluate("""() =>
                !document.body.innerText.includes('Can not display 3D scene') &&
                [...document.querySelectorAll('canvas')].some(c => c.width > 100 && c.height > 100)
            """)
            self._wait_for_ares_video_scene(page, page.url)
            # The maintained caller already requires 500ms of hidden loading
            # before each screenshot. Repeat it only if the scene then needed
            # another load; normal frames keep that original readiness gate.
            if not scene_ready:
                self._wait_for_ares_timeline_data(page, page.url)
            observed = page.evaluate("""() => {
                const f = document.querySelector("input[aria-label='Playback Time Method']");
                const play = document.querySelector('button#Play');
                return {actual_ms:f ? Number(f.value) : null,
                    editing:document.activeElement === f,
                    paused:!!play && play.getBoundingClientRect().width > 0};
            }""")
            observed["target_ms"] = self._last_seek_target
            if observed["editing"] or not observed["paused"] or observed["actual_ms"] is None or abs(observed["actual_ms"] - self._last_seek_target) > 1:
                raise RuntimeError("Screenshot time/state drifted after exact seek: " + json.dumps(observed))
            self._frame_observations.append(observed)
        return super()._screenshot_png(page, output)

    def _seek_ares_playback_time(self, page, timestamp_ms):
        if not page.locator("button#Play").is_visible():
            if not self._click_visible_ares_pause_control(page) or not self._wait_for_ares_paused(page, timeout_ms=5000):
                self._log_seek_diagnostics(page, timestamp_ms)
                raise RuntimeError("Ares must expose its paused Play control before exact seek")
        field = page.locator("input[aria-label='Playback Time Method']")
        if not field.is_visible():
            self._log_seek_diagnostics(page, timestamp_ms)
        retries = super()._seek_ares_playback_time(page, timestamp_ms)
        # While editing, Ares displays the typed text even when onSeek has
        # not yet changed currentTime. Blur through ordinary keyboard focus,
        # then validate the non-editing current-time display.
        field.press("Tab", timeout=min(self.options.timeout_ms, 5000))
        try:
            page.wait_for_function("""expected => {
                const f = document.querySelector("input[aria-label='Playback Time Method']");
                return f && document.activeElement !== f &&
                    Number.isFinite(Number(f.value)) && Math.abs(Number(f.value)-expected) <= 1;
            }""", arg=timestamp_ms, timeout=min(self.options.timeout_ms, 10000))
        except Exception:
            self._log_seek_diagnostics(page, timestamp_ms)
            raise
        if not self._wait_for_ares_paused(page, timeout_ms=5000):
            raise RuntimeError("Ares resumed playback during exact seek")
        self._last_seek_target = timestamp_ms
        return retries

    def _log_seek_diagnostics(self, page, timestamp_ms):
        state = page.evaluate("""() => {
            const field = document.querySelector("input[aria-label='Playback Time Method']");
            const ancestors = [];
            for (let e = field; e && ancestors.length < 10; e = e.parentElement) {
                const s = getComputedStyle(e), r = e.getBoundingClientRect();
                ancestors.push({tag:e.tagName,id:e.id,cls:e.className,
                    display:s.display,visibility:s.visibility,opacity:s.opacity,
                    rect:{x:r.x,y:r.y,width:r.width,height:r.height}});
            }
            return {field:field ? {value:field.value,disabled:field.disabled} : null,
                ancestors,viewport:{width:innerWidth,height:innerHeight},
                noScene:document.body.innerText.includes('Can not display 3D scene')};
        }""")
        directory = ROOT / "diagnostics" / "hidden-playback-input"
        directory.mkdir(parents=True, exist_ok=True)
        name = f"{timestamp_ms}-{time.time_ns()}"
        state["target_ms"] = timestamp_ms
        (directory / (name + ".json")).write_text(json.dumps(state, indent=2))
        page.screenshot(path=str(directory / (name + ".png")))
        print("[Seek diagnostics] " + json.dumps(state), flush=True)


def main():
    own = argparse.ArgumentParser(add_help=False)
    own.add_argument("--view-distance", type=float, default=30.0)
    own.add_argument("--keep-panels", action="store_true")
    own.add_argument("--ego-forward-m", type=float, default=4.0)
    config, remaining = own.parse_known_args()
    if not 20 <= config.view_distance <= 150:
        raise ValueError("Unsupported preview visual distance")
    if not -5 <= config.ego_forward_m <= 10:
        raise ValueError("Unsupported preview ego target offset")
    args = build_parser().parse_args(remaining)
    return run(args, renderer_factory=lambda name, options:
               CloseupRenderer(options, config.view_distance, config.keep_panels, config.ego_forward_m))


if __name__ == "__main__":
    raise SystemExit(main())
