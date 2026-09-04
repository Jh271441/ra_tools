/* ra_triage_dashboard/static/js/routing.js
 * Theme, i18n, comparison filters, SPA routing
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */

function normalizedColorTheme(value) {
  return String(value || "").toLowerCase() === "light" ? "light" : "dark";
}

function applyColorTheme(theme, { persist = true } = {}) {
  state.colorTheme = normalizedColorTheme(theme);
  document.documentElement.dataset.colorTheme = state.colorTheme;
  if (persist) localStorage.setItem("ra-triage-color-theme", state.colorTheme);
  const toggle = $("#themeToggleButton");
  if (toggle) {
    const light = state.colorTheme === "light";
    toggle.textContent = light ? "☾" : "☀";
    const themeKey = light ? "topbar.theme_to_dark" : "topbar.theme_to_light";
    const themeLabel =
      typeof t === "function"
        ? t(themeKey)
        : light
          ? "切换到深色模式"
          : "切换到浅色模式";
    toggle.setAttribute("aria-label", themeLabel);
    toggle.title = themeLabel;
  }
  // Re-render theme/language-sensitive analysis visuals without a data reload.
  if (state.reviewAnalysis?.data && typeof renderAnalysisReviewStatus === "function") {
    renderAnalysisReviewStatus(state.reviewAnalysis.data);
  }
  if (state.reviewAnalysis?.data && typeof renderAnalysisClusterPanels === "function") {
    renderAnalysisClusterPanels(state.reviewAnalysis.data, { animatePies: false });
  }
}

function normalizedUiLanguage(value) {
  return String(value || "").toLowerCase() === "en" ? "en" : "zh";
}

function renderPageChrome() {
  const route = PAGE_ROUTES[state.activePage] || PAGE_ROUTES.review;
  const title = state.uiLanguage === "en" ? route.titleEn : route.titleZh;
  $("#pageTitle").textContent = title;
  document.title = `${title} · Manual Triage`;
}

/**
 * I18n locale switch: set BCP 47 lang, CSS dual-span toggle, catalog DOM bind,
 * then re-render language-sensitive dynamic widgets (filters, run pickers).
 */
function applyUiLanguage(language, { persist = true } = {}) {
  state.uiLanguage = normalizedUiLanguage(language);
  document.documentElement.dataset.uiLang = state.uiLanguage;
  document.documentElement.lang = state.uiLanguage === "en" ? "en" : "zh-CN";
  if (persist) localStorage.setItem("ra-triage-ui-language", state.uiLanguage);
  const toggle = $("#languageToggleButton");
  if (toggle) {
    const english = state.uiLanguage === "en";
    toggle.textContent = english ? "中文" : "EN";
    toggle.setAttribute(
      "aria-label",
      english ? t("topbar.lang_to_zh") : t("topbar.lang_to_en")
    );
    toggle.title = english ? t("topbar.lang_to_zh") : t("topbar.lang_to_en");
  }
  if (typeof applyDomI18n === "function") applyDomI18n(document);
  if (typeof applyI18nPlaceholders === "function") applyI18nPlaceholders(document);
  renderPageChrome();
  renderSystemStatus();
  applySidebarState();
  renderSession();
  // Dynamic filters / pickers rebuild option labels from the active catalog.
  const refreshers = [
    "renderReviewCatalogFilters",
    "renderAnalysisComparisonFilter",
    "renderAnalysisRunFilter",
    "renderAnalysisCatalogFilters",
    "renderReviewerFilter",
    "renderWorkAssigneeFilter",
    "renderTrailAttributeRunPicker",
    "renderTrailUpdateFilters",
  ];
  for (const name of refreshers) {
    try {
      if (typeof window[name] === "function") window[name]();
      else if (typeof globalThis[name] === "function") globalThis[name]();
    } catch (_) {
      /* page widgets may not be mounted */
    }
  }
  // Classic scripts share global scope — call by bare name when defined.
  try {
    if (typeof renderReviewCatalogFilters === "function") renderReviewCatalogFilters();
  } catch (_) {}
  try {
    if (typeof renderAnalysisComparisonFilter === "function") renderAnalysisComparisonFilter();
  } catch (_) {}
  try {
    if (typeof renderAnalysisRunFilter === "function" && state.modelRuns?.length) {
      renderAnalysisRunFilter();
    }
  } catch (_) {}
  try {
    if (typeof loadRuns === "function" && state.modelRuns?.length) {
      // Refresh model-run picker labels without network.
      const picker = $("#modelRunPicker");
      if (picker && typeof populateUiSelect === "function") {
        const runOptions = [
          { value: "", label: t("filter.no_run") },
          ...state.modelRuns.map((run) => {
            const tag = run.is_default ? t("runs.default_tag") : "";
            const inferred = Array.isArray(run.inferred_baseline_ids)
              ? run.inferred_baseline_ids.filter(Boolean)
              : [];
            const setHint = inferred.length ? ` · ${inferred.join("+")}` : "";
            return {
              value: run.id,
              label: `${tag}${run.name}${setHint} · ${t("runs.set_count")} ${run.baseline_prediction_count ?? 0} · ${t("runs.err_count")} ${run.failure_count ?? 0}`,
            };
          }),
        ];
        populateUiSelect(picker, runOptions, state.selectedRunId || "");
      }
      // Keep empty-option labels in sync with locale.
      const emptySummary = $("#modelRunPickerSummary");
      if (emptySummary && !state.selectedRunId) emptySummary.textContent = t("filter.no_run");
      const analysisEmpty = $("#analysisRunPickerSummary");
      if (analysisEmpty && !state.analysis?.runId) {
        // only if native empty selected
        const native = $("#analysisRunFilter");
        if (native && !native.value) analysisEmpty.textContent = t("filter.no_overlay_run");
      }
    }
  } catch (_) {}
  document.querySelectorAll(".multi-filter").forEach((root) => {
    if (typeof updateMultiFilterSummary === "function") updateMultiFilterSummary(root);
  });
  // Gallery / analysis summaries use catalog when re-rendered.
  try {
    if (typeof renderCasePagination === "function") renderCasePagination();
  } catch (_) {}
  try {
    if (typeof updateFilteredPredictionButton === "function") updateFilteredPredictionButton();
  } catch (_) {}
  try {
    if (typeof renderSystemStatus === "function") renderSystemStatus();
  } catch (_) {}
  try {
    if (typeof renderAccessUsers === "function" && state.accessUsers) renderAccessUsers();
  } catch (_) {}
  try {
    if (typeof renderMentionUsers === "function" && state.mentionUsers) renderMentionUsers();
  } catch (_) {}
  try {
    if (typeof renderRunManager === "function" && state.modelRuns?.length) renderRunManager();
  } catch (_) {}
  try {
    if (typeof updatePredictionBatchCount === "function") updatePredictionBatchCount();
  } catch (_) {}
  try {
    if (typeof renderGatewayProviders === "function") renderGatewayProviders();
  } catch (_) {}
  try {
    if (typeof renderGatewayModels === "function") renderGatewayModels();
  } catch (_) {}
  try {
    if (typeof applyColorTheme === "function") {
      applyColorTheme(state.colorTheme, { persist: false });
    }
  } catch (_) {}
  // Re-apply open detail/review form if mounted.
  try {
    if (state.selectedCase && typeof syncExpectedOutputFromTags === "function") {
      syncExpectedOutputFromTags();
    }
  } catch (_) {}
}

function normalizedAnalysisComparisonStatus(value, fallback = "all") {
  const normalized = String(value || "").trim().toLowerCase();
  return ANALYSIS_COMPARISON_STATUSES.includes(normalized) ? normalized : fallback;
}

function normalizedReviewComparisonStatus(value, fallback = "all") {
  const normalized = String(value || "").trim().toLowerCase();
  return REVIEW_COMPARISON_STATUSES.includes(normalized) ? normalized : fallback;
}

function parseComparisonStatuses(value, fallback = []) {
  const values = parseFilterList(value).filter((item) =>
    ["match", "mismatch", "none"].includes(item)
  );
  if (values.length) return values;
  if (Array.isArray(fallback)) return fallback.filter((item) =>
    ["match", "mismatch", "none"].includes(item)
  );
  const single = normalizedReviewComparisonStatus(fallback, "");
  return single && single !== "all" ? [single] : [];
}

function comparisonStatusParam(values) {
  const list = parseComparisonStatuses(values);
  if (!list.length || list.length === 3) return "all";
  return list.join(",");
}

function setReviewComparisonStatus(
  comparisonStatus,
  { hasRun = Boolean($("#modelRunFilter")?.value) } = {}
) {
  let nextValues = parseComparisonStatuses(comparisonStatus);
  if (!hasRun) nextValues = [];
  const nextStatus = comparisonStatusParam(nextValues);
  state.reviewComparisonStatus = nextStatus;
  state.failureOnly = nextStatus === "mismatch";
  const root = $("#comparisonFilter");
  if (root) {
    root.classList.toggle("is-disabled", !hasRun);
    root.querySelector(".multi-filter-trigger")?.toggleAttribute("disabled", !hasRun);
    if (root.matches?.("select")) {
      root.disabled = !hasRun;
      root.value = nextStatus === "all" ? "all" : nextValues[0] || "all";
    } else {
      setMultiFilterValues(root, nextValues);
      if (!hasRun) setMultiFilterValues(root, []);
    }
  }
  return nextStatus;
}

function selectedReviewComparisonStatus() {
  const runId = $("#modelRunFilter")?.value || state.selectedRunId;
  if (!runId) return "all";
  const root = $("#comparisonFilter");
  if (!root) {
    return comparisonStatusParam(
      state.reviewComparisonStatus || (state.failureOnly ? "mismatch" : "all")
    );
  }
  // An existing filter with no checked values is an explicit "全部结果"
  // selection (for example after clicking 清除).  Do not revive the previous
  // MISMATCH state as a fallback.
  return comparisonStatusParam(getMultiFilterValues(root));
}

function routeReviewComparisonStatus(params) {
  const requested = String(params.get("comparison") || "").trim().toLowerCase();
  if (!requested) {
    if (params.get("failure") === "1") return "mismatch";
    // A direct Run URL without an explicit comparison keeps the Review page's
    // established MISMATCH default.  The caller can request all/NONE through
    // an explicit comparison query parameter.
    return null;
  }
  const values = parseComparisonStatuses(requested);
  if (values.length) return comparisonStatusParam(values);
  if (REVIEW_COMPARISON_STATUSES.includes(requested)) return requested;
  if (params.get("failure") === "1") return "mismatch";
  return null;
}

function routeAnalysisComparisonStatus(params) {
  const requested = String(params.get("comparison") || "").trim().toLowerCase();
  if (!requested) {
    if (params.get("failure") === "1") return "mismatch";
    // Match Review default: a Run deep-link without comparison keeps MISMATCH.
    return params.has("run") && params.get("run") !== "none" ? "mismatch" : null;
  }
  const values = parseComparisonStatuses(requested);
  if (values.length) return comparisonStatusParam(values);
  if (ANALYSIS_COMPARISON_STATUSES.includes(requested)) return requested;
  if (params.get("failure") === "1") return "mismatch";
  return params.has("run") ? "all" : null;
}

function normalizedReviewRouteFilters(params) {
  const gtLabel = params.get("gt") || "";
  const modelLabel = params.get("model_label") || params.get("annotation") || "";
  const reviewStatus = parseFilterList(params.get("status")).filter((value) =>
    ["pending", "reviewed", "needs_gt_review"].includes(value)
  );
  const rawPage = Number.parseInt(params.get("page") || "1", 10);
  const rawPageSize = Number.parseInt(
    params.get("page_size") || String(DEFAULT_CASE_PAGE_SIZE),
    10
  );
  const exclusionValue = String(params.get("exclusion") || "all").trim().toLowerCase();
  const exclusion = ["included", "excluded"].includes(exclusionValue)
    ? exclusionValue
    : "all";
  return {
    search: params.get("q") || "",
    gtLabel: parseFilterList(params.get("gt") || gtLabel).filter((value) =>
      LABELS.includes(value)
    ),
    modelLabel: parseFilterList(modelLabel).filter((value) =>
      MODEL_LABELS.includes(value)
    ),
    annotationAuthor: parseFilterList(params.get("reviewer")),
    reviewStatus,
    workAssignee: parseFilterList(
      params.get("work_assignee") || params.get("assignee") || ""
    ),
    exclusion,
    clusterKey: params.get("evidence") || "",
    casePage: Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 1,
    casePageSize: CASE_PAGE_SIZES.includes(rawPageSize)
      ? rawPageSize
      : DEFAULT_CASE_PAGE_SIZE,
  };
}

function normalizedAnalysisRouteFilters(params) {
  const rawPage = Number.parseInt(params.get("page") || "1", 10);
  const rawPageSize = Number.parseInt(params.get("page_size") || "", 10);
  const statuses = parseFilterList(params.get("status")).filter((value) =>
    ["pending", "reviewed", "needs_gt_review"].includes(value)
  );
  const gtLabels = parseFilterList(params.get("gt")).filter((value) =>
    LABELS.includes(value)
  );
  const modelLabels = parseFilterList(
    params.get("model_label") || params.get("annotation") || ""
  ).filter((value) => MODEL_LABELS.includes(value));
  const exclusionValue = String(params.get("exclusion") || "all").trim().toLowerCase();
  const exclusion = ["included", "excluded"].includes(exclusionValue)
    ? exclusionValue
    : "all";
  return {
    search: params.get("q") || "",
    gtLabel: gtLabels,
    modelLabel: modelLabels,
    annotationAuthor: parseFilterList(params.get("reviewer")),
    reviewStatus: statuses,
    missingEvidence: parseFilterList(params.get("evidence")),
    sceneTag: parseFilterList(params.get("scene_tag")),
    triggerTag: parseFilterList(params.get("trigger_tag")),
    egressTag: parseFilterList(params.get("egress_tag")),
    exclusion,
    legacyTag: params.get("tag") || "",
    comparisonStatus: routeAnalysisComparisonStatus(params),
    page: Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 1,
    pageSize: CASE_PAGE_SIZES.includes(rawPageSize) ? rawPageSize : DEFAULT_CASE_PAGE_SIZE,
  };
}

function normalizedTrailUpdateRouteFilters(params) {
  const rawPage = Number.parseInt(params.get("page") || "1", 10);
  const rawPageSize = Number.parseInt(params.get("page_size") || "", 10);
  return {
    search: params.get("q") || "",
    gtLabel: parseFilterList(params.get("gt")).filter((value) => LABELS.includes(value)),
    modelLabel: parseFilterList(params.get("model_label") || params.get("annotation") || ""),
    annotationAuthor: parseFilterList(params.get("reviewer")),
    reviewStatus: parseFilterList(params.get("review_status")).filter((value) =>
      ["pending", "reviewed", "needs_gt_review"].includes(value)
    ),
    trailStatus: parseFilterList(params.get("trail_status")).filter((value) =>
      ["querying", "synced", "pending", "not_found", "query_failed", "not_checked"].includes(value)
    ),
    page: Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 1,
    pageSize: CASE_PAGE_SIZES.includes(rawPageSize) ? rawPageSize : DEFAULT_CASE_PAGE_SIZE,
  };
}

function normalizedRunComparisonRouteFilters(params) {
  const transition = String(params.get("transition") || "ALL").toUpperCase();
  const gtLabel = String(params.get("gt") || "ALL");
  const baselineLabel = String(params.get("baseline_label") || "ALL");
  const candidateLabel = String(params.get("candidate_label") || "ALL");
  const labelChange = String(params.get("label_change") || "ALL").toUpperCase();
  const rawPage = Number.parseInt(params.get("page") || "1", 10);
  const rawPageSize = Number.parseInt(params.get("page_size") || "10", 10);
  return {
    baselineRunId: params.get("baseline_run") || params.get("baseline") || "",
    candidateRunId: params.get("candidate_run") || params.get("new") || "",
    transition: ["ALL", "P2P", "P2F", "F2P", "F2F"].includes(transition) ? transition : "ALL",
    gtLabel: ["ALL", ...LABELS].includes(gtLabel) ? gtLabel : "ALL",
    baselineLabel: ["ALL", ...MODEL_LABELS, "NONE"].includes(baselineLabel) ? baselineLabel : "ALL",
    candidateLabel: ["ALL", ...MODEL_LABELS, "NONE"].includes(candidateLabel) ? candidateLabel : "ALL",
    labelChange: ["ALL", "CHANGED", "UNCHANGED"].includes(labelChange) ? labelChange : "ALL",
    search: String(params.get("q") || "").slice(0, 128),
    page: Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 1,
    pageSize: CASE_PAGE_SIZES.includes(rawPageSize) ? rawPageSize : 10,
  };
}

function parsePageRoute() {
  const pathname = stripBasePath(window.location.pathname);
  const match = Object.entries(PAGE_ROUTES).find(([, config]) => config.path === pathname);
  const params = new URLSearchParams(window.location.search);
  const legacyHash = decodeURIComponent(window.location.hash.slice(1));
  const issueIds = params
    .getAll("issue")
    .filter((issueId) => /^[A-Za-z0-9_-]{3,128}$/.test(issueId));
  const reviewIssueIds = typeof parseIssueIdsInput === "function"
    ? parseIssueIdsInput(params.get("issue_ids") || "").ids
    : String(params.get("issue_ids") || "")
        .split(/[\s,，、;；]+/)
        .map((value) => value.trim())
        .filter((value, index, values) => /^[A-Za-z0-9_-]{3,128}$/.test(value) && values.indexOf(value) === index);
  const legacyImport = pathname === "/import";
  const reviewFilters = normalizedReviewRouteFilters(params);
  return {
    page:
      match?.[0] ||
      (pathname === "/inference"
        ? "prediction"
        : legacyImport
          ? "runs"
          : "review"),
    issue:
      issueIds[0] ||
      (/^[A-Za-z0-9_-]{3,128}$/.test(legacyHash) ? legacyHash : ""),
    issues: issueIds,
    reviewIssueIds,
    source: params.get("source") || "",
    runId: params.get("run") || "",
    openComments: params.get("comments") === "1",
    commentId: Number.parseInt(params.get("comment") || "0", 10) || 0,
    comparisonStatus: routeReviewComparisonStatus(params),
    failureOnly: params.has("failure") ? params.get("failure") === "1" : params.has("run") ? false : null,
    ...reviewFilters,
    analysisFilters: normalizedAnalysisRouteFilters(params),
    trailUpdateFilters: normalizedTrailUpdateRouteFilters(params),
    comparisonFilters: normalizedRunComparisonRouteFilters(params),
    intentDatasetId: params.get("dataset") || "",
    intentDatasetIds: params.getAll("dataset").map((value) => String(value || "").trim()).filter(Boolean),
    intentCaseId: params.get("case") || "",
    intentOffsetMs: Number.parseInt(params.get("t") || "", 10),
    intentAssignees: params.has("assignee") ? parseFilterList(params.get("assignee") || "") : null,
    intentExperimentId: params.get("experiment") || "",
    intentSummaryOwners: params.getAll("owner").filter((value) => /^[A-Za-z0-9._@-]{1,128}$/.test(value)),
    intentSummaryPage: Math.max(1, Number.parseInt(params.get("page") || "1", 10) || 1),
    intentSummaryPageSize: [10, 20, 50, 100].includes(Number.parseInt(params.get("page_size") || "20", 10))
      ? Number.parseInt(params.get("page_size") || "20", 10) : 20,
    intentSummaryAxis: ["routing", "lane_change"].includes(params.get("axis")) ? params.get("axis") : "all",
    intentSummaryCommentQuery: (params.get("q") || "").trim().slice(0, 80),
    // Issue / GT 上传已从页面移除；旧链接统一落到安全的模型结果导入区。
    importKind:
      params.get("import") === "model" ||
      params.get("kind") === "model" ||
      params.has("import") ||
      params.has("kind") ||
      legacyImport
        ? "model"
        : "",
    legacyRoute: legacyImport || pathname === "/inference" || Boolean(legacyHash),
  };
}

function currentReviewRouteOptions(overrides = {}) {
  return {
    issue: state.selectedId,
    runId: state.selectedRunId,
    comparisonStatus: state.reviewComparisonStatus,
    failureOnly: state.failureOnly,
    search: $("#searchInput")?.value.trim() || "",
    issueIds: [...(state.reviewIssueIds || [])],
    gtLabel: getMultiFilterValues($("#gtFilter")),
    modelLabel: getMultiFilterValues($("#annotationFilter")),
    annotationAuthor:
      typeof reviewerFilterSelection === "function"
        ? reviewerFilterSelection("review")
        : getMultiFilterValues($("#reviewerFilter")),
    reviewStatus: getMultiFilterValues($("#reviewStatusFilter")),
    workAssignee:
      typeof workAssigneeFilterSelection === "function"
        ? workAssigneeFilterSelection()
        : getMultiFilterValues($("#workAssigneeFilter")),
    exclusion:
      typeof selectedReviewExclusionFilter === "function"
        ? selectedReviewExclusionFilter()
        : "all",
    clusterKey: state.clusterKey,
    casePage: state.casePage,
    casePageSize: state.casePageSize,
    ...overrides,
  };
}

function applyReviewRouteControls(route) {
  if (!route) return;
  if ($("#searchInput")) $("#searchInput").value = route.search || "";
  state.reviewIssueIds = Array.isArray(route.reviewIssueIds)
    ? [...new Set(route.reviewIssueIds.filter((value) => /^[A-Za-z0-9_-]{3,128}$/.test(String(value))))]
    : [];
  if ($("#issueQueryInput")) $("#issueQueryInput").value = state.reviewIssueIds.join("\n");
  if (typeof updateIssueQueryButton === "function") updateIssueQueryButton();
  setMultiFilterValues($("#gtFilter"), route.gtLabel);
  setMultiFilterValues($("#annotationFilter"), route.modelLabel);
  setMultiFilterValues($("#workAssigneeFilter"), route.workAssignee);
  setMultiFilterValues($("#reviewerFilter"), route.annotationAuthor);
  setMultiFilterValues($("#reviewStatusFilter"), route.reviewStatus);
  setMultiFilterValues(
    $("#reviewExclusionFilter"),
    route.exclusion && route.exclusion !== "all" ? [route.exclusion] : []
  );
  state.clusterKey = route.clusterKey || "";
  state.casePage = Math.max(1, Number(route.casePage) || 1);
  state.casePageSize = CASE_PAGE_SIZES.includes(Number(route.casePageSize))
    ? Number(route.casePageSize)
    : DEFAULT_CASE_PAGE_SIZE;
  if ($("#casePageSize")) $("#casePageSize").value = String(state.casePageSize);
  if (route.comparisonStatus !== null && route.comparisonStatus !== undefined) {
    state.reviewComparisonStatus = comparisonStatusParam(route.comparisonStatus);
  }
  setReviewComparisonStatus(state.reviewComparisonStatus, {
    hasRun: Boolean(state.selectedRunId || $("#modelRunFilter")?.value),
  });
}

function currentAnalysisRouteOptions(overrides = {}) {
  return {
    runId: state.selectedRunId,
    comparisonStatus: state.reviewAnalysis.comparisonStatus,
    search: $("#analysisSearchInput")?.value.trim() || "",
    gtLabel: getMultiFilterValues($("#analysisGtFilter")),
    modelLabel: getMultiFilterValues($("#analysisModelLabelFilter")),
    annotationAuthor:
      typeof reviewerFilterSelection === "function"
        ? reviewerFilterSelection("analysis")
        : getMultiFilterValues($("#analysisReviewerFilter")),
    reviewStatus: getMultiFilterValues($("#analysisStatusFilter")),
    missingEvidence: getMultiFilterValues($("#analysisEvidenceFilter")),
    sceneTag: getMultiFilterValues($("#analysisSceneFilter")),
    triggerTag: getMultiFilterValues($("#analysisTriggerFilter")),
    egressTag: getMultiFilterValues($("#analysisEgressFilter")),
    exclusion:
      typeof selectedAnalysisExclusionFilter === "function"
        ? selectedAnalysisExclusionFilter()
        : "all",
    page: state.reviewAnalysis.page,
    pageSize: state.reviewAnalysis.pageSize,
    ...overrides,
  };
}

function applyAnalysisRouteControls(route) {
  const filters = route?.analysisFilters || route || {};
  if ($("#analysisSearchInput")) $("#analysisSearchInput").value = filters.search || "";
  setMultiFilterValues($("#analysisGtFilter"), filters.gtLabel);
  setMultiFilterValues($("#analysisModelLabelFilter"), filters.modelLabel);
  setMultiFilterValues($("#analysisStatusFilter"), filters.reviewStatus);
  setMultiFilterValues($("#analysisReviewerFilter"), filters.annotationAuthor);
  setMultiFilterValues($("#analysisEvidenceFilter"), filters.missingEvidence);
  const catalog = state.config?.review_tag_catalog || [];
  const legacyTag = filters.legacyTag || "";
  const legacyItem = catalog.find((item) => item.key === legacyTag);
  const sceneTag = parseFilterList(filters.sceneTag);
  const triggerTag = parseFilterList(filters.triggerTag);
  const egressTag = parseFilterList(filters.egressTag);
  if (legacyItem?.section === "scene" && !sceneTag.length) sceneTag.push(legacyTag);
  if (legacyItem?.section === "interaction_decision" && !triggerTag.length) {
    triggerTag.push(legacyTag);
  }
  if (legacyItem?.section === "egress" && !egressTag.length) egressTag.push(legacyTag);
  setMultiFilterValues($("#analysisSceneFilter"), sceneTag);
  setMultiFilterValues($("#analysisTriggerFilter"), triggerTag);
  setMultiFilterValues($("#analysisEgressFilter"), egressTag);
  setMultiFilterValues(
    $("#analysisExclusionFilter"),
    filters.exclusion && filters.exclusion !== "all" ? [filters.exclusion] : []
  );
  const requestedComparison =
    filters.comparisonStatus ||
    (state.failureOnly && state.selectedRunId
      ? "mismatch"
      : state.reviewAnalysis.comparisonStatus);
  setAnalysisComparisonStatus(requestedComparison, {
    hasRun: Boolean($("#analysisRunFilter")?.value),
  });
  state.reviewAnalysis.page = Math.max(1, Number(filters.page) || 1);
  state.reviewAnalysis.pageSize = CASE_PAGE_SIZES.includes(Number(filters.pageSize))
    ? Number(filters.pageSize)
    : DEFAULT_CASE_PAGE_SIZE;
  if ($("#analysisPageSize")) $("#analysisPageSize").value = String(state.reviewAnalysis.pageSize);
}

function pageUrl(page, options = {}) {
  const config = PAGE_ROUTES[page] || PAGE_ROUTES.review;
  const url = new URL(withBase(config.path), window.location.origin);
  if (page === "review") {
    const review = currentReviewRouteOptions(options);
    const issueId = review.issue;
    const runId = review.runId;
    const comparisonStatus = comparisonStatusParam(
      review.comparisonStatus || (review.failureOnly ? "mismatch" : "all")
    );
    if (issueId) url.searchParams.set("issue", issueId);
    if (runId) url.searchParams.set("run", runId);
    // Once the user has a Run overlay, persist even the explicit "all"
    // selection.  Omitting it is reserved for first-entry URLs, where the
    // product default remains MISMATCH.
    if (runId) {
      url.searchParams.set("comparison", comparisonStatus);
    }
    if (review.search) url.searchParams.set("q", review.search);
    const issueIds = (review.issueIds || []).filter((value) => /^[A-Za-z0-9_-]{3,128}$/.test(String(value)));
    if (issueIds.length) url.searchParams.set("issue_ids", issueIds.join(","));
    const gt = joinFilterList(review.gtLabel);
    const modelLabel = joinFilterList(review.modelLabel);
    const reviewer = joinFilterList(review.annotationAuthor);
    const status = joinFilterList(review.reviewStatus);
    const assignee = joinFilterList(review.workAssignee);
    if (gt) url.searchParams.set("gt", gt);
    if (modelLabel) url.searchParams.set("model_label", modelLabel);
    if (reviewer) url.searchParams.set("reviewer", reviewer);
    if (status) url.searchParams.set("status", status);
    if (assignee) url.searchParams.set("work_assignee", assignee);
    if (review.exclusion && review.exclusion !== "all") {
      url.searchParams.set("exclusion", review.exclusion);
    }
    if (review.clusterKey) url.searchParams.set("evidence", review.clusterKey);
    if (Number(review.casePage) > 1) url.searchParams.set("page", String(review.casePage));
    if (Number(review.casePageSize) !== DEFAULT_CASE_PAGE_SIZE) {
      url.searchParams.set("page_size", String(review.casePageSize));
    }
  }
  if (page === "analysis") {
    const analysis = currentAnalysisRouteOptions(options);
    url.searchParams.set("run", analysis.runId || "none");
    url.searchParams.set(
      "comparison",
      analysis.runId
        ? comparisonStatusParam(analysis.comparisonStatus || "all")
        : "all"
    );
    if (analysis.search) url.searchParams.set("q", analysis.search);
    const gt = joinFilterList(analysis.gtLabel);
    const modelLabel = joinFilterList(analysis.modelLabel);
    const reviewer = joinFilterList(analysis.annotationAuthor);
    const status = joinFilterList(analysis.reviewStatus);
    const evidence = joinFilterList(analysis.missingEvidence);
    const sceneTag = joinFilterList(analysis.sceneTag);
    const triggerTag = joinFilterList(analysis.triggerTag);
    const egressTag = joinFilterList(analysis.egressTag);
    if (gt) url.searchParams.set("gt", gt);
    if (modelLabel) url.searchParams.set("model_label", modelLabel);
    if (reviewer) url.searchParams.set("reviewer", reviewer);
    if (status) url.searchParams.set("status", status);
    if (evidence) url.searchParams.set("evidence", evidence);
    if (sceneTag) url.searchParams.set("scene_tag", sceneTag);
    if (triggerTag) url.searchParams.set("trigger_tag", triggerTag);
    if (egressTag) url.searchParams.set("egress_tag", egressTag);
    if (analysis.exclusion && analysis.exclusion !== "all") {
      url.searchParams.set("exclusion", analysis.exclusion);
    }
    if (Number(analysis.page) > 1) url.searchParams.set("page", String(analysis.page));
    if (Number(analysis.pageSize) !== DEFAULT_CASE_PAGE_SIZE) {
      url.searchParams.set("page_size", String(analysis.pageSize));
    }
  }
  if (page === "trail-update") {
    const trail = typeof currentTrailUpdateRouteOptions === "function"
      ? currentTrailUpdateRouteOptions(options)
      : options;
    const runId = trail.runId ?? state.trailUpdate?.runId ?? state.selectedRunId;
    if (runId) url.searchParams.set("run", runId);
    if (trail.search) url.searchParams.set("q", trail.search);
    const gt = joinFilterList(trail.gtLabel);
    const modelLabel = joinFilterList(trail.modelLabel);
    const reviewer = joinFilterList(trail.annotationAuthor);
    const reviewStatus = joinFilterList(trail.reviewStatus);
    const trailStatus = joinFilterList(trail.trailStatus);
    if (gt) url.searchParams.set("gt", gt);
    if (modelLabel) url.searchParams.set("model_label", modelLabel);
    if (reviewer) url.searchParams.set("reviewer", reviewer);
    if (reviewStatus) url.searchParams.set("review_status", reviewStatus);
    if (trailStatus) url.searchParams.set("trail_status", trailStatus);
    if (Number(trail.page) > 1) url.searchParams.set("page", String(trail.page));
    if (Number(trail.pageSize) !== DEFAULT_CASE_PAGE_SIZE) {
      url.searchParams.set("page_size", String(trail.pageSize));
    }
  }
  if (page === "prediction") {
    const issueIds = options.issues ?? (options.issue ? [options.issue] : []);
    [...new Set(issueIds)].forEach((issueId) => {
      if (/^[A-Za-z0-9_-]{3,128}$/.test(issueId)) url.searchParams.append("issue", issueId);
    });
    if (options.source) url.searchParams.set("source", options.source);
  }
  if (page === "runs" && options.importKind) {
    url.searchParams.set("import", "model");
  }
  if (page === "comparison") {
    const comparison = typeof runComparisonRouteOptions === "function"
      ? runComparisonRouteOptions(options)
      : options;
    if (comparison.baselineRunId) url.searchParams.set("baseline_run", comparison.baselineRunId);
    if (comparison.candidateRunId) url.searchParams.set("candidate_run", comparison.candidateRunId);
    if (comparison.transition && comparison.transition !== "ALL") {
      url.searchParams.set("transition", comparison.transition);
    }
    if (comparison.gtLabel && comparison.gtLabel !== "ALL") {
      url.searchParams.set("gt", comparison.gtLabel);
    }
    if (comparison.baselineLabel && comparison.baselineLabel !== "ALL") {
      url.searchParams.set("baseline_label", comparison.baselineLabel);
    }
    if (comparison.candidateLabel && comparison.candidateLabel !== "ALL") {
      url.searchParams.set("candidate_label", comparison.candidateLabel);
    }
    if (comparison.labelChange && comparison.labelChange !== "ALL") {
      url.searchParams.set("label_change", comparison.labelChange);
    }
    if (comparison.search) url.searchParams.set("q", comparison.search);
    if (Number(comparison.page) > 1) url.searchParams.set("page", String(comparison.page));
    if (Number(comparison.pageSize) !== 10) {
      url.searchParams.set("page_size", String(comparison.pageSize));
    }
  }
  if (page === "intent") {
    const intent = typeof intentRouteOptions === "function"
      ? intentRouteOptions(options)
      : options;
    const intentDatasetIds = parseFilterList(intent.datasetIds || intent.datasetId);
    intentDatasetIds.forEach((datasetId) => url.searchParams.append("dataset", datasetId));
    if (intent.caseId) url.searchParams.set("case", intent.caseId);
    if (intent.assignees?.length) url.searchParams.set("assignee", intent.assignees.join(","));
    if (intent.experimentId) url.searchParams.set("experiment", intent.experimentId);
    if (intent.offsetMs !== null && intent.offsetMs !== "" && Number.isFinite(Number(intent.offsetMs))) {
      url.searchParams.set("t", String(Number(intent.offsetMs)));
    }
    return `${url.pathname}${url.search}`;
  }
  // Persist multi-baseline selection for shareable URLs on all pages.
  const baselineValue =
    options.baselines != null
      ? normalizeBaselineIds(options.baselines).join(",")
      : selectedBaselineQueryValue();
  const defaults = defaultBaselineIdsFromConfig().join(",");
  if (baselineValue && baselineValue !== defaults) {
    url.searchParams.set("baselines", baselineValue);
  } else if (baselineValue && baselineValue.split(",").length > 1) {
    url.searchParams.set("baselines", baselineValue);
  } else if (baselineValue && baselineValue !== "0508") {
    url.searchParams.set("baselines", baselineValue);
  }
  return `${url.pathname}${url.search}`;
}

function setReviewView(issueId = "") {
  const gallery = $("#reviewGalleryView");
  const detail = $("#reviewDetailView");
  if (!gallery || !detail) return;
  const showingDetail = Boolean(issueId);
  gallery.classList.toggle("hidden", showingDetail);
  detail.classList.toggle("hidden", !showingDetail);
  $("#reviewPage")?.classList.toggle("is-detail", showingDetail);
  if (!showingDetail) {
    $("#detailHeroMedia")?.querySelector("video")?.pause();
    closeDialog("mediaDialog");
    window.requestAnimationFrame(() => {
      window.scrollTo({ top: state.galleryScrollY, behavior: "auto" });
    });
  }
}

function showPage(
  page,
  {
    historyMode = "",
    issue = "",
    issues = [],
    source = "",
    runId = "",
    importKind = "",
    runSourceTab = "",
    restoreRoute = false,
    loadPageData = true,
    intentDatasetId = "",
    intentDatasetIds = [],
    intentCaseId = "",
    intentOffsetMs = null,
    intentAssignees = null,
    intentExperimentId = "",
  } = {}
) {
  const target = PAGE_ROUTES[page] ? page : "review";
  if (target !== "review") $("#detailHeroMedia")?.querySelector("video")?.pause();
  state.activePage = target;
  document.body.dataset.activePage = target;
  document.querySelectorAll("[data-page]").forEach((section) => {
    section.classList.toggle("hidden", section.dataset.page !== target);
  });
  document.querySelectorAll(".sidebar-item[data-page-target]").forEach((item) => {
    const active = item.dataset.pageTarget === target;
    item.classList.toggle("active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  renderPageChrome();
  if (target === "runs") {
    renderRunManager();
    if (importKind) setImportKind(importKind);
    else activateRunSourceTab(runSourceTab || "upload");
  }
  if (target === "comparison") {
    renderRunComparisonSelectors?.();
    renderRunComparison?.();
    if (loadPageData) {
      loadRunComparison({ historyMode: historyMode || "replace" }).catch((error) => showToast(error.message, true));
    }
  }
  if (["intent", "intent-experiments", "intent-summary"].includes(target)) {
    const allowed = state.session.can_view_intent;
    if (!state.session.identity_pending && !allowed) {
      const message = target === "intent"
        ? uiText("当前账号没有意图标注查看权限。", "Intent access is required.")
        : uiText("当前账号没有实验查看权限。", "Intent viewing access is required.");
      showToast(message, true);
      return showPage("review", { historyMode: historyMode || "replace" });
    }
  }
  if (target === "prediction") {
    const issueIds = issues.length ? issues : issue ? [issue] : [];
    ensurePredictionBatchName();
    const issueInput = $("#predictionBatchIssues");
    if (issueInput && (issueIds.length || restoreRoute)) {
      issueInput.value = [...new Set(issueIds)].join(", ");
    }
    if (issueIds.length) {
      state.batchDraftSource = source || (issueIds.length === 1 ? "single" : "");
    } else if (restoreRoute) {
      state.batchDraftSource = "";
    }
    renderPredictionSourceSummary();
    updatePredictionBatchCount();
    renderBatchRuntimeSummary();
    if (loadPageData) {
      loadPredictionConfig().catch((error) => showToast(error.message, true));
      loadPredictionBatches().catch((error) => showToast(error.message, true));
    }
  }
  if (target === "intent" && loadPageData && typeof loadIntentLabeling === "function") {
    loadIntentLabeling({
      datasetId: intentDatasetId,
      datasetIds: intentDatasetIds.length ? intentDatasetIds : null,
      caseId: intentCaseId,
      offsetMs: intentOffsetMs,
      assignees: intentAssignees,
      experimentId: intentExperimentId,
    }).catch((error) => showToast(error.message, true));
  }
  if (target === "intent-experiments" && loadPageData && typeof loadIntentExperimentAdmin === "function") {
    loadIntentExperimentAdmin({
      datasetId: intentDatasetId,
      datasetIds: intentDatasetIds.length ? intentDatasetIds : null,
    }).catch((error) => showToast(error.message, true));
  }
  if (target === "intent-summary" && loadPageData && typeof loadIntentSummary === "function") {
    loadIntentSummary({
      datasetId: intentDatasetId,
      datasetIds: intentDatasetIds.length ? intentDatasetIds : null,
    }).catch((error) => showToast(error.message, true));
  }
  if (target === "analysis") renderAnalysisRunFilter();
  if (target === "trail-update") {
    const trailPage = $("#trailAttributeUpdatePage");
    if (runId) state.trailUpdate.runId = runId;
    if (typeof renderTrailAttributeRunPicker === "function") renderTrailAttributeRunPicker();
    const needsPreview =
      typeof trailAttributePreviewNeedsLoad !== "function" ||
      trailAttributePreviewNeedsLoad(state.trailUpdate?.runId || "");
    if (loadPageData && typeof loadTrailAttributePreview === "function" && needsPreview) {
      // Mark the page as loading only while an actual preview request will be
      // made.  Previously every route re-entry set this flag even when the
      // fresh preview was cached, permanently preserving disabled controls.
      trailPage?.classList.add("is-loading");
      loadTrailAttributePreview().catch((error) => showToast(error.message, true));
    } else if (loadPageData) {
      // Rehydrate cached state synchronously: navigation must not require a
      // second remote Trail check merely to make an already-ready commit
      // button usable again.
      trailPage?.classList.remove("is-loading");
      const cachedPreview = state.trailUpdate?.data || null;
      if (cachedPreview && typeof renderTrailAttributePreview === "function") {
        renderTrailAttributePreview(cachedPreview);
      }
      if (typeof syncTrailAttributeActions === "function") {
        syncTrailAttributeActions(cachedPreview);
      }
    } else {
      // Bootstrap paints the shell before it schedules the one batched Trail
      // query; retain the loading presentation for that short initial gap.
      trailPage?.classList.add("is-loading");
    }
  }
  if (target === "status" && loadPageData) {
    loadStatus().catch((error) => showToast(error.message, true));
  }
  if (target === "users" && loadPageData) {
    loadAccessUsers().catch((error) => showToast(error.message, true));
    loadMentionUsers().catch((error) => showToast(error.message, true));
  }
  if (target === "review") setReviewView(issue);
  const routeOptions =
    target === "review"
      ? currentReviewRouteOptions({ issue })
      : target === "analysis"
        ? currentAnalysisRouteOptions()
        : target === "trail-update"
          ? (typeof currentTrailUpdateRouteOptions === "function"
              ? currentTrailUpdateRouteOptions()
              : { runId: state.trailUpdate?.runId || "" })
        : target === "comparison" && typeof runComparisonRouteOptions === "function"
          ? runComparisonRouteOptions()
        : target === "intent" && typeof intentRouteOptions === "function"
          ? intentRouteOptions({
              datasetId: intentDatasetId,
              caseId: intentCaseId,
              offsetMs: intentOffsetMs,
              assignees: intentAssignees,
              experimentId: intentExperimentId,
            })
          : { issue, issues, source, importKind };
  const historyState = {
    page: target,
    issue: target === "review" ? issue : "",
    openedFromGallery:
      target === "review" &&
      Boolean(issue) &&
      (historyMode === "push" || Boolean(window.history.state?.openedFromGallery)),
  };
  if (historyMode === "push") {
    history.pushState(historyState, "", pageUrl(target, routeOptions));
  }
  if (historyMode === "replace") {
    history.replaceState(historyState, "", pageUrl(target, routeOptions));
  }
  // Instant scroll keeps tab switches snappy; avoid smooth-scroll lag between pages.
  if (target !== "review" || issue) {
    window.scrollTo({ top: 0, behavior: "auto" });
  }
}

function navigatePage(page, options = {}) {
  const previousPage = state.activePage;
  const restoreRoute =
    page === "prediction" &&
    !options.issue &&
    !(Array.isArray(options.issues) && options.issues.length);
  const enteringReviewHome =
    page === "review" && previousPage !== "review" && !options.issue;
  if (enteringReviewHome && state.reviewQueueStale) {
    state.casePage = 1;
  }
  // Keep gallery comparison in sync when returning from reason analysis.
  if (page === "review" && previousPage === "analysis" && state.selectedRunId) {
    state.reviewComparisonStatus = normalizedReviewComparisonStatus(
      state.reviewAnalysis.comparisonStatus,
      state.reviewComparisonStatus || "all"
    );
    setReviewComparisonStatus(state.reviewComparisonStatus, { hasRun: true });
  }
  showPage(page, { ...options, restoreRoute, historyMode: "push" });
  if (page === "analysis") {
    enterAnalysisPage().catch((error) => showToast(error.message, true));
  }
  if (enteringReviewHome) {
    const list = $("#issueList");
    const hasCards = Boolean(list?.querySelector("article[data-issue-id], .issue-grid-empty"));
    const needsReload =
      state.reviewQueueStale ||
      !Array.isArray(state.cases) ||
      !state.cases.length ||
      !hasCards;
    if (needsReload) {
      reloadReviewGallery({ includeOverview: false, historyMode: "" }).catch((error) =>
        showToast(error.message, true)
      );
    } else {
      setReviewView("");
    }
  }
}
