/* ra_triage_dashboard/static/js/detail-media.js
 * Issue detail media, trail metadata, external links
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */

function heroFrameIndex(frames) {
  const exact = frames.findIndex((frame) => Number(frame.offset_ms ?? frame.offset_sec * 1000) === 0);
  if (exact >= 0) return exact;
  return Math.floor(frames.length / 2);
}

function videoPlayerMarkup(video, { zoomable = true, compact = false } = {}) {
  const durationSec = Math.max(0, Number(video?.duration_ms || 0) / 1000);
  const startOffsetSec = Number(video?.start_offset_sec ?? 0);
  const eventTimeSec = Number(video?.event_time_sec ?? Math.max(0, -startOffsetSec));
  const frameStepSec = Math.max(0.01, Number(video?.frame_step_ms || 100) / 1000);
  const stepOptions = [...new Set([frameStepSec, 0.5, 1, 5])]
    .sort((left, right) => left - right)
    .map((step) => `<option value="${escapeHtml(step)}" ${step === 1 ? "selected" : ""}>${escapeHtml(step)}s${step === frameStepSec ? escapeHtml(t("media.frame_step")) : ""}</option>`)
    .join("");
  const posterUrl = String(video?.poster_url || "").trim();
  const posterAttribute = posterUrl ? ` poster="${escapeHtml(posterUrl)}"` : "";
  const videoMarkup = `<video src="${escapeHtml(video.url)}"${posterAttribute} preload="metadata" playsinline draggable="false" aria-label="Ares Studio BEV 视频"></video>`;
  const mediaMarkup = zoomable
    ? `<div class="media-viewport media-video-viewport" data-video-viewport><div class="media-canvas media-video-canvas" data-video-canvas>${videoMarkup}</div></div>`
    : `<div class="hero-media-button hero-media-video">${videoMarkup}</div>`;
  return `<div class="hero-video-player ${compact ? "is-compact" : ""}" data-bev-video-player
      data-start-offset-sec="${escapeHtml(startOffsetSec)}"
      data-event-time-sec="${escapeHtml(eventTimeSec)}"
      data-duration-sec="${escapeHtml(durationSec)}"
      data-frame-step-sec="${escapeHtml(frameStepSec)}">
    ${mediaMarkup}
    <div class="bev-video-controls" aria-label="BEV 视频控制">
      <div class="bev-video-control-row">
        <button class="button button-quiet" type="button" data-video-play>${escapeHtml(t("media.play"))}</button>
        <button class="button button-quiet" type="button" data-video-jump="-1"><span data-video-jump-label>−1s</span></button>
        <button class="button button-quiet" type="button" data-video-t0>${escapeHtml(t("media.back_t0"))}</button>
        <button class="button button-quiet" type="button" data-video-jump="1"><span data-video-jump-label>+1s</span></button>
        <label>${escapeHtml(t("media.step"))}
          <select data-video-step>
            ${stepOptions}
          </select>
        </label>
        <label>${escapeHtml(t("media.rate"))}
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
        <input data-video-seek type="range" min="0" max="${escapeHtml(durationSec || 40)}" value="0" step="0.01" aria-label="视频进度" />
        <span data-video-time>${escapeHtml(formatSignedSeconds(startOffsetSec))} / ${escapeHtml(formatSignedSeconds(startOffsetSec + durationSec))}</span>
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
  root.querySelectorAll("[data-bev-video-player]").forEach((player) => {
    const video = player.querySelector("video");
    const playButton = player.querySelector("[data-video-play]");
    const seek = player.querySelector("[data-video-seek]");
    const stepSelect = player.querySelector("[data-video-step]");
    const rateSelect = player.querySelector("[data-video-rate]");
    const timeLabel = player.querySelector("[data-video-time]");
    const startLabel = player.querySelector("[data-video-relative-start]");
    const startOffsetSec = Number(player.dataset.startOffsetSec || 0);
    const eventTimeSec = Number(player.dataset.eventTimeSec || 0);
    const configuredDuration = Number(player.dataset.durationSec || 0);
    let seekRequest = 0;
    let cancelPendingSeek = null;
    const duration = () => Number.isFinite(video.duration) ? video.duration : configuredDuration;
    const update = () => {
      const total = Math.max(0, duration());
      seek.max = String(total || configuredDuration || 40);
      seek.value = String(Math.min(Number(seek.max), Math.max(0, video.currentTime || 0)));
      startLabel.textContent = formatSignedSeconds(startOffsetSec);
      timeLabel.textContent = `${formatSignedSeconds(startOffsetSec + (video.currentTime || 0))} / ${formatSignedSeconds(startOffsetSec + total)}`;
      playButton.textContent = video.paused ? t("media.play") : t("media.pause");
    };
    const focusPlayer = () => {
      player.focus({ preventScroll: true });
    };
    const seekTo = (target) => {
      const request = ++seekRequest;
      cancelPendingSeek?.();
      let settled = false;
      let fallbackTimer = null;
      const settle = () => {
        if (settled || request !== seekRequest) return;
        settled = true;
        video.removeEventListener("seeked", settle);
        if (fallbackTimer) window.clearTimeout(fallbackTimer);
        cancelPendingSeek = null;
        update();
        // Some Chromium video decoders update currentTime before the paused
        // frame reaches the compositor.  Waiting for a decoded video frame
        // makes keyboard jumps visibly update the canvas instead of only the
        // progress input.
        if (typeof window.requestAnimationFrame === "function") {
          window.requestAnimationFrame(() => {
            window.requestAnimationFrame(() => {
              if (request === seekRequest) update();
            });
          });
        }
        if (typeof video.requestVideoFrameCallback === "function") {
          video.requestVideoFrameCallback(() => {
            if (request === seekRequest) update();
          });
        }
      };
      cancelPendingSeek = () => {
        video.removeEventListener("seeked", settle);
        if (fallbackTimer) window.clearTimeout(fallbackTimer);
        cancelPendingSeek = null;
      };
      video.addEventListener("seeked", settle);
      video.pause();
      video.currentTime = target;
      update();
      // A remote asset can delay seeked while metadata or the first keyframe
      // is fetched. Keep controls responsive and reconcile once it arrives.
      fallbackTimer = window.setTimeout(settle, 800);
    };
    const jump = (direction) => {
      const step = Math.max(0.01, Number(stepSelect.value || 1));
      const currentTime = Number.isFinite(video.currentTime) ? video.currentTime : 0;
      const target = Math.min(
        Math.max(0, duration()),
        Math.max(0, currentTime + direction * step)
      );
      seekTo(target);
    };
    const togglePlayback = () => {
      if (video.paused) {
        video.play().catch((error) => showToast(t("media.play_fail", { msg: error.message }), true));
      } else {
        video.pause();
      }
    };
    playButton.addEventListener("click", togglePlayback);
    video.addEventListener("click", togglePlayback);
    player.querySelectorAll("[data-video-jump]").forEach((button) => {
      button.addEventListener("click", () => jump(Number(button.dataset.videoJump)));
    });
    player.querySelector("[data-video-t0]").addEventListener("click", () => {
      seekTo(Math.min(Math.max(0, duration()), Math.max(0, eventTimeSec)));
    });
    stepSelect.addEventListener("change", () => {
      const step = Number(stepSelect.value || 1);
      player.querySelectorAll("[data-video-jump]").forEach((button) => {
        const sign = Number(button.dataset.videoJump) < 0 ? "−" : "+";
        button.querySelector("[data-video-jump-label]").textContent = `${sign}${step}s`;
      });
    });
    rateSelect.addEventListener("change", () => {
      video.playbackRate = Number(rateSelect.value || 1);
    });
    seek.addEventListener("input", () => {
      video.currentTime = Number(seek.value || 0);
      update();
    });
    seek.addEventListener("change", () => {
      seekTo(Number(seek.value || 0));
      focusPlayer();
    });
    ["loadedmetadata", "durationchange", "timeupdate", "play", "pause", "ended"].forEach(
      (eventName) => video.addEventListener(eventName, update)
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
      if (event.target.matches("select, input")) {
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
  });
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
  const video = caseData?.assets?.video;
  const camera = caseData?.camera?.frames || [];
  const previewThumbnailUrl = safeSameOriginAssetUrl(caseData?.preview_thumbnail_url);
  if (!frames.length && !camera.length && !video?.url) {
    if (caseData?.media_status === "pending") {
      return `<section class="hero-media"><div class="no-asset hero-media-placeholder detail-media-pending"><span>${escapeHtml(uiText("正在加载 BEV、Camera 与视频…", "Loading BEV, camera, and video…"))}</span></div></section>`;
    }
    return `<section class="hero-media"><div class="no-asset hero-media-placeholder"><span>${escapeHtml(t("media.no_assets"))}</span></div></section>`;
  }
  ensureDetailMediaState(caseData);
  const kind = state.detailMedia.kind;
  const activeFrames = kind === "camera" ? camera : frames;
  const index = Math.max(0, Math.min(
    Number(state.detailMedia.indexes[kind] || 0),
    Math.max(activeFrames.length - 1, 0)
  ));
  if (kind !== "video") state.detailMedia.indexes[kind] = index;
  const frame = activeFrames[index];
  const content = kind === "video" && video?.url
    ? videoPlayerMarkup(video, {
        zoomable: false,
        compact: true,
      })
    : `<button type="button" class="hero-media-button${previewThumbnailUrl ? " has-preview" : ""}" data-detail-media-expand aria-label="展开${kind === "camera" ? " Camera" : " BEV"}媒体预览">
        ${previewThumbnailUrl ? `<img class="detail-media-preview" src="${escapeHtml(previewThumbnailUrl)}" alt="" aria-hidden="true" />` : ""}
        <img class="detail-media-image" src="${escapeHtml(frame?.url || "")}" alt="${kind === "camera" ? "Camera" : "Ares Capture BEV"} ${escapeHtml(frameLabel(frame || {}))}" />
        <span class="hero-media-overlay">${escapeHtml(frameLabel(frame || {}))} · ${t("media.click_expand")}</span>
      </button>`;
  const quickTimeline = kind === "video" ? "" : mediaTimelineMarkup(activeFrames, index, "detail-media-frame");
  const frameControls = kind === "video" ? "" : `
    <div class="detail-media-frame-controls" aria-label="图片帧切换">
      <button class="button button-quiet" id="detailMediaPreviousButton" type="button" aria-label="${escapeHtml(t("media.prev_frame"))}">${escapeHtml(t("media.prev_frame"))}</button>
      <div class="detail-media-frame-center">
        <span class="detail-media-position" id="detailMediaPosition">${activeFrames.length ? `${index + 1} / ${activeFrames.length}` : "—"}</span>
        ${quickTimeline}
      </div>
      <button class="button button-quiet" id="detailMediaNextButton" type="button" aria-label="${escapeHtml(t("media.next_frame"))}">${escapeHtml(t("media.next_frame"))}</button>
    </div>`;
  return `
      <section class="hero-media detail-hero-media" id="detailHeroMedia" tabindex="0" aria-label="Issue 媒体">
      <div class="detail-media-content">${content}</div>
      ${frameControls}
      <p class="detail-media-help">${escapeHtml(kind === "video" ? t("media.help_video") : t("media.help_image"))}</p>
    </section>`;
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
  ];
}

function detailMediaCommandMarkup(caseData) {
  const available = ensureDetailMediaState(caseData);
  const kind = state.detailMedia.kind;
  const options = detailMediaKindOptions(caseData, available);
  const active = options.find((item) => item.value === kind) || options[0];
  return `<div class="detail-media-command" aria-label="详情媒体控制">
    <div class="ui-select detail-media-picker" id="detailMediaKindPicker">
      <button class="ui-select-trigger detail-media-picker-trigger" id="detailMediaKindTrigger" type="button" aria-haspopup="listbox" aria-expanded="false" aria-controls="detailMediaKindPanel" aria-label="媒体类型">
        <span class="ui-select-summary detail-media-picker-summary">${escapeHtml(active?.label || "媒体类型")}</span>
        <span class="ui-select-caret" aria-hidden="true"></span>
      </button>
      <div class="ui-select-panel detail-media-picker-panel" id="detailMediaKindPanel" role="listbox" hidden></div>
      <select class="ui-select-native gateway-model-native-select detail-media-select" id="detailMediaKindSelect" aria-hidden="true" tabindex="-1">
        ${options
          .map(
            (item) =>
              `<option value="${escapeHtml(item.value)}" ${item.disabled ? "disabled" : ""} ${item.value === kind ? "selected" : ""}>${escapeHtml(item.label)}</option>`
          )
          .join("")}
      </select>
    </div>
    <button class="button button-quiet detail-media-expand" id="detailMediaExpandButton" type="button"><span class="ui-lang-zh">展开查看</span><span class="ui-lang-en">Expand</span></button>
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
  const root = $("#detailHeroMedia");
  if (!root) return;
  const focusMediaSurface = () => {
    const surface = $("#detailHeroMedia");
    if (!surface) return;
    surface.focus({ preventScroll: true });
  };
  const render = () => {
    root.outerHTML = heroMediaSection(caseData);
    bindDetailMedia(caseData);
  };
  const switchKind = (kind) => {
    const available = kind === "video"
      ? Boolean(caseData?.assets?.video?.url)
      : Boolean((kind === "camera" ? caseData?.camera?.frames : caseData?.assets?.frames)?.length);
    if (!available || state.detailMedia.kind === kind) return;
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
  const expand = () => openMedia(
    state.detailMedia.kind,
    state.detailMedia.kind === "video" ? 0 : state.detailMedia.indexes[state.detailMedia.kind],
    { caseData }
  );
  const kindSelect = $("#detailMediaKindSelect");
  const kindPicker = $("#detailMediaKindPicker");
  if (kindSelect) {
    kindSelect.value = state.detailMedia.kind;
    kindSelect.onchange = () => {
      const nextKind = kindSelect.value;
      // The media surface owns the B/C/V and arrow shortcuts.  Do not leave
      // focus on the type selector after a choice is made, otherwise
      // ArrowLeft/ArrowRight continue changing this selector instead of
      // stepping frames or jumping the video.
      kindSelect.blur();
      $("#detailMediaKindTrigger")?.blur();
      if (nextKind === state.detailMedia.kind) {
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
      state.detailMedia.kind
    );
    bindUiSelect(kindPicker, { maxHeight: 260, maxWidth: 280 });
  }
  const previousButton = $("#detailMediaPreviousButton");
  const nextButton = $("#detailMediaNextButton");
  const position = $("#detailMediaPosition");
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
  const expandButton = $("#detailMediaExpandButton");
  if (expandButton) expandButton.onclick = expand;
  root.querySelectorAll("[data-detail-media-expand]").forEach((button) => button.addEventListener("click", expand));
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
  const isModel = kind === "model";
  const predictions = caseData.predictions || [];
  const annotations = isModel
    ? []
    : typeof reviewAnnotationsForAllRuns === "function"
      ? reviewAnnotationsForAllRuns(caseData)
      : (caseData.annotations || []);
  $("#historyDialogTitle").textContent = isModel
    ? uiText("评测 Run 输出历史", "Model run history")
    : uiText("Review 历史", "Review history");
  $("#historyDialogMeta").textContent = isModel
    ? uiText(
        `${predictions.length} 个模型 Run · 当前 Review Run 会高亮`,
        `${predictions.length} model runs · current review run is highlighted`
      )
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
    : annotationHistory(annotations);
  if (!isModel) bindAnnotationHistory($("#historyDialogContent"), caseData);
  openDialog("historyDialog");
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

function renderRaEventRows(events, query = "") {
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
          <td>${escapeHtml(formatRaEventTimestamp(timestamp))}</td>
        </tr>`;
      })
      .join("");
  }
  const empty = $("#raEventEmpty");
  if (empty) empty.hidden = rows.length > 0;
  return rows.length;
}

function openRaEventDialog(caseData) {
  if (!caseData) return;
  const externalLinks = caseData.external_links || {};
  const events = Array.isArray(externalLinks.ra_events) ? externalLinks.ra_events : [];
  state.raEventDialog = {
    issueId: String(caseData.issue_id || ""),
    events,
    trailUrl: safeUrl(externalLinks.ra_event_url),
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
  renderRaEventRows(events);
  openDialog("raEventDialog");
}

function detailExternalLinksMarkup(caseData) {
  const issueUrl = safeUrl(caseData?.voyager_issue_url || caseData?.trail_url);
  const aresUrl = aresStudioUrl(caseData, issueUrl);
  const externalLinks = caseData?.external_links || {};
  const raRecordingUrl = safeUrl(externalLinks.ra_recording_url);
  const raEventUrl = safeUrl(externalLinks.ra_event_url);
  const raEvents = Array.isArray(externalLinks.ra_events) ? externalLinks.ra_events : [];
  const aresLinkMarkup = aresUrl
    ? "<a class=\"detail-id detail-id-link detail-ares-link\" href=\"" + escapeHtml(aresUrl) + "\" target=\"_blank\" rel=\"noreferrer\" title=\"在 Ares Studio 中打开事件前后各 10 秒\">Ares Studio ↗</a>"
    : "";
  const raRecordingLinkMarkup = raRecordingUrl
    ? "<a class=\"detail-id detail-id-link detail-external-link\" href=\"" + escapeHtml(raRecordingUrl) + "\" target=\"_blank\" rel=\"noreferrer\" title=\"打开 RA 录屏" + (externalLinks.ra_task_id ? "：" + escapeHtml(externalLinks.ra_task_id) : "") + "\">RA 录屏 ↗</a>"
    : "";
  const raEventLinkMarkup = raEvents.length
    ? "<button class=\"detail-id detail-id-link detail-external-link detail-inline-button\" type=\"button\" data-open-ra-event title=\"查看 RA Event（" + raEvents.length + " 条）\">RA Event · " + raEvents.length + "</button>"
    : raEventUrl
      ? "<a class=\"detail-id detail-id-link detail-external-link\" href=\"" + escapeHtml(raEventUrl) + "\" target=\"_blank\" rel=\"noreferrer\" title=\"在 Trail Issue 中查看 RA Event（" + Number(externalLinks.ra_event_count || 0) + " 条）\">RA Event ↗</a>"
      : "";
  const pending = caseData?.trail_metadata_status === "pending" && !raRecordingUrl && !raEventUrl;
  const pendingMarkup = pending
    ? '<span class="detail-external-status" data-trail-metadata-pending>Trail 信息加载中…</span>'
    : "";
  return aresLinkMarkup + raRecordingLinkMarkup + raEventLinkMarkup + pendingMarkup;
}

function bindDetailExternalLinks(caseData) {
  const root = $("#detailExternalLinks");
  root?.querySelector("[data-open-ra-event]")?.addEventListener("click", () => {
    openRaEventDialog(caseData);
  });
}

function renderDetailExternalLinks(caseData) {
  const root = $("#detailExternalLinks");
  if (!root) return;
  root.innerHTML = detailExternalLinksMarkup(caseData);
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
  if (excludeInput && trailShouldExclude && !hasCurrentRunReview && !hasLocalDraft && !state.reviewFormDirty) {
    // Trail's namespaced info marker is read-only here.  Checking the local
    // box is only a first-Review suggestion. An explicit Review value,
    // including false, is authoritative for its selected Run.
    excludeInput.checked = true;
  }
  renderDetailExternalLinks(state.selectedCase);
}
