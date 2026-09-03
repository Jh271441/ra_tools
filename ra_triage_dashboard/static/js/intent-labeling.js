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
    assignees: overrides.assignees ?? intent.selectedAssignees,
    experimentId: overrides.experimentId ?? intent.selectedExperimentId,
  };
}

function intentAssigneeSearchParams(assignees = state.intentLabeling.selectedAssignees) {
  const params = new URLSearchParams();
  (assignees || []).forEach((username) => params.append("assignee", username));
  if (state.intentLabeling.selectedExperimentId) {
    params.set("experiment_id", state.intentLabeling.selectedExperimentId);
  }
  return params;
}

function intentApiUrl(path, params = new URLSearchParams()) {
  const query = params.toString();
  return `${path}${query ? `?${query}` : ""}`;
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

function intentAxisLabel(axis, value) {
  if (axis === "routing") return INTENT_ROUTING_LABELS[value] || "Routing 待填";
  return INTENT_LANE_LABELS[value] || "变道待填";
}

function intentLabelSummary(timepoint) {
  const effective = intentEffective(timepoint);
  return `${intentAxisLabel("routing", effective.routing)} · ${intentAxisLabel("laneChange", effective.laneChange)}`;
}

function intentChipMarkup(label, { pending = false, override = false } = {}) {
  return `<b class="intent-chip${pending ? " is-pending" : ""}${override ? " is-override" : ""}">${escapeHtml(label)}</b>`;
}

function intentTimepointLabelMarkup(timepoint) {
  const effective = intentEffective(timepoint);
  const override = timepoint ? intentOverride(timepoint.id) : null;
  return `<span class="intent-timepoint-labels${override ? " is-override" : ""}">${
    intentChipMarkup(intentAxisLabel("routing", effective.routing), { pending: !effective.routing, override: Boolean(override?.routing_intent) })
  }${
    intentChipMarkup(intentAxisLabel("laneChange", effective.laneChange), { pending: !effective.laneChange, override: Boolean(override?.lane_change_intent) })
  }</span>`;
}

function renderIntentTopbarDatasetPicker(selectedId = state.intentLabeling.datasetId) {
  const picker = $("#intentTopbarDatasetPicker");
  if (!picker) return;
  populateUiSelect(picker, state.intentLabeling.datasets.map((item) => ({
    value: item.id, label: item.display_name, disabled: !item.available,
  })), selectedId);
  bindUiSelect(picker, { maxHeight: 280, maxWidth: 320 });
}

function renderIntentAssignmentFilter() {
  const intent = state.intentLabeling;
  const picker = $("#intentAssignmentPicker");
  if (!picker) return;
  const options = (intent.assignmentExperiments || []).map((item) => ({
    value: item.id,
    label: `${item.name} · ${item.case_count} Case`,
  }));
  const native = $("#intentAssignmentSelect");
  if (native) {
    native.innerHTML = [
      '<option value="">未分配（全部 Issue）</option>',
      ...options.map((item) => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`),
    ].join("");
    native.value = intent.selectedExperimentId || "";
  }
  renderMultiFilter(picker, {
    options,
    selected: intent.selectedExperimentId ? [intent.selectedExperimentId] : [],
    onlyThis: true,
    onChange: (values) => {
      const experimentId = values[values.length - 1] || "";
      if (experimentId === intent.selectedExperimentId && values.length <= 1) return;
      setMultiFilterValues(picker, experimentId ? [experimentId] : []);
      if (native) native.value = experimentId;
      (async () => {
        await intentFlushSave();
        intent.assigneeDatasetId = "";
        intent.selectedAssignees = [];
        await loadIntentLabeling({
          datasetId: intent.datasetId,
          caseId: "",
          // Changing the experiment is an explicit scope change.  Clear the
          // owner filter as well so “未分配（全部 Issue）” really means the
          // complete dataset instead of silently re-selecting the SSO user.
          assignees: [],
          experimentId,
          historyMode: "push",
        });
      })().catch((error) => showToast(error.message, true));
    },
  });
}

function renderIntentAssigneeFilter() {
  const intent = state.intentLabeling;
  const currentUsername = String(state.session.username || "").toLowerCase();
  renderMultiFilter($("#intentAssigneeFilter"), {
    options: intent.assignees.map((item) => ({
      value: item.username,
      label: `${item.username}${item.username === currentUsername ? "（我）" : ""} · ${item.case_count} Case`,
    })),
    selected: intent.selectedAssignees,
    onlyThis: true,
    onChange: (values) => {
      (async () => {
        await intentFlushSave();
        intent.selectedAssignees = values;
        await loadIntentLabeling({
          datasetId: intent.datasetId,
          caseId: "",
          assignees: values,
          historyMode: "push",
        });
      })().catch((error) => showToast(error.message, true));
    },
  });
  const myTasks = $("#intentMyTasks");
  const assignedToMe = intent.assignees.some((item) => item.username === currentUsername);
  if (myTasks) {
    myTasks.disabled = !assignedToMe;
    myTasks.classList.toggle("is-active", intent.selectedAssignees.length === 1 && intent.selectedAssignees[0] === currentUsername);
    myTasks.title = assignedToMe ? "只看实验分配给我的 Case" : "当前数据集没有分配给我的任务";
  }
}

async function loadIntentAssignees(datasetId, requested = null, requestedExperimentId = null) {
  const intent = state.intentLabeling;
  const nextExperimentId = requestedExperimentId == null
    ? intent.selectedExperimentId
    : String(requestedExperimentId || "");
  const cacheKey = `${datasetId}:${nextExperimentId}`;
  if (intent.assigneeDatasetId !== cacheKey) {
    const params = new URLSearchParams({ dataset_id: datasetId });
    if (nextExperimentId) params.set("experiment_id", nextExperimentId);
    const payload = await api(`/api/intent-assignees?${params}`);
    if (intent.datasetId !== datasetId) return;
    intent.assignees = payload.items || [];
    intent.assignmentExperiments = payload.experiments || [];
    const experimentIds = new Set(intent.assignmentExperiments.map((item) => item.id));
    intent.selectedExperimentId = experimentIds.has(nextExperimentId) ? nextExperimentId : "";
    intent.assigneeDatasetId = `${datasetId}:${intent.selectedExperimentId}`;
  }
  const available = new Set(intent.assignees.map((item) => item.username));
  const currentUsername = String(state.session.username || "").toLowerCase();
  const selectionKey = `${datasetId}:${intent.selectedExperimentId}`;
  const firstSelectionForDataset = intent.assigneeSelectionDatasetId !== selectionKey;
  let selected = requested == null ? intent.selectedAssignees : parseFilterList(requested);
  // An unselected experiment is the unassigned/all-Issue scope. Do not let
  // the SSO convenience default silently narrow that scope to the current
  // annotator; the explicit “我的任务” action remains available. When a
  // concrete experiment is selected, keeping the current user selected is
  // useful for blind work and still follows the assignment snapshot.
  if (
    requested == null
    && firstSelectionForDataset
    && intent.selectedExperimentId
    && available.has(currentUsername)
  ) {
    selected = [currentUsername];
  }
  intent.assigneeSelectionDatasetId = selectionKey;
  intent.selectedAssignees = selected.filter((username) => available.has(username));
  renderIntentAssignmentFilter();
  renderIntentAssigneeFilter();
}

function intentExperimentModeLabel(mode) {
  return mode === "full" ? "全量盲标" : "交叉盲标";
}

function initializeIntentExperimentSelects() {
  const mode = $("#intentExperimentModePicker");
  populateUiSelect(mode, [
    { value: "blind", label: "交叉盲标" },
    { value: "full", label: "全量盲标" },
  ], $("#intentExperimentMode")?.value || "blind");
  bindUiSelect(mode, { maxHeight: 220, maxWidth: 280 });
  const overlap = $("#intentExperimentOverlapPicker");
  populateUiSelect(overlap, [0, 0.1, 0.2, 0.3, 0.5, 1].map((value) => ({
    value: String(value), label: `${Math.round(value * 100)}%`,
  })), $("#intentExperimentOverlap")?.value || "0.2");
  bindUiSelect(overlap, { maxHeight: 260, maxWidth: 240 });
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
  const reviewerInput = $("#intentExperimentReviewers");
  if (reviewerInput) {
    reviewerInput.max = String(Math.max(1, members.length));
    if (Number(reviewerInput.value) > members.length) reviewerInput.value = String(Math.max(1, members.length));
  }
  const reviewers = Math.max(1, Math.min(members.length, Number(reviewerInput?.value) || 1));
  if (members.length < 1) {
    output.textContent = "至少选择 1 名成员。";
    return;
  }
  const overlapCases = Math.round(count * overlap);
  const assignments = mode === "full" ? count * members.length : count + overlapCases * (reviewers - 1);
  output.textContent = mode === "full"
    ? `${count} 个 Case · ${members.length} 人全量复核 · 共 ${assignments} 份独立任务`
    : `${count} 个 Case · ${overlapCases} 个交叉 Case 由 ${reviewers} 人复核 · 共 ${assignments} 份独立任务`;
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
    const overlap = item.annotation_mode === "blind" ? ` · 交叉 ${Math.round(item.overlap_ratio * 100)}% · 每 Case ${item.overlap_reviewers || 2} 人` : "";
    return `<article class="intent-experiment-item${item.status === "closed" ? " is-closed" : ""}" data-intent-experiment="${escapeHtml(item.id)}">
      <div><h4>${escapeHtml(item.name)}</h4><div class="intent-experiment-meta">${intentExperimentModeLabel(item.annotation_mode)}${overlap} · ${item.case_count} 个 Case · ${item.assignment_count} 份任务 · ${escapeHtml(item.created_by)}</div></div>
      <span class="intent-experiment-status">${item.status === "closed" ? "已关闭" : "进行中"}</span>
      <div class="intent-experiment-member-stats">${members}</div>
      ${item.status === "active" && state.session.can_manage_intent ? '<div class="intent-experiment-actions"><button class="button button-quiet" type="button" data-close-intent-experiment>关闭实验</button></div>' : ""}
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
  renderIntentTopbarDatasetPicker(selected.id);
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
    const result = await api("/api/intent-experiments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dataset_id: intent.experimentDatasetId,
        name: $("#intentExperimentName")?.value.trim() || "",
        annotation_mode: $("#intentExperimentMode")?.value || "blind",
        case_count: Number($("#intentExperimentCaseCount")?.value) || 0,
        overlap_ratio: Number($("#intentExperimentOverlap")?.value) || 0,
        overlap_reviewers: Number($("#intentExperimentReviewers")?.value) || 1,
        members,
      }),
    });
    acknowledgeLocalChange(result);
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
  const result = await api(`/api/intent-experiments/${encodeURIComponent(experimentId)}/close`, { method: "POST" });
  acknowledgeLocalChange(result);
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

function intentFrameCountText(counts, labels) {
  const values = counts || {};
  return Object.entries(values)
    .filter(([, count]) => Number(count) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .map(([value, count]) => `${labels[value] || value} ${Number(count)}帧`)
    .join(" · ");
}

function intentSummaryChipClass(value) {
  return ({
    straight: "is-straight",
    left_turn: "is-left",
    right_turn: "is-right",
    u_turn: "is-uturn",
    parking: "is-parking",
    no_lane_change: "is-no-lane",
    lane_change: "is-lane",
  })[value] || "";
}

function intentSummaryResultMarkup(counts, labels) {
  const entries = Object.entries(counts || {})
    .filter(([, count]) => Number(count) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]));
  if (!entries.length) return '<div class="intent-summary-result is-empty">—</div>';
  return `<div class="intent-summary-result">${entries.map(([value, count]) => (
    `<b class="intent-summary-chip ${intentSummaryChipClass(value)}">${escapeHtml(labels[value] || value)} ${Number(count)}帧</b>`
  )).join("")}</div>`;
}

function renderIntentSummaryCommentHits(payload) {
  const card = $("#intentSummaryCommentHits");
  if (!card) return;
  const query = String(payload.comment_query || "").trim();
  const hits = payload.comment_hits || [];
  if (!query) {
    card.hidden = true;
    card.innerHTML = "";
    return;
  }
  card.hidden = false;
  const datasetId = state.intentLabeling.summaryDatasetId;
  const rows = hits.length ? hits.map((item) => {
    const href = `${withBase("/intent-labeling")}?dataset=${encodeURIComponent(datasetId)}&case=${encodeURIComponent(item.case_id)}&comments=1&comment=${encodeURIComponent(item.id)}`;
    return `<article class="intent-summary-comment-hit">
      <a class="intent-summary-case-link" href="${escapeHtml(href)}">${escapeHtml(item.case_id)}</a>
      <strong>${escapeHtml(item.author)}${item.author === state.session.username ? "（我）" : ""}</strong>
      <p>${escapeHtml(item.snippet || item.body || "")}</p>
      <time>${escapeHtml(formatTime(item.created_at) || "")}</time>
    </article>`;
  }).join("") : `<p class="intent-summary-comment-empty">没有匹配“${escapeHtml(query)}”的评论。</p>`;
  const blindNote = payload.blind_active && !payload.answers_revealed
    ? "<small>盲标中仅搜索自己的评论。</small>"
    : "";
  card.innerHTML = `<header><h2>评论搜索</h2><p>${hits.length} 条${blindNote}</p></header><div class="intent-summary-comment-list">${rows}</div>`;
}

function renderIntentSummary(payload) {
  const axis = payload.axis || "all";
  const showRouting = axis !== "lane_change";
  const showLaneChange = axis !== "routing";
  document.querySelectorAll(".intent-summary-routing-column").forEach((element) => { element.hidden = !showRouting; });
  document.querySelectorAll(".intent-summary-lane-column").forEach((element) => { element.hidden = !showLaneChange; });
  const metrics = [
    ["范围 Case", payload.case_count, "is-scope"],
    ["已标注 Case", payload.annotated_cases, "is-labeled"],
    ["完整标注记录", payload.complete_records, "is-complete"],
    ["多人一致性", payload.agreement.comparable_cases ? `${payload.agreement.matching_cases} / ${payload.agreement.comparable_cases}` : "—", "is-agree"],
  ];
  $("#intentSummaryMetrics").innerHTML = metrics.map(([label, value, kind]) => `<article class="intent-summary-metric ${kind}"><small>${label}</small><strong>${escapeHtml(value)}</strong></article>`).join("");
  renderIntentSummaryCommentHits(payload);
  const datasetId = state.intentLabeling.summaryDatasetId;
  const columnCount = 3 + Number(showRouting) + Number(showLaneChange);
  $("#intentSummaryRows").innerHTML = (payload.items || []).map((item) => {
    const href = `${withBase("/intent-labeling")}?dataset=${encodeURIComponent(datasetId)}&case=${encodeURIComponent(item.case_id)}`;
    return `<tr><td><a class="intent-summary-case-link" href="${escapeHtml(href)}">${escapeHtml(item.case_id)}</a></td><td>${escapeHtml(item.username)}${item.username === state.session.username ? "（我）" : ""}</td><td class="intent-summary-routing-column"${showRouting ? "" : " hidden"}>${intentSummaryResultMarkup(item.frame_counts?.routing, INTENT_ROUTING_LABELS)}</td><td class="intent-summary-lane-column"${showLaneChange ? "" : " hidden"}>${intentSummaryResultMarkup(item.frame_counts?.lane_change, INTENT_LANE_LABELS)}</td><td>${escapeHtml(formatTime(item.updated_at) || "—")}</td></tr>`;
  }).join("") || `<tr><td colspan="${columnCount}">当前筛选下没有已标注结果。</td></tr>`;
  $("#intentSummarySafety").textContent = payload.blind_active && !payload.answers_revealed ? "进行中的盲标实验仅显示自己的答案。" : "汇总当前标注头；不会加载 Camera / BEV 图片。";
  const reveal = $("#intentSummaryReveal");
  reveal.hidden = !(state.session.is_admin && payload.blind_active);
  reveal.textContent = payload.answers_revealed ? "恢复盲态" : "管理员解盲";
  $("#intentExportCompact").hidden = !state.session.is_admin;
  $("#intentExportExpanded").hidden = !state.session.is_admin;
  const pageCount = Math.max(1, Math.ceil(Number(payload.total || 0) / Number(payload.page_size || 20)));
  $("#intentSummaryPageState").textContent = `${payload.page} / ${pageCount}`;
  $("#intentSummaryPrevious").disabled = payload.page <= 1;
  $("#intentSummaryNext").disabled = payload.page >= pageCount;
}

async function loadIntentSummary({ datasetId = "", force = false } = {}) {
  const intent = state.intentLabeling;
  if (!intent.datasets.length) intent.datasets = (await api("/api/intent-datasets")).items || [];
  const selected = intent.datasets.find((item) => item.id === datasetId && item.available) || intent.datasets.find((item) => item.id === intent.summaryDatasetId && item.available) || intent.datasets.find((item) => item.available);
  if (!selected) throw new Error("没有可汇总的数据集。");
  intent.summaryDatasetId = selected.id;
  renderIntentTopbarDatasetPicker(selected.id);
  const params = new URLSearchParams({ dataset_id: selected.id });
  if (intent.summaryExperimentId) params.set("experiment_id", intent.summaryExperimentId);
  (intent.summaryAssignees || []).forEach((value) => params.append("assignee", value));
  if (intent.summaryReveal) params.set("reveal_answers", "true");
  params.set("axis", intent.summaryAxis || "all");
  params.set("page", String(intent.summaryPage || 1));
  params.set("page_size", String(intent.summaryPageSize || 20));
  const commentQuery = String(intent.summaryCommentQuery || "").trim();
  if (commentQuery) params.set("q", commentQuery);
  const payload = await api(`/api/intent-summary?${params}`);
  intent.summaryPayload = payload;
  const summaryExperimentOptions = (payload.experiments || []).map((item) => ({
    value: item.id,
    label: item.name,
  }));
  const summaryExperimentNative = $("#intentSummaryExperiment");
  if (summaryExperimentNative) {
    summaryExperimentNative.innerHTML = [
      '<option value="">全部实验</option>',
      ...summaryExperimentOptions.map((item) => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`),
    ].join("");
    summaryExperimentNative.value = intent.summaryExperimentId || "";
  }
  renderMultiFilter($("#intentSummaryExperimentPicker"), {
    options: summaryExperimentOptions,
    selected: intent.summaryExperimentId ? [intent.summaryExperimentId] : [],
    onlyThis: true,
    onChange: (values) => {
      const experimentId = values[values.length - 1] || "";
      setMultiFilterValues($("#intentSummaryExperimentPicker"), experimentId ? [experimentId] : []);
      if (summaryExperimentNative) summaryExperimentNative.value = experimentId;
      intent.summaryExperimentId = experimentId;
      intent.summaryAssignees = [];
      intent.summaryPage = 1;
      loadIntentSummary({ datasetId: selected.id, force: true }).catch((error) => showToast(error.message, true));
    },
  });
  populateUiSelect($("#intentSummaryAxisPicker"), [
    { value: "all", label: "Routing + 变道意图" },
    { value: "routing", label: "仅 Routing" },
    { value: "lane_change", label: "仅变道意图" },
  ], intent.summaryAxis || "all");
  bindUiSelect($("#intentSummaryAxisPicker"), { maxWidth: 260 });
  populateUiSelect($("#intentSummaryPageSizePicker"), [10, 20, 50].map((value) => ({ value: String(value), label: `${value} / 页` })), String(intent.summaryPageSize || 20));
  bindUiSelect($("#intentSummaryPageSizePicker"), { maxWidth: 180 });
  const commentInput = $("#intentSummaryCommentQuery");
  if (commentInput && commentInput.value !== (intent.summaryCommentQuery || "")) {
    commentInput.value = intent.summaryCommentQuery || "";
  }
  renderMultiFilter($("#intentSummaryAssignees"), { options: (payload.owners || []).map((value) => ({ value, label: value === state.session.username ? `${value}（我）` : value })), selected: intent.summaryAssignees || [], onlyThis: true, onChange: (values) => { intent.summaryAssignees = values; intent.summaryPage = 1; loadIntentSummary({ datasetId: selected.id, force: true }).catch((error) => showToast(error.message, true)); } });
  renderIntentSummary(payload);
  const routeParams = new URLSearchParams({ dataset: selected.id });
  if (intent.summaryExperimentId) routeParams.set("experiment", intent.summaryExperimentId);
  (intent.summaryAssignees || []).forEach((value) => routeParams.append("owner", value));
  if ((intent.summaryPage || 1) > 1) routeParams.set("page", String(intent.summaryPage));
  if ((intent.summaryAxis || "all") !== "all") routeParams.set("axis", intent.summaryAxis);
  if ((intent.summaryPageSize || 20) !== 20) routeParams.set("page_size", String(intent.summaryPageSize));
  if (commentQuery) routeParams.set("q", commentQuery);
  history.replaceState({ page: "intent-summary", datasetId: selected.id }, "", `${withBase("/intent-summary")}?${routeParams}`);
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

function intentLocalFrameCounts() {
  const routing = {};
  const laneChange = {};
  (state.intentLabeling.caseData?.timepoints || []).forEach((item) => {
    const effective = intentEffective(item);
    if (effective.routing) routing[effective.routing] = (routing[effective.routing] || 0) + 1;
    if (effective.laneChange) laneChange[effective.laneChange] = (laneChange[effective.laneChange] || 0) + 1;
  });
  return { routing, lane_change: laneChange };
}

function intentContributorIsLabeled(item) {
  return Boolean(
    item.labeled
    || item.routing_default
    || item.lane_change_default
    || (item.overrides || []).length
  );
}

function intentContributorStatus(item) {
  return intentContributorIsLabeled(item) ? "已标注" : "待标注";
}

function renderIntentCollaboration() {
  const active = intentActiveTimepoint();
  const collaboration = state.intentLabeling.caseData?.collaboration || {};
  const discussionButton = $("#intentOpenComments");
  if (discussionButton) {
    discussionButton.dataset.intentDatasetId = state.intentLabeling.datasetId || "";
    discussionButton.dataset.intentCaseId = state.intentLabeling.caseId || "";
  }
  const contributors = [...(collaboration.contributors || [])].sort((left, right) => {
    if (Boolean(left.is_current) !== Boolean(right.is_current)) return left.is_current ? -1 : 1;
    const leftLabeled = intentContributorIsLabeled(left);
    const rightLabeled = intentContributorIsLabeled(right);
    if (leftLabeled !== rightLabeled) return leftLabeled ? -1 : 1;
    return String(left.username || "").localeCompare(String(right.username || ""));
  });
  const contributorList = $("#intentContributorList");
  const revealButton = $("#intentToggleReveal");
  const canReveal = Boolean(state.session.is_admin && collaboration.blind_active);
  if (revealButton) {
    revealButton.hidden = !canReveal;
    revealButton.textContent = collaboration.answers_revealed ? "恢复盲态" : "管理员解盲";
  }
  const canDelete = Boolean(state.session.can_annotate_intent && state.intentLabeling.revisionId);
  if (contributorList) {
    contributorList.innerHTML = contributors.length ? contributors.map((item) => {
      const labeled = intentContributorIsLabeled(item);
      const name = `<strong>${escapeHtml(item.username)}${item.is_current ? "（我）" : ""}</strong>`;
      if (!item.revealed || !labeled) {
        return `<article class="intent-contributor${item.is_current ? " is-current" : ""}">${name}<span class="intent-contributor-status ${labeled ? "is-labeled" : "is-pending"}">${intentContributorStatus(item)}</span></article>`;
      }
      const frameOverride = (item.overrides || []).find((entry) => entry.timepoint_id === active?.id) || {};
      const routingValue = frameOverride.routing_intent || item.routing_default;
      const laneChangeValue = frameOverride.lane_change_intent || item.lane_change_default;
      const routingCountText = intentFrameCountText(item.frame_counts?.routing, INTENT_ROUTING_LABELS);
      const laneCountText = intentFrameCountText(item.frame_counts?.lane_change, INTENT_LANE_LABELS);
      const deleteButton = item.is_current && canDelete
        ? `<button class="button button-quiet intent-delete-label" type="button" data-intent-delete-mine title="移除自己的当前答案；历史版本与删除审计仍会保留">删除</button>`
        : "";
      return `<article class="intent-contributor is-revealed${item.is_current ? " is-current" : ""}">
        ${name}
        <div class="intent-contributor-labels">${
          intentChipMarkup(INTENT_ROUTING_LABELS[routingValue] || "Routing 待填", { pending: !routingValue })
        }${
          intentChipMarkup(INTENT_LANE_LABELS[laneChangeValue] || "变道待填", { pending: !laneChangeValue })
        }</div>
        <small class="intent-contributor-counts">${escapeHtml([routingCountText, laneCountText].filter(Boolean).join(" · ") || "")}</small>
        ${deleteButton}
      </article>`;
    }).join("") : "<p>尚无标注记录</p>";
  }
  const comments = collaboration.comments || [];
  if ($("#intentCommentCount")) $("#intentCommentCount").textContent = `${comments.length} 条`;
  if (discussionButton) {
    discussionButton.innerHTML = comments.length
      ? `打开讨论 · ${comments.length} <kbd>D</kbd>`
      : "打开讨论 <kbd>D</kbd>";
  }
}

async function deleteMyIntentLabel() {
  const intent = state.intentLabeling;
  if (!state.session.can_annotate_intent || !intent.caseId || !intent.revisionId) return;
  if (!window.confirm("确认删除自己在当前 Case 的标注？当前答案会被移除，但历史版本和删除审计会保留。")) return;
  await intentFlushSave();
  const revisionId = intent.revisionId;
  if (!revisionId) return;
  const result = await api(
    `/api/intent-datasets/${encodeURIComponent(intent.datasetId)}/cases/${encodeURIComponent(intent.caseId)}/labels?expected_revision_id=${encodeURIComponent(revisionId)}`,
    { method: "DELETE" }
  );
  acknowledgeLocalChange(result);
  intent.revisionId = null;
  intent.aggregate = { routing: "", laneChange: "" };
  intent.overrides = {};
  intent.undoStack = [];
  intent.dirty = false;
  intent.editVersion = 0;
  intent.autoAdvanceOnSave = false;
  intent.autoAdvanceTimepointId = "";
  if (intent.caseData) {
    intent.caseData.labels = result.labels;
    intent.caseData.status = "unlabeled";
    const username = String(state.session.username || "").toLowerCase();
    intent.caseData.collaboration ||= { contributors: [], comments: [] };
    const contributors = intent.caseData.collaboration.contributors ||= [];
    const current = contributors.find((item) => item.is_current || item.username === username);
    if (current) {
      Object.assign(current, {
        username,
        is_current: true,
        labeled: false,
        completed: false,
        revealed: true,
        routing_default: "",
        lane_change_default: "",
        overrides: [],
        frame_counts: {},
        updated_at: "",
        version: 0,
      });
    }
  }
  intentSetSaveState("尚未标注", "");
  updateIntentTimelineState({ scroll: false });
  renderIntentLabels();
  renderIntentCollaboration();
  showToast("当前标注已删除，历史版本与审计记录已保留。", false);
}

async function toggleIntentAnswerReveal() {
  const intent = state.intentLabeling;
  if (!state.session.is_admin || !intent.caseId) return;
  await intentFlushSave();
  intent.adminRevealAnswers = !intent.adminRevealAnswers;
  const params = intentAssigneeSearchParams();
  if (intent.adminRevealAnswers) params.set("reveal_answers", "true");
  try {
    const data = await api(intentApiUrl(`/api/intent-datasets/${encodeURIComponent(intent.datasetId)}/cases/${encodeURIComponent(intent.caseId)}`, params));
    if (intent.caseId !== data.case_id) return;
    intent.caseData.collaboration = data.collaboration;
    renderIntentCollaboration();
  } catch (error) {
    intent.adminRevealAnswers = !intent.adminRevealAnswers;
    throw error;
  }
}

function openIntentComments({ focusCommentId = 0 } = {}) {
  const intent = state.intentLabeling;
  const issueId = intent.caseData?.issue_id || intent.caseId;
  if (!issueId || typeof openAnalysisDiscussion !== "function") return;
  const discussionButton = $("#intentOpenComments");
  if (discussionButton) {
    discussionButton.dataset.intentDatasetId = intent.datasetId;
    discussionButton.dataset.intentCaseId = intent.caseId;
  }
  return openAnalysisDiscussion(issueId, {
    source: "intent",
    intentDatasetId: intent.datasetId,
    intentCaseId: intent.caseId,
    focusCommentId,
  });
}

function renderIntentCase({ deferTimelineThumbnails = false } = {}) {
  const intent = state.intentLabeling;
  const data = intent.caseData;
  renderIntentTopbarDatasetPicker(intent.datasetId);
  if (!data) return;
  $("#intentCaseInput").value = data.issue_id;
  $("#intentPreviousCase").disabled = !data.previous_case_id;
  $("#intentNextCase").disabled = !data.next_case_id;
  const caseOrdinal = $("#intentCaseOrdinalInput");
  if (caseOrdinal) {
    caseOrdinal.value = String(data.ordinal || "");
    caseOrdinal.max = String(Math.max(1, data.case_count || 0));
  }
  if ($("#intentCaseCount")) $("#intentCaseCount").textContent = String(data.case_count || "—");
  updateIntentFrameNavigation();
  const heroReady = renderIntentHero();
  renderIntentTimeline({ loadThumbnails: !deferTimelineThumbnails });
  renderIntentLabels();
  renderIntentCollaboration();
  if (deferTimelineThumbnails) {
    const renderedCase = data;
    heroReady.finally(() => {
      window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
        if (state.intentLabeling.caseData === renderedCase) activateIntentTimelineThumbnails();
      }));
    });
  }
}

async function loadIntentLabeling({ datasetId = "", caseId = "", offsetMs = null, assignees = null, experimentId = null, historyMode = "replace" } = {}) {
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
    renderIntentTopbarDatasetPicker("");
    intentSetSaveState("数据集媒体尚未挂载", "error");
    return;
  }
  const datasetChanged = intent.datasetId && intent.datasetId !== selectedDataset.id;
  intent.datasetId = selectedDataset.id;
  renderIntentTopbarDatasetPicker(intent.datasetId);
  if (datasetChanged) {
    intent.selectedAssignees = [];
    intent.assigneeDatasetId = "";
    intent.selectedExperimentId = "";
  }
  await loadIntentAssignees(intent.datasetId, assignees, experimentId);
  if (requestSeq !== intent.requestSeq) return;
  const assigneeParams = intentAssigneeSearchParams();
  let targetCaseId = caseId;
  if (targetCaseId && !/^cn[0-9]+_[0-9]+$/.test(targetCaseId)) {
    if (!/^cn[0-9]+$/.test(targetCaseId)) throw new Error("请输入完整的 Issue ID，例如 cn28896325。");
    const matchParams = intentAssigneeSearchParams();
    matchParams.set("q", targetCaseId);
    matchParams.set("page_size", "200");
    const matches = await api(intentApiUrl(`/api/intent-datasets/${encodeURIComponent(intent.datasetId)}/cases`, matchParams));
    if (requestSeq !== intent.requestSeq) return;
    const exact = (matches.items || []).filter((item) => item.issue_id === targetCaseId);
    if (exact.length !== 1) throw new Error(exact.length ? "该 Issue 对应多个 Episode，无法唯一打开。" : "该数据集中没有这个 Issue。");
    targetCaseId = exact[0].case_id;
  }
  if (!targetCaseId) {
    const allParams = new URLSearchParams(assigneeParams);
    allParams.set("status", "all");
    allParams.set("page_size", "1");
    const allCases = await api(intentApiUrl(`/api/intent-datasets/${encodeURIComponent(intent.datasetId)}/cases`, allParams));
    targetCaseId = allCases.items?.[0]?.case_id || "";
  }
  if (!targetCaseId) throw new Error("数据集中没有可标注 Case。");
  const data = await api(intentApiUrl(`/api/intent-datasets/${encodeURIComponent(intent.datasetId)}/cases/${encodeURIComponent(targetCaseId)}`, assigneeParams));
  if (requestSeq !== intent.requestSeq) return;
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
  const targetOffset = Number(offsetMs);
  const active = Number.isFinite(targetOffset)
    ? data.timepoints.find((item) => item.offset_ms === targetOffset)
    : null;
  intent.activeTimepointId = (active
    || data.timepoints.reduce((best, item) => !best || Math.abs(item.offset_ms) < Math.abs(best.offset_ms) ? item : best, null)
  )?.id || "";
  intent.selectedTimepointIds = intent.activeTimepointId ? [intent.activeTimepointId] : [];
  intent.selectionAnchorId = intent.activeTimepointId;
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
        completed: Boolean(payload.labels?.routing_default && payload.labels?.lane_change_default),
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
    && effective.routing
    && effective.laneChange
  ) {
    intent.autoAdvanceOnSave = true;
    intent.autoAdvanceTimepointId = active.id;
  }
}

function intentSetAggregate(axis, value) {
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
  const changed = selected.some((timepoint) => Boolean(intent.overrides[timepoint.id]));
  if (!changed) return;
  const previous = intentEditSnapshot();
  selected.forEach((timepoint) => delete intent.overrides[timepoint.id]);
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
  const caseId = direction < 0 ? data?.previous_case_id : data?.next_case_id;
  if (!caseId) return;
  await loadIntentLabeling({ datasetId: state.intentLabeling.datasetId, caseId, assignees: state.intentLabeling.selectedAssignees, historyMode: "push" });
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
  params.set("status", "all");
  params.set("page_size", "1");
  params.set("page", String(ordinal));
  const payload = await api(intentApiUrl(`/api/intent-datasets/${encodeURIComponent(intent.datasetId)}/cases`, params));
  const caseId = payload.items?.[0]?.case_id;
  if (!caseId) throw new Error(`找不到第 ${ordinal} 个 Issue。`);
  await loadIntentLabeling({
    datasetId: intent.datasetId,
    caseId,
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
  if (state.activePage !== "intent" || event.isComposing || event.repeat) return;
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
  const datasetId = state.intentLabeling.summaryDatasetId || state.intentLabeling.datasetId;
  if (!datasetId) return;
  const params = new URLSearchParams({ view, include_incomplete: "true" });
  const link = document.createElement("a");
  link.href = withBase(`/api/intent-datasets/${encodeURIComponent(datasetId)}/export?${params}`);
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function bindIntentLabelingEvents() {
  $("#intentOpenComments")?.addEventListener("click", () => {
    Promise.resolve(openIntentComments()).catch((error) => showToast(error.message, true));
  });
  $("#intentContributorList")?.addEventListener("click", (event) => {
    if (!event.target.closest("[data-intent-delete-mine]")) return;
    deleteMyIntentLabel().catch((error) => showToast(error.message, true));
  });
  $("#intentTimeline")?.addEventListener("wheel", (event) => {
    const timeline = event.currentTarget;
    if (event.ctrlKey || event.metaKey || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return;
    event.preventDefault();
    timeline.scrollLeft += event.deltaY;
  }, { passive: false });
  $("#intentTopbarDatasetSelect")?.addEventListener("change", (event) => {
    const datasetId = event.target.value;
    if (state.activePage === "intent-experiments") {
      state.intentLabeling.experimentsDatasetId = "";
      loadIntentExperimentAdmin({ datasetId, force: true })
        .catch((error) => showToast(error.message, true));
      return;
    }
    if (state.activePage === "intent-summary") {
      state.intentLabeling.summaryExperimentId = "";
      state.intentLabeling.summaryAssignees = [];
      state.intentLabeling.summaryPage = 1;
      loadIntentSummary({ datasetId, force: true }).catch((error) => showToast(error.message, true));
      return;
    }
    (async () => {
      await intentFlushSave();
      await loadIntentLabeling({ datasetId, assignees: [], historyMode: "push" });
    })().catch((error) => showToast(error.message, true));
  });
  $("#intentExperimentForm")?.addEventListener("submit", (event) => {
    createIntentExperiment(event).catch((error) => showToast(error.message, true));
  });
  $("#intentSummaryAxis")?.addEventListener("change", (event) => {
    state.intentLabeling.summaryAxis = event.target.value || "all";
    state.intentLabeling.summaryPage = 1;
    loadIntentSummary({ datasetId: state.intentLabeling.summaryDatasetId, force: true }).catch((error) => showToast(error.message, true));
  });
  $("#intentSummaryPageSize")?.addEventListener("change", (event) => {
    state.intentLabeling.summaryPageSize = Number(event.target.value) || 20;
    state.intentLabeling.summaryPage = 1;
    loadIntentSummary({ datasetId: state.intentLabeling.summaryDatasetId, force: true }).catch((error) => showToast(error.message, true));
  });
  $("#intentSummaryRefresh")?.addEventListener("click", () => loadIntentSummary({ datasetId: state.intentLabeling.summaryDatasetId, force: true }).catch((error) => showToast(error.message, true)));
  $("#intentExportCompact")?.addEventListener("click", () => downloadIntentExport("compact"));
  $("#intentExportExpanded")?.addEventListener("click", () => downloadIntentExport("expanded"));
  $("#intentSummaryReveal")?.addEventListener("click", () => {
    state.intentLabeling.summaryReveal = !state.intentLabeling.summaryReveal;
    loadIntentSummary({ datasetId: state.intentLabeling.summaryDatasetId, force: true }).catch((error) => showToast(error.message, true));
  });
  $("#intentSummaryPrevious")?.addEventListener("click", () => {
    state.intentLabeling.summaryPage = Math.max(1, state.intentLabeling.summaryPage - 1);
    loadIntentSummary({ datasetId: state.intentLabeling.summaryDatasetId, force: true }).catch((error) => showToast(error.message, true));
  });
  $("#intentSummaryNext")?.addEventListener("click", () => {
    state.intentLabeling.summaryPage += 1;
    loadIntentSummary({ datasetId: state.intentLabeling.summaryDatasetId, force: true }).catch((error) => showToast(error.message, true));
  });
  const submitSummaryCommentQuery = () => {
    const value = ($("#intentSummaryCommentQuery")?.value || "").trim().slice(0, 80);
    if (value === (state.intentLabeling.summaryCommentQuery || "")) return;
    state.intentLabeling.summaryCommentQuery = value;
    state.intentLabeling.summaryPage = 1;
    loadIntentSummary({ datasetId: state.intentLabeling.summaryDatasetId, force: true }).catch((error) => showToast(error.message, true));
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
  });
  $("#intentExperimentCaseCount")?.addEventListener("input", updateIntentExperimentEstimate);
  $("#intentExperimentOverlap")?.addEventListener("change", updateIntentExperimentEstimate);
  $("#intentExperimentReviewers")?.addEventListener("input", updateIntentExperimentEstimate);
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
