/* ra_triage_dashboard/static/js/analysis.js
 * Review reason analysis page
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
async function loadClusters() {
  const params = new URLSearchParams();
  if (state.selectedRunId) params.set("model_run_id", state.selectedRunId);
  params.set("failure_only", String(Boolean(state.failureOnly && state.selectedRunId)));
  const annotationAuthor = $("#reviewerFilter")?.value;
  if (annotationAuthor) params.set("annotation_author", annotationAuthor);
  const list = $("#clusterList");
  if (!list) return;
  const data = await api(`/api/review-clusters?${params.toString()}`);
  if (!(data.items || []).length) {
    list.innerHTML = '<span class="muted">标注缺失信息后，这里会按错误模式自动聚类。</span>';
    return;
  }
  list.innerHTML = data.items
    .map(
      (item) => `<button type="button" class="cluster-chip ${state.clusterKey === item.key ? "active" : ""}" data-cluster-key="${escapeHtml(item.key)}">
        <span>${escapeHtml(evidenceLabel(item.key))}</span><b>${item.count}</b>
      </button>`
    )
    .join("");
  list.querySelectorAll("[data-cluster-key]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.clusterKey = button.dataset.clusterKey === state.clusterKey ? "" : button.dataset.clusterKey;
      await reloadReviewGallery({ includeOverview: false });
    });
  });
}

function safeSameOriginReviewUrl(url) {
  try {
    const parsed = new URL(String(url || ""), window.location.origin);
    const pathname = stripBasePath(parsed.pathname);
    if (parsed.origin !== window.location.origin || pathname !== "/review") return "";
    return `${withBase(pathname)}${parsed.search}`;
  } catch {
    return "";
  }
}

function reviewStatusLabel(status) {
  return (
    {
      pending: "待复核",
      reviewed: "已 Review",
      needs_gt_review: "GT 待复核",
    }[status] || status || "未记录"
  );
}

function analysisRequestOptions() {
  const runId = $("#analysisRunFilter")?.value || "";
  return currentAnalysisRouteOptions({
    runId,
    comparisonStatus: runId ? checkedAnalysisComparisonStatus() : "all",
  });
}

function renderAnalysisClusterList(items, targetSelector, kind) {
  const target = $(targetSelector);
  if (!target) return;
  if (!items.length) {
    target.innerHTML =
      '<div class="analysis-empty">当前筛选范围内还没有可统计的聚类。</div>';
    return;
  }
  const activeValue =
    $("#analysisEvidenceFilter")?.value || "";
  target.innerHTML = items
    .map((item) => {
      const percentage = Math.round(Number(item.share || 0) * 1000) / 10;
      const width = Math.max(2, Math.min(100, percentage));
      return `<button class="analysis-cluster-row ${activeValue === item.key ? "active" : ""}" type="button"
          data-analysis-cluster-kind="${kind}" data-analysis-cluster-key="${escapeHtml(item.key)}"
          title="${escapeHtml(item.description || item.label)}">
        <span class="analysis-cluster-copy">
          <strong>${escapeHtml(item.label)}</strong>
          <small>${escapeHtml(item.description || "")}</small>
        </span>
        <span class="analysis-cluster-value"><b>${item.count}</b><small>${percentage}%</small></span>
        <span class="analysis-bar-track" aria-hidden="true"><span style="width:${width}%"></span></span>
      </button>`;
    })
    .join("");
  target.querySelectorAll("[data-analysis-cluster-key]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.analysisClusterKind === "evidence") {
        const select = $("#analysisEvidenceFilter");
        select.value = select.value === button.dataset.analysisClusterKey
          ? ""
          : button.dataset.analysisClusterKey;
      }
      state.reviewAnalysis.page = 1;
      showPage("analysis", { historyMode: "push" });
      loadReviewReasonAnalysis().catch((error) => showToast(error.message, true));
    });
  });
}

function renderAnalysisConfusion(data) {
  const target = $("#analysisConfusionMatrix");
  const summary = $("#analysisConfusionSummary");
  if (!target || !summary) return;
  const run = data.scope?.model_run;
  const confusion = data.confusion || {};
  if (!run) {
    summary.textContent = "选择 Model Run 后显示混淆统计";
    target.innerHTML = '<div class="analysis-empty">尚未选择可比较的 Model Run。</div>';
    return;
  }
  summary.textContent =
    `${run.name} · ` +
    `MATCH ${confusion.matches || 0} · ` +
    `MISMATCH ${confusion.mismatches || 0} · ` +
    `NONE ${confusion.none || 0}`;
  const labels = confusion.model_labels || confusion.labels || LABELS;
  if (!confusion.total) {
    target.innerHTML =
      '<div class="analysis-empty">当前 Review 切片没有可统计的模型判断结果。</div>';
    return;
  }
  target.innerHTML = `<table class="analysis-confusion-table">
    <thead><tr><th>GT ↓ / 模型 →</th>${labels
      .map((label) => `<th>${escapeHtml(label)}</th>`)
      .join("")}<th>合计</th></tr></thead>
    <tbody>${(confusion.rows || [])
      .map(
        (row) => `<tr>
          <th>${escapeHtml(row.gt_label)}</th>
          ${(row.cells || [])
            .map(
              (cell) => {
                const cellClass =
                  cell.model_label === "NONE"
                    ? "confusion-none"
                    : cell.model_label === row.gt_label
                      ? "confusion-match"
                      : cell.count
                        ? "confusion-mismatch"
                        : "";
                return `<td class="${cellClass}">${cell.count}</td>`;
              }
            )
            .join("")}
          <td class="confusion-total">${row.total}</td>
        </tr>`
      )
      .join("")}</tbody>
  </table>`;
}

function renderAnalysisCases(data) {
  const target = $("#analysisCaseList");
  const items = data.items || [];
  $("#analysisCaseSummary").textContent =
    `${data.total || 0} 条最新 Review · 当前显示 ${items.length} 条`;
  if (!items.length) {
    target.innerHTML =
      '<div class="analysis-empty">当前筛选下没有 Review 原因明细。</div>';
  } else {
    target.innerHTML = items
      .map((item) => {
        const annotation = item.annotation || {};
        const prediction = item.prediction || {};
        const reviewUrl = safeSameOriginReviewUrl(item.review_url);
        const voyagerUrl = safeUrl(item.voyager_issue_url);
        const issueId = escapeHtml(item.issue_id);
        const sceneLabel = item.title || item.scenario || "未填写场景";
        const issueIdMarkup = voyagerUrl
          ? `<a class="analysis-issue-link" href="${escapeHtml(voyagerUrl)}" target="_blank" rel="noreferrer" title="在 Voyager 中打开 ${issueId}">${issueId}</a>`
          : `<strong>${issueId}</strong>`;
        const comparisonStatus = normalizedAnalysisComparisonStatus(
          item.comparison_status,
          ""
        );
        const comparisonMeta = ANALYSIS_COMPARISON_META[comparisonStatus];
        const comparisonBadge = comparisonMeta
          ? `<span class="analysis-comparison-badge comparison-${comparisonStatus}" title="${escapeHtml(comparisonMeta.description)}">${escapeHtml(comparisonMeta.label)}${
              comparisonStatus === "none" ? " · 未预测" : ""
            }</span>`
          : "";
        const confidence =
          prediction.confidence === null || prediction.confidence === undefined
            ? ""
            : ` · ${(Number(prediction.confidence) * 100).toFixed(1)}%`;
        const evidenceChips = (annotation.missing_evidence || [])
          .map(
            (key) =>
              `<span class="analysis-chip evidence-chip">${escapeHtml(evidenceLabel(key))}</span>`
          )
          .join("");
        const tagChips = (annotation.tags || [])
          .map((key) => `<span class="analysis-chip tag-chip">${escapeHtml(tagLabel(key))}</span>`)
          .join("");
        return `<article class="analysis-case-row">
          <div class="analysis-case-identity">
            ${issueIdMarkup}
            <span title="${escapeHtml(sceneLabel)}">${escapeHtml(sceneLabel)}</span>
          </div>
          <div class="analysis-case-labels">
            ${comparisonBadge}
            <span title="0508 baseline GT">GT ${labelBadge(item.gt_label)}</span>
            <button class="analysis-model-history-button" type="button"
              data-analysis-model-history="${issueId}"
              title="查看此 Issue 的全部评测 Run 输出历史"
              aria-label="查看 ${issueId} 的评测 Run 输出历史">
              <span>模型</span>${labelBadge(prediction.label, "未输出")}${escapeHtml(confidence)}
            </button>
          </div>
          <div class="analysis-case-reason">
            <strong class="${annotation.note ? "" : "reason-empty"}">${escapeHtml(annotation.note || "未填写“模型为什么判错”")}</strong>
            ${prediction.reason ? `<p>模型说明：${escapeHtml(prediction.reason)}</p>` : ""}
            <div class="analysis-chip-list">${tagChips}${evidenceChips}</div>
          </div>
          <div class="analysis-case-meta">
            <span>${escapeHtml(annotation.author || "未记录复核人")}${annotation.author_verified ? " · SSO" : ""}</span>
            <span>${escapeHtml(reviewStatusLabel(annotation.review_status))} · ${formatTime(annotation.created_at)}</span>
            <span class="analysis-case-actions">
              ${reviewUrl ? `<a class="text-link" href="${escapeHtml(reviewUrl)}" title="打开问题详情与 Review">问题详情</a>` : ""}
            </span>
          </div>
        </article>`;
      })
      .join("");
    target.querySelectorAll("[data-analysis-model-history]").forEach((button) => {
      button.addEventListener("click", async () => {
        if (button.getAttribute("aria-busy") === "true") return;
        button.setAttribute("aria-busy", "true");
        try {
          const caseData = await api(
            `/api/cases/${encodeURIComponent(button.dataset.analysisModelHistory)}`
          );
          openHistoryDialog("model", caseData);
        } catch (error) {
          showToast(error.message, true);
        } finally {
          button.removeAttribute("aria-busy");
        }
      });
    });
  }
  const page = Number(data.page || 1);
  const pageCount = Number(data.page_count || 1);
  $("#analysisPageSummary").textContent = `${page} / ${pageCount}`;
  $("#analysisPagePrevious").disabled = page <= 1;
  $("#analysisPageNext").disabled = page >= pageCount;
}

function renderReviewReasonAnalysis(data) {
  const summary = data.summary || {};
  state.reviewAnalysis.page = Number(data.page || 1);
  $("#analysisReviewCount").textContent = summary.latest_reviews ?? 0;
  $("#analysisReasonCount").textContent = summary.with_reason ?? 0;
  $("#analysisEmptyReasonCount").textContent = `${summary.empty_reason ?? 0} 条未填写`;
  $("#analysisEvidenceCount").textContent = summary.with_structured_evidence ?? 0;
  const run = data.scope?.model_run;
  const comparisonStatus = normalizedAnalysisComparisonStatus(
    data.scope?.comparison_status,
    "all"
  );
  const comparisonMeta = ANALYSIS_COMPARISON_META[comparisonStatus];
  $("#analysisReviewScope").textContent = run
    ? `${run.name}${comparisonStatus === "all" ? "" : ` · ${comparisonMeta.label}`}`
    : "全部最新 Review";
  renderAnalysisClusterList(
    data.evidence_clusters || [],
    "#analysisEvidenceClusters",
    "evidence"
  );
  renderAnalysisConfusion(data);
  renderAnalysisCases(data);
}

async function loadReviewReasonAnalysis() {
  const requestSeq = ++state.reviewAnalysis.requestSeq;
  const options = analysisRequestOptions();
  const params = new URLSearchParams();
  if (options.runId) params.set("model_run_id", options.runId);
  params.set(
    "comparison",
    options.runId
      ? normalizedAnalysisComparisonStatus(options.comparisonStatus)
      : "all"
  );
  if (options.annotationAuthor) params.set("annotation_author", options.annotationAuthor);
  if (options.reviewStatus) params.set("review_status", options.reviewStatus);
  if (options.gtLabel) params.set("gt_label", options.gtLabel);
  if (options.modelLabel) params.set("model_label", options.modelLabel);
  if (options.missingEvidence) params.set("missing_evidence", options.missingEvidence);
  if (options.sceneTag) params.set("scene_tag", options.sceneTag);
  if (options.triggerTag) params.set("trigger_tag", options.triggerTag);
  if (options.egressTag) params.set("egress_tag", options.egressTag);
  if (options.search) params.set("search", options.search);
  params.set("page", String(Math.max(1, Number(options.page) || 1)));
  params.set("page_size", String(state.reviewAnalysis.pageSize));
  $("#analysisCaseSummary").textContent = "正在加载最新 Review…";
  const data = await api(`/api/review-reason-analysis?${params.toString()}`);
  if (requestSeq !== state.reviewAnalysis.requestSeq) return;
  state.reviewAnalysis.data = data;
  renderReviewReasonAnalysis(data);
}

function downloadReviewAnalysis(format) {
  const options = analysisRequestOptions();
  const params = new URLSearchParams({ format });
  if (options.runId) params.set("model_run_id", options.runId);
  params.set(
    "comparison",
    options.runId
      ? normalizedAnalysisComparisonStatus(options.comparisonStatus)
      : "all"
  );
  if (options.annotationAuthor) params.set("annotation_author", options.annotationAuthor);
  if (options.reviewStatus) params.set("review_status", options.reviewStatus);
  if (options.gtLabel) params.set("gt_label", options.gtLabel);
  if (options.modelLabel) params.set("model_label", options.modelLabel);
  if (options.missingEvidence) params.set("missing_evidence", options.missingEvidence);
  if (options.sceneTag) params.set("scene_tag", options.sceneTag);
  if (options.triggerTag) params.set("trigger_tag", options.triggerTag);
  if (options.egressTag) params.set("egress_tag", options.egressTag);
  if (options.search) params.set("search", options.search);
  const link = document.createElement("a");
  link.href = withBase(`/api/review-reason-analysis/export?${params.toString()}`);
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function applyAnalysisComparisonSelection() {
  const previousRunId = state.selectedRunId;
  const previousFailureOnly = state.failureOnly;
  const previousComparisonStatus = state.reviewAnalysis.comparisonStatus;
  const runId = $("#analysisRunFilter").value;
  state.selectedRunId = state.modelRuns.some((run) => run.id === runId) ? runId : "";
  state.reviewAnalysis.comparisonStatus = state.selectedRunId
    ? checkedAnalysisComparisonStatus()
    : "all";
  state.failureOnly = Boolean(
    state.selectedRunId &&
      state.reviewAnalysis.comparisonStatus === "mismatch"
  );
  if (
    previousRunId !== state.selectedRunId ||
    previousFailureOnly !== state.failureOnly ||
    previousComparisonStatus !== state.reviewAnalysis.comparisonStatus
  ) {
    state.reviewQueueStale = true;
  }
  $("#modelRunFilter").value = state.selectedRunId;
  setReviewComparisonStatus(state.reviewComparisonStatus, {
    hasRun: Boolean(state.selectedRunId),
  });
  renderActiveRun();
  renderRunManager();
}

async function reloadReviewAnalysis({ historyMode = "push" } = {}) {
  applyAnalysisComparisonSelection();
  showPage("analysis", { historyMode });
  await Promise.all([loadReviewReasonAnalysis(), loadOverview()]);
}

function scheduleAnalysisFilterReload(delay = 0) {
  if (state.reviewAnalysis.filterTimer) {
    window.clearTimeout(state.reviewAnalysis.filterTimer);
  }
  state.reviewAnalysis.filterTimer = window.setTimeout(() => {
    state.reviewAnalysis.filterTimer = null;
    state.reviewAnalysis.page = 1;
    reloadReviewAnalysis({ historyMode: "replace" }).catch((error) => {
      showToast(error.message, true);
    });
  }, Math.max(0, Number(delay) || 0));
}

async function changeAnalysisPage(delta) {
  const data = state.reviewAnalysis.data || {};
  const target = Math.max(
    1,
    Math.min(Number(data.page_count || 1), state.reviewAnalysis.page + delta)
  );
  if (target === state.reviewAnalysis.page) return;
  state.reviewAnalysis.page = target;
  showPage("analysis", { historyMode: "push" });
  await loadReviewReasonAnalysis();
  window.scrollTo({ top: $("#analysisCaseList").offsetTop - 72, behavior: "smooth" });
}

function clearDetail({ showGallery = true } = {}) {
  state.selectedId = "";
  state.selectedCase = null;
  state.caseRequestSeq += 1;
  $("#detailPane").innerHTML = `
    <div class="empty-state">
      <div class="empty-glyph" aria-hidden="true">+</div>
      <h2>正在准备 Issue 详情</h2>
      <p>从筛选结果中打开一个 Issue 后，这里会显示 BEV / Camera 与模型输出。</p>
    </div>`;
  $("#reviewPane").innerHTML = `
    <div class="review-placeholder"><h2>人工复核</h2><p>选择 Issue 后记录结论和模型遗漏的关键信息。</p></div>`;
  renderCaseNavigation();
  if (showGallery) setReviewView("");
}
