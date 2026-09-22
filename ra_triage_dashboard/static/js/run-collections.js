/* Multi-run evaluation and frozen multi-Run evaluation workspace. */

const runCollectionUi = {
  collections: [],
  detail: null,
  selectedRevision: 0,
  draftMembers: [],
  evaluation: null,
  page: 1,
  search: "",
  searchTimer: null,
  restoring: false,
};

function runCollectionCanWrite() {
  return Boolean(state.session?.is_admin && state.session?.verified);
}

function ensureRunCollectionsDedicatedPage(targetPage = state.activePage) {
  const workbench = document.getElementById("runCollectionsWorkbench");
  const host = document.getElementById("runCollectionsDedicatedHost");
  const pairwiseHost = document.getElementById("runCollectionPairwiseHost");
  const pairwiseDetails = document.getElementById("runCollectionPairwiseDetails");
  const comparison = document.getElementById("runComparisonPage");
  if (!workbench || !comparison) return;
  if (targetPage === "run-collections" && host) {
    host.appendChild(workbench);
    workbench.classList.remove("is-pairwise-manager");
  } else if (targetPage === "comparison") {
    if (pairwiseHost) pairwiseHost.appendChild(workbench);
    else {
      const anchor = document.getElementById("comparisonEmptyState");
      comparison.insertBefore(workbench, anchor || null);
    }
    if (pairwiseDetails) pairwiseDetails.open = false;
    workbench.classList.add("is-pairwise-manager");
  }
}

function applyRunCollectionReadOnlyGating() {
  const canWrite = runCollectionCanWrite();
  const note = document.getElementById("runCollectionReadonlyNote");
  if (note) note.hidden = canWrite;
  const writableIds = [
    "comparisonSaveCollectionButton",
    "runCollectionRenameButton",
    "runCollectionAppendRevisionButton",
    "runCollectionAddRun",
    "runCollectionAddRunButton",
    "runCollectionCreateButton",
    "runCollectionEvaluateButton",
    "runCollectionCreateLabelingCampaign",
    "runCollectionCreateModelReviewGroup",
    "runCollectionName",
    "runCollectionDescription",
    "runCollectionCreateName",
    "runCollectionReferenceType",
    "runCollectionReferenceId",
    "runCollectionComparisonReference",
    "runCollectionWorksetId",
    "runCollectionSelectionSourceRun",
    "runCollectionTaskAssignees",
  ];
  writableIds.forEach((id) => {
    const element = document.getElementById(id);
    if (!element) return;
    element.disabled = !canWrite;
    if (id.endsWith("Button") || element.tagName === "BUTTON") element.hidden = !canWrite;
  });
  document.getElementById("runCollectionCreateDetails")?.toggleAttribute("hidden", !canWrite);
  document.getElementById("runCollectionAdminOnly")?.toggleAttribute("hidden", !canWrite);
}

function runCollectionText(zh, en) {
  return uiText(zh, en);
}

function runCollectionRevision() {
  return (runCollectionUi.detail?.history || []).find(
    (item) => Number(item.revision) === Number(runCollectionUi.selectedRevision)
  ) || null;
}

function runCollectionMemberName(member) {
  const run = member?.run || (state.modelRuns || []).find(
    (item) => String(item.id) === String(member?.run_id)
  ) || {};
  return String(run.name || run.source_name || member?.run_id || "Unavailable Run");
}

function runCollectionSetStatus(message, error = false) {
  const target = $("#runCollectionStatus");
  if (!target) return;
  target.textContent = String(message || "");
  target.classList.toggle("error", Boolean(error));
}

function runCollectionApiHeaders(idempotencyKey = "") {
  const headers = { "Content-Type": "application/json" };
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
  return headers;
}

function runCollectionUpdateUrl(mode = "replace") {
  if (runCollectionUi.restoring) return;
  const url = new URL(window.location.href);
  if (runCollectionUi.detail?.id) {
    url.searchParams.set("collection_id", runCollectionUi.detail.id);
    url.searchParams.set("collection", runCollectionUi.detail.id);
    url.searchParams.set("collection_revision", String(runCollectionUi.selectedRevision || runCollectionUi.detail.current_revision));
    url.searchParams.set("revision", String(runCollectionUi.selectedRevision || runCollectionUi.detail.current_revision));
  } else {
    url.searchParams.delete("collection_id");
    url.searchParams.delete("collection");
    url.searchParams.delete("collection_revision");
    url.searchParams.delete("revision");
  }
  if (runCollectionUi.evaluation?.id) {
    url.searchParams.set("evaluation_id", runCollectionUi.evaluation.id);
    url.searchParams.set("context", runCollectionUi.evaluation.id);
    url.searchParams.set("evaluation_page", String(runCollectionUi.page));
    url.searchParams.set("page", String(runCollectionUi.page));
    if (runCollectionUi.evaluation.comparison_reference_run_id) {
      url.searchParams.set("evaluation_reference_run_id", runCollectionUi.evaluation.comparison_reference_run_id);
      url.searchParams.set("reference_run", runCollectionUi.evaluation.comparison_reference_run_id);
    } else {
      url.searchParams.delete("evaluation_reference_run_id");
      url.searchParams.delete("reference_run");
    }
    if (runCollectionUi.search) {
      url.searchParams.set("evaluation_q", runCollectionUi.search);
      url.searchParams.set("q", runCollectionUi.search);
    } else {
      url.searchParams.delete("evaluation_q");
      url.searchParams.delete("q");
    }
  } else {
    url.searchParams.delete("evaluation_id");
    url.searchParams.delete("context");
    url.searchParams.delete("evaluation_page");
    url.searchParams.delete("page");
    url.searchParams.delete("evaluation_q");
    url.searchParams.delete("q");
  }
  window.history[mode === "push" ? "pushState" : "replaceState"](
    { ...(window.history.state || {}), page: state.activePage === "run-collections" ? "run-collections" : "comparison" },
    "",
    `${withBase(state.activePage === "run-collections" ? "/multi-run-evaluation" : "/run-comparison")}${url.search}${url.hash}`
  );
}

function runCollectionSelectedScopes() {
  const catalog = state.baselineCatalog || state.config?.baselines || [];
  const selected = new Set(normalizeBaselineIds(state.selectedBaselineIds));
  return catalog
    .filter((item) => selected.has(String(item?.id || "")))
    .map((item) => String(item.scope || "").trim())
    .filter(Boolean);
}

function renderRunCollectionLabelReferenceSet(scopes = [], values = {}) {
  const root = document.getElementById("runCollectionLabelReferenceSet");
  if (!root) return;
  const normalized = [...new Set((scopes || []).map(String).filter(Boolean))];
  const labelType = String(document.getElementById("runCollectionReferenceType")?.value || "gt");
  const multi = labelType === "label_result" && normalized.length > 1;
  root.hidden = !multi;
  if (!multi) {
    root.innerHTML = "";
    return;
  }
  root.innerHTML = normalized.map((scope) => `
    <label><span>${escapeHtml(scope)} Label snapshot</span><input data-label-scope="${escapeHtml(scope)}" value="${escapeHtml(values[scope] || "")}" placeholder="label-result-…" autocomplete="off"></label>
  `).join("");
}

function renderRunCollectionSelectors() {
  const collectionSelect = $("#runCollectionSelect");
  if (!collectionSelect) return;
  applyRunCollectionReadOnlyGating();
  renderRunCollectionLabelReferenceSet(runCollectionUi.evaluation?.workset?.baseline_scopes || runCollectionSelectedScopes(), {});
  const selectedCollectionId = String(runCollectionUi.detail?.id || "");
  collectionSelect.innerHTML = [
    `<option value="">${escapeHtml(runCollectionText("选择评测项目", "Select an evaluation project"))}</option>`,
    ...runCollectionUi.collections.map((item) =>
      `<option value="${escapeHtml(item.id)}" ${item.id === selectedCollectionId ? "selected" : ""}>${escapeHtml(item.name)} · r${Number(item.current_revision || 0)}</option>`
    ),
  ].join("");
  const revisionSelect = $("#runCollectionRevisionSelect");
  const history = runCollectionUi.detail?.history || [];
  if (revisionSelect) {
    revisionSelect.disabled = !history.length;
    revisionSelect.innerHTML = history.map((item) =>
      `<option value="${Number(item.revision)}" ${Number(item.revision) === Number(runCollectionUi.selectedRevision) ? "selected" : ""}>r${Number(item.revision)} · ${escapeHtml(String(item.content_sha256 || "").slice(0, 12))}${Number(item.revision) === Number(runCollectionUi.detail?.current_revision) ? " · current" : ""}</option>`
    ).join("");
  }
  const addRun = $("#runCollectionAddRun");
  const existing = new Set(runCollectionUi.draftMembers.map((item) => String(item.run_id)));
  const runs = (state.modelRuns || []).filter((item) => item?.id);
  if (addRun) {
    addRun.innerHTML = [
      `<option value="">${escapeHtml(runCollectionText("选择 Run", "Select a Run"))}</option>`,
      ...runs.filter((item) => !existing.has(String(item.id))).map((item) =>
        `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name || item.source_name || item.id)} · ${escapeHtml(String(item.id).slice(0, 8))}</option>`
      ),
    ].join("");
  }
  const referenceSelect = $("#runCollectionComparisonReference");
  if (referenceSelect) {
    const marked = runCollectionUi.draftMembers.find((item) => item.is_reference)?.run_id || "";
    const selected = referenceSelect.value || marked;
    referenceSelect.innerHTML = [
      `<option value="">${escapeHtml(runCollectionText("使用 Collection 参考标记", "Use Collection reference mark"))}</option>`,
      ...runCollectionUi.draftMembers.map((item) =>
        `<option value="${escapeHtml(item.run_id)}">${escapeHtml(runCollectionMemberName(item))}</option>`
      ),
    ].join("");
    if (runCollectionUi.draftMembers.some((item) => String(item.run_id) === String(selected))) {
      referenceSelect.value = selected;
    }
  }
  const selectionSource = $("#runCollectionSelectionSourceRun");
  if (selectionSource) {
    const selectedSource = selectionSource.value || runCollectionUi.evaluation?.selection_source_run_id || "";
    selectionSource.innerHTML = [
      `<option value="">${escapeHtml(runCollectionText("不按 Run 筛选", "Do not filter by a Run"))}</option>`,
      ...runCollectionUi.draftMembers.map((item) =>
        `<option value="${escapeHtml(item.run_id)}">${escapeHtml(runCollectionMemberName(item))}</option>`
      ),
    ].join("");
    if (runCollectionUi.draftMembers.some((item) => String(item.run_id) === String(selectedSource))) {
      selectionSource.value = selectedSource;
    }
  }
}

function renderRunCollectionMembers() {
  const list = $("#runCollectionMembers");
  if (!list) return;
  const canWrite = runCollectionCanWrite();
  list.innerHTML = runCollectionUi.draftMembers.map((member, index) => `
    <li class="run-collection-member ${member.available_now === false ? "is-unavailable" : ""}" data-member-index="${index}">
      <span class="run-collection-member-order">${index + 1}</span>
      <span class="run-collection-member-info"><strong>${escapeHtml(runCollectionMemberName(member))}</strong><small>${escapeHtml(member.run_id)}${member.role ? ` · ${escapeHtml(member.role)}` : ""}${member.available_now === false ? ` · ${escapeHtml(runCollectionText("当前不可用", "Unavailable now"))}` : ""}</small></span>
      ${member.is_reference ? `<span class="run-collection-reference-badge">${escapeHtml(runCollectionText("参考 Run", "reference"))}</span>` : ""}
      ${canWrite ? `<span class="run-collection-member-actions"><button class="button button-quiet" type="button" data-member-move="-1" aria-label="Move up" ${index === 0 ? "disabled" : ""}>↑</button><button class="button button-quiet" type="button" data-member-move="1" aria-label="Move down" ${index === runCollectionUi.draftMembers.length - 1 ? "disabled" : ""}>↓</button><button class="button button-quiet" type="button" data-member-reference="true">${escapeHtml(member.is_reference ? runCollectionText("取消参考", "Unset reference") : runCollectionText("设为参考", "Set reference"))}</button><button class="button button-quiet" type="button" data-member-remove="true">×</button></span>` : ""}
    </li>
  `).join("");
  const revision = runCollectionRevision();
  const hash = $("#runCollectionMemberHash");
  if (hash) hash.textContent = revision ? `members ${String(revision.members_sha256 || "").slice(0, 16)}` : "";
  renderRunCollectionSelectors();
}

function renderRunCollectionDetail() {
  applyRunCollectionReadOnlyGating();
  const detail = runCollectionUi.detail;
  const name = $("#runCollectionName");
  const description = $("#runCollectionDescription");
  if (!detail) {
    runCollectionUi.draftMembers = [];
    if (name) name.value = "";
    if (description) description.value = "";
    const history = $("#runCollectionHistory");
    if (history) history.innerHTML = "";
    const audit = $("#runCollectionAudit");
    if (audit) audit.innerHTML = "";
    const evaluationHistory = $("#runCollectionEvaluationHistory");
    if (evaluationHistory) evaluationHistory.innerHTML = "";
    renderRunCollectionMembers();
    return;
  }
  if (name) name.value = detail.name || "";
  if (description) description.value = detail.description || "";
  const revision = runCollectionRevision() || detail.current;
  runCollectionUi.selectedRevision = Number(revision?.revision || detail.current_revision);
  runCollectionUi.draftMembers = (revision?.members || []).map((item) => ({ ...item }));
  const history = $("#runCollectionHistory");
  if (history) {
    history.innerHTML = (detail.history || []).map((item) => `
      <li><button class="button button-quiet" type="button" data-load-revision="${Number(item.revision)}">r${Number(item.revision)} · ${Number(item.members?.length || 0)} Runs · ${escapeHtml(String(item.content_sha256 || "").slice(0, 16))}</button><small>${escapeHtml(item.created_by || "")} · ${escapeHtml(item.created_at || "")}</small></li>
    `).join("");
  }
  const audit = $("#runCollectionAudit");
  if (audit) {
    audit.innerHTML = (detail.audit || []).map((item) => `
      <li><strong>${escapeHtml(item.action || "event")}</strong><small>r${Number(item.revision || 0)} · ${escapeHtml(item.actor || "")} (${escapeHtml(item.actor_source || "")}${item.actor_verified ? ", verified" : ", unverified"}) · ${escapeHtml(item.created_at || "")}</small>${item.context_id ? `<small>context ${escapeHtml(item.context_id)}</small>` : ""}</li>
    `).join("");
  }
  renderRunCollectionSelectors();
  renderRunCollectionMembers();
}

function renderRunCollectionEvaluation(payload) {
  const root = $("#runCollectionEvaluation");
  const provenance = $("#runCollectionProvenance");
  const metrics = $("#runCollectionMetrics");
  const head = $("#runCollectionTableHead");
  const body = $("#runCollectionTableBody");
  if (!root || !payload) {
    if (root) root.hidden = true;
    return;
  }
  applyRunCollectionReadOnlyGating();
  root.hidden = false;
  const referenceType = $("#runCollectionReferenceType");
  const referenceId = $("#runCollectionReferenceId");
  const comparisonReference = $("#runCollectionComparisonReference");
  const worksetId = $("#runCollectionWorksetId");
  const selectionSource = $("#runCollectionSelectionSourceRun");
  if (referenceType) referenceType.value = payload.reference?.type || "gt";
  if (referenceId) {
    referenceId.value = payload.reference?.id || "";
    referenceId.disabled = payload.reference?.type === "gt";
    referenceId.placeholder = payload.reference?.type === "label_result"
      ? "label-result-…" : "GT snapshot is selected by scope";
  }
  if (comparisonReference && payload.comparison_reference_run_id) {
    comparisonReference.value = payload.comparison_reference_run_id;
  }
  if (worksetId && payload.workset?.workset_id) worksetId.value = payload.workset.workset_id;
  if (selectionSource) selectionSource.value = payload.selection_source_run_id || "";
  renderRunCollectionLabelReferenceSet(
    payload.workset?.baseline_scopes || [],
    Object.fromEntries((payload.reference?.snapshot?.scope_snapshots || []).map((item) => [item.baseline_scope, item.id]))
  );
  const bias = payload.selection_bias_warning
    ? `<strong class="run-collection-bias-warning">${escapeHtml(payload.selection_bias_warning)}</strong>` : "";
  const scopeSnapshots = payload.reference?.snapshot?.scope_snapshots || [];
  const scopeProvenance = scopeSnapshots.map((item) =>
    `${escapeHtml(item.baseline_scope || "")}: ${escapeHtml(item.id || "")} · ${escapeHtml(String(item.content_sha256 || "").slice(0, 16))} · ${Number(item.member_count || 0)}`
  ).join(" | ");
  provenance.innerHTML = `
    <strong>${escapeHtml(runCollectionText("已冻结的评测快照", "Frozen evaluation snapshot"))} · ${escapeHtml(payload.id)}</strong>
    ${bias}
    <span>Case 范围 · ${Number(payload.summary?.workset_count || 0)} Issues · ${(payload.workset?.baseline_scopes || []).map(escapeHtml).join(", ")}</span>
    <details class="run-collection-technical-details"><summary>${escapeHtml(runCollectionText("版本与技术详情", "Version and technical details"))}</summary>
      <span>Project version r${Number(payload.collection_revision)} · ${escapeHtml(String(payload.collection_sha256 || ""))}</span>
      <span>Case range ${escapeHtml(String(payload.workset?.workset_id || ""))} · ${escapeHtml(String(payload.workset_sha256 || ""))}</span>
      <span>Frozen references ${scopeProvenance}</span>
      <span>${escapeHtml(payload.reference?.type || "")} ${escapeHtml(payload.reference?.id || "")} · ${escapeHtml(String(payload.reference?.sha256 || ""))}</span>
      <span>Policy ${escapeHtml(payload.scoring_policy_version || "")} · ${escapeHtml(String(payload.scoring_policy_sha256 || ""))}</span>
      <span>Exclusion ${escapeHtml(String(payload.exclusion?.sha256 || ""))} · snapshot ${escapeHtml(String(payload.context_sha256 || ""))}</span>
    </details>
  `;
  metrics.innerHTML = (payload.summary?.runs || []).map((item) => {
    const confusionRows = item.confusion || [];
    const confusionColumns = Object.keys(confusionRows[0]?.cells || {});
    return `
      <article class="run-collection-metric-card">
        <strong>${escapeHtml(item.run?.name || item.run_id)}</strong>
        <span>${escapeHtml(runCollectionText("准确率", "Accuracy"))} <b>${percentage(item.accuracy)}</b> · ${Number(item.correct_count || 0)}/${Number(item.reference_denominator || 0)}</span>
        <span>${escapeHtml(runCollectionText("Union 准确率覆盖", "Union accuracy coverage"))} ${percentage(item.coverage)} · denominator ${Number(item.pairwise_union_denominator || item.reference_denominator || 0)}</span>
        <span>${escapeHtml(runCollectionText("全 valid reference supported 覆盖", "Supported coverage over all valid reference"))} ${percentage(item.supported_coverage)} · ${Number(item.supported_count || 0)} / ${Number(item.valid_reference_count || 0)}</span>
        <span>${escapeHtml(runCollectionText("缺失 / UNKNOWN", "Absent / UNKNOWN"))} ${Number(item.absent_count || item.absent_prediction_count || 0)} / ${Number(item.unknown_count || 0)}</span>
        ${item.transitions_vs_reference ? `<span>P2P ${Number(item.transitions_vs_reference.P2P || 0)} · P2F ${Number(item.transitions_vs_reference.P2F || 0)} · F2P ${Number(item.transitions_vs_reference.F2P || 0)} · F2F ${Number(item.transitions_vs_reference.F2F || 0)}</span>` : ""}
        ${confusionRows.length ? `<details class="run-collection-confusion"><summary>${escapeHtml(runCollectionText("混淆矩阵", "Confusion matrix"))}</summary><div class="run-collection-mini-matrix-wrap"><table class="run-collection-mini-matrix"><thead><tr><th>Ref</th>${confusionColumns.map((label) => `<th>${escapeHtml(label)}</th>`).join("")}</tr></thead><tbody>${confusionRows.map((row) => `<tr><th>${escapeHtml(row.reference_label)}</th>${confusionColumns.map((label) => `<td>${Number(row.cells?.[label] || 0)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></details>` : ""}
        ${item.available_now === false ? `<em>${escapeHtml(runCollectionText("Run 当前已删除；此评估使用冻结输出。", "Run is unavailable now; this evaluation uses frozen outputs."))}</em>` : ""}
      </article>
    `;
  }).join("");
  const members = payload.members || [];
  head.innerHTML = `<tr><th>Issue</th><th>${escapeHtml(runCollectionText("共享标签状态", "Shared label state"))}</th><th>${escapeHtml(runCollectionText("参考标签", "Reference"))}</th>${members.map((item) => `<th>${escapeHtml(item.run?.name || item.run_id)}${item.is_reference ? ` · ${escapeHtml(runCollectionText("基准", "reference"))}` : ""}</th>`).join("")}</tr>`;
  body.innerHTML = (payload.items || []).map((item) => `
    <tr class="${item.excluded ? "is-excluded" : ""}">
      <th>${escapeHtml(item.issue_id)}${item.excluded ? `<small>${escapeHtml(runCollectionText("已排除", "excluded"))}</small>` : ""}</th>
      <td><span class="run-collection-shared-label">${escapeHtml(item.shared_label?.state || "none")}${item.shared_label?.expected_output ? ` · ${escapeHtml(item.shared_label.expected_output)}` : ""}</span><small>${escapeHtml(item.shared_label?.method || "")}</small></td>
      <td>${escapeHtml(item.reference_label || "—")}${!item.reference_valid ? `<small>${escapeHtml(runCollectionText("无有效参考", "no valid reference"))}</small>` : ""}</td>
      ${members.map((member) => {
        const prediction = item.predictions?.[member.run_id] || {};
        const cls = prediction.correct ? "is-correct" : prediction.label === "NONE" ? "is-missing" : "is-error";
        const reviews = Array.isArray(prediction.model_reviews) ? prediction.model_reviews : [];
        const reviewSummary = reviews.map((review) => `${review.status || "pending"} · ${review.reviewer || "—"}`).join(" / ");
        return `<td><span class="run-collection-prediction ${cls}">${escapeHtml(prediction.label || "NONE")}</span>${prediction.reason ? `<small title="${escapeHtml(prediction.reason)}">${escapeHtml(prediction.reason.slice(0, 100))}</small>` : ""}${reviewSummary ? `<small class="run-collection-review-status">review ${escapeHtml(reviewSummary)}</small>` : `<small class="run-collection-review-status is-unreviewed">review ${escapeHtml(runCollectionText("暂无", "none"))}</small>`}</td>`;
      }).join("")}
    </tr>
  `).join("");
  const pageSummary = $("#runCollectionPageSummary");
  if (pageSummary) pageSummary.textContent = `${Number(payload.page || 1)} / ${Number(payload.page_count || 1)} · ${Number(payload.total || 0)} Issues`;
  const previous = $("#runCollectionPagePrevious");
  const next = $("#runCollectionPageNext");
  if (previous) previous.disabled = Number(payload.page || 1) <= 1;
  if (next) next.disabled = Number(payload.page || 1) >= Number(payload.page_count || 1);
  const search = $("#runCollectionSearch");
  if (search && search.value !== runCollectionUi.search) search.value = runCollectionUi.search;
  const exportLink = $("#runCollectionExport");
  if (exportLink) exportLink.href = withBase(`/api/run-evaluations/${encodeURIComponent(payload.id)}/export`);
}

async function loadRunCollectionEvaluationHistory() {
  const target = $("#runCollectionEvaluationHistory");
  if (!target) return;
  if (!runCollectionUi.detail?.id) {
    target.innerHTML = "";
    return;
  }
  const response = await api(`/api/run-evaluations?collection_id=${encodeURIComponent(runCollectionUi.detail.id)}&limit=100`);
  target.innerHTML = (response.items || []).map((item) => `
    <li><button class="button button-quiet" type="button" data-load-evaluation="${escapeHtml(item.id)}">r${Number(item.collection_revision)} · ${escapeHtml(item.reference_type)} · ${escapeHtml(String(item.context_sha256 || "").slice(0, 16))}</button><small>${escapeHtml(item.created_at || "")} · ${escapeHtml(String(item.workset_sha256 || "").slice(0, 12))}</small></li>
  `).join("");
}

async function loadRunCollectionEvaluation(contextId, { page = 1, search = "", historyMode = "replace" } = {}) {
  const params = new URLSearchParams({ page: String(page), page_size: "50", q: String(search || "") });
  const payload = await api(`/api/run-evaluations/${encodeURIComponent(contextId)}?${params.toString()}`);
  runCollectionUi.evaluation = payload;
  if (runCollectionUi.detail?.id === payload.collection_id) {
    const pinnedRevision = Number(payload.collection_revision || 0);
    if (runCollectionUi.detail.history?.some((item) => Number(item.revision) === pinnedRevision)) {
      runCollectionUi.selectedRevision = pinnedRevision;
      renderRunCollectionDetail();
    }
  }
  runCollectionUi.page = Number(payload.page || 1);
  runCollectionUi.search = String(search || "");
  renderRunCollectionEvaluation(payload);
  runCollectionUpdateUrl(historyMode);
  return payload;
}

async function loadRunCollectionsWorkbench({ restoreRoute = false } = {}) {
  const select = $("#runCollectionSelect");
  if (!select) return;
  const params = new URLSearchParams(window.location.search);
  const routeCollectionId = params.get("collection_id") || params.get("collection") || "";
  const routeEvaluationId = params.get("evaluation_id") || params.get("context") || "";
  runCollectionUi.restoring = Boolean(restoreRoute);
  try {
    const payload = await api("/api/run-collections");
    runCollectionUi.collections = payload.items || [];
    const chosen = runCollectionUi.collections.find((item) => item.id === routeCollectionId)
      || runCollectionUi.collections.find((item) => item.id === runCollectionUi.detail?.id)
      || runCollectionUi.collections[0]
      || null;
    if (!chosen) {
      runCollectionUi.detail = null;
      runCollectionUi.selectedRevision = 0;
      runCollectionUi.evaluation = null;
      renderRunCollectionSelectors();
      renderRunCollectionDetail();
      renderRunCollectionEvaluation(null);
      runCollectionSetStatus(runCollectionText("尚无 Collection。可从 Pairwise 保存，或选择 Run 创建。", "No Collection yet. Save the pairwise Runs or select Runs and create one."));
      return;
    }
    const detail = await api(`/api/run-collections/${encodeURIComponent(chosen.id)}`);
    runCollectionUi.detail = detail;
    const wantedRevision = Number(params.get("collection_revision") || params.get("revision") || detail.current_revision);
    runCollectionUi.selectedRevision = detail.history.some((item) => Number(item.revision) === wantedRevision)
      ? wantedRevision : Number(detail.current_revision);
    renderRunCollectionDetail();
    await loadRunCollectionEvaluationHistory();
    if (routeEvaluationId) {
      runCollectionUi.page = Math.max(1, Number(params.get("evaluation_page") || params.get("page") || 1));
      runCollectionUi.search = String(params.get("evaluation_q") || "");
      try {
        await loadRunCollectionEvaluation(routeEvaluationId, {
          page: runCollectionUi.page, search: runCollectionUi.search, historyMode: "",
        });
      } catch (error) {
        runCollectionUi.evaluation = null;
        renderRunCollectionEvaluation(null);
        runCollectionSetStatus(error.message, true);
      }
    } else {
      runCollectionUi.evaluation = null;
      renderRunCollectionEvaluation(null);
    }
  } catch (error) {
    runCollectionSetStatus(error.message, true);
  } finally {
    runCollectionUi.restoring = false;
  }
}

async function refreshRunCollectionDetail({ updateUrl = false } = {}) {
  if (!runCollectionUi.detail?.id) return;
  const detail = await api(`/api/run-collections/${encodeURIComponent(runCollectionUi.detail.id)}`);
  runCollectionUi.detail = detail;
  if (!detail.history.some((item) => Number(item.revision) === Number(runCollectionUi.selectedRevision))) {
    runCollectionUi.selectedRevision = Number(detail.current_revision);
  }
  renderRunCollectionDetail();
  await loadRunCollectionEvaluationHistory();
  if (updateUrl) runCollectionUpdateUrl("push");
}

function runCollectionSaveButton(button, saving) {
  if (!button) return;
  button.disabled = Boolean(saving);
  button.classList.toggle("is-loading", Boolean(saving));
}

async function runCollectionCreate({ members, name, source = "user", updateUrl = false } = {}) {
  const selectedMembers = members || runCollectionUi.draftMembers;
  const normalized = selectedMembers.map((item) => ({
    run_id: String(item.run_id || ""), role: String(item.role || ""), is_reference: Boolean(item.is_reference),
  })).filter((item) => item.run_id);
  if (!normalized.length) throw new Error(runCollectionText("先选择至少一个 Run。", "Select at least one Run first."));
  const payload = await api("/api/run-collections", {
    method: "POST",
    headers: runCollectionApiHeaders(crypto.randomUUID()),
    body: JSON.stringify({ name: String(name || "").trim(), description: "", members: normalized, source }),
  });
  runCollectionUi.detail = payload;
  runCollectionUi.collections = await api("/api/run-collections").then((result) => result.items || []);
  runCollectionUi.selectedRevision = Number(payload.current_revision || 1);
  runCollectionUi.evaluation = null;
  renderRunCollectionDetail();
  renderRunCollectionSelectors();
  renderRunCollectionEvaluation(null);
  await loadRunCollectionEvaluationHistory();
  runCollectionSetStatus(runCollectionText(`已创建 Collection r${payload.current_revision}。`, `Created Collection r${payload.current_revision}.`));
  if (updateUrl) runCollectionUpdateUrl("push");
  return payload;
}

async function runCollectionEvaluate() {
  if (!runCollectionUi.detail?.id) throw new Error(runCollectionText("请先选择或创建 Collection。", "Select or create a Collection first."));
  const referenceType = $("#runCollectionReferenceType")?.value || "gt";
  const body = {
    collection_id: runCollectionUi.detail.id,
    collection_revision: Number(runCollectionUi.selectedRevision || runCollectionUi.detail.current_revision),
    baselines: selectedBaselineQueryValue(),
    workset_id: String($("#runCollectionWorksetId")?.value || "").trim(),
    reference_type: referenceType,
    reference_id: String($("#runCollectionReferenceId")?.value || "").trim(),
    comparison_reference_run_id: String($("#runCollectionComparisonReference")?.value || "").trim(),
    selection_source_run_id: String($("#runCollectionSelectionSourceRun")?.value || "").trim(),
  };
  if (!body.comparison_reference_run_id) delete body.comparison_reference_run_id;
  if (referenceType === "label_result") {
    const scopeInputs = [...document.querySelectorAll("#runCollectionLabelReferenceSet [data-label-scope]")];
    if (scopeInputs.length) {
      body.reference_ids = Object.fromEntries(
        scopeInputs.map((input) => [String(input.dataset.labelScope || ""), String(input.value || "").trim()]).filter((item) => item[0] && item[1])
      );
      delete body.reference_id;
    }
  }
  const result = await api("/api/run-evaluations", {
    method: "POST",
    headers: runCollectionApiHeaders(crypto.randomUUID()),
    body: JSON.stringify(body),
  });
  runCollectionUi.evaluation = result;
  runCollectionUi.page = Number(result.page || 1);
  runCollectionUi.search = "";
  renderRunCollectionEvaluation(result);
  await loadRunCollectionEvaluationHistory();
  runCollectionUpdateUrl("push");
  runCollectionSetStatus(runCollectionText("Evaluation Context 已冻结并保存。", "Evaluation Context frozen and saved."));
}

function bindRunCollectionsEvents() {
  if (window.__runCollectionsBound) return;
  window.__runCollectionsBound = true;
  $("#runCollectionRefreshButton")?.addEventListener("click", () => {
    loadRunCollectionsWorkbench().catch((error) => runCollectionSetStatus(error.message, true));
  });
  $("#runCollectionSelect")?.addEventListener("change", async (event) => {
    runCollectionUi.evaluation = null;
    renderRunCollectionEvaluation(null);
    if (!event.target.value) {
      runCollectionUi.detail = null;
      renderRunCollectionDetail();
      runCollectionUpdateUrl("push");
      return;
    }
    try {
      runCollectionUi.detail = await api(`/api/run-collections/${encodeURIComponent(event.target.value)}`);
      runCollectionUi.selectedRevision = Number(runCollectionUi.detail.current_revision);
      renderRunCollectionDetail();
      await loadRunCollectionEvaluationHistory();
      runCollectionUpdateUrl("push");
    } catch (error) { runCollectionSetStatus(error.message, true); }
  });
  $("#runCollectionRevisionSelect")?.addEventListener("change", (event) => {
    runCollectionUi.selectedRevision = Number(event.target.value || 0);
    renderRunCollectionDetail();
    runCollectionUpdateUrl("push");
  });
  $("#runCollectionMembers")?.addEventListener("click", (event) => {
    const row = event.target.closest("[data-member-index]");
    if (!row) return;
    const index = Number(row.dataset.memberIndex);
    if (event.target.closest("[data-member-move]")) {
      const delta = Number(event.target.closest("[data-member-move]").dataset.memberMove);
      const next = index + delta;
      if (next >= 0 && next < runCollectionUi.draftMembers.length) {
        [runCollectionUi.draftMembers[index], runCollectionUi.draftMembers[next]] = [runCollectionUi.draftMembers[next], runCollectionUi.draftMembers[index]];
        runCollectionUi.draftMembers.forEach((item, ordinal) => { item.ordinal = ordinal + 1; });
        renderRunCollectionMembers();
      }
    } else if (event.target.closest("[data-member-reference]")) {
      const selected = !runCollectionUi.draftMembers[index].is_reference;
      runCollectionUi.draftMembers = runCollectionUi.draftMembers.map((item, offset) => ({ ...item, is_reference: offset === index && selected }));
      renderRunCollectionMembers();
    } else if (event.target.closest("[data-member-remove]")) {
      runCollectionUi.draftMembers.splice(index, 1);
      renderRunCollectionMembers();
    }
  });
  $("#runCollectionAddRunButton")?.addEventListener("click", () => {
    const runId = String($("#runCollectionAddRun")?.value || "");
    if (!runId || runCollectionUi.draftMembers.some((item) => item.run_id === runId)) return;
    const run = (state.modelRuns || []).find((item) => String(item.id) === runId) || {};
    runCollectionUi.draftMembers.push({ run_id: runId, role: "", is_reference: runCollectionUi.draftMembers.length === 0, available_now: true, run });
    renderRunCollectionMembers();
  });
  $("#runCollectionAppendRevisionButton")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    if (!runCollectionUi.detail?.id) return runCollectionSetStatus(runCollectionText("请先选择评测项目。", "Select an evaluation project first."), true);
    runCollectionSaveButton(button, true);
    try {
      const result = await api(`/api/run-collections/${encodeURIComponent(runCollectionUi.detail.id)}/revisions`, {
        method: "POST", headers: runCollectionApiHeaders(crypto.randomUUID()),
        body: JSON.stringify({ expected_revision: Number(runCollectionUi.detail.current_revision), members: runCollectionUi.draftMembers.map((item) => ({ run_id: item.run_id, role: item.role || "", is_reference: Boolean(item.is_reference) })) }),
      });
      runCollectionUi.detail = result;
      runCollectionUi.selectedRevision = Number(result.current_revision);
      renderRunCollectionDetail();
      runCollectionUpdateUrl("push");
      runCollectionSetStatus(runCollectionText(`已保存项目版本 r${result.current_revision}。`, `Appended revision r${result.current_revision}.`));
    } catch (error) { runCollectionSetStatus(error.message, true); }
    finally { runCollectionSaveButton(button, false); }
  });
  $("#runCollectionRenameButton")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    if (!runCollectionUi.detail?.id) return runCollectionSetStatus(runCollectionText("请先选择评测项目。", "Select an evaluation project first."), true);
    runCollectionSaveButton(button, true);
    try {
      runCollectionUi.detail = await api(`/api/run-collections/${encodeURIComponent(runCollectionUi.detail.id)}`, {
        method: "PATCH", headers: runCollectionApiHeaders(),
        body: JSON.stringify({ expected_revision: Number(runCollectionUi.detail.current_revision), expected_metadata_revision: Number(runCollectionUi.detail.metadata_revision || 0), name: $("#runCollectionName").value, description: $("#runCollectionDescription").value }),
      });
      runCollectionUi.collections = await api("/api/run-collections").then((result) => result.items || []);
      renderRunCollectionDetail();
      runCollectionSetStatus(runCollectionText("元数据已更新，没有创建新 Revision。", "Metadata updated without creating a new revision."));
    } catch (error) { runCollectionSetStatus(error.message, true); }
    finally { runCollectionSaveButton(button, false); }
  });
  $("#runCollectionCreateButton")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    runCollectionSaveButton(button, true);
    try {
      await runCollectionCreate({ members: runCollectionUi.draftMembers, name: $("#runCollectionCreateName").value });
    } catch (error) { runCollectionSetStatus(error.message, true); }
    finally { runCollectionSaveButton(button, false); }
  });
  $("#comparisonSaveCollectionButton")?.addEventListener("click", async (event) => {
    const baseline = String(state.runComparison?.baselineRunId || "");
    const candidate = String(state.runComparison?.candidateRunId || "");
    if (!baseline || !candidate || baseline === candidate) {
      return runCollectionSetStatus(runCollectionText("选择两个不同的 Run 后再保存。", "Choose two different Runs before saving."), true);
    }
    const defaultName = `${runCollectionMemberName({ run_id: baseline })} vs ${runCollectionMemberName({ run_id: candidate })}`;
    const name = window.prompt(runCollectionText("评测项目名称", "Collection name"), defaultName);
    if (name == null || !name.trim()) return;
    const button = event.currentTarget;
    runCollectionSaveButton(button, true);
    try {
      const detail = await api("/api/run-comparison/save-collection", {
        method: "POST", headers: runCollectionApiHeaders(crypto.randomUUID()),
        body: JSON.stringify({ baseline_run_id: baseline, candidate_run_id: candidate, name: name.trim() }),
      });
      runCollectionUi.detail = detail;
      runCollectionUi.selectedRevision = Number(detail.current_revision);
      runCollectionUi.collections = await api("/api/run-collections").then((result) => result.items || []);
      renderRunCollectionDetail();
      runCollectionSetStatus(runCollectionText("Pairwise 已按基线、新 Run 顺序保存；当前 Pairwise URL 未改变。", "Pairwise saved in baseline/candidate order; the current pairwise URL is unchanged."));
    } catch (error) { runCollectionSetStatus(error.message, true); }
    finally { runCollectionSaveButton(button, false); }
  });
  $("#runCollectionHistory")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-load-revision]");
    if (!button) return;
    const revision = Number(button.dataset.loadRevision);
    $("#runCollectionRevisionSelect").value = String(revision);
    runCollectionUi.selectedRevision = revision;
    renderRunCollectionDetail();
    runCollectionUpdateUrl("push");
  });
  $("#runCollectionEvaluateButton")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    runCollectionSaveButton(button, true);
    try { await runCollectionEvaluate(); }
    catch (error) { runCollectionSetStatus(error.message, true); }
    finally { runCollectionSaveButton(button, false); }
  });
  $("#runCollectionEvaluationHistory")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-load-evaluation]");
    if (!button) return;
    loadRunCollectionEvaluation(button.dataset.loadEvaluation, { page: 1, search: "", historyMode: "push" })
      .catch((error) => runCollectionSetStatus(error.message, true));
  });
  const createReviewArtifact = async (endpoint, button, label) => {
    if (!runCollectionUi.evaluation?.id) {
      runCollectionSetStatus(runCollectionText("请先冻结并完成一次 Evaluation。", "Freeze an Evaluation Context first."), true);
      return;
    }
    const assignees = String($("#runCollectionTaskAssignees")?.value || "")
      .split(/[\s,，;；]+/).map((item) => item.trim()).filter(Boolean);
    if (!assignees.length) {
      runCollectionSetStatus(runCollectionText("填写至少一个已启用的管理员分配对象。", "Enter at least one enabled assignee."), true);
      return;
    }
    runCollectionSaveButton(button, true);
    try {
      const result = await api(`/api/run-evaluations/${encodeURIComponent(runCollectionUi.evaluation.id)}/${endpoint}`, {
        method: "POST", headers: runCollectionApiHeaders(crypto.randomUUID()),
        body: JSON.stringify({
          name: `${runCollectionUi.detail?.name || "Evaluation"} · ${label}`,
          assignees,
          run_ids: (runCollectionUi.evaluation.members || []).map((item) => item.run_id),
        }),
      });
      const item = result.campaign?.campaign || result.campaign || result.group || {};
      runCollectionSetStatus(`${label}: ${item.id || "created"}`);
    } catch (error) { runCollectionSetStatus(error.message, true); }
    finally { runCollectionSaveButton(button, false); }
  };
  $("#runCollectionCreateLabelingCampaign")?.addEventListener("click", (event) => {
    createReviewArtifact("labeling-campaign", event.currentTarget, runCollectionText("创建标注实验", "标注实验"));
  });
  $("#runCollectionCreateModelReviewGroup")?.addEventListener("click", (event) => {
    createReviewArtifact("model-review-group", event.currentTarget, runCollectionText("复核任务", "复核任务"));
  });
  $("#runCollectionPagePrevious")?.addEventListener("click", () => {
    if (runCollectionUi.evaluation && runCollectionUi.page > 1) {
      loadRunCollectionEvaluation(runCollectionUi.evaluation.id, { page: runCollectionUi.page - 1, search: runCollectionUi.search, historyMode: "push" }).catch((error) => runCollectionSetStatus(error.message, true));
    }
  });
  $("#runCollectionPageNext")?.addEventListener("click", () => {
    if (runCollectionUi.evaluation) {
      loadRunCollectionEvaluation(runCollectionUi.evaluation.id, { page: runCollectionUi.page + 1, search: runCollectionUi.search, historyMode: "push" }).catch((error) => runCollectionSetStatus(error.message, true));
    }
  });
  $("#runCollectionSearch")?.addEventListener("input", (event) => {
    runCollectionUi.search = String(event.target.value || "").trim().slice(0, 128);
    if (runCollectionUi.searchTimer) window.clearTimeout(runCollectionUi.searchTimer);
    runCollectionUi.searchTimer = window.setTimeout(() => {
      if (runCollectionUi.evaluation) loadRunCollectionEvaluation(runCollectionUi.evaluation.id, { page: 1, search: runCollectionUi.search, historyMode: "push" }).catch((error) => runCollectionSetStatus(error.message, true));
    }, 250);
  });
  $("#runCollectionReferenceType")?.addEventListener("change", (event) => {
    $("#runCollectionReferenceId").disabled = event.target.value === "gt";
    $("#runCollectionReferenceId").placeholder = event.target.value === "label_result" ? "label-result-…" : "GT snapshot is selected by scope";
    renderRunCollectionLabelReferenceSet(runCollectionUi.evaluation?.workset?.baseline_scopes || runCollectionSelectedScopes(), {});
  });
  window.addEventListener("popstate", () => {
    const params = new URLSearchParams(window.location.search);
    if (params.has("collection_id") || params.has("collection") || params.has("context")) {
      loadRunCollectionsWorkbench({ restoreRoute: true }).catch((error) => runCollectionSetStatus(error.message, true));
    }
  });
  if (state.activePage === "run-collections" || window.location.pathname.includes("/run-collections")) {
    loadRunCollectionsWorkbench({ restoreRoute: true }).catch((error) => runCollectionSetStatus(error.message, true));
  }
}
