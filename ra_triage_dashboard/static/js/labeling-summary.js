/* Labeling summary page: state, routes, filters, rendering and events.
 * Classic-script public functions retain their existing names for routing. */
let labelSummaryRequest = 0;
let labelSummaryPage = 1;
let labelSummaryPageSize = 20;
let labelSummaryRouteRestored = false;
let labelSummarySearchTimer = null;
const labelSummaryFilters = {
  search: "", issueIds: [], taskId: "", status: [], author: [], assignee: [],
  label: [], gt: [], commentState: [], exclusion: [], cluster: "",
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
    page: overrides.page ?? labelSummaryPage,
    pageSize: overrides.pageSize ?? labelSummaryPageSize,
    baselines: overrides.baselines ?? state.selectedBaselineIds,
  };
}

function restoreLabelSummaryRoute() {
  if (labelSummaryRouteRestored) return;
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
  labelSummaryPage = Math.max(1, Number(params.get("page") || 1));
  labelSummaryPageSize = CASE_PAGE_SIZES.includes(Number(params.get("page_size"))) ? Number(params.get("page_size")) : 20;
}

function persistLabelSummaryRoute() {
  window.history.replaceState(
    { ...(window.history.state || {}), page: "labeling-summary" },
    "",
    pageUrl("labeling-summary", labelSummaryRouteOptions()),
  );
}

function labelSummaryCaseUrl(filters = {}) {
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
  const taskOptions = [{ value: "", label: "全部标注（含历史迁移）" }, ...(tasks.items || []).map((task) => ({ value: task.id, label: task.name || "标注任务" }))];
  if (!taskOptions.some((item) => item.value === labelSummaryFilters.taskId)) labelSummaryFilters.taskId = "";
  const labelerOptions = (data.labelers || []).map((value) => ({ value, label: value }));
  const labelerValues = new Set(labelerOptions.map((item) => item.value));
  labelSummaryFilters.author = parseFilterList(labelSummaryFilters.author).filter((value) => labelerValues.has(value));
  const assigneeOptions = (data.assignees || []).map((value) => ({ value, label: value }));
  const assigneeValues = new Set(assigneeOptions.map((item) => item.value));
  labelSummaryFilters.assignee = parseFilterList(labelSummaryFilters.assignee).filter((value) => assigneeValues.has(value));
  renderLabelSummaryPicker("#labelSummaryTaskPicker", taskOptions, labelSummaryFilters.taskId);
  renderLabelSummaryMultiPicker("#labelSummaryStatusPicker", [
    { value: "resolved", label: "已形成结论" },
    { value: "pending", label: "待形成结论" }, { value: "conflict", label: "待裁决 / 需确认" },
  ], labelSummaryFilters.status, "status");
  renderLabelSummaryMultiPicker("#labelSummaryAuthorPicker", labelerOptions, labelSummaryFilters.author, "author");
  renderLabelSummaryMultiPicker("#labelSummaryAssigneePicker", assigneeOptions, labelSummaryFilters.assignee, "assignee");
  renderLabelSummaryMultiPicker("#labelSummaryLabelPicker", LABELS.map((value) => ({ value, label: value })), labelSummaryFilters.label, "label");
  renderLabelSummaryMultiPicker("#labelSummaryGtPicker", LABELS.map((value) => ({ value, label: value })), labelSummaryFilters.gt, "gt");
  renderLabelSummaryMultiPicker("#labelSummaryDiscussionPicker", [
    { value: "with", label: "有讨论" }, { value: "without", label: "无讨论" },
  ], labelSummaryFilters.commentState, "commentState");
  renderLabelSummaryMultiPicker("#labelSummaryExclusionPicker", [
    { value: "active", label: "未排除" },
    { value: "excluded", label: "已排除" },
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
  };
}

function labelSummaryStatusItems(data) {
  const counts = data.submitted_states || {};
  return [
    { key: "resolved", cssKey: "completed", label: "已形成结论", count: Number(counts.resolved || 0), description: "多来源聚合后已形成唯一结论" },
    { key: "pending", cssKey: "pending", label: "待形成结论", count: Number(counts.pending || 0), description: "已有提交，但还没有形成唯一结论" },
    { key: "conflict", cssKey: "blocked_by_label", label: "待裁决 / 需确认", count: Number(counts.conflict || 0), description: "当前来源之间存在冲突或 Issue 裁决已过期" },
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
  const names = { issue_adjudication: "Issue 裁决", task_adjudication: "任务内裁决", source_consensus: "多来源一致", consensus: "多人一致", single: "单人标注", unresolved: "尚未形成有效结论", unknown: "来源未记录" };
  const label = names[source.kind] || names.unknown;
  const authors = (source.authors || []).join("、");
  const containsDecision = source.kind === "source_consensus" && sources.some((value) => value.kind === "task_adjudication");
  const detail = sources.map((value) => `${names[value.kind] || value.kind} · ${value.task_id ? `任务 ${value.task_id}` : "任务外标注"}${value.source_run_id ? ` · Run ${value.source_run_id}` : ""} · ${(value.authors || []).join("、")}${value.revision_ids?.length ? ` · 记录 ${value.revision_ids.join("、")}` : ""}`).join("\n");
  const text = `${label}${containsDecision ? "（含任务裁决）" : ""}${source.kind === "source_consensus" ? ` · ${sources.length} 个来源` : ""}${authors ? ` · ${authors}` : ""}`;
  const trace = detail || (source.decision_id ? `Issue 裁决 #${source.decision_id} · ${authors}` : "");
  return trace ? `<details class="label-summary-source"><summary>来源：${escapeHtml(text)}</summary><div class="label-summary-source-trace">${trace.split("\n").map((line) => `<p>${escapeHtml(line)}</p>`).join("")}</div></details>` : `<span class="label-summary-source">来源：${escapeHtml(text)}</span>`;
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
  dialog.innerHTML = `<div class="dialog-card"><div class="dialog-heading"><h2 id="labelSummaryRulesTitle">期望输出规则</h2><button class="icon-button" type="button" data-close-summary-rules aria-label="关闭">×</button></div>
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
  const scene = item.title || item.scenario || "未记录场景";
  const status = ({ resolved: "已形成结论", pending: "待形成结论", conflict: "待裁决 / 需确认" })[item.label_state] || "待形成结论";
  const rationales = item.rationales || [];
  const tags = (item.tags || []).map((key) => `<span class="analysis-chip tag-chip">${escapeHtml(tagLabel(key))}</span>`).join("");
  const evidence = (item.evidence_gaps || []).map((key) => `<span class="analysis-chip evidence-chip">${escapeHtml(evidenceLabel(key))}</span>`).join("");
  const detailUrl = labelSummaryCaseUrl({ issue: issueId });
  const primary = item.label_state === "resolved" ? item.adjudication || null : null;
  const currentStatus = item.decision?.stale ? "裁决需确认" : primary ? "已裁决" : status;
  const statusKind = item.decision?.stale ? "stale" : primary ? "adjudicated" : item.label_state;
  const statusTitle = primary?.kind === "task" ? "任务内裁决" : primary?.kind === "issue" ? "Issue 裁决" : currentStatus;
  const resolved = item.label_state === "resolved" && LABELS.includes(item.expected_output);
  const comparison = resolved && LABELS.includes(item.gt_label)
    ? `<span class="label-summary-gt-relation ${item.gt_label === item.expected_output ? "is-match" : "is-different"}">${item.gt_label === item.expected_output ? "一致" : "待更新"}</span>` : "";
  const resultLabels = `<div class="label-summary-result-line"><span class="label-summary-final-label"><span>期望输出</span>${resolved ? labelBadge(item.expected_output) : '<span class="muted">待确定</span>'}</span></div><div class="label-summary-result-line"><span class="label-summary-gt-line">GT：${escapeHtml(item.gt_label || "未设置")}${comparison}</span><span class="label-summary-status" data-state="${escapeHtml(statusKind || "pending")}" title="${escapeHtml(statusTitle)}">${escapeHtml(currentStatus)}</span>${item.is_excluded ? '<span class="label-summary-excluded">已排除</span>' : ""}</div>`;
  const originalVotes = primary && (item.original_votes || []).length ? `<details class="label-summary-original-votes"><summary>${item.original_conflict ? "原始冲突 · 查看标注意见" : "原始标注意见"}</summary>${item.original_votes.map((vote) => `<p>${escapeHtml(vote.author)}：${escapeHtml(vote.expected_output || "待补充")}${vote.rationale ? ` · ${escapeHtml(vote.rationale)}` : ""}</p>`).join("")}</details>` : "";
  const sceneMarkup = LABELS.includes(scene.trim()) ? "" : `<span title="${escapeHtml(scene)}">${escapeHtml(scene)}</span>`;
  const actionLabel = item.label_state === "conflict" ? "进入裁决" : "Case 详情";
  return `<article class="analysis-case-row label-summary-case-row"><div class="analysis-case-identity"><a class="analysis-issue-link" href="${escapeHtml(detailUrl)}">${escapeHtml(issueId)}</a>${sceneMarkup}</div><div class="analysis-case-labels">${resultLabels}</div><div class="analysis-case-reason"><strong class="${rationales.length ? "" : "reason-empty"}">${escapeHtml(rationales[0] || "未填写标注依据")}</strong>${rationales.slice(1).map((reason) => `<p>${escapeHtml(reason)}</p>`).join("")}<div class="analysis-chip-list">${tags}${evidence}</div>${originalVotes}</div><div class="analysis-case-meta"><div class="label-summary-source-line">${labelSummarySourceMarkup(item)}</div>${resolved ? "" : `<span>${escapeHtml((item.authors || []).join("、") || "未记录标注人")}</span>`}<span>${Number(item.source_count || 0)} 个来源${item.created_at ? ` · ${escapeHtml(formatTime(item.created_at))}` : ""}</span><span class="analysis-case-actions"><a class="text-link" href="${escapeHtml(detailUrl)}">${actionLabel}</a></span></div></article>`;
}

function renderLabelingSummary(data) {
  const root = $("#labelSummaryContent");
  const comparable = (data.pairs || []).reduce((sum, row) => sum + Number(row.count || 0), 0);
  const matches = (data.pairs || []).filter((row) => row.gt === row.label).reduce((sum, row) => sum + Number(row.count || 0), 0);
  const page = Number(data.page || 1);
  const pageCount = Math.max(1, Number(data.page_count || 0));
  root.innerHTML = `<nav class="mobile-summary-tools"><button class="button button-quiet" type="button" data-mobile-scroll-target="labelSummaryCaseList">${uiText("查看标注明细", "Go to annotations")}</button><button class="button button-quiet" type="button" data-mobile-disclosure="labelSummaryClusterPanels" aria-controls="labelSummaryClusterPanels" aria-expanded="false">${uiText("场景与标签图表", "Tag charts")}</button></nav><section class="analysis-summary-grid" aria-label="Labeling overview"><article class="analysis-stat-card"><span>问题标注</span><strong>${Number(data.annotated || 0)}</strong><small>当前范围 ${Number(data.total || 0)} 个 Case</small></article><article class="analysis-stat-card"><span>已填写依据</span><strong>${Number(data.reason_count || 0)}</strong><small>未填写 ${Number(data.empty_reason_count || 0)}</small></article><button class="analysis-stat-card label-summary-adjudicated" id="labelSummaryAdjudicated" type="button" aria-pressed="${labelSummaryFilters.cluster === "adjudicated"}"><span>已裁决 Case</span><strong>${Number(data.adjudicated_count || 0)}</strong><small>${labelSummaryFilters.cluster === "adjudicated" ? "正在筛选 · 点击取消" : "查看裁决记录"}</small></button></section>
    <section class="analysis-decision-grid" aria-label="Label state and GT comparison"><section class="page-card analysis-review-status-card"><div class="section-heading analysis-review-status-heading"><div><h3>标注状态</h3></div><small>${Number(data.annotated || 0)} 个已提交 Case</small></div><div class="analysis-review-status-chart" id="labelSummaryStatusChart">${labelSummaryStatusMarkup(data)}</div></section><section class="page-card analysis-confusion-card"><div class="section-heading analysis-confusion-heading"><div><h3>GT × 标注结果混淆矩阵</h3></div><small>可比较 ${comparable} · 一致 ${matches}</small></div><div class="analysis-confusion-wrap" id="labelSummaryConfusionMatrix">${labelSummaryMatrixMarkup(data)}</div></section></section>
    <section class="analysis-cluster-grid" id="labelSummaryClusterPanels" aria-label="Structured labeling clusters">${labelSummaryClusterPanels(data)}</section>
    <section class="page-card analysis-case-card"><div class="section-heading label-summary-detail-heading"><h3>标注依据明细</h3><div class="label-summary-detail-actions"><button class="text-link label-summary-rules-button" id="labelSummaryRulesButton" type="button" aria-haspopup="dialog"><span aria-hidden="true">ⓘ</span> 期望输出规则</button><small>共 ${Number(data.annotated || 0)} 个 Case · 当前页 ${(data.items || []).length} 个</small></div></div><div class="analysis-case-list" id="labelSummaryCaseList">${(data.items || []).length ? data.items.map(labelSummaryCaseMarkup).join("") : '<div class="analysis-empty">当前范围暂无标注提交</div>'}</div><nav class="case-pagination gallery-pagination label-summary-pagination" aria-label="标注依据明细分页"><div class="case-pagination-main"><button class="button button-quiet" id="labelSummaryPrevious" type="button" ${page <= 1 ? "disabled" : ""}>上一页</button><span id="labelSummaryPageState">${page} / ${pageCount}</span><button class="button button-quiet" id="labelSummaryNext" type="button" ${page >= pageCount ? "disabled" : ""}>下一页</button><span class="page-jump-control"><label for="labelSummaryPageJump">跳至</label><input id="labelSummaryPageJump" type="number" min="1" max="${pageCount}" value="${page}" inputmode="numeric" ${pageCount <= 1 ? "disabled" : ""}/><span>页</span><button class="button button-quiet" id="labelSummaryPageJumpButton" type="button" ${pageCount <= 1 ? "disabled" : ""}>跳转</button></span></div><label class="case-page-size" for="labelSummaryPageSize"><span>每页</span><select id="labelSummaryPageSize"><option value="10">10</option><option value="20">20</option><option value="50">50</option><option value="100">100</option></select><span>条</span></label></nav></section>`;
  $("#labelSummaryRulesButton")?.addEventListener("click", showLabelSummaryRules);
  $("#labelSummaryAdjudicated")?.addEventListener("click", () => {
    labelSummaryFilters.cluster = labelSummaryFilters.cluster === "adjudicated" ? "" : "adjudicated";
    labelSummaryPage = 1;
    loadLabelingSummary().catch((error) => showToast(error.message, true));
  });
  $("#labelSummaryPageSize").value = String(Number(data.page_size || labelSummaryPageSize));
  bindAnalysisReviewStatusHover($("#labelSummaryStatusChart"));
  bindAnalysisConfusionHover($("#labelSummaryConfusionMatrix")?.querySelector(".analysis-confusion-table"));
  bindAnalysisPieHover($("#labelSummaryClusterPanels"));
  clearAnalysisPieEnterAnimations($("#labelSummaryClusterPanels"));
  $("#labelSummaryPrevious")?.addEventListener("click", () => { labelSummaryPage = Math.max(1, page - 1); loadLabelingSummary().catch((error) => showToast(error.message, true)); });
  $("#labelSummaryNext")?.addEventListener("click", () => { labelSummaryPage = Math.min(pageCount, page + 1); loadLabelingSummary().catch((error) => showToast(error.message, true)); });
  $("#labelSummaryPageJumpButton")?.addEventListener("click", () => { labelSummaryPage = Math.max(1, Math.min(pageCount, Number($("#labelSummaryPageJump")?.value || 1))); loadLabelingSummary().catch((error) => showToast(error.message, true)); });
  $("#labelSummaryPageJump")?.addEventListener("keydown", (event) => { if (event.key === "Enter") $("#labelSummaryPageJumpButton")?.click(); });
  $("#labelSummaryPageSize")?.addEventListener("change", (event) => { labelSummaryPageSize = Number(event.target.value || 20); labelSummaryPage = 1; loadLabelingSummary().catch((error) => showToast(error.message, true)); });
}
async function loadLabelingSummary() {
  restoreLabelSummaryRoute();
  const seq = ++labelSummaryRequest;
  const root = $("#labelSummaryContent");
  if (!root) return;
  root.innerHTML = '<div class="page-card campaign-analysis-empty">正在汇总标注…</div>';
  try {
    const baselines = selectedBaselineQueryValue();
    const tasks = await api(`/api/labeling/tasks?baselines=${encodeURIComponent(baselines)}`);
    if (seq !== labelSummaryRequest || state.activePage !== "labeling-summary") return;
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
      page: String(labelSummaryPage),
      page_size: String(labelSummaryPageSize),
    });
    const data = await api(`/api/labeling/summary?${params.toString()}`);
    if (seq !== labelSummaryRequest || state.activePage !== "labeling-summary") return;
    labelSummaryPage = Number(data.page || 1);
    labelSummaryPageSize = Number(data.page_size || 20);
    renderLabelSummaryFilters(tasks, data);
    renderLabelingSummary(data);
    persistLabelSummaryRoute();
  } catch(error) {
    if (seq === labelSummaryRequest) root.innerHTML = `<div class="page-card campaign-analysis-empty">${escapeHtml(error.message)}</div>`;
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
  labelSummarySearchTimer = window.setTimeout(() => loadLabelingSummary().catch((error) => showToast(error.message, true)), 280);
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
  Object.assign(labelSummaryFilters, {
    search: "", issueIds: [], taskId: "", status: [], author: [], assignee: [],
    label: [], gt: [], commentState: [], exclusion: [], cluster: "",
  });
  if (typeof updateIssueQueryButton === "function") updateIssueQueryButton();
  labelSummaryPage = 1;
  labelSummaryPageSize = 20;
  loadLabelingSummary().catch((error) => showToast(error.message, true));
});
document.getElementById("labelSummaryExportGt")?.addEventListener("click", () => {
  exportLabelingGtUpdate(labelSummaryFilterPayload(), document.getElementById("labelSummaryExportGt"))
    .catch((error) => showToast(error.message, true));
});
