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
    ["范围 Case", payload.case_count],
    ["已标注 Case", payload.annotated_cases],
    ["完整标注记录", payload.complete_records],
    ["多人一致性", payload.agreement.comparable_cases ? `${payload.agreement.matching_cases} / ${payload.agreement.comparable_cases}` : "—"],
  ];
  $("#intentSummaryMetrics").innerHTML = metrics.map(([label, value]) => `<article class="intent-summary-metric"><small>${label}</small><strong>${escapeHtml(value)}</strong></article>`).join("");
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

