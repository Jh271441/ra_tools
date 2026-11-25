import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "../../api/client";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";
import { useShortcut } from "../../core/shortcutManager";
import { normalizeAssetUrl, showWorkbenchToast } from "../../features/review/reviewHelpers";
import { ModalDialog } from "../ui/ModalDialog";
import { UiSelect } from "../ui/UiSelect";

export interface MediaFrameDescriptor {
  url: string;
  label?: string;
  offset_ms?: number | null;
  offset_sec?: number | null;
  index?: number;
}

export interface MediaVideoTrack {
  url: string;
  label?: string;
  source_id?: string;
  poster_url?: string;
  duration_ms?: number;
  start_offset_sec?: number;
  frame_step_ms?: number;
}

export interface MediaVideoDescriptor extends MediaVideoTrack {
  tracks?: MediaVideoTrack[];
}

export interface CaseMediaPayload {
  issue_id?: string;
  media_status?: string;
  preview_thumbnail_url?: string;
  assets?: {
    frames?: MediaFrameDescriptor[];
    video?: MediaVideoDescriptor | null;
  };
  camera?: {
    frames?: MediaFrameDescriptor[];
  };
}

interface PlanningFrame {
  timestamp_ms: number;
  valid_until_ms?: number;
  status?: string;
  constraint_id?: string;
  object_id?: number | null;
  raw?: string;
}

interface PlanningWindowResponse {
  issue_id?: string;
  bucket?: number;
  status?: string;
  anchor_ms?: number;
  tolerance_ms?: number;
  frames?: PlanningFrame[];
}

export interface MediaStageProps {
  issueId: string;
  media: CaseMediaPayload | null;
  loading?: boolean;
  error?: string | null;
  lang: UiLanguage;
  active?: boolean;
  compact?: boolean;
  hideExpand?: boolean;
  onRetryMedia?: () => void;
}

function frameOffsetMs(frame: MediaFrameDescriptor | undefined): number {
  if (!frame) return Number.NaN;
  if (frame.offset_ms != null && Number.isFinite(Number(frame.offset_ms))) return Number(frame.offset_ms);
  if (frame.offset_sec != null && Number.isFinite(Number(frame.offset_sec))) return Number(frame.offset_sec) * 1000;
  return Number.NaN;
}

export function findT0FrameIndex(frames: MediaFrameDescriptor[]): number {
  if (!frames.length) return 0;
  const exact = frames.findIndex((f) => frameOffsetMs(f) === 0);
  if (exact >= 0) return exact;
  let best = -1;
  let dist = Infinity;
  frames.forEach((f, idx) => {
    const off = frameOffsetMs(f);
    if (Number.isFinite(off) && Math.abs(off) < dist) {
      dist = Math.abs(off);
      best = idx;
    }
  });
  return best >= 0 ? best : Math.floor(frames.length / 2);
}

export function formatFrameLabel(frame: MediaFrameDescriptor | undefined, index: number): string {
  if (frame?.label) return frame.label;
  const ms = frameOffsetMs(frame);
  if (Number.isFinite(ms)) {
    const sec = ms / 1000;
    if (Math.abs(sec) < 0.05) return "t0";
    return `${sec > 0 ? "+" : ""}${Math.abs(sec % 1) < 0.05 ? Math.round(sec) : sec.toFixed(1)}s`;
  }
  return `#${index + 1}`;
}

function formatSignedSec(value: number): string {
  if (!Number.isFinite(value) || Math.abs(value) < 0.05) return "t0";
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}s`;
}

function localizedTrackLabel(label: string | undefined, lang: UiLanguage): string {
  const raw = String(label || "").trim();
  if (raw === "BEV 视频") return bilingual(lang, "BEV 视频", "BEV video");
  if (raw === "局部 BEV 视频") return bilingual(lang, "局部 BEV 视频", "Closeup BEV video");
  if (raw === "Camera102 视频") return bilingual(lang, "Camera102 视频", "Camera102 video");
  return raw || bilingual(lang, "Ares Studio 视频", "Ares Studio video");
}

function isCameraTrack(track: MediaVideoTrack): boolean {
  return track.label === "Camera102 视频" || /\/camera-video(?:[?#]|$)/.test(String(track.url || ""));
}

function buildPlaybackUrl(rawUrl: string, startSec: number | null): string {
  const norm = normalizeAssetUrl(rawUrl);
  if (!norm) return "";
  const sep = norm.includes("?") ? "&" : "?";
  const withFlag = norm.includes("playback=short-gop-v1") ? norm : `${norm}${sep}playback=short-gop-v1`;
  if (startSec !== null && Number.isFinite(startSec) && startSec >= 0) {
    return `${withFlag}#t=${Math.round(startSec * 1000) / 1000}`;
  }
  return withFlag;
}

function pickPlanningFrame(frames: PlanningFrame[], timestamp: number, tolerance = 150): PlanningFrame | null {
  let best: PlanningFrame | null = null;
  for (const item of frames) {
    if (Number.isFinite(item.timestamp_ms) && item.timestamp_ms <= timestamp) {
      if (!best || item.timestamp_ms >= best.timestamp_ms) best = item;
    }
  }
  if (!best) return null;
  if (timestamp - best.timestamp_ms > tolerance) return null;
  if (Number.isFinite(best.valid_until_ms) && timestamp >= (best.valid_until_ms as number)) return null;
  return best;
}

export const MediaStage: React.FC<MediaStageProps> = ({
  issueId,
  media,
  loading = false,
  error = null,
  lang,
  active = true,
  compact = false,
  hideExpand = false,
  onRetryMedia,
}) => {
  const bevFrames = useMemo(
    () => (media?.assets?.frames || []).map((f) => ({ ...f, url: normalizeAssetUrl(f.url) })).filter((f) => Boolean(f.url)),
    [media],
  );
  const cameraFrames = useMemo(
    () => (media?.camera?.frames || []).map((f) => ({ ...f, url: normalizeAssetUrl(f.url) })).filter((f) => Boolean(f.url)),
    [media],
  );
  const videoTracks = useMemo(() => {
    const primary = media?.assets?.video;
    if (!primary?.url) return [] as MediaVideoTrack[];
    const seen = new Set<string>();
    const list: MediaVideoTrack[] = [];
    for (const raw of [primary, ...(primary.tracks || [])]) {
      if (!raw?.url) continue;
      const url = normalizeAssetUrl(raw.url);
      if (!url || seen.has(url)) continue;
      seen.add(url);
      const isCam = isCameraTrack(raw);
      const fallbackFrames = isCam ? cameraFrames : bevFrames;
      const fallbackPoster =
        raw.source_id === "bev_closeup"
          ? normalizeAssetUrl(raw.poster_url)
          : normalizeAssetUrl(fallbackFrames[findT0FrameIndex(fallbackFrames)]?.url || raw.poster_url);
      list.push({
        ...raw,
        url,
        poster_url: fallbackPoster,
        duration_ms: raw.duration_ms ?? primary.duration_ms,
        start_offset_sec: raw.start_offset_sec ?? primary.start_offset_sec,
        frame_step_ms: raw.frame_step_ms ?? primary.frame_step_ms,
      });
    }
    return list;
  }, [media, bevFrames, cameraFrames]);

  const hasBev = bevFrames.length > 0;
  const hasCamera = cameraFrames.length > 0;
  const hasVideo = videoTracks.length > 0;

  // Source value: "bev" | "camera" | "video" | "track:<url>"
  const [sourceKey, setSourceKey] = useState<string>("video");
  const [bevIndex, setBevIndex] = useState<number>(0);
  const [cameraIndex, setCameraIndex] = useState<number>(0);
  const [expanded, setExpanded] = useState<boolean>(false);
  const [zoom, setZoom] = useState<number>(1);
  const lastBevTrackUrlRef = useRef<string>("");

  // Video playback state
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [playing, setPlaying] = useState<boolean>(false);
  const [videoTime, setVideoTime] = useState<number>(0);
  const [videoDuration, setVideoDuration] = useState<number>(0);
  const [stepSec, setStepSec] = useState<number>(1);
  const [rate, setRate] = useState<number>(1);
  const [videoStatus, setVideoStatus] = useState<string>("");
  const [videoRetryNonce, setVideoRetryNonce] = useState<number>(0);

  // Planning constraints popover state
  const [planningOpen, setPlanningOpen] = useState<boolean>(false);
  const [planningCopied, setPlanningCopied] = useState<boolean>(false);
  const [planningCache, setPlanningCache] = useState<Record<number, PlanningWindowResponse>>({});

  // Reset per issue
  useEffect(() => {
    setBevIndex(findT0FrameIndex(bevFrames));
    setCameraIndex(findT0FrameIndex(cameraFrames));
    setZoom(1);
    setPlaying(false);
    setVideoStatus("");
    setPlanningOpen(false);
    setPlanningCache({});
    if (hasVideo) setSourceKey("video");
    else if (hasBev) setSourceKey("bev");
    else if (hasCamera) setSourceKey("camera");
  }, [issueId, hasVideo, hasBev, hasCamera, bevFrames.length, cameraFrames.length]);

  const activeKind: "bev" | "camera" | "video" =
    sourceKey === "bev" ? "bev" : sourceKey === "camera" ? "camera" : "video";

  const activeTrack = useMemo(() => {
    if (!videoTracks.length) return null;
    if (sourceKey.startsWith("track:")) {
      const targetUrl = sourceKey.slice(6);
      const found = videoTracks.find((t) => t.url === targetUrl);
      if (found) return found;
    }
    return videoTracks[0];
  }, [videoTracks, sourceKey]);

  useEffect(() => {
    if (activeTrack && !isCameraTrack(activeTrack)) {
      lastBevTrackUrlRef.current = activeTrack.url;
    }
  }, [activeTrack]);

  const configuredDuration = Math.max(0, Number(activeTrack?.duration_ms || 0) / 1000);
  const effectiveDuration = videoDuration > 0 ? videoDuration : configuredDuration;
  const t0PlayerSec = effectiveDuration > 0 ? effectiveDuration / 2 : 0;
  const startOffsetSec = t0PlayerSec > 0 ? -t0PlayerSec : Number(activeTrack?.start_offset_sec ?? 0);
  const frameStepSec = Math.max(0.01, Number(activeTrack?.frame_step_ms || 100) / 1000);

  const playbackUrl = useMemo(() => {
    if (!activeTrack?.url) return "";
    return buildPlaybackUrl(activeTrack.url, configuredDuration > 0 ? configuredDuration / 2 : null);
  }, [activeTrack?.url, configuredDuration]);

  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    el.playbackRate = rate;
  }, [rate, playbackUrl]);

  const stepOptions = useMemo(() => {
    const vals = Array.from(new Set([frameStepSec, 0.5, 1, 5])).sort((a, b) => a - b);
    return vals.map((s) => ({
      value: String(s),
      label:
        s === frameStepSec
          ? bilingual(lang, `${s}s (单帧)`, `${s}s (frame)`)
          : `${s}s`,
    }));
  }, [frameStepSec, lang]);

  const rateOptions = useMemo(
    () => [
      { value: "0.5", label: "0.5×" },
      { value: "1", label: "1×" },
      { value: "1.5", label: "1.5×" },
      { value: "2", label: "2×" },
    ],
    [],
  );

  const sourceOptions = useMemo(() => {
    const opts: { value: string; label: string; disabled?: boolean }[] = [
      {
        value: "bev",
        label: bilingual(lang, `BEV 图片 · ${bevFrames.length}`, `BEV images · ${bevFrames.length}`),
        disabled: !hasBev,
      },
      {
        value: "camera",
        label: bilingual(lang, `Camera 图片 · ${cameraFrames.length}`, `Camera images · ${cameraFrames.length}`),
        disabled: !hasCamera,
      },
      {
        value: "video",
        label: bilingual(lang, `Ares Studio 视频 · ${hasVideo ? 1 : 0}`, `Ares Studio video · ${hasVideo ? 1 : 0}`),
        disabled: !hasVideo,
      },
    ];
    for (const track of videoTracks.slice(1)) {
      opts.push({
        value: `track:${track.url}`,
        label: localizedTrackLabel(track.label, lang),
      });
    }
    return opts;
  }, [lang, bevFrames.length, cameraFrames.length, hasBev, hasCamera, hasVideo, videoTracks]);

  const togglePlay = useCallback(() => {
    const el = videoRef.current;
    if (!el) return;
    if (el.paused) {
      void el.play().catch(() => {
        setVideoStatus(bilingual(lang, "浏览器阻止了播放，请再次点击。", "Playback blocked; click again."));
      });
    } else {
      el.pause();
    }
  }, [lang]);

  const seekVideoTo = useCallback(
    (targetSec: number) => {
      const el = videoRef.current;
      if (!el) return;
      const maxSec = effectiveDuration > 0 ? effectiveDuration : Number.MAX_SAFE_INTEGER;
      const clamped = Math.max(0, Math.min(maxSec, targetSec));
      el.currentTime = clamped;
      setVideoTime(clamped);
    },
    [effectiveDuration],
  );

  const jumpVideo = useCallback(
    (direction: -1 | 1) => {
      const el = videoRef.current;
      if (!el) return;
      seekVideoTo((Number.isFinite(el.currentTime) ? el.currentTime : videoTime) + direction * stepSec);
    },
    [seekVideoTo, stepSec, videoTime],
  );

  const jumpToT0 = useCallback(() => {
    if (activeKind === "video") {
      seekVideoTo(t0PlayerSec);
    } else if (activeKind === "bev") {
      setBevIndex(findT0FrameIndex(bevFrames));
    } else {
      setCameraIndex(findT0FrameIndex(cameraFrames));
    }
  }, [activeKind, seekVideoTo, t0PlayerSec, bevFrames, cameraFrames]);

  const moveFrame = useCallback(
    (delta: number) => {
      if (activeKind === "bev" && bevFrames.length) {
        setBevIndex((prev) => (prev + delta + bevFrames.length) % bevFrames.length);
      } else if (activeKind === "camera" && cameraFrames.length) {
        setCameraIndex((prev) => (prev + delta + cameraFrames.length) % cameraFrames.length);
      }
    },
    [activeKind, bevFrames.length, cameraFrames.length],
  );

  const selectTrack = useCallback(
    (track: MediaVideoTrack | undefined, missingMsg: [string, string]) => {
      if (!track) {
        showWorkbenchToast(bilingual(lang, missingMsg[0], missingMsg[1]), true);
        return;
      }
      const primary = videoTracks[0];
      setSourceKey(primary && track.url === primary.url ? "video" : `track:${track.url}`);
    },
    [lang, videoTracks],
  );

  // Planning constraints fetch for current 8s bucket
  const relativeMs = Math.round((videoTime + startOffsetSec) * 1000);
  const planningBucket = Math.floor(relativeMs / 8000);
  const planningEnabled = active && planningOpen && activeKind === "video" && Boolean(issueId);

  useEffect(() => {
    if (!planningEnabled) return;
    const cached = planningCache[planningBucket];
    if (cached && cached.status && !["loading", "busy", "pending"].includes(cached.status)) return;
    let cancelled = false;
    const controller = new AbortController();
    void apiRequest<PlanningWindowResponse>(
      `/api/cases/${encodeURIComponent(issueId)}/planning-constraints?offset_ms=${planningBucket * 8000}`,
      { signal: controller.signal },
    )
      .then((res) => {
        if (!cancelled) {
          setPlanningCache((prev) => ({ ...prev, [planningBucket]: res }));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setPlanningCache((prev) => ({ ...prev, [planningBucket]: { status: "error" } }));
        }
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [planningEnabled, planningBucket, issueId, planningCache]);

  const activePlanningData = planningCache[planningBucket];
  const activePlanningFrame = useMemo(() => {
    if (activePlanningData?.status !== "ready" || !Number.isFinite(activePlanningData.anchor_ms)) return null;
    return pickPlanningFrame(
      activePlanningData.frames || [],
      (activePlanningData.anchor_ms as number) + relativeMs,
      activePlanningData.tolerance_ms || 150,
    );
  }, [activePlanningData, relativeMs]);

  const copyConstraintId = useCallback(async () => {
    const id = activePlanningFrame?.status === "ready" ? String(activePlanningFrame.constraint_id || "") : "";
    if (!id) return;
    try {
      await navigator.clipboard.writeText(id);
      setPlanningCopied(true);
      window.setTimeout(() => setPlanningCopied(false), 1600);
    } catch {
      showWorkbenchToast(bilingual(lang, "复制失败", "Copy failed"), true);
    }
  }, [activePlanningFrame, lang]);

  // Register unified shortcuts via ShortcutManager (scoped to "modal" when expanded or "page" inline)
  const shortcutScope = expanded ? "modal" : "page";
  const shortcutsActive = active && Boolean(hasBev || hasCamera || hasVideo);

  useShortcut(
    shortcutScope,
    "b",
    (e) => {
      if (!hasBev) return false;
      e.preventDefault();
      setSourceKey("bev");
      return true;
    },
    { enabled: shortcutsActive },
  );
  useShortcut(
    shortcutScope,
    "c",
    (e) => {
      if (!hasCamera) return false;
      e.preventDefault();
      setSourceKey("camera");
      return true;
    },
    { enabled: shortcutsActive },
  );
  useShortcut(
    shortcutScope,
    "v",
    (e) => {
      if (!hasVideo) return false;
      e.preventDefault();
      const bevTrack =
        videoTracks.find((t) => t.url === lastBevTrackUrlRef.current) ||
        videoTracks.find((t) => !isCameraTrack(t)) ||
        videoTracks[0];
      selectTrack(bevTrack, ["当前 Issue 暂无 BEV 视频。", "No BEV video available."]);
      return true;
    },
    { enabled: shortcutsActive },
  );
  useShortcut(
    shortcutScope,
    "Shift+v",
    (e) => {
      if (!hasVideo) return false;
      e.preventDefault();
      const orig = videoTracks.find((t) => t.source_id !== "bev_closeup" && !isCameraTrack(t));
      const closeup = videoTracks.find((t) => t.source_id === "bev_closeup");
      const target = activeTrack?.url === closeup?.url ? orig : closeup;
      selectTrack(target, ["当前 Issue 暂无局部 BEV 视频。", "No closeup BEV video available."]);
      return true;
    },
    { enabled: shortcutsActive },
  );
  useShortcut(
    shortcutScope,
    "Shift+c",
    (e) => {
      if (!hasVideo) return false;
      e.preventDefault();
      const cam = videoTracks.find(isCameraTrack);
      selectTrack(cam, ["当前 Issue 暂无 Camera 视频。", "No Camera video available."]);
      return true;
    },
    { enabled: shortcutsActive },
  );
  useShortcut(
    shortcutScope,
    "o",
    (e) => {
      if (!hasVideo) return false;
      e.preventDefault();
      const orig = videoTracks.find((t) => t.source_id !== "bev_closeup" && !isCameraTrack(t));
      selectTrack(orig, ["当前 Issue 暂无原始 BEV 视频。", "No original BEV video available."]);
      return true;
    },
    { enabled: shortcutsActive },
  );
  useShortcut(
    shortcutScope,
    "Space",
    (e) => {
      if (activeKind !== "video") return false;
      e.preventDefault();
      togglePlay();
      return true;
    },
    { enabled: shortcutsActive },
  );
  useShortcut(
    shortcutScope,
    "ArrowLeft",
    (e) => {
      e.preventDefault();
      if (activeKind === "video") jumpVideo(-1);
      else moveFrame(-1);
      return true;
    },
    { enabled: shortcutsActive, allowRepeat: true },
  );
  useShortcut(
    shortcutScope,
    "ArrowRight",
    (e) => {
      e.preventDefault();
      if (activeKind === "video") jumpVideo(1);
      else moveFrame(1);
      return true;
    },
    { enabled: shortcutsActive, allowRepeat: true },
  );
  useShortcut(
    shortcutScope,
    "0",
    (e) => {
      e.preventDefault();
      jumpToT0();
      return true;
    },
    { enabled: shortcutsActive },
  );
  useShortcut(
    shortcutScope,
    "g",
    (e) => {
      if (activeKind !== "video" || !issueId) return false;
      e.preventDefault();
      setPlanningOpen((prev) => !prev);
      return true;
    },
    { enabled: shortcutsActive },
  );
  useShortcut(
    "page",
    "f",
    (e) => {
      if (hideExpand || expanded) return false;
      e.preventDefault();
      setExpanded(true);
      return true;
    },
    { enabled: shortcutsActive && !hideExpand },
  );

  const activeFrames = activeKind === "camera" ? cameraFrames : bevFrames;
  const activeFrameIdx = Math.max(
    0,
    Math.min(activeKind === "camera" ? cameraIndex : bevIndex, Math.max(activeFrames.length - 1, 0)),
  );
  const currentFrame = activeFrames[activeFrameIdx];

  const renderStageBody = (inModal: boolean) => {
    if (error) {
      return (
        <div className="empty-state ra-media-empty">
          <h3>{bilingual(lang, "媒体加载失败", "Failed to load media")}</h3>
          <p>{error}</p>
          {onRetryMedia && (
            <button type="button" className="button button-secondary" onClick={onRetryMedia}>
              {bilingual(lang, "重试加载", "Retry")}
            </button>
          )}
        </div>
      );
    }

    if (loading && !hasBev && !hasCamera && !hasVideo) {
      return (
        <div className="no-asset hero-media-placeholder detail-media-pending">
          <span>{bilingual(lang, "正在加载 BEV、Camera 与视频…", "Loading BEV, camera, and video…")}</span>
        </div>
      );
    }

    if (!hasBev && !hasCamera && !hasVideo) {
      return (
        <div className="no-asset hero-media-placeholder">
          <span>{bilingual(lang, "当前 Case 暂无可用媒体资源。", "No media assets available for this case.")}</span>
        </div>
      );
    }

    if (activeKind === "video" && activeTrack) {
      const constraintId = activePlanningFrame?.status === "ready" ? String(activePlanningFrame.constraint_id || "") : "";
      const planningMessage = (() => {
        if (constraintId) return "";
        if (!activePlanningData || ["loading", "busy", "pending"].includes(activePlanningData.status || "")) {
          return bilingual(lang, "正在读取当前时段规划数据…", "Loading planning data for this time window…");
        }
        if (activePlanningData.status === "error") {
          return bilingual(lang, "规划数据读取失败，请重试", "Could not load planning data. Retry.");
        }
        if (activePlanningData.status === "unavailable") {
          return bilingual(lang, "暂无可用规划数据", "Planning data unavailable");
        }
        if (activePlanningFrame?.status === "no_constraint") {
          return bilingual(lang, "当前规划帧无主导约束", "No dominant constraint in this frame");
        }
        return bilingual(lang, "当前时刻无匹配规划帧", "No matching planning frame at this time");
      })();

      return (
        <div className={`hero-video-player${compact && !inModal ? " is-compact" : ""}`}>
          <div className="hero-media-button hero-media-video ra-media-video-wrap">
            <video
              key={`${activeTrack.url}:${videoRetryNonce}`}
              ref={videoRef}
              src={playbackUrl}
              poster={activeTrack.poster_url || undefined}
              preload="auto"
              muted
              playsInline
              draggable={false}
              aria-label={bilingual(lang, "复核视频", "Review video")}
              onLoadedMetadata={(e) => {
                const el = e.currentTarget;
                const dur = Number.isFinite(el.duration) ? el.duration : configuredDuration;
                setVideoDuration(dur);
                if (dur > 0 && Math.abs(el.currentTime) < 0.05) {
                  el.currentTime = dur / 2;
                  setVideoTime(dur / 2);
                } else {
                  setVideoTime(el.currentTime);
                }
                el.playbackRate = rate;
                setVideoStatus("");
              }}
              onTimeUpdate={(e) => setVideoTime(e.currentTarget.currentTime)}
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
              onEnded={() => setPlaying(false)}
              onError={() =>
                setVideoStatus(bilingual(lang, "视频解码失败，请重试。", "Video failed to load. Retry."))
              }
            />
          </div>

          <div className="bev-video-controls" aria-label={bilingual(lang, "视频控制", "Video controls")}>
            <div className="bev-video-control-row">
              {issueId && (
                <button
                  type="button"
                  className={`button button-quiet${planningOpen ? " is-active" : ""}`}
                  aria-expanded={planningOpen}
                  onClick={() => setPlanningOpen((prev) => !prev)}
                  title={bilingual(lang, "展开或收起规划约束 (G)", "Toggle planning constraints (G)")}
                >
                  <span>{bilingual(lang, "规划约束", "Planning")}</span>
                  <kbd className="review-control-shortcut" aria-hidden="true">G</kbd>
                </button>
              )}
              <button type="button" className="button button-quiet" onClick={togglePlay}>
                {playing ? bilingual(lang, "暂停", "Pause") : bilingual(lang, "播放", "Play")}
              </button>
              <button type="button" className="button button-quiet" onClick={() => jumpVideo(-1)}>
                −{stepSec}s
              </button>
              <button type="button" className="button button-quiet" onClick={jumpToT0}>
                {bilingual(lang, "回到 t0", "Back to t0")}
              </button>
              <button type="button" className="button button-quiet" onClick={() => jumpVideo(1)}>
                +{stepSec}s
              </button>
              <div className="ra-video-select-inline">
                <span>{bilingual(lang, "步长", "Step")}</span>
                <UiSelect
                  value={String(stepSec)}
                  options={stepOptions}
                  compact
                  ariaLabel={bilingual(lang, "跳转步长", "Jump step")}
                  onChange={(v) => setStepSec(Number(v) || 1)}
                />
              </div>
              <div className="ra-video-select-inline">
                <span>{bilingual(lang, "倍速", "Rate")}</span>
                <UiSelect
                  value={String(rate)}
                  options={rateOptions}
                  compact
                  ariaLabel={bilingual(lang, "播放倍速", "Playback rate")}
                  onChange={(v) => setRate(Number(v) || 1)}
                />
              </div>
            </div>

            <div className="bev-video-progress-row">
              <span>{formatSignedSec(startOffsetSec)}</span>
              <input
                type="range"
                min={0}
                max={effectiveDuration || 40}
                step={0.01}
                value={Math.min(videoTime, effectiveDuration || 40)}
                aria-label={bilingual(lang, "视频进度", "Video progress")}
                onChange={(e) => seekVideoTo(Number(e.target.value))}
              />
              <span>
                {formatSignedSec(videoTime + startOffsetSec)} / {formatSignedSec(startOffsetSec + effectiveDuration)}
              </span>
            </div>

            {videoStatus && (
              <div className="bev-video-load-state" role="status">
                <span>{videoStatus}</span>
                <button
                  type="button"
                  className="button button-quiet"
                  onClick={() => {
                    setVideoStatus("");
                    setVideoRetryNonce((n) => n + 1);
                  }}
                >
                  {bilingual(lang, "重试视频", "Retry video")}
                </button>
              </div>
            )}

            {planningOpen && (
              <div className="ra-planning-inline-panel" role="region" aria-label={bilingual(lang, "规划约束", "Planning constraint")}>
                <div className="ra-planning-inline-head">
                  <strong>{bilingual(lang, "当前主导约束", "Current dominant constraint")}</strong>
                  <div className="ra-planning-inline-actions">
                    {constraintId && (
                      <button type="button" className="button button-quiet" onClick={() => void copyConstraintId()}>
                        {planningCopied ? bilingual(lang, "已复制", "Copied") : bilingual(lang, "复制 ID", "Copy ID")}
                      </button>
                    )}
                    {activePlanningData?.status === "error" && (
                      <button
                        type="button"
                        className="button button-quiet"
                        onClick={() =>
                          setPlanningCache((prev) => {
                            const next = { ...prev };
                            delete next[planningBucket];
                            return next;
                          })
                        }
                      >
                        {bilingual(lang, "重试", "Retry")}
                      </button>
                    )}
                    <button
                      type="button"
                      className="button button-quiet"
                      onClick={() => setPlanningOpen(false)}
                      aria-label={bilingual(lang, "关闭规划约束", "Close planning constraint")}
                    >
                      ×
                    </button>
                  </div>
                </div>
                <div className={`ra-planning-inline-val${constraintId ? " is-raw-id" : ""}`}>
                  {constraintId || planningMessage}
                </div>
                {constraintId && (
                  <div className="ra-planning-inline-meta">
                    <span>
                      {bilingual(lang, "对象 ID", "Object ID")}:{" "}
                      <strong>
                        {Number.isSafeInteger(activePlanningFrame?.object_id)
                          ? String(activePlanningFrame?.object_id)
                          : bilingual(lang, "未提供", "Not provided")}
                      </strong>
                    </span>
                  </div>
                )}
                {activePlanningFrame?.raw && (
                  <details className="planning-constraint-raw">
                    <summary>{bilingual(lang, "原文", "Raw text")}</summary>
                    <pre>{activePlanningFrame.raw}</pre>
                  </details>
                )}
              </div>
            )}
          </div>
        </div>
      );
    }

    // Image frames mode (BEV or Camera)
    return (
      <div className="ra-media-image-stage">
        {inModal && (
          <div className="ra-media-zoom-bar">
            <button
              type="button"
              className="button button-quiet"
              onClick={() => setZoom((z) => Math.max(0.5, Math.round((z - 0.25) * 100) / 100))}
            >
              −
            </button>
            <span>{Math.round(zoom * 100)}%</span>
            <button
              type="button"
              className="button button-quiet"
              onClick={() => setZoom((z) => Math.min(3, Math.round((z + 0.25) * 100) / 100))}
            >
              +
            </button>
            <button type="button" className="button button-quiet" onClick={() => setZoom(1)}>
              {bilingual(lang, "重置", "Reset")}
            </button>
          </div>
        )}
        <button
          type="button"
          className="hero-media-button"
          onClick={() => {
            if (!inModal && !hideExpand) setExpanded(true);
          }}
          aria-label={bilingual(
            lang,
            `展开 ${activeKind === "camera" ? "Camera" : "BEV"} 媒体预览`,
            `Expand ${activeKind === "camera" ? "Camera" : "BEV"} preview`,
          )}
        >
          {currentFrame?.url && (
            <img
              className="detail-media-image"
              src={currentFrame.url}
              alt={`${activeKind === "camera" ? "Camera" : "BEV"} ${formatFrameLabel(currentFrame, activeFrameIdx)}`}
              style={inModal && zoom !== 1 ? { transform: `scale(${zoom})`, transformOrigin: "center" } : undefined}
              draggable={false}
            />
          )}
          <span className="hero-media-overlay">
            {formatFrameLabel(currentFrame, activeFrameIdx)}
            {!inModal && !hideExpand ? ` · ${bilingual(lang, "点击展开", "Click to expand")}` : ""}
          </span>
        </button>

        <div className="detail-media-frame-controls" aria-label={bilingual(lang, "图片帧切换", "Frame navigation")}>
          <button type="button" className="button button-quiet" onClick={() => moveFrame(-1)}>
            {bilingual(lang, "上一帧", "Prev frame")}
          </button>
          <div className="detail-media-frame-center">
            <span className="detail-media-position">
              {activeFrames.length ? `${activeFrameIdx + 1} / ${activeFrames.length}` : "—"}
            </span>
            <div className="detail-media-timeline media-timeline">
              {activeFrames.map((frame, idx) => (
                <button
                  key={`${frame.url}-${idx}`}
                  type="button"
                  className={`timeline-dot${idx === activeFrameIdx ? " active" : ""}`}
                  onClick={() => (activeKind === "camera" ? setCameraIndex(idx) : setBevIndex(idx))}
                >
                  {formatFrameLabel(frame, idx)}
                </button>
              ))}
            </div>
          </div>
          <button type="button" className="button button-quiet" onClick={() => moveFrame(1)}>
            {bilingual(lang, "下一帧", "Next frame")}
          </button>
        </div>
      </div>
    );
  };

  return (
    <div className="ra-media-stage-shell">
      <div className="detail-media-command ra-media-command-bar" aria-label={bilingual(lang, "媒体控制", "Media controls")}>
        <div className="ra-media-kind-select">
          <UiSelect
            value={sourceKey}
            options={sourceOptions}
            disabled={!hasBev && !hasCamera && !hasVideo}
            ariaLabel={bilingual(lang, "媒体类型", "Media source")}
            onChange={(val) => setSourceKey(val)}
          />
        </div>
        {!hideExpand && (
          <button
            type="button"
            className="button button-quiet detail-media-expand"
            disabled={!hasBev && !hasCamera && !hasVideo}
            onClick={() => setExpanded(true)}
          >
            {bilingual(lang, "展开查看", "Expand")}
          </button>
        )}
      </div>

      <section
        className="hero-media detail-hero-media"
        data-detail-media-kind={activeKind}
        aria-label={bilingual(lang, "Issue 媒体", "Issue media")}
      >
        <div className="detail-media-content">{renderStageBody(false)}</div>
        <p className="detail-media-help">
          {activeKind === "video"
            ? bilingual(
                lang,
                "B / C / V 切换媒体 · Shift+V 切换原始/局部 BEV · Shift+C Camera 视频 · G 规划约束 · 空格播放/暂停 · ←/→ 跳转 · 0 回到 t0 · F 展开",
                "B/C/V switch media · Shift+V original/closeup BEV · Shift+C Camera video · G planning · Space play · ←/→ step · 0 t0 · F expand",
              )
            : bilingual(
                lang,
                "B / C / V 切换媒体 · ←/→ 切换帧 · 0 回到 t0 · 点击图片或按 F 展开大图",
                "B/C/V switch media · ←/→ switch frames · 0 jump to t0 · Click or F to expand",
              )}
        </p>
      </section>

      {!hideExpand && (
        <ModalDialog
          open={expanded}
          wide
          lang={lang}
          title={`${issueId} · ${bilingual(lang, "媒体预览", "Media preview")}`}
          onClose={() => {
            setExpanded(false);
            setZoom(1);
          }}
        >
          <div className="ra-media-modal-toolbar">
            <UiSelect
              value={sourceKey}
              options={sourceOptions}
              ariaLabel={bilingual(lang, "媒体类型", "Media source")}
              onChange={(val) => setSourceKey(val)}
            />
          </div>
          {renderStageBody(true)}
        </ModalDialog>
      )}
    </div>
  );
};

export interface CaseMediaPreviewModalProps {
  issueId: string | null;
  lang: UiLanguage;
  onClose: () => void;
}

export const CaseMediaPreviewModal: React.FC<CaseMediaPreviewModalProps> = ({
  issueId,
  lang,
  onClose,
}) => {
  const mediaQuery = useQuery<CaseMediaPayload>({
    queryKey: ["case-media-preview", issueId],
    queryFn: ({ signal }) =>
      apiRequest<CaseMediaPayload>(`/api/cases/${encodeURIComponent(issueId || "")}/media`, { signal }),
    enabled: Boolean(issueId),
    staleTime: 60_000,
  });

  return (
    <ModalDialog
      open={Boolean(issueId)}
      wide
      lang={lang}
      title={issueId ? `${issueId} · ${bilingual(lang, "媒体预览", "Media preview")}` : ""}
      onClose={onClose}
    >
      {issueId && (
        <MediaStage
          issueId={issueId}
          media={mediaQuery.data || null}
          loading={mediaQuery.isPending}
          error={mediaQuery.isError ? String((mediaQuery.error as Error)?.message || "Error") : null}
          lang={lang}
          active={Boolean(issueId)}
          hideExpand
          onRetryMedia={() => void mediaQuery.refetch()}
        />
      )}
    </ModalDialog>
  );
};
