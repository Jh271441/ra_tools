/* ra_triage_dashboard/static/js/work-split.js
 * Admin Review work-split: persist assignee ownership and gallery filters.
 * Loaded as a classic script (shared global scope).
 */
function workAssigneeRouteSelection() {
  const params = new URLSearchParams(window.location.search);
  return parseFilterList(params.get("work_assignee") || params.get("assignee") || "");
}

function renderReviewTaskContext() {
  const task = state.reviewTaskContext;
  const banner = $("#reviewTaskContextBanner");
  const errorCard = $("#reviewTaskContextError");
  if (errorCard) {
    errorCard.hidden = !state.reviewTaskContextError;
    if (state.reviewTaskContextError) {
      $("#reviewTaskContextErrorMessage").textContent = state.reviewTaskContextError.message || "任务上下文暂时不可用。";
      $("#reviewTaskContextErrorId").textContent = state.reviewWorkSplitId || "—";
    }
  }
  if (!banner) return;
  banner.hidden = !task || Boolean(state.reviewTaskContextError);
  if (!task) return;
  $("#reviewTaskContextTitle").textContent = task.name || task.id;
  $("#reviewTaskContextMeta").textContent = task.legacy_no_run
    ? `历史无 Run 任务 · ${task.issue_count || 0} 个 Issue · 仅用于查看原分配范围`
    : `${task.workflow_mode === "model_review_and_case_label" ? "联合复核" : "仅判错复核"} · ${task.issue_count || 0} 个 Issue`;
  const runTrigger = $("#modelRunPickerTrigger");
  if (runTrigger) {
    runTrigger.disabled = true;
    runTrigger.title = task.legacy_no_run
      ? "历史无 Run 任务仅用于查看原分配范围；退出任务后可选择 Model Run"
      : "当前 Model Run 由任务锁定";
  }
}

function renderReviewTaskLoading(splitId = state.reviewWorkSplitId) {
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
  state.reviewWorkSplitId = "";
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

async function loadReviewTaskContext(splitId, { route = null } = {}) {
  const normalized = String(splitId || "").trim();
  if (!normalized) {
    clearReviewTaskContext({ clearRun: false });
    return null;
  }
  state.reviewWorkSplitId = normalized;
  state.reviewTaskContextLoading = true;
  state.reviewTaskContextError = null;
  renderReviewTaskLoading(normalized);
  renderReviewTaskContext();
  try {
    const result = await api(`/api/review-task-context/${encodeURIComponent(normalized)}`);
    const task = result.task || {};
    state.reviewTaskContext = task;
    state.reviewTaskContextLoading = false;
    state.reviewLegacyNoRunTask = Boolean(task.legacy_no_run);
    const baselineIds = (task.baseline_ids || []).map(String).filter(Boolean);
    const previous = normalizeBaselineIds(state.selectedBaselineIds).join(",");
    if (baselineIds.length) {
      state.selectedBaselineIds = baselineIds;
      persistBaselineIds(baselineIds);
      renderBaselinePicker();
    }
    state.selectedRunId = task.model_run_id || "";
    if (route) {
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
    return task;
  } catch (error) {
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
  return uiText(`本次任务新增 · ${value.slice(0, 18)}…`, `This task only · ${value.slice(0, 18)}…`);
}

function analysisWorkSplitOptionLabel(item) {
  const splitId = String(item?.split_id || "").trim();
  const date = item?.created_at ? formatTime(item.created_at) : "";
  const progress = `${Number(item?.completed_count || 0)}/${Number(item?.assignment_count || 0)}`;
  const owner = String(item?.created_by || "").trim();
  return [date, owner, progress, splitId.slice(0, 14)].filter(Boolean).join(" · ");
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

function renderReviewWorkSplitPicker(selected = state.reviewWorkSplitId) {
  const rootSelector = document.getElementById("reviewTaskPicker") ? "#reviewTaskPicker" : "#reviewWorkSplitPicker";
  renderWorkSplitScopePicker(
    rootSelector,
    selected,
    state.availableReviewWorkSplitId,
    (value) => {
      state.reviewWorkSplitId = value || "";
      state.casePage = 1;
      persistCurrentReviewRoute({ workSplitId: state.reviewWorkSplitId, casePage: 1 });
      scheduleReviewFilterReload?.(0);
    }
  );
}

function effectiveReviewWorkflowMode(caseData = state.selectedCase) {
  const assignment = caseData?.review_assignment || {};
  if (state.reviewWorkSplitId && assignment.split_id === state.reviewWorkSplitId) {
    return assignment.workflow_mode || "model_review_only";
  }
  return state.reviewWorkflowMode || "model_review_only";
}

function syncReviewWorkflowMode(caseData = state.selectedCase) {
  const select = $("#reviewWorkflowMode");
  const field = $("#reviewWorkflowModeField");
  if (!select || !field) return effectiveReviewWorkflowMode(caseData);
  const identityPending = Boolean(state.session?.identity_pending);
  const canCombine = Boolean(state.session?.verified && state.session?.is_admin && state.session?.can_write);
  const locked = Boolean(state.reviewWorkSplitId && caseData?.review_assignment?.split_id === state.reviewWorkSplitId);
  const mode = locked
    ? (caseData.review_assignment.workflow_mode || "model_review_only")
    : (canCombine || identityPending ? state.reviewWorkflowMode : "model_review_only");
  state.reviewWorkflowMode = mode;
  select.value = mode;
  select.disabled = locked || !canCombine;
  select.title = locked
    ? "页面模式由当前任务锁定"
    : !canCombine ? "需要模型复核与 Case 标注双重写权限" : "";
  field.hidden = !canCombine && !locked;
  $("#reviewWorkflowModeHint")?.toggleAttribute("hidden", !locked);
  enhanceNativeUiSelect(select);
  return mode;
}

function renderAnalysisWorkSplitPicker(selected = state.reviewAnalysis.workSplitId) {
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
      if (value) state.reviewAnalysis.availableWorkSplitId = value;
      scheduleAnalysisFilterReload?.(0);
    },
    maxHeight: 320,
    maxWidth: 520,
  });
}

async function loadAnalysisWorkSplits({ force = false } = {}) {
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
  state.reviewAnalysis.workSplitOptionsKey = key;
  state.reviewAnalysis.workSplitOptions = result.items || [];
  renderAnalysisWorkSplitPicker(state.reviewAnalysis.workSplitId);
  return state.reviewAnalysis.workSplitOptions;
}

function currentReviewFilterPayload() {
  return {
    search: $("#searchInput")?.value.trim() || "",
    gt_label: joinFilterList(getMultiFilterValues($("#gtFilter"))),
    model_label: joinFilterList(getMultiFilterValues($("#annotationFilter"))),
    annotation_author: joinFilterList(getMultiFilterValues($("#reviewerFilter"))),
    review_status: joinFilterList(getMultiFilterValues($("#reviewStatusFilter"))),
    label_state: joinFilterList(getMultiFilterValues($("#sharedLabelStateFilter"))),
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
    issue_ids: (state.reviewIssueIds || []).join(","),
    baselines: selectedBaselineQueryValue(),
    // When creating a new split, ignore current assignee filter so the pool
    // is the full filtered set unless the admin intentionally kept it.
    work_assignee: "",
    work_split_id: state.reviewWorkSplitId || "",
  };
}

function workSplitPersonRow(name = "", count = "") {
  const users = Array.isArray(state.accessUsers) ? state.accessUsers : [];
  const selectedUser = users.find((item) => item.username === name);
  const selectedLabel = selectedUser
    ? `${selectedUser.username}${selectedUser.role === "admin" ? t("work.admin_suffix") : ""}`
    : t("work.pick_person");
  return `<div class="work-split-person-row">
    <div class="ui-select work-split-person-picker" data-work-split-selected="${escapeHtml(name)}">
      <button class="ui-select-trigger" type="button" aria-haspopup="listbox" aria-expanded="false" aria-label="复核人">
        <span class="ui-select-summary">${escapeHtml(selectedLabel)}</span>
        <span class="ui-select-caret" aria-hidden="true"></span>
      </button>
      <div class="ui-select-panel" role="listbox" hidden></div>
      <select class="ui-select-native work-split-person-name" aria-hidden="true" tabindex="-1"></select>
    </div>
    <input class="work-split-person-count" type="number" min="0" step="1" placeholder="${escapeHtml(t("work.even_split"))}" value="${escapeHtml(
      count
    )}" title="留空=参与剩余均分；填数字=固定领取数量" />
    <button class="button button-quiet work-split-remove-person" type="button" aria-label="移除">×</button>
  </div>`;
}

function renderWorkSplitPersonPickers(rootSelector = "#workSplitPeople") {
  const pickers = [...document.querySelectorAll(`${rootSelector} .work-split-person-picker`)];
  const selectedByPicker = new Map(
    pickers.map((picker) => {
      const select = picker.querySelector(".work-split-person-name");
      return [picker, select?.value || picker.dataset.workSplitSelected || ""];
    })
  );
  pickers.forEach((picker) => {
    const selected = selectedByPicker.get(picker) || "";
    const selectedElsewhere = new Set(
      [...selectedByPicker.entries()]
        .filter(([other]) => other !== picker)
        .map(([, value]) => value)
        .filter(Boolean)
    );
    const options = [
      { value: "", label: t("work.pick_person") },
      ...(state.accessUsers || []).map((item) => ({
        value: item.username,
        label: `${item.username}${item.role === "admin" ? t("work.admin_suffix") : ""}`,
        disabled: selectedElsewhere.has(item.username),
      })),
    ];
    populateUiSelect(picker, options, selected);
    bindUiSelect(picker, { maxHeight: 320, maxWidth: 520 });
    picker.dataset.workSplitSelected =
      picker.querySelector(".work-split-person-name")?.value || "";
  });
}

function ensureWorkSplitPeople(minRows = 2, rootSelector = "#workSplitPeople") {
  const root = $(rootSelector);
  if (!root) return;
  while (root.querySelectorAll(".work-split-person-row").length < minRows) {
    root.insertAdjacentHTML("beforeend", workSplitPersonRow());
  }
}

function readWorkSplitAssignees(rootSelector = "#workSplitPeople") {
  const rows = [...document.querySelectorAll(`${rootSelector} .work-split-person-row`)];
  return rows
    .map((row) => {
      const name = row.querySelector(".work-split-person-name")?.value.trim() || "";
      const countRaw = row.querySelector(".work-split-person-count")?.value.trim() || "";
      return {
        name,
        count: countRaw === "" ? null : Number(countRaw),
      };
    })
    .filter((item) => item.name);
}

function workSplitReviewersPerIssue() {
  const value = Number.parseInt($("#workSplitReviewersPerIssue")?.value || "1", 10);
  return Number.isFinite(value) ? Math.max(1, value) : 1;
}

function workSplitOverlapRatio() {
  const value = Number.parseFloat($("#workSplitOverlapRatio")?.value || "1");
  return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 1;
}

function renderWorkSplitOverlapPicker(selected = null) {
  const picker = $("#workSplitOverlapPicker");
  const requested = selected === null
    ? workSplitOverlapRatio()
    : Number.parseFloat(String(selected));
  const value = Number.isFinite(requested)
    ? Math.min(1, Math.max(0, requested))
    : 1;
  const options = [0, 0.1, 0.2, 0.3, 0.5, 1].map((ratio) => ({
    value: String(ratio),
    label: `${Math.round(ratio * 100)}%`,
  }));
  populateUiSelect(picker, options, String(value));
  bindUiSelect(picker, { maxHeight: 260, maxWidth: 180 });
  return value;
}

function updateWorkSplitOverlapVisibility() {
  const field = $("#workSplitOverlapField");
  if (field) field.hidden = workSplitReviewersPerIssue() <= 1;
}

function renderWorkSplitReviewersPerIssuePicker(selected = null) {
  const picker = $("#workSplitReviewersPerIssuePicker");
  const memberCount = readWorkSplitAssignees().length;
  const maximum = Math.max(1, memberCount);
  const requested = selected === null
    ? workSplitReviewersPerIssue()
    : Number.parseInt(String(selected), 10);
  const value = Math.min(Math.max(1, Number.isFinite(requested) ? requested : 1), maximum);
  populateUiSelect(
    picker,
    Array.from({ length: maximum }, (_, index) => ({
      value: String(index + 1),
      label: `${index + 1} 人`,
    })),
    String(value),
  );
  bindUiSelect(picker, { maxHeight: 260, maxWidth: 180 });
  return value;
}

function updateWorkSplitEstimate() {
  const reviewers = workSplitReviewersPerIssue();
  const overlapRatio = workSplitOverlapRatio();
  const people = readWorkSplitAssignees();
  const total = Number(state.caseTotal || 0);
  const target = $("#workSplitEstimate");
  updateWorkSplitOverlapVisibility();
  document.querySelectorAll(".work-split-person-count").forEach((input) => {
    input.placeholder = reviewers > 1 ? "自动均衡" : t("work.even_split");
  });
  if (!target) return;
  if (reviewers > people.length && people.length) {
    target.textContent = `每个 Issue 的人数不能超过已选 ${people.length} 人`;
    return;
  }
  const overlapCount = reviewers > 1 ? Math.min(total, Math.round(total * overlapRatio)) : 0;
  const assignmentCount = total + overlapCount * (reviewers - 1);
  const fixedTotal = people.reduce(
    (sum, person) => sum + (person.count === null ? 0 : Number(person.count || 0)),
    0,
  );
  const automaticPeople = people.filter((person) => person.count === null).length;
  if (people.some((person) => person.count !== null && person.count > total)) {
    target.textContent = `个人数量不能超过 ${total}，同一人不能重复领取同一个 Issue`;
    return;
  }
  if (fixedTotal > assignmentCount) {
    target.textContent = `已指定 ${fixedTotal} 条，超过任务总数 ${assignmentCount}`;
    return;
  }
  if (!automaticPeople && fixedTotal !== assignmentCount) {
    target.textContent = `已指定 ${fixedTotal} 条，需合计 ${assignmentCount} 条`;
    return;
  }
  if (automaticPeople && assignmentCount - fixedTotal > automaticPeople * total) {
    target.textContent = "剩余任务超过自动均衡人员可领取上限，请降低固定数量或增加人员";
    return;
  }
  const low = people.length ? Math.floor(assignmentCount / people.length) : 0;
  const high = people.length ? Math.ceil(assignmentCount / people.length) : 0;
  if (reviewers === 1) {
    target.textContent = t("work.single_estimate", { total });
    return;
  }
  const estimate = t("work.blind_estimate", {
    total,
    ratio: Math.round(overlapRatio * 100),
    overlap: overlapCount,
    reviewers,
    assignments: assignmentCount,
  });
  target.textContent = `${estimate} · ${
    fixedTotal
      ? t("work.fixed_remaining", { n: fixedTotal })
      : t("work.person_estimate", {
          range: `${low}${high !== low ? `～${high}` : ""}`,
        })
  }`;
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
      if (key === "work_assignee" || key === "failure_only" || !value) return;
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
  const button = $("#splitFilteredButton");
  const isAdmin = Boolean(state.session?.is_admin);
  const analysisField = $("#analysisWorkAgreementField");
  // Agreement is a read-only analysis filter and is available to every
  // viewer.  Only assignment/redistribution remains administrator-only.
  if (analysisField) analysisField.hidden = false;
  if (!button) return;
  button.hidden = !isAdmin;
  if (!isAdmin || !state.selectedRunId) {
    button.disabled = true;
    button.title = !state.selectedRunId
      ? "请先选择 Model Run；若只做 Case 标签，请前往 Case 标注 > 实验分配"
      : "仅管理员可创建复核任务";
  }
}

async function openWorkSplitDialog() {
  if (!state.session?.is_admin) {
    showToast(t("work.split_admin_only"), true);
    return;
  }
  if (!state.selectedRunId) {
    showToast("请先选择 Model Run；若只做 Case 标签，请前往 Case 标注 > 实验分配。", true);
    return;
  }
  const total = Number(state.caseTotal || 0);
  const summary = $("#workSplitSummary");
  const results = $("#workSplitResults");
  if (summary) {
    summary.textContent = total
      ? t("work.summary_n", { n: total })
      : t("work.no_issues");
  }
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
  const root = $("#workSplitPeople");
  if (root) {
    root.innerHTML = "";
    const users = state.accessUsers || [];
    if (users.length) {
      users.forEach((user) => {
        root.insertAdjacentHTML("beforeend", workSplitPersonRow(user.username, ""));
      });
    } else {
      ensureWorkSplitPeople(2);
      showToast(t("work.no_writers"), true);
    }
  }
  renderWorkSplitPersonPickers();
  if ($("#workSplitReviewersPerIssue")) $("#workSplitReviewersPerIssue").value = "1";
  if ($("#workSplitWorkflowMode")) $("#workSplitWorkflowMode").value = "model_review_only";
  $("#workSplitWorkflowModeCards")?.querySelectorAll("[data-workflow-mode]").forEach((card) => {
    card.classList.toggle("is-active", card.dataset.workflowMode === "model_review_only");
    card.setAttribute("aria-pressed", String(card.dataset.workflowMode === "model_review_only"));
  });
  renderWorkSplitReviewersPerIssuePicker(1);
  renderWorkSplitOverlapPicker(1);
  updateWorkSplitEstimate();
  openDialog("workSplitDialog");
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
  if (!state.selectedRunId) {
    showToast("请先选择 Model Run；若只做 Case 标签，请前往 Case 标注 > 实验分配。", true);
    return;
  }
  const assignees = readWorkSplitAssignees();
  if (!assignees.length) {
    showToast(t("work.need_reviewer"), true);
    return;
  }
  const reviewersPerIssue = workSplitReviewersPerIssue();
  const overlapRatio = reviewersPerIssue > 1 ? workSplitOverlapRatio() : 0;
  const seedRaw = $("#workSplitSeed")?.value.trim() || "";
  const body = {
    filters: currentReviewFilterPayload(),
    assignees,
    reviewers_per_issue: reviewersPerIssue,
    overlap_ratio: overlapRatio,
    workflow_mode: $("#workSplitWorkflowMode")?.value || "model_review_only",
  };
  if (body.reviewers_per_issue > assignees.length) {
    showToast("每个 Issue 的复核人数不能超过已选成员数。", true);
    return;
  }
  if (seedRaw !== "") {
    const seed = Number(seedRaw);
    if (!Number.isFinite(seed)) {
      showToast(t("work.seed_int"), true);
      return;
    }
    body.seed = seed;
  }
  const button = $("#workSplitGenerate");
  if (button) {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
  }
  try {
    const result = await api("/api/cases/work-split", {
      method: "POST",
      body: JSON.stringify(body),
    });
    acknowledgeLocalChange(result);
    state.workAssigneeRequestSeq += 1;
    if (Array.isArray(result.work_assignees)) {
      state.workAssignees = result.work_assignees;
      renderWorkAssigneeFilter();
    } else {
      await loadWorkAssignees();
    }
    renderWorkSplitResults(result);
    showToast(t("work.saved"));
  } catch (error) {
    showToast(error.message, true);
  } finally {
    if (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  }
}

function filterGalleryByWorkAssignee(assignee) {
  const name = String(assignee || "").trim();
  if (!name) return;
  state.reviewIssueIds = [];
  setMultiFilterValues($("#workAssigneeFilter"), [name]);
  persistWorkAssigneeFilterRoute([name]);
  state.casePage = 1;
  closeDialog("workSplitDialog");
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
  $("#reviewTaskContextRetry")?.addEventListener("click", () => {
    loadReviewTaskContext(state.reviewWorkSplitId).then(() => loadCases({ keepSelection: false, page: 1 })).catch((error) => showToast(error.message, true));
  });
  $("#reviewTaskContextExit")?.addEventListener("click", () => exitReviewTaskContext().catch((error) => showToast(error.message, true)));
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
    openWorkSplitDialog().catch((error) => showToast(error.message, true));
  });
  $("#workSplitAddPerson")?.addEventListener("click", () => {
    $("#workSplitPeople")?.insertAdjacentHTML("beforeend", workSplitPersonRow());
    renderWorkSplitPersonPickers();
    renderWorkSplitReviewersPerIssuePicker();
    updateWorkSplitEstimate();
  });
  $("#workSplitPeople")?.addEventListener("click", (event) => {
    const remove = event.target.closest(".work-split-remove-person");
    if (!remove) return;
    const row = remove.closest(".work-split-person-row");
    const root = $("#workSplitPeople");
    if (!row || !root) return;
    row.remove();
    ensureWorkSplitPeople(1);
    renderWorkSplitPersonPickers();
    renderWorkSplitReviewersPerIssuePicker();
    updateWorkSplitEstimate();
  });
  $("#workSplitPeople")?.addEventListener("change", (event) => {
    if (event.target.matches(".work-split-person-name")) {
      event.target.closest(".work-split-person-picker").dataset.workSplitSelected =
        event.target.value || "";
      renderWorkSplitPersonPickers();
      renderWorkSplitReviewersPerIssuePicker();
    }
    updateWorkSplitEstimate();
  });
  $("#workSplitPeople")?.addEventListener("input", (event) => {
    if (event.target.matches(".work-split-person-count")) updateWorkSplitEstimate();
  });
  $("#workSplitReviewersPerIssue")?.addEventListener("change", updateWorkSplitEstimate);
  $("#workSplitOverlapRatio")?.addEventListener("change", updateWorkSplitEstimate);
  $("#workSplitWorkflowModeCards")?.addEventListener("click", (event) => {
    const card = event.target.closest("[data-workflow-mode]");
    if (!card) return;
    const input = $("#workSplitWorkflowMode");
    if (input) input.value = card.dataset.workflowMode || "model_review_only";
    event.currentTarget.querySelectorAll("[data-workflow-mode]").forEach((item) => {
      const active = item === card;
      item.classList.toggle("is-active", active);
      item.setAttribute("aria-pressed", String(active));
    });
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
