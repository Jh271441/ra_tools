/* ra_triage_dashboard/static/js/bind-bootstrap.js
 * Event binding and bootstrap
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
function bindEvents() {
  bindWorkSplitControls();
  document.querySelectorAll("[data-page-target]").forEach((element) => {
    element.addEventListener("click", (event) => {
      if (
        element.tagName === "A" &&
        (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0)
      ) {
        return;
      }
      event.preventDefault();
      navigatePage(element.dataset.pageTarget);
      closeMobileSidebar();
    });
  });
  $("#filterForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    // Filters auto-apply on change; form submit is treated as reset.
    await resetReviewFilters();
  });
  $("#resetReviewFiltersButton")?.addEventListener("click", () => {
    resetReviewFilters().catch((error) => showToast(error.message, true));
  });
  let reviewSearchTimer = null;
  const scheduleReviewFilterReload = (delay = 0) => {
    if (reviewSearchTimer) window.clearTimeout(reviewSearchTimer);
    reviewSearchTimer = window.setTimeout(() => {
      reviewSearchTimer = null;
      state.reviewIssueIds = [];
      state.casePage = 1;
      reloadReviewGallery({ includeOverview: false, historyMode: "replace" }).catch(
        (error) => showToast(error.message, true)
      );
    }, Math.max(0, Number(delay) || 0));
  };
  $("#searchInput")?.addEventListener("input", () => scheduleReviewFilterReload(280));
  $("#reviewAnalysisFilterForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    state.reviewAnalysis.page = 1;
    try {
      await reloadReviewAnalysis();
    } catch (error) {
      showToast(error.message, true);
    }
  });
  $("#analysisRunFilter").addEventListener("change", () => {
    const runId = $("#analysisRunFilter").value;
    const previouslyHadRun = Boolean(state.selectedRunId);
    const nextStatus = !runId
      ? "all"
      : previouslyHadRun
        ? checkedAnalysisComparisonStatus()
        : "mismatch";
    setAnalysisComparisonStatus(nextStatus, { hasRun: Boolean(runId) });
  });
  ["#analysisRunFilter", "#analysisComparisonFilter"].forEach((selector) => {
    $(selector)?.addEventListener("change", () => scheduleAnalysisFilterReload());
  });
  $("#analysisSearchInput")?.addEventListener("input", () => {
    scheduleAnalysisFilterReload(220);
  });
  document.addEventListener("click", () => closeAllMultiFilters());
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeAllMultiFilters();
      hideAnalysisPieTooltip?.();
    }
  });
  document.addEventListener(
    "scroll",
    (event) => {
      if (!document.querySelector(".multi-filter.is-open")) return;
      const target = event.target;
      if (
        target instanceof Element &&
        target.closest(".multi-filter-panel.is-fixed-dropdown")
      ) {
        return;
      }
      closeAllMultiFilters();
    },
    true
  );
  window.addEventListener("resize", () => closeAllMultiFilters());
  $("#resetReviewAnalysisButton").addEventListener("click", async () => {
    $("#analysisRunFilter").value = "";
    setAnalysisComparisonStatus("all", { hasRun: false });
    [
      "#analysisReviewerFilter",
      "#analysisStatusFilter",
      "#analysisGtFilter",
      "#analysisModelLabelFilter",
      "#analysisEvidenceFilter",
      "#analysisSceneFilter",
      "#analysisTriggerFilter",
      "#analysisEgressFilter",
    ].forEach((selector) => setMultiFilterValues($(selector), []));
    $("#analysisSearchInput").value = "";
    state.reviewAnalysis.page = 1;
    try {
      await reloadReviewAnalysis();
    } catch (error) {
      showToast(error.message, true);
    }
  });
  $("#exportReviewAnalysisCsvButton").addEventListener("click", () => downloadReviewAnalysis("csv"));
  $("#exportReviewAnalysisXlsxButton").addEventListener("click", () => downloadReviewAnalysis("xlsx"));
  $("#analysisPagePrevious").addEventListener("click", () => {
    changeAnalysisPage(-1).catch((error) => showToast(error.message, true));
  });
  $("#analysisPageNext").addEventListener("click", () => {
    changeAnalysisPage(1).catch((error) => showToast(error.message, true));
  });
  $("#analysisPageSize")?.addEventListener("change", (event) => {
    changeAnalysisPageSize(event.target.value).catch((error) => showToast(error.message, true));
  });
  $("#modelRunFilter").addEventListener("change", async () => {
    const previousRunId = state.selectedRunId;
    state.selectedRunId = $("#modelRunFilter").value;
    if (!state.selectedRunId) state.reviewComparisonStatus = "all";
    if (state.selectedRunId && !previousRunId) {
      // Run selection changes the prediction overlay, not the immutable
      // baseline queue.  Keep the established failure-focused default while
      // retaining uncovered baseline Issues for the NONE/全部 filters.
      state.reviewComparisonStatus = "mismatch";
      state.failureOnly = true;
    }
    if (state.selectedRunId) {
      const run = (state.modelRuns || []).find(
        (item) => String(item.id) === String(state.selectedRunId)
      );
      // 单集评测 Run：切换对比时自动勾选对应 GT 数据集。
      if (run) {
        await applyInferredBaselinesFromRun(run, { reason: "run" });
      }
    }
    if (typeof renderReviewCatalogFilters === "function") {
      renderReviewCatalogFilters();
    }
    setReviewComparisonStatus(state.reviewComparisonStatus, {
      hasRun: Boolean(state.selectedRunId),
    });
    renderAnalysisRunFilter();
    renderActiveRun();
    renderRunManager();
    await reloadReviewGallery();
  });
  const clearClusterButton = $("#clearClusterButton");
  if (clearClusterButton) {
    clearClusterButton.addEventListener("click", async () => {
      state.clusterKey = "";
      await reloadReviewGallery({ includeOverview: false });
    });
  }
  $("#casePagePrevious").addEventListener("click", () => {
    changeCasePage(-1).catch((error) => showToast(error.message, true));
  });
  $("#casePageNext").addEventListener("click", () => {
    changeCasePage(1).catch((error) => showToast(error.message, true));
  });
  $("#casePageSize").addEventListener("change", (event) => {
    changeCasePageSize(event.target.value).catch((error) => showToast(error.message, true));
  });
  $("#refreshButton").addEventListener("click", async () => {
    try {
      await refreshAll();
      if (state.activePage === "analysis") {
        await loadReviewReasonAnalysis();
      } else if (state.selectedId) {
        await selectCase(state.selectedId, { updateRoute: false });
      }
      showToast("页面数据已刷新。");
    } catch (error) {
      showToast(error.message, true);
    }
  });
  $("#refreshSystemStatusButton").addEventListener("click", async () => {
    const button = $("#refreshSystemStatusButton");
    button.disabled = true;
    try {
      await loadStatus();
      showToast(uiText("系统状态已刷新。", "System status refreshed."));
    } catch (error) {
      showToast(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
  $("#checkTrailButton").addEventListener("click", () => syncTrail("preview"));
  $("#syncTrailButton").addEventListener("click", () => syncTrail("create"));
  $("#runManagerImportButton").addEventListener("click", () => {
    $("#importResult").classList.add("hidden");
    $("#importResult").textContent = "";
    activateRunSourceTab("upload");
  });
  $("#openAutoTriageImportButton").addEventListener("click", openAutoTriageImport);
  $("#openTrailImportButton").addEventListener("click", () => {
    activateRunSourceTab("trail");
  });
  $("#reviewUploadModelButton").addEventListener("click", () => openRunImport("model"));
  $("#accessUserForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("#accessUserName");
    const username = String(input.value || "").trim().toLowerCase();
    if (!username) return showToast("请输入用户名。", true);
    const submit = event.submitter || event.currentTarget.querySelector("button[type='submit']");
    submit.disabled = true;
    try {
      await saveAccessUser(username, $("#accessUserRole").value);
      input.value = "";
      showToast("用户权限已保存。");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      submit.disabled = false;
    }
  });
  $("#accessUserList").addEventListener("click", async (event) => {
    const row = event.target.closest("[data-access-user]");
    if (!row) return;
    const username = row.dataset.accessUser;
    if (event.target.closest("[data-save-access-user]")) {
      try {
        await saveAccessUser(username, row.querySelector("[data-access-role]").value);
        showToast("用户权限已更新。");
      } catch (error) { showToast(error.message, true); }
    }
    if (event.target.closest("[data-remove-access-user]")) {
      if (!window.confirm(`确认移除 ${username} 的写入权限？`)) return;
      try {
        const result = await api(`/api/access-users/${encodeURIComponent(username)}`, { method: "DELETE" });
        acknowledgeLocalChange(result);
        await loadAccessUsers();
        showToast("该用户已变为只读。");
      } catch (error) { showToast(error.message, true); }
    }
  });
  $("#predictFilteredButton").addEventListener("click", () => {
    const limit = predictionBatchLimit();
    if (state.caseTotal > limit) {
      showToast(
        `当前筛选有 ${state.caseTotal} 个 Issue；单批最多 ${limit} 个，请继续收窄筛选。`,
        true
      );
      return;
    }
    if (state.cases.length !== state.caseTotal) {
      showToast(
        `当前仅加载 ${state.cases.length} / ${state.caseTotal} 个筛选结果，不能创建不完整 Batch。`,
        true
      );
      return;
    }
    openBatchDraft(
      state.cases.map((item) => item.issue_id),
      "filtered"
    );
  });
  $("#refreshRunsButton").addEventListener("click", async () => {
    try {
      await loadRuns();
      await loadOverview();
      showToast("模型 run 列表已刷新。");
    } catch (error) {
      showToast(error.message, true);
    }
  });
  $("#runPersonFilter").addEventListener("change", renderRunManager);
  $("#runKindFilter").addEventListener("change", renderRunManager);
  $("#runSearchInput").addEventListener("input", renderRunManager);
  $("#batchRequesterFilter").addEventListener("change", () => {
    loadPredictionBatches().catch((error) => showToast(error.message, true));
  });
  $("#batchStatusFilter").addEventListener("change", () => {
    loadPredictionBatches().catch((error) => showToast(error.message, true));
  });
  ["#batchModelFilter", "#batchPromptFilter", "#batchInputFilter"].forEach((selector) => {
    $(selector).addEventListener("change", () => {
      loadPredictionBatches().catch((error) => showToast(error.message, true));
    });
  });
  $("#refreshPredictionBatchesButton").addEventListener("click", () => {
    loadPredictionBatches()
      .then(() => showToast("Batch 任务历史已刷新。"))
      .catch((error) => showToast(error.message, true));
  });
  $("#refreshGatewayModelsButton").addEventListener("click", () => {
    const button = $("#refreshGatewayModelsButton");
    button.disabled = true;
    loadGatewayModels({ refresh: true })
      .then(() => showToast("服务器模型目录已刷新。"))
      .catch((error) => showToast(error.message, true))
      .finally(() => {
        button.disabled = false;
      });
  });
  $("#predictionModelSelect").addEventListener("change", () => {
    state.selectedGatewayModelId = $("#predictionModelSelect").value;
    renderGatewayModels();
  });
  $("#predictionPromptSelect").addEventListener("change", loadSelectedPromptTemplate);
  $("#predictionPromptTemplate").addEventListener("input", updatePromptEditorSummary);
  $("#predictionInputProfile").addEventListener("change", applyBatchInputPreset);
  $("#predictionCameraPreset").addEventListener("change", applyCameraFramePreset);
  $("#predictionFrameOffsets").addEventListener("input", () => {
    syncCameraFramePreset();
    renderBatchRuntimeSummary();
  });
  $("#predictionUseRaEvent").addEventListener("change", () => {
    if (!$("#predictionUseRaEvent").checked) $("#predictionUseRaOptions").checked = false;
    renderBatchRuntimeSummary();
  });
  $("#predictionUseRaOptions").addEventListener("change", () => {
    if ($("#predictionUseRaOptions").checked) $("#predictionUseRaEvent").checked = true;
    renderBatchRuntimeSummary();
  });
  $("#predictionUseBev").addEventListener("change", renderBatchRuntimeSummary);
  $("#languageToggleButton").addEventListener("click", () => {
    applyUiLanguage(state.uiLanguage === "en" ? "zh" : "en");
  });
  $("#themeToggleButton").addEventListener("click", () => {
    applyColorTheme(state.colorTheme === "light" ? "dark" : "light");
  });
  $("#sidebarToggle").addEventListener("click", toggleSidebar);
  $("#sidebarBrandToggle").addEventListener("click", toggleSidebar);
  $("#mobileSidebarBackdrop")?.addEventListener("click", closeMobileSidebar);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMobileSidebar();
  });
  const sidebarMedia = typeof window.matchMedia === "function"
    ? window.matchMedia("(max-width: 639px)")
    : null;
  const syncSidebarViewport = () => {
    if (!isMobileSidebarViewport()) state.mobileSidebarOpen = false;
    applySidebarState();
  };
  if (sidebarMedia?.addEventListener) sidebarMedia.addEventListener("change", syncSidebarViewport);
  else if (sidebarMedia?.addListener) sidebarMedia.addListener(syncSidebarViewport);
  document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => closeDialog(button.dataset.close)));
  $("#mediaDialog").addEventListener("close", cleanupMediaDialog);
  $("#raEventSearchInput").addEventListener("input", (event) => {
    renderRaEventRows(state.raEventDialog.events, event.target.value);
  });
  $("#raEventSearchButton").addEventListener("click", () => $("#raEventSearchInput")?.focus());
  $("#raEventDialog").addEventListener("close", () => {
    state.raEventDialog = { issueId: "", events: [], trailUrl: "" };
  });
  $("#importFile").addEventListener("change", () => {
    const filename = $("#importFileName");
    if (filename) filename.textContent = $("#importFile").files[0]?.name || "未选择文件";
  });
  $("#openImportExamplesButton").addEventListener("click", openImportExamples);
  document.querySelectorAll("[data-import-example-format]").forEach((tab) => {
    tab.addEventListener("click", () => renderImportExample(tab.dataset.importExampleFormat));
  });
  $("#copyImportExampleButton").addEventListener("click", () => copyImportExample().catch((error) => showToast(error.message, true)));
  $("#importForm").addEventListener("submit", submitImport);
  $("#autotriageImportForm").addEventListener("submit", submitAutoTriageImport);
  $("#predictionBatchIssues").addEventListener("input", () => {
    state.batchDraftSource = "";
    updatePredictionBatchCount();
    renderPredictionSourceSummary();
  });
  $("#predictionBatchForm").addEventListener("submit", submitPredictionBatch);
  $("#sourcePreviewPrevious").addEventListener("click", () => {
    if (!state.sourcePreview.runId || state.sourcePreview.page <= 1) return;
    loadSourcePreviewPage(state.sourcePreview.runId, state.sourcePreview.page - 1).catch((error) => showToast(error.message, true));
  });
  $("#sourcePreviewNext").addEventListener("click", () => {
    if (!state.sourcePreview.runId || state.sourcePreview.page >= state.sourcePreview.pageCount) return;
    loadSourcePreviewPage(state.sourcePreview.runId, state.sourcePreview.page + 1).catch((error) => showToast(error.message, true));
  });
  $("#mediaPrevButton").addEventListener("click", () => moveMedia(-1));
  $("#mediaNextButton").addEventListener("click", () => moveMedia(1));
  $("#mediaZoomOutButton").addEventListener("click", () => setMediaZoom(state.media.zoom - MEDIA_ZOOM_STEP));
  $("#mediaZoomResetButton").addEventListener("click", () => setMediaZoom(1, { resetScroll: true }));
  $("#mediaZoomInButton").addEventListener("click", () => setMediaZoom(state.media.zoom + MEDIA_ZOOM_STEP));
  $("#mediaOriginalSizeButton").addEventListener("click", showMediaAtOriginalSize);
  $("#mediaFullscreenButton").addEventListener("click", () => toggleMediaFullscreen());
  $("#mediaPreviewImage").addEventListener("load", () => {
    setMediaZoom(state.media.zoom);
  });
  bindMediaPanViewport($("#mediaViewport"));
  document.addEventListener("fullscreenchange", () => {
    updateMediaViewControls();
    window.requestAnimationFrame(updateMediaPanState);
  });
  document.addEventListener("keydown", (event) => {
    if (!$("#mediaDialog").open) {
      const target = event.target instanceof Element ? event.target : null;
      const interactiveTarget = target?.closest("input, textarea, select, button, a, [contenteditable='true']");
      const detailMediaActive =
        state.activePage === "review" &&
        Boolean(state.selectedCase) &&
        Boolean($("#detailHeroMedia")) &&
        !document.querySelector("dialog[open]");
      if (!detailMediaActive || interactiveTarget || event.ctrlKey || event.metaKey || event.altKey) return;
      const activate = (control) => {
        if (!control || control.disabled) return false;
        event.preventDefault();
        control.click();
        return true;
      };
      const key = event.key.toLowerCase();
      if (["b", "c", "v"].includes(key)) {
        const kind = { b: "bev", c: "camera", v: "video" }[key];
        const select = $("#detailMediaKindSelect");
        const option = select?.querySelector(`option[value="${kind}"]`);
        if (select && option && !option.disabled && select.value !== kind) {
          event.preventDefault();
          select.value = kind;
          select.dispatchEvent(new Event("change", { bubbles: true }));
        }
      } else if (key === " " && state.detailMedia.kind === "video") {
        event.preventDefault();
        if (!event.repeat) $("#detailHeroMedia")?.querySelector("[data-video-play]")?.click();
      } else if (key === "arrowleft" || key === "arrowright") {
        const direction = key === "arrowleft" ? -1 : 1;
        const control = state.detailMedia.kind === "video"
          ? $("#detailHeroMedia")?.querySelector(`[data-video-jump="${direction}"]`)
          : $(direction < 0 ? "#detailMediaPreviousButton" : "#detailMediaNextButton");
        activate(control);
      } else if (key === "f") {
        if (!event.repeat) activate($("#detailMediaExpandButton"));
      }
      return;
    }
    if (["ArrowLeft", "ArrowUp"].includes(event.key)) { event.preventDefault(); moveMedia(-1); }
    if (["ArrowRight", "ArrowDown"].includes(event.key)) { event.preventDefault(); moveMedia(1); }
    if (event.key.toLowerCase() === "b") switchMediaKind("bev");
    if (event.key.toLowerCase() === "c") switchMediaKind("camera");
    if (event.key.toLowerCase() === "v") switchMediaKind("video");
    if (event.key === " " && state.media.kind === "video") {
      event.preventDefault();
      $("#mediaVideoStage")?.querySelector("[data-video-play]")?.click();
    }
    if (["+", "="].includes(event.key)) { event.preventDefault(); setMediaZoom(state.media.zoom + MEDIA_ZOOM_STEP); }
    if (["-", "_"].includes(event.key)) { event.preventDefault(); setMediaZoom(state.media.zoom - MEDIA_ZOOM_STEP); }
    if (event.key === "0") {
      event.preventDefault();
      setMediaZoom(1, { resetScroll: true });
    }
    if (event.key.toLowerCase() === "f") { event.preventDefault(); toggleMediaFullscreen(); }
  });
  window.addEventListener("popstate", async () => {
    const route = parsePageRoute();
    if (route.page === "analysis") {
      const previousRunId = state.selectedRunId;
      const previousFailureOnly = state.failureOnly;
      const previousComparisonStatus = state.reviewAnalysis.comparisonStatus;
      const nextRunId =
        route.runId && state.modelRuns.some((run) => run.id === route.runId)
          ? route.runId
          : "";
      const nextComparisonStatus = nextRunId
        ? normalizedAnalysisComparisonStatus(
            route.analysisFilters.comparisonStatus,
            state.config?.default_failure_only ? "mismatch" : "all"
          )
        : "all";
      state.selectedRunId = nextRunId;
      state.reviewAnalysis.comparisonStatus = nextComparisonStatus;
      state.failureOnly = Boolean(
        nextRunId && nextComparisonStatus === "mismatch"
      );
      if (
        previousRunId !== state.selectedRunId ||
        previousFailureOnly !== state.failureOnly ||
        previousComparisonStatus !== state.reviewAnalysis.comparisonStatus
      ) {
        state.reviewQueueStale = true;
      }
      $("#modelRunFilter").value = nextRunId;
      setReviewComparisonStatus(state.reviewComparisonStatus, {
        hasRun: Boolean(nextRunId),
      });
      renderAnalysisRunFilter();
      applyAnalysisRouteControls(route);
      showPage("analysis", { restoreRoute: true });
      renderActiveRun();
      renderRunManager();
      try {
        await enterAnalysisPage({ includeOverview: true });
      } catch (error) {
        showToast(error.message, true);
      }
      return;
    }
    if (route.page !== "review") {
      showPage(route.page, {
        issues: route.issues,
        source: route.source,
        importKind: route.importKind,
        restoreRoute: true,
      });
      return;
    }
    const nextRunId =
      route.runId && state.modelRuns.some((run) => run.id === route.runId)
        ? route.runId
        : "";
    const nextComparisonStatus = nextRunId
      ? normalizedReviewComparisonStatus(
          route.comparisonStatus,
          route.failureOnly ? "mismatch" : "all"
        )
      : "all";
    state.selectedRunId = nextRunId;
    $("#modelRunFilter").value = nextRunId;
    state.reviewComparisonStatus = nextComparisonStatus;
    setReviewComparisonStatus(nextComparisonStatus, {
      hasRun: Boolean(nextRunId),
    });
    applyReviewRouteControls(route);
    renderAnalysisRunFilter();
    renderActiveRun();
    renderRunManager();
    if (!route.issue) {
      if (state.selectedId) clearPendingReviewImages();
      clearDetail({ showGallery: true });
    }
    showPage("review", {
      issue: route.issue,
      restoreRoute: true,
    });
    try {
      await Promise.all([
        loadCases({ keepSelection: true, page: route.casePage }),
        loadClusters(),
        loadOverview(),
      ]);
      if (route.issue) {
        if (route.issue !== state.selectedId || !state.selectedCase) {
          await selectCase(route.issue, { updateRoute: false });
        } else {
          setReviewView(route.issue);
          renderCaseNavigation();
        }
      }
    } catch (error) {
      showToast(error.message, true);
    }
  });
}

async function bootstrap() {
  const initialRoute = parsePageRoute();
  applyColorTheme(
    localStorage.getItem("ra-triage-color-theme") || document.documentElement.dataset.colorTheme,
    { persist: false }
  );
  applyUiLanguage(localStorage.getItem("ra-triage-ui-language") || "zh", { persist: false });
  const savedSidebarState = localStorage.getItem("ra-triage-sidebar-collapsed");
  state.sidebarCollapsed = savedSidebarState === "true";
  applySidebarState();
  markUiReady();
  bindMobileFilterDrawers();
  if (initialRoute.page === "review") applyReviewRouteControls(initialRoute);
  bindEvents();
  updateImportFields();
  showPage(initialRoute.page, {
    historyMode: initialRoute.legacyRoute ? "replace" : "",
    issue: initialRoute.issue,
    issues: initialRoute.issues,
    source: initialRoute.source,
    importKind: initialRoute.importKind,
    restoreRoute: true,
    loadPageData: false,
  });
  const sessionRequest = resolveSessionInBackground();
  try {
    await settleInitialRequests([loadConfig()], "基础配置");
    if (initialRoute.page === "users") {
      await sessionRequest;
    }
    if (initialRoute.page === "users" && !state.session.is_admin) {
      initialRoute.page = "review";
      showToast("用户管理仅对管理员开放。", true);
    }
    const defaultFailureOnly = Boolean(state.config?.default_failure_only);
    state.selectedRunId =
      initialRoute.runId === "none"
        ? ""
        : initialRoute.runId || state.config?.default_model_run_id || "";
    if (initialRoute.page === "analysis") {
      state.reviewAnalysis.comparisonStatus = state.selectedRunId
        ? normalizedAnalysisComparisonStatus(
            initialRoute.analysisFilters.comparisonStatus,
            defaultFailureOnly ? "mismatch" : "all"
          )
        : "all";
      state.failureOnly =
        state.reviewAnalysis.comparisonStatus === "mismatch";
    } else {
      state.reviewComparisonStatus = state.selectedRunId
          ? normalizedReviewComparisonStatus(
            initialRoute.comparisonStatus,
            "mismatch"
          )
        : "all";
      state.failureOnly = state.reviewComparisonStatus === "mismatch";
    }
    await settleInitialRequests(
      [
        loadRuns({
          preferDefault: !initialRoute.runId,
          preserveEmpty: initialRoute.runId === "none",
        }),
        loadReviewers(),
        loadWorkAssignees(),
      ],
      "共享数据"
    );
    setReviewComparisonStatus(state.reviewComparisonStatus, {
      hasRun: Boolean(state.selectedRunId),
    });
    if (initialRoute.page === "review") applyReviewRouteControls(initialRoute);
    if (initialRoute.page === "analysis") applyAnalysisRouteControls(initialRoute);
    const initialPageRequests = [loadOverview()];
    let initialDetailRequest = null;
    if (initialRoute.page === "review") {
      initialPageRequests.push(
        loadCases({
          keepSelection: Boolean(initialRoute.issue),
          page: initialRoute.casePage,
        }),
        loadClusters()
      );
      if (initialRoute.issue) {
        initialDetailRequest = selectCase(initialRoute.issue, { updateRoute: false });
      }
    } else if (initialRoute.page === "status") {
      initialPageRequests.push(loadStatus());
    } else if (initialRoute.page === "users") {
      initialPageRequests.push(loadAccessUsers());
    } else if (initialRoute.page === "prediction") {
      initialPageRequests.push(loadPredictionConfig(), loadPredictionBatches());
    }
    if (initialRoute.page === "analysis") {
      initialPageRequests.push(loadReviewReasonAnalysis());
    }
    const initialPageResults = settleInitialRequests(
      initialPageRequests,
      initialRoute.page === "review" ? "首页" : "页面"
    );
    if (initialDetailRequest) {
      await settleInitialRequests([initialDetailRequest], "问题详情");
    }
    showPage(initialRoute.page, {
      historyMode: "replace",
      issue: initialRoute.issue,
      issues: initialRoute.issues,
      source: initialRoute.source,
      importKind: initialRoute.importKind,
      restoreRoute: true,
      loadPageData: false,
    });
    void initialPageResults;
  } catch (error) {
    showToast(`启动失败：${error.message}`, true);
  }
  startChangePolling();
}

if (document.readyState === "loading") {
  window.addEventListener("DOMContentLoaded", bootstrap, { once: true });
} else {
  bootstrap();
}
