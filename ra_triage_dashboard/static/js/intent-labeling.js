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
const INTENT_DIGIT_LABELS = {
  Digit1: ["routing", "left_turn"],
  Digit2: ["routing", "right_turn"],
  Digit3: ["routing", "straight"],
  Digit4: ["routing", "u_turn"],
  Digit5: ["routing", "parking"],
  Digit6: ["laneChange", "no_lane_change"],
  Digit7: ["laneChange", "lane_change"],
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

function intentSetImage(image, missing, descriptor, sequence) {
  if (!image || !missing) return;
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
    image.src = descriptor.url;
    image.hidden = false;
    missing.hidden = true;
  });
}

function renderIntentHero() {
  const intent = state.intentLabeling;
  const timepoints = intent.caseData?.timepoints || [];
  const active = intentActiveTimepoint();
  const index = active ? timepoints.findIndex((item) => item.id === active.id) : -1;
  $("#intentMediaHeading").textContent = active
    ? `同步媒体 · 第 ${index + 1} / ${timepoints.length} 帧 · t = ${active.offset_ms} ms`
    : "同步媒体";
  $("#intentCameraDelta").textContent = active?.camera_delta_ms == null
    ? ""
    : `Δ ${active.camera_delta_ms >= 0 ? "+" : ""}${active.camera_delta_ms} ms`;
  const sequence = ++intent.mediaSeq;
  intentSetImage($("#intentCameraImage"), $("#intentCameraMissing"), active?.camera, sequence);
  intentSetImage($("#intentBevImage"), $("#intentBevMissing"), active?.bev, sequence);
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
      <small class="${override ? "is-override" : ""}">${override ? "覆盖" : "继承"}</small>
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
  $("#intentFrameInheritance").textContent = currentOverride
    ? "含单帧覆盖"
    : "继承 Case 聚合";
  const total = intent.caseData?.timepoints?.length || 0;
  const overrideCount = Object.keys(intent.overrides).length;
  $("#intentCoverage").textContent = `${Math.max(0, total - overrideCount)} 帧继承 · ${overrideCount} 帧覆盖`;
}

function renderIntentCase() {
  const intent = state.intentLabeling;
  const data = intent.caseData;
  renderIntentDatasetPicker();
  if (!data) return;
  $("#intentCaseInput").value = data.case_id;
  $("#intentCaseId").textContent = data.case_id;
  $("#intentSceneSet").textContent = intent.datasets.find((item) => item.id === intent.datasetId)?.scene_set || "—";
  $("#intentFrameCount").textContent = `${data.timepoints.length} / ${data.timepoints.length}`;
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
  if (axis === "routing") state.intentLabeling.aggregate.routing = value;
  else state.intentLabeling.aggregate.laneChange = value;
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

function intentRestoreInheritance() {
  const id = state.intentLabeling.activeTimepointId;
  if (!id || !state.intentLabeling.overrides[id]) return;
  delete state.intentLabeling.overrides[id];
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

function intentShortcutIsEditable(target) {
  return Boolean(target?.closest?.("input, textarea, select, button, [contenteditable='true'], dialog[open]"));
}

function handleIntentShortcut(event) {
  if (state.activePage !== "intent" || event.isComposing || event.repeat) return;
  if (event.ctrlKey || event.metaKey || event.altKey || intentShortcutIsEditable(event.target)) return;
  const digit = INTENT_DIGIT_LABELS[event.code];
  if (digit) {
    event.preventDefault();
    event.stopPropagation();
    if (event.shiftKey) intentSetAggregate(digit[0], digit[1]);
    else intentSetFrameLabel(digit[0], digit[1]);
    return;
  }
  if (event.shiftKey) return;
  const actions = {
    ArrowLeft: () => intentMoveFrame(-1),
    ArrowRight: () => intentMoveFrame(1),
    BracketLeft: () => intentNavigateCase(-1),
    BracketRight: () => intentNavigateCase(1),
    Digit0: () => intentRestoreInheritance(),
    Space: async () => { await intentFlushSave(); await intentNavigateCase(1); },
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
  $("#intentLoadCaseButton")?.addEventListener("click", async () => {
    await intentFlushSave();
    await loadIntentLabeling({
      datasetId: state.intentLabeling.datasetId,
      caseId: $("#intentCaseInput")?.value.trim() || "",
      historyMode: "push",
    });
  });
  $("#intentTimepointSelect")?.addEventListener("change", (event) => intentSelectTimepoint(event.target.value));
  $("#intentPreviousFrame")?.addEventListener("click", () => intentMoveFrame(-1));
  $("#intentNextFrame")?.addEventListener("click", () => intentMoveFrame(1));
  $("#intentPreviousCase")?.addEventListener("click", () => intentNavigateCase(-1).catch((error) => showToast(error.message, true)));
  $("#intentNextCase")?.addEventListener("click", () => intentNavigateCase(1).catch((error) => showToast(error.message, true)));
  $("#intentRestoreInheritance")?.addEventListener("click", intentRestoreInheritance);
  document.querySelectorAll("[data-intent-aggregate-axis]").forEach((button) => {
    button.addEventListener("click", () => intentSetAggregate(button.dataset.intentAggregateAxis, button.dataset.value));
  });
  document.querySelectorAll("[data-intent-frame-axis]").forEach((button) => {
    button.addEventListener("click", () => intentSetFrameLabel(button.dataset.intentFrameAxis, button.dataset.value));
  });
  document.addEventListener("keydown", handleIntentShortcut, true);
}
