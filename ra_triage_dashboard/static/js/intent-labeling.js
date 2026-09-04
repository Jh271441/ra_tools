async function loadIntentLabeling({ datasetId = "", datasetIds = null, caseId = "", offsetMs = null, assignees = null, experimentId = null, historyMode = "replace" } = {}) {
  const intent = state.intentLabeling;
  restoreIntentWorkspacePreferences();
  const requestSeq = ++intent.requestSeq;
  if (!intent.datasets.length) {
    const payload = await api("/api/intent-datasets");
    if (requestSeq !== intent.requestSeq) return;
    intent.datasets = payload.items || [];
  }
  const available = intent.datasets.filter((item) => item.available);
  let scopeIds = parseFilterList(datasetIds == null ? intent.selectedDatasetIds : datasetIds)
    .filter((id) => available.some((item) => item.id === id));
  if (!scopeIds.length && datasetId && available.some((item) => item.id === datasetId)) scopeIds = [datasetId];
  if (!scopeIds.length && intent.datasetId && available.some((item) => item.id === intent.datasetId)) scopeIds = [intent.datasetId];
  if (!scopeIds.length && available[0]) scopeIds = [available[0].id];
  let selectedDataset = available.find((item) => item.id === datasetId && scopeIds.includes(item.id))
    || available.find((item) => item.id === intent.datasetId && scopeIds.includes(item.id))
    || available.find((item) => scopeIds.includes(item.id));
  if (!selectedDataset) {
    renderIntentTopbarDatasetPicker("");
    intentSetSaveState("数据集媒体尚未挂载", "error");
    return;
  }
  const previousScopeKey = (intent.selectedDatasetIds || []).join(",");
  const scopeChanged = previousScopeKey && previousScopeKey !== scopeIds.join(",");
  intent.datasetId = selectedDataset.id;
  intent.selectedDatasetIds = scopeIds;
  renderIntentTopbarDatasetPicker(scopeIds);
  if (scopeChanged) {
    intent.selectedAssignees = [];
    intent.assigneeDatasetId = "";
    intent.selectedExperimentId = "";
  }
  await loadIntentAssignees(scopeIds, assignees, experimentId);
  if (requestSeq !== intent.requestSeq) return;
  const assigneeParams = intentAssigneeSearchParams();
  const queueParams = new URLSearchParams(assigneeParams);
  scopeIds.forEach((id) => queueParams.append("dataset_id", id));
  queueParams.set("status", "all");
  queueParams.set("page_size", "200");
  let targetCaseId = caseId;
  if (targetCaseId && !/^cn[0-9]+(?:_[0-9]+)?$/.test(targetCaseId)) {
    throw new Error("请输入完整的 Issue ID，例如 cn28896325。");
  }
  if (targetCaseId) queueParams.set("q", targetCaseId);
  else queueParams.set("page_size", "1");
  const queue = await api(intentApiUrl("/api/intent-cases", queueParams));
  if (requestSeq !== intent.requestSeq) return;
  let queueItem = null;
  if (/^cn[0-9]+_[0-9]+$/.test(targetCaseId)) {
    const exact = (queue.items || []).filter((item) => item.case_id === targetCaseId);
    queueItem = exact.find((item) => item.dataset_id === selectedDataset.id) || exact[0] || null;
  } else if (targetCaseId) {
    const exact = (queue.items || []).filter((item) => item.issue_id === targetCaseId);
    if (exact.length !== 1) throw new Error(exact.length ? "该 Issue 对应多个数据集或 Episode，无法唯一打开。" : "所选数据集中没有这个 Issue。");
    queueItem = exact[0];
  } else {
    queueItem = queue.items?.[0] || null;
  }
  targetCaseId = queueItem?.case_id || "";
  if (!targetCaseId) throw new Error("数据集中没有可标注 Case。");
  selectedDataset = available.find((item) => item.id === queueItem.dataset_id) || selectedDataset;
  intent.datasetId = selectedDataset.id;
  const data = await api(intentApiUrl(`/api/intent-datasets/${encodeURIComponent(intent.datasetId)}/cases/${encodeURIComponent(targetCaseId)}`, assigneeParams));
  if (requestSeq !== intent.requestSeq) return;
  data.ordinal = queueItem.ordinal;
  data.case_count = queue.scope_total;
  data.previous_case = queueItem.previous;
  data.next_case = queueItem.next;
  intent.caseId = data.case_id;
  intent.caseData = data;
  intent.adminRevealAnswers = false;
  intent.revisionId = data.labels?.revision_id || null;
  intent.aggregate = {
    routing: data.labels?.routing_default || "",
    laneChange: data.labels?.lane_change_default || "",
  };
  intent.overrides = Object.fromEntries((data.labels?.overrides || []).map((item) => [item.timepoint_id, { ...item }]));
  intent.undoStack = [];
  intent.dirty = false;
  intent.editVersion = 0;
  const hasTargetOffset = offsetMs !== null && offsetMs !== undefined && offsetMs !== "";
  const targetOffset = Number(offsetMs);
  const active = hasTargetOffset && Number.isFinite(targetOffset)
    ? data.timepoints.find((item) => item.offset_ms === targetOffset)
    : null;
  intent.activeTimepointId = (active
    || data.timepoints[0]
  )?.id || "";
  intent.selectedTimepointIds = intent.activeTimepointId ? [intent.activeTimepointId] : [];
  intent.selectionAnchorId = intent.activeTimepointId;
  persistIntentWorkspacePreferences();
  renderIntentCase({ deferTimelineThumbnails: true });
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
    acknowledgeLocalChange(payload);
    intent.revisionId = payload.labels?.revision_id || null;
    if (intent.editVersion === savedEditVersion) {
      const shouldAutoAdvance = Boolean(
        intent.autoAdvanceOnSave
        && intent.autoAdvanceTimepointId
        && intent.activeTimepointId === intent.autoAdvanceTimepointId
      );
      intent.autoAdvanceOnSave = false;
      intent.autoAdvanceTimepointId = "";
      intent.overrides = Object.fromEntries((payload.labels?.overrides || []).map((item) => [item.timepoint_id, { ...item }]));
      intentSetSaveState("已自动保存", "saved");
      updateIntentTimelineState({ scroll: false });
      renderIntentLabels();
      const username = String(state.session.username || "").toLowerCase();
      intent.caseData.collaboration ||= { contributors: [], comments: [] };
      const contributors = intent.caseData.collaboration.contributors ||= [];
      let current = contributors.find((item) => item.is_current || item.username === username);
      if (!current) {
        current = { username, is_current: true };
        contributors.push(current);
      }
      Object.assign(current, {
        username,
        is_current: true,
        revealed: true,
        labeled: true,
        completed: intentLabelsComplete(
          payload.labels?.routing_default,
          payload.labels?.lane_change_default,
        ),
        routing_default: payload.labels?.routing_default || "",
        lane_change_default: payload.labels?.lane_change_default || "",
        overrides: payload.labels?.overrides || [],
        frame_counts: intentLocalFrameCounts(),
        updated_at: payload.labels?.created_at || "",
      });
      renderIntentCollaboration();
      if (shouldAutoAdvance) {
        intentMoveFrame(1);
      }
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

function intentEditSnapshot() {
  const intent = state.intentLabeling;
  return {
    aggregate: { ...intent.aggregate },
    overrides: Object.fromEntries(
      Object.entries(intent.overrides).map(([timepointId, override]) => [timepointId, { ...override }])
    ),
  };
}

function intentSnapshotKey(snapshot) {
  return JSON.stringify({
    aggregate: snapshot.aggregate,
    overrides: Object.keys(snapshot.overrides).sort().map((key) => [key, snapshot.overrides[key]]),
  });
}

function intentCommitEdit(previous) {
  const intent = state.intentLabeling;
  if (intentSnapshotKey(previous) === intentSnapshotKey(intentEditSnapshot())) return false;
  intent.undoStack.push(previous);
  if (intent.undoStack.length > 100) intent.undoStack.shift();
  intentMarkDirty();
  renderIntentLabels();
  updateIntentTimelineState({ scroll: false });
  return true;
}

function intentUndo() {
  const intent = state.intentLabeling;
  const previous = intent.undoStack.pop();
  if (!previous) {
    showToast("当前 Case 没有可撤销的标注操作。", false);
    return;
  }
  intent.aggregate = { ...previous.aggregate };
  intent.overrides = Object.fromEntries(
    Object.entries(previous.overrides).map(([timepointId, override]) => [timepointId, { ...override }])
  );
  intentMarkDirty();
  renderIntentLabels();
  updateIntentTimelineState({ scroll: false });
  showToast("已撤销上一次标注操作，正在自动保存。", false);
}

function intentQueueAutoAdvance(selectedCount = 0) {
  const intent = state.intentLabeling;
  const active = intentActiveTimepoint();
  const effective = active ? intentEffective(active) : {};
  if (
    selectedCount === 1
    && active
    && intentLabelsComplete(effective.routing, effective.laneChange)
  ) {
    intent.autoAdvanceOnSave = true;
    intent.autoAdvanceTimepointId = active.id;
  }
}

function intentSetAggregate(axis, value) {
  if (!intentAxisEnabled(axis)) return;
  const intent = state.intentLabeling;
  const previous = intentEditSnapshot();
  const key = axis === "routing" ? "routing_intent" : "lane_change_intent";
  if (axis === "routing") intent.aggregate.routing = value;
  else intent.aggregate.laneChange = value;
  Object.entries(intent.overrides).forEach(([timepointId, override]) => {
    if (override[key] === value) delete override[key];
    if (!override.routing_intent && !override.lane_change_intent) delete intent.overrides[timepointId];
  });
  // Batch prefill changes the whole Case; auto-advance is reserved for a
  // completed current-frame edit so a Shift+number action never jumps away
  // from the frame the annotator is reviewing.
  intentCommitEdit(previous);
}

function intentSetFrameLabel(axis, value) {
  if (!intentAxisEnabled(axis)) return;
  const intent = state.intentLabeling;
  const selected = intentSelectedTimepoints();
  if (!selected.length) return;
  const previous = intentEditSnapshot();
  const aggregateValue = axis === "routing" ? intent.aggregate.routing : intent.aggregate.laneChange;
  const key = axis === "routing" ? "routing_intent" : "lane_change_intent";
  selected.forEach((timepoint) => {
    const override = { ...(intentOverride(timepoint.id) || {}), timepoint_id: timepoint.id, offset_ms: timepoint.offset_ms };
    if (value === aggregateValue) delete override[key];
    else override[key] = value;
    if (!override.routing_intent && !override.lane_change_intent) delete intent.overrides[timepoint.id];
    else intent.overrides[timepoint.id] = override;
  });
  if (intentCommitEdit(previous)) {
    intentQueueAutoAdvance(selected.length);
  }
}

function intentRestoreBatchPrefill() {
  const intent = state.intentLabeling;
  const selected = intentSelectedTimepoints();
  const changed = selected.some((timepoint) => {
    const override = intent.overrides[timepoint.id];
    return Boolean(
      (intentAxisEnabled("routing") && override?.routing_intent)
      || (intentAxisEnabled("laneChange") && override?.lane_change_intent)
    );
  });
  if (!changed) return;
  const previous = intentEditSnapshot();
  selected.forEach((timepoint) => {
    const override = intent.overrides[timepoint.id];
    if (!override) return;
    if (intentAxisEnabled("routing")) delete override.routing_intent;
    if (intentAxisEnabled("laneChange")) delete override.lane_change_intent;
    if (!override.routing_intent && !override.lane_change_intent) delete intent.overrides[timepoint.id];
  });
  intentCommitEdit(previous);
}

function intentSelectTimepoint(timepointId, { updateRoute = true, extendSelection = false } = {}) {
  const intent = state.intentLabeling;
  if (!(intent.caseData?.timepoints || []).some((item) => item.id === timepointId)) return;
  if (!extendSelection && intent.activeTimepointId === timepointId
      && intent.selectedTimepointIds?.length === 1 && intent.selectedTimepointIds[0] === timepointId) return;
  if (extendSelection) {
    const anchorId = intent.selectionAnchorId || intent.activeTimepointId || timepointId;
    intent.selectionAnchorId = anchorId;
    intent.selectedTimepointIds = intentSelectionRange(anchorId, timepointId);
  } else {
    intent.selectionAnchorId = timepointId;
    intent.selectedTimepointIds = [timepointId];
  }
  if (intent.activeTimepointId !== timepointId) {
    intent.autoAdvanceOnSave = false;
    intent.autoAdvanceTimepointId = "";
  }
  intent.activeTimepointId = timepointId;
  renderIntentActiveFrame();
  if (updateRoute && state.activePage === "intent") {
    history.replaceState({ page: "intent", caseId: intent.caseId }, "", pageUrl("intent", intentRouteOptions()));
  }
}

function intentMoveFrame(delta, { extendSelection = false, toBoundary = false } = {}) {
  const items = state.intentLabeling.caseData?.timepoints || [];
  const index = items.findIndex((item) => item.id === state.intentLabeling.activeTimepointId);
  if (index < 0 || !items.length) return;
  const targetIndex = toBoundary
    ? (delta < 0 ? 0 : items.length - 1)
    : Math.max(0, Math.min(items.length - 1, index + delta));
  intentSelectTimepoint(items[targetIndex].id, { extendSelection });
}

async function intentNavigateCase(direction) {
  await intentFlushSave();
  const data = state.intentLabeling.caseData;
  const target = direction < 0 ? data?.previous_case : data?.next_case;
  if (!target?.case_id) return;
  await loadIntentLabeling({
    datasetId: target.dataset_id,
    datasetIds: state.intentLabeling.selectedDatasetIds,
    caseId: target.case_id,
    assignees: state.intentLabeling.selectedAssignees,
    historyMode: "push",
  });
}

async function intentJumpToCaseOrdinal(rawValue) {
  const intent = state.intentLabeling;
  const total = Number(intent.caseData?.case_count) || 0;
  if (!total) return;
  const ordinal = Math.max(1, Math.min(total, Math.trunc(Number(rawValue) || 1)));
  if (ordinal === Number(intent.caseData?.ordinal)) {
    $("#intentCaseOrdinalInput").value = String(ordinal);
    return;
  }
  await intentFlushSave();
  const params = intentAssigneeSearchParams();
  (intent.selectedDatasetIds || []).forEach((id) => params.append("dataset_id", id));
  params.set("status", "all");
  params.set("page_size", "1");
  params.set("page", String(ordinal));
  const payload = await api(intentApiUrl("/api/intent-cases", params));
  const target = payload.items?.[0];
  if (!target?.case_id) throw new Error(`找不到第 ${ordinal} 个 Issue。`);
  await loadIntentLabeling({
    datasetId: target.dataset_id,
    datasetIds: intent.selectedDatasetIds,
    caseId: target.case_id,
    assignees: intent.selectedAssignees,
    historyMode: "push",
  });
}

function intentJumpToFrameOrdinal(rawValue) {
  const items = state.intentLabeling.caseData?.timepoints || [];
  if (!items.length) return;
  const ordinal = Math.max(1, Math.min(items.length, Math.trunc(Number(rawValue) || 1)));
  $("#intentFrameOrdinalInput").value = String(ordinal);
  intentSelectTimepoint(items[ordinal - 1].id);
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
  return Boolean(
    document.querySelector("dialog[open]") ||
    target?.closest?.("input, textarea, select, [contenteditable='true'], [role='textbox']")
  );
}

function handleIntentShortcut(event) {
  if (state.activePage !== "intent" || event.isComposing) return;
  if (event.altKey || intentShortcutIsEditable(event.target)) return;
  const boundaryModifier = event.ctrlKey || event.metaKey;
  if (boundaryModifier && !event.shiftKey && event.code === "KeyZ") {
    event.preventDefault();
    event.stopPropagation();
    intentUndo();
    return;
  }
  const digit = INTENT_DIGIT_LABELS[event.code];
  if (digit) {
    if (event.repeat || !intentAxisEnabled(digit[0])) return;
    if (boundaryModifier) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.shiftKey) intentSetAggregate(digit[0], digit[1]);
    else intentSetFrameLabel(digit[0], digit[1]);
    return;
  }
  if (event.code === "ArrowLeft" || event.code === "ArrowRight") {
    event.preventDefault();
    event.stopPropagation();
    intentMoveFrame(event.code === "ArrowLeft" ? -1 : 1, {
      extendSelection: event.shiftKey,
      toBoundary: boundaryModifier,
    });
    return;
  }
  if (event.repeat) return;
  if (event.shiftKey || boundaryModifier) return;
  const actions = {
    ArrowUp: () => intentNavigateCase(-1),
    ArrowDown: () => intentNavigateCase(1),
    KeyB: () => openIntentMedia("bev"),
    KeyC: () => openIntentMedia("camera"),
    KeyD: () => openIntentComments(),
    Digit0: () => intentRestoreBatchPrefill(),
    Space: () => openIntentMedia(intentActiveTimepoint()?.camera?.url ? "camera" : "bev"),
  };
  const action = actions[event.code];
  if (!action) return;
  event.preventDefault();
  event.stopPropagation();
  Promise.resolve(action()).catch((error) => showToast(error.message, true));
}

function downloadIntentExport(view) {
  if (!state.session.is_admin) return;
  let datasetIds = parseFilterList(
    state.intentLabeling.summaryDatasetIds?.length
      ? state.intentLabeling.summaryDatasetIds
      : (state.intentLabeling.summaryDatasetId || state.intentLabeling.datasetId)
  );
  if (!datasetIds.length) return;
  const params = new URLSearchParams({ view, include_incomplete: "true" });
  const experimentId = state.intentLabeling.summaryExperimentId || "";
  if (experimentId) {
    const experiment = (state.intentLabeling.summaryPayload?.experiments || [])
      .find((item) => item.id === experimentId);
    if (experiment?.dataset_id) datasetIds = [experiment.dataset_id];
    params.set("experiment_id", experimentId);
  }
  datasetIds.forEach((datasetId) => {
    const link = document.createElement("a");
    link.href = withBase(`/api/intent-datasets/${encodeURIComponent(datasetId)}/export?${params}`);
    link.download = "";
    document.body.appendChild(link);
    link.click();
    link.remove();
  });
}

function closeIntentContributorMenus() {
  document.querySelectorAll(".intent-contributor-menu").forEach((menu) => {
    menu.classList.remove("is-open");
    const trigger = menu.querySelector("[data-intent-contributor-menu]");
    const panel = menu.querySelector(".intent-contributor-menu-panel");
    if (trigger) trigger.setAttribute("aria-expanded", "false");
    if (panel) panel.hidden = true;
  });
}

function bindIntentLabelingEvents() {
  $("#intentOpenComments")?.addEventListener("click", () => {
    Promise.resolve(openIntentComments()).catch((error) => showToast(error.message, true));
  });
  $("#intentContributorList")?.addEventListener("click", (event) => {
    const menuButton = event.target.closest("[data-intent-contributor-menu]");
    if (menuButton) {
      event.preventDefault();
      event.stopPropagation();
      const menu = menuButton.closest(".intent-contributor-menu");
      const panel = menu?.querySelector(".intent-contributor-menu-panel");
      const willOpen = Boolean(panel?.hidden);
      closeIntentContributorMenus();
      if (willOpen && menu && panel) {
        menu.classList.add("is-open");
        menuButton.setAttribute("aria-expanded", "true");
        panel.hidden = false;
      }
      return;
    }
    if (!event.target.closest("[data-intent-delete-mine]")) return;
    closeIntentContributorMenus();
    deleteMyIntentLabel().catch((error) => showToast(error.message, true));
  });
  document.addEventListener("click", (event) => {
    if (event.target.closest(".intent-contributor-menu")) return;
    closeIntentContributorMenus();
  });
  $("#intentTimeline")?.addEventListener("wheel", (event) => {
    const timeline = event.currentTarget;
    if (event.ctrlKey || event.metaKey || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return;
    event.preventDefault();
    timeline.scrollLeft += event.deltaY;
  }, { passive: false });
  $("#intentExperimentForm")?.addEventListener("submit", (event) => {
    createIntentExperiment(event).catch((error) => showToast(error.message, true));
  });
  $("#intentExperimentEditForm")?.addEventListener("submit", (event) => {
    updateIntentExperiment(event).catch((error) => showToast(error.message, true));
  });
  $("#intentSummaryAxis")?.addEventListener("change", (event) => {
    state.intentLabeling.summaryAxis = event.target.value || "all";
    state.intentLabeling.summaryPage = 1;
    persistIntentWorkspacePreferences();
    loadIntentSummary({ datasetIds: state.intentLabeling.summaryDatasetIds, force: true }).catch((error) => showToast(error.message, true));
  });
  $("#intentSummaryPageSize")?.addEventListener("change", (event) => {
    const nextSize = Number(event.target.value);
    state.intentLabeling.summaryPageSize = [10, 20, 50, 100].includes(nextSize) ? nextSize : 20;
    state.intentLabeling.summaryPage = 1;
    persistIntentWorkspacePreferences();
    loadIntentSummary({ datasetIds: state.intentLabeling.summaryDatasetIds, force: true }).catch((error) => showToast(error.message, true));
  });
  $("#intentSummaryPageJumpButton")?.addEventListener("click", jumpIntentSummaryPage);
  $("#intentSummaryPageJump")?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    jumpIntentSummaryPage();
  });
  $("#intentSummaryRefresh")?.addEventListener("click", () => loadIntentSummary({ datasetIds: state.intentLabeling.summaryDatasetIds, force: true }).catch((error) => showToast(error.message, true)));
  $("#intentExportCompact")?.addEventListener("click", () => downloadIntentExport("compact"));
  $("#intentExportExpanded")?.addEventListener("click", () => downloadIntentExport("expanded"));
  $("#intentSummaryReveal")?.addEventListener("click", () => {
    state.intentLabeling.summaryReveal = !state.intentLabeling.summaryReveal;
    loadIntentSummary({ datasetIds: state.intentLabeling.summaryDatasetIds, force: true }).catch((error) => showToast(error.message, true));
  });
  $("#intentSummaryPrevious")?.addEventListener("click", () => {
    state.intentLabeling.summaryPage = Math.max(1, state.intentLabeling.summaryPage - 1);
    loadIntentSummary({ datasetIds: state.intentLabeling.summaryDatasetIds, force: true }).catch((error) => showToast(error.message, true));
  });
  $("#intentSummaryNext")?.addEventListener("click", () => {
    state.intentLabeling.summaryPage += 1;
    loadIntentSummary({ datasetIds: state.intentLabeling.summaryDatasetIds, force: true }).catch((error) => showToast(error.message, true));
  });
  const submitSummaryCommentQuery = () => {
    const value = ($("#intentSummaryCommentQuery")?.value || "").trim().slice(0, 80);
    if (value === (state.intentLabeling.summaryCommentQuery || "")) return;
    state.intentLabeling.summaryCommentQuery = value;
    state.intentLabeling.summaryPage = 1;
    loadIntentSummary({ datasetIds: state.intentLabeling.summaryDatasetIds, force: true }).catch((error) => showToast(error.message, true));
  };
  $("#intentSummaryCommentQuery")?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    window.clearTimeout(state.intentLabeling.summaryCommentTimer);
    submitSummaryCommentQuery();
  });
  $("#intentSummaryCommentQuery")?.addEventListener("input", () => {
    window.clearTimeout(state.intentLabeling.summaryCommentTimer);
    state.intentLabeling.summaryCommentTimer = window.setTimeout(submitSummaryCommentQuery, 350);
  });
  initializeIntentExperimentSelects();
  $("#intentExperimentScope")?.addEventListener("change", () => {
    initializeIntentExperimentSelects();
    updateIntentExperimentEstimate();
    persistIntentWorkspacePreferences();
  });
  $("#intentExperimentMode")?.addEventListener("change", (event) => {
    const full = event.target.value === "full";
    const overlap = $("#intentExperimentOverlap");
    if (overlap) {
      overlap.disabled = full;
      if (full) overlap.value = "1";
    }
    $("#intentExperimentOverlapField")?.classList.toggle("is-disabled", full);
    const reviewers = $("#intentExperimentReviewers");
    if (reviewers) reviewers.disabled = full;
    $("#intentExperimentReviewersField")?.classList.toggle("is-disabled", full);
    initializeIntentExperimentSelects();
    updateIntentExperimentEstimate();
    persistIntentWorkspacePreferences();
  });
  $("#intentExperimentCaseCount")?.addEventListener("input", () => { updateIntentExperimentEstimate(); persistIntentWorkspacePreferences(); });
  $("#intentExperimentOverlap")?.addEventListener("change", () => { updateIntentExperimentEstimate(); persistIntentWorkspacePreferences(); });
  $("#intentExperimentReviewers")?.addEventListener("input", () => { updateIntentExperimentEstimate(); persistIntentWorkspacePreferences(); });
  $("#intentExperimentName")?.addEventListener("input", (event) => {
    event.currentTarget.dataset.manualEdited = event.currentTarget.value.trim() ? "true" : "false";
    updateIntentExperimentNameSuggestion();
  });
  $("#intentMyTasks")?.addEventListener("click", () => {
    const username = String(state.session.username || "").toLowerCase();
    if (!state.intentLabeling.assignees.some((item) => item.username === username)) return;
    (async () => {
      await intentFlushSave();
      await loadIntentLabeling({
        datasetId: state.intentLabeling.datasetId,
        caseId: "",
        assignees: [username],
        historyMode: "push",
      });
    })().catch((error) => showToast(error.message, true));
  });
  $("#intentToggleReveal")?.addEventListener("click", () => {
    toggleIntentAnswerReveal().catch((error) => showToast(error.message, true));
  });
  $("#intentLoadCaseButton")?.addEventListener("click", () => {
    (async () => {
      await intentFlushSave();
      await loadIntentLabeling({
        datasetId: state.intentLabeling.datasetId,
        caseId: $("#intentCaseInput")?.value.trim() || "",
        assignees: state.intentLabeling.selectedAssignees,
        historyMode: "push",
      });
    })().catch((error) => showToast(error.message, true));
  });
  $("#intentCaseInput")?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    $("#intentLoadCaseButton")?.click();
  });
  $("#intentCaseOrdinalInput")?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    event.currentTarget.blur();
  });
  $("#intentCaseOrdinalInput")?.addEventListener("change", (event) => {
    intentJumpToCaseOrdinal(event.currentTarget.value).catch((error) => showToast(error.message, true));
  });
  $("#intentFrameOrdinalInput")?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    event.currentTarget.blur();
  });
  $("#intentFrameOrdinalInput")?.addEventListener("change", (event) => {
    intentJumpToFrameOrdinal(event.currentTarget.value);
  });
  $("#intentPreviousFrame")?.addEventListener("click", () => intentMoveFrame(-1));
  $("#intentNextFrame")?.addEventListener("click", () => intentMoveFrame(1));
  $("#intentPreviousCase")?.addEventListener("click", () => intentNavigateCase(-1).catch((error) => showToast(error.message, true)));
  $("#intentNextCase")?.addEventListener("click", () => intentNavigateCase(1).catch((error) => showToast(error.message, true)));
  $("#intentRestoreBatchPrefill")?.addEventListener("click", () => intentRestoreBatchPrefill());
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
