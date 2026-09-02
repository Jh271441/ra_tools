/* Routing / ego lane-change labeling. This state is intentionally isolated
 * from the three-class Review form and its media dialog. */

const INTENT_ROUTING_LABELS = {
  left_turn: "左转",
  right_turn: "右转",
  straight: "直行",
  u_turn: "掉头",
  parking: "泊车",
};
const INTENT_LANE_LABELS = {
  no_lane_change: "非变道",
  lane_change: "变道",
};
const INTENT_MODE_DIGIT_LABELS = {
  routing: {
    Digit1: "left_turn",
    Digit2: "right_turn",
    Digit3: "straight",
    Digit4: "u_turn",
    Digit5: "parking",
  },
  laneChange: {
    Digit1: "no_lane_change",
    Digit2: "lane_change",
  },
};

function intentRouteOptions(overrides = {}) {
  const intent = state.intentLabeling;
  const active = (intent.caseData?.timepoints || []).find(
    (item) => item.id === intent.activeTimepointId
  );
  return {
    datasetId: overrides.datasetId ?? intent.datasetId,
    caseId: overrides.caseId ?? intent.caseId,
    offsetMs: overrides.offsetMs ?? active?.offset_ms ?? null,
  };
}

function intentTimeLabel(offsetMs) {
  const value = Number(offsetMs) || 0;
  if (value % 1000 === 0) return `${value >= 0 ? "+" : ""}${value / 1000}s`;
  return `${value >= 0 ? "+" : ""}${value}ms`;
}

function intentActiveTimepoint() {
  return (state.intentLabeling.caseData?.timepoints || []).find(
    (item) => item.id === state.intentLabeling.activeTimepointId
  ) || null;
}

function intentOverride(timepointId = state.intentLabeling.activeTimepointId) {
  return state.intentLabeling.overrides[timepointId] || null;
}

function intentEffective(timepoint = intentActiveTimepoint()) {
  const intent = state.intentLabeling;
  const override = timepoint ? intentOverride(timepoint.id) : null;
  return {
    routing: override?.routing_intent || intent.aggregate.routing || "",
    laneChange: override?.lane_change_intent || intent.aggregate.laneChange || "",
  };
}

function intentLabelSummary(timepoint) {
  const effective = intentEffective(timepoint);
  const routing = INTENT_ROUTING_LABELS[effective.routing] || "Routing 待填";
  const laneChange = INTENT_LANE_LABELS[effective.laneChange] || "变道待填";
  return `${routing} · ${laneChange}`;
}

function renderIntentDatasetPicker() {
  const select = $("#intentDatasetSelect");
  if (!select) return;
  select.innerHTML = state.intentLabeling.datasets.map((item) => (
    `<option value="${escapeHtml(item.id)}"${item.id === state.intentLabeling.datasetId ? " selected" : ""}${item.available ? "" : " disabled"}>${escapeHtml(item.display_name)}</option>`
  )).join("");
}

function intentSetSaveState(text, kind = "") {
  const element = $("#intentSaveState");
  if (!element) return;
  element.textContent = text;
  element.dataset.status = kind;
}

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
  if (!image || !missing) return;
  intentPrepareMediaZoom(kind, descriptor);
  if (!descriptor?.url) {
    image.removeAttribute("src");
    image.hidden = true;
    missing.hidden = false;
    return;
  }
  const probe = new Image();
  probe.src = descriptor.url;
  const ready = typeof probe.decode === "function"
    ? probe.decode().catch(() => undefined)
    : Promise.resolve();
  ready.then(() => {
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
  intentSetImage("camera", $("#intentCameraImage"), $("#intentCameraMissing"), active?.camera, sequence);
  intentSetImage("bev", $("#intentBevImage"), $("#intentBevMissing"), active?.bev, sequence);
}

function renderIntentTimeline() {
  const timeline = $("#intentTimeline");
  if (!timeline) return;
  const intent = state.intentLabeling;
  const timepoints = intent.caseData?.timepoints || [];
  timeline.innerHTML = timepoints.map((item) => {
    const override = intentOverride(item.id);
    const camera = item.camera?.thumbnail_url;
    const bev = item.bev?.thumbnail_url;
    return `<button class="intent-timepoint${item.id === intent.activeTimepointId ? " active" : ""}" type="button" data-intent-timepoint="${escapeHtml(item.id)}" aria-label="切换到 ${escapeHtml(intentTimeLabel(item.offset_ms))}">
      <strong>${escapeHtml(intentTimeLabel(item.offset_ms))}</strong>
      <span class="intent-thumb-stack">
        ${camera ? `<img data-intent-lazy-src="${escapeHtml(camera)}" alt=""/>` : '<span class="intent-thumb-missing">Camera 缺失</span>'}
        ${bev ? `<img data-intent-lazy-src="${escapeHtml(bev)}" alt=""/>` : '<span class="intent-thumb-missing">BEV 缺失</span>'}
      </span>
      <small class="${override ? "is-override" : ""}">${escapeHtml(intentLabelSummary(item))}</small>
    </button>`;
  }).join("");
  timeline.querySelectorAll("[data-intent-timepoint]").forEach((button) => {
    button.addEventListener("click", () => intentSelectTimepoint(button.dataset.intentTimepoint));
  });
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
    }, { root: timeline, rootMargin: "240px" });
    timeline.querySelectorAll("img[data-intent-lazy-src]").forEach((image) => {
      state.intentLabeling.thumbnailObserver.observe(image);
    });
  } else {
    timeline.querySelectorAll("img[data-intent-lazy-src]").forEach((image) => {
      image.src = image.dataset.intentLazySrc;
    });
  }
  timeline.querySelector(".intent-timepoint.active")?.scrollIntoView({ block: "nearest", inline: "center" });
}

function renderIntentLabels() {
  const intent = state.intentLabeling;
  const currentOverride = intentOverride();
  const effective = intentEffective();
  document.querySelectorAll("[data-intent-axis-mode]").forEach((button) => {
    const selected = button.dataset.intentAxisMode === intent.activeAxis;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", selected ? "true" : "false");
  });
  document.querySelectorAll("[data-intent-axis-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.intentAxisPanel !== intent.activeAxis;
  });
  document.querySelectorAll("[data-intent-aggregate-axis]").forEach((button) => {
    const value = button.dataset.value;
    const selected = button.dataset.intentAggregateAxis === "routing"
      ? intent.aggregate.routing === value
      : intent.aggregate.laneChange === value;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", selected ? "true" : "false");
  });
  document.querySelectorAll("[data-intent-frame-axis]").forEach((button) => {
    const value = button.dataset.value;
    const selected = button.dataset.intentFrameAxis === "routing"
      ? effective.routing === value
      : effective.laneChange === value;
    button.classList.toggle("active", selected);
    button.classList.toggle("is-override", Boolean(
      selected && (button.dataset.intentFrameAxis === "routing"
        ? currentOverride?.routing_intent
        : currentOverride?.lane_change_intent)
    ));
    button.setAttribute("aria-pressed", selected ? "true" : "false");
  });
  document.querySelectorAll("[data-intent-frame-source]").forEach((source) => {
    const key = source.dataset.intentFrameSource === "routing"
      ? "routing_intent"
      : "lane_change_intent";
    source.textContent = currentOverride?.[key] ? "已单独修改" : "来自批量预填";
  });
  const total = intent.caseData?.timepoints?.length || 0;
  const overrideKey = intent.activeAxis === "routing" ? "routing_intent" : "lane_change_intent";
  const overrideCount = Object.values(intent.overrides).filter((item) => item?.[overrideKey]).length;
  $("#intentCoverage").textContent = `${Math.max(0, total - overrideCount)} 帧使用批量预填 · ${overrideCount} 帧单独修改`;
}

function intentSetActiveAxis(axis) {
  if (!INTENT_MODE_DIGIT_LABELS[axis]) return;
  state.intentLabeling.activeAxis = axis;
  renderIntentLabels();
}

function renderIntentCase() {
  const intent = state.intentLabeling;
  const data = intent.caseData;
  renderIntentDatasetPicker();
  if (!data) return;
  $("#intentCaseInput").value = data.issue_id;
  $("#intentPreviousCase").disabled = !data.previous_case_id;
  $("#intentNextCase").disabled = !data.next_case_id;
  const select = $("#intentTimepointSelect");
  select.innerHTML = data.timepoints.map((item, index) => (
    `<option value="${escapeHtml(item.id)}"${item.id === intent.activeTimepointId ? " selected" : ""}>${index + 1} / ${data.timepoints.length} · ${escapeHtml(intentTimeLabel(item.offset_ms))}</option>`
  )).join("");
  renderIntentHero();
  renderIntentTimeline();
  renderIntentLabels();
}

async function loadIntentLabeling({ datasetId = "", caseId = "", offsetMs = null, historyMode = "replace" } = {}) {
  const intent = state.intentLabeling;
  const requestSeq = ++intent.requestSeq;
  if (!intent.datasets.length) {
    const payload = await api("/api/intent-datasets");
    if (requestSeq !== intent.requestSeq) return;
    intent.datasets = payload.items || [];
  }
  const selectedDataset = intent.datasets.find((item) => item.id === datasetId && item.available)
    || intent.datasets.find((item) => item.id === intent.datasetId && item.available)
    || intent.datasets.find((item) => item.available);
  if (!selectedDataset) {
    renderIntentDatasetPicker();
    intentSetSaveState("数据集媒体尚未挂载", "error");
    return;
  }
  intent.datasetId = selectedDataset.id;
  let targetCaseId = caseId;
  if (targetCaseId && !/^cn[0-9]+_[0-9]+$/.test(targetCaseId)) {
    if (!/^cn[0-9]+$/.test(targetCaseId)) throw new Error("请输入完整的 Issue ID，例如 cn28896325。");
    const matches = await api(`/api/intent-datasets/${encodeURIComponent(intent.datasetId)}/cases?q=${encodeURIComponent(targetCaseId)}&page_size=200`);
    if (requestSeq !== intent.requestSeq) return;
    const exact = (matches.items || []).filter((item) => item.issue_id === targetCaseId);
    if (exact.length !== 1) throw new Error(exact.length ? "该 Issue 对应多个 Episode，无法唯一打开。" : "该数据集中没有这个 Issue。");
    targetCaseId = exact[0].case_id;
  }
  if (!targetCaseId) {
    const pending = await api(`/api/intent-datasets/${encodeURIComponent(intent.datasetId)}/cases?status=unlabeled&page_size=1`);
    const fallback = pending.items?.length
      ? pending
      : await api(`/api/intent-datasets/${encodeURIComponent(intent.datasetId)}/cases?status=all&page_size=1`);
    targetCaseId = fallback.items?.[0]?.case_id || "";
  }
  if (!targetCaseId) throw new Error("数据集中没有可标注 Case。");
  const data = await api(`/api/intent-datasets/${encodeURIComponent(intent.datasetId)}/cases/${encodeURIComponent(targetCaseId)}`);
  if (requestSeq !== intent.requestSeq) return;
  intent.caseId = data.case_id;
  intent.caseData = data;
  intent.revisionId = data.labels?.revision_id || null;
  intent.aggregate = {
    routing: data.labels?.routing_default || "",
    laneChange: data.labels?.lane_change_default || "",
  };
  intent.overrides = Object.fromEntries((data.labels?.overrides || []).map((item) => [item.timepoint_id, { ...item }]));
  intent.dirty = false;
  intent.editVersion = 0;
  const targetOffset = Number(offsetMs);
  const active = Number.isFinite(targetOffset)
    ? data.timepoints.find((item) => item.offset_ms === targetOffset)
    : null;
  intent.activeTimepointId = (active
    || data.timepoints.reduce((best, item) => !best || Math.abs(item.offset_ms) < Math.abs(best.offset_ms) ? item : best, null)
  )?.id || "";
  renderIntentCase();
  intentSetSaveState(intent.revisionId ? "已自动保存" : "尚未标注", intent.revisionId ? "saved" : "");
  if (state.activePage === "intent" && historyMode) {
    const route = pageUrl("intent", intentRouteOptions());
    const historyState = { page: "intent", datasetId: intent.datasetId, caseId: intent.caseId };
    if (historyMode === "push") history.pushState(historyState, "", route);
    else history.replaceState(historyState, "", route);
  }
}

function intentMarkDirty() {
  const intent = state.intentLabeling;
  intent.dirty = true;
  intent.editVersion += 1;
  intentSetSaveState("等待自动保存…", "dirty");
  window.clearTimeout(intent.saveTimer);
  intent.saveTimer = window.setTimeout(() => {
    intentFlushSave().catch((error) => showToast(error.message, true));
  }, 600);
}

function intentOverridesPayload() {
  return Object.values(state.intentLabeling.overrides).map((item) => ({
    timepoint_id: item.timepoint_id,
    offset_ms: item.offset_ms,
    routing_intent: item.routing_intent || "",
    lane_change_intent: item.lane_change_intent || "",
  }));
}

async function intentFlushSave() {
  const intent = state.intentLabeling;
  window.clearTimeout(intent.saveTimer);
  if (intent.savePromise) {
    await intent.savePromise;
    return intent.dirty ? intentFlushSave() : null;
  }
  if (!intent.dirty || !intent.caseId) return null;
  const savedEditVersion = intent.editVersion;
  intent.dirty = false;
  intent.saving = true;
  intentSetSaveState("正在保存…", "saving");
  intent.savePromise = api(
    `/api/intent-datasets/${encodeURIComponent(intent.datasetId)}/cases/${encodeURIComponent(intent.caseId)}/labels`,
    {
      method: "PUT",
      body: JSON.stringify({
        expected_revision_id: intent.revisionId,
        routing_default: intent.aggregate.routing,
        lane_change_default: intent.aggregate.laneChange,
        overrides: intentOverridesPayload(),
        author: state.session.username || "",
      }),
    }
  ).then((payload) => {
    intent.revisionId = payload.labels?.revision_id || null;
    if (intent.editVersion === savedEditVersion) {
      intent.overrides = Object.fromEntries((payload.labels?.overrides || []).map((item) => [item.timepoint_id, { ...item }]));
      intentSetSaveState("已自动保存", "saved");
      renderIntentTimeline();
      renderIntentLabels();
    } else {
      intent.dirty = true;
      intentSetSaveState("等待自动保存…", "dirty");
    }
    return payload;
  }).catch((error) => {
    intent.dirty = true;
    intentSetSaveState("保存失败", "error");
    throw error;
  }).finally(() => {
    intent.saving = false;
    intent.savePromise = null;
  });
  const result = await intent.savePromise;
  if (intent.dirty) return intentFlushSave();
  return result;
}

function intentSetAggregate(axis, value) {
  const intent = state.intentLabeling;
  const key = axis === "routing" ? "routing_intent" : "lane_change_intent";
  if (axis === "routing") intent.aggregate.routing = value;
  else intent.aggregate.laneChange = value;
  Object.entries(intent.overrides).forEach(([timepointId, override]) => {
    if (override[key] === value) delete override[key];
    if (!override.routing_intent && !override.lane_change_intent) delete intent.overrides[timepointId];
  });
  intentMarkDirty();
  renderIntentLabels();
  renderIntentTimeline();
}

function intentSetFrameLabel(axis, value) {
  const intent = state.intentLabeling;
  const active = intentActiveTimepoint();
  if (!active) return;
  const override = { ...(intentOverride(active.id) || {}), timepoint_id: active.id, offset_ms: active.offset_ms };
  const aggregateValue = axis === "routing" ? intent.aggregate.routing : intent.aggregate.laneChange;
  const key = axis === "routing" ? "routing_intent" : "lane_change_intent";
  if (value === aggregateValue) delete override[key];
  else override[key] = value;
  if (!override.routing_intent && !override.lane_change_intent) delete intent.overrides[active.id];
  else intent.overrides[active.id] = override;
  intentMarkDirty();
  renderIntentLabels();
  renderIntentTimeline();
}

function intentRestoreBatchPrefill(axis = state.intentLabeling.activeAxis) {
  const id = state.intentLabeling.activeTimepointId;
  const override = state.intentLabeling.overrides[id];
  if (!id || !override) return;
  if (axis === "routing") delete override.routing_intent;
  else delete override.lane_change_intent;
  if (!override.routing_intent && !override.lane_change_intent) {
    delete state.intentLabeling.overrides[id];
  }
  intentMarkDirty();
  renderIntentLabels();
  renderIntentTimeline();
}

function intentSelectTimepoint(timepointId, { updateRoute = true } = {}) {
  const intent = state.intentLabeling;
  if (!(intent.caseData?.timepoints || []).some((item) => item.id === timepointId)) return;
  intent.activeTimepointId = timepointId;
  renderIntentCase();
  if (updateRoute && state.activePage === "intent") {
    history.replaceState({ page: "intent", caseId: intent.caseId }, "", pageUrl("intent", intentRouteOptions()));
  }
}

function intentMoveFrame(delta) {
  const items = state.intentLabeling.caseData?.timepoints || [];
  const index = items.findIndex((item) => item.id === state.intentLabeling.activeTimepointId);
  if (index < 0 || !items.length) return;
  intentSelectTimepoint(items[Math.max(0, Math.min(items.length - 1, index + delta))].id);
}

async function intentNavigateCase(direction) {
  await intentFlushSave();
  const data = state.intentLabeling.caseData;
  const caseId = direction < 0 ? data?.previous_case_id : data?.next_case_id;
  if (!caseId) return;
  await loadIntentLabeling({ datasetId: state.intentLabeling.datasetId, caseId, historyMode: "push" });
}

function intentPreviewFrames(kind) {
  const descriptorKey = kind === "camera" ? "camera" : "bev";
  return (state.intentLabeling.caseData?.timepoints || []).flatMap((timepoint) => {
    const descriptor = timepoint?.[descriptorKey];
    if (!descriptor?.url) return [];
    return [{ ...descriptor, offset_ms: timepoint.offset_ms, timepoint_id: timepoint.id }];
  });
}

function openIntentMedia(kind) {
  const frames = intentPreviewFrames(kind);
  const active = intentActiveTimepoint();
  if (!frames.length) {
    showToast(`当前 Issue 没有可用的 ${kind === "camera" ? "Camera" : "BEV"} 图片。`, true);
    return;
  }
  const exactIndex = frames.findIndex((frame) => frame.timepoint_id === active?.id);
  const index = exactIndex >= 0
    ? exactIndex
    : frames.reduce((bestIndex, frame, frameIndex) => (
      Math.abs(Number(frame.offset_ms) - Number(active?.offset_ms || 0))
        < Math.abs(Number(frames[bestIndex]?.offset_ms) - Number(active?.offset_ms || 0))
        ? frameIndex
        : bestIndex
    ), 0);
  const data = state.intentLabeling.caseData;
  openMedia(kind, index, {
    caseData: {
      issue_id: data?.issue_id || "",
      intent_preview: true,
      assets: { frames: intentPreviewFrames("bev") },
      camera: { frames: intentPreviewFrames("camera") },
      predictions: [],
    },
  });
}

function intentShortcutIsEditable(target) {
  return Boolean(target?.closest?.("input, textarea, select, button, [contenteditable='true'], dialog[open]"));
}

function handleIntentShortcut(event) {
  if (state.activePage !== "intent" || event.isComposing || event.repeat) return;
  if (event.ctrlKey || event.metaKey || event.altKey || intentShortcutIsEditable(event.target)) return;
  const axis = state.intentLabeling.activeAxis;
  const value = INTENT_MODE_DIGIT_LABELS[axis]?.[event.code];
  if (value) {
    event.preventDefault();
    event.stopPropagation();
    if (event.shiftKey) intentSetAggregate(axis, value);
    else intentSetFrameLabel(axis, value);
    return;
  }
  if (event.shiftKey) return;
  const actions = {
    ArrowUp: () => intentNavigateCase(-1),
    ArrowDown: () => intentNavigateCase(1),
    ArrowLeft: () => intentMoveFrame(-1),
    ArrowRight: () => intentMoveFrame(1),
    KeyB: () => openIntentMedia("bev"),
    KeyC: () => openIntentMedia("camera"),
    Digit0: () => intentRestoreBatchPrefill(),
    Space: () => openIntentMedia(intentActiveTimepoint()?.camera?.url ? "camera" : "bev"),
  };
  const action = actions[event.code];
  if (!action) return;
  event.preventDefault();
  event.stopPropagation();
  Promise.resolve(action()).catch((error) => showToast(error.message, true));
}

function bindIntentLabelingEvents() {
  $("#intentDatasetSelect")?.addEventListener("change", async (event) => {
    await intentFlushSave();
    await loadIntentLabeling({ datasetId: event.target.value, historyMode: "push" });
  });
  $("#intentLoadCaseButton")?.addEventListener("click", () => {
    (async () => {
      await intentFlushSave();
      await loadIntentLabeling({
        datasetId: state.intentLabeling.datasetId,
        caseId: $("#intentCaseInput")?.value.trim() || "",
        historyMode: "push",
      });
    })().catch((error) => showToast(error.message, true));
  });
  $("#intentCaseInput")?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    $("#intentLoadCaseButton")?.click();
  });
  $("#intentTimepointSelect")?.addEventListener("change", (event) => intentSelectTimepoint(event.target.value));
  $("#intentPreviousFrame")?.addEventListener("click", () => intentMoveFrame(-1));
  $("#intentNextFrame")?.addEventListener("click", () => intentMoveFrame(1));
  $("#intentPreviousCase")?.addEventListener("click", () => intentNavigateCase(-1).catch((error) => showToast(error.message, true)));
  $("#intentNextCase")?.addEventListener("click", () => intentNavigateCase(1).catch((error) => showToast(error.message, true)));
  $("#intentRestoreBatchPrefill")?.addEventListener("click", () => intentRestoreBatchPrefill());
  document.querySelectorAll("[data-intent-axis-mode]").forEach((button) => {
    button.addEventListener("click", () => intentSetActiveAxis(button.dataset.intentAxisMode));
  });
  document.querySelectorAll("[data-intent-open-media]").forEach((button) => {
    button.addEventListener("click", () => openIntentMedia(button.dataset.intentOpenMedia));
  });
  document.querySelectorAll("[data-intent-media-controls]").forEach((controls) => {
    controls.addEventListener("click", (event) => {
      const button = event.target.closest("[data-intent-media-zoom]");
      if (!button) return;
      const kind = controls.dataset.intentMediaControls;
      const current = intentMediaTransform(kind)?.scale || 1;
      if (button.dataset.intentMediaZoom === "reset") intentResetMediaZoom(kind);
      else intentSetMediaZoom(kind, current + (button.dataset.intentMediaZoom === "in" ? .2 : -.2));
    });
  });
  document.querySelectorAll("[data-intent-media-stage]").forEach((stage) => {
    const kind = stage.dataset.intentMediaStage;
    let drag = null;
    stage.addEventListener("pointerdown", (event) => {
      const transform = intentMediaTransform(kind);
      if (event.target.tagName !== "IMG" || !transform || transform.scale <= 1) return;
      drag = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, startX: transform.x, startY: transform.y };
      stage.setPointerCapture(event.pointerId);
      stage.classList.add("is-dragging");
      event.preventDefault();
    });
    stage.addEventListener("pointermove", (event) => {
      if (!drag || drag.pointerId !== event.pointerId) return;
      const transform = intentMediaTransform(kind);
      transform.x = drag.startX + event.clientX - drag.x;
      transform.y = drag.startY + event.clientY - drag.y;
      intentApplyMediaTransform(kind);
    });
    const stopDrag = (event) => {
      if (!drag || drag.pointerId !== event.pointerId) return;
      drag = null;
      stage.classList.remove("is-dragging");
    };
    stage.addEventListener("pointerup", stopDrag);
    stage.addEventListener("pointercancel", stopDrag);
    stage.addEventListener("wheel", (event) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      const current = intentMediaTransform(kind)?.scale || 1;
      intentSetMediaZoom(kind, current + (event.deltaY < 0 ? .2 : -.2));
    }, { passive: false });
  });
  document.querySelectorAll("[data-intent-aggregate-axis]").forEach((button) => {
    button.addEventListener("click", () => intentSetAggregate(button.dataset.intentAggregateAxis, button.dataset.value));
  });
  document.querySelectorAll("[data-intent-frame-axis]").forEach((button) => {
    button.addEventListener("click", () => intentSetFrameLabel(button.dataset.intentFrameAxis, button.dataset.value));
  });
  document.addEventListener("keydown", handleIntentShortcut, true);
}
