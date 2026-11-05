/* analysis.js
 * Review analysis queries, case table, filters and pagination.
 * Classic script; shared globals are initialized before bind-bootstrap.js.
 */

function selectedAnalysisExclusionFilter() {
  const values = parseFilterList(getMultiFilterValues($("#analysisExclusionFilter")));
  if (values.length === 1 && ["included", "excluded"].includes(values[0])) {
    return values[0];
  }
  return "all";
}

function analysisExclusionLabel(value) {
  return {
    all: uiText("全部（含问题排除）", "All (including shielded)"),
    included: uiText("不含问题排除", "Exclude shielded cases"),
    excluded: uiText("仅问题排除", "Only shielded cases"),
  }[value] || uiText("全部（含问题排除）", "All (including shielded)");
}

function renderAnalysisWorkAgreementPicker(selected = "") {
  const picker = $("#analysisWorkAgreementPicker");
  const value = selected || $("#analysisWorkAgreementFilter")?.value || "all";
  populateUiSelect(
    picker,
    [
      { value: "all", label: uiText("全部", "All") },
      { value: "pending", label: uiText("未完成", "Pending") },
      { value: "agreed", label: uiText("一致", "Agreed") },
      { value: "conflict", label: uiText("冲突", "Conflict") },
    ],
    value,
  );
  bindUiSelect(picker, { maxHeight: 240, maxWidth: 260 });
}

function renderAnalysisCommentStatePicker(selected = "") {
  const picker = $("#analysisCommentStatePicker");
  const value = selected || $("#analysisCommentStateFilter")?.value || "all";
  populateUiSelect(picker, [
    { value: "all", label: uiText("全部评论", "All comments") },
    { value: "with", label: uiText("有评论", "With comments") },
    { value: "without", label: uiText("无评论", "Without comments") },
  ], value);
  bindUiSelect(picker, { maxHeight: 220, maxWidth: 240 });
}

async function loadClusters() {
  const params = new URLSearchParams();
  if (state.selectedRunId) params.set("model_run_id", state.selectedRunId);
  params.set("failure_only", String(Boolean(state.failureOnly && state.selectedRunId)));
  const annotationAuthor = joinFilterList(
    typeof reviewerFilterSelection === "function"
      ? reviewerFilterSelection("review")
      : getMultiFilterValues($("#reviewerFilter"))
  );
  if (annotationAuthor) params.set("annotation_author", annotationAuthor);
  if (state.activePage === "review" && state.reviewWorkSplitId) {
    params.set("work_split_id", state.reviewWorkSplitId);
  }
  // The exclusion slice belongs to 原因聚类/分析.  Review's quick cluster
  // chips should keep the neutral all-inclusive scope even if a previous
  // analysis page selection is still present in the shared DOM.
  const exclusion = state.activePage === "analysis"
    ? selectedAnalysisExclusionFilter()
    : "all";
  if (exclusion !== "all") params.set("exclusion", exclusion);
  const list = $("#clusterList");
  if (!list) return;
  const data = await api(`/api/review-clusters?${params.toString()}`);
  if (!(data.items || []).length) {
    list.innerHTML = `<span class="muted">${escapeHtml(t("analysis.cluster_hint"))}</span>`;
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
      pending: uiText("待开始", "Pending"),
      in_progress: uiText("待复核", "Needs review"),
      completed: uiText("已完成", "Completed"),
      blocked_by_label: uiText("待复核", "Needs review"),
      reviewed: t("status.matches_gt"),
      needs_gt_review: t("status.needs_gt"),
    }[status] || status || t("status.recorded")
  );
}

function analysisRequestOptions() {
  const runId = $("#analysisRunFilter")?.value || "";
  return currentAnalysisRouteOptions({
    runId,
    comparisonStatus: runId ? checkedAnalysisComparisonStatus() : "all",
    exclusion: selectedAnalysisExclusionFilter(),
    workAgreement: $("#analysisWorkAgreementFilter")?.value || "all",
    workSplitId: state.reviewAnalysis.workSplitId || "",
  });
}

/** Shared query builder for analysis JSON + export endpoints. */
function buildAnalysisQueryParams({ format = "", includePagination = true } = {}) {
  const options = analysisRequestOptions();
  const params = new URLSearchParams();
  if (format) params.set("format", format);
  if (options.runId) params.set("model_run_id", options.runId);
  params.set(
    "comparison",
    options.runId
      ? comparisonStatusParam(options.comparisonStatus || "all")
      : "all"
  );
  const fields = [
    ["issue_ids", joinFilterList(options.issueIds)],
    ["annotation_author", joinFilterList(options.annotationAuthor)],
    ["review_status", joinFilterList(options.reviewStatus)],
    ["label_state", joinFilterList(options.labelStates)],
    ["gt_relation", joinFilterList(options.gtRelations)],
    ["gt_label", joinFilterList(options.gtLabel)],
    ["model_label", joinFilterList(options.modelLabel)],
    ["missing_evidence", joinFilterList(options.missingEvidence)],
    ["scene_tag", joinFilterList(options.sceneTag)],
    ["trigger_tag", joinFilterList(options.triggerTag)],
    ["egress_tag", joinFilterList(options.egressTag)],
    ["search", options.search || ""],
    ["comment_state", options.commentState === "all" ? "" : options.commentState],
    ["comment_search", options.commentSearch || ""],
  ];
  if (options.exclusion && options.exclusion !== "all") {
    params.set("exclusion", options.exclusion);
  }
  if (options.workAgreement && options.workAgreement !== "all") {
    params.set("work_agreement", options.workAgreement);
  }
  if (options.workSplitId) params.set("work_split_id", options.workSplitId);
  for (const [key, value] of fields) {
    if (value) params.set(key, value);
  }
  if (includePagination) {
    params.set("page", String(Math.max(1, Number(options.page) || 1)));
    params.set("page_size", String(state.reviewAnalysis.pageSize));
  }
  appendBaselineParams(params);
  return params;
}

function renderAnalysisCases(data) {
  const target = $("#analysisCaseList");
  const items = data.items || [];
  $("#analysisCaseSummary").textContent =
    t("analysis.case_summary", { total: data.total || 0, n: items.length });
  if (!items.length) {
    target.innerHTML =
      `<div class="analysis-empty">${escapeHtml(t("analysis.case_empty"))}</div>`;
  } else {
    target.innerHTML = items
      .map((item) => {
        const annotation = item.annotation || {};
        const prediction = item.prediction || {};
        const expectedOutput = annotationExpectedOutput(annotation);
        const reviewUrl = safeSameOriginReviewUrl(item.review_url);
        const voyagerUrl = safeUrl(item.voyager_issue_url);
        const issueId = escapeHtml(item.issue_id);
        const sceneLabel = item.title || item.scenario || t("analysis.no_scene");
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
              comparisonStatus === "none" ? t("analysis.no_pred") : ""
            }</span>`
          : "";
        const multi = item.multi_review || null;
        const multiLabel = multi
          ? ({ pending: "未完成", agreed: "一致", conflict: "冲突" }[multi.agreement] || "多人复核")
          : "";
        const multiBadge = multi
          ? `<span class="analysis-comparison-badge comparison-${multi.agreement === "conflict" ? "mismatch" : multi.agreement === "agreed" ? "match" : "none"}">${escapeHtml(multiLabel)} · ${Number(multi.completed_count || 0)}/${Number(multi.assigned_count || 0)}</span>`
          : "";
        const multiDistribution = multi
          ? Object.entries(multi.output_counts || {})
              .map(([label, count]) => `${label} ${count}`)
              .join(" · ")
          : "";
        const multiReviewerLines = multi
          ? (multi.reviews || [])
              .map((review) => `${review.username}：${review.expected_output || "待补充"}`)
              .join(" · ")
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
        const tagChips = (item.case_label_context?.tags || annotation.tags || [])
          .map((key) => {
            const catalogItem = reviewTagCatalogItem(key) || {};
            const section = String(catalogItem.section || "");
            const group = String(catalogItem.group || "");
            return `<span class="analysis-chip tag-chip"${section ? ` data-tag-section="${escapeHtml(section)}"` : ""}${group ? ` data-tag-group="${escapeHtml(group)}"` : ""}>${escapeHtml(tagLabel(key))}</span>`;
          })
          .join("");
        const discussionRunId = state.selectedRunId || annotation.model_run_id || "";
        return `<article class="analysis-case-row">
          <div class="analysis-case-identity">
            ${issueIdMarkup}
            <span title="${escapeHtml(sceneLabel)}">${escapeHtml(sceneLabel)}</span>
          </div>
          <div class="analysis-case-labels">
            ${comparisonBadge}
            ${multiBadge}
            <span title="${escapeHtml(`${baselineLabelForScope(item.baseline_scope)} GT`)}">GT ${labelBadge(item.gt_label)}</span>
            ${annotation.review_domain === "model_review" ? `<span title="模型判错复核状态"><span class="ui-lang-zh">模型复核</span><span class="ui-lang-en">Model review</span> ${escapeHtml(reviewStatusLabel(item.model_review_progress || annotation.model_review_status))}</span>` : `<span title="历史 Review 期望输出"><span class="ui-lang-zh">历史期望</span><span class="ui-lang-en">Legacy expected</span> ${labelBadge(expectedOutput, uiText("待补充", "Pending"))}</span>`}
            <button class="analysis-model-history-button" type="button"
              data-analysis-model-history="${issueId}"
              title="查看此 Issue 的全部评测 Run 输出历史"
              aria-label="查看 ${issueId} 的评测 Run 输出历史">
              <span>${escapeHtml(t("analysis.model"))}</span>${labelBadge(prediction.label, "未输出")}${escapeHtml(confidence)}
            </button>
          </div>
          <div class="analysis-case-reason">
            <strong class="${annotation.note ? "" : "reason-empty"}">${escapeHtml(annotation.note || t("analysis.empty_reason"))}</strong>
            ${prediction.reason ? `<p>${escapeHtml(t("analysis.model_note", { note: prediction.reason }))}</p>` : ""}
            ${multiDistribution ? `<p>多人结论：${escapeHtml(multiDistribution)}</p>` : ""}
            ${multiReviewerLines ? `<p>复核人：${escapeHtml(multiReviewerLines)}</p>` : ""}
            <div class="analysis-chip-list">${tagChips}${evidenceChips}</div>
          </div>
          <div class="analysis-case-meta">
            <span>${escapeHtml(annotation.author || "未记录复核人")}${annotation.author_verified ? " · SSO" : ""}</span>
            <span>${escapeHtml(reviewStatusLabel(item.model_review_progress || annotation.model_review_status || annotation.review_status))} · ${formatTime(annotation.created_at)}</span>
            <span class="analysis-case-actions">
              <button class="analysis-discussion-link" type="button" data-analysis-discussion="${issueId}" data-model-run-id="${escapeHtml(discussionRunId)}">评论</button>
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
    target.querySelectorAll("[data-analysis-discussion]").forEach((button) => {
      button.addEventListener("click", () => {
        openAnalysisDiscussion(button.dataset.analysisDiscussion, {
          runId: button.dataset.modelRunId || "",
          source: "analysis",
        }).catch((error) => {
          showToast(error.message, true);
        });
      });
    });
  }
  const page = Number(data.page || 1);
  const pageCount = Number(data.page_count || 1);
  const pageSize = CASE_PAGE_SIZES.includes(Number(data.page_size))
    ? Number(data.page_size)
    : state.reviewAnalysis.pageSize;
  state.reviewAnalysis.pageSize = pageSize;
  $("#analysisPageSummary").textContent = `${page} / ${pageCount}`;
  $("#analysisPageSize").value = String(pageSize);
  enhanceNativeUiSelect($("#analysisPageSize"));
  $("#analysisPagePrevious").disabled = page <= 1;
  $("#analysisPageNext").disabled = page >= pageCount;
  const jumpInput = $("#analysisPageJump");
  const jumpButton = $("#analysisPageJumpButton");
  if (jumpInput) {
    const focused = document.activeElement === jumpInput;
    jumpInput.min = "1";
    jumpInput.max = String(Math.max(1, pageCount));
    jumpInput.disabled = pageCount <= 1;
    jumpInput.dataset.pageCount = String(Math.max(1, pageCount));
    if (!focused) jumpInput.value = String(page);
  }
  if (jumpButton) jumpButton.disabled = pageCount <= 1;
}

function renderReviewReasonAnalysis(data, { animatePies = true } = {}) {
  const summary = data.summary || {};
  state.reviewAnalysis.page = Number(data.page || 1);
  $("#analysisReviewCount").textContent = summary.latest_reviews ?? 0;
  $("#analysisReasonCount").textContent = summary.with_reason ?? 0;
  $("#analysisEmptyReasonCount").textContent = uiText(
    `${summary.empty_reason ?? 0} 条未填写`,
    `${summary.empty_reason ?? 0} empty`
  );
  $("#analysisEvidenceCount").textContent = summary.with_structured_evidence ?? 0;
  const run = data.scope?.model_run;
  const comparisonStatus = comparisonStatusParam(
    data.scope?.comparison_status || "all"
  );
  const comparisonLabels = parseComparisonStatuses(comparisonStatus)
    .map((status) => ANALYSIS_COMPARISON_META[status]?.label || status)
    .join(" / ");
  const exclusion = data.scope?.exclusion || "all";
  const exclusionSuffix = exclusion === "all" ? "" : ` · ${analysisExclusionLabel(exclusion)}`;
  const reviewScope = run
    ? `${run.name}${comparisonStatus === "all" ? "" : ` · ${comparisonLabels}`}${exclusionSuffix}`
    : `${uiText("全部最新 Review", "All latest reviews")}${exclusionSuffix}`;
  const workSplitSuffix = data.scope?.work_split_id
    ? ` · ${uiText("本次任务新增", "This task only")}`
    : "";
  $("#analysisReviewScope").textContent = `${reviewScope}${workSplitSuffix}`;
  $("#analysisReviewScope").title = `${reviewScope}${workSplitSuffix}`;
  renderAnalysisReviewStatus(data);
  renderAnalysisGtStatus(data);
  renderAnalysisClusterPanels(data, { animatePies });
  renderAnalysisConfusion(data);
  renderAnalysisCases(data);
}

function paintAnalysisFromCache() {
  const data = state.reviewAnalysis?.data;
  if (!data) return false;
  // A cached response may belong to a different history entry (for example,
  // page 2 while popstate just restored page 1). Rendering that response must
  // not overwrite the pagination parsed from the current URL before the
  // revalidation request is built.
  const requestedPage = state.reviewAnalysis.page;
  const requestedPageSize = state.reviewAnalysis.pageSize;
  // Quiet repaint when revisiting the tab — pie spin is for real data loads only.
  renderReviewReasonAnalysis(data, { animatePies: false });
  state.reviewAnalysis.page = requestedPage;
  state.reviewAnalysis.pageSize = requestedPageSize;
  return true;
}

/**
 * Enter/revisit the analysis page: paint cache immediately (if any), then revalidate.
 * Used by sidebar navigation and popstate so tab switches stay snappy without blanking.
 */
async function enterAnalysisPage({ includeOverview = false } = {}) {
  if (!state.config) return;
  const painted = paintAnalysisFromCache();
  const loads = [loadReviewReasonAnalysis({ keepPainted: painted })];
  if (includeOverview) loads.push(loadOverview());
  await Promise.all(loads);
}

async function loadReviewReasonAnalysis({ keepPainted = false } = {}) {
  const pageContext = capturePageContext();
  const requestSeq = ++state.reviewAnalysis.requestSeq;
  try {
    await loadAnalysisWorkSplits();
  } catch (_error) {
    // Task-batch options are a secondary filter facet. A transient failure
    // must not block the analysis payload or an already URL-selected Split.
    renderAnalysisWorkSplitPicker(state.reviewAnalysis.workSplitId);
  }
  if (!isPageContextCurrent(pageContext) || requestSeq !== state.reviewAnalysis.requestSeq) return;
  const params = buildAnalysisQueryParams({ includePagination: true });
  // Keep existing paint when revisiting the tab; avoid blanking for a snappier switch.
  if (!keepPainted) {
    $("#analysisCaseSummary").textContent = "正在加载最新 Review…";
  }
  const data = await api(`/api/review-reason-analysis?${params.toString()}`);
  if (requestSeq !== state.reviewAnalysis.requestSeq || !isPageContextCurrent(pageContext)) return;
  state.reviewAnalysis.data = data;
  // Spin on first paint / filter reloads; skip when quietly revalidating a painted tab.
  renderReviewReasonAnalysis(data, { animatePies: !keepPainted });
}

function downloadReviewAnalysis(format) {
  const params = buildAnalysisQueryParams({
    format,
    includePagination: false,
  });
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
  if (state.activePage !== "analysis") return;
  applyAnalysisComparisonSelection();
  showPage("analysis", { historyMode });
  await Promise.all([loadReviewReasonAnalysis(), loadOverview()]);
}

function scheduleAnalysisFilterReload(delay = 0) {
  if (state.activePage !== "analysis") return;
  if (state.reviewAnalysis.filterTimer) {
    window.clearTimeout(state.reviewAnalysis.filterTimer);
  }
  // Persist controls before the debounce. Refreshing while typing or directly
  // after a checkbox change must restore the exact analysis view.
  state.reviewAnalysis.page = 1;
  persistCurrentAnalysisRoute({
    ...analysisRequestOptions(),
    page: 1,
  });
  const pageContext = capturePageContext();
  state.reviewAnalysis.filterTimer = window.setTimeout(() => {
    state.reviewAnalysis.filterTimer = null;
    if (!isPageContextCurrent(pageContext)) return;
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

async function jumpToAnalysisPage(raw) {
  const pageCount = Math.max(
    1,
    Number(state.reviewAnalysis.data?.page_count) || 1
  );
  const input = $("#analysisPageJump");
  const text = String(raw ?? "").trim();
  if (!/^\d+$/.test(text)) {
    showToast(t("analysis.jump_range", { total: pageCount }), true);
    if (input) {
      input.value = String(state.reviewAnalysis.page);
      input.focus();
      input.select();
    }
    return;
  }
  const target = Number.parseInt(text, 10);
  if (!Number.isFinite(target) || target < 1 || target > pageCount) {
    showToast(t("analysis.jump_range", { total: pageCount }), true);
    if (input) {
      input.value = String(state.reviewAnalysis.page);
      input.focus();
      input.select();
    }
    return;
  }
  if (target === state.reviewAnalysis.page) {
    if (input) input.value = String(target);
    return;
  }
  state.reviewAnalysis.page = target;
  showPage("analysis", { historyMode: "push" });
  await loadReviewReasonAnalysis();
  window.scrollTo({ top: $("#analysisCaseList").offsetTop - 72, behavior: "smooth" });
}

async function changeAnalysisPageSize(value) {
  const nextPageSize = CASE_PAGE_SIZES.includes(Number(value))
    ? Number(value)
    : DEFAULT_CASE_PAGE_SIZE;
  if (nextPageSize === state.reviewAnalysis.pageSize) return;
  state.reviewAnalysis.pageSize = nextPageSize;
  state.reviewAnalysis.page = 1;
  showPage("analysis", { historyMode: "push" });
  await loadReviewReasonAnalysis();
  window.scrollTo({ top: $("#analysisCaseList").offsetTop - 72, behavior: "smooth" });
}
