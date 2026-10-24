/* Labeling summary page: state, routes, filters, rendering and events.
 * Classic-script public functions retain their existing names for routing. */
let labelSummaryRequest = 0;
let labelSummaryPage = 1;
let labelSummaryPageSize = 20;
let labelSummaryRouteRestored = false;
let labelSummarySearchTimer = null;
let labelSummaryTasks = [];
let labelSummaryData = null;
const labelSummaryFilters = {
  search: "", issueIds: [], taskId: "", status: [], author: [], assignee: [],
  label: [], gt: [], commentState: [], exclusion: [], cluster: "", gtUpdate: "",
};

function labelSummaryRouteOptions(overrides = {}) {
  return {
    search: overrides.search ?? labelSummaryFilters.search,
    issueIds: overrides.issueIds ?? labelSummaryFilters.issueIds,
    taskId: overrides.taskId ?? labelSummaryFilters.taskId,
    status: overrides.status ?? labelSummaryFilters.status,
    author: overrides.author ?? labelSummaryFilters.author,
    assignee: overrides.assignee ?? labelSummaryFilters.assignee,
    label: overrides.label ?? labelSummaryFilters.label,
    gt: overrides.gt ?? labelSummaryFilters.gt,
    commentState: overrides.commentState ?? labelSummaryFilters.commentState,
    exclusion: overrides.exclusion ?? labelSummaryFilters.exclusion,
    cluster: overrides.cluster ?? labelSummaryFilters.cluster,
    gtUpdate: overrides.gtUpdate ?? labelSummaryFilters.gtUpdate,
    page: overrides.page ?? labelSummaryPage,
    pageSize: overrides.pageSize ?? labelSummaryPageSize,
    baselines: overrides.baselines ?? state.selectedBaselineIds,
  };
}

function restoreLabelSummaryRoute({ force = false } = {}) {
  if (labelSummaryRouteRestored && !force) return;
  labelSummaryRouteRestored = true;
  const params = new URLSearchParams(window.location.search);
  labelSummaryFilters.search = String(params.get("q") || "").trim();
  labelSummaryFilters.issueIds = parseFilterList(params.get("issue_ids")).filter((value) => ISSUE_QUERY_ID_RE.test(value));
  labelSummaryFilters.taskId = String(params.get("task") || "").trim();
  labelSummaryFilters.status = parseFilterList(params.get("status")).filter((value) => ["resolved", "pending", "conflict"].includes(value));
  labelSummaryFilters.author = parseFilterList(params.get("author"));
  labelSummaryFilters.assignee = parseFilterList(params.get("assignee"));
  labelSummaryFilters.label = parseFilterList(params.get("label")).filter((value) => LABELS.includes(value));
  labelSummaryFilters.gt = parseFilterList(params.get("gt")).filter((value) => LABELS.includes(value));
  labelSummaryFilters.commentState = parseFilterList(params.get("comment_state")).filter((value) => ["with", "without"].includes(value));
  labelSummaryFilters.exclusion = parseFilterList(params.get("exclusion")).filter((value) => ["active", "excluded"].includes(value));
  labelSummaryFilters.cluster = String(params.get("cluster") || "").trim();
  labelSummaryFilters.gtUpdate = ["ready", "blocked"].includes(params.get("gt_update")) ? params.get("gt_update") : "";
  labelSummaryPage = Math.max(1, Number(params.get("page") || 1));
  labelSummaryPageSize = CASE_PAGE_SIZES.includes(Number(params.get("page_size"))) ? Number(params.get("page_size")) : 20;
}

function labelSummaryViewTitle() {
  return labelSummaryFilters.gtUpdate === "ready" ? uiText("GT 待更新", "GT updates")
    : labelSummaryFilters.gtUpdate === "blocked" ? uiText("GT 需确认", "GT needs attention")
      : uiText("标注汇总", "Labeling summary");
}

function labelSummaryNavActive(item) {
  return item.id === "gtUpdatesNavButton" ? Boolean(labelSummaryFilters.gtUpdate) : !labelSummaryFilters.gtUpdate;
}

function syncLabelSummaryNavigation() {
  document.querySelectorAll('.sidebar-item[data-page-target="labeling-summary"]').forEach((item) => {
    const active = state.activePage === "labeling-summary" && labelSummaryNavActive(item);
    item.classList.toggle("active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  const link = $("#gtUpdatesNavButton");
  if (link) {
    link.title = uiText("GT 待更新", "GT updates");
    link.href = pageUrl("labeling-summary", { search: "", issueIds: [], taskId: "", status: [], author: [], assignee: [], label: [], gt: [], commentState: [], exclusion: [], cluster: "", gtUpdate: "ready", page: 1 });
  }
  if (state.activePage === "labeling-summary") renderPageChrome();
}

function setLabelSummaryView(view, { reset = false } = {}) {
  window.clearTimeout(labelSummarySearchTimer);
  if (reset) Object.assign(labelSummaryFilters, {
    search: "", issueIds: [], taskId: "", status: [], author: [], assignee: [],
    label: [], gt: [], commentState: [], exclusion: [], cluster: "",
  });
  labelSummaryFilters.gtUpdate = ["ready", "blocked"].includes(view) ? view : "";
  labelSummaryRouteRestored = true;
  labelSummaryPage = 1;
  syncLabelSummaryNavigation();
}

function refreshLabelSummaryLanguage() {
  syncLabelSummaryNavigation();
  if (state.activePage !== "labeling-summary" || !labelSummaryData) return;
  // Loading has not established the task directory yet. Do not discard a
  // restored task selection when language changes before that response.
  renderLabelSummaryFilters({ items: labelSummaryTasks }, labelSummaryData);
  renderLabelingSummary(labelSummaryData);
}

function labelSummaryGtViewsMarkup(data) {
  const counts = data.gt_update_counts || {};
  const views = [
    { key: "", label: uiText("全部标注", "All annotations"), count: counts.all },
    { key: "ready", label: uiText("GT 待更新", "GT updates"), count: counts.ready },
    { key: "blocked", label: uiText("需确认", "Needs attention"), count: counts.blocked },
  ];
  const copy = labelSummaryFilters.gtUpdate === "blocked"
    ? uiText("来源冲突、标注未齐或裁决需确认", "Conflicting sources, incomplete labels or stale decisions")
    : labelSummaryFilters.gtUpdate === "ready"
      ? uiText("全部来源的有效结论与当前 GT 不同", "Valid results across all sources differ from current GT") : "";
  return `<section class="page-card label-summary-viewbar"><nav class="label-summary-view-tabs" aria-label="${escapeHtml(uiText("标注清单视图", "Annotation views"))}">${views.map((view) => `<button class="button ${labelSummaryFilters.gtUpdate === view.key ? "button-primary" : "button-quiet"}" type="button" data-gt-update-view="${view.key}" aria-pressed="${labelSummaryFilters.gtUpdate === view.key}"><span>${escapeHtml(view.label)}</span><strong>${Number(view.count || 0)}</strong></button>`).join("")}</nav>${copy ? `<span class="label-summary-view-copy">${escapeHtml(copy)}</span>` : ""}</section>`;
}

function persistLabelSummaryRoute() {
  if (state.activePage !== "labeling-summary") return;
  window.history.replaceState(
    { ...(window.history.state || {}), page: "labeling-summary" },
    "",
    pageUrl("labeling-summary", labelSummaryRouteOptions()),
  );
}

function labelSummaryCaseUrl(filters = {}) {
  const task = labelSummaryTasks.find((item) => item.id === labelSummaryFilters.taskId);
  if (task?.workflow_mode === "model_review_and_case_label") {
    return pageUrl("review", {
      ...reviewAssignmentRouteOptions({
        ...task, split_id: task.id, model_run_id: task.selection_source_run_id,
        baseline_ids: state.selectedBaselineIds,
      }, "review"),
      issue: filters.issue || "",
    });
  }
  if (labelSummaryFilters.gtUpdate) return pageUrl("labeling", { issue: filters.issue || "", baselines: state.selectedBaselineIds });
  return pageUrl("labeling", { issue: "", taskId: labelSummaryFilters.taskId,
    search: labelSummaryFilters.search, issueIds: labelSummaryFilters.issueIds,
    status: labelSummaryFilters.status,
    author: labelSummaryFilters.author, assignee: labelSummaryFilters.assignee,
    cluster: labelSummaryFilters.cluster, label: labelSummaryFilters.label,
    gt: labelSummaryFilters.gt, commentState: labelSummaryFilters.commentState,
    exclusion: labelSummaryFilters.exclusion, page: 1,
    ...filters });
}

function renderLabelSummaryPicker(selector, options, selected) {
  const picker = $(selector);
  populateUiSelect(picker, options, selected);
  bindUiSelect(picker, { maxHeight: 300, maxWidth: 420 });
}

function updateLabelSummaryMultiFilter(key, values) {
  labelSummaryFilters[key] = parseFilterList(values);
  labelSummaryFilters.cluster = "";
  labelSummaryPage = 1;
  loadLabelingSummary().catch((error) => showToast(error.message, true));
}

function renderLabelSummaryMultiPicker(selector, options, selected, key) {
  const root = $(selector);
  if (!root) return;
  const fingerprint = JSON.stringify(options.map((item) => [item.value, item.label]));
  if (root.dataset.optionsFingerprint === fingerprint && root.querySelector(".multi-filter-trigger")) {
    setMultiFilterValues(root, selected);
    return;
  }
  if (root.classList.contains("is-open")) return;
  renderMultiFilter(root, {
    options,
    selected,
    onChange: (values) => updateLabelSummaryMultiFilter(key, values),
  });
  root.dataset.optionsFingerprint = fingerprint;
}

function renderLabelSummaryFilters(tasks, data) {
  const taskOptions = [{ value: "", label: uiText("全部标注（含历史迁移）", "All annotations (including migrated)") }, ...(tasks.items || []).map((task) => ({ value: task.id, label: task.name || uiText("标注任务", "Labeling task") }))];
  if (!taskOptions.some((item) => item.value === labelSummaryFilters.taskId)) labelSummaryFilters.taskId = "";
  const labelerOptions = [...new Set([...(data.labelers || []), ...parseFilterList(labelSummaryFilters.author)])].map((value) => ({ value, label: value }));
  const assigneeOptions = [...new Set([...(data.assignees || []), ...parseFilterList(labelSummaryFilters.assignee)])].map((value) => ({ value, label: value }));
  renderLabelSummaryPicker("#labelSummaryTaskPicker", taskOptions, labelSummaryFilters.taskId);
  renderLabelSummaryMultiPicker("#labelSummaryStatusPicker", [
    { value: "resolved", label: uiText("已形成结论", "Resolved") },
    { value: "pending", label: uiText("待形成结论", "Pending") }, { value: "conflict", label: uiText("待裁决 / 需确认", "Needs adjudication / confirmation") },
  ], labelSummaryFilters.status, "status");
  renderLabelSummaryMultiPicker("#labelSummaryAuthorPicker", labelerOptions, labelSummaryFilters.author, "author");
  renderLabelSummaryMultiPicker("#labelSummaryAssigneePicker", assigneeOptions, labelSummaryFilters.assignee, "assignee");
  renderLabelSummaryMultiPicker("#labelSummaryLabelPicker", LABELS.map((value) => ({ value, label: value })), labelSummaryFilters.label, "label");
  renderLabelSummaryMultiPicker("#labelSummaryGtPicker", LABELS.map((value) => ({ value, label: value })), labelSummaryFilters.gt, "gt");
  renderLabelSummaryMultiPicker("#labelSummaryDiscussionPicker", [
    { value: "with", label: uiText("有讨论", "With discussion") }, { value: "without", label: uiText("无讨论", "Without discussion") },
  ], labelSummaryFilters.commentState, "commentState");
  renderLabelSummaryMultiPicker("#labelSummaryExclusionPicker", [
    { value: "active", label: uiText("未排除", "Active") },
    { value: "excluded", label: uiText("已排除", "Excluded") },
  ], labelSummaryFilters.exclusion, "exclusion");
  const search = $("#labelSummarySearch");
  if (search && document.activeElement !== search) search.value = labelSummaryFilters.search;
  const exportButton = $("#labelSummaryExportGt");
  if (exportButton) exportButton.disabled = !state.session?.is_admin;
  if (typeof updateIssueQueryButton === "function") updateIssueQueryButton();
}

function labelSummaryFilterPayload() {
  return {
    baselines: selectedBaselineQueryValue(),
    task_id: labelSummaryFilters.taskId,
    q: labelSummaryFilters.search,
    issue_ids: labelSummaryFilters.issueIds.join(","),
    status: joinFilterList(labelSummaryFilters.status),
    author: joinFilterList(labelSummaryFilters.author),
    assignee: joinFilterList(labelSummaryFilters.assignee),
    label: joinFilterList(labelSummaryFilters.label),
    gt: joinFilterList(labelSummaryFilters.gt),
    comment_state: joinFilterList(labelSummaryFilters.commentState),
    exclusion: joinFilterList(labelSummaryFilters.exclusion),
    cluster: labelSummaryFilters.cluster,
    gt_update: labelSummaryFilters.gtUpdate,
  };
}

function labelSummaryStatusItems(data) {
  const counts = data.submitted_states || {};
  return [
    { key: "resolved", cssKey: "completed", label: uiText("已形成结论", "Resolved"), count: Number(counts.resolved || 0), description: "多来源聚合后已形成唯一结论" },
    { key: "pending", cssKey: "pending", label: uiText("待形成结论", "Pending"), count: Number(counts.pending || 0), description: "已有提交，但还没有形成唯一结论" },
    { key: "conflict", cssKey: "blocked_by_label", label: uiText("待裁决 / 需确认", "Needs adjudication / confirmation"), count: Number(counts.conflict || 0), description: "当前来源之间存在冲突或 Issue 裁决已过期" },
  ];
}

function labelSummaryStatusMarkup(data) {
  const statuses = labelSummaryStatusItems(data);
  const total = statuses.reduce((sum, item) => sum + item.count, 0);
  const segments = total
    ? statuses.filter((item) => item.count).map((item) => {
      const percent = analysisPiePercent(item, total);
      return `<span class="analysis-review-status-segment status-${escapeHtml(item.cssKey)}" data-review-status-key="${escapeHtml(item.key)}" style="width:${percent}%" title="${escapeHtml(`${item.label}: ${item.count}, ${percent}%`)}"></span>`;
    }).join("")
    : '<span class="analysis-review-status-empty">暂无标注提交</span>';
  const legend = statuses.map((item) => {
    const percent = analysisPiePercent(item, total);
    return `<div class="analysis-review-status-legend-item status-${escapeHtml(item.cssKey)}" data-review-status-key="${escapeHtml(item.key)}" role="listitem" tabindex="0" title="${escapeHtml(item.description)}"><span class="analysis-review-status-swatch"></span><span class="analysis-review-status-legend-copy"><strong>${escapeHtml(item.label)}</strong><small>${item.count} · ${percent}%</small></span></div>`;
  }).join("");
  return `<div class="analysis-review-status-visual"><div class="analysis-review-status-bar" role="img" aria-label="${escapeHtml(statuses.map((item) => `${item.label} ${item.count}`).join("；"))}">${segments}</div><div class="analysis-review-status-legend" role="list">${legend}</div></div>`;
}

function labelSummaryMatrixMarkup(data) {
  const labels = ["误触发", "正确触发", "无需协助"];
  const pairs = new Map((data.pairs || []).map((row) => [`${row.gt}|${row.label}`, Number(row.count || 0)]));
  const columnTotals = new Map(labels.map((label) => [label, 0]));
  const rows = labels.map((gt, rowIndex) => {
    const cells = labels.map((label, columnIndex) => {
      const count = pairs.get(`${gt}|${label}`) || 0;
      columnTotals.set(label, (columnTotals.get(label) || 0) + count);
      return `<td class="${gt === label ? "confusion-match" : count ? "confusion-mismatch" : ""}" data-confusion-row="${rowIndex}" data-confusion-col="${columnIndex}" tabindex="0" title="GT ${escapeHtml(gt)} · 标注 ${escapeHtml(label)}: ${count}">${count}</td>`;
    }).join("");
    const rowTotal = labels.reduce((sum, label) => sum + (pairs.get(`${gt}|${label}`) || 0), 0);
    return `<tr><th scope="row" data-confusion-row="${rowIndex}">${escapeHtml(gt)}</th>${cells}<td class="confusion-total" data-confusion-row="${rowIndex}" data-confusion-total tabindex="0">${rowTotal}</td></tr>`;
  }).join("");
  const total = [...columnTotals.values()].reduce((sum, count) => sum + count, 0);
  return `<table class="analysis-confusion-table"><thead><tr><th>GT ↓ / 标注 →</th>${labels.map((label, index) => `<th scope="col" data-confusion-col="${index}">${escapeHtml(label)}</th>`).join("")}<th scope="col" data-confusion-total-col>合计</th></tr></thead><tbody>${rows}</tbody><tfoot><tr><th>合计</th>${labels.map((label, index) => `<td class="confusion-total" data-confusion-col="${index}">${columnTotals.get(label) || 0}</td>`).join("")}<td class="confusion-total">${total}</td></tr></tfoot></table>`;
}

function labelSummaryClusterPanels(data) {
  const catalog = new Map((state.config?.review_tag_catalog || []).map((item) => [item.key, item]));
  const tagCounts = data.tags || {};
  const groupItems = (section, group) => Object.entries(tagCounts)
    .map(([key, count]) => ({ key, count: Number(count || 0), item: catalog.get(key) || {} }))
    .filter(({ item }) => item.section === section && item.group === group)
    .map(({ key, count, item }) => ({ key, count, label: item.label || key, description: item.hint || "" }))
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label));
  const makeGroup = (key, label, items) => ({ key, label, annotated_count: items.reduce((sum, item) => sum + item.count, 0), items });
  const panels = [
    { key: "environment", label: "场景环境", layout: "single", groups: [makeGroup("environment", "场景环境", groupItems("scene", "environment"))] },
    { key: "self_intent", label: "自车意图", layout: "single", groups: [makeGroup("self_intent", "自车意图", groupItems("scene", "self_intent"))] },
    { key: "trigger", label: "触发判定", layout: "dual", groups: [makeGroup("false_trigger", "误触发", groupItems("interaction_decision", "false_trigger")), makeGroup("true_trigger", "正确触发", groupItems("interaction_decision", "true_trigger"))] },
    { key: "egress", label: "如何脱困", layout: "dual", groups: [makeGroup("ra", "RA", groupItems("egress", "ra")), makeGroup("no_assist", "无需协助", groupItems("egress", "no_assist"))] },
  ];
  return panels.map((panel) => {
    const dual = panel.layout === "dual";
    return `<article class="page-card analysis-cluster-card layout-${panel.layout}" data-panel="${panel.key}"><div class="section-heading"><div><h3>${escapeHtml(panel.label)}</h3></div></div><div class="analysis-pie-groups ${dual ? "dual" : "single"}">${panel.groups.map((group) => renderAnalysisClusterGroup(group, panel, { dual, animatePies: false })).join("")}</div></article>`;
  }).join("");
}

function labelSummarySourceMarkup(item) {
  const source = item.expected_output_source || { kind: "unknown" };
  const sources = source.sources || [];
  const names = { issue_adjudication: uiText("Issue 裁决", "Issue decision"), task_adjudication: uiText("任务内裁决", "Task decision"), source_consensus: uiText("多来源一致", "Source consensus"), consensus: uiText("多人一致", "Reviewer consensus"), single: uiText("单人标注", "Single annotation"), unresolved: uiText("尚未形成有效结论", "No valid result yet"), unknown: uiText("来源未记录", "Source not recorded") };
  const label = names[source.kind] || names.unknown;
  const authors = (source.authors || []).join("、");
  const containsDecision = source.kind === "source_consensus" && sources.some((value) => value.kind === "task_adjudication");
  const detail = sources.map((value) => `${names[value.kind] || value.kind} · ${value.task_id ? `${uiText("任务", "Task")} ${value.task_id}` : uiText("任务外标注", "Outside tasks")}${value.source_run_id ? ` · Run ${value.source_run_id}` : ""} · ${(value.authors || []).join("、")}${value.revision_ids?.length ? ` · ${uiText("记录", "Revisions")} ${value.revision_ids.join("、")}` : ""}`).join("\n");
  const text = `${label}${containsDecision ? uiText("（含任务裁决）", " (includes task decisions)") : ""}${source.kind === "source_consensus" ? ` · ${uiText(`${sources.length} 个来源`, `${sources.length} sources`)}` : ""}${authors ? ` · ${authors}` : ""}`;
  const trace = detail || (source.decision_id ? `${uiText("Issue 裁决", "Issue decision")} #${source.decision_id} · ${authors}` : "");
  return trace ? `<details class="label-summary-source"><summary>${uiText("来源", "Source")}: ${escapeHtml(text)}</summary><div class="label-summary-source-trace">${trace.split("\n").map((line) => `<p>${escapeHtml(line)}</p>`).join("")}</div></details>` : `<span class="label-summary-source">${uiText("来源", "Source")}: ${escapeHtml(text)}</span>`;
}

function showLabelSummaryRules() {
  let dialog = $("#labelSummaryRulesDialog");
  if (!dialog) {
    dialog = document.createElement("dialog");
    dialog.id = "labelSummaryRulesDialog";
    dialog.className = "dialog label-summary-rules-dialog";
    dialog.setAttribute("aria-labelledby", "labelSummaryRulesTitle");
    document.body.appendChild(dialog);
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  }
  if (labelSummaryFilters.gtUpdate) {
    dialog.innerHTML = `<div class="dialog-card"><div class="dialog-heading"><h2 id="labelSummaryRulesTitle">${uiText("GT 更新规则", "GT update rules")}</h2><button class="icon-button" type="button" data-close-summary-rules aria-label="${uiText("关闭", "Close")}">×</button></div>
      <ol class="label-summary-gt-rules"><li>${uiText("汇总当前 Issue 的全部任务结果和任务外标注。有效的 Issue 裁决优先。", "Combine all task results and annotations outside tasks. A valid Issue decision takes precedence.")}</li><li>${uiText("没有 Issue 裁决时，全部来源必须完成且结论一致。", "Without an Issue decision, all sources must be complete and agree.")}</li><li>${uiText("结论与当前 GT 不同，或 GT 未设置：列入 GT 待更新。", "A result that differs from current GT, or fills a missing GT, appears in GT updates.")}</li><li>${uiText("来源冲突、标注未齐或裁决过期：列入需确认。", "Conflicts, incomplete labels or stale decisions appear in Needs attention.")}</li><li>${uiText("任务筛选只限定 Issue 范围，GT 更新仍依据全部来源。GT 一致后，刷新即可退出待更新清单。", "A task filter limits Issue membership; GT eligibility still considers all sources. After GT matches, refresh to remove the Issue from this queue.")}</li></ol>
      <p class="dialog-copy">${uiText("查看清单不会修改 GT。导出沿用现有权限和审核流程。", "Viewing this queue does not change GT. Export keeps the existing permissions and review workflow.")}</p><div class="dialog-actions"><button class="button button-quiet" type="button" data-close-summary-rules>${uiText("知道了", "Got it")}</button></div></div>`;
  } else dialog.innerHTML = `<div class="dialog-card"><div class="dialog-heading"><h2 id="labelSummaryRulesTitle">期望输出规则</h2><button class="icon-button" type="button" data-close-summary-rules aria-label="关闭">×</button></div>
    <p class="dialog-copy">先形成任务结果，再汇总为 Case 的最终结果。</p>
    <div class="label-summary-flow" role="group" aria-label="期望输出裁决流程">
      <section class="label-summary-flow-lane" aria-labelledby="labelRuleTaskTitle">
        <h3 id="labelRuleTaskTitle"><span>1</span> 任务内</h3>
        <div class="label-summary-flow-input">分配人员各自的最新提交</div>
        <div class="label-summary-flow-branches">
          <div class="label-summary-flow-branch"><span>有有效任务裁决</span><span aria-hidden="true">→</span><strong class="is-final">采用任务裁决</strong></div>
          <div class="label-summary-flow-branch"><span>无裁决 · 提交齐全且一致</span><span aria-hidden="true">→</span><strong>采用标注结果</strong></div>
          <div class="label-summary-flow-branch"><span>缺提交 / 冲突 / 裁决过期</span><span aria-hidden="true">→</span><strong class="is-pending">待处理</strong></div>
        </div>
        <small>选定单个任务时，只看这一层。</small>
      </section>
      <section class="label-summary-flow-lane" aria-labelledby="labelRuleIssueTitle">
        <h3 id="labelRuleIssueTitle"><span>2</span> 全部标注</h3>
        <div class="label-summary-flow-input">各任务结果 + 任务外标注</div>
        <div class="label-summary-flow-branches">
          <div class="label-summary-flow-branch"><span>有有效 Issue 裁决</span><span aria-hidden="true">→</span><strong class="is-final">采用 Issue 裁决</strong></div>
          <div class="label-summary-flow-branch"><span>无裁决 · 所有来源有效且一致</span><span aria-hidden="true">→</span><strong>采用一致结果</strong></div>
          <div class="label-summary-flow-branch"><span>未完成 / 冲突 / 裁决过期</span><span aria-hidden="true">→</span><strong class="is-pending">待处理</strong></div>
        </div>
        <small>先完成任务内结果，才能做 Issue 裁决。</small>
      </section>
    </div>
    <section class="label-summary-rule-examples" aria-labelledby="labelRuleExamplesTitle"><h3 id="labelRuleExamplesTitle">三个案例，一眼看懂</h3>
      <div class="label-summary-example"><h4>① 双人一致</h4><div class="label-summary-example-flow">
        <div class="label-summary-example-node example-votes"><div><span>甲</span>${labelBadge("误触发")}</div><div><span>乙</span>${labelBadge("误触发")}</div></div>
        <span class="label-summary-example-arrow" aria-hidden="true">→</span><div class="label-summary-example-node example-action"><strong>多人一致</strong><small>提交齐全</small></div>
        <span class="label-summary-example-arrow" aria-hidden="true">→</span><div class="label-summary-example-node example-output"><small>期望输出</small>${labelBadge("误触发")}</div>
      </div></div>
      <div class="label-summary-example"><h4>② 任务内冲突</h4><div class="label-summary-example-flow">
        <div class="label-summary-example-node example-votes"><div><span>甲</span>${labelBadge("误触发")}</div><div><span>乙</span>${labelBadge("正确触发")}</div></div>
        <span class="label-summary-example-arrow" aria-hidden="true">→</span><div class="label-summary-example-node example-action"><strong>任务内裁决</strong><small>丙 · 原始冲突保留</small></div>
        <span class="label-summary-example-arrow" aria-hidden="true">→</span><div class="label-summary-example-node example-output"><small>该任务期望输出</small>${labelBadge("正确触发")}</div>
      </div></div>
      <div class="label-summary-example"><h4>③ 跨任务冲突</h4><div class="label-summary-example-flow">
        <div class="label-summary-example-node example-votes"><div><span>任务 A</span>${labelBadge("误触发")}</div><div><span>任务 B</span>${labelBadge("正确触发")}</div></div>
        <span class="label-summary-example-arrow" aria-hidden="true">→</span><div class="label-summary-example-node example-action"><strong>Issue 裁决</strong><small>丁 · 任务原结果保留</small></div>
        <span class="label-summary-example-arrow" aria-hidden="true">→</span><div class="label-summary-example-node example-output"><small>全部标注期望输出</small>${labelBadge("无需协助")}</div>
      </div></div>
    </section>
    <p class="label-summary-rules-note">来源变化 → 裁决需重新确认；GT 仅作对照。</p>
    <div class="dialog-actions"><button class="button button-quiet" type="button" data-close-summary-rules>知道了</button></div></div>`;
  dialog.querySelectorAll("[data-close-summary-rules]").forEach((button) => button.addEventListener("click", () => dialog.close()));
  if (!dialog.open) dialog.showModal();
}

function labelSummaryCaseMarkup(item) {
  const issueId = String(item.issue_id || "");
  const scene = item.title || item.scenario || uiText("未提供场景描述", "No scene description");
  const status = ({ resolved: uiText("已形成结论", "Resolved"), pending: uiText("待形成结论", "Pending"), conflict: uiText("待裁决 / 需确认", "Needs adjudication / confirmation") })[item.label_state] || uiText("待形成结论", "Pending");
  const rationales = item.rationales || [];
  const tags = (item.tags || []).map((key) => `<span class="analysis-chip tag-chip">${escapeHtml(tagLabel(key))}</span>`).join("");
  const evidence = (item.evidence_gaps || []).map((key) => `<span class="analysis-chip evidence-chip">${escapeHtml(evidenceLabel(key))}</span>`).join("");
  const detailUrl = labelSummaryCaseUrl({ issue: issueId });
  const primary = item.label_state === "resolved" ? item.adjudication || null : null;
  const currentStatus = item.decision?.stale ? uiText("裁决需确认", "Decision needs confirmation") : primary ? uiText("已裁决", "Adjudicated") : status;
  const statusKind = item.decision?.stale ? "stale" : primary ? "adjudicated" : item.label_state;
  const statusTitle = primary?.kind === "task" ? uiText("任务内裁决", "Task decision") : primary?.kind === "issue" ? uiText("Issue 裁决", "Issue decision") : currentStatus;
  const resolved = item.label_state === "resolved" && LABELS.includes(item.expected_output);
  const update = item.gt_update;
  const updateCopy = ({ different: uiText("结论与 GT 不同", "Result differs from GT"), missing_gt: uiText("当前 GT 未设置", "Current GT is missing"), conflict: uiText("标注来源存在冲突", "Conflicting label sources"), stale: uiText("裁决需重新确认", "Decision needs reconfirmation"), pending: uiText("标注尚未齐备", "Incomplete label submissions") })[update?.reason] || "";
  const resultTitle = labelSummaryFilters.gtUpdate === "ready" ? uiText("建议 GT", "Suggested GT") : uiText("期望输出", "Expected result");
  const comparison = resolved && LABELS.includes(item.gt_label)
    ? `<span class="label-summary-gt-relation ${item.gt_label === item.expected_output ? "is-match" : "is-different"}">${item.gt_label === item.expected_output ? uiText("一致", "Matches") : uiText("与 GT 不一致", "Differs from GT")}</span>` : "";
  const resultLabels = `<div class="label-summary-result-line"><span class="label-summary-final-label"><span>${resultTitle}</span>${resolved ? labelBadge(item.expected_output) : `<span class="muted">${uiText("待确定", "Undetermined")}</span>`}</span></div><div class="label-summary-result-line"><span class="label-summary-gt-line">${uiText("当前 GT", "Current GT")}：${escapeHtml(item.gt_label || uiText("未设置", "Not set"))}${labelSummaryFilters.gtUpdate ? "" : comparison}</span><span class="label-summary-status" data-state="${escapeHtml(statusKind || "pending")}" title="${escapeHtml(statusTitle)}">${escapeHtml(currentStatus)}</span>${item.is_excluded ? `<span class="label-summary-excluded">${uiText("已排除", "Excluded")}</span>` : ""}</div>${update ? `<div class="label-summary-gt-update" data-state="${escapeHtml(update.state)}">${escapeHtml(updateCopy)}</div>` : ""}`;
  const originalVotes = primary && (item.original_votes || []).length ? `<details class="label-summary-original-votes"><summary>${item.original_conflict ? uiText("原始冲突 · 查看标注意见", "Original conflict · view votes") : uiText("原始标注意见", "Original votes")}</summary>${item.original_votes.map((vote) => `<p>${escapeHtml(vote.author)}：${escapeHtml(vote.expected_output || uiText("待补充", "Pending"))}${vote.rationale ? ` · ${escapeHtml(vote.rationale)}` : ""}</p>`).join("")}</details>` : "";
  const sceneMarkup = LABELS.includes(scene.trim()) ? "" : `<span title="${escapeHtml(scene)}">${escapeHtml(scene)}</span>`;
  const actionLabel = item.label_state === "conflict" || update?.state === "blocked" ? uiText("查看并确认", "Review sources") : uiText("Case 详情", "Case details");
  return `<article class="analysis-case-row label-summary-case-row"><div class="analysis-case-identity"><a class="analysis-issue-link" href="${escapeHtml(detailUrl)}">${escapeHtml(issueId)}</a>${sceneMarkup}</div><div class="analysis-case-labels">${resultLabels}</div><div class="analysis-case-reason"><strong class="${rationales.length ? "" : "reason-empty"}">${escapeHtml(rationales[0] || uiText("未填写标注依据", "No label rationale"))}</strong>${rationales.slice(1).map((reason) => `<p>${escapeHtml(reason)}</p>`).join("")}<div class="analysis-chip-list">${tags}${evidence}</div>${originalVotes}</div><div class="analysis-case-meta"><div class="label-summary-source-line">${labelSummarySourceMarkup(item)}</div>${resolved ? "" : `<span>${escapeHtml((item.authors || []).join("、") || uiText("未记录标注人", "No labeler recorded"))}</span>`}<span>${escapeHtml(uiText(`${Number(item.source_count || 0)} 个来源`, `${Number(item.source_count || 0)} ${Number(item.source_count || 0) === 1 ? "source" : "sources"}`))}${item.created_at ? ` · ${escapeHtml(formatTime(item.created_at))}` : ""}</span><span class="analysis-case-actions"><a class="text-link" href="${escapeHtml(detailUrl)}">${actionLabel}</a></span></div></article>`;
}

function renderLabelingSummary(data) {
  const root = $("#labelSummaryContent");
  const comparable = (data.pairs || []).reduce((sum, row) => sum + Number(row.count || 0), 0);
  const matches = (data.pairs || []).filter((row) => row.gt === row.label).reduce((sum, row) => sum + Number(row.count || 0), 0);
  const page = Number(data.page || 1);
  const pageCount = Math.max(1, Number(data.page_count || 0));
  root.classList.toggle("is-gt-queue", Boolean(labelSummaryFilters.gtUpdate));
  root.innerHTML = `${labelSummaryGtViewsMarkup(data)}${labelSummaryFilters.gtUpdate ? "" : `<nav class="mobile-summary-tools"><button class="button button-quiet" type="button" data-mobile-scroll-target="labelSummaryCaseList">${uiText("查看标注明细", "Go to annotations")}</button><button class="button button-quiet" type="button" data-mobile-disclosure="labelSummaryClusterPanels" aria-controls="labelSummaryClusterPanels" aria-expanded="false">${uiText("场景与标签图表", "Tag charts")}</button></nav><section class="analysis-summary-grid" aria-label="Labeling overview"><article class="analysis-stat-card"><span>问题标注</span><strong>${Number(data.annotated || 0)}</strong><small>当前范围 ${Number(data.total || 0)} 个 Case</small></article><article class="analysis-stat-card"><span>已填写依据</span><strong>${Number(data.reason_count || 0)}</strong><small>未填写 ${Number(data.empty_reason_count || 0)}</small></article><button class="analysis-stat-card label-summary-adjudicated" id="labelSummaryAdjudicated" type="button" aria-pressed="${labelSummaryFilters.cluster === "adjudicated"}"><span>已裁决 Case</span><strong>${Number(data.adjudicated_count || 0)}</strong><small>${labelSummaryFilters.cluster === "adjudicated" ? "正在筛选 · 点击取消" : "查看裁决记录"}</small></button></section>
    <section class="analysis-decision-grid" aria-label="Label state and GT comparison"><section class="page-card analysis-review-status-card"><div class="section-heading analysis-review-status-heading"><div><h3>标注状态</h3></div><small>${Number(data.annotated || 0)} 个已提交 Case</small></div><div class="analysis-review-status-chart" id="labelSummaryStatusChart">${labelSummaryStatusMarkup(data)}</div></section><section class="page-card analysis-confusion-card"><div class="section-heading analysis-confusion-heading"><div><h3>GT × 标注结果混淆矩阵</h3></div><small>可比较 ${comparable} · 一致 ${matches}</small></div><div class="analysis-confusion-wrap" id="labelSummaryConfusionMatrix">${labelSummaryMatrixMarkup(data)}</div></section></section>
    <section class="analysis-cluster-grid" id="labelSummaryClusterPanels" aria-label="Structured labeling clusters">${labelSummaryClusterPanels(data)}</section>`}
    <section class="page-card analysis-case-card"><div class="section-heading label-summary-detail-heading"><h3>${labelSummaryFilters.gtUpdate ? labelSummaryViewTitle() : uiText("标注依据明细", "Label rationales")}</h3><div class="label-summary-detail-actions"><button class="text-link label-summary-rules-button" id="labelSummaryRulesButton" type="button" aria-haspopup="dialog"><span aria-hidden="true">ⓘ</span> ${uiText("期望输出规则", "Result rules")}</button><small>${escapeHtml(uiText(`共 ${Number(data.annotated || 0)} 个 Case · 当前页 ${(data.items || []).length} 个`, `${Number(data.annotated || 0)} ${Number(data.annotated || 0) === 1 ? "Case" : "Cases"} · ${(data.items || []).length} on this page`))}</small></div></div><div class="analysis-case-list" id="labelSummaryCaseList">${(data.items || []).length ? data.items.map(labelSummaryCaseMarkup).join("") : `<div class="analysis-empty">${labelSummaryFilters.gtUpdate === "ready" ? uiText("当前筛选下没有待更新的 GT", "No GT updates match these filters") : labelSummaryFilters.gtUpdate === "blocked" ? uiText("当前筛选下没有需要确认的 Issue", "No Issues need attention under these filters") : uiText("当前范围暂无标注提交", "No annotations in this scope")}</div>`}</div><nav class="case-pagination gallery-pagination label-summary-pagination" aria-label="${escapeHtml(uiText("标注明细分页", "Annotation pagination"))}"><div class="case-pagination-main"><button class="button button-quiet" id="labelSummaryPrevious" type="button" ${page <= 1 ? "disabled" : ""}>${uiText("上一页", "Previous")}</button><span id="labelSummaryPageState">${page} / ${pageCount}</span><button class="button button-quiet" id="labelSummaryNext" type="button" ${page >= pageCount ? "disabled" : ""}>${uiText("下一页", "Next")}</button><span class="page-jump-control"><label for="labelSummaryPageJump">${uiText("跳至", "Go to")}</label><input id="labelSummaryPageJump" type="number" min="1" max="${pageCount}" value="${page}" inputmode="numeric" ${pageCount <= 1 ? "disabled" : ""}/><span>${uiText("页", "page")}</span><button class="button button-quiet" id="labelSummaryPageJumpButton" type="button" ${pageCount <= 1 ? "disabled" : ""}>${uiText("跳转", "Go")}</button></span></div><label class="case-page-size" for="labelSummaryPageSize"><span>${uiText("每页", "Per page")}</span><select id="labelSummaryPageSize"><option value="10">10</option><option value="20">20</option><option value="50">50</option><option value="100">100</option></select><span>${uiText("条", "items")}</span></label></nav></section>`;
  root.querySelectorAll("[data-gt-update-view]").forEach((button) => button.addEventListener("click", () => {
    setLabelSummaryView(button.dataset.gtUpdateView);
    loadLabelingSummary().catch((error) => showToast(error.message, true));
  }));
  syncLabelSummaryNavigation();
  $("#labelSummaryRulesButton")?.addEventListener("click", showLabelSummaryRules);
  $("#labelSummaryAdjudicated")?.addEventListener("click", () => {
    labelSummaryFilters.cluster = labelSummaryFilters.cluster === "adjudicated" ? "" : "adjudicated";
    labelSummaryPage = 1;
    loadLabelingSummary().catch((error) => showToast(error.message, true));
  });
  $("#labelSummaryPageSize").value = String(Number(data.page_size || labelSummaryPageSize));
  enhanceNativeUiSelect($("#labelSummaryPageSize"));
  if (!labelSummaryFilters.gtUpdate) {
    bindAnalysisReviewStatusHover($("#labelSummaryStatusChart"));
    bindAnalysisConfusionHover($("#labelSummaryConfusionMatrix")?.querySelector(".analysis-confusion-table"));
    bindAnalysisPieHover($("#labelSummaryClusterPanels"));
    clearAnalysisPieEnterAnimations($("#labelSummaryClusterPanels"));
  }
  $("#labelSummaryPrevious")?.addEventListener("click", () => { labelSummaryPage = Math.max(1, page - 1); loadLabelingSummary().catch((error) => showToast(error.message, true)); });
  $("#labelSummaryNext")?.addEventListener("click", () => { labelSummaryPage = Math.min(pageCount, page + 1); loadLabelingSummary().catch((error) => showToast(error.message, true)); });
  $("#labelSummaryPageJumpButton")?.addEventListener("click", () => { labelSummaryPage = Math.max(1, Math.min(pageCount, Number($("#labelSummaryPageJump")?.value || 1))); loadLabelingSummary().catch((error) => showToast(error.message, true)); });
  $("#labelSummaryPageJump")?.addEventListener("keydown", (event) => { if (event.key === "Enter") $("#labelSummaryPageJumpButton")?.click(); });
  $("#labelSummaryPageSize")?.addEventListener("change", (event) => { labelSummaryPageSize = Number(event.target.value || 20); labelSummaryPage = 1; loadLabelingSummary().catch((error) => showToast(error.message, true)); });
}
async function loadLabelingSummary() {
  if (state.activePage !== "labeling-summary") return;
  const pageContext = capturePageContext();
  restoreLabelSummaryRoute();
  const seq = ++labelSummaryRequest;
  const root = $("#labelSummaryContent");
  if (!root) return;
  labelSummaryData = null;
  root.innerHTML = '<div class="page-card campaign-analysis-empty"><span class="ui-lang-zh">正在汇总标注…</span><span class="ui-lang-en">Loading annotations…</span></div>';
  try {
    const baselines = selectedBaselineQueryValue();
    const tasks = await api(`/api/labeling/tasks?include_combined=true&baselines=${encodeURIComponent(baselines)}`);
    if (seq !== labelSummaryRequest || !isPageContextCurrent(pageContext)) return;
    labelSummaryTasks = tasks.items || [];
    if (!(tasks.items || []).some((task) => task.id === labelSummaryFilters.taskId)) {
      labelSummaryFilters.taskId = "";
    }
    const params = new URLSearchParams({
      baselines,
      task_id: labelSummaryFilters.taskId,
      q: labelSummaryFilters.search,
      issue_ids: labelSummaryFilters.issueIds.join(","),
      status: joinFilterList(labelSummaryFilters.status),
      author: joinFilterList(labelSummaryFilters.author),
      assignee: joinFilterList(labelSummaryFilters.assignee),
      exclusion: joinFilterList(labelSummaryFilters.exclusion),
      label: joinFilterList(labelSummaryFilters.label),
      gt: joinFilterList(labelSummaryFilters.gt),
      comment_state: joinFilterList(labelSummaryFilters.commentState),
      cluster: labelSummaryFilters.cluster,
      gt_update: labelSummaryFilters.gtUpdate,
      page: String(labelSummaryPage),
      page_size: String(labelSummaryPageSize),
    });
    const data = await api(`/api/labeling/summary?${params.toString()}`);
    if (seq !== labelSummaryRequest || !isPageContextCurrent(pageContext)) return;
    labelSummaryPage = Number(data.page || 1);
    labelSummaryPageSize = Number(data.page_size || 20);
    labelSummaryData = data;
    renderLabelSummaryFilters(tasks, data);
    renderLabelingSummary(data);
    persistLabelSummaryRoute();
  } catch(error) {
    if (seq === labelSummaryRequest && isPageContextCurrent(pageContext)) root.innerHTML = `<div class="page-card campaign-analysis-empty">${escapeHtml(error.message)}</div>`;
    throw error;
  }
}
document.getElementById("labelSummaryFilterForm")?.addEventListener("submit", (event) => {
  event.preventDefault();
  window.clearTimeout(labelSummarySearchTimer);
  labelSummaryFilters.search = $("#labelSummarySearch")?.value.trim() || "";
  labelSummaryPage = 1;
  loadLabelingSummary().catch((error) => showToast(error.message, true));
});
document.getElementById("labelSummarySearch")?.addEventListener("input", (event) => {
  labelSummaryFilters.search = event.target.value.trim();
  if (labelSummaryFilters.issueIds.length) {
    labelSummaryFilters.issueIds = [];
    if (typeof updateIssueQueryButton === "function") updateIssueQueryButton();
  }
  labelSummaryPage = 1;
  window.clearTimeout(labelSummarySearchTimer);
  const pageContext = capturePageContext();
  labelSummarySearchTimer = window.setTimeout(() => {
    if (!isPageContextCurrent(pageContext)) return;
    loadLabelingSummary().catch((error) => showToast(error.message, true));
  }, 280);
});
document.getElementById("labelSummaryTask")?.addEventListener("change", (event) => {
  labelSummaryFilters.taskId = event.target.value;
  labelSummaryFilters.author = [];
  labelSummaryFilters.assignee = [];
  labelSummaryFilters.cluster = "";
  labelSummaryPage = 1;
  loadLabelingSummary().catch((error) => showToast(error.message, true));
});
document.getElementById("labelSummaryReset")?.addEventListener("click", () => {
  const gtUpdate = labelSummaryFilters.gtUpdate;
  Object.assign(labelSummaryFilters, {
    search: "", issueIds: [], taskId: "", status: [], author: [], assignee: [],
    label: [], gt: [], commentState: [], exclusion: [], cluster: "", gtUpdate: "",
  });
  labelSummaryFilters.gtUpdate = gtUpdate;
  if (typeof updateIssueQueryButton === "function") updateIssueQueryButton();
  labelSummaryPage = 1;
  labelSummaryPageSize = 20;
  loadLabelingSummary().catch((error) => showToast(error.message, true));
});
document.getElementById("labelSummaryExportGt")?.addEventListener("click", () => {
  exportLabelingGtUpdate(labelSummaryFilterPayload(), document.getElementById("labelSummaryExportGt"))
    .catch((error) => showToast(error.message, true));
});
