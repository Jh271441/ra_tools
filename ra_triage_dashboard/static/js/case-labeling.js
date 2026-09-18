/* Independent RA Case labeling workspace; model predictions are never loaded. */

function caseLabelingRouteOptions(overrides = {}) {
  const labeling = state.caseLabeling || {};
  return {
    issue: overrides.issue ?? labeling.issueId ?? "",
    taskId: overrides.taskId ?? labeling.taskId ?? "",
    search: overrides.search ?? labeling.search ?? "",
    status: overrides.status ?? labeling.status ?? "all",
    page: overrides.page ?? labeling.page ?? 1,
    pageSize: overrides.pageSize ?? labeling.pageSize ?? DEFAULT_CASE_PAGE_SIZE,
    baselines: overrides.baselines ?? state.selectedBaselineIds,
  };
}

function persistCaseLabelingRoute(overrides = {}, mode = "replace") {
  const url = pageUrl("labeling", caseLabelingRouteOptions(overrides));
  window.history[mode === "push" ? "pushState" : "replaceState"](
    { page: "labeling" }, "", url
  );
}

function activeLabelingBaselineIds() {
  return [...new Set(state.config?.case_labeling?.active_baseline_ids || [])].map(String);
}

function selectedActiveLabelingBaselineIds() {
  const active = new Set(activeLabelingBaselineIds());
  return normalizeBaselineIds(state.selectedBaselineIds).filter((id) => active.has(id));
}

function labelingBaselineItems(ids) {
  const wanted = new Set((ids || []).map(String));
  return (state.config?.baselines || state.baselineCatalog || []).filter((item) =>
    wanted.has(String(item.id))
  );
}

function canAccessCaseLabelingPreview() {
  return Boolean(state.session?.is_admin);
}

function caseLabelingStateText(value) {
  return ({ pending: "待标注", resolved: "已形成结果", conflict: "冲突待处理", stale: "裁决需确认" })[value] || value || "待标注";
}

function renderCaseLabelingTaskPicker() {
  const root = $("#caseLabelingTaskPicker");
  if (!root) return;
  const options = [
    { value: "", label: "全部标注" },
    ...(state.caseLabeling.tasks || []).map((task) => ({
      value: task.id,
      label: `${task.name || task.id} · ${task.member_count} Case`,
    })),
  ];
  populateUiSelect(root, options, state.caseLabeling.taskId || "");
  bindUiSelect(root);
}

function renderCaseLabelingStatusPicker() {
  const root = $("#caseLabelingStatusPicker");
  if (!root) return;
  populateUiSelect(root, [
    { value: "all", label: "全部状态" },
    { value: "pending", label: "待标注" },
    { value: "resolved", label: "已形成结果" },
    { value: "conflict", label: "冲突 / 需重新确认" },
  ], state.caseLabeling.status || "all");
  bindUiSelect(root);
}

async function loadCaseLabelingTasks() {
  const result = await api(withBaselineQuery("/api/labeling/tasks"));
  state.caseLabeling.tasks = result.items || [];
  if (
    state.caseLabeling.taskId &&
    !state.caseLabeling.tasks.some((item) => item.id === state.caseLabeling.taskId)
  ) {
    state.caseLabeling.taskId = "";
  }
  renderCaseLabelingTaskPicker();
}

function caseLabelingCardMarkup(item, index) {
  const statusClass = `label-state-${item.label_state || "pending"}`;
  const output = item.expected_output
    ? labelBadge(item.expected_output, "待标注")
    : `<span class="${statusClass}">${escapeHtml(caseLabelingStateText(item.label_state))}</span>`;
  return `<button class="issue-card case-labeling-card" type="button" data-labeling-issue="${escapeHtml(item.issue_id)}" data-labeling-index="${index}">
    <div class="issue-card-preview"><img src="${escapeHtml(item.thumbnail_url || "")}" alt="${escapeHtml(item.issue_id)} BEV" loading="lazy" /></div>
    <div class="issue-card-body">
      <div class="issue-card-heading"><strong>${escapeHtml(item.issue_id)}</strong>${output}</div>
      <p>${escapeHtml(item.scenario || item.title || "暂无场景说明")}</p>
      <div class="issue-card-status"><span>GT ${escapeHtml(item.gt_label || "待补充")}</span><span>来源 ${Number(item.source_count || 0)}</span></div>
    </div>
  </button>`;
}

function renderCaseLabelingInactiveState() {
  const selected = labelingBaselineItems(normalizeBaselineIds(state.selectedBaselineIds));
  const active = labelingBaselineItems(activeLabelingBaselineIds());
  const selectedText = selected.length
    ? selected.map((item) => item.label || item.id).join("、")
    : "当前数据集";
  const switches = active.length
    ? `<div class="case-labeling-active-switchers">${active.map((item) => `<button class="button button-primary" type="button" data-labeling-baseline="${escapeHtml(item.id)}">查看 ${escapeHtml(item.label || item.id)} · ${escapeHtml(String(item.count ?? "—"))}</button>`).join("")}</div>`
    : `<p>当前还没有已激活的标注数据集。</p>`;
  return `<div class="empty-state case-labeling-inactive-state"><p class="case-labeling-preview-badge">内测 · 仅管理员</p><h2>${escapeHtml(selectedText)} 尚未切换到 Case 标注</h2><p>该范围仍在「判错复核」工作台。Case 标注内测只列出已激活数据集，避免把未迁移范围显示成 0 个 Case。</p>${switches}</div>`;
}

function renderCaseLabelingList(data) {
  const list = $("#caseLabelingList");
  const items = data.items || [];
  const pagination = $("#caseLabelingGallery")?.querySelector(".case-pagination");
  if (pagination) pagination.hidden = Boolean(data.inactive);
  if (data.inactive) {
    list.innerHTML = renderCaseLabelingInactiveState();
    list.querySelectorAll("[data-labeling-baseline]").forEach((button) => {
      button.addEventListener("click", () => {
        setBaselineScopes([button.dataset.labelingBaseline]).catch((error) => showToast(error.message, true));
      });
    });
    $("#caseLabelingCount").textContent = "0";
    $("#caseLabelingSummary").textContent = "内测中 · 当前数据集尚未激活";
    $("#caseLabelingPageSummary").textContent = "— / —";
    $("#caseLabelingPrevious").disabled = true;
    $("#caseLabelingNext").disabled = true;
    if ($("#caseLabelingExportGt")) $("#caseLabelingExportGt").disabled = true;
    return;
  }
  list.innerHTML = items.length
    ? items.map(caseLabelingCardMarkup).join("")
    : `<div class="empty-state"><h2>当前范围没有 Case</h2><p>请切换已激活的数据集、任务或状态。</p></div>`;
  list.querySelectorAll("[data-labeling-issue]").forEach((button) => {
    button.addEventListener("click", () => selectCaseLabelingIssue(button.dataset.labelingIssue));
  });
  $("#caseLabelingCount").textContent = String(data.total || 0);
  $("#caseLabelingSummary").textContent = state.caseLabeling.taskId
    ? `任务范围 · ${data.total || 0} 个 Case`
    : `当前已激活数据集 · ${data.total || 0} 个 Case`;
  $("#caseLabelingPageSummary").textContent = `${data.page || 1} / ${data.pages || 1}`;
  $("#caseLabelingPrevious").disabled = Number(data.page || 1) <= 1;
  $("#caseLabelingNext").disabled = Number(data.page || 1) >= Number(data.pages || 1);
  $("#caseLabelingPageSize").value = String(data.page_size || DEFAULT_CASE_PAGE_SIZE);
  if ($("#caseLabelingExportGt")) {
    $("#caseLabelingExportGt").disabled = !state.session?.is_admin;
  }
}

async function loadCaseLabelingCases({ page = state.caseLabeling.page } = {}) {
  const seq = ++state.caseLabeling.requestSeq;
  if (!selectedActiveLabelingBaselineIds().length) {
    if (seq !== state.caseLabeling.requestSeq) return;
    state.caseLabeling.page = 1;
    state.caseLabeling.data = { items: [], total: 0, page: 1, pages: 1, page_size: state.caseLabeling.pageSize, inactive: true };
    renderCaseLabelingList(state.caseLabeling.data);
    persistCaseLabelingRoute({ issue: "", page: 1 });
    return;
  }
  const params = new URLSearchParams({
    baselines: selectedBaselineQueryValue(),
    task_id: state.caseLabeling.taskId || "",
    q: state.caseLabeling.search || "",
    status: state.caseLabeling.status || "all",
    page: String(Math.max(1, Number(page) || 1)),
    page_size: String(state.caseLabeling.pageSize || DEFAULT_CASE_PAGE_SIZE),
  });
  const result = await api(`/api/labeling/cases?${params}`);
  if (seq !== state.caseLabeling.requestSeq) return;
  state.caseLabeling.page = result.page || 1;
  state.caseLabeling.data = result;
  renderCaseLabelingList(result);
  persistCaseLabelingRoute({ issue: "", page: state.caseLabeling.page });
}

function labelingFrameAtT0(frames) {
  const list = Array.isArray(frames) ? frames : [];
  return list[heroFrameIndex(list)] || null;
}

function caseLabelingMediaMarkup(caseData) {
  const bev = labelingFrameAtT0(caseData?.assets?.frames);
  const camera = labelingFrameAtT0(caseData?.camera?.frames);
  const video = caseData?.assets?.video;
  const cards = [
    ["BEV", bev],
    ["Camera", camera],
  ].map(([label, frame]) => `<figure class="case-labeling-media-card"><figcaption>${label}${frame ? ` · ${escapeHtml(frameLabel(frame))}` : ""}</figcaption>${frame?.url ? `<img src="${escapeHtml(frame.url)}" alt="${label} ${escapeHtml(frameLabel(frame))}" />` : `<div class="no-asset">暂无 ${label}</div>`}</figure>`).join("");
  return `<div class="case-labeling-media-grid">${cards}</div>${video?.url ? `<section>${videoPlayerMarkup(video, { zoomable: false, compact: true })}</section>` : ""}`;
}

function caseLabelingTagMarkup(selectedTags) {
  const selected = new Set(selectedTags || []);
  const catalog = (state.config?.review_tag_catalog || []).filter(
    (item) => item.visible !== false && !item.deleted
  );
  const groups = [
    ["environment", "环境"], ["self_intent", "自车意图"],
    ["false_trigger", "误触发"], ["true_trigger", "应该触发"],
    ["ra", "正确触发"], ["no_assist", "无需协助"],
  ];
  return groups.map(([key, label]) => {
    const items = catalog.filter((item) => String(item.group || item.group_key || "") === key);
    if (!items.length) return "";
    return `<details class="review-tag-dropdown review-dropdown"><summary><span>${escapeHtml(label)}</span><span class="tag-group-chevron" aria-hidden="true"></span></summary><div class="review-tag-options">${items.map((item) => `<label class="tag-option"${item.hint ? ` title="${escapeHtml(item.hint)}"` : ""}><input type="checkbox" name="caseLabelTags" value="${escapeHtml(item.key)}" data-tag-group="${escapeHtml(key)}" ${selected.has(item.key) ? "checked" : ""}/><span>${escapeHtml(item.label)}</span></label>`).join("")}</div></details>`;
  }).join("");
}

function currentEditableLabelCase(caseData) {
  const cases = caseData?.label_cases || [];
  if (state.caseLabeling.taskId) {
    return cases.find((item) => item.task_id === state.caseLabeling.taskId) || null;
  }
  return cases.find((item) => !item.task_id && !item.source_run_id) || null;
}

function currentLabelingRevision(caseData) {
  const editable = currentEditableLabelCase(caseData);
  if (!editable) return null;
  const currentUser = String(state.session?.username || "").trim().toLowerCase();
  return (editable.resolution?.heads || []).find(
    (item) => String(item.author || "").trim().toLowerCase() === currentUser
  ) || editable.resolution?.result_revision || null;
}

function caseLabelingHistoryMarkup(caseData) {
  const all = (caseData.label_cases || []).flatMap((labelCase) =>
    (labelCase.resolution?.heads || []).map((revision) => ({ labelCase, revision }))
  );
  if (!all.length) return `<p class="muted">尚无工作台标注。</p>`;
  return all.sort((a, b) => Number(b.revision.id) - Number(a.revision.id)).map(({ labelCase, revision }) => `<article class="case-labeling-history-row"><header><strong>${escapeHtml(revision.author || "未记录")}</strong><span>${escapeHtml(revision.created_at || "")}</span></header><div>${labelBadge(revision.expected_output, "待补充")} · ${escapeHtml(labelCase.task_id ? "任务标注" : "历史/自由标注")}</div>${revision.rationale ? `<p>${escapeHtml(revision.rationale)}</p>` : ""}${revision.attachments?.length ? `<div class="tags">${revision.attachments.map((attachment, index) => `<a class="tag" href="${escapeHtml(attachment.url)}" target="_blank" rel="noreferrer">标注截图 ${index + 1}</a>`).join("")}</div>` : ""}</article>`).join("");
}

function caseLabelingCommentsMarkup(caseData) {
  const comments = caseData.comments || [];
  const count = comments.length;
  const button = `<button class="button button-quiet" type="button" id="caseLabelingOpenDiscussion">打开讨论${count ? ` · ${count}` : ""} <kbd>D</kbd></button>`;
  if (!comments.length) {
    return `${button}<p class="muted">尚无标注讨论。可在讨论面板回复历史线程或发起新讨论。</p>`;
  }
  const items = comments.map((comment) => {
    const body = typeof reviewCommentBodyMarkup === "function"
      ? reviewCommentBodyMarkup(comment.body || "", comment.attachments || [])
      : `<p>${escapeHtml(comment.body || "")}</p>`;
    const displayName = typeof reviewMentionDisplayName === "function"
      ? reviewMentionDisplayName(comment.author || "未记录")
      : (comment.author || "未记录");
    const sourceBits = [
      comment.label_task_id ? "任务讨论" : "",
      comment.source_run_id ? `历史来源 Run · ${comment.source_run_id}` : "",
    ].filter(Boolean);
    return `<article class="case-labeling-history-row"><header><strong>${escapeHtml(displayName)}</strong><span>${escapeHtml(comment.created_at || "")}</span></header><div class="comment-thread-body">${body}</div>${sourceBits.length ? `<small>${escapeHtml(sourceBits.join(" · "))}</small>` : ""}</article>`;
  }).join("");
  return `${button}<div class="case-labeling-history">${items}</div>`;
}

function renderCaseLabelingEditor(caseData) {
  const editable = currentEditableLabelCase(caseData);
  const revision = currentLabelingRevision(caseData);
  const aggregateResolved = (caseData.label_cases || []).find(
    (item) => item.resolution?.state === "resolved"
  )?.resolution?.result_revision;
  const source = revision || aggregateResolved || {};
  const exactTaskCase = state.caseLabeling.taskId
    ? (caseData.label_cases || []).find((item) => item.task_id === state.caseLabeling.taskId)
    : null;
  const resolution = exactTaskCase?.resolution || null;
  $("#caseLabelingEditor").innerHTML = `<form class="case-labeling-form" id="caseLabelingForm">
    <section><div class="review-section-heading"><h2>期望输出</h2><span>${escapeHtml(caseLabelingStateText(resolution?.state || (source.expected_output ? "resolved" : "pending")))}</span></div><div class="case-labeling-output-grid">${LABELS.map((label) => `<label><input type="radio" name="caseLabelOutput" value="${escapeHtml(label)}" ${source.expected_output === label ? "checked" : ""}/><span>${escapeHtml(label)}</span></label>`).join("")}</div></section>
    <section><div class="review-section-heading"><h2>Issue 标签</h2></div><div class="review-tag-groups-shell">${caseLabelingTagMarkup(source.tags || [])}</div></section>
    <section><label><span>标注依据</span><textarea id="caseLabelingRationale" placeholder="说明判断依据；此处不填写模型判错原因。">${escapeHtml(source.rationale || "")}</textarea></label></section>
    <label class="review-exclude-toggle"><input id="caseLabelingExcluded" type="checkbox" ${source.is_excluded ? "checked" : ""}/><span>应该排除</span></label>
    <label><span>标注截图（最多 4 张）</span><input id="caseLabelingAttachments" type="file" accept="image/png,image/jpeg,image/webp" multiple /></label>
    <button class="button button-primary" type="submit" ${state.session?.is_admin ? "" : "disabled"}>保存标注</button>
    ${resolution?.state === "conflict" || resolution?.state === "stale" ? `<section class="case-labeling-adjudication"><strong>标注冲突</strong><p>${(resolution.heads || []).map((item) => `${escapeHtml(item.author)}：${escapeHtml(item.expected_output || "待补充")}`).join(" · ")}</p><button class="button button-quiet" id="caseLabelingAdjudicate" type="button">按当前表单显式裁决</button></section>` : ""}
    <section><div class="review-section-heading"><h2>标注历史</h2></div><div class="case-labeling-history">${caseLabelingHistoryMarkup(caseData)}</div></section>
    <section><div class="review-section-heading"><h2>标注讨论</h2></div><div class="case-labeling-history">${caseLabelingCommentsMarkup(caseData)}</div></section>
  </form>`;
  $("#caseLabelingForm").addEventListener("submit", saveCaseLabelingRevision);
  $("#caseLabelingForm").addEventListener("input", () => { state.caseLabeling.dirty = true; });
  $("#caseLabelingForm").addEventListener("change", () => { state.caseLabeling.dirty = true; });
  $("#caseLabelingAdjudicate")?.addEventListener("click", adjudicateCaseLabeling);
  $("#caseLabelingOpenDiscussion")?.addEventListener("click", () => {
    openCaseLabelingDiscussion().catch((error) => showToast(error.message, true));
  });
}

async function selectCaseLabelingIssue(issueId, { updateRoute = true } = {}) {
  const normalized = String(issueId || "").trim();
  if (!normalized) return;
  const seq = ++state.caseLabeling.detailSeq;
  const task = state.caseLabeling.taskId ? `&task_id=${encodeURIComponent(state.caseLabeling.taskId)}` : "";
  const caseData = await api(withBaselineQuery(`/api/labeling/cases/${encodeURIComponent(normalized)}?${task ? task.slice(1) : ""}`));
  if (seq !== state.caseLabeling.detailSeq) return;
  state.caseLabeling.issueId = normalized;
  state.caseLabeling.caseData = caseData;
  state.caseLabeling.dirty = false;
  $("#caseLabelingGallery").classList.add("hidden");
  $("#caseLabelingDetail").classList.remove("hidden");
  $("#caseLabelingIssueTitle").textContent = normalized;
  $("#caseLabelingPosition").textContent = `${caseData.baseline_scope || ""} · GT ${caseData.gt_label || "待补充"}`;
  $("#caseLabelingMedia").innerHTML = `<div class="empty-state"><h2>正在加载 BEV / Camera…</h2></div>`;
  renderCaseLabelingEditor(caseData);
  if (updateRoute) persistCaseLabelingRoute({ issue: normalized }, "push");
  try {
    const media = await api(`/api/cases/${encodeURIComponent(normalized)}/media`);
    if (seq !== state.caseLabeling.detailSeq || state.caseLabeling.issueId !== normalized) return;
    Object.assign(caseData, media);
    $("#caseLabelingMedia").innerHTML = caseLabelingMediaMarkup(caseData);
    bindBevVideoPlayers($("#caseLabelingMedia"));
  } catch (error) {
    if (seq === state.caseLabeling.detailSeq) {
      $("#caseLabelingMedia").innerHTML = `<div class="empty-state"><h2>媒体加载失败</h2><p>${escapeHtml(error.message)}</p></div>`;
    }
  }
}

function closeCaseLabelingDetail({ updateRoute = true } = {}) {
  $("#caseLabelingMedia")?.querySelector("video")?.pause();
  state.caseLabeling.issueId = "";
  state.caseLabeling.caseData = null;
  state.caseLabeling.dirty = false;
  state.caseLabeling.detailSeq += 1;
  $("#caseLabelingDetail").classList.add("hidden");
  $("#caseLabelingGallery").classList.remove("hidden");
  if (updateRoute) persistCaseLabelingRoute({ issue: "" }, "push");
}

function caseLabelingFormPayload() {
  return {
    task_id: state.caseLabeling.taskId || "",
    expected_output: document.querySelector('input[name="caseLabelOutput"]:checked')?.value || "",
    tags: [...document.querySelectorAll('input[name="caseLabelTags"]:checked')].map((item) => item.value),
    evidence_gaps: [],
    rationale: $("#caseLabelingRationale")?.value || "",
    is_excluded: Boolean($("#caseLabelingExcluded")?.checked),
  };
}

async function saveCaseLabelingRevision(event) {
  event.preventDefault();
  const caseData = state.caseLabeling.caseData;
  if (!caseData) return;
  const revision = currentLabelingRevision(caseData);
  const payload = {
    ...caseLabelingFormPayload(),
    expected_previous_revision_id: revision?.id || null,
  };
  const files = [...($("#caseLabelingAttachments")?.files || [])];
  if (files.length > 4) {
    showToast("标注截图最多 4 张。", true);
    return;
  }
  const button = event.submitter || event.currentTarget.querySelector('[type="submit"]');
  button.disabled = true;
  try {
    let result;
    if (files.length) {
      const form = new FormData();
      form.append("payload", JSON.stringify(payload));
      files.forEach((file) => form.append("attachments", file, file.name));
      result = await api(`/api/labeling/cases/${encodeURIComponent(caseData.issue_id)}/revisions-with-attachments`, {
        method: "POST",
        body: form,
        headers: { "X-RA-Triage-Request": "labeling-v1" },
      });
    } else {
      result = await api(`/api/labeling/cases/${encodeURIComponent(caseData.issue_id)}/revisions`, {
        method: "POST", body: JSON.stringify(payload),
      });
    }
    acknowledgeLocalChange(result);
    state.caseLabeling.dirty = false;
    showToast("标注已保存。");
    await Promise.all([
      selectCaseLabelingIssue(caseData.issue_id, { updateRoute: false }),
      loadCaseLabelingCases({ page: state.caseLabeling.page }),
    ]);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function adjudicateCaseLabeling() {
  const caseData = state.caseLabeling.caseData;
  const labelCase = (caseData?.label_cases || []).find(
    (item) => item.task_id === state.caseLabeling.taskId
  );
  if (!labelCase) return;
  const resolution = labelCase.resolution || {};
  const payload = {
    ...caseLabelingFormPayload(),
    source_revision_ids: (resolution.heads || []).map((item) => item.id),
    expected_previous_resolution_id: resolution.adjudication?.id || null,
  };
  try {
    const result = await api(`/api/labeling/label-cases/${encodeURIComponent(labelCase.id)}/adjudications`, {
      method: "POST", body: JSON.stringify(payload),
    });
    acknowledgeLocalChange(result);
    state.caseLabeling.dirty = false;
    showToast("裁决已保存。");
    await selectCaseLabelingIssue(caseData.issue_id, { updateRoute: false });
    await loadCaseLabelingCases({ page: state.caseLabeling.page });
  } catch (error) {
    showToast(error.message, true);
  }
}

function openCaseLabelingDiscussion(focusCommentId = 0) {
  const issueId = state.caseLabeling.issueId || state.caseLabeling.caseData?.issue_id;
  if (!issueId || typeof openAnalysisDiscussion !== "function") return Promise.resolve();
  return openAnalysisDiscussion(issueId, {
    source: "labeling",
    kind: "labeling",
    taskId: state.caseLabeling.taskId || "",
    focusCommentId,
  });
}

function bindCaseLabelingDiscussionShortcut() {
  if (document.documentElement.dataset.caseLabelingKeys === "1") return;
  document.documentElement.dataset.caseLabelingKeys = "1";
  document.addEventListener("keydown", (event) => {
    if (state.activePage !== "labeling" || !state.caseLabeling.issueId) return;
    const key = String(event.key || "").toLowerCase();
    if (key !== "d") return;
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest("textarea, input, select, [contenteditable='true']")) return;
    event.preventDefault();
    const dialog = $("#analysisDiscussionDialog");
    if (dialog?.open && state.analysisDiscussion?.kind === "labeling") {
      if (typeof closeDialog === "function") closeDialog("analysisDiscussionDialog");
      else dialog.close();
      return;
    }
    if (document.querySelector("dialog[open]")) return;
    openCaseLabelingDiscussion().catch((error) => showToast(error.message, true));
  });
}

async function enterCaseLabeling({ route = null } = {}) {
  if (!canAccessCaseLabelingPreview() && !state.session?.identity_pending) {
    showToast("Case 标注内测仅限管理员。", true);
    if (typeof showPage === "function") showPage("review", { historyMode: "replace" });
    return;
  }
  const filters = route?.labelingFilters || parsePageRoute().labelingFilters || {};
  state.caseLabeling.taskId = filters.taskId ?? state.caseLabeling.taskId;
  state.caseLabeling.search = filters.search ?? state.caseLabeling.search;
  state.caseLabeling.status = filters.status ?? state.caseLabeling.status;
  state.caseLabeling.page = filters.page || 1;
  state.caseLabeling.pageSize = filters.pageSize || DEFAULT_CASE_PAGE_SIZE;
  $("#caseLabelingSearch").value = state.caseLabeling.search;
  await loadCaseLabelingTasks();
  renderCaseLabelingStatusPicker();
  await loadCaseLabelingCases({ page: state.caseLabeling.page });
  const issue = route?.issue || filters.issue || "";
  if (issue) await selectCaseLabelingIssue(issue, { updateRoute: false });
  else closeCaseLabelingDetail({ updateRoute: false });
}

function bindCaseLabelingEvents() {
  bindCaseLabelingDiscussionShortcut();
  $("#caseLabelingTask")?.addEventListener("change", () => {
    state.caseLabeling.taskId = $("#caseLabelingTask").value || "";
    state.caseLabeling.page = 1;
    closeCaseLabelingDetail({ updateRoute: false });
    loadCaseLabelingCases({ page: 1 }).catch((error) => showToast(error.message, true));
  });
  $("#caseLabelingStatus")?.addEventListener("change", () => {
    state.caseLabeling.status = $("#caseLabelingStatus").value || "all";
    loadCaseLabelingCases({ page: 1 }).catch((error) => showToast(error.message, true));
  });
  let timer = null;
  $("#caseLabelingSearch")?.addEventListener("input", () => {
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      state.caseLabeling.search = $("#caseLabelingSearch").value.trim();
      loadCaseLabelingCases({ page: 1 }).catch((error) => showToast(error.message, true));
    }, 250);
  });
  $("#caseLabelingReset")?.addEventListener("click", () => {
    state.caseLabeling.taskId = "";
    state.caseLabeling.status = "all";
    state.caseLabeling.search = "";
    $("#caseLabelingSearch").value = "";
    renderCaseLabelingTaskPicker();
    renderCaseLabelingStatusPicker();
    loadCaseLabelingCases({ page: 1 }).catch((error) => showToast(error.message, true));
  });
  $("#caseLabelingPrevious")?.addEventListener("click", () => loadCaseLabelingCases({ page: state.caseLabeling.page - 1 }).catch((error) => showToast(error.message, true)));
  $("#caseLabelingNext")?.addEventListener("click", () => loadCaseLabelingCases({ page: state.caseLabeling.page + 1 }).catch((error) => showToast(error.message, true)));
  $("#caseLabelingPageSize")?.addEventListener("change", (event) => {
    state.caseLabeling.pageSize = Number(event.target.value) || DEFAULT_CASE_PAGE_SIZE;
    loadCaseLabelingCases({ page: 1 }).catch((error) => showToast(error.message, true));
  });
  $("#caseLabelingBack")?.addEventListener("click", () => closeCaseLabelingDetail());
  $("#caseLabelingExportGt")?.addEventListener("click", () => {
    (async () => {
      try {
        const result = await api("/api/labeling/gt-export-previews", {
          method: "POST",
          body: JSON.stringify({ baselines: selectedBaselineQueryValue(), issue_ids: [] }),
        });
        acknowledgeLocalChange(result);
        window.location.href = result.download_url;
      } catch (error) {
        showToast(error.message, true);
      }
    })();
  });
}
