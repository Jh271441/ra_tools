/* detail-media.js
 * Issue BEV/Camera frame rendering, timeline and deferred-media hydration.
 * Classic script; shared globals are initialized before bind-bootstrap.js.
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
    if (document.activeElement?.closest?.(
      "#reviewPane .review-dropdown[open], #caseLabelingEditor .review-dropdown[open]"
    )) return;
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
      state.detailMedia.preferredVideoTrack = track.url;
      if (!isCameraVideoTrack(track)) state.detailMedia.preferredBevVideoTrack = track.url;
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
    pauseBevVideoPlayers(root);
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
