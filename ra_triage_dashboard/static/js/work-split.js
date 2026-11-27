let workSplitDraft = null;

function workSplitFilters() {
  return workSplitDraft ? { ...workSplitDraft.filters } : currentReviewFilterPayload();
}

function workSplitTotal() {
  return Number(workSplitDraft?.total ?? state.caseTotal ?? 0);
}

/* ra_triage_dashboard/static/js/work-split.js
 * Admin Review work-split: persist assignee ownership and gallery filters.
 * Loaded as a classic script (shared global scope).
 */
function workAssigneeRouteSelection() {
  const params = new URLSearchParams(window.location.search);
  return parseFilterList(params.get("work_assignee") || params.get("assignee") || "");
}

function renderReviewTaskContext() {
  if (typeof window !== "undefined" && (window.__RA_REACT_WORKBENCH__?.ownsPage?.("review") || window.__RA_REACT_OWNED_PAGES__?.includes?.("review"))) return;
  bindUiInfoPopovers($("#filterForm"));
  const task = state.reviewTaskContext;
  const errorCard = $("#reviewTaskContextError");
  if (errorCard) {
    errorCard.hidden = !state.reviewTaskContextError;
    if (state.reviewTaskContextError) {
      $("#reviewTaskContextErrorMessage").textContent = state.reviewTaskContextError.message || "任务上下文暂时不可用。";
      $("#reviewTaskContextErrorId").textContent = state.reviewWorkSplitId || "—";
    }
  }
  const summary = $("#reviewTaskSummary");
  const exit = $("#reviewTaskContextExit");
  renderReviewProgressFilter();
  if (summary) {
    summary.hidden = !task;
    summary.textContent = task
      ? `${task.legacy_no_run ? uiText("历史任务", "Historical task") : (task.name || uiText("当前任务", "Current task"))} · ${Number(task.issue_count || 0)} ${uiText("个 Issue", "Issues")}${task.supplemental_only ? uiText(" · 任务外补充", " · Supplemental review") : ""}`
      : "";
    summary.title = task?.legacy_no_run
      ? uiText("历史无 Run 任务，仅查看原分配范围", "Historical task without a Run; original assignment scope only")
      : task ? `${task.workflow_mode === "model_review_and_case_label" ? uiText("联合复核", "Combined review") : uiText("仅判错复核", "Model review only")} · ${task.supplemental_only ? uiText("未分配：提交不计任务进度 · ", "Unassigned: submissions do not count toward task progress · ") : ""}${task.id || ""}` : "";
    const details = $("#reviewTaskDetails");
    if (details) { details.hidden = !task; details.textContent = summary.title; }
  }
  if (exit) exit.hidden = !task || Boolean(state.reviewTaskContextError);
  if (!task) return;
  const runTrigger = $("#modelRunPickerTrigger");
  if (runTrigger) {
    runTrigger.disabled = true;
    runTrigger.title = task.legacy_no_run
      ? uiText("历史无 Run 任务仅用于查看原分配范围，退出任务后可选择模型 Run", "Exit this historical task to choose a model Run.")
      : uiText("当前复核任务已锁定模型 Run", "The current review task locks the model Run.");
  }
}

function renderReviewTaskLoading(splitId = state.reviewWorkSplitId) {
  if (typeof window !== "undefined" && (window.__RA_REACT_WORKBENCH__?.ownsPage?.("review") || window.__RA_REACT_OWNED_PAGES__?.includes?.("review"))) return;
  const list = $("#issueList");
  if (!list) return;
  list.innerHTML = Array.from({ length: 8 }, (_, index) => `<article class="issue-card issue-card-skeleton" aria-label="正在加载任务范围"><div class="issue-thumbnail"></div><div class="issue-card-body"><span></span><span></span><small>正在加载任务范围 · ${escapeHtml(String(splitId || "").slice(0, 18))}${index ? "" : "…"}</small></div></article>`).join("");
  $("#galleryResultSummary").textContent = "正在加载任务范围";
  $("#caseCount").textContent = "—";
  ["#exportFilteredIssuesButton", "#splitFilteredButton", "#predictFilteredButton"].forEach((selector) => {
    const button = $(selector);
    if (button) { button.disabled = true; button.title = "等待任务范围加载完成"; }
  });
}

function clearReviewTaskContext({ clearRun = true } = {}) {
  state.reviewTaskContextRequestSeq = Number(state.reviewTaskContextRequestSeq || 0) + 1;
  state.reviewWorkSplitId = "";
  state.reviewTaskView = '';
  state.reviewTaskProgress = [];
  state.availableReviewWorkSplitId = "";
  state.reviewTaskContext = null;
  state.reviewTaskContextError = null;
  state.reviewTaskContextLoading = false;
  state.reviewLegacyNoRunTask = false;
  if (clearRun) state.selectedRunId = "";
  renderReviewTaskContext();
  const runTrigger = $("#modelRunPickerTrigger");
  if (runTrigger) { runTrigger.disabled = false; runTrigger.title = ""; }
  renderReviewWorkSplitPicker?.("");
}

async function exitReviewTaskContext({ reload = true } = {}) {
  clearReviewTaskContext({ clearRun: true });
  const nextUrl = pageUrl("review", currentReviewRouteOptions({ workSplitId: "", runId: "", issue: "", casePage: 1 }));
  window.history.replaceState(window.history.state || {}, "", nextUrl);
  if ($("#modelRunFilter")) $("#modelRunFilter").value = "";
  if (!reload) return;
  await loadRuns({ preserveEmpty: true });
  await loadCases({ keepSelection: false, page: 1 });
  await loadOverview();
}

async function exitReviewTaskAndOpenRunPicker() {
  await exitReviewTaskContext({ reload: true });
  const trigger = $("#modelRunPickerTrigger");
  if (!trigger) return;
  trigger.focus({ preventScroll: false });
  trigger.click();
}

async function loadReviewTaskContext(splitId, { route = null } = {}) {
  let normalized = String(splitId || "").trim();
  if (!normalized) {
    clearReviewTaskContext({ clearRun: false });
    return null;
  }
  if (state.activePage !== "review") return null;
  const pageContext = capturePageContext();
  const requestSeq = Number(state.reviewTaskContextRequestSeq || 0) + 1;
  state.reviewTaskContextRequestSeq = requestSeq;
  const isCurrent = () => requestSeq === state.reviewTaskContextRequestSeq && isPageContextCurrent(pageContext);
  state.reviewWorkSplitId = normalized;
  state.reviewTaskContextLoading = true;
  state.reviewTaskContextError = null;
  renderReviewTaskLoading(normalized);
  renderReviewTaskContext();
  try {
    const result = await api(`/api/review-task-context/${encodeURIComponent(normalized)}?${new URLSearchParams({...(state.reviewTaskView?{task_view:state.reviewTaskView}:{}),issue_id:route?.issue||new URLSearchParams(window.location.search).get('issue')||''})}`);
    if (!isCurrent()) return null;
    const task = result.task || {};
    if(task.id && task.id!==normalized){normalized=task.id;state.reviewWorkSplitId=normalized;}
    state.reviewTaskContext = task;
    state.reviewWorkflowMode = task.workflow_mode || 'model_review_only';
    state.reviewTaskContextLoading = false;
    state.reviewLegacyNoRunTask = Boolean(task.legacy_no_run);
    const baselineIds = (task.baseline_ids || []).map(String).filter(Boolean);
    const previous = normalizeBaselineIds(state.selectedBaselineIds).join(",");
    if (baselineIds.length) {
      state.selectedBaselineIds = baselineIds;
      persistBaselineIds(baselineIds);
      renderBaselinePicker();
      renderConfig();
    }
    state.selectedRunId = task.model_run_id || "";
    if (route) {
      route.workflowMode = state.reviewWorkflowMode;
      route.runId = task.model_run_id || "none";
      route.workSplitId = normalized;
    }
    const nextUrl = new URL(pageUrl("review", {
      ...currentReviewRouteOptions({ workSplitId: normalized, runId: task.model_run_id || "", casePage: 1 }),
      baselines: baselineIds,
    }), window.location.origin);
    if (baselineIds.length) nextUrl.searchParams.set("baselines", baselineIds.join(","));
    window.history.replaceState(window.history.state || {}, "", `${nextUrl.pathname}${nextUrl.search}`);
    if (previous && baselineIds.length && previous !== baselineIds.join(",")) {
      showToast(`已切换至任务数据集 ${baselineIds.join("+")}`);
    }
    renderReviewTaskContext();
    renderReviewWorkSplitPicker(normalized);
    return task;
  } catch (error) {
    if (!isCurrent()) return null;
    state.reviewTaskContextLoading = false;
    state.reviewTaskContextError = error;
    if ($("#issueList")) $("#issueList").innerHTML = "";
    if ($("#galleryResultSummary")) $("#galleryResultSummary").textContent = "任务范围加载失败";
    if ($("#caseCount")) $("#caseCount").textContent = "—";
    ["#exportFilteredIssuesButton", "#splitFilteredButton", "#predictFilteredButton"].forEach((selector) => {
      const button = $(selector);
      if (button) { button.disabled = true; button.title = `任务范围加载失败：${error.message || "未知错误"}`; }
    });
    renderReviewTaskContext();
    throw error;
  }
}

function workAssigneeFilterSelection() {
  const values = parseFilterList(getMultiFilterValues($("#workAssigneeFilter")));
  // The custom facet is rebuilt after an asynchronous request.  During that
  // short window it has no checked inputs, but the active Review URL still
  // carries the operator's intended task-assignee filter.
  if (values.length || state.activePage !== "review") return values;
  return workAssigneeRouteSelection();
}

function persistWorkAssigneeFilterRoute(values) {
  if (state.activePage !== "review") return;
  const selection = parseFilterList(
    values === undefined ? workAssigneeFilterSelection() : values
  );
  const nextUrl = pageUrl(
    "review",
    currentReviewRouteOptions({ workAssignee: selection })
  );
  const currentUrl = `${window.location.pathname}${window.location.search}`;
  if (nextUrl === currentUrl) return;
  window.history.replaceState(
    { ...(window.history.state || {}), page: "review" },
    "",
    nextUrl
  );
}

function workSplitOptionLabel(splitId) {
  const value = String(splitId || "").trim();
  if (!value) return uiText("综合结果", "Combined results");
  const task = state.reviewTaskContext;
  if (task && value === String(task.id || "")) {
    const count = Number(task.issue_count || 0);
    return `${task.name || uiText("当前任务", "Current task")} · ${uiText(`${count} 个 Issue`, `${count} ${count === 1 ? "issue" : "issues"}`)}`;
  }
  return uiText("当前复核任务", "Current review task");
}

function analysisWorkSplitOptionLabel(item) {
  const splitId = String(item?.split_id || "").trim();
  const date = item?.created_at ? formatTime(item.created_at) : "";
  const progress = `${Number(item?.completed_count || 0)}/${Number(item?.assignment_count || 0)}`;
  const owner = String(item?.created_by || "").trim();
  return [item?.name || splitId.slice(0, 14), progress, date, owner].filter(Boolean).join(" · ");
}

function renderWorkSplitScopePicker(rootSelector, selected, available, onChange) {
  const root = $(rootSelector);
  if (!root) return;
  const known = String(selected || available || "").trim();
  const options = [{ value: "", label: workSplitOptionLabel("") }];
  if (known) options.push({ value: known, label: workSplitOptionLabel(known) });
  populateUiSelect(root, options, String(selected || ""));
  bindUiSelect(root, { onChange, maxHeight: 180, maxWidth: 360 });
}

let reviewTaskOptions = [];
let reviewTaskOptionsLoadedAt = 0;
let reviewTaskOptionsRequest = null;
let reviewTaskOptionsError = "";

function renderReviewTaskPickerHint() {
  const hint = $("#reviewTaskPickerHint");
  if (!hint) return;
  hint.hidden = !reviewTaskOptionsError && (reviewTaskOptions.length > 0 || !reviewTaskOptionsLoadedAt);
  hint.textContent = reviewTaskOptionsError
    ? uiText("任务列表加载失败：", "Failed to load tasks: ") + reviewTaskOptionsError
    : uiText("暂无分配给当前账号的进行中任务；综合结果不绑定任务。", "No active tasks assigned to this account. Combined results is not bound to a task.");
}

async function loadReviewTaskOptions({ force = false } = {}) {
  if (reviewTaskOptionsRequest) return reviewTaskOptionsRequest;
  if (!force && Date.now() - reviewTaskOptionsLoadedAt < 30000) return;
  reviewTaskOptionsRequest = (async () => {
    try {
      const result = await api("/api/review-work-splits?all_baselines=true&assigned_to_me=true");
      reviewTaskOptions = (result.items || []).filter((item) => !["superseded", "cancelled"].includes(item.lifecycle) && item.can_review !== false);
      reviewTaskOptionsLoadedAt = Date.now();
      reviewTaskOptionsError = "";
      renderReviewWorkSplitPicker(state.reviewWorkSplitId, { load: false });
    } catch (error) {
      reviewTaskOptionsError = error.message;
      renderReviewTaskPickerHint();
    } finally {
      reviewTaskOptionsRequest = null;
    }
  })();
  return reviewTaskOptionsRequest;
}

function renderReviewWorkSplitPicker(selected = state.reviewWorkSplitId, { load = true } = {}) {
  if (typeof window !== "undefined" && (window.__RA_REACT_WORKBENCH__?.ownsPage?.("review") || window.__RA_REACT_OWNED_PAGES__?.includes?.("review"))) return;
  bindUiInfoPopovers($("#filterForm"));
  const root = $("#reviewTaskPicker") || $("#reviewWorkSplitPicker");
  if (!root) return;
  const known = String(selected || state.availableReviewWorkSplitId || "");
  const options = [{ value: "", label: workSplitOptionLabel("") },
    ...reviewTaskOptions.map((item) => ({
      value: item.split_id,
      label: `${item.name || uiText("复核任务", "Review task")} · ${Number(item.completed_count || 0)}/${Number(item.assignment_count || 0)}`,
    })),
  ];
  if (known && !options.some((item) => item.value === known)) {
    options.push({ value: known, label: workSplitOptionLabel(known) });
  }
  populateUiSelect(root, options, String(selected || ""));
  bindUiSelect(root, {
    onChange: (value) => {
      if (!value) {
        exitReviewTaskContext().catch((error) => showToast(error.message, true));
        return;
      }
      const item = reviewTaskOptions.find((task) => task.split_id === value);
      if (item) {
        // Reuse task-card navigation: reset stale filters and hydrate the task's
        // frozen datasets/Run before loading Issue detail or enabling submit.
        window.location.assign(pageUrl("review", reviewAssignmentRouteOptions({
          ...item, baseline_ids: item.baselines, assigned_to_me: true,
        }, "review")));
        return;
      }
      loadReviewTaskContext(value).then(() => loadCases({ keepSelection: false, page: 1 }))
        .catch((error) => showToast(error.message, true));
    },
    maxHeight: 320, minWidth: 480,
  });
  renderReviewTaskPickerHint();
  if (!root.dataset.taskOptionsBound) {
    root.dataset.taskOptionsBound = "true";
    root.addEventListener("focusin", () => loadReviewTaskOptions());
  }
  if (load) void loadReviewTaskOptions();
}

function effectiveReviewWorkflowMode(caseData = state.selectedCase) {
  const assignment = caseData?.review_assignment || {};
  if (state.reviewWorkSplitId && assignment.split_id === state.reviewWorkSplitId) {
    return assignment.workflow_mode || "model_review_only";
  }
  return state.reviewWorkflowMode || "model_review_and_case_label";
}

function syncReviewWorkflowMode(caseData = state.selectedCase) {
  if (typeof window !== "undefined" && (window.__RA_REACT_WORKBENCH__?.ownsPage?.("review") || window.__RA_REACT_OWNED_PAGES__?.includes?.("review"))) {
    return effectiveReviewWorkflowMode(caseData);
  }
  const select = $("#reviewWorkflowMode");
  const field = $("#reviewWorkflowModeField");
  if (!select || !field) return effectiveReviewWorkflowMode(caseData);
  const identityPending = Boolean(state.session?.identity_pending);
  const canCombine = hasDashboardWriteRole();
  const locked = Boolean(state.reviewWorkSplitId && caseData?.review_assignment?.split_id === state.reviewWorkSplitId);
  const mode = locked
    ? (caseData.review_assignment.workflow_mode || "model_review_only")
    : (canCombine || identityPending ? state.reviewWorkflowMode : "model_review_only");
  state.reviewWorkflowMode = mode;
  select.value = mode;
  select.disabled = locked || !canCombine;
  select.title = locked
    ? uiText("页面模式由当前任务锁定", "The current task locks this mode")
    : !canCombine ? uiText("需要模型复核与 问题标注双重写权限", "Model review and Issue labeling write permissions are required") : "";
  field.hidden = !canCombine && !locked;
  $("#reviewWorkflowModeHint")?.toggleAttribute("hidden", !locked);
  enhanceNativeUiSelect(select);
  return mode;
}

function renderAnalysisWorkSplitPicker(selected = state.reviewAnalysis.workSplitId) {
  if (typeof window !== "undefined" && (window.__RA_REACT_WORKBENCH__?.ownsPage?.("analysis") || window.__RA_REACT_OWNED_PAGES__?.includes?.("analysis"))) return;
  bindUiInfoPopovers($("#reviewAnalysisPage"));
  const root = $("#analysisWorkSplitPicker");
  if (!root) return;
  const known = String(selected || state.reviewAnalysis.availableWorkSplitId || "").trim();
  const options = [
    { value: "", label: workSplitOptionLabel("") },
    ...(state.reviewAnalysis.workSplitOptions || []).map((item) => ({
      value: String(item.split_id || ""),
      label: analysisWorkSplitOptionLabel(item),
    })),
  ];
  if (known && !options.some((item) => item.value === known)) {
    options.push({ value: known, label: workSplitOptionLabel(known) });
  }
  populateUiSelect(root, options, String(selected || ""));
  bindUiSelect(root, {
    onChange: (value) => {
      state.reviewAnalysis.workSplitId = value || "";
      state.reviewAnalysis.taskView = '';
      if (value) state.reviewAnalysis.availableWorkSplitId = value;
      scheduleAnalysisFilterReload?.(0);
    },
    maxHeight: 320,
    maxWidth: 520,
  });
}

let analysisWorkSplitsRequestSeq = 0;
async function loadAnalysisWorkSplits({ force = false } = {}) {
  if (typeof window !== "undefined" && (window.__RA_REACT_WORKBENCH__?.ownsPage?.("analysis") || window.__RA_REACT_OWNED_PAGES__?.includes?.("analysis"))) return [];
  const requestSeq = ++analysisWorkSplitsRequestSeq;
  const runId = state.selectedRunId || $("#analysisRunFilter")?.value || "";
  const baselines = selectedBaselineQueryValue();
  const key = `${runId}|${baselines}`;
  if (!force && state.reviewAnalysis.workSplitOptionsKey === key) {
    renderAnalysisWorkSplitPicker(state.reviewAnalysis.workSplitId);
    return state.reviewAnalysis.workSplitOptions;
  }
  const params = new URLSearchParams();
  if (runId) params.set("model_run_id", runId);
  if (baselines) params.set("baselines", baselines);
  const result = await api(`/api/review-work-splits?${params.toString()}`);
  if (requestSeq !== analysisWorkSplitsRequestSeq
      || runId !== (state.selectedRunId || $("#analysisRunFilter")?.value || "")
      || baselines !== selectedBaselineQueryValue()) return [];
  state.reviewAnalysis.workSplitOptionsKey = key;
  state.reviewAnalysis.workSplitOptions = result.items || [];
  renderAnalysisWorkSplitPicker(state.reviewAnalysis.workSplitId);
  return state.reviewAnalysis.workSplitOptions;
}

function currentReviewFilterPayload() {
  const reviewOwned = typeof window !== "undefined" && Boolean(
    window.__RA_REACT_WORKBENCH__?.ownsPage?.("review") ||
    window.__RA_REACT_OWNED_PAGES__?.includes?.("review")
  );
  const rf = reviewOwned && state._reactReviewFilters ? state._reactReviewFilters : null;
  if (rf) {
    return {
      search: rf.search || "",
      gt_label: joinFilterList(rf.gtLabel),
      model_label: joinFilterList(rf.modelLabel),
      annotation_author: joinFilterList(rf.annotationAuthor),
      review_status: joinFilterList(rf.reviewStatus),
      task_progress: joinFilterList(selectedCombinedTaskProgress()),
      label_state: joinFilterList(rf.labelStates),
      gt_relation: joinFilterList(rf.gtRelations),
      issue_tags: joinFilterList(selectedReviewIssueTags()),
      target_group: state.reviewTargetGroup || "",
      comment_state: rf.commentState || "all",
      exclusion: rf.exclusion || "all",
      model_run_id: state.selectedRunId || "",
      comparison: state.selectedRunId ? (state.reviewComparisonStatus || "all") : "all",
      failure_only: false,
      missing_evidence: state.clusterKey || "",
      ...(state.reviewAnalysisScope && { analysis_scope: state.reviewAnalysisScope }),
      issue_ids: (state.reviewIssueIds || []).join(","),
      baselines: selectedBaselineQueryValue(),
      work_assignee: "",
      work_split_id: state.reviewWorkSplitId || "",
      task_view: state.reviewWorkSplitId ? (state.reviewTaskView || "") : "",
    };
  }
  return {
    search: $("#searchInput")?.value.trim() || "",
    gt_label: joinFilterList(getMultiFilterValues($("#gtFilter"))),
    model_label: joinFilterList(getMultiFilterValues($("#annotationFilter"))),
    annotation_author: joinFilterList(getMultiFilterValues($("#reviewerFilter"))),
    review_status: joinFilterList(selectedModelReviewStatuses()),
    task_progress: joinFilterList(selectedCombinedTaskProgress()),
    label_state: joinFilterList(selectedReviewLabelStates()),
    gt_relation: joinFilterList(selectedReviewGtRelations()),
    issue_tags: joinFilterList(selectedReviewIssueTags()),
    target_group: state.reviewTargetGroup || '',
    comment_state:
      typeof selectedReviewDiscussionFilter === "function"
        ? selectedReviewDiscussionFilter()
        : "all",
    exclusion:
      typeof selectedReviewExclusionFilter === "function"
        ? selectedReviewExclusionFilter()
        : "all",
    model_run_id: state.selectedRunId || $("#modelRunFilter")?.value || "",
    comparison:
      state.selectedRunId || $("#modelRunFilter")?.value
        ? selectedReviewComparisonStatus()
        : "all",
    failure_only: false,
    missing_evidence: state.clusterKey || "",
    ...(state.reviewAnalysisScope && { analysis_scope: state.reviewAnalysisScope }),
    issue_ids: (state.reviewIssueIds || []).join(","),
    baselines: selectedBaselineQueryValue(),
    // When creating a new split, ignore current assignee filter so the pool
    // is the full filtered set unless the admin intentionally kept it.
    work_assignee: "",
    work_split_id: state.reviewWorkSplitId || "",
    task_view: state.reviewWorkSplitId ? (state.reviewTaskView || '') : '',
  };
}

function workAssigneeOptionsWithSelected(options, selected) {
  const known = new Set(options.map((item) => String(item.value || "")));
  const retained = parseFilterList(selected)
    .filter((name) => !known.has(name))
    .map((name) => ({
      value: name,
      // A task owner can be absent from the current facet after changing Run
      // or baseline. Keep the URL-restored choice visible and removable.
      label: `${name} · ${uiText("当前筛选", "Current filter")}`,
    }));
  return [...options, ...retained];
}

function renderWorkAssigneeFilter(selected = workAssigneeFilterSelection()) {
  if (typeof window !== "undefined" && (window.__RA_REACT_WORKBENCH__?.ownsPage?.("review") || window.__RA_REACT_OWNED_PAGES__?.includes?.("review"))) return;
  const root = $("#workAssigneeFilter");
  if (!root) return;
  const items = Array.isArray(state.workAssignees) ? state.workAssignees : [];
  const options = [
    { value: "__none__", label: t("work.unassigned") },
    ...items.map((item) => ({
      value: item.username,
      label: `${item.username} · ${Number(item.issue_count || 0)}`,
    })),
  ];
  renderMultiFilter(root, {
    options: workAssigneeOptionsWithSelected(options, selected),
    selected,
    onChange: (values) => {
      // Persist before triggering the async facet refresh.  Any in-flight
      // detail navigation or top-bar refresh then serializes the same filter.
      persistWorkAssigneeFilterRoute(values);
      scheduleReviewFilterReload?.(0);
    },
  });
}

async function loadWorkAssignees() {
  const requestSeq = ++state.workAssigneeRequestSeq;
  try {
    const params = new URLSearchParams();
    Object.entries(currentReviewFilterPayload()).forEach(([key, value]) => {
      // Owner counts describe the assigned scope, not the shrinking todo queue.
      if (key === "work_assignee" || key === "task_progress" || key === "failure_only" || !value) return;
      params.set(key, String(value));
    });
    const query = params.toString();
    const result = await api(`/api/work-assignees${query ? `?${query}` : ""}`);
    if (requestSeq !== state.workAssigneeRequestSeq) return;
    state.workAssignees = result.items || [];
    renderWorkAssigneeFilter(workAssigneeFilterSelection());
  } catch (_error) {
    // Filter remains usable with default options.
  }
}

function updateWorkSplitAdminVisibility() {
  if (typeof window !== "undefined" && (window.__RA_REACT_WORKBENCH__?.ownsPage?.("review") || window.__RA_REACT_OWNED_PAGES__?.includes?.("review"))) return;
  const button = $("#splitFilteredButton");
  const isAdmin = Boolean(state.session?.is_admin);
  if (typeof renderReviewAssignmentPermissions === "function") renderReviewAssignmentPermissions();
  const analysisField = $("#analysisWorkAgreementField");
  // Agreement is a read-only analysis filter and is available to every
  // viewer.  Only assignment/redistribution remains administrator-only.
  if (analysisField) analysisField.hidden = false;
  if (!button) return;
  button.hidden = !isAdmin;
  if (!isAdmin || !state.selectedRunId) {
    button.disabled = true;
    button.title = !state.selectedRunId
      ? "请先选择 Model Run；若只做 Case 标签，请前往 问题标注 > 实验分配"
      : "仅管理员可创建复核任务";
  }
}

let workSplitScopeSeq = 0;

function workSplitHasExtraGalleryFilters(filters = {}) {
  const keys = ["search", "issue_ids", "gt_label", "model_label", "annotation_author",
    "review_status", "label_state", "gt_relation", "issue_tags", "target_group",
    "work_assignee", "work_split_id", "missing_evidence"];
  return keys.some((key) => {
    const val = filters[key];
    return Array.isArray(val) ? val.length > 0 : Boolean(String(val || "").trim());
  }) || Boolean(filters.comment_state && filters.comment_state !== "all")
    || Boolean(filters.exclusion && filters.exclusion !== "all");
}

function renderWorkSplitScopeCount(total, filters = {}) {
  const node = $("#workSplitScopeCount");
  if (!node) return;
  if (!filters?.model_run_id) {
    node.textContent = uiText("请先选择 Run", "Select a Run");
    return;
  }
  const n = new Intl.NumberFormat(i18nLocale()).format(Math.max(0, Number(total) || 0));
  const extra = workSplitHasExtraGalleryFilters(filters);
  node.textContent = extra
    ? uiText(`图库筛选 · ${n} 个 Case`, `Gallery · ${n} cases`)
    : uiText(`${n} 个 Case`, `${n} cases`);
}

async function populateWorkSplitRunSelect(preferredRunId = "") {
  const runSelect = $("#workSplitModelRun");
  let data = null;
  try {
    data = await api(withBaselineQuery("/api/model-runs"));
  } catch (_) {
    data = { items: state.modelRuns || [], default_model_run_id: "" };
  }
  const runs = Array.isArray(data?.items) ? data.items : [];
  if (runs.length) state.modelRuns = runs;
  const matching = runs.filter((run) => Number(run.baseline_prediction_count || 0) > 0);
  const ordered = matching.length
    ? [...matching, ...runs.filter((run) => !matching.includes(run))]
    : runs;
  let chosen = "";
  if (preferredRunId && ordered.some((r) => r.id === preferredRunId)) chosen = preferredRunId;
  else if (data?.default_model_run_id && matching.some((r) => r.id === data.default_model_run_id)) chosen = data.default_model_run_id;
  else if (state.selectedRunId && matching.some((r) => r.id === state.selectedRunId)) chosen = state.selectedRunId;
  else chosen = matching[0]?.id || ordered[0]?.id || "";
  if (runSelect) {
    runSelect.disabled = !ordered.length;
    if (!ordered.length) {
      runSelect.innerHTML = `<option value="">${escapeHtml(uiText("当前数据集暂无 Model Run", "No Model Run in this dataset"))}</option>`;
      runSelect.value = "";
    } else {
      runSelect.innerHTML = ordered.map((run) => {
        const count = Number(run.baseline_prediction_count || 0);
        const label = `${run.name} · ${count} ${uiText("例", "cases")}`;
        return `<option value="${escapeHtml(run.id)}">${escapeHtml(label)}</option>`;
      }).join("");
      runSelect.value = chosen;
    }
    enhanceNativeUiSelect(runSelect);
  }
  return { runId: chosen, runs: ordered };
}

async function refreshWorkSplitScope() {
  if (!$("#workSplitPanel") || $("#workSplitPanel").hidden) return;
  const runId = $("#workSplitModelRun")?.value || "";
  const comparison = $("#workSplitComparison")?.value || "all";
  const baselines = selectedBaselineQueryValue();
  const prevFilters = workSplitDraft?.filters || {};
  const keepGallery = Boolean(workSplitDraft?.fromReview && prevFilters.baselines === baselines);
  const nextFilters = keepGallery
    ? { ...prevFilters, model_run_id: runId, baselines, comparison, comparison_status: comparison }
    : { model_run_id: runId, baselines, comparison, comparison_status: comparison, comment_state: "all", exclusion: "all" };
  workSplitDraft = {
    ...(workSplitDraft || {}),
    filters: nextFilters,
    dirty: false,
    submitted: false,
    fromReview: keepGallery,
  };
  if (!runId) {
    workSplitDraft.total = 0;
    renderWorkSplitScopeCount(0, nextFilters);
    displayCreationGroupSetup("workSplit");
    return;
  }
  const seq = ++workSplitScopeSeq;
  const scopeNode = $("#workSplitScopeCount");
  if (scopeNode) scopeNode.textContent = uiText("统计中…", "Counting…");
  try {
    const params = new URLSearchParams({ ...nextFilters, page: "1", page_size: "1", include_thumbnail: "false" });
    const result = await api(`/api/cases?${params}`);
    if (seq !== workSplitScopeSeq || $("#workSplitPanel")?.hidden) return;
    workSplitDraft.total = Number(result.total || 0);
    renderWorkSplitScopeCount(workSplitDraft.total, nextFilters);
    saveReviewAllocationDraft(workSplitDraft);
    displayCreationGroupSetup("workSplit");
    updateAssignmentNameSuggestion("review");
    queueCreationGroupPreview("workSplit", true);
  } catch (error) {
    if (seq !== workSplitScopeSeq) return;
    workSplitDraft.total = 0;
    renderWorkSplitScopeCount(0, nextFilters);
    showToast(error.message, true);
  }
}

async function openDirectWorkSplitCreator() {
  if (!state.session?.is_admin) {
    showToast(t("work.split_admin_only"), true);
    return;
  }
  const baselines = selectedBaselineQueryValue();
  const { runId } = await populateWorkSplitRunSelect(workSplitDraft?.filters?.model_run_id || state.selectedRunId || "");
  if (!runId) {
    showToast(uiText("当前数据集暂无 Model Run，请先切换数据集或上传模型预测 Run。", "No Model Run is available for the selected dataset."), true);
    return;
  }
  const draft = {
    filters: { model_run_id: runId, baselines, comparison: "all", comparison_status: "all", comment_state: "all", exclusion: "all" },
    total: 0,
    fromReview: false,
    dirty: false,
    submitted: false,
  };
  await openWorkSplitDialog(draft);
  await refreshWorkSplitScope();
}

async function refreshWorkSplitCreatorForDataset() {
  if (!$("#workSplitPanel") || $("#workSplitPanel").hidden || !state.session?.is_admin) return;
  const { runId } = await populateWorkSplitRunSelect("");
  if (workSplitDraft) workSplitDraft.fromReview = false;
  if (!runId) {
    workSplitDraft = {
      ...(workSplitDraft || {}),
      filters: { model_run_id: "", baselines: selectedBaselineQueryValue(), comparison: "all", comparison_status: "all" },
      total: 0,
      fromReview: false,
    };
    renderWorkSplitScopeCount(0, workSplitDraft.filters);
    displayCreationGroupSetup("workSplit");
    return;
  }
  await refreshWorkSplitScope();
}

async function openWorkSplitDialog(draft = null) {
  workSplitDraft = draft ? { ...draft, filters: { ...draft.filters }, total: draft.total } : null;
  if (!state.session?.is_admin) {
    showToast(t("work.split_admin_only"), true);
    return;
  }
  if (!workSplitFilters().model_run_id) {
    showToast("请先选择 Model Run；若只做 Case 标签，请前往 问题标注 > 实验分配。", true);
    return;
  }
  const results = $("#workSplitResults");
  if (results) {
    results.classList.add("hidden");
    results.innerHTML = "";
  }
  try {
    if (!state.accessUsers?.length) {
      await loadAccessUsers();
    }
  } catch (error) {
    showToast(error.message || t("work.load_users_fail"), true);
    return;
  }
  if ($("#workSplitWorkflowMode")) $("#workSplitWorkflowMode").value = "model_review_and_case_label";
  enhanceNativeUiSelect($("#workSplitWorkflowMode"));
  const comp = workSplitFilters().comparison || workSplitFilters().comparison_status || "all";
  if ($("#workSplitComparison")) {
    $("#workSplitComparison").value = ["all", "mismatch", "match"].includes(comp) ? comp : "all";
    enhanceNativeUiSelect($("#workSplitComparison"));
  }
  await populateWorkSplitRunSelect(workSplitFilters().model_run_id);
  renderWorkSplitScopeCount(workSplitTotal(), workSplitFilters());
  const panel = $("#workSplitPanel");
  panel.hidden = false;
  displayCreationGroupSetup("workSplit", workSplitDraft?.groupSetup || { groups: [newAllocationGroup()] });
  resetAssignmentNameSuggestion("review");
  const link = $("#workSplitReturnSource");
  if (link) {
    const fallback = reviewAssignmentSourceHref(workSplitFilters());
    const source = new URL(workSplitDraft?.returnUrl || fallback, window.location.origin);
    const expected = new URL(fallback, window.location.origin);
    link.href = source.origin === expected.origin && source.pathname === expected.pathname
      ? `${source.pathname}${source.search}` : fallback;
  }
  saveReviewAllocationDraft(workSplitDraft);
  panel.scrollIntoView({ block: "start", behavior: "smooth" });
}

function renderWorkSplitResults(payload) {
  const root = $("#workSplitResults");
  if (!root) return;
  const assignments = Array.isArray(payload?.assignments) ? payload.assignments : [];
  if (!assignments.length) {
    root.classList.add("hidden");
    root.innerHTML = "";
    return;
  }
  const reviewers = Math.max(1, Number(payload.reviewers_per_issue ?? 1));
  const overlapRatio = reviewers > 1
    ? Math.min(1, Math.max(0, Number(payload.overlap_ratio ?? 1)))
    : 0;
  const cards = assignments
    .map((item, index) => {
      const ids = Array.isArray(item.issue_ids) ? item.issue_ids : [];
      const mode =
        item.mode === "fixed"
          ? t("work.fixed_n", { n: item.requested_count ?? "—" })
          : item.mode === "blind"
            ? t("work.blind_n", { n: reviewers })
          : t("work.even_rest");
      return `<article class="work-split-card" data-work-split-index="${index}">
        <header>
          <strong>${escapeHtml(item.name || "—")}</strong>
        <span>${escapeHtml(t("runs.count_n", { n: Number(item.count || 0) }))} · ${escapeHtml(mode)}</span>
        </header>
        <textarea class="work-split-ids" readonly rows="4">${escapeHtml(
          ids.join("\n")
        )}</textarea>
        <div class="work-split-card-actions">
          <button class="button button-quiet" type="button" data-copy-work-split="${index}">${escapeHtml(t("work.copy_ids"))}</button>
          <button class="button button-primary" type="button" data-filter-work-assignee="${escapeHtml(
            item.name || ""
          )}">${escapeHtml(t("work.filter_assignee"))}</button>
        </div>
      </article>`;
    })
    .join("");
  root.classList.remove("hidden");
  root.innerHTML = `
    <div class="work-split-results-heading">
      <strong>${escapeHtml(t("work.result_title"))}</strong>
      <span>${escapeHtml(t("work.result_meta", { n: Number(payload.total || 0), seed: payload.split_id || "" }))} · ${escapeHtml(t("work.task_count", { n: Number(payload.assignment_count || payload.total || 0) }))} · ${escapeHtml(reviewers > 1 ? t("work.cross_ratio", { n: Math.round(overlapRatio * 100) }) : t("work.single_review"))}${payload.truncated ? escapeHtml(t("work.truncated")) : ""}</span>
      <button class="button button-quiet" type="button" data-open-review-assignments="${escapeHtml(payload.split_id || "")}">${escapeHtml(uiText("打开任务管理", "Open assignment manager"))}</button>
    </div>
    <div class="work-split-card-grid">${cards}</div>
  `;
  root.dataset.payload = JSON.stringify(payload);
}

async function generateWorkSplit() {
  if (!state.session?.is_admin) {
    showToast(t("work.split_admin_only"), true);
    return;
  }
  if (!workSplitFilters().model_run_id) {
    showToast("请先选择 Model Run；若只做 Case 标签，请前往 问题标注 > 实验分配。", true);
    return;
  }
  if (workSplitDraft?.submitted) {
    showToast(uiText("已创建分配。返回图库选择新任务的范围。", "Allocation created. Return to the gallery to select a new scope."), true);
    return;
  }
  if (workSplitDraft?.dirty) { showToast(uiText("筛选已修改，请先更新范围。", "Filters changed. Update the scope first."), true); return; }
  try {
    const result = await submitGroupedCreation("workSplit");
    if (!result) return;
    acknowledgeLocalChange(result);
    state.workAssigneeRequestSeq += 1;
    if (Array.isArray(result.work_assignees)) {
      state.workAssignees = result.work_assignees;
      renderWorkAssigneeFilter();
    } else {
      await loadWorkAssignees();
    }
    renderWorkSplitResults(result);
    saveReviewAllocationDraft(null);
    if (workSplitDraft) workSplitDraft.submitted = true;
    if (state.activePage === "review-assignments") {
      if (["versions", "history"].includes(state.reviewAssignments?.lifecycle) && typeof reviewAssignmentDetailUrl === "function") {
        state.reviewAssignments.lifecycle = "current";
        window.history.replaceState({ page: "review-assignments" }, "", reviewAssignmentDetailUrl());
      }
      await loadReviewAssignments({ force: true });
    }
    showToast(t("work.saved"));
  } catch (error) {
    showToast(creationAllocationError(error), true);
  }
}


function filterGalleryByWorkAssignee(assignee) {
  const name = String(assignee || "").trim();
  if (!name) return;
  if (workSplitDraft) {
    const filters = workSplitDraft.filters;
    const payload = JSON.parse($("#workSplitResults")?.dataset.payload || "{}");
    if ($("#workSplitPanel")) $("#workSplitPanel").hidden = true;
    navigatePage("review", { runId: filters.model_run_id, baselines: filters.baselines,
      comparisonStatus: filters.comparison, search: filters.search || "", issue: "",
      issueIds: [], workSplitId: payload.split_id || "", workAssignee: [name], casePage: 1 });
    return;
  }
  state.reviewIssueIds = [];
  setMultiFilterValues($("#workAssigneeFilter"), [name]);
  persistWorkAssigneeFilterRoute([name]);
  state.casePage = 1;
  if ($("#workSplitPanel")) $("#workSplitPanel").hidden = true;
  loadCases({ keepSelection: false, page: 1 })
    .then(() => showToast(`已筛选任务负责人：${name}`))
    .catch((error) => showToast(error.message, true));
}

function copyWorkSplitAssignment(index) {
  const root = $("#workSplitResults");
  if (!root?.dataset.payload) return;
  let payload;
  try {
    payload = JSON.parse(root.dataset.payload);
  } catch (_error) {
    showToast("无法读取分配结果。", true);
    return;
  }
  const item = payload.assignments?.[Number(index)];
  const ids = Array.isArray(item?.issue_ids) ? item.issue_ids : [];
  if (!ids.length) {
    showToast("该成员没有分到 Issue。", true);
    return;
  }
  const text = ids.join("\n");
  const done = () => showToast(`已复制 ${item.name} 的 ${ids.length} 个 Issue ID。`);
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => {
      window.prompt("复制以下 Issue ID：", text);
    });
    return;
  }
  window.prompt("复制以下 Issue ID：", text);
  done();
}

function bindWorkSplitControls() {
  bindCreationGroupSetup("workSplit");
  bindAssignmentNameInput("review");
  $("#workSplitModelRun")?.addEventListener("change", () => {
    refreshWorkSplitScope().catch((error) => showToast(error.message, true));
  });
  $("#workSplitComparison")?.addEventListener("change", () => {
    refreshWorkSplitScope().catch((error) => showToast(error.message, true));
  });
  $("#workSplitResetDraft")?.addEventListener("click", () => {
    workSplitDraft = null;
    saveReviewAllocationDraft(null);
    $("#workSplitPanel").hidden = true;
  });
  $("#reviewTaskContextRetry")?.addEventListener("click", () => {
    loadReviewTaskContext(state.reviewWorkSplitId).then(() => loadCases({ keepSelection: false, page: 1 })).catch((error) => showToast(error.message, true));
  });
  $("#reviewTaskContextExit")?.addEventListener("click", () => exitReviewTaskContext().catch((error) => showToast(error.message, true)));
  $('#reviewNextPendingTaskButton')?.addEventListener('click', () => jumpToNextPendingTask().catch(error => showToast(error.message, true)));
  $("#reviewTaskContextErrorExit")?.addEventListener("click", () => exitReviewTaskContext().catch((error) => showToast(error.message, true)));
  $("#reviewWorkflowMode")?.addEventListener("change", (event) => {
    if (state.reviewWorkSplitId) return;
    state.reviewWorkflowMode = event.target.value === "model_review_and_case_label"
      ? "model_review_and_case_label"
      : "model_review_only";
    persistCurrentReviewRoute({ workflowMode: state.reviewWorkflowMode });
    if (state.selectedCase) renderReview(state.selectedCase);
  });
  $("#splitFilteredButton")?.addEventListener("click", () => {
    if (!state.session?.is_admin) {
      showToast(t("work.split_admin_only"), true);
      return;
    }
    if (!state.caseTotal) {
      showToast(t("work.no_issues"), true);
      return;
    }
    const draft = { filters: { ...currentReviewFilterPayload(),
      work_assignee: joinFilterList(workAssigneeFilterSelection()) }, total: Number(state.caseTotal), fromReview: true, returnUrl: pageUrl("review", currentReviewRouteOptions({ issue: "" })) };
    saveReviewAllocationDraft(draft);
    workSplitDraft = null;
    $("#workSplitPanel").hidden = true;
    navigatePage("review-assignments");
  });
  $("#workSplitGenerate")?.addEventListener("click", () => {
    generateWorkSplit().catch((error) => showToast(error.message, true));
  });
  $("#workSplitResults")?.addEventListener("click", (event) => {
    const manage = event.target.closest("[data-open-review-assignments]");
    if (manage) {
      const splitId = manage.dataset.openReviewAssignments || "";
      if (splitId) {
        state.reviewAssignments.selectedSplitId = splitId;
        navigatePage("review-assignments", { reviewAssignmentSplitId: splitId });
      }
      return;
    }
    const copy = event.target.closest("[data-copy-work-split]");
    if (copy) {
      copyWorkSplitAssignment(copy.dataset.copyWorkSplit);
      return;
    }
    const filter = event.target.closest("[data-filter-work-assignee]");
    if (filter) filterGalleryByWorkAssignee(filter.dataset.filterWorkAssignee);
  });
}
