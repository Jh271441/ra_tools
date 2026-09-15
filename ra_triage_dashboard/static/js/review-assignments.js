/* Review assignment history, progress, and administrator task transfers. */

function reviewAssignmentRunLabel(runId) {
  const value = String(runId || "").trim();
  if (!value) return uiText("未绑定 Model Run", "No Model Run");
  const run = (state.modelRuns || []).find((item) => String(item.id) === value);
  return run ? run.name || value : value;
}

function reviewAssignmentModeLabel(item) {
  const reviewers = Math.max(1, Number(item?.reviewers_per_issue || 1));
  if (reviewers <= 1) return uiText("单人分配", "Single review");
  return uiText(
    `交叉盲标 ${Math.round(Number(item?.overlap_ratio || 0) * 100)}% · 每个 Issue ${reviewers} 人`,
    `${Math.round(Number(item?.overlap_ratio || 0) * 100)}% cross-review · ${reviewers} reviewers / Issue`
  );
}

function reviewAssignmentPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.max(0, Math.min(100, Math.round(numeric * 100)));
}

function reviewAssignmentFilterLabel(item) {
  const filter = item?.filter_snapshot && typeof item.filter_snapshot === "object"
    ? item.filter_snapshot
    : {};
  const values = [];
  if (filter.baselines) values.push(`${uiText("数据集", "Datasets")}: ${filter.baselines}`);
  if (filter.comparison_status && filter.comparison_status !== "all") {
    values.push(`${uiText("模型结果", "Model")}: ${filter.comparison_status}`);
  }
  if (filter.gt_label) values.push(`GT: ${filter.gt_label}`);
  if (filter.model_label) values.push(`${uiText("模型标注", "Model label")}: ${filter.model_label}`);
  if (filter.annotation_author) values.push(`${uiText("复核人", "Reviewer")}: ${filter.annotation_author}`);
  if (filter.search) values.push(`${uiText("检索", "Search")}: ${filter.search}`);
  return values.length
    ? values.join(" · ")
    : uiText("按创建时的筛选结果分配", "Created from the saved Review filter");
}

function reviewAssignmentMetricMarkup(label, value, note = "") {
  return `<article class="review-assignment-metric"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong>${note ? `<span>${escapeHtml(note)}</span>` : ""}</article>`;
}

function renderReviewAssignmentMetrics(items) {
  const root = $("#reviewAssignmentMetrics");
  if (!root) return;
  const active = items.filter((item) => item.is_current);
  const assignments = items.reduce((sum, item) => sum + Number(item.assignment_count || 0), 0);
  const completed = items.reduce((sum, item) => sum + Number(item.completed_count || 0), 0);
  const pending = items.reduce((sum, item) => sum + Number(item.pending_count || 0), 0);
  root.innerHTML = [
    reviewAssignmentMetricMarkup(uiText("分配批次", "Batches"), items.length, uiText(`${active.length} 个当前批次`, `${active.length} current`)),
    reviewAssignmentMetricMarkup(uiText("任务总量", "Assigned tasks"), assignments, uiText("按 Review 人次计数", "Reviewer-task count")),
    reviewAssignmentMetricMarkup(uiText("已完成", "Completed"), completed, uiText("已有 Review 提交", "Review submitted")),
    reviewAssignmentMetricMarkup(uiText("待处理", "Pending"), pending, uiText("可在明细中转派", "Reassign from task detail")),
  ].join("");
}

function reviewAssignmentMemberMarkup(member) {
  const assigned = Number(member.assigned_count || 0);
  const completed = Number(member.completed_count || 0);
  const percent = reviewAssignmentPercent(member.completion_ratio);
  return `<div class="review-assignment-member">
    <div class="review-assignment-member-heading"><strong>${escapeHtml(member.username || "—")}</strong><span>${completed} / ${assigned}</span></div>
    <div class="review-assignment-progress-track" aria-label="${escapeHtml(`${completed} / ${assigned}`)}"><span style="width:${percent}%"></span></div>
    <small>${escapeHtml(uiText(`${member.pending_count || 0} 条待处理`, `${member.pending_count || 0} pending`))}</small>
  </div>`;
}

function renderReviewAssignmentBatch(item) {
  const percent = reviewAssignmentPercent(item.completion_ratio);
  const status = item.is_current
    ? uiText("当前分配", "Current")
    : uiText("已被后续分配覆盖", "Superseded");
  const statusClass = item.is_current ? "is-current" : "is-superseded";
  const filterLabel = reviewAssignmentFilterLabel(item);
  const changeNote = Number(item.change_count || 0)
    ? uiText(`已转派 ${item.change_count} 次`, `${item.change_count} transfers`)
    : uiText("尚未转派", "No transfers");
  return `<article class="review-assignment-batch" data-review-assignment-batch="${escapeHtml(item.split_id)}">
    <header class="review-assignment-batch-header">
      <div><strong class="review-assignment-batch-title">${escapeHtml(reviewAssignmentRunLabel(item.model_run_id))} · ${escapeHtml(formatTime(item.created_at))}</strong><span class="review-assignment-batch-meta">${escapeHtml(item.split_id)} · ${escapeHtml(item.created_by || uiText("未记录", "Unknown"))} · ${escapeHtml(reviewAssignmentModeLabel(item))}</span><span class="review-assignment-batch-meta">${escapeHtml(filterLabel)}</span></div>
      <span class="review-assignment-status ${statusClass}">${escapeHtml(status)}</span>
    </header>
    <div class="review-assignment-progress"><div class="review-assignment-progress-heading"><span>${escapeHtml(uiText("整体进度", "Overall progress"))}</span><strong>${escapeHtml(`${item.completed_count || 0} / ${item.assignment_count || 0} · ${percent}%`)}</strong></div><div class="review-assignment-progress-track"><span style="width:${percent}%"></span></div></div>
    <div class="review-assignment-member-grid">${(item.members || []).map(reviewAssignmentMemberMarkup).join("") || `<span class="quiet-meta">${escapeHtml(uiText("没有成员记录", "No member data"))}</span>`}</div>
    <footer class="review-assignment-batch-footer"><span>${escapeHtml(`${item.total_count || 0} ${uiText("个 Issue", "Issues")} · ${changeNote}`)}</span><div class="review-assignment-batch-actions"><button class="button button-quiet" type="button" data-open-review-assignment="${escapeHtml(item.split_id)}">${escapeHtml(uiText("查看任务明细", "View task detail"))}</button></div></footer>
  </article>`;
}

function renderReviewAssignmentList() {
  const store = state.reviewAssignments;
  const root = $("#reviewAssignmentList");
  const status = $("#reviewAssignmentListStatus");
  if (!root) return;
  if (store.loading && !store.splits.length) {
    root.innerHTML = `<div class="review-assignment-empty">${escapeHtml(uiText("正在加载任务分配。", "Loading assignments."))}</div>`;
    if (status) status.textContent = "";
    return;
  }
  if (!store.splits.length) {
    root.innerHTML = `<div class="review-assignment-empty"><strong>${escapeHtml(uiText("还没有生成过均分任务", "No split assignments yet"))}</strong><span>${escapeHtml(uiText("回到 Review 页面筛选 Issue 后，点击“均分任务”即可创建。", "Filter Issues in Review, then choose Split work to create one."))}</span></div>`;
    if (status) status.textContent = "";
    return;
  }
  root.innerHTML = store.splits.map(renderReviewAssignmentBatch).join("");
  if (status) {
    status.textContent = uiText(`最近 ${store.splits.length} 个批次`, `${store.splits.length} recent batches`);
  }
}

function reviewAssignmentTaskTypeLabel(value) {
  return value === "cross"
    ? uiText("交叉复核", "Cross-review")
    : value === "full"
      ? uiText("全量复核", "Full review")
      : uiText("基础任务", "Base task");
}

function reviewAssignmentTaskStatusMarkup(item) {
  return item.submitted
    ? `<span class="review-assignment-task-status is-complete">${escapeHtml(uiText("已完成", "Completed"))}</span>`
    : `<span class="review-assignment-task-status is-pending">${escapeHtml(uiText("待处理", "Pending"))}</span>`;
}

function reviewAssignmentIssueHref(item) {
  return pageUrl("review", {
    issue: item.issue_id,
    runId: item.split_model_run_id || state.reviewAssignments.detail?.model_run_id || "",
    comparisonStatus: "all",
    workAssignee: [item.assignee],
    issueIds: [],
    casePage: 1,
  });
}

function reviewAssignmentPersonOptions(selected = "") {
  const values = (state.accessUsers || []).map((item) => ({
    value: String(item.username || "").trim(),
    label: `${item.username}${item.role === "admin" ? uiText(" · 管理员", " · admin") : ""}`,
  })).filter((item) => item.value);
  if (selected && !values.some((item) => item.value === selected)) {
    values.unshift({ value: selected, label: `${selected} · ${uiText("已移除账号", "removed user")}` });
  }
  return values;
}

function renderReviewAssignmentRowPersonPickers() {
  document.querySelectorAll("#reviewAssignmentDetailRows .review-assignment-person-picker").forEach((root) => {
    const native = root.querySelector(".ui-select-native");
    const selected = native?.value || root.dataset.selectedAssignee || "";
    populateUiSelect(root, reviewAssignmentPersonOptions(selected), selected);
    bindUiSelect(root, {
      maxHeight: 300,
      maxWidth: 300,
      onChange: (value) => {
        root.dataset.selectedAssignee = value;
        const row = root.closest("tr");
        const save = row?.querySelector("[data-review-assignment-save]");
        if (save) save.disabled = value === row?.dataset.originalAssignee;
      },
    });
  });
}

function renderReviewAssignmentDetailFilters(detail) {
  const store = state.reviewAssignments;
  const assigneePicker = $("#reviewAssignmentAssigneePicker");
  const assigneeOptions = [
    { value: "", label: uiText("全部负责人", "All assignees") },
    ...(detail.members || []).map((item) => ({
      value: item.username,
      label: `${item.username} · ${item.assigned_count || 0}`,
    })),
  ];
  if (assigneePicker) {
    const selected = assigneeOptions.some((item) => item.value === store.assignee) ? store.assignee : "";
    store.assignee = selected;
    populateUiSelect(assigneePicker, assigneeOptions, selected);
    bindUiSelect(assigneePicker, { maxHeight: 280, maxWidth: 280 });
  }
  const statusPicker = $("#reviewAssignmentStatusPicker");
  if (statusPicker) {
    const options = [
      { value: "all", label: uiText("全部任务", "All tasks") },
      { value: "pending", label: uiText("待处理", "Pending") },
      { value: "completed", label: uiText("已完成", "Completed") },
    ];
    const selected = options.some((item) => item.value === store.status) ? store.status : "all";
    store.status = selected;
    populateUiSelect(statusPicker, options, selected);
    bindUiSelect(statusPicker, { maxHeight: 220, maxWidth: 220 });
  }
  const search = $("#reviewAssignmentSearch");
  if (search && search.value !== store.query) search.value = store.query;
}

function renderReviewAssignmentDetail() {
  const store = state.reviewAssignments;
  const root = $("#reviewAssignmentDetail");
  const detail = store.detail;
  if (!root) return;
  root.hidden = !detail && !store.detailLoading;
  if (!detail) {
    if (store.detailLoading) {
      root.hidden = false;
      $("#reviewAssignmentDetailTitle").textContent = uiText("正在加载任务明细", "Loading task detail");
      $("#reviewAssignmentDetailMeta").textContent = "";
      $("#reviewAssignmentDetailRows").innerHTML = `<tr><td colspan="6" class="review-assignment-empty">${escapeHtml(uiText("正在加载。", "Loading."))}</td></tr>`;
    }
    return;
  }
  const title = $("#reviewAssignmentDetailTitle");
  if (title) title.textContent = `${reviewAssignmentRunLabel(detail.model_run_id)} · ${uiText("任务明细", "Task detail")}`;
  const meta = $("#reviewAssignmentDetailMeta");
  if (meta) {
    meta.textContent = `${detail.split_id} · ${detail.total_count || 0} ${uiText("个 Issue", "Issues")} · ${detail.assignment_count || 0} ${uiText("条任务", "tasks")} · ${reviewAssignmentModeLabel(detail)}${detail.is_current ? "" : ` · ${uiText("该批次已被后续分配覆盖，当前不可编辑", "Superseded by a later allocation; read-only")}`}`;
  }
  renderReviewAssignmentDetailFilters(detail);
  const summary = $("#reviewAssignmentDetailSummary");
  if (summary) {
    const percent = reviewAssignmentPercent(detail.completion_ratio);
    summary.innerHTML = `<span class="review-assignment-summary-chip is-complete">${escapeHtml(`${detail.completed_count || 0} ${uiText("已完成", "completed")}`)}</span><span class="review-assignment-summary-chip is-pending">${escapeHtml(`${detail.pending_count || 0} ${uiText("待处理", "pending")}`)}</span><span class="review-assignment-summary-chip">${escapeHtml(`${percent}% ${uiText("完成率", "complete")}`)}</span><span class="review-assignment-summary-chip">${escapeHtml(`${detail.change_count || 0} ${uiText("次转派", "transfers")}`)}</span>`;
  }
  const rows = $("#reviewAssignmentDetailRows");
  if (!rows) return;
  if (store.detailLoading) {
    rows.innerHTML = `<tr><td colspan="6" class="review-assignment-empty">${escapeHtml(uiText("正在加载。", "Loading."))}</td></tr>`;
  } else if (!detail.items?.length) {
    rows.innerHTML = `<tr><td colspan="6" class="review-assignment-empty">${escapeHtml(detail.is_current ? uiText("没有符合当前筛选的任务。", "No tasks match these filters.") : uiText("该批次的任务已被后续分配覆盖。", "This batch has been superseded."))}</td></tr>`;
  } else {
    rows.innerHTML = detail.items.map((item) => {
      const locked = item.submitted || !detail.is_current;
      const picker = locked
        ? `<span class="review-assignment-locked">${escapeHtml(item.assignee)}${item.submitted ? ` · ${escapeHtml(uiText("已提交", "submitted"))}` : ""}</span>`
        : `<div class="ui-select review-assignment-person-picker" data-selected-assignee="${escapeHtml(item.assignee)}"><button class="ui-select-trigger" type="button" aria-haspopup="listbox" aria-expanded="false"><span class="ui-select-summary">${escapeHtml(item.assignee)}</span><span class="ui-select-caret" aria-hidden="true"></span></button><div class="ui-select-panel" role="listbox" hidden></div><select class="ui-select-native" aria-hidden="true" tabindex="-1"></select></div>`;
      const save = locked
        ? `<span class="review-assignment-locked">${escapeHtml(item.submitted ? uiText("已完成，锁定", "Completed; locked") : uiText("历史批次，只读", "Read-only history"))}</span>`
        : `<button class="button button-quiet review-assignment-save" type="button" data-review-assignment-save disabled>${escapeHtml(uiText("保存转派", "Save transfer"))}</button>`;
      return `<tr data-review-assignment-row data-issue-id="${escapeHtml(item.issue_id)}" data-original-assignee="${escapeHtml(item.assignee)}"><td><a class="review-assignment-issue-link" href="${escapeHtml(reviewAssignmentIssueHref(item))}">${escapeHtml(item.issue_id)}</a>${item.title || item.scenario ? `<small class="review-assignment-issue-meta" title="${escapeHtml(item.title || item.scenario)}">${escapeHtml(item.title || item.scenario)}</small>` : ""}</td><td>${picker}</td><td>${escapeHtml(reviewAssignmentTaskTypeLabel(item.assignment_kind))}</td><td>${reviewAssignmentTaskStatusMarkup(item)}</td><td>${escapeHtml(item.submitted_at ? formatTime(item.submitted_at) : "—")}</td><td>${save}</td></tr>`;
    }).join("");
    renderReviewAssignmentRowPersonPickers();
  }
  const pageCount = Math.max(1, Number(detail.page_count || 1));
  const page = Math.min(pageCount, Math.max(1, Number(detail.page || store.page || 1)));
  store.page = page;
  const pageState = $("#reviewAssignmentPageState");
  if (pageState) pageState.textContent = `${page} / ${pageCount}`;
  const previous = $("#reviewAssignmentPrevious");
  const next = $("#reviewAssignmentNext");
  if (previous) previous.disabled = page <= 1 || store.detailLoading;
  if (next) next.disabled = page >= pageCount || store.detailLoading;
  const jump = $("#reviewAssignmentPageJump");
  if (jump) {
    jump.max = String(pageCount);
    jump.value = String(page);
    jump.disabled = store.detailLoading;
  }
  const pageSize = $("#reviewAssignmentPageSize");
  if (pageSize) pageSize.value = String(store.pageSize);
  const log = $("#reviewAssignmentChangeLog");
  if (log) {
    log.innerHTML = detail.changes?.length
      ? detail.changes.map((item) => `<div class="review-assignment-change-row"><span><strong>${escapeHtml(item.issue_id)}</strong> · ${escapeHtml(item.from_assignee)} → ${escapeHtml(item.to_assignee)}</span><small>${escapeHtml(item.changed_by)} · ${escapeHtml(formatTime(item.changed_at))}</small></div>`).join("")
      : `<span class="quiet-meta">${escapeHtml(uiText("暂无转派记录。", "No reassignment history."))}</span>`;
  }
}

function renderReviewAssignmentPage() {
  if (!$("#reviewAssignmentsPage")) return;
  renderReviewAssignmentMetrics(state.reviewAssignments.splits || []);
  renderReviewAssignmentList();
  renderReviewAssignmentDetail();
}

function reviewAssignmentDetailUrl(splitId = "") {
  const url = new URL(withBase("/review-assignments"), window.location.origin);
  if (splitId) url.searchParams.set("split", splitId);
  return `${url.pathname}${url.search}`;
}

async function loadReviewAssignmentDetail(
  splitId = state.reviewAssignments.selectedSplitId,
  { updateRoute = false } = {}
) {
  const store = state.reviewAssignments;
  const normalized = String(splitId || "").trim();
  if (!normalized) return;
  store.selectedSplitId = normalized;
  const requestSeq = ++store.detailRequestSeq;
  store.detailLoading = true;
  renderReviewAssignmentPage();
  const params = new URLSearchParams({
    page: String(store.page || 1),
    page_size: String(store.pageSize || 50),
    status: store.status || "all",
  });
  if (store.assignee) params.set("assignee", store.assignee);
  if (store.query) params.set("q", store.query);
  try {
    const detail = await api(`/api/cases/work-splits/${encodeURIComponent(normalized)}?${params}`);
    if (requestSeq !== store.detailRequestSeq || store.selectedSplitId !== normalized) return;
    store.detail = detail;
    store.detailLoading = false;
    renderReviewAssignmentPage();
    if (updateRoute) {
      window.history.replaceState(
        { ...(window.history.state || {}), page: "review-assignments" },
        "",
        reviewAssignmentDetailUrl(normalized)
      );
    }
  } catch (error) {
    if (requestSeq !== store.detailRequestSeq) return;
    store.detailLoading = false;
    store.detail = null;
    renderReviewAssignmentPage();
    showToast(error.message, true);
  }
}

async function loadReviewAssignments({ force = false, splitId = "", reloadDetail = true } = {}) {
  const store = state.reviewAssignments;
  if (!state.accessUsers?.length && state.session?.is_admin && typeof loadAccessUsers === "function") {
    await loadAccessUsers();
  }
  if (!force && store.splits.length) {
    renderReviewAssignmentPage();
    if (splitId && reloadDetail) await loadReviewAssignmentDetail(splitId, { updateRoute: false });
    return;
  }
  const requestSeq = ++store.requestSeq;
  store.loading = true;
  renderReviewAssignmentPage();
  try {
    const result = await api("/api/cases/work-splits?limit=100");
    if (requestSeq !== store.requestSeq) return;
    store.splits = result.items || [];
    store.loading = false;
    renderReviewAssignmentPage();
    const selected = splitId || store.selectedSplitId;
    if (selected && reloadDetail) {
      store.page = 1;
      await loadReviewAssignmentDetail(selected, { updateRoute: false });
    }
  } catch (error) {
    if (requestSeq !== store.requestSeq) return;
    store.loading = false;
    renderReviewAssignmentPage();
    showToast(error.message, true);
  }
}

async function reassignReviewAssignment(row, button) {
  const store = state.reviewAssignments;
  const detail = store.detail;
  const issueId = row?.dataset.issueId || "";
  const assignee = row?.querySelector(".review-assignment-person-picker .ui-select-native")?.value || "";
  if (!detail?.split_id || !issueId || !assignee || assignee === row.dataset.originalAssignee) return;
  if (button) {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
  }
  try {
    const result = await api(`/api/cases/work-splits/${encodeURIComponent(detail.split_id)}/assignments/${encodeURIComponent(issueId)}`, {
      method: "PATCH",
      body: JSON.stringify({ assignee }),
    });
    acknowledgeLocalChange(result);
    store.detail = result.split || store.detail;
    store.selectedSplitId = detail.split_id;
    await loadReviewAssignments({ force: true, splitId: detail.split_id, reloadDetail: true });
    renderReviewAssignmentPage();
    showToast(uiText(`${issueId} 已转派给 ${assignee}。`, `${issueId} transferred to ${assignee}.`));
  } catch (error) {
    showToast(error.message, true);
  } finally {
    if (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  }
}

function bindReviewAssignmentsPage() {
  $("#reviewAssignmentsRefresh")?.addEventListener("click", () => {
    loadReviewAssignments({ force: true, splitId: state.reviewAssignments.selectedSplitId }).catch((error) => showToast(error.message, true));
  });
  $("#reviewAssignmentsGoReview")?.addEventListener("click", () => navigatePage("review"));
  $("#reviewAssignmentDetailClose")?.addEventListener("click", () => {
    const store = state.reviewAssignments;
    store.selectedSplitId = "";
    store.detail = null;
    store.detailLoading = false;
    window.history.replaceState(
      { ...(window.history.state || {}), page: "review-assignments" },
      "",
      reviewAssignmentDetailUrl()
    );
    renderReviewAssignmentPage();
  });
  $("#reviewAssignmentList")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-open-review-assignment]");
    if (!button) return;
    const splitId = button.dataset.openReviewAssignment || "";
    state.reviewAssignments.page = 1;
    state.reviewAssignments.assignee = "";
    state.reviewAssignments.status = "all";
    state.reviewAssignments.query = "";
    loadReviewAssignmentDetail(splitId, { updateRoute: true }).catch((error) => showToast(error.message, true));
  });
  $("#reviewAssignmentDetailRows")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-review-assignment-save]");
    if (!button) return;
    reassignReviewAssignment(button.closest("tr"), button).catch((error) => showToast(error.message, true));
  });
  $("#reviewAssignmentAssigneeFilter")?.addEventListener("change", () => {
    state.reviewAssignments.assignee = $("#reviewAssignmentAssigneeFilter")?.value || "";
    state.reviewAssignments.page = 1;
    loadReviewAssignmentDetail().catch((error) => showToast(error.message, true));
  });
  $("#reviewAssignmentStatusFilter")?.addEventListener("change", () => {
    state.reviewAssignments.status = $("#reviewAssignmentStatusFilter")?.value || "all";
    state.reviewAssignments.page = 1;
    loadReviewAssignmentDetail().catch((error) => showToast(error.message, true));
  });
  $("#reviewAssignmentSearch")?.addEventListener("input", () => {
    state.reviewAssignments.query = $("#reviewAssignmentSearch")?.value.trim() || "";
    state.reviewAssignments.page = 1;
    window.clearTimeout(state.reviewAssignments.filterTimer);
    state.reviewAssignments.filterTimer = window.setTimeout(() => {
      loadReviewAssignmentDetail().catch((error) => showToast(error.message, true));
    }, 240);
  });
  $("#reviewAssignmentPrevious")?.addEventListener("click", () => {
    if (state.reviewAssignments.page <= 1) return;
    state.reviewAssignments.page -= 1;
    loadReviewAssignmentDetail().catch((error) => showToast(error.message, true));
  });
  $("#reviewAssignmentNext")?.addEventListener("click", () => {
    const pageCount = Number(state.reviewAssignments.detail?.page_count || 1);
    if (state.reviewAssignments.page >= pageCount) return;
    state.reviewAssignments.page += 1;
    loadReviewAssignmentDetail().catch((error) => showToast(error.message, true));
  });
  $("#reviewAssignmentPageJumpButton")?.addEventListener("click", () => {
    const pageCount = Number(state.reviewAssignments.detail?.page_count || 1);
    const page = Math.max(1, Math.min(pageCount, Number($("#reviewAssignmentPageJump")?.value || 1)));
    state.reviewAssignments.page = page;
    loadReviewAssignmentDetail().catch((error) => showToast(error.message, true));
  });
  $("#reviewAssignmentPageJump")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") $("#reviewAssignmentPageJumpButton")?.click();
  });
  $("#reviewAssignmentPageSize")?.addEventListener("change", () => {
    state.reviewAssignments.pageSize = Number($("#reviewAssignmentPageSize")?.value || 50);
    state.reviewAssignments.page = 1;
    loadReviewAssignmentDetail().catch((error) => showToast(error.message, true));
  });
}
