/* ra_triage_dashboard/static/js/media-dialog.js
 * Unified media dialog and zoom/pan
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
function mediaFrames(kind) {
  return kind === "bev"
    ? state.media.snapshot?.bev || []
    : state.media.snapshot?.camera || [];
}

function mediaVideo() {
  return state.media.snapshot?.video?.url ? state.media.snapshot.video : null;
}

function preferredMediaKind(caseData) {
  if (caseData?.assets?.video?.url) return "video";
  if (caseData?.assets?.frames?.length) return "bev";
  if (caseData?.camera?.frames?.length) return "camera";
  return "";
}

async function openCaseMediaPreview(issueId, button = null) {
  if (!issueId) return;
  const requestSeq = ++state.media.requestSeq;
  const previousLabel = button?.textContent || "媒体预览";
  if (button) {
    button.disabled = true;
    button.textContent = "加载中…";
  }
  try {
    const caseData = await api(`/api/cases/${encodeURIComponent(issueId)}`);
    if (requestSeq !== state.media.requestSeq) return;
    const kind = preferredMediaKind(caseData);
    if (!kind) {
      showToast(`${issueId} 暂无 BEV、Camera 或视频。`, true);
      return;
    }
    const index = kind === "bev" ? heroFrameIndex(caseData.assets?.frames || []) : 0;
    openMedia(kind, index, { caseData });
  } finally {
    if (button?.isConnected) {
      button.disabled = false;
      button.textContent = previousLabel;
    }
  }
}

function openDialog(id) {
  const dialog = $(`#${id}`);
  if (dialog && !dialog.open) dialog.showModal();
}

function cleanupMediaDialog() {
  const dialog = $("#mediaDialog");
  state.media.drag = null;
  state.media.snapshot = null;
  document.querySelectorAll("#mediaDialog .media-viewport").forEach((viewport) => {
    viewport.classList.remove("is-dragging");
  });
  $("#mediaVideoStage")?.querySelector("video")?.pause();
  if ($("#mediaVideoStage")) {
    $("#mediaVideoStage").innerHTML = "";
    delete $("#mediaVideoStage").dataset.videoUrl;
  }
  dialog?.classList.remove("media-fallback-fullscreen");
  if (document.fullscreenElement && dialog?.contains(document.fullscreenElement)) {
    document.exitFullscreen().catch(() => {});
  }
}

function closeDialog(id) {
  const dialog = $(`#${id}`);
  if (id === "mediaDialog") cleanupMediaDialog();
  if (dialog?.open) dialog.close();
}

function renderSourcePreview(data) {
  const rows = Array.isArray(data?.rows) ? data.rows : [];
  const columns = Array.isArray(data?.columns) ? data.columns : [];
  const metadata = data?.metadata && typeof data.metadata === "object" ? data.metadata : {};
  const rowCount = Number(data?.total_rows || rows.length);
  const page = Number(data?.page || 1);
  const pageCount = Number(data?.page_count || 1);
  const offset = Number(data?.offset || 0);
  state.sourcePreview.page = page;
  state.sourcePreview.pageCount = pageCount;
  $("#sourcePreviewTitle").textContent = data?.filename || "文件预览";
  $("#sourcePreviewMeta").textContent = `${rowCount} 条结果 · 第 ${page} / ${pageCount} 页${data?.reconstructed ? " · Run 重建副本" : ""}`;
  $("#sourcePreviewPageLabel").textContent = `第 ${page} / ${pageCount} 页`;
  $("#sourcePreviewPrevious").disabled = !data?.has_previous;
  $("#sourcePreviewNext").disabled = !data?.has_next;
  const notice = data?.reconstructed
    ? '<div class="source-preview-notice">原始上传文件未归档；当前内容由 Run 中已保存的脱敏预测行重建，仅用于复核。</div>'
    : "";
  const metadataBlock = Object.keys(metadata).length
    ? `<details class="source-preview-metadata"><summary>文件元数据</summary><pre class="source-preview-json">${escapeHtml(JSON.stringify(metadata, null, 2))}</pre></details>`
    : "";
  if (!rows.length || !columns.length) {
    $("#sourcePreviewContent").innerHTML = `${notice}${metadataBlock}<div class="no-asset">文件中没有可展示的结果行。</div>`;
    return;
  }
  const header = columns.map((column) => `<th scope="col">${escapeHtml(column)}</th>`).join("");
  const body = rows
    .map((row, index) => {
      const cells = columns
        .map((column) => `<td>${escapeHtml(row?.[column] ?? "")}</td>`)
        .join("");
      return `<tr><td>${offset + index + 1}</td>${cells}</tr>`;
    })
    .join("");
  $("#sourcePreviewContent").innerHTML = `${notice}${metadataBlock}<table class="source-preview-table"><thead><tr><th scope="col">#</th>${header}</tr></thead><tbody>${body}</tbody></table>`;
}

async function loadSourcePreviewPage(runId, page = 1) {
  const run = state.modelRuns.find((item) => item.id === runId);
  const source = run?.source_file && typeof run.source_file === "object" ? run.source_file : {};
  const previewUrl = safeSameOriginAssetUrl(source.preview_url);
  if (!run || !source.available || !source.preview_supported || !previewUrl) {
    throw new Error("该 Run 没有可用的 CSV / JSON / XLSX 页面预览。");
  }
  const separator = previewUrl.includes("?") ? "&" : "?";
  const data = await api(`${previewUrl}${separator}page=${encodeURIComponent(Math.max(1, page))}&page_size=${state.sourcePreview.pageSize}`);
  state.sourcePreview.runId = runId;
  renderSourcePreview(data);
}

async function openSourcePreview(runId) {
  const run = state.modelRuns.find((item) => item.id === runId);
  const source = run?.source_file && typeof run.source_file === "object" ? run.source_file : {};
  const previewUrl = safeSameOriginAssetUrl(source.preview_url);
  if (!run || !source.available || !source.preview_supported || !previewUrl) {
    showToast("该 Run 没有可用的 CSV / JSON / XLSX 页面预览，请重新上传原文件。", true);
    return;
  }
  $("#sourcePreviewTitle").textContent = source.filename || "文件预览";
  $("#sourcePreviewMeta").textContent = "正在读取…";
  $("#sourcePreviewPageLabel").textContent = "第 1 / … 页";
  $("#sourcePreviewPrevious").disabled = true;
  $("#sourcePreviewNext").disabled = true;
  $("#sourcePreviewContent").innerHTML = '<div class="no-asset">正在生成预览…</div>';
  openDialog("sourcePreviewDialog");
  try {
    state.sourcePreview = { runId, page: 1, pageSize: 100, pageCount: 1 };
    await loadSourcePreviewPage(runId, 1);
  } catch (error) {
    $("#sourcePreviewMeta").textContent = "预览失败";
    $("#sourcePreviewContent").innerHTML = `<div class="no-asset">${escapeHtml(error.message)}</div>`;
  }
}

const MEDIA_ZOOM_MIN = 0.5;
const MEDIA_ZOOM_BASE_MAX = 4;
const MEDIA_ZOOM_STEP = 0.25;

function activeMediaViewport() {
  return state.media.kind === "video"
    ? $("#mediaVideoStage")?.querySelector("[data-video-viewport]")
    : $("#mediaViewport");
}

function activeMediaCanvas() {
  return state.media.kind === "video"
    ? $("#mediaVideoStage")?.querySelector("[data-video-canvas]")
    : $("#mediaCanvas");
}

function activeMediaDimensions() {
  if (state.media.kind === "video") {
    const video = $("#mediaVideoStage")?.querySelector("video");
    return { width: Number(video?.videoWidth || 0), height: Number(video?.videoHeight || 0) };
  }
  const image = $("#mediaPreviewImage");
  return { width: Number(image?.naturalWidth || 0), height: Number(image?.naturalHeight || 0) };
}

function mediaOriginalZoom() {
  const viewport = activeMediaViewport();
  const dimensions = activeMediaDimensions();
  if (!viewport?.clientWidth || !viewport?.clientHeight || !dimensions.width || !dimensions.height) {
    return null;
  }
  const fitScale = Math.min(
    viewport.clientWidth / dimensions.width,
    viewport.clientHeight / dimensions.height
  );
  return fitScale > 0 ? 1 / fitScale : null;
}

function mediaZoomMax() {
  return Math.max(MEDIA_ZOOM_BASE_MAX, mediaOriginalZoom() || 1);
}

function mediaZoomMin() {
  return Math.min(MEDIA_ZOOM_MIN, mediaOriginalZoom() || 1);
}

function updateMediaPanState(viewport = activeMediaViewport()) {
  if (!viewport) return;
  const pannable =
    viewport.scrollWidth > viewport.clientWidth + 1 ||
    viewport.scrollHeight > viewport.clientHeight + 1;
  viewport.classList.toggle("is-pannable", pannable);
  if (!pannable) {
    state.media.drag = null;
    viewport.classList.remove("is-dragging");
  }
}

function mediaFullscreenActive() {
  const dialog = $("#mediaDialog");
  const card = dialog?.querySelector(".media-dialog-card");
  return Boolean(document.fullscreenElement === card || dialog?.classList.contains("media-fallback-fullscreen"));
}

function updateMediaViewControls() {
  const zoom = Math.min(mediaZoomMax(), Math.max(mediaZoomMin(), Number(state.media.zoom) || 1));
  state.media.zoom = zoom;
  $("#mediaZoomResetButton").textContent = `${Math.round(zoom * 100)}%`;
  $("#mediaZoomOutButton").disabled = zoom <= mediaZoomMin();
  $("#mediaZoomInButton").disabled = zoom >= mediaZoomMax();
  const originalZoom = mediaOriginalZoom();
  const originalButton = $("#mediaOriginalSizeButton");
  originalButton.disabled = !originalZoom;
  originalButton.classList.toggle(
    "active",
    Boolean(originalZoom && Math.abs(zoom - originalZoom) < 0.01)
  );
  const dimensions = activeMediaDimensions();
  originalButton.title = originalZoom
    ? `按媒体原始像素 1:1 显示（${dimensions.width} × ${dimensions.height}）`
    : "媒体尺寸读取中";
  const fullscreen = mediaFullscreenActive();
  $("#mediaFullscreenButton").textContent = fullscreen ? "⤢" : "⛶";
  $("#mediaFullscreenButton").setAttribute("aria-label", fullscreen ? "退出全屏" : "进入全屏");
  $("#mediaFullscreenButton").title = fullscreen ? "退出全屏（F）" : "进入全屏（F）";
}

function setMediaZoom(nextZoom, { resetScroll = false } = {}) {
  const viewport = activeMediaViewport();
  const canvas = activeMediaCanvas();
  if (!viewport || !canvas) return;
  const centerRatioX = viewport.scrollWidth > 0
    ? (viewport.scrollLeft + viewport.clientWidth / 2) / viewport.scrollWidth
    : 0.5;
  const centerRatioY = viewport.scrollHeight > 0
    ? (viewport.scrollTop + viewport.clientHeight / 2) / viewport.scrollHeight
    : 0.5;
  state.media.zoom = Math.min(mediaZoomMax(), Math.max(mediaZoomMin(), Number(nextZoom) || 1));
  const size = `${state.media.zoom * 100}%`;
  canvas.style.width = size;
  canvas.style.height = size;
  updateMediaViewControls();
  window.requestAnimationFrame(() => {
    if (resetScroll) {
      viewport.scrollLeft = Math.max(0, (viewport.scrollWidth - viewport.clientWidth) / 2);
      viewport.scrollTop = Math.max(0, (viewport.scrollHeight - viewport.clientHeight) / 2);
      updateMediaPanState();
      return;
    }
    viewport.scrollLeft = Math.max(0, centerRatioX * viewport.scrollWidth - viewport.clientWidth / 2);
    viewport.scrollTop = Math.max(0, centerRatioY * viewport.scrollHeight - viewport.clientHeight / 2);
    updateMediaPanState();
  });
}

function showMediaAtOriginalSize() {
  const originalZoom = mediaOriginalZoom();
  if (!originalZoom) return;
  setMediaZoom(originalZoom, { resetScroll: true });
}

async function toggleMediaFullscreen() {
  const dialog = $("#mediaDialog");
  const card = dialog?.querySelector(".media-dialog-card");
  if (!dialog || !card) return;
  try {
    if (document.fullscreenElement === card) {
      await document.exitFullscreen();
    } else if (document.fullscreenElement) {
      await document.exitFullscreen();
      await card.requestFullscreen();
    } else if (card.requestFullscreen) {
      await card.requestFullscreen();
    } else {
      dialog.classList.toggle("media-fallback-fullscreen");
    }
  } catch (error) {
    showToast(`无法切换全屏：${error.message}`, true);
  }
  updateMediaViewControls();
  window.requestAnimationFrame(updateMediaPanState);
}

function switchMediaKind(kind) {
  const available = kind === "video" ? Boolean(mediaVideo()) : Boolean(mediaFrames(kind).length);
  if (!available) {
      showToast(`${kind === "video" ? "Ares Studio 视频" : `${kind.toUpperCase()} 图片`} 当前不可用。`, true);
    return;
  }
  if (state.media.kind === "video" && kind !== "video") {
    $("#mediaVideoStage")?.querySelector("video")?.pause();
  }
  const currentOffset = state.media.kind === "video"
    ? null
    : Number(mediaFrames(state.media.kind)[state.media.index]?.offset_ms);
  const currentTimepointId = state.media.kind === "video"
    ? ""
    : String(mediaFrames(state.media.kind)[state.media.index]?.timepoint_id || "");
  const nextFrames = kind === "video" ? [] : mediaFrames(kind);
  const exactTimepointIndex = currentTimepointId
    ? nextFrames.findIndex((frame) => String(frame.timepoint_id || "") === currentTimepointId)
    : -1;
  if (state.media.snapshot?.intentPreview && currentTimepointId && exactTimepointIndex < 0) {
    showToast(`当前时间点没有可用的 ${kind === "camera" ? "Camera" : "BEV"} 图片。`, true);
    return;
  }
  state.media.kind = kind;
  state.media.index = exactTimepointIndex >= 0
    ? exactTimepointIndex
    : Number.isFinite(currentOffset) && nextFrames.length
      ? nextFrames.reduce((bestIndex, frame, index) => (
        Math.abs(Number(frame.offset_ms) - currentOffset)
          < Math.abs(Number(nextFrames[bestIndex]?.offset_ms) - currentOffset)
          ? index
          : bestIndex
      ), 0)
      : 0;
  state.media.zoom = 1;
  renderMediaDialog();
}

function cycleIntentMediaKind() {
  if (!state.media.snapshot?.intentPreview) return;
  const alternate = state.media.kind === "camera" ? "bev" : "camera";
  if (mediaFrames(alternate).length) switchMediaKind(alternate);
}

function bindMediaPanViewport(viewport) {
  if (!viewport || viewport.dataset.mediaPanBound === "true") return;
  viewport.dataset.mediaPanBound = "true";
  viewport.addEventListener("pointerdown", (event) => {
    if (
      !viewport.classList.contains("is-pannable") ||
      (event.pointerType === "mouse" && event.button !== 0)
    ) return;
    event.preventDefault();
    state.media.drag = {
      viewport,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      scrollLeft: viewport.scrollLeft,
      scrollTop: viewport.scrollTop,
    };
    viewport.setPointerCapture(event.pointerId);
    viewport.classList.add("is-dragging");
  });
  viewport.addEventListener("pointermove", (event) => {
    const drag = state.media.drag;
    if (!drag || drag.viewport !== viewport || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    viewport.scrollLeft = drag.scrollLeft - (event.clientX - drag.startX);
    viewport.scrollTop = drag.scrollTop - (event.clientY - drag.startY);
  });
  const endDrag = (event) => {
    const drag = state.media.drag;
    if (!drag || drag.viewport !== viewport || drag.pointerId !== event.pointerId) return;
    if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
    state.media.drag = null;
    viewport.classList.remove("is-dragging");
  };
  viewport.addEventListener("pointerup", endDrag);
  viewport.addEventListener("pointercancel", endDrag);
  viewport.addEventListener("wheel", (event) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    setMediaZoom(state.media.zoom + (event.deltaY < 0 ? MEDIA_ZOOM_STEP : -MEDIA_ZOOM_STEP));
  }, { passive: false });
}

function preloadMediaDialogImage(url, onReady) {
  const requestSeq = Number(state.media.imageRequestSeq || 0) + 1;
  state.media.imageRequestSeq = requestSeq;
  const image = new Image();
  image.decoding = "async";
  image.onload = () => {
    let decoded;
    try {
      decoded = typeof image.decode === "function" ? image.decode() : Promise.resolve();
    } catch {
      decoded = Promise.resolve();
    }
    Promise.resolve(decoded).catch(() => {}).then(() => {
      if (requestSeq === state.media.imageRequestSeq) onReady();
    });
  };
  image.onerror = () => {
    if (requestSeq === state.media.imageRequestSeq) showToast("媒体图片加载失败，已保留当前画面。", true);
  };
  image.src = url;
}

function renderMediaDialog() {
  const snapshot = state.media.snapshot;
  const bev = mediaFrames("bev");
  const camera = mediaFrames("camera");
  const video = mediaVideo();
  const availableKinds = [
    bev.length ? "bev" : "",
    camera.length ? "camera" : "",
    video ? "video" : "",
  ].filter(Boolean);
  if (!availableKinds.includes(state.media.kind)) state.media.kind = availableKinds[0] || "bev";
  const videoMode = state.media.kind === "video";
  const gtLabel = snapshot?.gtLabel || "";
  const modelLabel = snapshot?.modelLabel || "";
  const predictionComparable = MODEL_LABELS.includes(modelLabel);
  const predictionMatches = modelLabelMatchesGt(modelLabel, gtLabel);
  const comparisonText = predictionComparable ? (predictionMatches ? "一致" : "不一致") : "未输出";
  const comparisonClass = predictionComparable && !predictionMatches ? "comparison-fail" : "comparison-neutral";
  $("#mediaDecisionSummary").hidden = Boolean(snapshot?.intentPreview);
  $("#mediaDecisionSummary").innerHTML = `
    <span class="comparison-side-label comparison-side-gt">GT</span>${labelBadge(gtLabel, "缺失")}
    <b aria-hidden="true">→</b>
    <span class="comparison-side-label comparison-side-model">模型</span>${labelBadge(modelLabel, "未输出")}
    <strong class="${comparisonClass}">${comparisonText}</strong>`;
  const imageStage = $("#mediaImageStage");
  const videoStage = $("#mediaVideoStage");
  imageStage.hidden = videoMode;
  videoStage.hidden = !videoMode;
  $("#mediaTimeline").hidden = videoMode;
  $("#mediaModeTabs").innerHTML = `
    <button type="button" class="media-mode ${state.media.kind === "bev" ? "active" : ""}" data-media-mode="bev" ${bev.length ? "" : "disabled"}>BEV 图片 <span>${bev.length}</span></button>
    <button type="button" class="media-mode ${state.media.kind === "camera" ? "active" : ""}" data-media-mode="camera" ${camera.length ? "" : "disabled"}>Camera 图片 <span>${camera.length}</span></button>
    <button type="button" class="media-mode ${videoMode ? "active" : ""}" data-media-mode="video" ${video ? "" : "disabled"}>Ares Studio 视频 <span>${video ? "1" : "0"}</span></button>`;
  $("#mediaModeTabs").querySelectorAll("[data-media-mode]").forEach((button) => {
    button.addEventListener("click", () => switchMediaKind(button.dataset.mediaMode));
  });

  if (videoMode && video) {
    state.media.imageRequestSeq += 1;
    if (videoStage.dataset.videoUrl !== video.url) {
      videoStage.dataset.videoUrl = video.url;
      videoStage.innerHTML = videoPlayerMarkup(video);
      bindBevVideoPlayers(videoStage);
      const viewport = videoStage.querySelector("[data-video-viewport]");
      const videoElement = videoStage.querySelector("video");
      bindMediaPanViewport(viewport);
      videoElement.addEventListener("loadedmetadata", () => {
        setMediaZoom(state.media.zoom, { resetScroll: true });
      });
    }
    $("#mediaTitle").textContent = `${snapshot?.issueId || ""} · Ares Studio 视频`;
    $("#mediaTimeline").innerHTML = "";
    $("#mediaHelp").textContent = "← / → 按所选步长跳转 · 空格播放/暂停 · B/C/V 切媒体 · +/− 缩放 · 0 适配 · 放大后拖拽平移 · F 全屏 · Esc 退出";
    setMediaZoom(state.media.zoom, { resetScroll: state.media.zoom === 1 });
    return;
  }

  const frames = mediaFrames(state.media.kind);
  state.media.index = Math.max(0, Math.min(state.media.index, Math.max(frames.length - 1, 0)));
  const current = frames[state.media.index];
  if (!current) return;
  $("#mediaTitle").textContent = `${snapshot?.issueId || ""} · ${frameLabel(current)} · ${state.media.index + 1}/${frames.length}`;
  const previewImage = $("#mediaPreviewImage");
  const targetUrl = String(current.url || "");
  const targetKind = state.media.kind;
  const targetIndex = state.media.index;
  const targetIssueId = String(snapshot?.issueId || "");
  state.media.imageRequestSeq += 1;
  const applyImage = () => {
    if (
      state.media.kind !== targetKind ||
      state.media.index !== targetIndex ||
      String(state.media.snapshot?.issueId || "") !== targetIssueId
    ) return;
    previewImage.src = targetUrl;
    previewImage.alt = `${targetKind} ${frameLabel(current)}`;
    previewImage.dataset.mediaUrl = targetUrl;
    setMediaZoom(state.media.zoom);
  };
  if (previewImage.dataset.mediaUrl === targetUrl) {
    previewImage.alt = `${targetKind} ${frameLabel(current)}`;
    setMediaZoom(state.media.zoom);
  } else if (targetUrl) {
    preloadMediaDialogImage(targetUrl, applyImage);
  }
  $("#mediaHelp").textContent = snapshot?.intentPreview
    ? "← / → 切帧 · Space 同帧轮换 Camera / BEV · B/C 直达媒体 · +/− 缩放 · 0 复位 · F 全屏 · Esc 退出"
    : "← / ↑ 上一帧 · → / ↓ 下一帧 · B/C/V 切媒体 · +/− 缩放 · 0 复位 · 放大后拖拽平移 · F 全屏 · Esc 退出";
  $("#mediaTimeline").innerHTML = mediaTimelineButtonsMarkup(frames, state.media.index, "media-frame");
  $("#mediaTimeline").querySelectorAll("[data-media-frame]").forEach((button) => {
    button.addEventListener("click", () => {
      state.media.index = Number(button.dataset.mediaFrame);
      renderMediaDialog();
    });
  });
}

function openMedia(kind, index, { caseData = state.selectedCase } = {}) {
  const selectedPrediction = (caseData?.predictions || []).find(
    (item) => item.model_run_id === state.selectedRunId
  ) || caseData?.predictions?.[0];
  state.media.snapshot = {
    issueId: String(caseData?.issue_id || ""),
    gtLabel: String(caseData?.gt_label || ""),
    modelLabel: String(selectedPrediction?.model_label || ""),
    intentPreview: Boolean(caseData?.intent_preview),
    bev: [...(caseData?.assets?.frames || [])],
    camera: [...(caseData?.camera?.frames || [])],
    video: caseData?.assets?.video?.url ? { ...caseData.assets.video } : null,
  };
  const requestedAvailable = kind === "video" ? Boolean(mediaVideo()) : Boolean(mediaFrames(kind).length);
  if (!requestedAvailable) kind = preferredMediaKind(caseData);
  if (!kind) return;
  state.media.kind = kind;
  state.media.index = Number.isFinite(Number(index)) ? Number(index) : 0;
  state.media.zoom = 1;
  renderMediaDialog();
  openDialog("mediaDialog");
  setMediaZoom(1, { resetScroll: true });
}

function moveMedia(delta) {
  if (state.media.kind === "video") {
    $("#mediaVideoStage")
      ?.querySelector(`[data-video-jump="${delta < 0 ? -1 : 1}"]`)
      ?.click();
    return;
  }
  const frames = mediaFrames(state.media.kind);
  if (!frames.length) return;
  state.media.index = (state.media.index + delta + frames.length) % frames.length;
  renderMediaDialog();
}
