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

function intentSelectedTimepoints() {
  const intent = state.intentLabeling;
  const selected = new Set(intent.selectedTimepointIds || []);
  const items = (intent.caseData?.timepoints || []).filter((item) => selected.has(item.id));
  if (items.length) return items;
  const active = intentActiveTimepoint();
  return active ? [active] : [];
}

function intentSelectionRange(anchorId, focusId) {
  const items = state.intentLabeling.caseData?.timepoints || [];
  const anchorIndex = items.findIndex((item) => item.id === anchorId);
  const focusIndex = items.findIndex((item) => item.id === focusId);
  if (anchorIndex < 0 || focusIndex < 0) return focusId ? [focusId] : [];
  const start = Math.min(anchorIndex, focusIndex);
  const end = Math.max(anchorIndex, focusIndex);
  return items.slice(start, end + 1).map((item) => item.id);
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

function intentExperimentModeLabel(mode) {
  return mode === "full" ? "全量盲标" : "交叉盲标";
}

function renderIntentExperimentMembers() {
  const container = $("#intentExperimentMembers");
  if (!container) return;
  const members = state.intentLabeling.experimentMembers || [];
  container.innerHTML = members.length ? members.map((item) => (
    `<label class="intent-experiment-member"><input type="checkbox" value="${escapeHtml(item.username)}"/><span>${escapeHtml(item.username)}</span><small>${item.role === "admin" ? "管理员" : "标注人"}</small></label>`
  )).join("") : '<div class="empty-note">请先在用户管理中添加具有写入权限的标注人。</div>';
  container.querySelectorAll("input").forEach((input) => {
    input.addEventListener("change", updateIntentExperimentEstimate);
  });
}

function updateIntentExperimentEstimate() {
  const output = $("#intentExperimentEstimate");
  if (!output) return;
  const members = Array.from(document.querySelectorAll("#intentExperimentMembers input:checked"));
  const count = Math.max(0, Number($("#intentExperimentCaseCount")?.value) || 0);
  const mode = $("#intentExperimentMode")?.value || "blind";
  const overlap = Math.max(0, Number($("#intentExperimentOverlap")?.value) || 0);
  if (members.length < 2) {
    output.textContent = "至少选择 2 名成员。";
    return;
  }
  const assignments = mode === "full" ? count * members.length : count + Math.round(count * overlap);
  output.textContent = `${count} 个 Case · ${members.length} 人 · 共 ${assignments} 份独立任务`;
}

function renderIntentExperiments() {
  const container = $("#intentExperimentList");
  if (!container) return;
  const experiments = state.intentLabeling.experiments || [];
  const count = $("#intentExperimentCount");
  if (count) count.textContent = String(experiments.length);
  container.innerHTML = experiments.length ? experiments.map((item) => {
    const members = (item.members || []).map((member) => {
      const detail = item.annotation_mode === "full"
        ? `${member.total} 个 Case`
        : `基础 ${member.base} · 交叉 ${member.cross}`;
      return `<span title="${escapeHtml(member.username)}">${escapeHtml(member.username)} · ${detail}</span>`;
    }).join("");
    const overlap = item.annotation_mode === "blind" ? ` · 交叉 ${Math.round(item.overlap_ratio * 100)}%` : "";
    return `<article class="intent-experiment-item${item.status === "closed" ? " is-closed" : ""}" data-intent-experiment="${escapeHtml(item.id)}">
      <div><h4>${escapeHtml(item.name)}</h4><div class="intent-experiment-meta">${intentExperimentModeLabel(item.annotation_mode)}${overlap} · ${item.case_count} 个 Case · ${item.assignment_count} 份任务 · ${escapeHtml(item.created_by)}</div></div>
      <span class="intent-experiment-status">${item.status === "closed" ? "已关闭" : "进行中"}</span>
      <div class="intent-experiment-member-stats">${members}</div>
      ${item.status === "active" ? '<div class="intent-experiment-actions"><button class="button button-quiet" type="button" data-close-intent-experiment>关闭实验</button></div>' : ""}
    </article>`;
  }).join("") : '<div class="intent-experiment-empty"><span aria-hidden="true">◎</span><strong>这个数据集尚未创建实验</strong><p>在左侧完成配置后，实验与每位成员的任务量会显示在这里。</p></div>';
  container.querySelectorAll("[data-close-intent-experiment]").forEach((button) => {
    button.addEventListener("click", () => {
      const experimentId = button.closest("[data-intent-experiment]")?.dataset.intentExperiment;
      if (!experimentId) return;
      closeIntentExperiment(experimentId).catch((error) => showToast(error.message, true));
    });
  });
}

async function loadIntentExperiments({ force = false } = {}) {
  const intent = state.intentLabeling;
  const requestedDatasetId = intent.experimentDatasetId;
  if (!requestedDatasetId) return;
  if (!force && intent.experimentsDatasetId === requestedDatasetId) {
    renderIntentExperiments();
    return;
  }
  const payload = await api(`/api/intent-experiments?dataset_id=${encodeURIComponent(requestedDatasetId)}`);
  if (intent.experimentDatasetId !== requestedDatasetId) return;
  intent.experiments = payload.items || [];
  intent.experimentMembers = payload.eligible_members || [];
  intent.experimentsDatasetId = requestedDatasetId;
  const dataset = intent.datasets.find((item) => item.id === requestedDatasetId);
  const countInput = $("#intentExperimentCaseCount");
  if (countInput) {
    countInput.max = String(dataset?.case_count || 1);
    countInput.value = String(dataset?.case_count || 1);
  }
  renderIntentExperimentMembers();
  renderIntentExperiments();
  updateIntentExperimentEstimate();
}

function renderIntentExperimentDatasetPicker() {
  const select = $("#intentExperimentDatasetSelect");
  if (!select) return;
  select.innerHTML = state.intentLabeling.datasets.map((item) => (
    `<option value="${escapeHtml(item.id)}"${item.id === state.intentLabeling.experimentDatasetId ? " selected" : ""}${item.available ? "" : " disabled"}>${escapeHtml(item.display_name)}</option>`
  )).join("");
}

async function loadIntentExperimentAdmin({ datasetId = "", force = false } = {}) {
  const intent = state.intentLabeling;
  if (!intent.datasets.length) {
    const payload = await api("/api/intent-datasets");
    intent.datasets = payload.items || [];
  }
  const selected = intent.datasets.find((item) => item.id === datasetId && item.available)
    || intent.datasets.find((item) => item.id === intent.experimentDatasetId && item.available)
    || intent.datasets.find((item) => item.available);
  if (!selected) throw new Error("没有可用于实验分配的数据集。");
  intent.experimentDatasetId = selected.id;
  renderIntentExperimentDatasetPicker();
  await loadIntentExperiments({ force });
  if (state.activePage === "intent-experiments") {
    history.replaceState(
      { page: "intent-experiments", datasetId: selected.id },
      "",
      `${withBase("/intent-experiments")}?dataset=${encodeURIComponent(selected.id)}`
    );
  }
}

async function createIntentExperiment(event) {
  event?.preventDefault();
  const intent = state.intentLabeling;
  const members = Array.from(document.querySelectorAll("#intentExperimentMembers input:checked"))
    .map((input) => input.value);
  const button = $("#intentCreateExperiment");
  if (button) button.disabled = true;
  try {
    await api("/api/intent-experiments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dataset_id: intent.experimentDatasetId,
        name: $("#intentExperimentName")?.value.trim() || "",
        annotation_mode: $("#intentExperimentMode")?.value || "blind",
        case_count: Number($("#intentExperimentCaseCount")?.value) || 0,
        overlap_ratio: Number($("#intentExperimentOverlap")?.value) || 0,
        members,
      }),
    });
    $("#intentExperimentName").value = "";
    intent.experimentsDatasetId = "";
    await loadIntentExperiments({ force: true });
    showToast("实验已创建，任务分配快照已保存。", false);
  } finally {
    if (button) button.disabled = false;
  }
}

async function closeIntentExperiment(experimentId) {
  if (!window.confirm("关闭后仍会保留实验与分配记录。确认关闭这个实验？")) return;
  await api(`/api/intent-experiments/${encodeURIComponent(experimentId)}/close`, { method: "POST" });
  state.intentLabeling.experimentsDatasetId = "";
  await loadIntentExperiments({ force: true });
  showToast("实验已关闭，历史分配仍然保留。", false);
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
    const selected = (intent.selectedTimepointIds || []).includes(item.id);
    return `<button class="intent-timepoint${selected ? " selected" : ""}${item.id === intent.activeTimepointId ? " active" : ""}" type="button" data-intent-timepoint="${escapeHtml(item.id)}" aria-label="切换到 ${escapeHtml(intentTimeLabel(item.offset_ms))}" aria-pressed="${selected ? "true" : "false"}">
      <strong>${escapeHtml(intentTimeLabel(item.offset_ms))}</strong>
      <span class="intent-thumb-stack">
        ${camera ? `<img data-intent-lazy-src="${escapeHtml(camera)}" alt=""/>` : '<span class="intent-thumb-missing">Camera 缺失</span>'}
        ${bev ? `<img data-intent-lazy-src="${escapeHtml(bev)}" alt=""/>` : '<span class="intent-thumb-missing">BEV 缺失</span>'}
      </span>
      <small class="${override ? "is-override" : ""}">${escapeHtml(intentLabelSummary(item))}</small>
    </button>`;
  }).join("");
  timeline.querySelectorAll("[data-intent-timepoint]").forEach((button) => {
    button.addEventListener("click", (event) => intentSelectTimepoint(button.dataset.intentTimepoint, { extendSelection: event.shiftKey }));
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
  const selectedCount = intentSelectedTimepoints().length;
  $("#intentFrameTitle").textContent = selectedCount > 1 ? "多个帧标签" : "当前帧标签";
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
  $("#intentFrameSource").textContent = selectedCount > 1
    ? `已选 ${selectedCount} 帧，数字键应用到全部选中帧`
    : (currentOverride ? "当前帧已单独修改" : "当前帧来自批量预填");
  $("#intentRestoreBatchPrefillText").textContent = selectedCount > 1
    ? `选中 ${selectedCount} 帧恢复批量预填`
    : "当前帧恢复批量预填";
  const total = intent.caseData?.timepoints?.length || 0;
  const overrideCount = Object.keys(intent.overrides).length;
  $("#intentCoverage").textContent = `${Math.max(0, total - overrideCount)} 帧使用批量预填 · ${overrideCount} 帧单独修改`;
}

function renderIntentCollaboration() {
  const collaboration = state.intentLabeling.caseData?.collaboration || {};
  const contributors = collaboration.contributors || [];
  const contributorList = $("#intentContributorList");
  const revealState = $("#intentRevealState");
  if (revealState) revealState.textContent = collaboration.answers_revealed
    ? "已解盲"
    : "实验进行中 · 答案隐藏";
  if (contributorList) {
    contributorList.innerHTML = contributors.length ? contributors.map((item) => {
      const status = item.completed ? "已完成" : "进行中";
      const answer = item.revealed
        ? `${INTENT_ROUTING_LABELS[item.routing_default] || "Routing 待填"} · ${INTENT_LANE_LABELS[item.lane_change_default] || "变道待填"}`
        : "答案已隐藏";
      return `<article class="intent-contributor${item.is_current ? " is-current" : ""}"><div><strong>${escapeHtml(item.username)}${item.is_current ? "（我）" : ""}</strong><span>${escapeHtml(answer)}</span></div><small class="${item.completed ? "is-complete" : ""}">${status}</small></article>`;
    }).join("") : "<p>尚无标注记录</p>";
  }
  const comments = collaboration.comments || [];
  const commentList = $("#intentCommentList");
  if ($("#intentCommentCount")) $("#intentCommentCount").textContent = `${comments.length} 条`;
  if (commentList) {
    commentList.innerHTML = comments.length ? comments.map((item) => (
      `<article class="intent-comment"><div><strong>${escapeHtml(item.author)}</strong><time>${escapeHtml(new Date(item.created_at).toLocaleString())}</time></div><p>${escapeHtml(item.body)}</p></article>`
    )).join("") : "<p>还没有评论</p>";
    commentList.scrollTop = commentList.scrollHeight;
  }
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
  renderIntentCollaboration();
}

async function postIntentComment(event) {
  event.preventDefault();
  const intent = state.intentLabeling;
  const input = $("#intentCommentInput");
  const body = input?.value.trim() || "";
  if (!body || !intent.datasetId || !intent.caseId || intent.postingComment) return;
  intent.postingComment = true;
  const submit = event.currentTarget.querySelector('button[type="submit"]');
  if (submit) submit.disabled = true;
  try {
    const result = await api(`/api/intent-datasets/${encodeURIComponent(intent.datasetId)}/cases/${encodeURIComponent(intent.caseId)}/comments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
    });
    intent.caseData.collaboration ||= { contributors: [], comments: [] };
    intent.caseData.collaboration.comments ||= [];
    intent.caseData.collaboration.comments.push(result.comment);
    input.value = "";
    renderIntentCollaboration();
  } finally {
    intent.postingComment = false;
    if (submit) submit.disabled = false;
  }
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
  intent.selectedTimepointIds = intent.activeTimepointId ? [intent.activeTimepointId] : [];
  intent.selectionAnchorId = intent.activeTimepointId;
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
  const selected = intentSelectedTimepoints();
  if (!selected.length) return;
  const aggregateValue = axis === "routing" ? intent.aggregate.routing : intent.aggregate.laneChange;
  const key = axis === "routing" ? "routing_intent" : "lane_change_intent";
  selected.forEach((timepoint) => {
    const override = { ...(intentOverride(timepoint.id) || {}), timepoint_id: timepoint.id, offset_ms: timepoint.offset_ms };
    if (value === aggregateValue) delete override[key];
    else override[key] = value;
    if (!override.routing_intent && !override.lane_change_intent) delete intent.overrides[timepoint.id];
    else intent.overrides[timepoint.id] = override;
  });
  intentMarkDirty();
  renderIntentLabels();
  renderIntentTimeline();
}

function intentRestoreBatchPrefill() {
  const intent = state.intentLabeling;
  const selected = intentSelectedTimepoints();
  const changed = selected.some((timepoint) => Boolean(intent.overrides[timepoint.id]));
  if (!changed) return;
  selected.forEach((timepoint) => delete intent.overrides[timepoint.id]);
  intentMarkDirty();
  renderIntentLabels();
  renderIntentTimeline();
}

function intentSelectTimepoint(timepointId, { updateRoute = true, extendSelection = false } = {}) {
  const intent = state.intentLabeling;
  if (!(intent.caseData?.timepoints || []).some((item) => item.id === timepointId)) return;
  if (extendSelection) {
    const anchorId = intent.selectionAnchorId || intent.activeTimepointId || timepointId;
    intent.selectionAnchorId = anchorId;
    intent.selectedTimepointIds = intentSelectionRange(anchorId, timepointId);
  } else {
    intent.selectionAnchorId = timepointId;
    intent.selectedTimepointIds = [timepointId];
  }
  intent.activeTimepointId = timepointId;
  renderIntentCase();
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
  if (event.altKey || intentShortcutIsEditable(event.target)) return;
  const boundaryModifier = event.ctrlKey || event.metaKey;
  const digit = INTENT_DIGIT_LABELS[event.code];
  if (digit) {
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
  if (event.shiftKey || boundaryModifier) return;
  const actions = {
    ArrowUp: () => intentNavigateCase(-1),
    ArrowDown: () => intentNavigateCase(1),
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
  $("#intentCommentForm")?.addEventListener("submit", (event) => {
    postIntentComment(event).catch((error) => showToast(error.message, true));
  });
  $("#intentTimeline")?.addEventListener("wheel", (event) => {
    const timeline = event.currentTarget;
    if (event.ctrlKey || event.metaKey || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return;
    event.preventDefault();
    timeline.scrollLeft += event.deltaY;
  }, { passive: false });
  $("#intentExperimentDatasetSelect")?.addEventListener("change", (event) => {
    state.intentLabeling.experimentsDatasetId = "";
    loadIntentExperimentAdmin({ datasetId: event.target.value, force: true })
      .catch((error) => showToast(error.message, true));
  });
  $("#intentExperimentForm")?.addEventListener("submit", (event) => {
    createIntentExperiment(event).catch((error) => showToast(error.message, true));
  });
  $("#intentRefreshExperiments")?.addEventListener("click", () => {
    state.intentLabeling.experimentsDatasetId = "";
    loadIntentExperiments({ force: true }).catch((error) => showToast(error.message, true));
  });
  $("#intentExperimentMode")?.addEventListener("change", (event) => {
    const full = event.target.value === "full";
    const overlap = $("#intentExperimentOverlap");
    if (overlap) {
      overlap.disabled = full;
      if (full) overlap.value = "1";
    }
    $("#intentExperimentOverlapField")?.classList.toggle("is-disabled", full);
    updateIntentExperimentEstimate();
  });
  $("#intentExperimentCaseCount")?.addEventListener("input", updateIntentExperimentEstimate);
  $("#intentExperimentOverlap")?.addEventListener("change", updateIntentExperimentEstimate);
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
