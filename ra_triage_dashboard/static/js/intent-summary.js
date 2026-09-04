function intentSetSaveState(text, kind = "") {
  const element = $("#intentSaveState");
  if (!element) return;
  element.textContent = text;
  element.dataset.status = kind;
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

function intentSummaryLabelingHref(datasetId, caseId, extra = {}) {
  const selected = parseFilterList(state.intentLabeling.summaryDatasetIds);
  const ordered = [datasetId, ...selected.filter((id) => id !== datasetId)];
  const params = new URLSearchParams();
  ordered.forEach((id) => params.append("dataset", id));
  params.set("case", caseId);
  Object.entries(extra).forEach(([key, value]) => params.set(key, String(value)));
  return `${withBase("/intent-labeling")}?${params}`;
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
  const rows = hits.length ? hits.map((item) => {
    const datasetId = item.dataset_id || state.intentLabeling.summaryDatasetId;
    const href = intentSummaryLabelingHref(datasetId, item.case_id, { comments: 1, comment: item.id });
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

function intentSummaryDistributionMarkup(title, counts, labels) {
  const entries = Object.entries(counts || {})
    .filter(([, count]) => Number(count) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]));
  const total = entries.reduce((sum, [, count]) => sum + Number(count), 0);
  if (!entries.length) return "";
  const segments = entries.map(([value, count]) => `<i class="${intentSummaryChipClass(value)}" style="width:${Number(count) * 100 / total}%" title="${escapeHtml(labels[value] || value)} ${Number(count)} 帧"></i>`).join("");
  const legend = entries.map(([value, count]) => `<span><b class="${intentSummaryChipClass(value)}"></b>${escapeHtml(labels[value] || value)} ${Number(count)}帧 · ${Math.round(Number(count) * 100 / total)}%</span>`).join("");
  return `<article class="intent-summary-distribution"><header><strong>${title}</strong><small>${total} 个已标注帧</small></header><div class="intent-summary-distribution-track">${segments}</div><div class="intent-summary-distribution-legend">${legend}</div></article>`;
}

function renderIntentSummaryDistributions(payload, showRouting, showLaneChange) {
  const container = $("#intentSummaryDistributions");
  if (!container) return;
  const distributions = payload.frame_distributions || {};
  container.innerHTML = [
    showRouting ? intentSummaryDistributionMarkup("Routing 标签比例", distributions.routing, INTENT_ROUTING_LABELS) : "",
    showLaneChange ? intentSummaryDistributionMarkup("变道意图标签比例", distributions.lane_change, INTENT_LANE_LABELS) : "",
  ].filter(Boolean).join("");
  container.hidden = !container.innerHTML;
}

function renderIntentSummary(payload) {
  const axis = payload.axis || "all";
  const labelScope = payload.label_scope || "all";
  const showRouting = labelScope !== "lane_change" && axis !== "lane_change";
  const showLaneChange = labelScope !== "routing" && axis !== "routing";
  document.querySelectorAll(".intent-summary-routing-column").forEach((element) => { element.hidden = !showRouting; });
  document.querySelectorAll(".intent-summary-lane-column").forEach((element) => { element.hidden = !showLaneChange; });
  document.querySelectorAll(".intent-summary-admin-column").forEach((element) => { element.hidden = !state.session.is_admin; });
  const metrics = [
    ["范围 Case", payload.case_count],
    ["已标注 Case", payload.annotated_cases],
    ["完整标注记录", payload.complete_records],
    ["多人一致性", payload.agreement.comparable_cases ? `${payload.agreement.matching_cases} / ${payload.agreement.comparable_cases}` : "—"],
  ];
  $("#intentSummaryMetrics").innerHTML = metrics.map(([label, value]) => `<article class="intent-summary-metric"><small>${label}</small><strong>${escapeHtml(value)}</strong></article>`).join("");
  renderIntentSummaryDistributions(payload, showRouting, showLaneChange);
  renderIntentSummaryCommentHits(payload);
  const columnCount = 4 + Number(showRouting) + Number(showLaneChange) + Number(state.session.is_admin);
  $("#intentSummaryRows").innerHTML = (payload.items || []).map((item) => {
    const datasetId = item.dataset_id || state.intentLabeling.summaryDatasetId;
    const href = intentSummaryLabelingHref(datasetId, item.case_id);
    const action = state.session.is_admin
      ? `<td class="intent-summary-admin-column"><div class="intent-summary-row-actions"><label class="intent-summary-select"><input type="checkbox" data-intent-summary-select data-dataset-id="${escapeHtml(datasetId)}" data-case-id="${escapeHtml(item.case_id)}" data-username="${escapeHtml(item.username)}" data-revision-id="${Number(item.revision_id)}" aria-label="选择 ${escapeHtml(item.case_id)} ${escapeHtml(item.username)} 的标注"/></label><button class="button button-quiet intent-summary-delete" type="button" data-intent-summary-delete data-dataset-id="${escapeHtml(datasetId)}" data-case-id="${escapeHtml(item.case_id)}" data-username="${escapeHtml(item.username)}" data-revision-id="${Number(item.revision_id)}">删除标注</button></div></td>`
      : "";
    const comments = (item.comments || []).map((comment) => `<a href="${escapeHtml(intentSummaryLabelingHref(datasetId, item.case_id, { comments: 1, comment: comment.id }))}" title="${escapeHtml(comment.body)}"><b>${escapeHtml(comment.author)}：</b>${escapeHtml(comment.body)}</a>`).join("");
    const commentMarkup = comments ? `<div class="intent-summary-row-comments">${comments}${Number(item.comment_count || 0) > (item.comments || []).length ? `<small>共 ${Number(item.comment_count)} 条</small>` : ""}</div>` : '<span class="intent-summary-no-comment">—</span>';
    return `<tr><td><a class="intent-summary-case-link" href="${escapeHtml(href)}">${escapeHtml(item.case_id)}</a>${(payload.dataset_ids || []).length > 1 ? `<small>${escapeHtml(datasetId)}</small>` : ""}</td><td>${escapeHtml(item.username)}${item.username === state.session.username ? "（我）" : ""}</td><td class="intent-summary-routing-column"${showRouting ? "" : " hidden"}>${intentSummaryResultMarkup(item.frame_counts?.routing, INTENT_ROUTING_LABELS)}</td><td class="intent-summary-lane-column"${showLaneChange ? "" : " hidden"}>${intentSummaryResultMarkup(item.frame_counts?.lane_change, INTENT_LANE_LABELS)}</td><td class="intent-summary-comments-column">${commentMarkup}</td><td>${escapeHtml(formatTime(item.updated_at) || "—")}</td>${action}</tr>`;
  }).join("") || `<tr><td colspan="${columnCount}">当前筛选下没有已标注结果。</td></tr>`;
  $("#intentSummaryRows").querySelectorAll("[data-intent-summary-delete]").forEach((button) => {
    button.addEventListener("click", () => {
      deleteIntentSummaryLabel(button).catch((error) => showToast(error.message, true));
    });
  });
  const selectPage = $("#intentSummarySelectPage");
  const bulkDelete = $("#intentSummaryBulkDelete");
  if (selectPage) {
    selectPage.hidden = !state.session.is_admin;
    selectPage.checked = false;
    selectPage.indeterminate = false;
    selectPage.onchange = () => {
      $("#intentSummaryRows").querySelectorAll("[data-intent-summary-select]").forEach((checkbox) => {
        checkbox.checked = selectPage.checked;
      });
      updateIntentSummaryBulkSelection();
    };
  }
  $("#intentSummaryRows").querySelectorAll("[data-intent-summary-select]").forEach((checkbox) => {
    checkbox.addEventListener("change", updateIntentSummaryBulkSelection);
  });
  if (bulkDelete) {
    bulkDelete.hidden = !state.session.is_admin;
    bulkDelete.onclick = () => bulkDeleteIntentSummaryLabels().catch((error) => showToast(error.message, true));
  }
  updateIntentSummaryBulkSelection();
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
  const pageJump = $("#intentSummaryPageJump");
  if (pageJump) {
    pageJump.max = String(pageCount);
    pageJump.value = String(payload.page);
  }
  const pageSize = $("#intentSummaryPageSize");
  if (pageSize) pageSize.value = String(payload.page_size || 20);
}

function jumpIntentSummaryPage() {
  const input = $("#intentSummaryPageJump");
  const pageCount = Math.max(1, Math.ceil(
    Number(state.intentLabeling.summaryPayload?.total || 0)
      / Number(state.intentLabeling.summaryPayload?.page_size || 20)
  ));
  const page = Math.min(pageCount, Math.max(1, Number.parseInt(input?.value || "1", 10) || 1));
  if (input) input.value = String(page);
  if (page === state.intentLabeling.summaryPage) return;
  state.intentLabeling.summaryPage = page;
  loadIntentSummary({ datasetIds: state.intentLabeling.summaryDatasetIds, force: true })
    .catch((error) => showToast(error.message, true));
}

function selectedIntentSummaryDeleteTargets() {
  return [...$("#intentSummaryRows").querySelectorAll("[data-intent-summary-select]:checked")].map((checkbox) => ({
    dataset_id: checkbox.dataset.datasetId || "",
    case_id: checkbox.dataset.caseId || "",
    username: checkbox.dataset.username || "",
    expected_revision_id: Number(checkbox.dataset.revisionId) || 0,
  })).filter((item) => item.dataset_id && item.case_id && item.username && item.expected_revision_id);
}

function updateIntentSummaryBulkSelection() {
  const checkboxes = [...$("#intentSummaryRows").querySelectorAll("[data-intent-summary-select]")];
  const selectedCount = checkboxes.filter((checkbox) => checkbox.checked).length;
  const selectPage = $("#intentSummarySelectPage");
  if (selectPage) {
    selectPage.checked = Boolean(checkboxes.length) && selectedCount === checkboxes.length;
    selectPage.indeterminate = selectedCount > 0 && selectedCount < checkboxes.length;
  }
  const button = $("#intentSummaryBulkDelete");
  if (button) {
    button.disabled = selectedCount === 0;
    button.textContent = selectedCount ? `批量删除 (${selectedCount})` : "批量删除";
  }
}

async function bulkDeleteIntentSummaryLabels() {
  if (!state.session.is_admin) return;
  const items = selectedIntentSummaryDeleteTargets();
  if (!items.length) return;
  if (!await confirmIntentLabelDeletion({ count: items.length })) return;
  const button = $("#intentSummaryBulkDelete");
  if (button) button.disabled = true;
  try {
    const result = await api("/api/intent-labels/bulk-delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    });
    acknowledgeLocalChange(result);
    await loadIntentSummary({ datasetIds: state.intentLabeling.summaryDatasetIds, force: true });
    showToast(`已删除 ${Number(result.count) || items.length} 条标注，历史修订与审计记录已保留。`, false);
  } finally {
    if (button) button.disabled = false;
  }
}

async function deleteIntentSummaryLabel(button) {
  if (!state.session.is_admin) return;
  const caseId = button.dataset.caseId || "";
  const username = button.dataset.username || "";
  const revisionId = Number(button.dataset.revisionId) || 0;
  const datasetId = button.dataset.datasetId || state.intentLabeling.summaryDatasetId;
  if (!caseId || !username || !revisionId) return;
  if (!await confirmIntentLabelDeletion({ username, caseId })) return;
  button.disabled = true;
  try {
    const result = await api(`/api/intent-datasets/${encodeURIComponent(datasetId)}/cases/${encodeURIComponent(caseId)}/labels/${encodeURIComponent(username)}?expected_revision_id=${revisionId}`, { method: "DELETE" });
    acknowledgeLocalChange(result);
    await loadIntentSummary({ datasetIds: state.intentLabeling.summaryDatasetIds, force: true });
    showToast("标注已删除，历史修订与审计记录已保留。", false);
  } finally {
    button.disabled = false;
  }
}

async function loadIntentSummary({ datasetId = "", datasetIds = null, force = false } = {}) {
  const intent = state.intentLabeling;
  restoreIntentWorkspacePreferences();
  if (!intent.datasets.length) intent.datasets = (await api("/api/intent-datasets")).items || [];
  const available = intent.datasets.filter((item) => item.available);
  let selectedIds = parseFilterList(datasetIds == null ? intent.summaryDatasetIds : datasetIds)
    .filter((id) => available.some((item) => item.id === id));
  if (!selectedIds.length && datasetId && available.some((item) => item.id === datasetId)) selectedIds = [datasetId];
  if (!selectedIds.length && intent.summaryDatasetId && available.some((item) => item.id === intent.summaryDatasetId)) selectedIds = [intent.summaryDatasetId];
  if (!selectedIds.length && available[0]) selectedIds = [available[0].id];
  if (!selectedIds.length) throw new Error("没有可汇总的数据集。");
  intent.summaryDatasetIds = selectedIds;
  intent.summaryDatasetId = selectedIds[0];
  renderIntentTopbarDatasetPicker(selectedIds);
  const params = new URLSearchParams();
  selectedIds.forEach((id) => params.append("dataset_id", id));
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
    label: selectedIds.length > 1 ? `${item.dataset_id} · ${item.name}` : item.name,
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
      const selectedExperiment = (payload.experiments || []).find((item) => item.id === experimentId);
      if (selectedExperiment?.label_scope && selectedExperiment.label_scope !== "all") {
        intent.summaryAxis = selectedExperiment.label_scope;
      }
      intent.summaryAssignees = [];
      intent.summaryPage = 1;
      loadIntentSummary({ datasetIds: selectedIds, force: true }).catch((error) => showToast(error.message, true));
    },
  });
  const summaryAxisOptions = [
    { value: "all", label: "Routing + 变道意图" },
    { value: "routing", label: "仅 Routing" },
    { value: "lane_change", label: "仅变道意图" },
  ].filter((item) => payload.label_scope === "all" || item.value === payload.label_scope);
  if (payload.label_scope !== "all") intent.summaryAxis = payload.label_scope;
  populateUiSelect($("#intentSummaryAxisPicker"), summaryAxisOptions, intent.summaryAxis || "all");
  bindUiSelect($("#intentSummaryAxisPicker"), { maxWidth: 260 });
  const commentInput = $("#intentSummaryCommentQuery");
  if (commentInput && commentInput.value !== (intent.summaryCommentQuery || "")) {
    commentInput.value = intent.summaryCommentQuery || "";
  }
  renderMultiFilter($("#intentSummaryAssignees"), { options: (payload.owners || []).map((value) => ({ value, label: value === state.session.username ? `${value}（我）` : value })), selected: intent.summaryAssignees || [], onlyThis: true, onChange: (values) => { intent.summaryAssignees = values; intent.summaryPage = 1; loadIntentSummary({ datasetIds: selectedIds, force: true }).catch((error) => showToast(error.message, true)); } });
  renderIntentSummary(payload);
  persistIntentWorkspacePreferences();
  const routeParams = new URLSearchParams();
  selectedIds.forEach((id) => routeParams.append("dataset", id));
  if (intent.summaryExperimentId) routeParams.set("experiment", intent.summaryExperimentId);
  (intent.summaryAssignees || []).forEach((value) => routeParams.append("owner", value));
  if ((intent.summaryPage || 1) > 1) routeParams.set("page", String(intent.summaryPage));
  if ((intent.summaryAxis || "all") !== "all") routeParams.set("axis", intent.summaryAxis);
  if ((intent.summaryPageSize || 20) !== 20) routeParams.set("page_size", String(intent.summaryPageSize));
  if (commentQuery) routeParams.set("q", commentQuery);
  history.replaceState({ page: "intent-summary", datasetId: selectedIds[0], datasetIds: selectedIds }, "", `${withBase("/intent-summary")}?${routeParams}`);
}
