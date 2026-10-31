/* ra_triage_dashboard/static/js/detail-media.js
 * Issue detail media, trail metadata, external links
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */

function mediaFrameOffsetMs(frame) {
  if (frame?.offset_ms != null) return Number(frame.offset_ms);
  if (frame?.offset_sec != null) return Number(frame.offset_sec) * 1000;
  return NaN;
}
function heroFrameIndex(frames) {
  const exact = frames.findIndex((frame) => mediaFrameOffsetMs(frame) === 0);
  if (exact >= 0) return exact;
  let best = -1, distance = Infinity;
  frames.forEach((frame, index) => {
    const offset = mediaFrameOffsetMs(frame);
    if (Number.isFinite(offset) && Math.abs(offset) < distance) { best = index; distance = Math.abs(offset); }
  });
  return best >= 0 ? best : Math.floor(frames.length / 2);
}

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

function videoTrackLabel(label) {
  if (label === "BEV 视频") return uiText("BEV 视频", "BEV video");
  if (label === "局部 BEV 视频") return uiText("局部 BEV 视频", "Closeup BEV video");
  if (label === "Camera102 视频") return uiText("Camera102 视频", "Camera102 video");
  return label;
}

function handleCloseupVideoShortcut(event) {
  if (!event.shiftKey || String(event.key || "").toLowerCase() !== "v") return false;
  if (event.defaultPrevented || event.repeat || isImeComposing(event)
      || event.ctrlKey || event.metaKey || event.altKey
      || event.target?.closest?.("input, textarea, select, [contenteditable]:not([contenteditable=false]), [role=textbox], .ui-select")) return true;
  const dialog = $("#mediaDialog");
  const inDialog = Boolean(dialog?.open);
  if (document.querySelector("dialog[open]:not(#mediaDialog)")) return true;
  if (inDialog && state.media.snapshot?.intentPreview) return true;
  const caseData = state.activePage === "labeling" ? state.caseLabeling?.caseData : state.selectedCase;
  const pane = typeof detailMediaPane === "function" ? detailMediaPane() : $("#detailPane");
  if (!inDialog && (!["review", "labeling"].includes(state.activePage) || !caseData
      || !pane?.querySelector(".detail-hero-media")
      || document.querySelector("#reviewPane .review-dropdown[open], #caseLabelingEditor .review-dropdown[open]"))) return true;
  event.preventDefault();
  const descriptor = inDialog ? mediaVideo() : videoWithFramePosters(caseData);
  const track = [descriptor, ...(descriptor?.tracks || [])].find(item => item?.source_id === "bev_closeup" && safeSameOriginAssetUrl(item.url));
  if (!track) {
    showToast(uiText("当前 Issue 暂无局部 BEV 视频。", "No closeup BEV video is available for this Issue."), true);
    return true;
  }
  if (inDialog) {
    if (state.media.kind !== "video") switchMediaKind("video");
    const stage = $("#mediaVideoStage");
    const video = stage?.querySelector("video");
    if (video?.getAttribute("src") === track.url) return true;
    const select = stage?.querySelector("[data-video-track]");
    if (select?.querySelector(`option[data-video-source-id="bev_closeup"]`)) {
      select.value = track.url;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      enhanceNativeUiSelect(select);
    } else {
      video?._setBevVideoTrack?.(track.url, track.poster_url || "");
    }
  } else {
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
    const track = tracks.find(item => item.url === video?.getAttribute("src"));
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
    ? `<label><span class="ui-lang-zh">视频源</span><span class="ui-lang-en">Video source</span> <select data-video-track aria-keyshortcuts="Shift+V" title="${escapeHtml(uiText("Shift+V 切换到局部 BEV 视频", "Shift+V switches to closeup BEV video"))}">${tracks.map((track) => `<option value="${escapeHtml(track.url)}" ${track.url === video.url ? "selected" : ""} data-video-source-id="${escapeHtml(track.source_id || "")}" data-poster="${escapeHtml(track.poster_url || "")}" data-video-track-label="${escapeHtml(track.label || "")}">${escapeHtml(videoTrackLabel(track.label))}</option>`).join("")}</select></label>`
    : "";
  const posterUrl = String(video?.poster_url || "").trim();
  const posterAttribute = posterUrl ? ` poster="${escapeHtml(posterUrl)}"` : "";
  const videoMarkup = `<video src="${escapeHtml(video.url)}"${posterAttribute} preload="metadata" playsinline draggable="false" aria-label="${escapeHtml(uiText("复核视频", "Review video"))}"></video>`;
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
        ${issueId ? `<button class="button button-quiet" type="button" data-planning-constraint aria-haspopup="dialog" aria-expanded="false">${escapeHtml(uiText("规划约束", "Planning constraint"))}</button>` : ""}
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
    const planningConstraint = bindPlanningConstraint(player, video);
    const playButton = player.querySelector("[data-video-play]");
    const seek = player.querySelector("[data-video-seek]");
    const stepSelect = player.querySelector("[data-video-step]");
    const rateSelect = player.querySelector("[data-video-rate]");
    const timeLabel = player.querySelector("[data-video-time]");
    const startLabel = player.querySelector("[data-video-relative-start]");
    const startOffsetSec = Number(player.dataset.startOffsetSec || 0);
    const configuredT0PlayerSec = Number(player.dataset.t0PlayerSec || 0);
    const configuredDuration = Number(player.dataset.durationSec || 0);
    let disposed = false;
    let sourceGeneration = 0;
    let pendingStart = configuredT0PlayerSec > 0 ? configuredT0PlayerSec : null;
    let resumeAfterLoad = false;
    let loadTimer = null;
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
      if (disposed || video.readyState < 2 || video.seeking) return;
      if (loadTimer !== null) window.clearTimeout(loadTimer);
      loadTimer = null;
      setStatus("ready");
    };
    let seekRequest = 0;
    let cancelPendingSeek = null;
    let queuedSeekTarget = null;
    let queuedSeekTimer = null;
    const duration = () => Number.isFinite(video.duration) ? video.duration : configuredDuration;
    const update = (previewTime = null) => {
      const total = Math.max(0, duration());
      const currentTime = previewTime !== null && Number.isFinite(Number(previewTime))
        ? Number(previewTime)
        : video.currentTime || 0;
      seek.max = String(total || configuredDuration || 40);
      seek.value = String(Math.min(Number(seek.max), Math.max(0, currentTime)));
      startLabel.textContent = formatSignedSeconds(startOffsetSec);
      timeLabel.textContent = `${formatSignedSeconds(startOffsetSec + currentTime)} / ${formatSignedSeconds(startOffsetSec + total)}`;
      playButton.textContent = video.paused ? t("media.play") : t("media.pause");
    };
    const focusPlayer = () => {
      player.focus({ preventScroll: true });
    };
    const seekTo = (target) => {
      if (disposed) return;
      if (video.readyState < 1) { pendingStart = target; update(target); return; }
      if (queuedSeekTimer !== null) window.clearTimeout(queuedSeekTimer);
      queuedSeekTimer = null;
      queuedSeekTarget = null;
      const request = ++seekRequest;
      cancelPendingSeek?.();
      let settled = false;
      let fallbackTimer = null;
      const settle = () => {
        if (disposed || settled || request !== seekRequest) return;
        settled = true;
        video.removeEventListener("seeked", settle);
        if (fallbackTimer) window.clearTimeout(fallbackTimer);
        cancelPendingSeek = null;
        update();
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
      video.currentTime = target;
      update();
      // A remote asset can delay seeked while metadata or the first keyframe
      // is fetched. Keep controls responsive and reconcile once it arrives.
      fallbackTimer = window.setTimeout(settle, 800);
    };
    const queueSeek = (target, delay = 75) => {
      if (disposed) return;
      const total = Math.max(0, duration());
      queuedSeekTarget = Math.min(total, Math.max(0, Number(target) || 0));
      update(queuedSeekTarget);
      if (queuedSeekTimer !== null) window.clearTimeout(queuedSeekTimer);
      queuedSeekTimer = window.setTimeout(() => {
        const latest = queuedSeekTarget;
        queuedSeekTimer = null;
        if (!disposed && latest !== null) seekTo(latest);
      }, Math.max(0, delay));
    };
    const jump = (direction) => {
      const step = Math.max(0.01, Number(stepSelect.value || 1));
      const currentTime = queuedSeekTarget !== null
        ? queuedSeekTarget
        : Number.isFinite(video.currentTime) ? video.currentTime : 0;
      const target = Math.min(
        Math.max(0, duration()),
        Math.max(0, currentTime + direction * step)
      );
      queueSeek(target);
    };
    const togglePlayback = () => {
      if (disposed) return;
      if (queuedSeekTarget !== null) {
        const target = queuedSeekTarget;
        seekTo(target);
      }
      if (video.paused) {
        const generation = sourceGeneration;
        video.play().catch((error) => {
          if (!disposed && generation === sourceGeneration && error.name !== "AbortError") {
            showToast(t("media.play_fail", { msg: error.message }), true);
          }
        });
      } else {
        video.pause();
      }
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
    const loadSource = (url, poster = "") => {
      sourceGeneration += 1;
      pendingStart = video.readyState >= 1 && Number.isFinite(video.currentTime) ? video.currentTime : pendingStart;
      resumeAfterLoad = !video.paused;
      video.pause();
      ++seekRequest;
      cancelPendingSeek?.();
      if (queuedSeekTimer !== null) window.clearTimeout(queuedSeekTimer);
      queuedSeekTimer = null;
      queuedSeekTarget = null;
      if (poster) video.setAttribute("poster", poster);
      else video.removeAttribute("poster");
      video.src = url;
      video.load();
      loading();
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
      if (!disposed) loadSource(video.getAttribute("src"), video.getAttribute("poster") || "");
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
    player.addEventListener("keydown", (event) => {
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
      if (event.target.matches("select, input, button") || event.target.closest(".ui-select")) {
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
        togglePlayback();
      }
    });
    player.tabIndex = 0;
    update();
    const metadataReady = () => {
      if (disposed) return;
      const target = Number.isFinite(pendingStart) ? pendingStart : videoT0PlayerPosition(0, duration());
      pendingStart = null;
      seekTo(Math.min(Math.max(0, duration()), Math.max(0, target)));
      video.playbackRate = Number(rateSelect.value || 1);
      if (resumeAfterLoad) { resumeAfterLoad = false; togglePlayback(); }
    };
    listen(video, "loadedmetadata", metadataReady);
    ["loadstart", "waiting", "seeking"].forEach(name => listen(video, name, loading));
    listen(video, "stalled", () => {
      if (video.readyState < 2 || video.seeking || (!video.paused && video.readyState < 3)) loading();
    });
    ["loadeddata", "canplay", "playing", "seeked"].forEach(name => listen(video, name, ready));
    listen(video, "error", () => {
      if (loadTimer !== null) window.clearTimeout(loadTimer);
      loadTimer = null;
      setStatus("error");
    });
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
      player.querySelector("[data-video-track]")?.setAttribute("title", uiText("Shift+V 切换到局部 BEV 视频", "Shift+V switches to closeup BEV video"));
    };
    // Explicit teardown also cancels queued seeks and old metadata handlers.
    video._disposeBevPlayer = () => {
      if (disposed) return;
      disposed = true;
      planningConstraint.dispose();
      ++sourceGeneration;
      ++seekRequest;
      cancelPendingSeek?.();
      if (queuedSeekTimer !== null) window.clearTimeout(queuedSeekTimer);
      if (loadTimer !== null) window.clearTimeout(loadTimer);
      listeners.forEach(remove => remove());
    };
    loading();
    // Cached metadata may already have fired before the dynamic pane was bound.
    if (video.error) setStatus("error");
    else if (video.readyState >= 1) metadataReady();
  });
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

function detailMediaPane() {
  return state.activePage === "labeling" ? $("#caseLabelingMedia") : $("#detailPane");
}

function detailMediaPrefix() {
  return state.activePage === "labeling" ? "caseLabeling" : "detail";
}

function detailHeroMediaEl() {
  return detailMediaPane()?.querySelector(".detail-hero-media") || $("#detailHeroMedia");
}

function ensureDetailMediaState(caseData) {
  const issueId = String(caseData?.issue_id || "");
  const available = {
    bev: Boolean(caseData?.assets?.frames?.length),
    camera: Boolean(caseData?.camera?.frames?.length),
    video: Boolean(caseData?.assets?.video?.url),
  };
  if (state.detailMedia.issueId !== issueId) {
    state.detailMedia = {
      issueId,
      kind: preferredMediaKind(caseData),
      indexes: {
        bev: heroFrameIndex(caseData?.assets?.frames || []),
        camera: heroFrameIndex(caseData?.camera?.frames || []),
      },
      loadSeq: 0,
    };
  }
  if (!available[state.detailMedia.kind]) state.detailMedia.kind = preferredMediaKind(caseData);
  return available;
}

function heroMediaSection(caseData) {
  const frames = caseData?.assets?.frames || [];
  const video = videoWithFramePosters(caseData);
  const camera = caseData?.camera?.frames || [];
  const previewThumbnailUrl = safeSameOriginAssetUrl(caseData?.preview_thumbnail_url);
  if (!frames.length && !camera.length && !video?.url) {
    if (caseData?.media_status === "pending") {
      return `<section class="hero-media detail-hero-media" id="${detailMediaPrefix()}HeroMedia" tabindex="0"><div class="no-asset hero-media-placeholder detail-media-pending"><span>${escapeHtml(uiText("正在加载 BEV、Camera 与视频…", "Loading BEV, camera, and video…"))}</span></div></section>`;
    }
    return `<section class="hero-media"><div class="no-asset hero-media-placeholder"><span>${escapeHtml(t("media.no_assets"))}</span></div></section>`;
  }
  ensureDetailMediaState(caseData);
  const selectedTrack = video?.tracks?.find(track => track.url === state.detailMedia.videoTrack);
  const kind = state.detailMedia.kind;
  const activeFrames = kind === "camera" ? camera : frames;
  const index = Math.max(0, Math.min(
    Number(state.detailMedia.indexes[kind] || 0),
    Math.max(activeFrames.length - 1, 0)
  ));
  if (kind !== "video") state.detailMedia.indexes[kind] = index;
  const frame = activeFrames[index];
  const content = kind === "video" && video?.url
    ? videoPlayerMarkup(selectedTrack ? { ...video, ...selectedTrack } : video, {
        zoomable: false,
        compact: true,
        issueId: caseData.issue_id,
      })
    : `<button type="button" class="hero-media-button${previewThumbnailUrl ? " has-preview" : ""}" data-detail-media-expand aria-label="展开${kind === "camera" ? " Camera" : " BEV"}媒体预览">
        ${previewThumbnailUrl ? `<img class="detail-media-preview" src="${escapeHtml(previewThumbnailUrl)}" alt="" aria-hidden="true" />` : ""}
        <img class="detail-media-image" src="${escapeHtml(frame?.url || "")}" alt="${kind === "camera" ? "Camera" : "Ares Capture BEV"} ${escapeHtml(frameLabel(frame || {}))}" />
        <span class="hero-media-overlay">${escapeHtml(frameLabel(frame || {}))} · ${t("media.click_expand")}</span>
      </button>`;
  const quickTimeline = kind === "video" ? "" : mediaTimelineMarkup(activeFrames, index, "detail-media-frame");
  const frameControls = kind === "video" ? "" : `
    <div class="detail-media-frame-controls" aria-label="图片帧切换">
      <button class="button button-quiet" id="${detailMediaPrefix()}MediaPreviousButton" type="button" aria-label="${escapeHtml(t("media.prev_frame"))}">${escapeHtml(t("media.prev_frame"))}</button>
      <div class="detail-media-frame-center">
        <span class="detail-media-position" id="${detailMediaPrefix()}MediaPosition">${activeFrames.length ? `${index + 1} / ${activeFrames.length}` : "—"}</span>
        ${quickTimeline}
      </div>
      <button class="button button-quiet" id="${detailMediaPrefix()}MediaNextButton" type="button" aria-label="${escapeHtml(t("media.next_frame"))}">${escapeHtml(t("media.next_frame"))}</button>
    </div>`;
  return `
      <section class="hero-media detail-hero-media" id="${detailMediaPrefix()}HeroMedia" data-detail-media-kind="${escapeHtml(kind)}" tabindex="0" aria-label="Issue 媒体" aria-keyshortcuts="0">
      <div class="detail-media-content">${content}</div>
      ${frameControls}
      <p class="detail-media-help" data-i18n="${kind === "video" ? "media.help_video" : "media.help_image"}">${escapeHtml(kind === "video" ? t("media.help_video") : t("media.help_image"))}</p>
    </section>`;
}

function hydrateDetailMedia(caseData) {
  const issueId = String(caseData?.issue_id || "");
  const expectedId = state.activePage === "labeling"
    ? state.caseLabeling?.issueId
    : state.selectedId;
  if (!issueId || issueId !== expectedId) return false;
  const scrollY = window.scrollY;
  const pane = detailMediaPane();
  const hero = pane?.querySelector(".detail-hero-media") || $("#detailHeroMedia");
  if (hero) {
    releaseBevVideoPlayer(hero);
    hero.outerHTML = heroMediaSection(caseData);
  }
  const command = pane?.querySelector(".detail-media-command");
  if (command) command.outerHTML = detailMediaCommandMarkup(caseData);
  bindDetailMedia(caseData);
  window.requestAnimationFrame(() => {
    if (expectedId === issueId) {
      window.scrollTo({ top: scrollY, behavior: "auto" });
    }
  });
  return true;
}

function hydrateDetailMediaControls(caseData) {
  const issueId = String(caseData?.issue_id || "");
  const expectedId = state.activePage === "labeling"
    ? state.caseLabeling?.issueId
    : state.selectedId;
  if (!issueId || issueId !== expectedId) return false;
  refreshVideoFramePosters(detailHeroMediaEl(), caseData);
  const command = detailMediaPane()?.querySelector(".detail-media-command");
  if (command) command.outerHTML = detailMediaCommandMarkup(caseData);
  // Rebind the newly replaced picker without replacing the decoded video.
  // bindBevVideoPlayers is idempotent for the preserved player node.
  bindDetailMedia(caseData);
  return true;
}

function mediaTimelineMarkup(frames, activeIndex, dataName, className = "detail-media-timeline media-timeline") {
  const buttons = mediaTimelineButtonsMarkup(frames, activeIndex, dataName);
  if (!buttons) return "";
  return `<div class="${className}" aria-label="媒体时间点快速跳转">${buttons}</div>`;
}

function mediaTimelineButtonsMarkup(frames, activeIndex, dataName) {
  if (!Array.isArray(frames) || !frames.length) return "";
  return frames
    .map((frame, index) => {
      const label = frameLabel(frame);
      return `<button type="button" class="timeline-dot ${index === activeIndex ? "active" : ""}" data-${escapeHtml(dataName)}="${index}" title="跳转到 ${escapeHtml(label)}">${escapeHtml(label)}</button>`;
    })
    .join("");
}

function preloadDetailImage(caseData, kind, index, root, onReady) {
  const issueId = String(caseData?.issue_id || "");
  const frames = kind === "camera" ? caseData?.camera?.frames || [] : caseData?.assets?.frames || [];
  const frame = frames[index];
  const url = frame?.url;
  if (!issueId || !url || !root) return;
  const requestSeq = Number(state.detailMedia.loadSeq || 0) + 1;
  state.detailMedia.loadSeq = requestSeq;
  root.setAttribute("aria-busy", "true");
  root.querySelectorAll("#detailMediaPreviousButton, #detailMediaNextButton").forEach((control) => {
    control.disabled = true;
  });
  root.querySelectorAll("[data-detail-media-frame]").forEach((control) => {
    control.disabled = true;
  });
  const image = new Image();
  image.decoding = "async";
  let settled = false;
  const isCurrent = () => (
    requestSeq === state.detailMedia.loadSeq &&
    root.isConnected &&
    state.detailMedia.issueId === issueId &&
    state.selectedId === issueId &&
    String(state.selectedCase?.issue_id || "") === issueId
  );
  const finish = (loaded) => {
    if (settled) return;
    settled = true;
    if (!isCurrent()) return;
    root.removeAttribute("aria-busy");
    root.querySelectorAll("#detailMediaPreviousButton, #detailMediaNextButton").forEach((control) => {
      control.disabled = false;
    });
    root.querySelectorAll("[data-detail-media-frame]").forEach((control) => {
      control.disabled = false;
    });
    if (loaded) onReady(image);
    else showToast(t("media.load_fail"), true);
  };
  image.onload = () => {
    let decoded;
    try {
      decoded = typeof image.decode === "function" ? image.decode() : Promise.resolve();
    } catch {
      decoded = Promise.resolve();
    }
    Promise.resolve(decoded).catch(() => {}).then(() => finish(true));
  };
  image.onerror = () => finish(false);
  image.src = url;
}

function applyDetailImageFrame(root, caseData, kind, index, loadedImage = null) {
  const frames = kind === "camera" ? caseData?.camera?.frames || [] : caseData?.assets?.frames || [];
  const frame = frames[index];
  const image = root?.querySelector(".detail-media-image");
  const button = root?.querySelector("[data-detail-media-expand]");
  const overlay = root?.querySelector(".hero-media-overlay");
  if (!frame?.url || !image || !button || !overlay) return false;
  const nextImage = loadedImage || image;
  nextImage.className = "detail-media-image";
  nextImage.alt = `${kind === "camera" ? "Camera" : "Ares Capture BEV"} ${frameLabel(frame)}`;
  nextImage.decoding = "async";
  nextImage.draggable = false;
  nextImage.style.transition = "none";
  nextImage.style.animation = "none";
  nextImage.style.opacity = "1";
  if (nextImage !== image) {
    // Keep the current frame above the already-decoded next frame until the
    // browser has had two rendering opportunities.  One requestAnimationFrame
    // callback runs before paint and is not a guarantee that a large image has
    // reached the compositor yet.
    nextImage.style.position = "absolute";
    nextImage.style.inset = "0";
    nextImage.style.zIndex = "0";
    nextImage.style.visibility = "visible";
    image.style.position = "absolute";
    image.style.inset = "0";
    image.style.zIndex = "1";
    overlay.style.zIndex = "2";
    image.before(nextImage);
    const commit = () => {
      if (!nextImage.isConnected) return;
      nextImage.style.zIndex = "1";
      image.remove();
    };
    if (typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(() => window.requestAnimationFrame(commit));
    } else commit();
  } else {
    nextImage.src = frame.url;
  }
  button.setAttribute("aria-label", `展开${kind === "camera" ? " Camera" : " BEV"}媒体预览`);
  overlay.textContent = `${frameLabel(frame)} · ${t("media.click_expand")}`;
  const position = root.querySelector("#detailMediaPosition");
  if (position) position.textContent = `${index + 1} / ${frames.length}`;
  root.querySelectorAll("[data-detail-media-frame]").forEach((timelineButton) => {
    timelineButton.classList.toggle("active", Number(timelineButton.dataset.detailMediaFrame) === index);
  });
  const kindSelect = root.querySelector("#detailMediaKindSelect");
  if (kindSelect) kindSelect.value = kind;
  return true;
}

function detailMediaKindOptions(caseData, available) {
  return [
    {
      value: "bev",
      label: uiText(
        `BEV 图片 · ${caseData?.assets?.frames?.length || 0}`,
        `BEV images · ${caseData?.assets?.frames?.length || 0}`
      ),
      disabled: !available.bev,
    },
    {
      value: "camera",
      label: uiText(
        `Camera 图片 · ${caseData?.camera?.frames?.length || 0}`,
        `Camera images · ${caseData?.camera?.frames?.length || 0}`
      ),
      disabled: !available.camera,
    },
    {
      value: "video",
      label: uiText(
        `Ares Studio 视频 · ${available.video ? 1 : 0}`,
        `Ares Studio video · ${available.video ? 1 : 0}`
      ),
      disabled: !available.video,
    },
    ...(caseData?.assets?.video?.tracks || []).filter(track => track.url !== caseData.assets.video.url && safeSameOriginAssetUrl(track.url))
      .map(track => ({value: `track:${track.url}`, label: videoTrackLabel(track.label), disabled: false})),
  ];
}

function detailMediaSelectedKind(caseData) {
  const track = state.detailMedia.videoTrack;
  return state.detailMedia.kind === "video" && track && track !== caseData?.assets?.video?.url
    ? `track:${track}` : state.detailMedia.kind;
}

function detailMediaCommandMarkup(caseData) {
  const available = ensureDetailMediaState(caseData);
  const kind = detailMediaSelectedKind(caseData);
  const options = detailMediaKindOptions(caseData, available);
  const active = options.find((item) => item.value === kind) || options[0];
  return `<div class="detail-media-command" aria-label="详情媒体控制">
    <div class="ui-select detail-media-picker" id="${detailMediaPrefix()}MediaKindPicker">
      <button class="ui-select-trigger detail-media-picker-trigger" id="${detailMediaPrefix()}MediaKindTrigger" type="button" aria-haspopup="listbox" aria-expanded="false" aria-controls="${detailMediaPrefix()}MediaKindPanel" aria-label="媒体类型">
        <span class="ui-select-summary detail-media-picker-summary">${escapeHtml(active?.label || "媒体类型")}</span>
        <span class="ui-select-caret" aria-hidden="true"></span>
      </button>
      <div class="ui-select-panel detail-media-picker-panel" id="${detailMediaPrefix()}MediaKindPanel" role="listbox" hidden></div>
      <select class="ui-select-native gateway-model-native-select detail-media-select" id="${detailMediaPrefix()}MediaKindSelect" aria-hidden="true" tabindex="-1">
        ${options
          .map(
            (item) =>
              `<option value="${escapeHtml(item.value)}" ${item.disabled ? "disabled" : ""} ${item.value === kind ? "selected" : ""}>${escapeHtml(item.label)}</option>`
          )
          .join("")}
      </select>
    </div>
    <button class="button button-quiet detail-media-expand" id="${detailMediaPrefix()}MediaExpandButton" type="button"><span class="ui-lang-zh">展开查看</span><span class="ui-lang-en">Expand</span></button>
  </div>`;
}

function refreshDetailMediaTimeline(root, caseData) {
  const kind = state.detailMedia.kind;
  if (kind === "video") return;
  const frames = kind === "camera" ? caseData?.camera?.frames || [] : caseData?.assets?.frames || [];
  const timeline = root?.querySelector(".detail-media-timeline");
  if (!timeline || !frames.length) return;
  const index = Number(state.detailMedia.indexes[kind] || 0);
  timeline.outerHTML = mediaTimelineMarkup(frames, index, "detail-media-frame");
}

function bindDetailMediaTimeline(root, caseData, onRender = null) {
  root.querySelectorAll("[data-detail-media-frame]").forEach((button) => {
    button.addEventListener("click", () => {
      const kind = state.detailMedia.kind;
      if (kind === "video") return;
      const frames = kind === "camera" ? caseData?.camera?.frames || [] : caseData?.assets?.frames || [];
      const nextIndex = Number(button.dataset.detailMediaFrame);
      if (!Number.isInteger(nextIndex) || nextIndex < 0 || nextIndex >= frames.length) return;
      if (nextIndex === Number(state.detailMedia.indexes[kind] || 0)) return;
      preloadDetailImage(caseData, kind, nextIndex, root, (loadedImage) => {
        state.detailMedia.indexes[kind] = nextIndex;
        if (!applyDetailImageFrame(root, caseData, kind, nextIndex, loadedImage) && onRender) onRender();
      });
    });
  });
}

function bindDetailMedia(caseData) {
  const pane = detailMediaPane();
  const prefix = detailMediaPrefix();
  const root = pane?.querySelector(".detail-hero-media") || $("#detailHeroMedia");
  pane?.classList.toggle(
    "detail-pane-video",
    root?.dataset.detailMediaKind === "video"
  );
  if (!pane || !root) return;
  const focusMediaSurface = () => {
    const surface = pane?.querySelector(".detail-hero-media");
    if (!surface) return;
    surface.focus({ preventScroll: true });
  };
  const render = () => {
    const current = pane?.querySelector(".detail-hero-media");
    if (current) {
      releaseBevVideoPlayer(current);
      current.outerHTML = heroMediaSection(caseData);
    }
    bindDetailMedia(caseData);
  };
  const switchKind = (kind) => {
    if (kind === "video" || kind.startsWith("track:")) {
      const descriptor = videoWithFramePosters(caseData);
      const track = kind === "video" ? descriptor : descriptor?.tracks?.find(item => `track:${item.url}` === kind);
      if (!track?.url) return;
      state.detailMedia.userSelected = true;
      state.detailMedia.videoTrack = track.url;
      if (state.detailMedia.kind === "video") {
        root.querySelector("video")?._setBevVideoTrack?.(track.url, track.poster_url || "");
        focusMediaSurface();
        return;
      }
      kind = "video";
    }
    const available = kind === "video"
      ? Boolean(caseData?.assets?.video?.url)
      : Boolean((kind === "camera" ? caseData?.camera?.frames : caseData?.assets?.frames)?.length);
    if (!available || state.detailMedia.kind === kind) return;
    state.detailMedia.userSelected = true;
    root.querySelector("video")?.pause();
    if (kind === "video") {
      state.detailMedia.loadSeq += 1;
      state.detailMedia.kind = kind;
      render();
      focusMediaSurface();
      return;
    }
    const frames = kind === "camera" ? caseData?.camera?.frames || [] : caseData?.assets?.frames || [];
    const index = Math.max(0, Math.min(
      Number(state.detailMedia.indexes[kind] || 0),
      Math.max(frames.length - 1, 0)
    ));
    preloadDetailImage(caseData, kind, index, root, (loadedImage) => {
      state.detailMedia.kind = kind;
      state.detailMedia.indexes[kind] = index;
      if (!applyDetailImageFrame(root, caseData, kind, index, loadedImage)) {
        render();
        focusMediaSurface();
        return;
      }
      refreshDetailMediaTimeline(root, caseData);
      bindDetailMediaTimeline(root, caseData, render);
      focusMediaSurface();
    });
  };
  const move = (delta) => {
    const kind = state.detailMedia.kind;
    if (kind === "video") return;
    const frames = kind === "camera" ? caseData?.camera?.frames || [] : caseData?.assets?.frames || [];
    if (!frames.length) return;
    const nextIndex = (Number(state.detailMedia.indexes[kind] || 0) + delta + frames.length) % frames.length;
    preloadDetailImage(caseData, kind, nextIndex, root, (loadedImage) => {
      state.detailMedia.indexes[kind] = nextIndex;
      if (!applyDetailImageFrame(root, caseData, kind, nextIndex, loadedImage)) render();
    });
  };
  const expand = () => {
    const descriptor = videoWithFramePosters(caseData);
    const track = descriptor?.tracks?.find(item => item.url === state.detailMedia.videoTrack);
    const expandedCase = track ? { ...caseData, assets: { ...caseData.assets, video: { ...descriptor, ...track } } } : caseData;
    openMedia(state.detailMedia.kind,
      state.detailMedia.kind === "video" ? 0 : state.detailMedia.indexes[state.detailMedia.kind],
      { caseData: expandedCase });
  };
  const kindSelect = pane.querySelector(`#${prefix}MediaKindSelect`);
  const kindPicker = pane.querySelector(`#${prefix}MediaKindPicker`);
  if (kindSelect) {
    kindSelect.value = detailMediaSelectedKind(caseData);
    kindSelect.onchange = () => {
      const nextKind = kindSelect.value;
      // The media surface owns the B/C/V and arrow shortcuts.  Do not leave
      // focus on the type selector after a choice is made, otherwise
      // ArrowLeft/ArrowRight continue changing this selector instead of
      // stepping frames or jumping the video.
      kindSelect.blur();
      pane.querySelector(`#${prefix}MediaKindTrigger`)?.blur();
      if (nextKind === detailMediaSelectedKind(caseData)) {
        focusMediaSurface();
        return;
      }
      switchKind(nextKind);
    };
  }
  if (kindPicker && typeof populateUiSelect === "function") {
    const available = ensureDetailMediaState(caseData);
    populateUiSelect(
      kindPicker,
      detailMediaKindOptions(caseData, available),
      detailMediaSelectedKind(caseData)
    );
    bindUiSelect(kindPicker, { maxHeight: 260, maxWidth: 280 });
  }
  const previousButton = pane.querySelector(`#${prefix}MediaPreviousButton`);
  const nextButton = pane.querySelector(`#${prefix}MediaNextButton`);
  const position = pane.querySelector(`#${prefix}MediaPosition`);
  const videoMode = state.detailMedia.kind === "video";
  if (previousButton) {
    previousButton.hidden = videoMode;
    previousButton.onclick = () => move(-1);
  }
  if (nextButton) {
    nextButton.hidden = videoMode;
    nextButton.onclick = () => move(1);
  }
  if (position) {
    const activeFrames = state.detailMedia.kind === "camera"
      ? caseData?.camera?.frames || []
      : caseData?.assets?.frames || [];
    const activeIndex = Number(state.detailMedia.indexes[state.detailMedia.kind] || 0);
    position.hidden = videoMode;
    position.textContent = activeFrames.length ? `${activeIndex + 1} / ${activeFrames.length}` : "—";
  }
  const expandButton = pane.querySelector(`#${prefix}MediaExpandButton`);
  if (expandButton) expandButton.onclick = expand;
  root.querySelectorAll("[data-detail-media-expand]").forEach((button) => { button.onclick = expand; });
  bindDetailMediaTimeline(root, caseData, render);
  bindBevVideoPlayers(root);
}

function predictionCards(caseData) {
  const predictions = caseData.predictions || [];
  if (!predictions.length) {
    return '<div class="no-asset">当前 case 没有 Run 模型输出。可创建 Trail 只读快照、上传批量结果，或等待 Batch 预测生成新的 Run。</div>';
  }
  return `<div class="model-list">${predictions
    .map((prediction) => {
      const selected = prediction.model_run_id === state.selectedRunId;
      const extra = prediction.model_extra?.ra_stuck_auto_result_info;
      const detail = prediction.model_reason || (typeof extra === "object" ? extra.text || "" : "") || "模型未返回解释。";
      return `<article class="model-card ${selected ? "active" : ""}">
        <div class="model-card-head"><div><h3>${escapeHtml(prediction.run_name || "模型输出")}</h3></div>${labelBadge(prediction.model_label, "未输出")}</div>
        <p>${escapeHtml(detail)}</p>
        <div class="model-card-meta">${formatModelConfidence(prediction.model_confidence)} confidence · ${formatTime(prediction.created_at)}${prediction.run_created_by ? ` · 创建人 ${escapeHtml(prediction.run_created_by)}` : ""}</div>
      </article>`;
    })
    .join("")}</div>`;
}

function currentRunOutputMarkup(_caseData, prediction) {
  if (!prediction) return "";
  const reason = String(prediction.model_reason || "").trim();
  return `<section class="current-run-output" aria-label="当前 Run Reason">
    <div class="current-run-output-heading">
      <div><span>当前 Run Reason</span><strong>${escapeHtml(prediction.run_name || "模型输出")}</strong></div>
      <span>${labelBadge(prediction.model_label, "未输出")}${prediction.model_confidence === null || prediction.model_confidence === undefined ? "" : ` · ${escapeHtml(formatModelConfidence(prediction.model_confidence))} confidence`}</span>
    </div>
    <p class="current-run-reason">${escapeHtml(reason || "模型未返回 reason。")}</p>
  </section>`;
}

function openHistoryDialog(kind, caseData) {
  if (!caseData) return;
  if (kind === "labeling" && state.activePage === "labeling") { openCaseLabelDecision(caseData); return; }
  const isModel = kind === "model";
  const isLabeling = kind === "labeling";
  const dialog = $("#historyDialog");
  if (dialog) { dialog.dataset.historyKind = isModel ? "model" : isLabeling ? "labeling" : "review"; dialog.historyCaseData = caseData; }
  const predictions = caseData.predictions || [];
  const annotations = isModel || isLabeling
    ? []
    : typeof reviewAnnotationsForAllRuns === "function"
      ? reviewAnnotationsForAllRuns(caseData)
      : (caseData.annotations || []);
  $("#historyDialogTitle").textContent = isModel
    ? uiText("评测 Run 输出历史", "Model run history")
    : isLabeling
      ? uiText("标注历史", "Label history")
      : uiText("Review 历史", "Review history");
  $("#historyDialogMeta").textContent = isModel
    ? uiText(
        `${predictions.length} 个模型 Run · 当前 Review Run 会高亮`,
        `${predictions.length} model runs · current review run is highlighted`
      )
    : isLabeling
      ? (() => {
          const labelCount = (caseData.label_cases || []).reduce(
            (count, labelCase) => count + (labelCase.resolution?.heads || []).length,
            0
          );
          return uiText(`${labelCount} 条工作台标注`, `${labelCount} workbench labels`);
        })()
      : (() => {
        const runCount = new Set(
          annotations.map((item) => String(item.model_run_id || "legacy"))
        ).size;
        return uiText(
          `${annotations.length} 条历史 Review · 跨 ${runCount} 个 Model Run`,
          `${annotations.length} reviews · across ${runCount} model runs`
        );
      })();
  $("#historyDialogContent").innerHTML = isModel
    ? predictionCards(caseData)
    : isLabeling
      ? caseLabelingHistoryMarkup(caseData)
      : annotationHistory(annotations);
  if (!isModel && !isLabeling) bindAnnotationHistory($("#historyDialogContent"), caseData);
  openDialog("historyDialog");
}

function toggleHistoryDialog(kind, caseData) {
  const dialog = $("#historyDialog");
  if (dialog?.open && dialog.dataset.historyKind === kind) {
    closeDialog("historyDialog");
    return false;
  }
  if (dialog?.open) closeDialog("historyDialog");
  openHistoryDialog(kind, caseData);
  return true;
}

function formatRaEventTimestamp(value) {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return "—";
  const date = new Date(numeric);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleString("zh-CN", { hour12: false });
}

function formatRaEventRelativeTime(value, t0TimestampMs) {
  const timestamp = Number(value);
  const reference = Number(t0TimestampMs);
  if (
    !Number.isFinite(timestamp) || timestamp <= 0 ||
    !Number.isFinite(reference) || reference <= 0
  ) return "—";
  const deltaSeconds = (timestamp - reference) / 1000;
  if (Math.abs(deltaSeconds) < 0.0005) return "t0";
  const magnitude = Math.abs(deltaSeconds)
    .toFixed(3)
    .replace(/\.0+$/, "")
    .replace(/(\.\d*?)0+$/, "$1");
  return `t${deltaSeconds < 0 ? "−" : "+"}${magnitude}s`;
}

function renderRaEventRows(
  events,
  query = "",
  t0TimestampMs = state.raEventDialog.t0TimestampMs
) {
  const normalizedQuery = String(query || "").trim().toLowerCase();
  const rows = (Array.isArray(events) ? events : []).filter((item) => {
    if (!normalizedQuery) return true;
    return [item?.event, item?.value]
      .map((value) => String(value ?? "").toLowerCase())
      .some((value) => value.includes(normalizedQuery));
  });
  const body = $("#raEventTableBody");
  if (body) {
    body.innerHTML = rows
      .map((item) => {
        const timestamp = item?.timestamp;
        return `<tr>
          <td>${escapeHtml(item?.event || "—")}</td>
          <td>${escapeHtml(item?.value ?? "—")}</td>
          <td class="ra-event-timestamp">${escapeHtml(timestamp ?? "—")}</td>
          <td class="ra-event-relative-time">${escapeHtml(formatRaEventRelativeTime(timestamp, t0TimestampMs))}</td>
          <td>${escapeHtml(formatRaEventTimestamp(timestamp))}</td>
        </tr>`;
      })
      .join("");
  }
  const empty = $("#raEventEmpty");
  if (empty) empty.hidden = rows.length > 0;
  return rows.length;
}

function bindRaEventDialogFocus() {
  const dialog = $("#raEventDialog");
  if (!dialog || dialog.dataset.escapeFocusBound === "1") return;
  dialog.dataset.escapeFocusBound = "1";
  const releaseTriggerFocus = () => {
    if (document.querySelector("dialog[open]")) return false;
    const active = document.activeElement;
    if (!active?.matches?.("[data-open-ra-event]")) return false;
    active.blur();
    return true;
  };
  // Native dialog dismissal restores its opener before the close event. Release
  // only that trigger, never a field the user has moved to in the meantime.
  dialog.addEventListener("close", () => window.requestAnimationFrame(releaseTriggerFocus));
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || event.defaultPrevented || event.isComposing
        || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
    if (releaseTriggerFocus()) {
      event.preventDefault();
      event.stopPropagation();
    }
  });
}

function openRaEventDialog(caseData) {
  if (!caseData) return;
  const externalLinks = caseData.external_links || {};
  const events = Array.isArray(externalLinks.ra_events) ? externalLinks.ra_events : [];
  state.raEventDialog = {
    issueId: String(caseData.issue_id || ""),
    events,
    trailUrl: safeUrl(externalLinks.ra_event_url),
    t0TimestampMs: reviewCaseT0TimestampMs(caseData),
  };
  const input = $("#raEventSearchInput");
  if (input) input.value = "";
  const meta = $("#raEventDialogMeta");
  if (meta) meta.textContent = `${events.length} 条 · ${caseData.issue_id || "当前 Issue"}`;
  const trailLink = $("#raEventTrailLink");
  if (trailLink) {
    trailLink.hidden = !state.raEventDialog.trailUrl;
    trailLink.href = state.raEventDialog.trailUrl || "#";
  }
  renderRaEventRows(events, "", state.raEventDialog.t0TimestampMs);
  openDialog("raEventDialog");
}

function detailExternalLinksMarkup(caseData) {
  const issueUrl = safeUrl(caseData?.voyager_issue_url || caseData?.trail_url);
  const aresUrl = aresStudioUrl(caseData, issueUrl);
  const externalLinks = caseData?.external_links || {};
  const raRecordingUrl = safeUrl(externalLinks.ra_recording_url);
  const raEventUrl = safeUrl(externalLinks.ra_event_url);
  const disableRaSimulationUrl = safeUrl(externalLinks.disable_ra_simulation_url);
  const raEvents = Array.isArray(externalLinks.ra_events) ? externalLinks.ra_events : [];
  const aresLinkMarkup = aresUrl
    ? "<a class=\"detail-id detail-id-link detail-ares-link\" href=\"" + escapeHtml(aresUrl) + "\" target=\"_blank\" rel=\"noreferrer\" title=\"在 Ares Studio 中打开事件前后各 10 秒\">Ares Studio ↗</a>"
    : "";
  const raRecordingLinkMarkup = raRecordingUrl
    ? "<a class=\"detail-id detail-id-link detail-external-link\" href=\"" + escapeHtml(raRecordingUrl) + "\" target=\"_blank\" rel=\"noreferrer\" title=\"打开 RA 录屏" + (externalLinks.ra_task_id ? "：" + escapeHtml(externalLinks.ra_task_id) : "") + "\">RA 录屏 ↗</a>"
    : "";
  const raEventLinkMarkup = raEvents.length
    ? "<button class=\"detail-id detail-id-link detail-external-link detail-inline-button\" type=\"button\" data-open-ra-event aria-keyshortcuts=\"T\" title=\"查看 RA Event（" + raEvents.length + " 条，快捷键 T）\">RA Event · " + raEvents.length + " <kbd class=\"review-control-shortcut detail-external-shortcut\" aria-hidden=\"true\">T</kbd></button>"
    : raEventUrl
      ? "<a class=\"detail-id detail-id-link detail-external-link\" href=\"" + escapeHtml(raEventUrl) + "\" target=\"_blank\" rel=\"noreferrer\" title=\"在 Trail Issue 中查看 RA Event（" + Number(externalLinks.ra_event_count || 0) + " 条）\">RA Event ↗</a>"
      : "";
  const disableRaSimulationLinkMarkup = disableRaSimulationUrl
    ? "<a class=\"detail-id detail-id-link detail-external-link detail-disable-ra-link\" href=\"" + escapeHtml(disableRaSimulationUrl) + "\" target=\"_blank\" rel=\"noreferrer\" title=\"打开屏蔽 RA 指令仿真" + (externalLinks.disable_ra_simulation_task_id ? "：" + escapeHtml(externalLinks.disable_ra_simulation_task_id) : "") + "\">屏蔽 RA ↗</a>"
    : "";
  const pending = caseData?.trail_metadata_status === "pending" && !raRecordingUrl && !raEventUrl && !disableRaSimulationUrl;
  const pendingMarkup = pending
    ? '<span class="detail-external-status" data-trail-metadata-pending>Trail 信息加载中…</span>'
    : "";
  return aresLinkMarkup + raRecordingLinkMarkup + raEventLinkMarkup + disableRaSimulationLinkMarkup + pendingMarkup;
}

function bindDetailExternalLinks(caseData, root = $("#detailExternalLinks") || $("#caseLabelingExternalLinks")) {
  root?.querySelector("[data-open-ra-event]")?.addEventListener("click", () => {
    openRaEventDialog(caseData);
  });
}

function renderDetailExternalLinks(caseData) {
  const root = $("#detailExternalLinks");
  if (!root) return;
  const markup = detailExternalLinksMarkup(caseData);
  root.innerHTML = markup;
  root.hidden = !markup;
  bindDetailExternalLinks(caseData);
}

function startTrailDetailMetadata(issueId, requestSeq, signal = null) {
  // Start this optional remote lookup independently from local media/DB
  // loading.  The caller applies it only after the matching detail DOM exists.
  return api(
    "/api/cases/" + encodeURIComponent(issueId) + "/trail-metadata",
    signal ? { signal } : {}
  ).catch(() => null);
}

function applyTrailDetailMetadata(result, issueId, requestSeq) {
  if (
    requestSeq !== state.caseRequestSeq ||
    state.selectedId !== issueId ||
    !state.selectedCase
  ) {
    return;
  }
  state.selectedCase.external_links = result?.external_links || {};
  state.selectedCase.trail_metadata_status = result?.status || "unavailable";
  const trailShouldExclude = result?.dashboard_should_exclude === true;
  state.selectedCase.trail_should_exclude = trailShouldExclude;
  const excludeInput = $("#reviewExcludeInput");
  const hasCurrentRunReview = reviewAnnotationsForCurrentRun(state.selectedCase).length > 0;
  const hasLocalDraft = Boolean(reviewDraftForCase(state.selectedCase));
  if (excludeInput && excludeInput.dataset?.caseExclusion !== "true" && trailShouldExclude && !hasCurrentRunReview && !hasLocalDraft && !state.reviewFormDirty) {
    // Trail's namespaced info marker is read-only here.  Checking the local
    // box is only a first-Review suggestion. An explicit Review value,
    // including false, is authoritative for its selected Run.
    excludeInput.checked = true;
  }
  renderDetailExternalLinks(state.selectedCase);
}
