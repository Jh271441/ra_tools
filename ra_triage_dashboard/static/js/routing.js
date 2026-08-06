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
    toggle.setAttribute("aria-label", light ? "切换到深色模式" : "切换到浅色模式");
    toggle.title = light ? "切换到深色模式" : "切换到浅色模式";
  }
  // Pie slice colors are painted into SVG; re-render when theme flips.
  if (state.reviewAnalysis?.data && typeof renderAnalysisClusterPanels === "function") {
    renderAnalysisClusterPanels(state.reviewAnalysis.data, { animatePies: false });
  }
}

function normalizedUiLanguage(value) {
  return String(value || "").toLowerCase() === "en" ? "en" : "zh";
}

function uiText(zh, en) {
  return state.uiLanguage === "en" ? en : zh;
}

function renderPageChrome() {
  const route = PAGE_ROUTES[state.activePage] || PAGE_ROUTES.review;
  const title = state.uiLanguage === "en" ? route.titleEn : route.titleZh;
  $("#pageTitle").textContent = title;
  document.title = `${title} · Manual Triage`;
}

function applyUiLanguage(language, { persist = true } = {}) {
  state.uiLanguage = normalizedUiLanguage(language);
  document.documentElement.dataset.uiLang = state.uiLanguage;
  document.documentElement.lang = state.uiLanguage === "en" ? "en" : "zh-CN";
  if (persist) localStorage.setItem("ra-triage-ui-language", state.uiLanguage);
  const toggle = $("#languageToggleButton");
  if (toggle) {
    const english = state.uiLanguage === "en";
    toggle.textContent = english ? "中文" : "EN";
    toggle.setAttribute("aria-label", english ? "切换到中文" : "切换到 English");
    toggle.title = english ? "切换到中文" : "Switch to English";
  }
  renderPageChrome();
  renderSystemStatus();
  applySidebarState();
  renderSession();
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
  const values = parseComparisonStatuses(
    getMultiFilterValues($("#comparisonFilter")),
    state.reviewComparisonStatus || (state.failureOnly ? "mismatch" : "all")
  );
  return comparisonStatusParam(values);
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
  if (ANALYSIS_COMPARISON_STATUSES.includes(requested)) return requested;
  if (params.get("failure") === "1") return "mismatch";
  return params.has("run") ? "all" : null;
}

function normalizedReviewRouteFilters(params) {
  const gtLabel = params.get("gt") || "";
  const modelLabel = params.get("model_label") || params.get("annotation") || "";
  const rawPage = Number.parseInt(params.get("page") || "1", 10);
  const rawPageSize = Number.parseInt(
    params.get("page_size") || String(DEFAULT_CASE_PAGE_SIZE),
    10
  );
  return {
    search: params.get("q") || "",
    gtLabel: parseFilterList(params.get("gt") || gtLabel).filter((value) =>
      LABELS.includes(value)
    ),
    modelLabel: parseFilterList(modelLabel).filter((value) =>
      LABELS.includes(value)
    ),
    annotationAuthor: parseFilterList(params.get("reviewer")),
    workAssignee: parseFilterList(
      params.get("work_assignee") || params.get("assignee") || ""
    ),
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
  ).filter((value) => LABELS.includes(value));
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
    legacyTag: params.get("tag") || "",
    comparisonStatus: routeAnalysisComparisonStatus(params),
    page: Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 1,
    pageSize: CASE_PAGE_SIZES.includes(rawPageSize) ? rawPageSize : DEFAULT_CASE_PAGE_SIZE,
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
    source: params.get("source") || "",
    runId: params.get("run") || "",
    comparisonStatus: routeReviewComparisonStatus(params),
    failureOnly: params.has("failure") ? params.get("failure") === "1" : params.has("run") ? false : null,
    ...reviewFilters,
    analysisFilters: normalizedAnalysisRouteFilters(params),
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
    gtLabel: getMultiFilterValues($("#gtFilter")),
    modelLabel: getMultiFilterValues($("#annotationFilter")),
    annotationAuthor: getMultiFilterValues($("#reviewerFilter")),
    workAssignee: getMultiFilterValues($("#workAssigneeFilter")),
    clusterKey: state.clusterKey,
    casePage: state.casePage,
    casePageSize: state.casePageSize,
    ...overrides,
  };
}

function applyReviewRouteControls(route) {
  if (!route) return;
  if ($("#searchInput")) $("#searchInput").value = route.search || "";
  setMultiFilterValues($("#gtFilter"), route.gtLabel);
  setMultiFilterValues($("#annotationFilter"), route.modelLabel);
  setMultiFilterValues($("#workAssigneeFilter"), route.workAssignee);
  setMultiFilterValues($("#reviewerFilter"), route.annotationAuthor);
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
    annotationAuthor: getMultiFilterValues($("#analysisReviewerFilter")),
    reviewStatus: getMultiFilterValues($("#analysisStatusFilter")),
    missingEvidence: getMultiFilterValues($("#analysisEvidenceFilter")),
    sceneTag: getMultiFilterValues($("#analysisSceneFilter")),
    triggerTag: getMultiFilterValues($("#analysisTriggerFilter")),
    egressTag: getMultiFilterValues($("#analysisEgressFilter")),
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
    if (runId && comparisonStatus !== "all") {
      url.searchParams.set("comparison", comparisonStatus);
    }
    if (review.search) url.searchParams.set("q", review.search);
    const gt = joinFilterList(review.gtLabel);
    const modelLabel = joinFilterList(review.modelLabel);
    const reviewer = joinFilterList(review.annotationAuthor);
    const assignee = joinFilterList(review.workAssignee);
    if (gt) url.searchParams.set("gt", gt);
    if (modelLabel) url.searchParams.set("model_label", modelLabel);
    if (reviewer) url.searchParams.set("reviewer", reviewer);
    if (assignee) url.searchParams.set("work_assignee", assignee);
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
        ? normalizedAnalysisComparisonStatus(analysis.comparisonStatus)
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
    if (Number(analysis.page) > 1) url.searchParams.set("page", String(analysis.page));
    if (Number(analysis.pageSize) !== DEFAULT_CASE_PAGE_SIZE) {
      url.searchParams.set("page_size", String(analysis.pageSize));
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
    importKind = "",
    runSourceTab = "",
    restoreRoute = false,
    loadPageData = true,
  } = {}
) {
  const target = PAGE_ROUTES[page] ? page : "review";
  if (target !== "review") $("#detailHeroMedia")?.querySelector("video")?.pause();
  state.activePage = target;
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
  if (target === "analysis") renderAnalysisRunFilter();
  if (target === "status" && loadPageData) {
    loadStatus().catch((error) => showToast(error.message, true));
  }
  if (target === "users" && loadPageData) {
    loadAccessUsers().catch((error) => showToast(error.message, true));
  }
  if (target === "review") setReviewView(issue);
  const routeOptions =
    target === "review"
      ? currentReviewRouteOptions({ issue })
      : target === "analysis"
        ? currentAnalysisRouteOptions()
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
