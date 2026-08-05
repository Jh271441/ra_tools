/* ra_triage_dashboard/static/js/runs.js
 * Model runs registry and selection
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
async function loadReviewers() {
  const runId = String(state.selectedRunId || "").trim();
  const data = await api(
    runId ? `/api/reviewers?model_run_id=${encodeURIComponent(runId)}` : "/api/reviewers"
  );
  state.reviewers = data.items || [];
  const reviewerOptions = state.reviewers.map((item) => {
    const trust =
      item.verified_count > 0 && item.unverified_count > 0
        ? " · 混合身份"
        : item.verified
          ? " · SSO"
          : "";
    return {
      value: item.name,
      label: `${item.name} · ${item.review_count} 条${trust}`,
    };
  });
  const reviewSelect = $("#reviewerFilter");
  if (reviewSelect) {
    renderMultiFilter(reviewSelect, {
      options: reviewerOptions,
      selected: getMultiFilterValues(reviewSelect),
      onChange: () => scheduleReviewFilterReload?.(0),
    });
  }
  const analysisReviewer = $("#analysisReviewerFilter");
  if (analysisReviewer) {
    renderMultiFilter(analysisReviewer, {
      options: reviewerOptions,
      selected: getMultiFilterValues(analysisReviewer),
      onChange: () => scheduleAnalysisFilterReload(),
    });
  }
}

function renderReviewCatalogFilters() {
  const onChange = () => scheduleReviewFilterReload?.(0);
  renderMultiFilter($("#comparisonFilter"), {
    options: [
      { value: "mismatch", label: "MISMATCH · 判断失败" },
      { value: "match", label: "MATCH · 判断一致" },
      { value: "none", label: "NONE · 未预测" },
    ],
    selected: parseComparisonStatuses(
      getMultiFilterValues($("#comparisonFilter")).length
        ? getMultiFilterValues($("#comparisonFilter"))
        : state.reviewComparisonStatus
    ),
    onChange: () => {
      state.reviewComparisonStatus = selectedReviewComparisonStatus();
      state.failureOnly = state.reviewComparisonStatus === "mismatch";
      onChange();
    },
  });
  const hasRun = Boolean($("#modelRunFilter")?.value || state.selectedRunId);
  $("#comparisonFilter")?.classList.toggle("is-disabled", !hasRun);
  $("#comparisonFilter")
    ?.querySelector(".multi-filter-trigger")
    ?.toggleAttribute("disabled", !hasRun);
  if (!hasRun) setMultiFilterValues($("#comparisonFilter"), []);
  renderMultiFilter($("#gtFilter"), {
    options: LABELS.map((label) => ({ value: label, label })),
    selected: getMultiFilterValues($("#gtFilter")),
    onChange,
  });
  renderMultiFilter($("#annotationFilter"), {
    options: LABELS.map((label) => ({ value: label, label })),
    selected: getMultiFilterValues($("#annotationFilter")),
    onChange,
  });
}

function checkedAnalysisComparisonStatus() {
  return normalizedAnalysisComparisonStatus(
    $("#analysisComparisonFilter")?.value,
    state.reviewAnalysis.comparisonStatus || "all"
  );
}

function setAnalysisComparisonStatus(
  comparisonStatus,
  { hasRun = Boolean($("#analysisRunFilter")?.value) } = {}
) {
  let nextStatus = normalizedAnalysisComparisonStatus(comparisonStatus);
  if (!hasRun && nextStatus !== "all") nextStatus = "all";
  state.reviewAnalysis.comparisonStatus = nextStatus;
  const select = $("#analysisComparisonFilter");
  if (select) {
    select.disabled = !hasRun;
    select.value = nextStatus;
  }
  return nextStatus;
}

function renderAnalysisRunFilter() {
  const select = $("#analysisRunFilter");
  if (!select) return;
  select.innerHTML = `<option value="">不叠加模型输出</option>${state.modelRuns
    .map((run) => {
      const tag = run.is_default ? "默认 · " : "";
      return `<option value="${escapeHtml(run.id)}">${tag}${escapeHtml(run.name)} · ${run.baseline_prediction_count ?? 0} 条 · 错 ${run.failure_count ?? 0}</option>`;
    })
    .join("")}`;
  select.value = state.modelRuns.some((run) => run.id === state.selectedRunId)
    ? state.selectedRunId
    : "";
  setAnalysisComparisonStatus(state.reviewAnalysis.comparisonStatus, {
    hasRun: Boolean(select.value),
  });
}

async function loadRuns({ preferDefault = false, preserveEmpty = false } = {}) {
  const data = await api("/api/model-runs");
  state.modelRuns = data.items || [];
  const select = $("#modelRunFilter");
  const previousRunId = state.selectedRunId;
  const preferredRunId =
    data.default_model_run_id ||
    state.config?.default_model_run_id ||
    (preferDefault ? state.modelRuns[0]?.id || "" : "");
  const candidate = preferDefault
    ? preferredRunId
    : preserveEmpty
      ? state.selectedRunId
      : state.selectedRunId || data.default_model_run_id || state.config?.default_model_run_id || "";
  select.innerHTML = `<option value="">未选择模型 run</option>${state.modelRuns
    .map((run) => {
      const tag = run.is_default ? "默认 · " : "";
      return `<option value="${escapeHtml(run.id)}">${tag}${escapeHtml(run.name)} · ${run.baseline_prediction_count ?? 0} 条 · 错 ${run.failure_count ?? 0}</option>`;
    })
    .join("")}`;
  state.selectedRunId = state.modelRuns.some((run) => run.id === candidate) ? candidate : "";
  select.value = state.selectedRunId;
  if (preferDefault && !previousRunId && state.selectedRunId) {
    // A Run is an overlay on the immutable 0508 baseline.  Selecting or
    // importing it must not shrink the baseline itself.  Keep the established
    // Review default focused on model failures; NONE remains available from
    // the comparison filter and is still retained in the baseline queue.
    state.reviewComparisonStatus = "mismatch";
    state.failureOnly = true;
  }
  if (!state.selectedRunId) state.reviewComparisonStatus = "all";
  setReviewComparisonStatus(state.reviewComparisonStatus, {
    hasRun: Boolean(state.selectedRunId),
  });
  renderAnalysisRunFilter();
  renderRunFilters();
  renderRunSourceSummary();
  renderActiveRun();
  renderRunManager();
}

const RUN_SOURCE_META = Object.freeze({
  upload: {
    label: "文件模型结果",
    description: "JSON / CSV / XLSX",
    className: "source-upload",
    countId: "runSourceCountUpload",
  },
  trail_snapshot: {
    label: "Trail 快照",
    description: "Trail 只读字段",
    className: "source-trail",
    countId: "runSourceCountTrail",
  },
  autotriage_snapshot: {
    label: "AutoTriage 快照",
    description: "平台只读结果",
    className: "source-autotriage",
    countId: "runSourceCountAutotriage",
  },
  manual_batch: {
    label: "网页 Batch 预测",
    description: "服务器模型推理",
    className: "source-batch",
  },
});

function runSourceMeta(runOrKind) {
  const kind = typeof runOrKind === "string" ? runOrKind : runOrKind?.kind;
  return RUN_SOURCE_META[kind] || {
    label: kind || "未知来源",
    description: "未记录来源",
    className: "source-unknown",
  };
}

function runSourceReference(run) {
  const metadata = run?.metadata && typeof run.metadata === "object" ? run.metadata : {};
  const recordUrl = safeUrl(metadata.record_url || metadata.records_url || "");
  if (recordUrl) {
    return `<a class="run-source-link" href="${escapeHtml(recordUrl)}" target="_blank" rel="noreferrer">原始 records</a>`;
  }
  if (run?.kind === "trail_snapshot") {
    const viewId = metadata.view_id || metadata.trail_view_id || String(run.source_name || "").match(/\d+/)?.[0] || "2410";
    return `<span class="run-source-ref">Trail view ${escapeHtml(viewId)}</span>`;
  }
  const source = run?.source_file && typeof run.source_file === "object" ? run.source_file : {};
  const sourceName = String(source.filename || run?.source_name || "").split(/[\\/]/).pop() || "文件名未记录";
  const previewUrl = safeSameOriginAssetUrl(source.preview_url);
  const downloadUrl = safeSameOriginAssetUrl(source.download_url);
  const reconstructed = source.reconstructed
    ? '<span class="run-source-reconstructed">Run 重建</span>'
    : "";
  const previewAction = source.preview_supported
    ? `<button class="run-source-preview" type="button" data-preview-run="${escapeHtml(run?.id || "")}">预览</button>`
    : previewUrl
      ? `<a class="run-source-link" href="${escapeHtml(previewUrl)}" target="_blank" rel="noreferrer">打开</a>`
      : "";
  const actions = source.available && (previewUrl || downloadUrl)
    ? `<span class="run-source-actions">${previewAction}${downloadUrl ? `<a class="run-source-link" href="${escapeHtml(downloadUrl)}" download>下载</a>` : ""}</span>${reconstructed}`
    : `<span class="run-source-unavailable">未归档</span>`;
  return `<span class="run-source-ref" title="${escapeHtml(run?.source_name || sourceName)}">原始文件 · ${escapeHtml(sourceName)} ${actions}</span>`;
}

function renderRunSourceSummary() {
  Object.entries(RUN_SOURCE_META).forEach(([kind, meta]) => {
    if (!meta.countId) return;
    const target = $(`#${meta.countId}`);
    if (target) {
      target.textContent = String(state.modelRuns.filter((run) => run.kind === kind).length);
    }
  });
}

function runOwner(run) {
  return run.created_by || run.declared_author || "";
}

function runPeople() {
  const values = new Set();
  state.modelRuns.forEach((run) => {
    const owner = runOwner(run);
    if (owner) values.add(owner);
  });
  return [...values].sort((left, right) => left.localeCompare(right, "zh-CN"));
}

function runBatchName(run) {
  const experiment = run.metadata?.experiment || {};
  const platformBatch = run.metadata?.platform_batch || {};
  const sourceFile = String(run.source_name || "").split(/[\\/]/).pop() || "";
  return (
    platformBatch.batch_name ||
    experiment.run_id ||
    experiment.experiment_id ||
    sourceFile.replace(/\.(json|csv|xlsx|xlsm)$/i, "") ||
    "未命名批次"
  );
}

function renderRunFilters() {
  const select = $("#runPersonFilter");
  if (!select) return;
  const previous = select.value;
  const mine = state.session.username;
  const people = runPeople();
  select.innerHTML = [
    '<option value="">全部人员</option>',
    mine ? `<option value="__me__">我的 · ${escapeHtml(mine)}</option>` : "",
    ...people.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`),
  ].join("");
  select.value =
    previous === "__me__" || people.includes(previous)
      ? previous
      : "";
}

function activeRun() {
  return state.modelRuns.find((run) => run.id === state.selectedRunId);
}

function renderActiveRun(overview = null) {
  const run = activeRun();
  const activeName = $("#activeRunName");
  const activeMeta = $("#activeRunMeta");
  if (activeName) activeName.textContent = run?.name || "尚未选择模型 Run";
  const runSelect = $("#modelRunFilter");
  if (runSelect) {
    runSelect.title = run
      ? `${run.name} · ${run.baseline_prediction_count ?? 0} 条 · 错 ${run.failure_count ?? 0}`
      : "尚未选择模型 Run";
  }
  if (!run) {
    if (activeMeta) {
      activeMeta.textContent =
        state.config?.trail_sync?.message ||
        "选择团队 Run、创建 Trail 只读快照，或导入 JSON / CSV / XLSX";
    }
    return;
  }
  const coverage = overview?.predictions ?? run.baseline_prediction_count ?? 0;
  const failures = overview?.model_failures ?? run.failure_count ?? 0;
  const reviewed = overview?.reviewed_failures;
  const sourceLabel = runSourceMeta(run).label;
  if (activeMeta) {
    activeMeta.textContent =
      `${coverage} / ${state.config?.baseline?.count || "—"} 覆盖 · ${failures} 条判断失败` +
      `${reviewed === undefined ? "" : ` · ${reviewed} 条已复核`}` +
      ` · ${sourceLabel}`;
  }
}

function renderRunManager() {
  const list = $("#modelRunList");
  if (!list) return;
  const search = ($("#runSearchInput")?.value || "").trim().toLowerCase();
  const personValue = $("#runPersonFilter")?.value || "";
  const person = personValue === "__me__" ? state.session.username : personValue;
  const kind = $("#runKindFilter")?.value || "";
  const filteredRuns = state.modelRuns.filter((run) => {
    const personMatch = !person || runOwner(run) === person;
    const searchText = [
      run.name,
      runBatchName(run),
      run.source_name,
      run.created_by,
      run.declared_author,
      run.metadata?.model_name,
      run.metadata?.prompt_version,
      run.metadata?.external_username,
    ]
      .join(" ")
      .toLowerCase();
    return personMatch && (!kind || run.kind === kind) && (!search || searchText.includes(search));
  });
  const totalCoverage = filteredRuns.reduce(
    (sum, run) => sum + Number(run.baseline_prediction_count || 0),
    0
  );
  $("#runManagerSummary").textContent =
    `${filteredRuns.length} / ${state.modelRuns.length} 个 Run · ${totalCoverage} 条预测`;
  if (!filteredRuns.length) {
    list.innerHTML = '<div class="no-asset">当前筛选下没有 Run。</div>';
    return;
  }
  const baselineCount = Number(state.config?.baseline?.count || 0);
  list.innerHTML = filteredRuns
    .map(
      (run) => {
        const coverage = Number(run.baseline_prediction_count || 0);
        const coverageLabel =
          baselineCount && coverage >= baselineCount ? "全量覆盖" : "部分覆盖";
        const owner = runOwner(run) || "未记录";
        const batch = runBatchName(run);
        const modelName = run.metadata?.model_name || run.metadata?.experiment?.model_name || "";
        const promptVersion = run.metadata?.prompt_version || run.metadata?.experiment?.prompt_version || "";
        const externalUser = run.metadata?.external_username || "";
        const sourceMeta = runSourceMeta(run);
        const ownerTitle = run.created_by
          ? `提交人：${run.created_by}${run.declared_author && run.declared_author !== run.created_by ? `；结果包作者：${run.declared_author}` : ""}`
          : run.declared_author
            ? `结果包作者：${run.declared_author}`
            : "人员信息未记录";
        return `<article class="run-row ${run.id === state.selectedRunId ? "active" : ""}">
        <div class="run-row-main">
          <div class="run-row-title">
            <strong>${escapeHtml(run.name)}</strong>
            <span class="run-source-badge ${sourceMeta.className}" title="${escapeHtml(sourceMeta.description)}">${escapeHtml(sourceMeta.label)}</span>
            <span class="run-coverage-badge">${coverageLabel}</span>
          </div>
          <div class="run-row-meta">
            <span title="${escapeHtml(ownerTitle)}">人员 · <b class="run-meta-value">${escapeHtml(owner)}</b></span>
            <span title="${escapeHtml(run.source_name || "")}">批次 · <b class="run-meta-value">${escapeHtml(batch)}</b></span>
            ${modelName ? `<span>模型 · ${escapeHtml(modelName)}</span>` : ""}
            ${promptVersion ? `<span>Prompt · ${escapeHtml(promptVersion)}</span>` : ""}
            ${externalUser && externalUser !== owner ? `<span>平台用户 · ${escapeHtml(externalUser)}</span>` : ""}
            <span>${runSourceReference(run)}</span>
            <span>${coverage} / ${state.config?.baseline?.count || "—"} 条</span>
            <span class="run-failure-count">错误 ${run.failure_count ?? 0}</span>
            <span>${formatTime(run.created_at)}</span>
          </div>
        </div>
        <div class="run-row-actions">
          <button class="button ${run.id === state.selectedRunId ? "button-primary" : "button-quiet"}" type="button" data-use-run="${escapeHtml(run.id)}">${run.id === state.selectedRunId ? "当前 Review" : "打开 Review"}</button>
          ${run.is_default ? '<button class="button button-quiet" type="button" disabled title="先切换团队默认 Run 才能删除">默认 Run</button>' : `<button class="button button-danger" type="button" data-delete-run="${escapeHtml(run.id)}">删除</button>`}
        </div>
      </article>`;
      }
    )
    .join("");
  list.querySelectorAll("[data-use-run]").forEach((button) => {
    button.addEventListener("click", () => useModelRun(button.dataset.useRun));
  });
  list.querySelectorAll("[data-preview-run]").forEach((button) => {
    button.addEventListener("click", () => openSourcePreview(button.dataset.previewRun));
  });
  list.querySelectorAll("[data-delete-run]").forEach((button) => {
    button.addEventListener("click", () => deleteModelRun(button.dataset.deleteRun));
  });
}

async function useModelRun(runId) {
  if (!state.modelRuns.some((run) => run.id === runId)) return;
  state.selectedRunId = runId;
  // Keep the established failure-focused Review default.  Missing
  // predictions are represented as NONE by the comparison overlay rather than
  // dropping those Issues from the immutable baseline.
  state.reviewComparisonStatus = "mismatch";
  state.failureOnly = true;
  state.selectedId = "";
  state.casePage = 1;
  state.galleryScrollY = 0;
  $("#modelRunFilter").value = runId;
  setReviewComparisonStatus("mismatch", { hasRun: true });
  renderActiveRun();
  renderRunManager();
  await Promise.all([loadCases({ keepSelection: false, page: 1 }), loadClusters(), loadOverview()]);
  navigatePage("review");
}

async function deleteModelRun(runId) {
  const run = state.modelRuns.find((item) => item.id === runId);
  if (!run) return;
  if (run.is_default) {
    showToast("当前团队默认 Run 不能删除，请先切换默认 Run。", true);
    return;
  }
  const confirmed = window.confirm(
    `确认删除模型 Run「${run.name}」？\n\n该操作会删除该 Run 的模型输出和来源归档，不会删除 0508 GT、Issue 或人工 review，且不可恢复。`
  );
  if (!confirmed) return;
  const button = document.querySelector(`[data-delete-run="${CSS.escape(runId)}"]`);
  if (button) {
    button.disabled = true;
    button.textContent = "删除中…";
  }
  try {
    const result = await api(`/api/model-runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
    if (state.selectedRunId === runId) {
      state.selectedRunId = "";
      state.reviewComparisonStatus = "all";
      state.failureOnly = false;
    }
    await Promise.all([loadRuns({ preserveEmpty: true }), loadOverview(), loadCases(), loadClusters()]);
    showToast(`已删除 Run「${result.deleted?.name || run.name}」${result.source_deleted ? "及来源文件" : ""}。`);
  } catch (error) {
    showToast(error.message, true);
    if (button?.isConnected) {
      button.disabled = false;
      button.textContent = "删除";
    }
  }
}
