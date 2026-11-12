/* bev-video.js
 * Shared BEV video rendering, playback intent, source switching and disposal.
 * Classic script; shared globals are initialized before bind-bootstrap.js.
 */

function videoT0PlayerPosition(configuredDuration, decodedDuration = 0) {
  const configured = Number(configuredDuration);
  const decoded = Number(decodedDuration);
  const total = configured > 0 && Number.isFinite(configured)
    ? configured
    : decoded > 0 && Number.isFinite(decoded)
      ? decoded
      : 0;
  return total / 2;
}

function videoCanonicalAssetUrl(url) {
  const source = safeSameOriginAssetUrl(url);
  if (!source) return "";
  const parsed = new URL(source, "http://localhost");
  if (parsed.searchParams.get("playback") === "short-gop-v1") parsed.searchParams.delete("playback");
  return parsed.pathname + parsed.search;
}

function videoElementAssetUrl(video) {
  // MediaSource uses a blob URL; source identity remains the scoped asset URL.
  return video?.dataset?.videoSource || video?.getAttribute("src") || "";
}

function videoPlaybackSourceUrl(url, startSec = null) {
  const canonical = videoCanonicalAssetUrl(url);
  const source = canonical ? `${canonical}${canonical.includes("?") ? "&" : "?"}playback=short-gop-v1` : "";
  const position = Number(startSec);
  // A start-only media fragment lets the native loader request the nearest
  // keyframe before our metadata handler runs. It never limits the clip end.
  return source && startSec !== null && Number.isFinite(position) && position >= 0
    ? `${source}#t=${Math.round(position * 1000) / 1000}` : source;
}

function videoTrackLabel(label) {
  if (label === "BEV 视频") return uiText("BEV 视频", "BEV video");
  if (label === "局部 BEV 视频") return uiText("局部 BEV 视频", "Closeup BEV video");
  if (label === "Camera102 视频") return uiText("Camera102 视频", "Camera102 video");
  return label;
}

function videoSourceTracks(descriptor) {
  const seen = new Set();
  return [descriptor, ...(descriptor?.tracks || [])].filter(track => {
    if (!track || !safeSameOriginAssetUrl(track.url) || seen.has(track.url)) return false;
    seen.add(track.url);
    return true;
  });
}

function isCameraVideoTrack(track) {
  return track?.label === "Camera102 视频" || /\/camera-video(?:[?#]|$)/.test(String(track?.url || ""));
}

let mediaShortcutActivating = false;

function activateMediaShortcutControl(control, event) {
  if (!control || control.disabled) return false;
  event.preventDefault();
  const previous = mediaShortcutActivating;
  mediaShortcutActivating = true;
  try { control.click(); }
  finally { mediaShortcutActivating = previous; }
  return true;
}

function handleDetailMediaShortcut(event) {
  if (event.defaultPrevented || isImeComposing(event)
      || event.ctrlKey || event.metaKey || event.altKey
      || mediaShortcutHasEditableTarget(event.target)
      || document.querySelector("dialog[open]")) return false;
  const active = (state.activePage === "review" && state.selectedCase)
    || (state.activePage === "labeling" && state.caseLabeling?.issueId);
  const hero = detailHeroMediaEl();
  if (!active || !hero) return false;
  const pane = detailMediaPane(), prefix = detailMediaPrefix();
  const key = String(event.key || "").toLowerCase();
  if (["b", "c"].includes(key)) {
    const kind = { b: "bev", c: "camera" }[key];
    const select = pane?.querySelector(`#${prefix}MediaKindSelect`);
    const option = select?.querySelector(`option[value="${kind}"]`);
    if (!select || !option || option.disabled || select.value === kind) return false;
    event.preventDefault();
    select.value = kind;
    select.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }
  if (key === " " && state.detailMedia.kind === "video") {
    event.preventDefault();
    if (!event.repeat) activateMediaShortcutControl(hero.querySelector("[data-video-play]"), event);
    return true;
  }
  if (key === "arrowleft" || key === "arrowright") {
    const direction = key === "arrowleft" ? -1 : 1;
    const control = state.detailMedia.kind === "video"
      ? hero.querySelector(`[data-video-jump="${direction}"]`)
      : pane?.querySelector(direction < 0 ? `#${prefix}MediaPreviousButton` : `#${prefix}MediaNextButton`);
    return activateMediaShortcutControl(control, event);
  }
  if (key === "f") {
    return !event.repeat && activateMediaShortcutControl(pane?.querySelector(`#${prefix}MediaExpandButton`), event);
  }
  if (key === "0" && !event.shiftKey) {
    // The visible 0 binding owns the key while its tag group is open.
    if (openReviewDropdownShortcutInput("0")) return false;
    if (state.detailMedia.kind === "video") {
      return activateMediaShortcutControl(hero.querySelector("[data-video-t0]"), event);
    }
    const caseData = state.activePage === "labeling" ? state.caseLabeling?.caseData : state.selectedCase;
    const frames = state.detailMedia.kind === "camera" ? caseData?.camera?.frames || [] : caseData?.assets?.frames || [];
    const t0Index = heroFrameIndex(frames);
    return t0Index >= 0 && activateMediaShortcutControl(hero.querySelector(`[data-detail-media-frame="${t0Index}"]`), event);
  }
  return false;
}

function handleVideoSourceShortcut(event) {
  const key = String(event.key || "").toLowerCase();
  const cameraShortcut = key === "c" && event.shiftKey;
  if (key !== "v" && (key !== "o" || event.shiftKey) && !cameraShortcut) return false;
  if (event.defaultPrevented || event.repeat || isImeComposing(event)
      || event.ctrlKey || event.metaKey || event.altKey
      || mediaShortcutHasEditableTarget(event.target)) return true;
  const dialog = $("#mediaDialog");
  const inDialog = Boolean(dialog?.open);
  if (document.querySelector("dialog[open]:not(#mediaDialog)")) return true;
  if (inDialog && state.media.snapshot?.intentPreview) return true;
  const caseData = state.activePage === "labeling" ? state.caseLabeling?.caseData : state.selectedCase;
  const pane = typeof detailMediaPane === "function" ? detailMediaPane() : $("#detailPane");
  if (!inDialog && (!["review", "labeling"].includes(state.activePage) || !caseData
      || !pane?.querySelector(".detail-hero-media"))) return true;
  event.preventDefault();
  const descriptor = inDialog ? mediaVideo() : videoWithFramePosters(caseData);
  const stage = inDialog ? $("#mediaVideoStage") : pane;
  const video = stage?.querySelector("video");
  // Native start hints (#t=...) describe playback position, not source identity.
  const currentUrl = videoCanonicalAssetUrl(videoElementAssetUrl(video)
    || (inDialog ? state.media.snapshot?.videoTrack : state.detailMedia.videoTrack)
    || descriptor?.url);
  const rememberedUrl = inDialog ? state.media.snapshot?.videoTrack
    : state.detailMedia.preferredVideoTrack || state.detailMedia.videoTrack;
  const tracks = videoSourceTracks(descriptor);
  const owner = inDialog ? state.media.snapshot : state.detailMedia;
  const bevTracks = tracks.filter(track => !isCameraVideoTrack(track));
  const activeBev = bevTracks.find(track => track.url === currentUrl);
  // Camera has its own shortcut. Preserve the BEV choice before leaving it,
  // including the default source that has not emitted a picker change yet.
  if (cameraShortcut && activeBev && owner) owner.preferredBevVideoTrack = activeBev.url;
  const rememberedBev = bevTracks.find(track => track.url === owner?.preferredBevVideoTrack)
    || bevTracks.find(track => track.url === rememberedUrl);
  const camera = tracks.find(isCameraVideoTrack);
  const original = tracks.find(track => track.source_id !== "bev_closeup"
    && !isCameraVideoTrack(track));
  const closeup = tracks.find(track => track.source_id === "bev_closeup");
  const toggle = key === "v" && event.shiftKey;
  const track = cameraShortcut ? camera : key === "o" ? original
    : toggle ? (currentUrl === closeup?.url ? original : closeup)
    : rememberedBev || activeBev || original || closeup;
  if (!track) {
    showToast(cameraShortcut
      ? uiText("当前 Issue 暂无 Camera 视频。", "No Camera video is available for this Issue.")
      : key === "o" || (toggle && currentUrl === closeup?.url)
      ? uiText("当前 Issue 暂无原始 BEV 视频。", "No original BEV video is available for this Issue.")
      : toggle
        ? uiText("当前 Issue 暂无局部 BEV 视频。", "No closeup BEV video is available for this Issue.")
        : uiText("当前 Issue 暂无 BEV 视频。", "No BEV video is available for this Issue."), true);
    return true;
  }
  if (inDialog) {
    if (state.media.kind !== "video") switchMediaKind("video");
    const activeVideo = stage?.querySelector("video");
    if (videoCanonicalAssetUrl(videoElementAssetUrl(activeVideo)) === track.url) return true;
    const select = stage?.querySelector("[data-video-track]");
    if (select && Array.from(select.options).some(option => option.value === track.url && !option.disabled)) {
      select.value = track.url;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      enhanceNativeUiSelect(select);
    } else {
      activeVideo?._setBevVideoTrack?.(track.url, track.poster_url || "");
      rememberMediaVideoSource(track.url);
      stage.dataset.videoUrl = track.url;
    }
  } else {
    if (state.detailMedia.kind === "video" && currentUrl === track.url) return true;
    const prefix = detailMediaPrefix();
    const select = pane.querySelector(`#${prefix}MediaKindSelect`);
    const value = track.url === descriptor.url ? "video" : `track:${track.url}`;
    if (!select || !Array.from(select.options).some(option => option.value === value && !option.disabled)) return true;
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
    populateUiSelect(pane.querySelector(`#${prefix}MediaKindPicker`), detailMediaKindOptions(caseData, ensureDetailMediaState(caseData)), detailMediaSelectedKind(caseData));
  }
  return true;
}

function videoWithFramePosters(caseData) {
  const video = caseData?.assets?.video;
  if (!video?.url) return null;
  const withPoster = (track) => {
    if (track.source_id === "bev_closeup") {
      return { ...track, poster_url: safeSameOriginAssetUrl(track.poster_url || "") };
    }
    const frames = String(track.url || "").endsWith("/camera-video")
      ? caseData?.camera?.frames || [] : caseData?.assets?.frames || [];
    const poster = safeSameOriginAssetUrl(frames[heroFrameIndex(frames)]?.url || track.poster_url || "");
    return { ...track, poster_url: poster };
  };
  // Keep the September native-video behavior: full-resolution posters only,
  // no positioning overlay or visibility gate, and no extra image lookup.
  return { ...withPoster(video), tracks: (video.tracks || []).map(withPoster) };
}

function refreshVideoFramePosters(root, caseData) {
  const descriptor = videoWithFramePosters(caseData);
  if (!descriptor) return;
  const tracks = [descriptor, ...descriptor.tracks];
  root?.querySelectorAll("[data-bev-video-player]").forEach(player => {
    const video = player.querySelector("video");
    const track = tracks.find(item => item.url === videoCanonicalAssetUrl(videoElementAssetUrl(video)));
    // Updating a native poster never reloads the source or seeks the player.
    if (track?.poster_url) video.setAttribute("poster", track.poster_url);
    player.querySelectorAll("[data-video-track] option").forEach(option => {
      option.dataset.poster = tracks.find(item => item.url === option.value)?.poster_url || "";
    });
  });
}

function refreshBevVideoLanguage(root = document) {
  root.querySelectorAll("[data-bev-video-player] video").forEach(video => video._refreshBevPlayerLanguage?.());
  enhanceDashboardSelects(root);
}

function videoPlayerMarkup(video, { zoomable = true, compact = false, issueId = "" } = {}) {
  const durationSec = Math.max(0, Number(video?.duration_ms || 0) / 1000);
  const t0PlayerSec = videoT0PlayerPosition(durationSec);
  // Review video t0 is always the clip midpoint. Some captures have stale or
  // missing start_offset_sec metadata; using it makes a 40s clip read 0..40s
  // even though player position 20s is t0.
  const startOffsetSec = t0PlayerSec > 0 ? -t0PlayerSec : Number(video?.start_offset_sec ?? 0);
  const frameStepSec = Math.max(0.01, Number(video?.frame_step_ms || 100) / 1000);
  const stepOptions = [...new Set([frameStepSec, 0.5, 1, 5])]
    .sort((left, right) => left - right)
    .map((step) => `<option value="${escapeHtml(step)}" ${step === 1 ? "selected" : ""}>${escapeHtml(step)}s${step === frameStepSec ? escapeHtml(t("media.frame_step")) : ""}</option>`)
    .join("");
  const tracks = (video?.tracks || []).filter((track) => safeSameOriginAssetUrl(track.url));
  const trackControl = tracks.length > 1 && !compact
    ? `<label><span class="ui-lang-zh">视频源</span><span class="ui-lang-en">Video source</span> <select data-video-track aria-keyshortcuts="V Shift+V Shift+C O" title="${escapeHtml(t("media.video_source_shortcuts"))}">${tracks.map((track) => `<option value="${escapeHtml(track.url)}" ${track.url === video.url ? "selected" : ""} data-video-source-id="${escapeHtml(track.source_id || "")}" data-poster="${escapeHtml(track.poster_url || "")}" data-video-track-label="${escapeHtml(track.label || "")}">${escapeHtml(videoTrackLabel(track.label))}</option>`).join("")}</select></label>`
    : "";
  const posterUrl = String(video?.poster_url || "").trim();
  const posterAttribute = posterUrl ? ` poster="${escapeHtml(posterUrl)}"` : "";
  const sourceUrl = videoPlaybackSourceUrl(video.url, durationSec > 0 ? t0PlayerSec : null);
  const segmented = typeof videoSegmentManifestUrl === "function" && videoSegmentManifestUrl(sourceUrl);
  const videoMarkup = `<video data-video-source="${escapeHtml(sourceUrl)}"${segmented ? "" : ` src="${escapeHtml(sourceUrl)}"`}${posterAttribute} preload="metadata" muted playsinline draggable="false" aria-label="${escapeHtml(uiText("复核视频", "Review video"))}"></video>`;
  const mediaMarkup = zoomable
    ? `<div class="media-viewport media-video-viewport" data-video-viewport><div class="media-canvas media-video-canvas" data-video-canvas>${videoMarkup}</div></div>`
    : `<div class="hero-media-button hero-media-video">${videoMarkup}</div>`;
  return `<div class="hero-video-player ${compact ? "is-compact" : ""}" data-bev-video-player
      data-planning-issue="${escapeHtml(issueId)}"
      data-start-offset-sec="${escapeHtml(startOffsetSec)}"
      data-t0-player-sec="${escapeHtml(t0PlayerSec)}"
      data-duration-sec="${escapeHtml(durationSec)}"
      data-frame-step-sec="${escapeHtml(frameStepSec)}">
    ${mediaMarkup}
    <div class="bev-video-controls" aria-label="${escapeHtml(uiText("视频控制", "Video controls"))}">
      <div class="bev-video-control-row">
        ${issueId ? `<button class="button button-quiet" type="button" data-planning-constraint aria-haspopup="dialog" aria-expanded="false" aria-keyshortcuts="G"><span data-pc-trigger-label>${escapeHtml(uiText("规划约束", "Planning constraint"))}</span> <kbd class="review-control-shortcut detail-external-shortcut" aria-hidden="true">G</kbd></button>` : ""}
        ${trackControl}
        <button class="button button-quiet" type="button" data-video-play>${escapeHtml(t("media.play"))}</button>
        <button class="button button-quiet" type="button" data-video-jump="-1"><span data-video-jump-label>−1s</span></button>
        <button class="button button-quiet" type="button" data-video-t0 data-i18n="media.back_t0">${escapeHtml(t("media.back_t0"))}</button>
        <button class="button button-quiet" type="button" data-video-jump="1"><span data-video-jump-label>+1s</span></button>
        <label><span data-i18n="media.step">${escapeHtml(t("media.step"))}</span>
          <select data-video-step>
            ${stepOptions}
          </select>
        </label>
        <label><span data-i18n="media.rate">${escapeHtml(t("media.rate"))}</span>
          <select data-video-rate>
            <option value="0.5">0.5×</option>
            <option value="1" selected>1×</option>
            <option value="1.5">1.5×</option>
            <option value="2">2×</option>
          </select>
        </label>
      </div>
      <div class="bev-video-progress-row">
        <span data-video-relative-start>${escapeHtml(formatSignedSeconds(startOffsetSec))}</span>
        <input data-video-seek type="range" min="0" max="${escapeHtml(durationSec || 40)}" value="0" step="0.01" aria-label="${escapeHtml(uiText("视频进度", "Video progress"))}" />
        <span data-video-time>${escapeHtml(formatSignedSeconds(startOffsetSec))} / ${escapeHtml(formatSignedSeconds(startOffsetSec + durationSec))}</span>
      </div>
      <div class="bev-video-load-state" data-video-status role="status" aria-live="polite" hidden>
        <span data-video-status-text></span><button class="button button-quiet" type="button" data-video-retry hidden>${escapeHtml(uiText("重试视频", "Retry video"))}</button>
      </div>
    </div>
  </div>`;
}

function formatSignedSeconds(value) {
  const seconds = Number(value || 0);
  if (Math.abs(seconds) < 0.05) return "t0";
  return `${seconds > 0 ? "+" : ""}${seconds.toFixed(1)}s`;
}

function bindBevVideoPlayers(root) {
  enhanceDashboardSelects(root);
  root.querySelectorAll("[data-bev-video-player]").forEach((player) => {
    if (player.dataset.videoBound === "1") return;
    player.dataset.videoBound = "1";
    const video = player.querySelector("video");
    const playButton = player.querySelector("[data-video-play]");
    const seek = player.querySelector("[data-video-seek]");
    const stepSelect = player.querySelector("[data-video-step]");
    const rateSelect = player.querySelector("[data-video-rate]");
    const timeLabel = player.querySelector("[data-video-time]");
    const startLabel = player.querySelector("[data-video-relative-start]");
    const startOffsetSec = Number(player.dataset.startOffsetSec || 0);
    const configuredT0PlayerSec = Number(player.dataset.t0PlayerSec || 0);
    const configuredDuration = Number(player.dataset.durationSec || 0);
    const configuredFrameStep = Number(player.dataset.frameStepSec);
    const frameStepSec = Number.isFinite(configuredFrameStep) && configuredFrameStep > 0 ? configuredFrameStep : 0.1;
    let disposed = false;
    let segmentLoader = null;
    let sourceGeneration = 0;
    let pendingStart = configuredT0PlayerSec > 0 ? configuredT0PlayerSec : null;
    let pendingBackwardSeek = null;
    // Each new Case/player waits for its own explicit Play choice at t0.
    let wantsPlayback = false;
    let suspended = false;
    let metadataGeneration = -1;
    let sourceHasStartHint = configuredT0PlayerSec > 0;
    let playbackAttempt = 0;
    let playPending = false;
    let playing = false;
    let hasPlayed = false;
    let rebufferTarget = null;
    let loadTimer = null;
    let heldFrame = null;
    let heldTarget = null;
    let frameCallback = null;
    let confirmedFrame = null;
    const cancelFrameCheck = () => {
      if (frameCallback !== null) video.cancelVideoFrameCallback?.(frameCallback);
      frameCallback = null;
      confirmedFrame = null;
    };
    const holdFrame = (target) => {
      heldTarget = target;
      if (heldFrame) return;
      // Keep the last decoded frame while native load()/seek replaces its
      // surface. Before the first decode, a neutral cover prevents the new
      // source's t0 poster/frame0 from impersonating a different requested time.
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth || 1;
      canvas.height = video.videoHeight || 1;
      if (video.readyState >= 2 && !video.seeking) {
        try { canvas.getContext("2d").drawImage(video, 0, 0); } catch { /* Keep the neutral cover. */ }
      }
      canvas.className = "video-source-frame";
      canvas.setAttribute("aria-hidden", "true");
      video.after(canvas);
      heldFrame = canvas;
    };
    const frameMatchesTarget = (mediaTime) => {
      if (!Number.isFinite(mediaTime) || !Number.isFinite(heldTarget)) return false;
      const frameIndex = time => Math.floor((time + 0.000001) / frameStepSec);
      // currentTime may equal duration, although its last frame starts earlier.
      const total = Number.isFinite(video.duration) ? video.duration : configuredDuration;
      const target = total > 0 ? Math.min(heldTarget, Math.max(0, total - 0.00001)) : heldTarget;
      return frameIndex(mediaTime) >= frameIndex(target)
        && frameIndex(mediaTime) <= frameIndex(video.currentTime);
    };
    const releaseHeldFrame = () => {
      if (!heldFrame || metadataGeneration !== sourceGeneration) return;
      if (typeof video.requestVideoFrameCallback === "function" && !frameMatchesTarget(confirmedFrame)) {
        watchPresentedFrame();
        return;
      }
      const canvas = heldFrame, generation = sourceGeneration, request = seekRequest, target = heldTarget;
      const commit = () => {
        if (disposed || generation !== sourceGeneration || request !== seekRequest || canvas !== heldFrame
            || video.seeking || video.readyState < 2 || video.error
            || video.currentTime < target - frameStepSec
            || (typeof video.requestVideoFrameCallback === "function" && !frameMatchesTarget(confirmedFrame))) return;
        canvas.remove();
        heldFrame = null;
        heldTarget = null;
        cancelFrameCheck();
      };
      // Media events/currentTime do not prove which frame was submitted.
      // After that proof, allow the compositor to adopt the confirmed frame.
      window.requestAnimationFrame(() => window.requestAnimationFrame(commit));
    };
    const watchPresentedFrame = () => {
      if (disposed || !heldFrame || frameCallback !== null || typeof video.requestVideoFrameCallback !== "function") return;
      const generation = sourceGeneration, request = seekRequest;
      frameCallback = video.requestVideoFrameCallback((_now, metadata) => {
        if (disposed || generation !== sourceGeneration || request !== seekRequest) return;
        frameCallback = null;
        // A paused decoder can submit its only target frame while seeking /
        // readyState still lag behind. Retain that proof for the later ready
        // event; waiting for a second frame would leave a paused cover stuck.
        if (metadataGeneration === sourceGeneration && frameMatchesTarget(metadata.mediaTime)) {
          confirmedFrame = metadata.mediaTime;
          releaseHeldFrame();
        } else watchPresentedFrame();
      });
    };
    const listeners = [];
    const listen = (target, name, handler) => {
      target.addEventListener(name, handler);
      listeners.push(() => target.removeEventListener(name, handler));
    };
    const status = player.querySelector("[data-video-status]");
    const statusText = player.querySelector("[data-video-status-text]");
    const retry = player.querySelector("[data-video-retry]");
    const setStatus = (kind) => {
      if (disposed) return;
      player.dataset.loadState = kind;
      // Native loading/seeking is transient. Showing a full-width status for
      // every seek made the timeline jump between rows (e249d10 regression).
      // Only actionable slow/error states occupy a row, after the timeline.
      if (status) status.hidden = !["slow", "error"].includes(kind);
      if (retry) retry.hidden = !["slow", "error"].includes(kind);
      if (statusText) statusText.textContent = kind === "error"
        ? uiText("视频加载失败", "Video failed to load")
        : kind === "slow" ? uiText("视频加载较慢，可重试或切换图片", "Video is loading slowly; retry or switch to images")
        : "";
    };
    const loading = () => {
      if (disposed || video.error) return;
      setStatus("loading");
      if (loadTimer !== null) window.clearTimeout(loadTimer);
      loadTimer = window.setTimeout(() => setStatus("slow"), 12000);
    };
    const ready = () => {
      if (disposed || video.error || pendingBackwardSeek !== null || video.readyState < 2 || video.seeking) return;
      if (rebufferTarget !== null) {
        startPlayback();
        if (rebufferTarget !== null) return;
      }
      if (loadTimer !== null) window.clearTimeout(loadTimer);
      loadTimer = null;
      setStatus("ready");
      releaseHeldFrame();
      // Buffered seeks can resume without another `playing` event.
      if (hasPlayed && wantsPlayback && !suspended && !video.paused && video.readyState >= 3) {
        playing = true;
        update();
      }
    };
    let seekRequest = 0;
    let cancelPendingSeek = null;
    let queuedSeekTarget = null;
    let queuedSeekTimer = null;
    let queuedSeekGroup = null;
    let playbackFrameCallback = null;
    let firstPlaybackFrame = null, lastPlaybackFrame = null;
    const resetPlaybackFrames = () => {
      if (playbackFrameCallback !== null) video.cancelVideoFrameCallback?.(playbackFrameCallback);
      playbackFrameCallback = null;
      firstPlaybackFrame = lastPlaybackFrame = null;
    };
    const observePlaybackFrames = () => {
      if (disposed || !wantsPlayback || !segmentLoader || playbackFrameCallback !== null
          || typeof video.requestVideoFrameCallback !== "function") return;
      const generation = sourceGeneration, request = seekRequest;
      const callback = video.requestVideoFrameCallback((_now, metadata) => {
        if (disposed || playbackFrameCallback !== callback) return;
        playbackFrameCallback = null;
        if (generation === sourceGeneration && request === seekRequest
            && metadataGeneration === sourceGeneration && wantsPlayback && !heldFrame) {
          firstPlaybackFrame ??= metadata.mediaTime;
          lastPlaybackFrame = metadata.mediaTime;
          if (rebufferTarget !== null) {
            rebufferTarget = metadata.mediaTime;
            update();
          }
        }
        observePlaybackFrames();
      });
      playbackFrameCallback = callback;
    };
    const playbackPosition = () => rebufferTarget ?? pendingBackwardSeek ?? pendingStart
      ?? (Number.isFinite(video.currentTime) ? video.currentTime : 0);
    const timelinePosition = () => queuedSeekTarget ?? playbackPosition();
    const clearQueuedSeek = () => {
      if (queuedSeekTimer !== null) window.clearTimeout(queuedSeekTimer);
      queuedSeekTimer = null;
      queuedSeekTarget = null;
      queuedSeekGroup = null;
    };
    const planningConstraint = bindPlanningConstraint(player, video, timelinePosition);
    const duration = () => Number.isFinite(video.duration) ? video.duration : configuredDuration;
    const bufferedAhead = (time) => {
      const ranges = video.buffered;
      for (let i = 0; i < (ranges?.length || 0); i++) {
        if (ranges.start(i) <= time && time < ranges.end(i)) return ranges.end(i) - time;
      }
      return 0;
    };
    const update = (previewTime = null) => {
      const total = Math.max(0, duration());
      const currentTime = previewTime !== null && Number.isFinite(Number(previewTime))
        ? Number(previewTime)
        : timelinePosition();
      seek.max = String(total || configuredDuration || 40);
      seek.value = String(Math.min(Number(seek.max), Math.max(0, currentTime)));
      startLabel.textContent = formatSignedSeconds(startOffsetSec);
      timeLabel.textContent = `${formatSignedSeconds(startOffsetSec + currentTime)} / ${formatSignedSeconds(startOffsetSec + total)}`;
      const requested = wantsPlayback && !suspended;
      const playbackState = !requested ? "paused"
        : playing && !video.paused && !video.seeking ? "playing"
        : hasPlayed ? "buffering" : "waiting";
      player.dataset.playbackState = playbackState;
      const action = t(requested ? "media.pause" : "media.play");
      if (playButton.textContent !== action) playButton.textContent = action;
      playButton.setAttribute("aria-pressed", String(requested));
    };
    const focusPlayer = () => {
      player.focus({ preventScroll: true });
    };
    const seekTo = (target) => {
      if (disposed) return;
      // A native seek retains this source's last frame until the target is
      // decoded. Copying it to a full-resolution canvas adds a readback and a
      // second scaling/compositing path on every jump. Only an in-flight
      // source replacement needs the held-frame confirmation below.
      if (heldFrame) heldTarget = target;
      clearQueuedSeek();
      const resumePlayback = pendingBackwardSeek !== null || rebufferTarget !== null;
      pendingBackwardSeek = null;
      rebufferTarget = null;
      if (video.readyState < 1) { pendingStart = target; segmentLoader?.prioritize(); update(target); return; }
      if (!heldFrame && target === video.currentTime) {
        if (resumePlayback) {
          segmentLoader?.prioritize();
          ready();
          startPlayback();
        }
        update();
        return;
      }
      const request = ++seekRequest;
      resetPlaybackFrames();
      cancelFrameCheck();
      cancelPendingSeek?.();
      if (!heldFrame && wantsPlayback && target < video.currentTime && !isBuffered(target)
          && segmentLoader?.prepareUnbufferedSeek(target)) {
        // Seeking across a missing range while playing can let the browser
        // advance from the next buffered frame. Fetch the exact target first.
        pendingBackwardSeek = target;
        ++playbackAttempt;
        playPending = false;
        playing = false;
        video.pause();
        segmentLoader.prioritize();
        loading();
        update();
        return;
      }
      let settled = false;
      let fallbackTimer = null;
      const settle = () => {
        if (disposed || settled || request !== seekRequest) return;
        settled = true;
        video.removeEventListener("seeked", settle);
        if (fallbackTimer) window.clearTimeout(fallbackTimer);
        cancelPendingSeek = null;
        update();
        releaseHeldFrame();
        // Some Chromium video decoders update currentTime before the paused
        // frame reaches the compositor. Reconcile the controls on the next
        // paint without accumulating decoded-frame callbacks on paused video.
        if (typeof window.requestAnimationFrame === "function") {
          window.requestAnimationFrame(() => {
            window.requestAnimationFrame(() => {
              if (!disposed && request === seekRequest) update();
            });
          });
        }

      };
      cancelPendingSeek = () => {
        video.removeEventListener("seeked", settle);
        if (fallbackTimer) window.clearTimeout(fallbackTimer);
        cancelPendingSeek = null;
      };
      video.addEventListener("seeked", settle);
      // Setting currentTime preserves the native play/pause state. A jump
      // while playing must continue playback; a paused video stays paused.
      watchPresentedFrame();
      video.currentTime = target;
      segmentLoader?.prioritize();
      update();
      // A remote asset can delay seeked while metadata or the first keyframe
      // is fetched. Keep controls responsive and reconcile once it arrives.
      fallbackTimer = window.setTimeout(settle, 800);
      observePlaybackFrames();
      if (resumePlayback) startPlayback();
    };
    const isBuffered = (time) => bufferedAhead(time) > 0;
    const previewInterval = 50;
    const queueSeek = (target, delay = 75) => {
      if (disposed) return;
      const total = Math.max(0, duration() || Number(seek.max));
      queuedSeekTarget = Math.min(total, Math.max(0, Number(target) || 0));
      update(queuedSeekTarget);
      const buffered = delay > 0 && isBuffered(queuedSeekTarget);
      let group = null;
      if (delay > 0) group = buffered ? "buffered" : segmentLoader?.segmentForTime(queuedSeekTarget);
      // Buffered previews and motion within one unbuffered GOP keep the
      // original deadline. Crossing GOPs still coalesces transient requests.
      if (queuedSeekTimer !== null && group != null && group === queuedSeekGroup) return;
      if (queuedSeekTimer !== null) window.clearTimeout(queuedSeekTimer);
      queuedSeekGroup = group;
      const flush = () => {
        if (disposed || queuedSeekTarget === null) return;
        // Give an in-flight buffered seek a chance to decode before sending
        // another preview. A return from an unbuffered seek may proceed now.
        if (buffered && video.seeking && cancelPendingSeek && isBuffered(video.currentTime)) {
          queuedSeekTimer = window.setTimeout(flush, previewInterval);
          return;
        }
        seekTo(queuedSeekTarget);
      };
      queuedSeekTimer = window.setTimeout(flush, buffered ? previewInterval : delay);
    };
    const jump = (direction) => {
      const step = Math.max(0.01, Number(stepSelect.value || 1));
      const currentTime = timelinePosition();
      const target = Math.min(
        Math.max(0, duration()),
        Math.max(0, currentTime + direction * step)
      );
      // Discrete jumps must not wait for the slider's trailing debounce;
      // repeated arrow keys otherwise postpone every decode until release.
      queueSeek(target, 0);
    };
    const startPlayback = () => {
      if (disposed || suspended || !wantsPlayback || pendingBackwardSeek !== null || playPending
        || !video.paused || !video.getAttribute("src")
        || (metadataGeneration !== sourceGeneration && !sourceHasStartHint)
        || !player.isConnected || player.closest?.('dialog:not([open]), [hidden], .hidden')) return;
      if (rebufferTarget !== null) {
        const target = rebufferTarget;
        const goal = Math.min(Math.max(.5, video.playbackRate), Math.max(0, duration() - target));
        if (queuedSeekTarget !== null || bufferedAhead(target) + .00001 < goal) return;
        rebufferTarget = null;
        // A starving MSE clock can lag behind the frame already on screen.
        video.currentTime = target;
      }
      observePlaybackFrames();
      const generation = sourceGeneration;
      const attempt = ++playbackAttempt;
      if (video.ended && heldFrame) {
        heldTarget = 0; // Native Play at the end restarts the clip.
        cancelFrameCheck();
        watchPresentedFrame();
      }
      playPending = true;
      video.play().then(() => {
        if (disposed || generation !== sourceGeneration || attempt !== playbackAttempt) return;
        playPending = false;
        update();
      }).catch((error) => {
        if (disposed || generation !== sourceGeneration || attempt !== playbackAttempt) return;
        playPending = false;
        if (error.name === "AbortError") return;
        wantsPlayback = false;
        playing = false;
        update();
        showToast(t("media.play_fail", { msg: error.message }), true);
      });
    };
    const togglePlayback = () => {
      if (disposed) return;
      suspended = false;
      if (rebufferTarget !== null) video.currentTime = rebufferTarget;
      rebufferTarget = null;
      resetPlaybackFrames();
      wantsPlayback = !wantsPlayback;
      // A key press changes intent and its feedback synchronously, even before
      // metadata/frames arrive. A second press cancels a queued play request.
      if (!wantsPlayback) {
        ++playbackAttempt;
        playPending = false;
        playing = false;
        video.pause();
      }
      if (queuedSeekTarget !== null) {
        const target = queuedSeekTarget;
        seekTo(target);
      }
      // A dialog can suspend the inline loader independently of the native
      // video's paused state. Explicit Play restores both parts together.
      if (wantsPlayback) segmentLoader?.resume();
      else segmentLoader?.prioritize();
      update();
      startPlayback();
    };
    const seekToT0 = () => {
      const target = configuredT0PlayerSec > 0
        ? configuredT0PlayerSec
        : videoT0PlayerPosition(0, duration());
      queueSeek(Math.min(Math.max(0, duration()), Math.max(0, target)), 0);
    };
    playButton.addEventListener("click", togglePlayback);
    video.addEventListener("click", togglePlayback);
    player.querySelectorAll("[data-video-jump]").forEach((button) => {
      button.addEventListener("click", () => jump(Number(button.dataset.videoJump)));
    });
    player.querySelector("[data-video-t0]").addEventListener("click", seekToT0);
    stepSelect.addEventListener("change", () => {
      const step = Number(stepSelect.value || 1);
      player.querySelectorAll("[data-video-jump]").forEach((button) => {
        const sign = Number(button.dataset.videoJump) < 0 ? "−" : "+";
        button.querySelector("[data-video-jump-label]").textContent = `${sign}${step}s`;
      });
    });
    const attachSource = (url, nativeOnly = false) => {
      segmentLoader?.dispose();
      segmentLoader = null;
      const source = videoPlaybackSourceUrl(url, sourceHasStartHint ? pendingStart : null);
      video.dataset.videoSource = source;
      if (!nativeOnly && typeof createVideoSegmentLoader === "function") {
        segmentLoader = createVideoSegmentLoader(video, {
          url: source,
          frameStepSec,
          playbackRequested: () => wantsPlayback && !suspended,
          // A thumb preview changes the display immediately. Network work
          // follows the last dispatched seek, not intermediate slider values.
          position: () => metadataGeneration !== sourceGeneration && pendingStart === null
            ? null : playbackPosition(),
          attached: startPlayback,
          onBufferAppended: () => {
            if (queuedSeekTarget === null && pendingBackwardSeek !== null && isBuffered(pendingBackwardSeek)) {
              seekTo(pendingBackwardSeek);
            }
            if (rebufferTarget !== null) startPlayback();
          },
          fallback: () => {
            if (!disposed) loadSource(url, video.getAttribute("poster") || "", true);
          },
        });
      }
      if (segmentLoader) video.removeAttribute("src");
      else video.src = source;
      video.load();
    };
    const loadSource = (url, poster = "", nativeOnly = false) => {
      pendingStart = rebufferTarget ?? pendingBackwardSeek
        ?? (video.readyState >= 1 && Number.isFinite(video.currentTime) ? video.currentTime : pendingStart);
      pendingBackwardSeek = null;
      // A cold stream's first native fallback can keep the correct t0 poster.
      // Explicit source changes and non-t0 requests retain the frame guard.
      if (!(nativeOnly && sourceGeneration === 0 && video.readyState < 2
          && pendingStart === configuredT0PlayerSec)) holdFrame(pendingStart);
      sourceGeneration += 1;
      cancelFrameCheck();
      ++playbackAttempt;
      playPending = false;
      playing = false;
      hasPlayed = false;
      rebufferTarget = null;
      resetPlaybackFrames();
      video.pause();
      ++seekRequest;
      cancelPendingSeek?.();
      clearQueuedSeek();
      if (poster) video.setAttribute("poster", poster);
      else video.removeAttribute("poster");
      sourceHasStartHint = pendingStart !== null && Number.isFinite(pendingStart);
      attachSource(url, nativeOnly);
      watchPresentedFrame();
      loading();
      update();
      startPlayback();
    };
    video._setBevVideoTrack = (url, poster = "") => {
      const safe = safeSameOriginAssetUrl(url);
      if (safe && !disposed) loadSource(safe, safeSameOriginAssetUrl(poster));
    };
    player.querySelector("[data-video-track]")?.addEventListener("change", (event) => {
      const url = safeSameOriginAssetUrl(event.target.value);
      if (!url || disposed) return;
      const poster = safeSameOriginAssetUrl(event.target.selectedOptions?.[0]?.dataset.poster || "");
      loadSource(url, poster);
    });
    retry?.addEventListener("click", () => {
      if (!disposed) loadSource(videoElementAssetUrl(video), video.getAttribute("poster") || "");
    });
    rateSelect.addEventListener("change", () => {
      video.playbackRate = Number(rateSelect.value || 1);
    });
    seek.addEventListener("input", () => {
      queueSeek(Number(seek.value || 0));
    });
    seek.addEventListener("change", () => {
      seekTo(Number(seek.value || 0));
      focusPlayer();
    });
    ["loadedmetadata", "durationchange", "timeupdate", "play", "pause", "ended"].forEach(
      (eventName) => listen(video, eventName, update)
    );
    listen(video, "playing", () => { playing = true; hasPlayed = true; update(); });
    listen(video, "waiting", () => {
      // Let the first visible motion through. After underflow, buffer a short
      // playable run instead of repeatedly restarting the native clock.
      if (segmentLoader && hasPlayed && wantsPlayback && !suspended && !playPending && !video.paused && !video.seeking
          && pendingBackwardSeek === null && firstPlaybackFrame !== null
          && lastPlaybackFrame > firstPlaybackFrame + frameStepSec / 2) {
        rebufferTarget = lastPlaybackFrame;
        ++playbackAttempt;
        playPending = false;
        video.pause();
        update();
        startPlayback();
      }
    });
    ["waiting", "seeking", "loadstart"].forEach(name => listen(video, name, () => { playing = false; update(); }));
    listen(video, "ended", () => { wantsPlayback = false; playing = false; update(); });
    player.addEventListener("keydown", (event) => {
      if (event.defaultPrevented || (typeof isImeComposing === "function" && isImeComposing(event))
          || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
      if (event.target.matches("[data-video-seek]") && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
        // A focused range input otherwise consumes the arrow key itself and
        // only moves the thumb. Route it through the decoded-frame seek path,
        // then return focus to the media surface.
        event.preventDefault();
        event.stopPropagation();
        jump(event.key === "ArrowLeft" ? -1 : 1);
        focusPlayer();
        return;
      }
      if (event.target.matches("select, input") || event.target.closest(".ui-select")) {
        event.stopPropagation();
        return;
      }
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        event.stopPropagation();
        jump(event.key === "ArrowLeft" ? -1 : 1);
      } else if (event.key === " ") {
        event.preventDefault();
        event.stopPropagation();
        if (!event.repeat) togglePlayback();
      }
    });
    player.tabIndex = 0;
    update();
    const metadataReady = () => {
      if (disposed || metadataGeneration === sourceGeneration) return;
      metadataGeneration = sourceGeneration;
      const target = queuedSeekTarget ?? pendingStart ?? videoT0PlayerPosition(0, duration());
      pendingStart = null;
      const total = Math.max(0, duration());
      // The exclusive end has no displayable frame in some paused decoders.
      // Seek just inside it so source changes can confirm the final frame.
      const position = Math.min(Math.max(0, total - 0.00001), Math.max(0, target));
      if (heldFrame) heldTarget = position;
      // Native media-fragment startup may already be seeking to this point.
      // Avoid restarting that Range request; retain an exact-seek fallback for
      // browsers without fragment support and descriptors without duration.
      if ((total > 0 && video.currentTime >= total) || Math.abs(video.currentTime - position) > 0.001) seekTo(position);
      else { clearQueuedSeek(); update(); }
      video.playbackRate = Number(rateSelect.value || 1);
      startPlayback();
    };
    listen(video, "loadedmetadata", metadataReady);
    ["loadstart", "waiting", "seeking"].forEach(name => listen(video, name, loading));
    listen(video, "stalled", () => {
      if (video.readyState < 2 || video.seeking || (!video.paused && video.readyState < 3)) loading();
    });
    ["loadeddata", "canplay", "canplaythrough", "progress", "playing", "seeked"].forEach(name => listen(video, name, ready));
    listen(video, "error", () => {
      if (segmentLoader?.recover()) return;
      cancelFrameCheck();
      if (loadTimer !== null) window.clearTimeout(loadTimer);
      loadTimer = null;
      ++playbackAttempt;
      playPending = false;
      playing = false;
      setStatus("error");
      update();
    });
    video._pauseBevPlayback = () => {
      if (disposed) return;
      suspended = true;
      if (rebufferTarget !== null) video.currentTime = rebufferTarget;
      rebufferTarget = null;
      resetPlaybackFrames();
      wantsPlayback = false;
      ++playbackAttempt;
      playPending = false;
      playing = false;
      video.pause();
      segmentLoader?.suspend();
      update();
    };
    video._resumeBevPlayback = () => {
      if (disposed) return;
      suspended = false;
      segmentLoader?.resume();
      // Becoming visible again must not restore an earlier Play choice.
      update();
      startPlayback();
    };
    video._refreshBevPlayerLanguage = () => {
      if (disposed) return;
      planningConstraint.refresh();
      update();
      setStatus(player.dataset.loadState || "loading");
      video.setAttribute("aria-label", uiText("复核视频", "Review video"));
      seek.setAttribute("aria-label", uiText("视频进度", "Video progress"));
      player.querySelector(".bev-video-controls")?.setAttribute("aria-label", uiText("视频控制", "Video controls"));
      if (retry) retry.textContent = uiText("重试视频", "Retry video");
      player.querySelectorAll("[data-video-track-label]").forEach(option => {
        option.textContent = videoTrackLabel(option.dataset.videoTrackLabel);
      });
      player.querySelector("[data-video-track]")?.setAttribute("title", t("media.video_source_shortcuts"));
    };
    // Explicit teardown also cancels queued seeks and old metadata handlers.
    video._disposeBevPlayer = () => {
      if (disposed) return;
      disposed = true;
      segmentLoader?.dispose();
      segmentLoader = null;
      heldFrame?.remove();
      heldFrame = null;
      cancelFrameCheck();
      resetPlaybackFrames();
      planningConstraint.dispose();
      ++playbackAttempt;
      ++sourceGeneration;
      ++seekRequest;
      cancelPendingSeek?.();
      clearQueuedSeek();
      if (loadTimer !== null) window.clearTimeout(loadTimer);
      listeners.forEach(remove => remove());
    };
    loading();
    if (!video.getAttribute("src") && video.dataset.videoSource) attachSource(video.dataset.videoSource);
    // Cached metadata may already have fired before the dynamic pane was bound.
    if (video.error) setStatus("error");
    else if (video.readyState >= 1) metadataReady();
    else startPlayback();
  });
}

function pauseBevVideoPlayers(root) {
  root?.querySelectorAll("video").forEach(video => {
    if (video._pauseBevPlayback) video._pauseBevPlayback();
    else video.pause();
  });
}

function resumeBevVideoPlayers(root) {
  root?.querySelectorAll("video").forEach(video => video._resumeBevPlayback?.());
}

function releaseBevVideoPlayer(root) {
  const videos = root?.matches?.("video") ? [root] : [...(root?.querySelectorAll?.("video") || [])];
  for (const video of videos) {
    video._disposeBevPlayer?.();
    video.pause();
    video.removeAttribute("src");
    video.load();
  }
}
