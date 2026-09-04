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
    datasetIds: overrides.datasetIds ?? intent.selectedDatasetIds,
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

function intentLabelScope() {
  return state.intentLabeling.caseData?.experiment?.label_scope || "all";
}

function intentAxisEnabled(axis) {
  const normalized = axis === "laneChange" ? "lane_change" : axis;
  const scope = intentLabelScope();
  return scope === "all" || scope === normalized;
}

function intentLabelsComplete(routing, laneChange) {
  return (!intentAxisEnabled("routing") || Boolean(routing))
    && (!intentAxisEnabled("laneChange") || Boolean(laneChange));
}

function intentAxisLabel(axis, value) {
  if (axis === "routing") return INTENT_ROUTING_LABELS[value] || "Routing 待填";
  return INTENT_LANE_LABELS[value] || "变道待填";
}

function intentLabelSummary(timepoint) {
  const effective = intentEffective(timepoint);
  return [
    intentAxisEnabled("routing") ? intentAxisLabel("routing", effective.routing) : "",
    intentAxisEnabled("laneChange") ? intentAxisLabel("laneChange", effective.laneChange) : "",
  ].filter(Boolean).join(" · ");
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

function intentChipMarkup(label, { pending = false, override = false, value = "" } = {}) {
  const classes = ["intent-chip"];
  if (pending) classes.push("is-pending");
  else {
    const tone = intentSummaryChipClass(value);
    if (tone) classes.push(tone);
    if (override) classes.push("is-override");
  }
  return `<b class="${classes.join(" ")}">${escapeHtml(label)}</b>`;
}

function intentTimepointLabelMarkup(timepoint) {
  const effective = intentEffective(timepoint);
  const override = timepoint ? intentOverride(timepoint.id) : null;
  const routingChip = intentAxisEnabled("routing") ? intentChipMarkup(intentAxisLabel("routing", effective.routing), {
    pending: !effective.routing,
    override: Boolean(override?.routing_intent),
    value: effective.routing,
  }) : "";
  const laneChip = intentAxisEnabled("laneChange") ? intentChipMarkup(intentAxisLabel("laneChange", effective.laneChange), {
    pending: !effective.laneChange,
    override: Boolean(override?.lane_change_intent),
    value: effective.laneChange,
  }) : "";
  return `<span class="intent-timepoint-labels${override ? " is-override" : ""}">${routingChip}${laneChip}</span>`;
}

function intentAvailableDatasets() {
  return (state.intentLabeling.datasets || []).filter((item) => item.available);
}

function applyIntentTopbarDatasetSelection(values) {
  const selected = parseFilterList(values);
  if (!selected.length) return;
  if (state.activePage === "intent-experiments") {
    loadIntentExperimentAdmin({ datasetIds: selected, force: true })
      .catch((error) => showToast(error.message, true));
    return;
  }
  const datasetId = selected.includes(state.intentLabeling.datasetId)
    ? state.intentLabeling.datasetId
    : selected[0];
  if (!datasetId) return;
  if (state.activePage === "intent-summary") {
    state.intentLabeling.summaryDatasetIds = selected;
    state.intentLabeling.summaryDatasetId = selected[0];
    state.intentLabeling.summaryExperimentId = "";
    state.intentLabeling.summaryAssignees = [];
    state.intentLabeling.summaryPage = 1;
    loadIntentSummary({ datasetIds: selected, force: true }).catch((error) => showToast(error.message, true));
    return;
  }
  (async () => {
    await intentFlushSave();
    await loadIntentLabeling({ datasetId, datasetIds: selected, assignees: [], historyMode: "push" });
  })().catch((error) => showToast(error.message, true));
}

function renderIntentTopbarDatasetPicker(selectedIds = null) {
  const picker = $("#intentTopbarDatasetPicker");
  if (!picker) return;
  const available = intentAvailableDatasets();
  const multiple = true;
  let selected = parseFilterList(selectedIds);
  if (!selected.length) {
    if (state.activePage === "intent-experiments") {
      selected = (state.intentLabeling.experimentDatasetIds || []).filter((id) => (
        available.some((item) => item.id === id)
      ));
      if (!selected.length) selected = available.map((item) => item.id);
    } else {
      const stored = state.activePage === "intent-summary"
        ? state.intentLabeling.summaryDatasetIds
        : state.intentLabeling.selectedDatasetIds;
      selected = (stored || []).filter((id) => available.some((item) => item.id === id));
      if (!selected.length) {
        const current = state.activePage === "intent-summary"
          ? state.intentLabeling.summaryDatasetId
          : state.intentLabeling.datasetId;
        selected = current && available.some((item) => item.id === current)
          ? [current]
          : (available[0] ? [available[0].id] : []);
      }
    }
  }
  selected = selected.filter((id) => available.some((item) => item.id === id));
  const singleSelection = selected[0] || available[0]?.id || "";
  renderMultiFilter(picker, {
    options: available.map((item) => ({ value: item.id, label: item.display_name })),
    selected,
    onlyThis: multiple,
    onChange: (values) => {
      let next = parseFilterList(values);
      if (!next.length && singleSelection) {
        next = [singleSelection];
        setMultiFilterValues(picker, next);
      }
      applyIntentTopbarDatasetSelection(next);
    },
  });
}

function renderIntentAssignmentFilter() {
  const intent = state.intentLabeling;
  const picker = $("#intentAssignmentPicker");
  if (!picker) return;
  const options = (intent.assignmentExperiments || []).map((item) => ({
    value: item.id,
    label: `${(intent.selectedDatasetIds || []).length > 1 ? `${item.dataset_id} · ` : ""}${item.name} · ${intentExperimentScopeLabel(item.label_scope)} · ${item.case_count} Case`,
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

async function loadIntentAssignees(datasetIds, requested = null, requestedExperimentId = null) {
  const intent = state.intentLabeling;
  const scopeIds = parseFilterList(datasetIds);
  const nextExperimentId = requestedExperimentId == null
    ? intent.selectedExperimentId
    : String(requestedExperimentId || "");
  const scopeKey = scopeIds.join(",");
  const cacheKey = `${scopeKey}:${nextExperimentId}`;
  if (intent.assigneeDatasetId !== cacheKey) {
    const params = new URLSearchParams();
    scopeIds.forEach((datasetId) => params.append("dataset_id", datasetId));
    if (nextExperimentId) params.set("experiment_id", nextExperimentId);
    const payload = await api(`/api/intent-assignees?${params}`);
    if ((intent.selectedDatasetIds || []).join(",") !== scopeKey) return;
    intent.assignees = payload.items || [];
    intent.assignmentExperiments = payload.experiments || [];
    const experimentIds = new Set(intent.assignmentExperiments.map((item) => item.id));
    intent.selectedExperimentId = experimentIds.has(nextExperimentId) ? nextExperimentId : "";
    intent.assigneeDatasetId = `${scopeKey}:${intent.selectedExperimentId}`;
  }
  const available = new Set(intent.assignees.map((item) => item.username));
  const currentUsername = String(state.session.username || "").toLowerCase();
  const selectionKey = `${scopeKey}:${intent.selectedExperimentId}`;
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

function intentExperimentScopeLabel(scope) {
  return ({
    routing: "仅 Routing 意图",
    lane_change: "仅变道意图",
    all: "Routing + 变道意图",
  })[scope] || "Routing + 变道意图";
}

function initializeIntentExperimentSelects() {
  const scope = $("#intentExperimentScopePicker");
  populateUiSelect(scope, [
    { value: "all", label: "Routing + 变道意图" },
    { value: "routing", label: "仅 Routing 意图" },
    { value: "lane_change", label: "仅变道意图" },
  ], $("#intentExperimentScope")?.value || "all");
  bindUiSelect(scope, { maxHeight: 220, maxWidth: 300 });
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
  const selected = getMultiFilterValues(container).filter((username) => (
    members.some((item) => item.username === username)
  ));
  renderMultiFilter(container, {
    options: members.map((item) => ({
      value: item.username,
      label: `${item.username} · ${item.role === "admin" ? "管理员" : "标注人"}`,
    })),
    selected,
    onChange: () => updateIntentExperimentEstimate(),
  });
}

function intentExperimentSuggestionContext() {
  const datasets = intentAvailableDatasets().filter((item) => (
    (state.intentLabeling.experimentDatasetIds || []).includes(item.id)
  ));
  const mode = $("#intentExperimentMode")?.value || "blind";
  const labelScope = $("#intentExperimentScope")?.value || "all";
  const requested = Math.max(1, Number($("#intentExperimentCaseCount")?.value) || 1);
  const overlap = Math.max(0, Number($("#intentExperimentOverlap")?.value) || 0);
  const reviewers = Math.max(1, Number($("#intentExperimentReviewers")?.value) || 1);
  const memberCount = document.querySelectorAll("#intentExperimentMembers input:checked").length;
  return { datasets, mode, labelScope, requested, overlap, reviewers, memberCount };
}

function ruleBasedIntentExperimentName(context) {
  const scope = context.datasets.map((item) => (
    String(item.display_name || item.id || "").split("·", 1)[0].trim()
  )).filter(Boolean).join("+") || "Routing";
  let mode = "全量盲标";
  if (context.mode !== "full") {
    const hasCrossReview = context.memberCount > 1 && context.reviewers > 1 && context.overlap > 0;
    mode = hasCrossReview
      ? `交叉${Math.round(context.overlap * 100)}%复核`
      : (context.memberCount === 1 ? "单人盲标" : "分工盲标");
  }
  const intentName = ({ routing: "Routing", lane_change: "变道意图", all: "Routing+变道意图" })[context.labelScope];
  return `${scope} ${intentName} ${mode} ${context.requested} Case`.slice(0, 80);
}

function renderIntentExperimentNameSuggestion(value, source = "rule", status = "ready") {
  const input = $("#intentExperimentName");
  if (!input) return;
  const statusNode = $("#intentExperimentNameStatus");
  const suggestion = String(value || "").trim();
  input.dataset.suggestion = suggestion;
  input.dataset.suggestionSource = source;
  input.placeholder = "例如 0206 Routing 双盲复核";
  if (statusNode) {
    statusNode.dataset.status = status;
    statusNode.textContent = status === "loading" ? "AI 推理中" : "";
    statusNode.title = status === "loading" ? "AI 正在后台优化实验名称" : "";
  }
}

let intentLabelDeleteConfirmPending = null;

function confirmIntentLabelDeletion({ username = "", caseId = "", own = false, count = 0 } = {}) {
  const dialog = $("#intentDeleteConfirmDialog");
  if (!dialog || intentLabelDeleteConfirmPending) return intentLabelDeleteConfirmPending || Promise.resolve(false);
  const context = $("#intentDeleteConfirmContext");
  if (context) {
    context.textContent = count > 0
      ? `确认批量删除选中的 ${count} 条当前标注？`
      : own
      ? `确认删除自己在 ${caseId || "当前 Case"} 的当前标注？`
      : `确认删除 ${username} 在 ${caseId} 的当前标注？`;
  }
  const title = $("#intentDeleteConfirmTitle");
  if (title) title.textContent = count > 0 ? "批量删除当前标注" : "删除当前标注";
  const submit = $("#intentDeleteConfirmSubmit");
  if (submit) submit.textContent = count > 0 ? `确认删除 ${count} 条` : "确认删除";
  dialog.returnValue = "";
  const pending = new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true });
  });
  intentLabelDeleteConfirmPending = pending.finally(() => {
    intentLabelDeleteConfirmPending = null;
  });
  dialog.showModal();
  return intentLabelDeleteConfirmPending;
}

function updateIntentExperimentNameSuggestion() {
  const intent = state.intentLabeling;
  const context = intentExperimentSuggestionContext();
  const fallback = ruleBasedIntentExperimentName(context);
  const input = $("#intentExperimentName");
  const hasManualDraft = input?.dataset.manualEdited === "true" && Boolean(input.value.trim());
  if (input && !hasManualDraft) {
    input.value = fallback;
    input.dataset.manualEdited = "false";
  }
  renderIntentExperimentNameSuggestion(fallback, "rule");
  window.clearTimeout(intent.experimentNameSuggestionTimer);
  if (!intent.experimentNameSuggestionAvailable || !state.session.can_manage_intent || !context.datasets.length) return;
  const draftName = hasManualDraft ? String(input?.value || "").trim() : "";
  const fingerprint = JSON.stringify({
    dataset_ids: context.datasets.map((item) => item.id),
    annotation_mode: context.mode,
    label_scope: context.labelScope,
    case_count: context.requested,
    overlap_ratio: context.overlap,
    overlap_reviewers: context.reviewers,
    member_count: context.memberCount,
    draft_name: draftName,
  });
  if (fingerprint === intent.experimentNameSuggestionFingerprint) return;
  const requestSeq = ++intent.experimentNameSuggestionSeq;
  renderIntentExperimentNameSuggestion(fallback, "rule", "loading");
  intent.experimentNameSuggestionTimer = window.setTimeout(async () => {
    intent.experimentNameSuggestionFingerprint = fingerprint;
    try {
      const payload = await api("/api/intent-experiments/name-suggestion", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: fingerprint,
      });
      if (requestSeq !== intent.experimentNameSuggestionSeq) return;
      const suggestion = String(payload.suggestion || "").trim();
      if (payload.source === "llm" && suggestion && input) {
        input.value = suggestion;
        input.dataset.manualEdited = "false";
        renderIntentExperimentNameSuggestion(suggestion, "llm");
      } else {
        renderIntentExperimentNameSuggestion(input?.value || fallback, "rule");
      }
    } catch (_error) {
      if (requestSeq === intent.experimentNameSuggestionSeq) {
        renderIntentExperimentNameSuggestion(input?.value || fallback, "rule");
      }
    }
  }, 650);
}

function updateIntentExperimentEstimate() {
  const output = $("#intentExperimentEstimate");
  if (!output) return;
  const members = Array.from(document.querySelectorAll("#intentExperimentMembers input:checked"));
  const datasets = intentAvailableDatasets().filter((item) => (
    (state.intentLabeling.experimentDatasetIds || []).includes(item.id)
  ));
  const requested = Math.max(0, Number($("#intentExperimentCaseCount")?.value) || 0);
  const mode = $("#intentExperimentMode")?.value || "blind";
  const labelScope = $("#intentExperimentScope")?.value || "all";
  const overlap = Math.max(0, Number($("#intentExperimentOverlap")?.value) || 0);
  const reviewerInput = $("#intentExperimentReviewers");
  if (reviewerInput) {
    reviewerInput.max = String(Math.max(1, members.length));
    if (Number(reviewerInput.value) > members.length) reviewerInput.value = String(Math.max(1, members.length));
  }
  const reviewers = Math.max(1, Math.min(members.length, Number(reviewerInput?.value) || 1));
  if (!datasets.length) {
    output.textContent = "请在顶栏至少选择 1 个数据集。";
    updateIntentExperimentNameSuggestion();
    return;
  }
  if (members.length < 1) {
    output.textContent = "至少选择 1 名成员。";
    updateIntentExperimentNameSuggestion();
    return;
  }
  let totalCases = 0;
  let totalAssignments = 0;
  datasets.forEach((item) => {
    const count = Math.min(requested || item.case_count || 0, item.case_count || 0);
    totalCases += count;
    const overlapCases = Math.round(count * overlap);
    totalAssignments += mode === "full"
      ? count * members.length
      : count + overlapCases * (reviewers - 1);
  });
  const datasetText = datasets.length > 1 ? `${datasets.length} 个数据集` : datasets[0].display_name;
  output.textContent = mode === "full"
    ? `${datasetText} · ${intentExperimentScopeLabel(labelScope)} · ${totalCases} 个 Case · ${members.length} 人全量复核 · 共 ${totalAssignments} 份独立任务`
    : `${datasetText} · ${intentExperimentScopeLabel(labelScope)} · ${totalCases} 个 Case · 交叉 ${Math.round(overlap * 100)}% · 共 ${totalAssignments} 份独立任务`;
  updateIntentExperimentNameSuggestion();
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
    const datasetName = (state.intentLabeling.datasets.find((dataset) => dataset.id === item.dataset_id) || {}).display_name || item.dataset_id || "";
    return `<article class="intent-experiment-item${item.status === "closed" ? " is-closed" : ""}" data-intent-experiment="${escapeHtml(item.id)}">
      <div><h4>${escapeHtml(item.name)}</h4><div class="intent-experiment-meta">${escapeHtml(datasetName)} · ${intentExperimentScopeLabel(item.label_scope)} · ${intentExperimentModeLabel(item.annotation_mode)}${overlap} · ${item.case_count} 个 Case · ${item.assignment_count} 份任务 · ${escapeHtml(item.created_by)}</div></div>
      <div class="intent-experiment-controls"><span class="intent-experiment-status">${item.status === "closed" ? "已关闭" : "进行中"}</span>${item.status === "active" && state.session.can_manage_intent ? '<button class="button button-quiet" type="button" data-close-intent-experiment>关闭实验</button>' : ""}</div>
      <div class="intent-experiment-member-stats">${members}</div>
    </article>`;
  }).join("") : '<div class="intent-experiment-empty"><span aria-hidden="true">◎</span><strong>所选数据集尚未创建实验</strong><p>在上方完成配置后，实验与每位成员的任务量会显示在这里。</p></div>';
  container.querySelectorAll("[data-close-intent-experiment]").forEach((button) => {
    button.addEventListener("click", () => {
      const experimentId = button.closest("[data-intent-experiment]")?.dataset.intentExperiment;
      if (!experimentId) return;
      closeIntentExperiment(experimentId).catch((error) => showToast(error.message, true));
    });
  });
}

async function loadIntentExperiments({ force = false, resetCaseCount = false } = {}) {
  const intent = state.intentLabeling;
  const requestedIds = [...(intent.experimentDatasetIds || [])];
  const cacheKey = requestedIds.slice().sort().join(",");
  if (!force && intent.experimentsDatasetId === cacheKey) {
    renderIntentExperiments();
    return;
  }
  const params = new URLSearchParams();
  requestedIds.forEach((id) => params.append("dataset_id", id));
  const payload = await api(`/api/intent-experiments${params.toString() ? `?${params}` : ""}`);
  if ((intent.experimentDatasetIds || []).join(",") !== requestedIds.join(",")) return;
  intent.experiments = payload.items || [];
  intent.experimentMembers = payload.eligible_members || [];
  intent.experimentNameSuggestionAvailable = Boolean(payload.name_suggestion?.llm_available);
  intent.experimentsDatasetId = cacheKey;
  const selectedDatasets = intentAvailableDatasets().filter((item) => requestedIds.includes(item.id));
  const countInput = $("#intentExperimentCaseCount");
  if (countInput) {
    const maxCount = Math.max(1, ...selectedDatasets.map((item) => Number(item.case_count) || 1));
    countInput.max = String(maxCount);
    const currentCount = Number(countInput.value) || 0;
    if (resetCaseCount || currentCount < 1 || currentCount > maxCount) {
      countInput.value = String(maxCount);
    }
  }
  renderIntentExperimentMembers();
  renderIntentExperiments();
  updateIntentExperimentEstimate();
}

async function loadIntentExperimentAdmin({ datasetId = "", datasetIds = null, force = false } = {}) {
  const intent = state.intentLabeling;
  const previousScope = [...(intent.experimentDatasetIds || [])].sort().join(",");
  if (!intent.datasets.length) {
    const payload = await api("/api/intent-datasets");
    intent.datasets = payload.items || [];
  }
  const available = intentAvailableDatasets();
  if (!available.length) throw new Error("没有可用于实验分配的数据集。");
  let selected;
  if (datasetIds != null) {
    selected = parseFilterList(datasetIds);
  } else if (datasetId) {
    selected = [datasetId];
  } else {
    selected = [...(intent.experimentDatasetIds || [])];
    if (!selected.length && available[0]) selected = [available[0].id];
  }
  selected = selected.filter((id) => available.some((item) => item.id === id));
  const nextScope = [...selected].sort().join(",");
  intent.experimentDatasetIds = selected;
  intent.experimentDatasetId = selected[0] || "";
  renderIntentTopbarDatasetPicker(selected);
  await loadIntentExperiments({ force, resetCaseCount: previousScope !== nextScope });
  if (state.activePage === "intent-experiments") {
    const params = new URLSearchParams();
    selected.forEach((id) => params.append("dataset", id));
    history.replaceState(
      { page: "intent-experiments", datasetId: selected[0] || "", datasetIds: selected },
      "",
      `${withBase("/intent-experiments")}${params.toString() ? `?${params}` : ""}`
    );
  }
}

async function createIntentExperiment(event) {
  event?.preventDefault();
  const intent = state.intentLabeling;
  const members = Array.from(document.querySelectorAll("#intentExperimentMembers input:checked"))
    .map((input) => input.value);
  const datasetIds = [...(intent.experimentDatasetIds || [])];
  if (!datasetIds.length) {
    showToast("请在顶栏至少选择 1 个数据集。", true);
    return;
  }
  const button = $("#intentCreateExperiment");
  if (button) button.disabled = true;
  try {
    const result = await api("/api/intent-experiments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dataset_id: datasetIds[0],
        dataset_ids: datasetIds,
        name: $("#intentExperimentName")?.value.trim() || "",
        annotation_mode: $("#intentExperimentMode")?.value || "blind",
        label_scope: $("#intentExperimentScope")?.value || "all",
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
    const created = result.experiments || (result.experiment ? [result.experiment] : []);
    showToast(created.length > 1
      ? `已在 ${created.length} 个数据集创建实验，任务分配快照已保存。`
      : "实验已创建，任务分配快照已保存。", false);
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
