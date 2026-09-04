function intentMediaTransform(kind) {
  return state.intentLabeling.mediaZoom[kind];
}

function intentApplyMediaTransform(kind) {
  const transform = intentMediaTransform(kind);
  const stage = document.querySelector(`[data-intent-media-stage="${kind}"]`);
  const image = kind === "camera" ? $("#intentCameraImage") : $("#intentBevImage");
  const level = kind === "camera" ? $("#intentCameraZoomLevel") : $("#intentBevZoomLevel");
  if (!transform || !stage || !image || !level) return;
  const maxX = stage.clientWidth * (transform.scale - 1) / 2;
  const maxY = stage.clientHeight * (transform.scale - 1) / 2;
  transform.x = Math.max(-maxX, Math.min(maxX, transform.x));
  transform.y = Math.max(-maxY, Math.min(maxY, transform.y));
  image.style.transform = `translate3d(${transform.x}px, ${transform.y}px, 0) scale(${transform.scale})`;
  stage.classList.toggle("is-zoomed", transform.scale > 1);
  level.textContent = `${Math.round(transform.scale * 100)}%`;
}

function intentResetMediaZoom(kind, source = intentMediaTransform(kind)?.source || "") {
  const transform = intentMediaTransform(kind);
  if (!transform) return;
  Object.assign(transform, { scale: 1, x: 0, y: 0, source });
  intentApplyMediaTransform(kind);
}

function intentSetMediaZoom(kind, scale) {
  const transform = intentMediaTransform(kind);
  if (!transform) return;
  transform.scale = Math.max(1, Math.min(4, Math.round(scale * 10) / 10));
  if (transform.scale === 1) {
    transform.x = 0;
    transform.y = 0;
  }
  intentApplyMediaTransform(kind);
}

function intentPrepareMediaZoom(kind, descriptor) {
  const source = descriptor?.url || "";
  const transform = intentMediaTransform(kind);
  if (transform && transform.source !== source) intentResetMediaZoom(kind, source);
  const controls = document.querySelector(`[data-intent-media-controls="${kind}"]`);
  if (controls) controls.dataset.available = source ? "true" : "false";
}

function intentSetImage(kind, image, missing, descriptor, sequence) {
  if (!image || !missing) return Promise.resolve();
  intentPrepareMediaZoom(kind, descriptor);
  if (!descriptor?.url) {
    image.removeAttribute("src");
    image.hidden = true;
    missing.hidden = false;
    return Promise.resolve();
  }
  const probe = new Image();
  probe.decoding = "async";
  probe.fetchPriority = "high";
  probe.src = descriptor.url;
  const ready = typeof probe.decode === "function"
    ? probe.decode().catch(() => undefined)
    : Promise.resolve();
  return ready.then(() => {
    if (sequence !== state.intentLabeling.mediaSeq) return;
    if (!probe.naturalWidth) {
      image.removeAttribute("src");
      image.hidden = true;
      missing.hidden = false;
      return;
    }
    image.src = descriptor.url;
    image.hidden = false;
    missing.hidden = true;
    intentApplyMediaTransform(kind);
  });
}

function renderIntentHero() {
  const intent = state.intentLabeling;
  const active = intentActiveTimepoint();
  $("#intentCameraDelta").textContent = active?.camera_delta_ms == null
    ? ""
    : `Δ ${active.camera_delta_ms >= 0 ? "+" : ""}${active.camera_delta_ms} ms`;
  const sequence = ++intent.mediaSeq;
  return Promise.all([
    intentSetImage("camera", $("#intentCameraImage"), $("#intentCameraMissing"), active?.camera, sequence),
    intentSetImage("bev", $("#intentBevImage"), $("#intentBevMissing"), active?.bev, sequence),
  ]);
}

function activateIntentTimelineThumbnails(timeline = $("#intentTimeline")) {
  if (!timeline) return;
  state.intentLabeling.thumbnailObserver?.disconnect();
  if ("IntersectionObserver" in window) {
    state.intentLabeling.thumbnailObserver = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const image = entry.target;
        image.src = image.dataset.intentLazySrc;
        delete image.dataset.intentLazySrc;
        state.intentLabeling.thumbnailObserver?.unobserve(image);
      }
    }, { root: timeline, rootMargin: "48px" });
    timeline.querySelectorAll("img[data-intent-lazy-src]").forEach((image) => {
      state.intentLabeling.thumbnailObserver.observe(image);
    });
  } else {
    timeline.querySelectorAll("img[data-intent-lazy-src]").forEach((image) => {
      image.src = image.dataset.intentLazySrc;
      delete image.dataset.intentLazySrc;
    });
  }
}

function renderIntentTimeline({ loadThumbnails = true } = {}) {
  const timeline = $("#intentTimeline");
  if (!timeline) return;
  state.intentLabeling.thumbnailObserver?.disconnect();
  const intent = state.intentLabeling;
  const timepoints = intent.caseData?.timepoints || [];
  timeline.innerHTML = timepoints.map((item) => {
    const camera = item.camera?.thumbnail_url;
    const bev = item.bev?.thumbnail_url;
    const selected = (intent.selectedTimepointIds || []).includes(item.id);
    return `<button class="intent-timepoint${selected ? " selected" : ""}${item.id === intent.activeTimepointId ? " active" : ""}" type="button" data-intent-timepoint="${escapeHtml(item.id)}" aria-label="切换到 ${escapeHtml(intentTimeLabel(item.offset_ms))}" aria-pressed="${selected ? "true" : "false"}">
      <strong>${escapeHtml(intentTimeLabel(item.offset_ms))}</strong>
      <span class="intent-thumb-stack">
        ${camera ? `<img data-intent-lazy-src="${escapeHtml(camera)}" loading="lazy" decoding="async" alt=""/>` : '<span class="intent-thumb-missing">Camera 缺失</span>'}
        ${bev ? `<img data-intent-lazy-src="${escapeHtml(bev)}" loading="lazy" decoding="async" alt=""/>` : '<span class="intent-thumb-missing">BEV 缺失</span>'}
      </span>
      ${intentTimepointLabelMarkup(item)}
    </button>`;
  }).join("");
  timeline.querySelectorAll("[data-intent-timepoint]").forEach((button) => {
    button.addEventListener("click", (event) => {
      intentSelectTimepoint(button.dataset.intentTimepoint, { extendSelection: event.shiftKey });
      // The timeline cards are buttons for accessibility, but keeping focus on
      // one makes the page-level Ctrl/Shift/arrow shortcuts look disabled.
      button.blur();
    });
  });
  if (loadThumbnails) activateIntentTimelineThumbnails(timeline);
  timeline.querySelector(".intent-timepoint.active")?.scrollIntoView({ block: "nearest", inline: "center" });
}

function updateIntentTimelineState({ scroll = true } = {}) {
  const intent = state.intentLabeling;
  const selected = new Set(intent.selectedTimepointIds || []);
  const byId = new Map((intent.caseData?.timepoints || []).map((item) => [item.id, item]));
  $("#intentTimeline")?.querySelectorAll("[data-intent-timepoint]").forEach((button) => {
    const timepointId = button.dataset.intentTimepoint;
    const isSelected = selected.has(timepointId);
    const isActive = timepointId === intent.activeTimepointId;
    button.classList.toggle("selected", isSelected);
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", isSelected ? "true" : "false");
    const labels = button.querySelector(".intent-timepoint-labels");
    const timepoint = byId.get(timepointId);
    if (labels && timepoint) {
      labels.outerHTML = intentTimepointLabelMarkup(timepoint);
    }
  });
  if (scroll) {
    $("#intentTimeline")?.querySelector(".intent-timepoint.active")
      ?.scrollIntoView({ block: "nearest", inline: "center" });
  }
}

function updateIntentFrameNavigation() {
  const intent = state.intentLabeling;
  const items = intent.caseData?.timepoints || [];
  const index = items.findIndex((item) => item.id === intent.activeTimepointId);
  const select = $("#intentTimepointSelect");
  if (select) select.value = intent.activeTimepointId;
  const ordinal = $("#intentFrameOrdinalInput");
  if (ordinal) {
    ordinal.value = index >= 0 ? String(index + 1) : "";
    ordinal.max = String(Math.max(1, items.length));
  }
  if ($("#intentFrameCount")) $("#intentFrameCount").textContent = String(items.length || "—");
  if ($("#intentPreviousFrame")) $("#intentPreviousFrame").disabled = index <= 0;
  if ($("#intentNextFrame")) $("#intentNextFrame").disabled = index < 0 || index >= items.length - 1;
}

function renderIntentActiveFrame() {
  updateIntentFrameNavigation();
  renderIntentHero();
  renderIntentLabels();
  renderIntentCollaboration();
  updateIntentTimelineState();
}

